from app.core.redis import redis_settings
from app.services.ingestion_service import process_source_pdf, process_source_text, process_source_url

async def ingest_source_pdf(ctx, r2_key, source_name, user_id, source_id):
    await process_source_pdf(ctx, user_id, source_id, source_name, r2_key)

async def ingest_source_text(ctx, text, user_id, source_id, source_title):
    await process_source_text(ctx, user_id, source_id, text, source_title)

async def ingest_source_url(ctx, user_id, source_id, url):
    await process_source_url(ctx, user_id, source_id, url)

class WorkerSettings:
    functions = [ingest_source_pdf, ingest_source_text, ingest_source_url]
    redis_settings = redis_settings
