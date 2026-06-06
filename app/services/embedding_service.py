import traceback
from qdrant_client.models import PointStruct
from app.core.qdrant import client
from app.services.llm_service import embed_texts
import hashlib, traceback

async def embedding_chunks(chunks_batch, collection_name):
    try:
        print(chunks_batch[0])
        texts = [chunk.page_content for chunk in chunks_batch]
        vectors = await embed_texts(texts)

        points = [
            PointStruct(
                id=hashlib.md5(
                    chunk.page_content.encode("utf-8")
                ).hexdigest(),

                vector=vector,

                payload={
                    "text": chunk.page_content,
                    **chunk.metadata
                }
            )
            for chunk, vector in zip(chunks_batch, vectors)
        ]

        await client.upsert(
            collection_name=collection_name,
            points=points
        )
    except Exception:
        traceback.print_exc()