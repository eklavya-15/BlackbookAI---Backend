from pydantic import BaseModel
from typing import Literal

class ChatMessage(BaseModel):
  role: Literal["system", "user", "assistant"]
  content: str

class ChatRequest(BaseModel):
    userId: str
    sourceIds: list[str]
    query: str
    conversationHistory: list[ChatMessage] 


