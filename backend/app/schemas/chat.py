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
    context: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    session_id: UUID
    content: str
    # 用户本次对话上传的附件（datasource_id 列表），后端注入到 user message 前缀让 Agent 知道
    attachments: Optional[List[str]] = None
    # 跳过技能/流程/数据匹配（用户点「直接对话」或「继续处理」时为 True）
    skip_match: bool = False
    # 跳过指定匹配步骤（用户点「继续」时带上已匹配过的步骤，如 ["tables", "pipelines"]）
    skip_steps: List[str] = Field(default_factory=list)
    # 用户从 data_suggestion 中选择的数据（点"选择此数据"后发送消息时带上，跳过名称匹配和表匹配）
    selected_datasource_id: Optional[str] = None
    selected_table_name: Optional[str] = None


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    code_blocks: Optional[List[dict]] = None
    table_data: Optional[dict] = None
    charts: Optional[List[dict]] = None
    meta: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class StreamMessage(BaseModel):
    type: str  # content, code_block, table, chart, error, done
    content: str = ""
    data: Optional[Any] = None
