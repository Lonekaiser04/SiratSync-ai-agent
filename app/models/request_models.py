from pydantic import BaseModel, validator
from typing import Optional, List, Dict

class ChatRequest(BaseModel):
    user_id:     str
    message:     str
    user_name:   Optional[str] = None
    app_version: Optional[str] = "2.0"
    context:     Optional[str] = None

    @validator("message")
    def message_not_empty_and_not_too_long(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("message cannot be empty")
        if len(v) > 2000:
            raise ValueError("message too long (max 2000 characters)")
        return v

    @validator("user_id")
    def user_id_valid(cls, v):
        v = v.strip()
        if not v or len(v) > 128:
            raise ValueError("invalid user_id")
        return v

    @validator("context")
    def context_length(cls, v):
        if v and len(v) > 4000:
            return v[:4000]
        return v


class SummarizeRequest(BaseModel):
    user_id:      str
    post_content: str

    @validator("post_content")
    def content_length(cls, v):
        v = v.strip()
        if len(v) > 5000:
            raise ValueError("post_content too long (max 5000 characters)")
        return v