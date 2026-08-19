"""流程相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime
from uuid import UUID


class SkillCall(BaseModel):
    skill_id: Optional[str] = None
    skill_name: str = ""
    script: str = ""
    function: str = ""
    line: int = 0


class PipelineCreate(BaseModel):
    name: str = Field(..., max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    main_code: str = ""
    entry_function: str = "main"
    parameters: Optional[List[Dict[str, Any]]] = None
    skill_calls: Optional[List[SkillCall]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = "private"


class PipelineUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    main_code: Optional[str] = None
    entry_function: Optional[str] = None
    parameters: Optional[List[Dict[str, Any]]] = None
    skill_calls: Optional[List[SkillCall]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = None


class PipelineResponse(BaseModel):
    id: UUID
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    main_code: Optional[str] = None
    entry_function: str = "main"
    parameters: Optional[List[Any]] = None
    skill_calls: Optional[List[Any]] = None
    source_skill_id: Optional[UUID] = None
    version: int = 1
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = None
    is_active: bool = True
    is_builtin: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PipelineRunRequest(BaseModel):
    inputs: Optional[Dict[str, Any]] = None


class PipelineFromSkillRequest(BaseModel):
    display_name: Optional[str] = None
    # mode: skip(默认，查重命中则取消) / overwrite(覆盖现有) / rename(另存为新名)
    mode: Optional[str] = "skip"
    new_name: Optional[str] = None  # mode=rename 时的新 display_name


class PipelineExecutionResponse(BaseModel):
    id: UUID
    pipeline_id: UUID
    status: str
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    logs: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PipelineDebugChatRequest(BaseModel):
    message: str = Field(..., description="用户调试消息")
    history: Optional[List[Dict[str, str]]] = Field(default=[], description="对话历史")
    context: Optional[Dict[str, Any]] = Field(default={}, description="调试上下文")
