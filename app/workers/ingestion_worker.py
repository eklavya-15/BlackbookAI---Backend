from app.core.redis import redis_settings
from app.services.ingestion_service import process_source_pdf, process_source_text, process_source_url
from app.core.redis import set_source_status

async def ingest_source_pdf(ctx, source_path, source_name, user_id, source_id):
    redis = ctx["redis"]  # arq injects this automatically

    await set_source_status(redis, source_id, {"status": "processing", "progress": 0})
    try:
        await process_source_pdf(user_id, source_id, source_name, source_path) 
        await set_source_status(redis, source_id, {"status": "completed", "progress": 100})
    except Exception as e:
        await set_source_status(redis, source_id, {"status": "failed", "error": str(e)})
        raise

async def ingest_source_text(ctx, text, user_id, source_id, source_title):
    redis = ctx["redis"]
    await set_source_status(redis, source_id, {"status": "processing", "progress": 0})
    try:
        await process_source_text(user_id, source_id, text, source_title)
        await set_source_status(redis, source_id, {"status": "completed", "progress": 100})
    except Exception as e:
        await set_source_status(redis, source_id, {"status": "failed", "error": str(e)})
        raise

async def ingest_source_url(ctx, user_id, source_id, url):
    redis = ctx["redis"]
    await set_source_status(redis, source_id, {"status": "processing", "progress": 0})
    try:
        await process_source_url(user_id, source_id, url)
        await set_source_status(redis, source_id, {"status": "completed", "progress": 100})
    except Exception as e:
        await set_source_status(redis, source_id, {"status": "failed", "error": str(e)})
        raise

class WorkerSettings:
    functions = [ingest_source_pdf, ingest_source_text, ingest_source_url]
    redis_settings = redis_settings
