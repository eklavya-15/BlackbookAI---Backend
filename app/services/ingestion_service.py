import traceback, os, tempfile
from app.core.r2 import s3
from dotenv import load_dotenv
from app.core.ram import ram
from app.core.redis import set_source_status
from app.core.qdrant import init_user_collection
from app.services.crawler_service import crawl_website
from app.services.embedding_service import embedding_chunks
from app.services.chunking_service import extract_chunks_from_pdf, extract_chunks_from_text_content, extract_chunks_from_url_content
load_dotenv()

async def process_source_pdf(ctx, user_id, source_id, source_name, r2_key):  
    tmp_path = None
    success = False
    try:
        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "Reading", "progress": 0})
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            s3.download_fileobj(os.getenv("R2_BUCKET_NAME"), r2_key, tmp)
            tmp_path = tmp.name

        collection_name = await init_user_collection(user_id)
        print("start", ram())

        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "Chunking", "progress": 50})
        for chunk_batch in extract_chunks_from_pdf(source_id, source_name, tmp_path):
            await embedding_chunks(chunk_batch, collection_name)
        
        success = True
        print("after embedding", ram())

    except Exception as e:
        await set_source_status(ctx["redis"], source_id, {"status": "failed", "error": str(e)})
        print(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
    
    finally:
        if tmp_path:
            os.remove(tmp_path)
        s3.delete_object(Bucket=os.getenv("R2_BUCKET_NAME"), Key=r2_key)
    
    if success:
        await set_source_status(ctx["redis"], source_id, {"status": "completed", "progress": 100})


async def process_source_text(ctx, user_id, source_id, text, source_title):
    try:
        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "initializing", "progress": 50})

        # Init collection (recreates fresh if exists)
        collection_name = await init_user_collection(user_id)

        # this creates chunks from text content and attach metadata
        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "chunking", "progress": 75})
        chunks = extract_chunks_from_text_content(user_id, source_id, source_title or "source_text", text)
        
        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "embedding", "progress": 90})
        await embedding_chunks(chunks, collection_name)

    except Exception as e:
        await set_source_status(ctx["redis"], source_id, {"status": "failed", "error": str(e)})
        print(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()

    finally:
        await set_source_status(ctx["redis"], source_id, {"status": "completed", "progress": 100})

async def process_source_url(ctx, user_id, source_id, url):
    try:
        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "initializing", "progress": 50})

        # Init collection (recreates fresh if exists)
        collection_name = await init_user_collection(user_id)

        # Extract text content from the URL (with crawler) - this is where you can add retries, error handling, etc.
        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "crawling", "progress": 25})
        text_content = await crawl_website(url)

        # this creates chunks from text content and attach metadata
        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "chunking", "progress": 50})
        chunks = extract_chunks_from_url_content(user_id, source_id, url, text_content)
        
        await set_source_status(ctx["redis"], source_id, {"status": "processing", "stage": "embedding", "progress": 75})
        await embedding_chunks(chunks, collection_name)

    except Exception as e:
        await set_source_status(ctx["redis"], source_id, {"status": "failed", "error": str(e)})
        print(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()

    finally:
        await set_source_status(ctx["redis"], source_id, {"status": "completed", "progress": 100})

   
