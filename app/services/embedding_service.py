from qdrant_client.models import PointStruct
from app.core.qdrant import client
from app.services.llm_service import embed_texts
import hashlib

async def embedding_chunks(chunks, collection_name):
    BATCH_SIZE = 100

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i+BATCH_SIZE]
        texts = [chunk.page_content for chunk in batch]

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
            for chunk, vector in zip(batch, vectors)
        ]

        await client.upsert(
            collection_name=collection_name,
            points=points
        )
        