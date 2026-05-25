import traceback
from app.core.qdrant import init_user_collection
from app.services.crawler_service import crawl_website
from app.services.embedding_service import embedding_chunks
from app.services.chunking_service import extract_chunks_from_pdf, extract_chunks_from_text_content, extract_chunks_from_url_content


async def process_source_text(user_id, source_id, text, source_title):
    try:
        # Init collection (recreates fresh if exists)
        collection_name = await init_user_collection(user_id)

        # this creates chunks from text content and attach metadata
        chunks = extract_chunks_from_text_content(user_id, source_id, source_title or "source_text", text)

        await embedding_chunks(chunks, collection_name)

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()

async def process_source_url(user_id, source_id, url):
    try:
        # Init collection (recreates fresh if exists)
        collection_name = await init_user_collection(user_id)

        # Extract text content from the URL (with crawler) - this is where you can add retries, error handling, etc.
        text_content = await crawl_website(url)

        # this creates chunks from text content and attach metadata
        chunks = extract_chunks_from_url_content(user_id, source_id, url, text_content)

        await embedding_chunks(chunks, collection_name)

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()

async def process_source_pdf(user_id, source_id, source_name, source_path):
    try:
        # set_status(sourceId, "processing")

        # Init collection (recreates fresh if exists)
        collection_name = await init_user_collection(user_id)
        
        # Extract per page content + metadata and create chunks from it
        chunks = extract_chunks_from_pdf(user_id, source_id, source_name, source_path)

        await embedding_chunks(chunks, collection_name)

        # set_status(sourceId, "completed")

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
   
