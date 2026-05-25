from fastapi import APIRouter
from app.schemas.chat import ChatRequest
from app.services.retrieval_service import retrieve_answer

router = APIRouter()

@router.post("")
async def chat(payload: ChatRequest):

    return await retrieve_answer(
        query=payload.query,
        user_id=payload.userId,
        active_source_ids=payload.sourceIds,
        conversation_history=payload.conversationHistory
    )