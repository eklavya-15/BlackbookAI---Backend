from litellm import acompletion, aembedding, APIError, AuthenticationError, RateLimitError
import os
from dotenv import load_dotenv
from openai import OpenAI

from app.schemas.chat import ChatMessage
load_dotenv()

client = OpenAI()

SYSTEM_PROMPT = """
You are a helpful AI assistant answering questions based on retrieved document context.

Use the provided context to answer the user's question as accurately as possible.

Guidelines:
- Prefer information from the provided context.
- If the context partially answers the question, provide the best possible answer using the available information.
- Only say "I don't know" if the context contains absolutely no relevant information.
- Keep answers concise but informative.
- When possible, cite the source and page number in this format:
  (Source: <source>, Page: <page>)

Retrieved Context:
{context}
"""

async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts, returns list of vectors."""
    response = await aembedding(
        model=os.getenv("EMBEDDING_MODEL"),
        input=texts,
        api_key=os.getenv("OPENAI_API_KEY")
    )
    return [item["embedding"] for item in response.data]


async def embed_user_query(query: str) -> list[float]:
    vectors = await embed_texts([query])
    return vectors[0]


async def get_llm_response( query: str, relevant_context: list | None, conversation_history: list[ChatMessage]) -> dict:
    """
    Build prompt from retrieved chunks and get LLM response.
    context_chunks: list of dicts with 'text', 'source_title', 'page', 'section'
    """

    if not relevant_context:
        context = ""
    else:
        context = "\n\n".join([
            (
                f"[Source: {c['source_name']} ({c['source_type']})]"
                + (f", Page: {c['page']}" if c.get("page") else "")
                + (f", URL: {c['url']}" if c.get("url") else "")
                + (f", Section: {c['section']}" if c.get("section") else "")
                + "]"
                + f"\n{c['text']}"
            )
            for c in (relevant_context or [])
        ])
    print("CONTEXT FOR LLM:")
    print(context[:1000])  # print first 1000 chars of context for debugging
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(context=context)
        },
        *[
            {
                "role": msg.role,
                "content": msg.content
            }
            for msg in conversation_history
        ]
    ]

    try:
        response = await acompletion(
            model=os.getenv("LLM_MODEL"),
            messages=messages,
            temperature=0.2,
            max_tokens=1000
        )
    except AuthenticationError as e:
        print(f"Bad API key: {e}")
    except RateLimitError as e:
        print(f"Rate limited: {e}")
    except APIError as e:
        print(f"API error: {e}")

    return {
        "answer"  : response.choices[0].message.content.strip(),
        "sources" : [
            {
                "title"     : c["source_name"],
                "page"      : c["page"],
                "url"       : c["url"],
                "section"   : c["section"]
            }
            for c in relevant_context
        ]
    }