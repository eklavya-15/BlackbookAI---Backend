from pydantic import BaseModel

class TextSourceRequest(BaseModel):
    type: str
    text: str
    sourceTitle: str | None = None

class URLSourceRequest(BaseModel):
    type: str 
    url: str