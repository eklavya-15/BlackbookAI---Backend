# db/qdrant.py
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PayloadSchemaType
from dotenv import load_dotenv
import os

load_dotenv()

client = AsyncQdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY"),
)

async def init_user_collection(user_id: str) -> str:
    collection_name = f"blackbook_{user_id}"
    
    existing = [c.name for c in (await client.get_collections()).collections]

    if collection_name not in existing:
        # first time this user ingests — create fresh
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
        )
        await client.create_payload_index(
            collection_name=collection_name,
            field_name="source_id",
            field_schema=PayloadSchemaType.KEYWORD
        )

    return collection_name 

async def delete_user_collection(user_id: str):
    """Called by daily cron job."""
    await client.delete_collection(f"blackbook_{user_id}")

async def delete_all_collections(client):  # accepts client as arg
    collections = await client.get_collections()
    for col in collections.collections:
        if col.name.startswith("blackbook_"):
            await client.delete_collection(col.name)