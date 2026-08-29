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
    # 用户点「直接处理」时为 True，跳过 classify+匹配直接走 Agent
    direct_execute: bool = False
    # 用户点「使用技能」时为 True，走技能调试模式调用技能
    use_skill: bool = False
    # 用户从 data_suggestion 中选择的数据（点"选择此数据"后发送消息时带上，跳过名称匹配和表匹配）
    selected_datasource_id: Optional[str] = None
    selected_table_name: Optional[str] = None
    # 用户从 target_suggestion 中选择的目标表
    target_datasource_id: Optional[str] = None
    target_datasource_name: Optional[str] = None
    target_table_name: Optional[str] = None
    target_write_mode: Optional[str] = None
    # 用户从 skill_suggestion 中选择的技能/流程
    selected_skill_id: Optional[str] = None
    selected_skill_name: Optional[str] = None
    selected_skill_type: Optional[str] = None  # "skill" / "pipeline"


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
