from fastapi import APIRouter
from app.schemas.chat import ChatRequest
from app.services.retrieval_service import retrieve_answer
from app.services.llm_service import get_llm_response_stream
from fastapi.responses import StreamingResponse
from app.services.llm_service import embed_user_query
from app.services.retrieval_service import search_relevant_context

router = APIRouter()

@router.post("/no-stream")
async def chat(payload: ChatRequest):

    return await retrieve_answer(
        query=payload.query,
        user_id=payload.userId,
        active_source_ids=payload.sourceIds,
        conversation_history=payload.conversationHistory
    )

@router.post("")
async def chat(payload: ChatRequest):

    query_embedding = await embed_user_query(payload.query)

    relevant_context = await search_relevant_context(query_embedding, payload.userId, payload.sourceIds)

    return StreamingResponse(
        get_llm_response_stream(
            query=payload.query,
            relevant_context=relevant_context,
            conversation_history=payload.conversationHistory,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )