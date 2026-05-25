from qdrant_client.models import Filter, FieldCondition, MatchAny
from app.core.qdrant import client
from app.services.llm_service import embed_user_query, get_llm_response

async def retrieve_answer(query: str, user_id: str, active_source_ids: list[str], conversation_history: list | None = None) -> str:

    query_embedding = await embed_user_query(query)

    relevant_context = await search_relevant_context(query_embedding, user_id, active_source_ids)

    answer = await get_llm_response(query, relevant_context, conversation_history)

    return answer



async def search_relevant_context( query_embedding: list, user_id: str, active_source_ids: list[str] | None, top_k: int = 3) -> list:

    COLLECTION_NAME = f"blackbook_{user_id}"

    results = await client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_embedding,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="source_id",
                    match=MatchAny(any=active_source_ids)
                )
            ]
        ),
        with_payload=True,
        limit=top_k
    )
    return [
        {
            "text": r.payload.get("text"),
            "source_id": r.payload.get("source_id"),
            "source_name": r.payload.get("source_name"),
            "source_type": r.payload.get("source_type"),
            "page": r.payload.get("page"),
            "url": r.payload.get("url"),
            "section": r.payload.get("section"),
            "score": r.score
        }
        for r in results.points 
    ]