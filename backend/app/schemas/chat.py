"""对话相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID


class ChatSessionCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)


class ChatSessionUpdate(BaseModel):
    title: str = Field(..., max_length=200)


class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    session_id: UUID
    content: str


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    code_blocks: Optional[List[dict]] = None
    table_data: Optional[dict] = None
    charts: Optional[List[dict]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class StreamMessage(BaseModel):
    type: str  # content, code_block, table, chart, error, done
    content: str = ""
    data: Optional[Any] = None
