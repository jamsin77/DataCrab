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


# ===== 自然语言数据处理相关 =====

class NLDataProcessRequest(BaseModel):
    """自然语言数据处理请求"""
    natural_language: str = Field(..., description="自然语言描述")
    data: Optional[List[dict]] = Field(None, description="输入数据(JSON数组格式)")
    file_id: Optional[UUID] = Field(None, description="数据文件ID")
    session_id: Optional[UUID] = Field(None, description="会话ID")


class NLDataProcessResponse(BaseModel):
    """自然语言数据处理响应"""
    success: bool
    output_data: Optional[List[dict]] = None
    pipeline_name: str = ""
    steps: List[dict] = []
    explanation: str = ""
    execution_time: float = 0.0
    error: Optional[str] = None
    logs: List[str] = []


class NLStreamEvent(BaseModel):
    """流式事件"""
    type: str  # init, progress, matched_skills, pipeline_plan, parameter_inferred, step_start, step_complete, complete, error
    message: str = ""
    data: Optional[Any] = None
