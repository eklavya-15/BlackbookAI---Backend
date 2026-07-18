# BlackbookAI Backend — Interview Preparation Document
---

## 1. Project Overview

### 1.1 Problem it solves

BlackbookAI is a **Retrieval-Augmented Generation (RAG)** backend. Users upload sources in three forms:

- **PDF documents**
- **Raw text**
- **Public URLs** (which the system crawls)

The system parses each source, breaks it into chunks, computes embeddings, and stores them in a vector database. Users then ask questions over selected sources, and the system:

1. Embeds the user query.
2. Retrieves the most relevant chunks from the user’s vector collection.
3. Sends the chunks + conversation history to an LLM.
4. Returns either a full JSON response or an SSE stream.

### 1.2 High-level architecture

```text
                    +-------------------------------+
   Client           |       FastAPI Server          |
   requests         |  /source/*   /chat/*          |
                    |                               |
                    |  +--------+  +-------------+  |
                    |  | ARQ    |  | Background  |  |
                    |  | Queue  |  | Worker      |  |
                    |  | Redis  |  | same process|  |
                    |  +--------+  +-------------+  |
                    +-------------------------------+
                            |      |
                            v      v
                    +-------------------------------+
                    |  Cloudflare R2 (PDF staging)  |
                    |  Qdrant        (vectors)      |
                    |  Redis         (queue/status) |
                    |  OpenAI API    (embed + chat) |
                    +-------------------------------+
```

### 1.3 Main features

| Feature | What it does |
|---|---|
| PDF ingestion | Upload a PDF, stage it in R2, chunk/extract headings/tables/embed, store in Qdrant per user. |
| URL ingestion | Crawl a public URL (Playwright), extract text, chunk, embed. |
| Text ingestion | Accept raw text, chunk, embed directly (no file staging). |
| Source status | Poll Redis for processing progress (`processing`, `completed`, `failed`). |
| Chat (non-stream) | Synchronous `/chat/no-stream` returning final answer + cited sources. |
| Chat (stream) | Server-sent events (SSE) from `/chat` streaming LLM tokens. |
| RAG evaluation | Local CLI / Gradio dashboard to measure retrieval (MRR, nDCG, keyword coverage) and answer quality (accuracy, completeness, relevance) via an LLM-as-a-judge. |

### 1.4 End-to-end request flow (PDF upload → chat)

1. `POST /source/pdf` with `Content-Type: application/pdf` and `x-user-id` header.
2. Server validates MIME type, creates `source_id = uuid5(namespace=DNS, name=filename)`.
3. PDF bytes are uploaded to Cloudflare R2 under `uploads/{source_id}.pdf`.
4. An ARQ job `ingest_source_pdf` is enqueued in Redis.
5. The worker dequeues the job, downloads the PDF temp file, and deletes the R2 object.
6. `chunking_service.py` extracts per-page text (PyMuPDF), per-page tables (pdfplumber), detects headings by font size, and creates ~768-token chunks with 150-token overlap.
7. `embedding_service.py` calls OpenAI `text-embedding-3-small` for each batch and upserts points into Qdrant collection `blackbook_{user_id}`.
8. Job updates Redis status to `completed` (or `failed`).
9. Client polls `GET /source/{source_id}/status` until done.
10. Client calls `POST /chat` with the selected `sourceIds` and question.
11. Server embeds query, searches Qdrant (`top_k=5`) filtered by `source_id IN active_source_ids`.
12. Server formats context, calls OpenAI `gpt-4o-mini` (configurable via `LLM_MODEL`) with conversation history, returns an SSE stream.

---

## 2. Tech Stack

Every dependency is declared in `pyproject.toml` (managed with `uv`).

| Technology | Role in project | Why it is used / alternatives not chosen |
|---|---|---|
| **Python 3.12** | Runtime | Modern typing, `str \| None`, faster Pydantic. |
| **FastAPI** | HTTP framework & OpenAPI | Async-native, automatic Pydantic validation, OpenAPI docs out of the box. Flask/Django are heavier and less async-friendly. |
| **Uvicorn** | ASGI server | Standard FastAPI runner; `uvicorn[standard]` includes WebSocket support for SSE. |
| **Pydantic** | Request/response schemas | Faster validation via Rust core; type-safe models (`ChatRequest`, `TextSourceRequest`). |
| **OpenAI Python SDK** | Embeddings + chat completions | `AsyncOpenAI` supports streaming; the team uses `text-embedding-3-small` and `gpt-4o-mini` for cost/quality balance. |
| **LiteLLM (`litellm.acompletion`)** | Evaluation judge | Unified async LLM interface; lets the evaluator switch to Gemini without rewriting API logic (`model='gemini/...'`). |
| **LangChain Text Splitters** | Recursive chunking | `RecursiveCharacterTextSplitter` gives separator-aware chunking; avoids writing a custom splitter. |
| **Qdrant Cloud (`qdrant-client`)** | Vector database | Managed service, payload filtering, cosine distance search, per-user collection isolation. Alternatives: Pinecone is paid at scale, Weaviate is more complex. |
| **Redis + ARQ** | Task queue | ARQ is async-native, Redis-backed, and lighter than Celery for one worker. Redis also caches per-source status. |
| **Boto3** | S3-compatible object storage client | Cloudflare R2 exposes an S3 API; boto3 is the standard client; avoids pulling Cloudflare-specific tools. |
| **PyMuPDF (`fitz`)** | PDF text + heading extraction | Fast, fine-grained page/block extraction; allows heading detection via font size. |
| **pdfplumber** | PDF table extraction | Stable table extraction pipelines; used alongside PyMuPDF to merge tables with page text. |
| **Playwright + Chromium** | Web crawling | Renders SPAs / JS-driven sites; supports request interception to block heavy assets. `requests` + `bs4` fail on many modern pages; Scrapy adds ops overhead. |
| **APScheduler** | Cron scheduling | Commented-out daily cleanup of Qdrant collections; included for future scheduled jobs. |
| **psutil** | Memory debugging | `ram()` helper prints per-stage RSS during ingestion. |
| **Gradio + pandas** | Evaluation dashboard | Quick local UI for non-engineering users to run tests and view metrics. |
| **uv** | Package manager / build | Very fast lockfile + virtual env; multi-stage Docker builder. |
| **Docker + Fly.io** | Deployment | Dockerfile builds a small distroless-ish image; Fly auto-stops machines to save cost. |

**Note:** There is **no frontend** in this repo, no persistent relational database for users/sources, and no authentication library.

---

## 3. Folder Structure

```text
BlackbookAI - Backend/
+-- .env                           # Secrets (ignored by git, but present in working tree)
+-- .env.example (missing)         # Would document required keys
+-- .gitignore                     # Ignores .venv, .env, uploads, test*.py, evaluation
+-- .python-version                # 3.12
+-- Dockerfile                     # Multi-stage uv build, runs uvicorn on 8080
+-- .dockerignore                  # Excludes .env, fly.toml, uploads, tests, etc.
+-- fly.toml                       # Fly.io: app name, region sin, min_machines_running=0
+-- pyproject.toml                 # Project metadata + dependencies
+-- uv.lock                        # Deterministic lockfile
+-- README.md                      # Empty file in working tree
+-- test.py / test2.py / etc.      # Untracked scratch scripts with hardcoded credentials
|
+-- .github/workflows/fly-deploy.yml   # GitHub Action: deploy on push to main
|
+-- app/
    +-- main.py                    # FastAPI app, lifespan, CORS, router mounting
    +-- api/routes/
    |   +-- chat.py                # /chat (SSE), /chat/no-stream
    |   +-- source.py              # /source/pdf, /url, /text, /status
    +-- core/                      # Shared infrastructure clients
    |   +-- qdrant.py              # Async Qdrant client + collection creation
    |   +-- r2.py                  # boto3 client for Cloudflare R2
    |   +-- ram.py                 # Resident set size helper
    |   +-- redis.py               # RedisSettings + status get/set
    +-- schemas/                   # Pydantic request models
    |   +-- chat.py
    |   +-- source.py
    +-- services/                  # Business logic
    |   +-- chunking_service.py    # PDF/text/URL chunking + metadata
    |   +-- crawler.py             # Old recursive crawler (commented out)
    |   +-- crawler_service.py     # Active BFS Playwright crawler
    |   +-- embedding_service.py   # Batch embedding + upsert into Qdrant
    |   +-- ingestion_service.py   # Orchestrates PDF/text/URL processing
    |   +-- llm_service.py         # OpenAI embeddings + chat completion
    |   +-- retrieval_service.py   # Query vector search + answer orchestration
    +-- workers/
    |   +-- ingestion_worker.py    # ARQ functions linked to ingestion_service
    |   +-- test_worker.py         # Untracked example with hardcoded Redis password
    +-- evaluation/                # Untracked evaluation harness
        +-- eval.py                # MRR/NDCG/answer-judge logic
        +-- evaluator.py           # Gradio dashboard
        +-- test.py                # JSONL loader + TestQuestion schema
        +-- tests.jsonl            # 20 hand-written RAG test cases
```

### Important files at a glance

- **`app/main.py`** — Creates the ARQ Redis pool and starts a background worker inside the same process using `lifespan`.
- **`app/core/qdrant.py`** — Holds `AsyncQdrantClient` and the collection bootstrap (`blackbook_{user_id}`, size 1536, cosine, indexed on `source_id`).
- **`app/core/redis.py`** — `RedisSettings` with fallback defaults and helpers to read/write source status as JSON with a 1-hour TTL.
- **`app/core/r2.py`** — Boto3 client configured for Cloudflare R2.
- **`app/services/ingestion_service.py`** — The heavy-lift orchestration behind the ARQ worker.
- **`app/services/llm_service.py`** — All OpenAI calls + the system prompt with citation guidance.
- **`app/services/crawler_service.py`** — Real web crawler (BFS, semaphore, robots.txt, resource blocking, blocked domains).
- **`Dockerfile`** — Two-stage image: builder installs deps with `uv`, final image copies only `.venv` and `app/`.

---

## 4. Architecture

### 4.1 How components communicate

| Component | Technology | Owned by | How others reach it |
|---|---|---|---|
| Web API | FastAPI/Uvicorn | This process | HTTP on port `8080` |
| Task queue + status cache | Redis (Redis Cloud via URL `REDIS_URL`) | This process (via `arq`) | Redis protocol |
| Vector storage | Qdrant (managed via `QDRANT_URL` + `QDRANT_API_KEY`) | This process (via client) | gRPC/HTTP |
| PDF staging | Cloudflare R2 (S3-compatible, `R2_*` vars) | This process (via boto3) | S3 API |
| Embeddings / LLM | OpenAI API (`OPENAI_API_KEY`) | This process (via `AsyncOpenAI`) | HTTPS |
| Evaluation judge | Gemini via LiteLLM (`GEMINI_API_KEY`) | Evaluation scripts only | HTTPS |

There is **no authentication service**, **no PostgreSQL/MySQL**, and **no external message bus** beyond Redis.

### 4.2 Step-by-step request lifecycle

#### A. PDF upload

```text
Client
   | POST /source/pdf
   | Headers: x-user-id, Content-Type: application/pdf
   | Body: multipart file
   v
FastAPI (app/api/routes/source.py)
   | 1. Validate content_type == application/pdf
   | 2. source_id = uuid5(NAMESPACE_DNS, file.filename)
   | 3. r2_key = uploads/{source_id}.pdf
   | 4. s3.upload_fileobj(..., R2_BUCKET_NAME, r2_key)
   | 5. app.state.arq_pool.enqueue_job('ingest_source_pdf', ...)
   v
Client receives { fileName, userId, sourceId }
   |
   | (async) ARQ Worker (app/workers/ingestion_worker.py)
   v
process_source_pdf (app/services/ingestion_service.py)
   | 1. set_source_status(processing)
   | 2. s3.download_fileobj(bucket, r2_key, NamedTemporaryFile)
   | 3. s3.delete_object(bucket, r2_key)
   | 4. collection_name = init_user_collection(user_id) -> blackbook_{user_id}
   | 5. For each batch from extract_chunks_from_pdf(...):
   |    -> embedding_chunks(batch, collection_name)
   |       a. embed_texts(batch.page_content) -> vectors
   |       b. PointStruct(id=md5(text).hexdigest, vector, payload=text+metadata)
   |       c. client.upsert(collection_name, points)
   | 6. set_source_status(completed) or (failed)
```

#### B. Chat stream

```text
Client
   | POST /chat
   | Body: {userId, sourceIds, query, conversationHistory}
   v
FastAPI (app/api/routes/chat.py)
   | 1. query_embedding = embed_user_query(query)
   | 2. relevant_context = search_relevant_context(query_embedding, userId, sourceIds)
   v
Qdrant query_points(
   collection = blackbook_{user_id},
   query      = query_embedding,
   filter     = source_id IN sourceIds,
   limit      = 5,
   with_payload = True
)
   v
get_llm_response_stream
   | Formats context string from chunks, calls AsyncOpenAI chat.completions.create(..., stream=True)
   | Yields SSE events: data: {content: token}\n\n, then data: [DONE]\n\n
   v
Client streams tokens
```

#### C. URL ingestion

Same as PDF, except `process_source_url`:

1. `crawl_website(url)` (BFS via Playwright -> list of `{url, title, content, status, crawl_time_ms}`).
2. `extract_chunks_from_url_content` only keeps the first 1,000 crawl results.
3. Each page becomes one document passed to `RecursiveCharacterTextSplitter`.
4. Metadata contains `source_name=url`, `source_type=url`, per-page `url` and `title` as `section`.

#### D. Status polling

`GET /source/{source_id}/status` reads Redis key `source:status:{source_id}` using the same ARQ pool (ARQ exposes an async Redis wrapper). JSON TTL = 3600 seconds.

---

## 5. Authentication & Authorization

### 5.1 Actual authentication flow

The system currently has **no real authentication**:

- `x-user-id` is read from a plain HTTP header and used to determine the Qdrant collection name.
- There is no middleware verifying JWTs, API keys, cookies, or sessions.
- CORS is configured as `allow_origins=['*']`.

So the only `auth` is **collection-level isolation** in Qdrant: a user can only query the collection named `blackbook_{user_id}`. Because the header is supplied by the client, this is merely **tenant separation**, not secure user authentication.

### 5.2 Token / cookie handling

- **None.** No JWT, no session cookie, no CSRF token, no refresh token.
- The OpenAI API key and Redis password live in environment variables and are passed directly to clients. They are never rotated or scoped per user.

### 5.3 Security measures that exist

1. `force_https = true` in `fly.toml` so public traffic is redirected to HTTPS.
2. Per-user collection names (`blackbook_{user_id}`) give logical partitioning in Qdrant.
3. `source_id` filters inside each chat request prevent one source from another from being returned **if the Qdrant query is trusted**.
4. Robots.txt parsing and blocked domains/extensions in the crawler.

### 5.4 Common interview questions about this implementation

- *How would you add real authentication?* Add OAuth2 / JWT middleware; map verified `sub` claim to `user_id`; reject missing/invalid tokens before route handlers.
- *What happens if a user changes the `x-user-id` header?* They would access a different user’s collection because the server trusts the header. This is a critical vulnerability.
- *Where are secrets stored?* In `.env` and, in the working tree, hardcoded in `test.py`, `test2.py?`, and `app/workers/test_worker.py`. This is a major security/code-quality issue.
- *Is CORS safe?* `allow_origins=['*']` is convenient for development but should be narrowed to the actual frontend domain and `allow_credentials` should be reconsidered.

---

## 6. Database

### 6.1 Schema / models

No relational database exists. Data is stored in two systems.

#### Qdrant (vector store)

- **Collection name:** `blackbook_{user_id}` — one collection per end user.
- **Vector config:**
  - `size = 1536` (matches `text-embedding-3-small`)
  - `distance = Distance.COSINE`
- **Payload schema (per PointStruct):**

  | Field | Type | Source |
  |---|---|---|
  | `text` | string | chunk text |
  | `source_id` | string | deterministic UUID for the upload |
  | `source_name` | string | filename, URL, or user-supplied title |
  | `source_type` | `'pdf'` \| `'text'` \| `'url'` | ingestion type |
  | `page` | int | extracted PDF page number (PDF only) |
  | `section` | string | heading text or page title |
  | `url` | string | original page URL (URL only) |
  | `user_id` | string | header value (text/URL only, observed in payload) |

- **Point IDs:** deterministically generated as `hashlib.md5(chunk.page_content.encode('utf-8')).hexdigest()`.

#### Redis (job queue + transient status)

- ARQ serializes jobs via Redis lists.
- Status keys: `source:status:{source_id}` with JSON value `{ status: 'processing', stage: 'Chunking', progress: 50 }`.
- TTL = 3600 seconds (set by `set_source_status`).

### 6.2 Relationships

There are **no foreign keys / table joins**. Relationships are implicit:

- A user -> many sources is represented by having many chunks that share `source_id` inside the same Qdrant collection.
- A source -> many chunks is implicit by repeated `source_id` values across multiple PointStruct payloads.
- A chunk -> one source is a payload field.

### 6.3 Indexes

- **Qdrant indexes:**
  - HNSW vector index (automatic per collection).
  - Payload keyword index on `source_id` created in `init_user_collection`.
- **Redis:** keys used as lookup only (no Redis secondary indexes).

### 6.4 Query optimization

- `search_relevant_context` uses a single `query_points` call with a `MatchAny` filter; this avoids scanning unrelated sources.
- The per-user collection limits search space to one tenant at a time (good for isolation and performance).
- No query rewriting, no hybrid (BM25 + vector), no reranker, and no cache of embeddings.

### 6.5 Potential improvements

1. The `source_id` payload index is already created by default.
2. Add a `source_name` keyword index for searching by title.
3. Store source metadata in a relational DB (source title, upload timestamp, owner, status history) so statuses survive Redis TTL expiration.
4. Use UUID4 for point IDs instead of MD5 to prevent chunk-text collisions from silently overwriting chunks.
5. Add a `created_at` payload field for time-aware retrieval / cleanup.

---

## 7. API Design

### 7.1 Route map

| Method | Path | Input | Output |
|---|---|---|---|
| `GET` | `/source/` | none | `{ message: 'Hello World' }` |
| `POST` | `/source/pdf` | `UploadFile` + `x-user-id` header | `{ fileName, userId, sourceId }` |
| `POST` | `/source/url` | `URLSourceRequest` + `x-user-id` header | `{ url, userId, sourceId }` |
| `POST` | `/source/text` | `TextSourceRequest` + `x-user-id` header | `{ text: first_50_chars, userId, sourceId }` |
| `GET` | `/source/{source_id}/status` | source_id path param | status JSON or 404 |
| `POST` | `/chat` | `ChatRequest` | `text/event-stream` (SSE) |
| `POST` | `/chat/no-stream` | `ChatRequest` | JSON `{ answer, sources }` |

### 7.2 Request flow details

**`/source/pdf`**

- `File(...)` ensures a multipart file is present.
- `content_type` is checked; on mismatch an error JSON is returned with HTTP 200 (bad — should be 400 via `HTTPException`).
- `source_id` = `uuid5(NAMESPACE_DNS, file.filename)`.
- R2 upload uses the entire file in memory (`await file.read()`).
- Job enqueued with positional/keyword args for `ingest_source_pdf`.

**`/source/url`**

- `URLSourceRequest` has `type` and `url`; `type` is validated nowhere.
- `source_id` = `uuid5(NAMESPACE_DNS, url)`.
- No URL scheme/allow-list validation; enqueued directly.

**`/source/text`**

- `TextSourceRequest` has `type`, `text`, optional `sourceTitle`.
- Validates `type == 'text'` and returns 200 error JSON on mismatch.
- `source_id` = `uuid5(NAMESPACE_DNS, text[:100])`.
- Enqueues `ingest_source_text` — no staging to R2.

**`/chat` and `/chat/no-stream`**

- `ChatRequest` validates `userId: str`, `sourceIds: list[str]`, `query: str`, `conversationHistory: list[ChatMessage]`.
- `role` is constrained to `Literal['system', 'user', 'assistant']`.
- Stream path: embeds query, retrieves context, returns `StreamingResponse` of SSE data.
- Non-stream path delegates to `retrieve_answer`, which calls `get_llm_response`.

**`/source/{source_id}/status`**

- Reads from Redis directly using the ARQ pool.
- Returns 404 if no status key exists.

### 7.3 Validation

- Pydantic handles type validation, `Literal`, and list structure.
- Manual validations: PDF `content_type`, text `type`.
- **Missing:** URL allow-list, file size limit, user ID format validation, auth token validation, source existence check before chat.

### 7.4 Error handling

- Ingestion exceptions are caught broadly (`Exception`), logged with `traceback.print_exc()`, and set status to `failed`.
- `/chat/no-stream`: `get_llm_response` catches OpenAI errors (`AuthenticationError`, `RateLimitError`, `APIError`) but then falls through; if an exception occurs, `response` is undefined and an `UnboundLocalError` is raised.
- `/chat` stream: exceptions inside the generator raise `HTTPException`, but because they are raised from an async generator, the client receives a truncated stream and the response is opaque.
- No global exception handler is registered.

---

## 8. Important Features

### 8.1 PDF ingestion with tables & headings

**How it works internally**

1. `process_source_pdf` downloads the PDF to a temp file and deletes the R2 object.
2. Opens the file with both `fitz` (PyMuPDF) and `pdfplumber`.
3. For each page:
   - Extracts tables with pdfplumber -> converts rows to `' | '` joined text.
   - Extracts text blocks from PyMuPDF `dict` output; updates `current_section` if a span has font size > 14.
   - Concatenates block text + table text as the page content.
   - Runs `RecursiveCharacterTextSplitter` with chunk_size 768 and overlap 150.
   - Emits chunks in batches of 100.
4. `embedding_chunks` sends each batch to OpenAI, builds `PointStruct`, upserts to Qdrant.

**Files involved:** `app/services/chunking_service.py`, `app/services/embedding_service.py`, `app/services/ingestion_service.py`, `app/workers/ingestion_worker.py`, `app/core/qdrant.py`, `app/core/r2.py`.

**Data flow:** `R2 -> temp file -> PyMuPDF/pdfplumber -> LangChain chunks -> OpenAI embeddings -> Qdrant points`.

**Why implemented this way:** Combining PyMuPDF and pdfplumber gives both speed/heading-aware extraction and decent table support. Recursive splitting preserves natural boundaries (paragraph -> line -> sentence).

**Possible interview questions**

- Why two PDF libraries?  
  **Answer:** PyMuPDF for text blocks + font-based headings; pdfplumber for tables. Merging both improves context quality.
- How are chunk IDs generated and what risk does that carry?  
  **Answer:** MD5 of content. Risk of collision causing silent overwrites if duplicate text appears across pages/sources.
- What happens to the R2 object after upload?  
  **Answer:** It is deleted in `finally` of `process_source_pdf`, even on failure. This can prevent retrying a failed ingestion.

### 8.2 Web crawling for URLs

**How it works internally**

The active crawler is `app/services/crawler_service.py` (the old `crawler.py` is fully commented out).

1. `load_robots(start_url)` fetches `/robots.txt`.
2. `normalize_url` strips fragments, lowercases scheme/host, sorts query params, removes trailing slash.
3. BFS queue seeded with normalized start URL.
4. Each batch of queued URLs is fanned out with `asyncio.gather`, limited by `asyncio.Semaphore(max_concurrency)`.
5. `scrape_page`:
   - Opens a new Playwright page.
   - Routes `image`, `media`, `font`, `stylesheet` to abort.
   - Navigates with `domcontentloaded`, 30s timeout.
   - Extracts `document.title` and `document.body.innerText`.
   - Collects links, filters external domains and blocked extensions.
6. Valid child links are enqueued up to `max_depth` and `max_pages`.

**Files involved:** `crawler_service.py`, `ingestion_service.py`, `chunking_service.py`.

**Data flow:** `URL -> robots.txt -> BFS queue -> Playwright pages -> list[dict] -> chunking -> embeddings -> Qdrant`.

**Why this way:** Browser-based crawling handles modern JS sites. Concurrency and resource blocking keep it reasonably fast. Robots.txt and blocked domains add politeness/security.

**Possible interview questions**

- How do you avoid crawling the entire internet?  
  **Answer:** Same-domain enforcement, max_depth, max_pages, blocked domains, blocked extensions.
- How would you make the crawler resilient to bot detection?  
  **Answer:** Rotate user agents, use stealth plugins, respect crawl-delay, add proxy rotation, slow down `request_delay`.
- Why did you use BFS instead of recursion?  
  **Answer:** Avoids stack overflow; gives breadth-priority coverage; easier concurrency control with queue/semaphore.

### 8.3 Background ingestion with ARQ

**How it works internally**

- `app/main.py` creates an `arq` Redis pool in the FastAPI lifespan.
- It also starts an ARQ `Worker` in a background `asyncio.create_task` with `max_jobs=1` and `job_timeout=300`.
- `ingestion_worker.py` registers three functions (`ingest_source_pdf/text/url`) that call into `ingestion_service.py`.
- Routes use `request.app.state.arq_pool.enqueue_job(...)` to push work.

**Files involved:** `app/main.py`, `app/workers/ingestion_worker.py`, `app/core/redis.py`, `app/api/routes/source.py`.

**Why this way:** ARQ is an async-native, Redis-backed task queue; very small overhead versus Celery; Python `async`/`await` all the way through.

**Trade-off:** Worker runs inside the web process. A long-running crawl/embedding job can compete for CPU/memory with active HTTP requests and kills both on crash/redeploy.

### 8.4 Chat / RAG retrieval

**How it works internally**

1. `POST /chat` embeds the user query via `embed_user_query` (OpenAI).
2. `search_relevant_context` constructs Qdrant `Filter(MatchAny(source_id))` and calls `query_points` with `limit=5`.
3. `get_llm_response_stream` formats chunks into a context block and supplies it to a system prompt that tells the LLM to cite source/page/section.
4. It `await`s `AsyncOpenAI.chat.completions.create(..., stream=True)` and yields SSE events.
5. After tokens, it yields `data: [DONE]\n\n` twice (the second event intended to carry sources but actually also sends just `[DONE]`).

**Files involved:** `app/api/routes/chat.py`, `app/services/retrieval_service.py`, `app/services/llm_service.py`, `app/schemas/chat.py`.

**Why this way:** Streaming gives low time-to-first-byte and good UX. Source-level filtering ensures the answer only uses selected documents.

**Possible interview questions**

- How do you prevent the LLM from hallucinating off-topic?  
  **Answer:** System prompt says prefer context and only say `I don't know` when no relevant info. Plus retrieval filters to selected sources.
- How do you handle conversation history?  
  **Answer:** It is included as a list of `{role, content}` messages after the system message.
- What is the retrieval limit and is it configurable?  
  **Answer:** `top_k=5` with a function default; not exposed to the client in current routes.

### 8.5 RAG evaluation suite

**How it works internally**

- `tests.jsonl` contains 20 labeled questions with keywords and reference answers.
- `eval.py` computes:
  - **MRR** over keyword presence in retrieved chunks.
  - **nDCG** of keyword binary relevances over top-k.
  - Keyword coverage.
  - **LLM-as-a-judge** via Gemini (through `litellm`) scoring accuracy, completeness, relevance 1–5.
- `evaluator.py` wires these into a Gradio dashboard with HTML metric cards and pandas bar charts.

**Files involved:** `app/evaluation/eval.py`, `evaluator.py`, `test.py`, `tests.jsonl`.

**Why this way:** Provides repeatable, automated signals for retrieval and generation quality.

**Weakness:** `evaluate_retrieval` and `evaluate_answer` ignore the passed `user_id`/`source_ids` and hardcode user `1111` and source `24795850-...`, so the harness only works against a specific manually seeded collection.

---

## 9. Design Decisions

| Decision | Chosen approach | Trade-offs | Better alternatives |
|---|---|---|---|
| **Per-user Qdrant collection** | `blackbook_{user_id}` | Easy tenant deletion/isolation; harder cross-tenant analytics; many small collections. | Single collection with `user_id` payload filter and a global HNSW index. |
| **Worker colocated with API** | ARQ Worker started as `asyncio.create_task` inside FastAPI lifespan | Simpler local/dev deployment; worker competes with HTTP traffic; redeploy kills jobs. | Separate worker container/service (same queue, dedicated CPU/memory). |
| **Deterministic source IDs** | `uuid5(DNS, filename/url/text[:100])` | Deduplication by name; collisions across users/content; no versioning. | UUID4 + persistent source table with unique constraints. |
| **MD5 chunk IDs** | `md5(page_content).hexdigest()` | Deduplicates identical text; collision risk; silent overwrites. | UUID4 or hash of content + source_id + index. |
| **R2 staging + immediate delete** | Upload PDF to R2, ingest, then delete in `finally` | Avoids ephemeral disk; no replay if worker fails mid-ingestion. | Keep object until success, or stream PDF directly from request. |
| **OpenAI-only LLM/embedding** | `AsyncOpenAI` with env-driven model vars | Simple, high quality; vendor lock-in; no fallback on rate limits. | LiteLLM/abstracted provider for embeddings too, with retries across providers. |
| **Redis TTL status** | `ex=3600` on status key | Simple ephemeral progress; status disappears after 1 hour. | Persistent source table in Postgres + Redis pub/sub for live updates. |
| **No relational DB** | No source/user table fast | Minimal moving parts; no audit trail, listing, ACLs. | Add Supabase/Postgres for users, sources, chats, billing. |

---

## 10. Performance

### 10.1 Bottlenecks

1. **Embedding API latency/cost** — every chunk batch is sent to OpenAI; no batch cap or local embedding fallback. Large PDFs/URL crawls can generate thousands of chunks and hundreds of API calls.
2. **In-memory PDF processing** — `await file.read()` loads the whole file; the temp file is local; very large PDFs are limited by container RAM.
3. **Single ARQ worker with `max_jobs=1`** — only one ingestion job runs at a time. Concurrent PDF/text/url uploads queue up.
4. **Playwright crawler per URL** — even with concurrency = 5, a 100-page crawl with `request_delay=0.5` can take ~10-20+ seconds.
5. **No caching** — repeated identical queries re-embed and re-search Qdrant each time.
6. **Stream response copies sources list twice** — minor, but the second `[DONE]` event does not actually send sources.

### 10.2 Optimizations already present

- Chunks are batched in groups of 100 before embedding/upsert.
- Crawler blocks images/fonts/stylesheets and aborts heavy resource types.
- Per-user collection narrows vector search space.
- Multi-stage Docker build keeps final image small.
- `AsyncOpenAI` and async Qdrant client avoid blocking the event loop.
- URL crawler uses BFS + semaphore rather than recursive synchronous calls.

### 10.3 Possible future optimizations

1. Use a local embedding model (e.g. `sentence-transformers` or ONNX) for batch ingestion to reduce OpenAI cost/latency.
2. Add a query-embedding cache in Redis (TTL ~hours) and a Qdrant result cache.
3. Implement hybrid search: sparse vectors / keyword BM25 + dense vector, with reranking (e.g. Cohere rerank).
4. Paginate/parallelize PDF chunk extraction and embedding instead of single-threaded page loop.
5. Prefetch/adapt chunk size based on expected LLM context budget.
6. Move to a dedicated worker container with `max_jobs > 1`, or use separate queues per ingestion type.
7. For large PDFs, use chunked upload to R2 and chunked processing (partial read with `boto3` multipart).

---

## 11. Security

### 11.1 Existing security measures

- Fly.io HTTP service forces HTTPS (`force_https = true`).
- CORS credentials allowed only because origins are `*`; not really a measure.
- Robots.txt + blocked-domain/extension list in the crawler.
- Sensitive config is intended to come from environment variables (though not done correctly in all local scratch scripts).

### 11.2 Weaknesses

1. **No authentication/authorization** — anyone with the public URL can upload, query, and read any user’s collection by changing `x-user-id`.
2. **Open CORS** — `allow_origins=['*']` and `allow_credentials=True` is dangerous in production.
3. **Secrets leakage** — `.env` exists in the working tree (ignored by git but present), and credentials are hardcoded in `test.py` and `app/workers/test_worker.py`.
4. **SSRF via URL ingestion** — `/source/url` will crawl arbitrary internal or external URLs from the worker.
5. **No file size / rate limits** — large PDFs or many requests can exhaust memory, OpenAI quota, or Redis.
6. **Unconditional R2 delete** — `finally` block deletes the staging object even on failure, destroying evidence and preventing retry.
7. **Verbose logs** — some routes print status/payloads; `get_source_status` prints raw Redis responses.
8. **LLM prompt injection** — user query is passed to the LLM as part of the system prompt conversation without sanitization.

### 11.3 Improvements

- Add OAuth2/JWT/API-key middleware and enforce `user_id` from verified identity.
- Restrict CORS to the exact frontend origin.
- Store secrets in a vault/Fly secrets, never commit or hardcode them.
- Add URL allow-list + DNS rebinding protection for the crawler.
- Add `max_file_size`, `max_pages`, and rate-limiting (Redis or in-memory).
- Move R2 delete to a successful-ingestion branch only.
- Implement PII scrubbing and prompt-injection guardrails.

---

## 12. Deployment

### 12.1 Docker

- `Dockerfile` uses a **two-stage build**:
  1. `builder` stage runs `uv sync --frozen --no-dev --no-install-project` to produce `.venv`.
  2. Final stage copies `.venv` and `app/` onto `python:3.12-slim`.
- Final image starts `uvicorn app.main:app --host 0.0.0.0 --port 8080`.
- `.dockerignore` excludes `.env`, `fly.toml`, tests, uploads, evaluation to keep the image small and avoid leaking secrets.

### 12.2 Fly.io configuration (`fly.toml`)

- App name `blackbookai-backend`, primary region `sin` (Singapore).
- HTTP service on internal port `8080`, `force_https = true`.
- `auto_stop_machines = 'stop'`, `auto_start_machines = true`, `min_machines_running = 0` — machines scale to zero to save cost, but this causes cold starts.
- VM: shared CPU, 1 vCPU, 1 GB RAM.

### 12.3 CI/CD (`.github/workflows/fly-deploy.yml`)

- Deploys on every push to `main`.
- Uses `superfly/flyctl-actions/setup-flyctl@master`.
- Runs `flyctl deploy --remote-only` with `FLY_API_TOKEN` from repository secrets.
- No test/lint step before deploy.

### 12.4 Environment variables used

`REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_USERNAME`, `REDIS_PASSWORD`, `QDRANT_URL`, `QDRANT_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `TOGETHER_API_KEY`, `EMBEDDING_MODEL`, `LLM_MODEL`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET_NAME`, `R2_API_ENDPOINT`, `R2_AUTH_TOKEN`.

**Note:** Many alternative-LLM keys (`GEMINI`, `OPENROUTER`, `TOGETHER`) are defined but only `GEMINI_API_KEY` is used today — by the evaluation harness.

### 12.5 Reverse proxy / load balancing

- There is **no Nginx** config in the repo. Fly.io’s edge layer acts as reverse proxy and terminates TLS.

---

## 13. Code Quality

### 13.1 Good practices followed

- Modular separation: `core/` for infra, `services/` for business logic, `api/routes/` for HTTP, `schemas/` for Pydantic models.
- `async`/`await` used consistently where I/O is involved (OpenAI, Qdrant, Redis, R2 via `boto3` sync inside async context — but the heavy ingest work runs in the worker).
- FastAPI `lifespan` is used correctly to initialize and tear down Redis pool + worker.
- Evaluation harness with MRR, nDCG, and LLM-as-a-judge shows engineering rigor.
- Multi-stage Docker build and `uv` lockfile for reproducible deployments.
- `.gitignore` correctly ignores `.env`, `.venv`, cache, and tests.

### 13.2 Code smells

- `load_dotenv()` is called in many individual modules (`r2.py`, `redis.py`, `llm_service.py`, `ingestion_service.py`, `eval/*.py`) instead of once at app entry.
- `print()` debugging statements are scattered; production logs should use a structured logger.
- `embedding_service.py` imports `traceback` twice.
- `response` may be undefined in `get_llm_response` non-stream if an OpenAI exception is raised (UnboundLocalError).
- `process_source_text` always sets status to `completed` in `finally`, even on failure.
- Routes return 200 error JSONs instead of raising `HTTPException` for invalid input.
- `get_llm_response_stream` duplicates the context-formatting logic already present in `get_llm_response`.
- Evaluation hardcodes a test user/source, making generalized benchmarking impossible.
- `evaluator.py` still references `Insurellm RAG system` in UI text — stale branding.
- `test_worker.py` and `test.py` contain literal secrets in local scripts.

### 13.3 Refactoring suggestions

1. Centralize config in a Pydantic `Settings` class (`pydantic-settings`) and remove `load_dotenv` from modules.
2. Add structured logging (`structlog` or stdlib `logging`) with correlation IDs.
3. Raise `HTTPException` (400/404/422) instead of returning dict errors.
4. Extract the context-formatting helper to remove duplication between streaming and non-stream.
5. Add `pytest` tests for routes, services, and evaluation metrics.
6. Run `ruff`/`mypy` in CI before deploying.
7. Add health-check and readiness endpoints.
8. Delete/hide local scratch scripts (`test.py`, `test_worker.py`, etc.) or remove all hardcoded values.

---

## 14. Resume Explanation

### 14.1 Two-minute version

>I built BlackbookAI, a FastAPI-based RAG backend that lets users upload PDFs, paste text, or submit URLs, then ask questions grounded in that content. PDFs are staged in Cloudflare R2 and processed by an ARQ background worker: it extracts text and tables with PyMuPDF and pdfplumber, chunks them with LangChain, embeds them with OpenAI text-embedding-3-small, and stores them in a per-user Qdrant collection. Chat endpoints either return a full JSON answer or stream an OpenAI completion as Server-Sent Events, using the top-5 retrieved chunks plus conversation history. I also wrote a small evaluation harness that computes MRR, nDCG, and LLM-as-a-judge metrics, served through a Gradio dashboard. The service is containerized with Docker and deployed to Fly.io via GitHub Actions.

### 14.2 Five-minute version

>I built the BlackbookAI backend, a Retrieval-Augmented Generation API in Python 3.12 / FastAPI. The core idea is to turn a user’s documents or web pages into a searchable knowledge base and answer questions with citations.
>
>Users can submit three kinds of sources: PDFs, raw text, or URLs. PDF uploads land temporarily in Cloudflare R2, then an ARQ worker picks up the ingestion job from Redis. The worker uses PyMuPDF to extract structured text blocks and detect headings by font size, and pdfplumber to pull out tables. Text and tables are merged per page, split into ~768-token chunks with 150-token overlap using LangChain’s recursive splitter, embedded with OpenAI’s text-embedding-3-small, and upserted into a Qdrant collection named `blackbook_{user_id}`. URLs go through an async BFS Playwright crawler that respects robots.txt, blocks images/CSS/fonts, and limits depth and total pages. Text sources skip the crawler and object storage entirely.
>
>For chat, the query is embedded, Qdrant returns the top-5 chunks filtered by the selected source IDs, and the chunks plus prior conversation history are fed into an OpenAI chat model. The client can choose a regular JSON response or an SSE stream for lower latency. I also created an evaluation pipeline: hand-written test cases stored in JSONL, retrieval metrics like MRR and nDCG, and an LLM-as-a-judge using Gemini that scores accuracy, completeness, and relevance, all wrapped in a Gradio UI.
>
>Ops-wise, the project uses `uv` for dependency management, a multi-stage Dockerfile, and Fly.io auto-scaling with CI/CD from GitHub Actions. The main trade-offs I accepted: no separate relational database for source metadata, per-user vector collections, and the worker running inside the API process for simplicity. If I were scaling this, I would split the worker, add OAuth2, and introduce hybrid search with a reranker.

### 14.3 Business version
BlackbookAI is a NotebookLM-inspired Retrieval-Augmented Generation (RAG) platform that allows users to create their own private AI knowledge bases. Instead of asking a general-purpose LLM questions, users can upload their own documents, website content, or notes, and the system answers questions grounded only in those sources with citations. The goal was to make it easy for users to chat with their own information while minimizing hallucinations.

I built the backend in Python 3.12 using FastAPI, with a strong focus on asynchronous processing because document ingestion can take several seconds or even minutes depending on the document size.

Users can add knowledge in three forms: PDFs, raw text, or URLs. PDF uploads are stored temporarily in Cloudflare R2, and an ARQ worker consumes ingestion jobs from Redis so the API can immediately respond instead of blocking while processing documents.

During ingestion, I extract document content using PyMuPDF, where I preserve document structure by detecting headings based on font sizes. I also use pdfplumber to extract tables, then merge both outputs page by page. The text is split into approximately 768-token chunks with 150-token overlap using LangChain's recursive text splitter. Each chunk is converted into embeddings using OpenAI's text-embedding-3-small model and stored in Qdrant. I maintain separate collections for each user (blackbook_{user_id}) to keep user data isolated.

For website ingestion, I built an asynchronous BFS crawler using Playwright. It respects robots.txt, blocks unnecessary assets like images, CSS, and fonts to reduce bandwidth, and limits crawl depth and total pages to avoid excessive crawling. Raw text sources are much simpler—they skip storage and crawling and go directly through the chunking and embedding pipeline.

During chat, the user's question is embedded, and Qdrant performs semantic similarity search to retrieve the top five relevant chunks, filtered by the specific source IDs selected by the user. Those retrieved chunks, along with the previous conversation history, are sent to an OpenAI chat model to generate the final grounded response. I exposed both a normal JSON API and an SSE streaming endpoint, allowing users to start receiving tokens immediately for a better perceived response time.

To evaluate the system, I also built an automated evaluation pipeline. I created hand-written test datasets in JSONL format, measured retrieval quality using metrics like MRR and nDCG, and used Gemini as an LLM judge to score generated answers on accuracy, completeness, and relevance. I wrapped the evaluation workflow inside a Gradio dashboard so experiments could be run easily.

From a deployment perspective, I used uv for dependency management, a multi-stage Docker build, and deployed the application on Fly.io with GitHub Actions handling CI/CD.

There were a few intentional trade-offs. To keep the architecture simple, I didn't introduce a separate relational database for source metadata, I used per-user vector collections instead of a shared multi-tenant collection, and I initially ran the background worker alongside the API service. If I were taking this into production at larger scale, I would separate the worker into its own service, add OAuth2-based authentication, move to a shared collection with metadata filtering where appropriate, and improve retrieval using hybrid search and a reranking model.

---

## 15. Interview Questions

### 15.1 Easy (30)

1. What framework is the API built with?
2. Which vector database does the project use?
3. What embedding model is configured?
4. What LLM model is used for chat completions?
5. Name the three source types the backend accepts.
6. Which library handles PDF table extraction?
7. Which library handles PDF text block + heading extraction?
8. What is the chunk size and overlap used by the text splitter?
9. How is a source status stored and retrieved?
10. What is the Redis TTL for source status keys?
11. What task queue library is used?
12. Why is the worker started inside the FastAPI lifespan?
13. What port does the container expose?
14. Which platform hosts the app in production?
15. What file defines the Fly.io deployment configuration?
16. Which CI/CD service deploys the app?
17. What is the collection naming convention in Qdrant?
18. What distance metric is used for vector search?
19. What is the vector size in each Qdrant collection?
20. Which header identifies the user in source routes?
21. What is the main purpose of `x-user-id`?
22. How many top chunks are retrieved for a chat question?
23. What response type does `/chat` return?
24. What response type does `/chat/no-stream` return?
25. Which file defines the crawler logic currently in use?
26. Name two blocked resource types in the Playwright crawler.
27. What file contains the evaluation test cases?
28. Which metric measures mean reciprocal rank?
29. What does nDCG stand for?
30. What is the purpose of `ram.py`?

### 15.2 Medium (30)

1. Walk through the full PDF upload-to-answer flow.
2. How are chunk point IDs generated, and why does that matter?
3. Why are both PyMuPDF and pdfplumber used?
4. What would happen if two different PDFs have the same filename?
5. How does the crawler avoid leaving the starting domain?
6. Explain the BFS + semaphore design in `crawler_service.py`.
7. Why does the worker run in the same process as the web server?
8. What are the trade-offs of one collection per user?
9. How would you add a new ingestion source type (e.g. YouTube transcript)?
10. What is the role of `source_id` in Qdrant queries?
11. How is conversation history passed to the LLM?
12. Why does the streaming endpoint yield `data: [DONE]` twice?
13. How would you implement retries for the OpenAI embedding call?
14. What happens if Qdrant is unavailable when FastAPI starts?
15. How does the status endpoint work?
16. Why are PDFs staged to R2 instead of kept on local disk?
17. What is the risk of deleting the R2 object in a `finally` block?
18. How would you rate-limit uploads by user?
19. Why might streaming responses be harder to debug than JSON responses?
20. Compare `query_points` and `scroll` in Qdrant.
21. How is robots.txt handled during crawling?
22. What information is included in each Qdrant payload?
23. How are tables converted into text during PDF chunking?
24. Why does the app use `AsyncOpenAI` instead of the sync client?
25. What would you change if the app needed to support 10,000 users?
26. How is source-level isolation enforced today?
27. How would you validate a URL before enqueuing it?
28. What is the difference between `process_source_text` and `process_source_pdf` error handling?
29. How does the evaluation harness compute keyword coverage?
30. Why is `force_https = true` important in `fly.toml`?

### 15.3 Hard (30)

1. Design a secure multi-tenant architecture for this RAG backend. Where does the current design fail?
2. The `x-user-id` header controls collection access. What is wrong with that?
3. Propose a migration from per-user collections to a single global collection; what breaks and how do you fix it?
4. How would you prevent duplicate chunks from silently overwriting each other in Qdrant?
5. The OpenAI call embeds every chunk synchronously per batch. How would you make ingestion scale to 1,000-page PDFs?
6. Write a fault-tolerant design where the worker lives in a separate container and can scale horizontally.
7. The crawler can be abused for SSRF. How would you harden URL ingestion?
8. Given cold starts on Fly (`min_machines_running = 0`), what user-visible latency issues might occur, and how do you mitigate them?
9. How would you implement hybrid search (dense + sparse) in Qdrant for this project?
10. Design a cost-control mechanism that caps OpenAI tokens per user per day.
11. The non-stream chat function catches OpenAI errors but does not return a valid response. What is the bug and how do you fix it?
12. How would you cache query embeddings and Qdrant results without stale context?
13. Design a source-versioning system so re-uploading the same PDF creates a new revision rather than overwriting chunks.
14. The evaluation hardcodes user `1111` and a single source. How would you make evaluation general and CI-friendly?
15. How would you protect the LLM from prompt injection in user queries?
16. What happens to ingestion jobs if the Fly machine restarts mid-job with `max_jobs=1`?
17. How would you guarantee at-least-once or exactly-once ingestion semantics?
18. Propose an architecture to keep source documents encrypted in R2 and chunks encrypted in Qdrant.
19. How does `allow_origins=['*']` interact with `allow_credentials=True`? Why is it risky?
20. How would you shard users across multiple Qdrant clusters?
21. Design idempotent payment/billing for per-token usage.
22. What concurrency issues exist if `max_jobs` is increased while sharing a single Qdrant collection?
23. How would you compress or prune embeddings to reduce storage cost?
24. Design a graceful shutdown path for the colocated ARQ worker.
25. If the same text appears in different sources, the MD5 chunk ID collides. Is that desirable? Justify and provide alternatives.
26. How would you add real-time status updates to the client instead of polling?
27. Compare ARQ vs Celery vs RQ for this workload and justify a choice.
28. How would you handle PDFs that contain scanned images instead of selectable text?
29. Design a global evaluation loop that continuously measures retrieval and answer quality in production.
30. How would you remove the dependency on the OpenAI API entirely while keeping answer quality comparable?

---

## 16. Deep Dive Questions

These are the kinds of `why` questions a senior interviewer typically asks.

1. **Architecture:** Why is the worker running in the same process as the web server instead of as a separate service? What are the real-world consequences?
2. **Scalability:** A single collection per user is simple today, but how does it behave when you have tens of thousands of users? What operational limits does Qdrant impose?
3. **Authentication:** You rely solely on a client-provided `x-user-id` header. Why is that acceptable or unacceptable for production? What would you replace it with?
4. **Data isolation:** If user A knows user B’s `user_id`, can they read user B’s sources? Trace the request path to prove your answer.
5. **Storage:** Why stage PDFs to R2 at all? Could you process the upload directly in the request handler?
6. **Chunking:** You combine PyMuPDF and pdfplumber. What problem does each solve, and what maintenance burden do two libraries introduce?
7. **Crawler design:** Why BFS instead of DFS or recursion? How does semaphore-based concurrency compare to launching one browser context per URL?
8. **Error handling:** `process_source_text` sets status to `completed` in `finally` even after an exception. Is that intentional? What is the impact?
9. **Vector IDs:** Why did you choose MD5 of the chunk text as the point ID? What semantic does that encode (dedup vs. identity)?
10. **Context window:** You always retrieve top-5 chunks. What if the combined chunks exceed the model’s context length? How would you guard against that?
11. **Cost:** You call OpenAI for every chunk during ingestion and every chat query. Where would you cache or avoid those calls?
12. **Security:** `/source/url` can crawl arbitrary URLs. What is the blast radius, and how do you minimize it?
13. **Operations:** `fly.toml` scales to zero machines. What does that mean for the first request after idle?
14. **Testing:** There are no automated tests in CI, and the evaluation harness hardcodes a user. How do you know the system works before each deploy?
15. **Prompting:** The system prompt asks the model to cite sources but does not enforce structured output. How would you guarantee consistent citations?

---

## 17. Improvements

Features and architectural upgrades that would impress senior interviewers:

1. **Real auth + RBAC** — OAuth2/JWT, organizations, shared collections, read-only vs editor roles.
2. **Persistent source metadata** — PostgreSQL/SQLite table for sources, users, chats, and audit logs.
3. **Separate worker deployment** — Horizontal scaling of ingestion workers by source type (PDF, URL, text).
4. **Hybrid retrieval + reranker** — Dense embeddings + sparse BM25/keyword search, plus a reranker for better precision.
5. **Query rewriting / multi-hop** — Rewrite vague queries, break complex questions into sub-questions.
6. **SLA observability** — OpenTelemetry, structured logs, latency/error dashboards, SLOs for embedding and chat.
7. **Caching layers** — Redis for query embeddings, frequent Qdrant results, and LLM responses.
8. **Async real-time status** — WebSocket or SSE push for ingestion progress instead of polling.
9. **File format expansion** — DOCX, markdown, HTML, audio transcripts with appropriate parsers.
10. **Cost controls** — Per-user rate limits, token budgets, usage tracking, model fallbacks.
11. **Data privacy** — End-to-end encryption at rest, PII detection/redaction, data retention policies.
12. **A/B eval pipeline** — Continuous online evaluation comparing chunking strategies and prompts.

---

## 18. Weak Areas & How to Defend or Improve Them

| Weak area | Why an interviewer may criticize it | How to defend (honestly) | How to improve |
|---|---|---|---|
| No real authentication | Any header can switch tenants. | It was an MVP; isolation is a placeholder for OAuth. | Add JWT middleware, map claim to `user_id`, reject anonymous requests. |
| Worker in API process | Violates separation of concerns, not scalable. | Kept deployment simple; ARQ made it easy. | Split into a dedicated worker Docker image + service on Fly. |
| `allow_origins=['*']` | Open to CSRF-like abuse if credentials are used. | Local-dev convenience. | Restrict to frontend origin, drop credentials unless needed. |
| Secrets in local scripts / `.env` | Shows poor secret hygiene. | Untracked scratch files (`test.py`, `test_worker.py`) left behind; `.env` is gitignored but present. | Delete scratch files, use Fly secrets, add pre-commit secret scanner. |
| Hardcoded evaluation user/source | Evaluation is not portable/CI-friendly. | Quick manual harness against a known seeded collection. | Parameterize user/source or bootstrap test fixtures automatically. |
| R2 object deleted in `finally` | Loses ability to retry failed ingests. | Wanted to avoid leaving orphaned staging objects. | Delete only after successful completion; implement dead-letter queue. |
| No input size / URL restrictions | SSRF, DoS, and large-memory risks. | Feature-complete first pass. | Add `max_pages`, `max_file_size`, URL allow-list, content-length checks. |
| MD5 chunk IDs | Hash collisions overwrite unrelated chunks. | Simple deterministic dedup. | Use UUID4 or combine content hash with source_id and index. |
| No tests in CI | Deploys without verification. | Focused on manual eval dashboard. | Add `pytest` unit + integration tests; run them in GitHub Actions before Fly deploy. |

---

**Document generated from the actual codebase on 2026-07-08.**
