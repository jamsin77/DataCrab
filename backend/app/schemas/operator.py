"""算子相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime
from uuid import UUID


class OperatorCreate(BaseModel):
    name: str = Field(..., max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    inputs: Optional[Any] = None
    outputs: Optional[Any] = None
    parameters: Optional[Any] = None
    execution_config: Optional[Any] = None
    code_template: Optional[str] = None
    tags: Optional[List[str]] = None
    visibility: Optional[str] = "public"


class OperatorUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    inputs: Optional[Any] = None
    outputs: Optional[Any] = None
    parameters: Optional[Any] = None
    execution_config: Optional[Any] = None
    code_template: Optional[str] = None
    tags: Optional[List[str]] = None
    visibility: Optional[str] = None


class OperatorResponse(BaseModel):
    id: UUID
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    inputs: Optional[Any] = None
    outputs: Optional[Any] = None
    parameters: Optional[Any] = None
    execution_config: Optional[Any] = None
    code_template: Optional[str] = None
    script_content: Optional[str] = None
    script_filename: Optional[str] = None
    function_name: Optional[str] = None
    version: str = "1.0.0"
    tags: Optional[List[str]] = None
    visibility: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OperatorScriptUpdate(BaseModel):
    script_content: str = Field(..., description="Python脚本内容")


class OperatorDebugRequest(BaseModel):
    test_data: Any = Field(None, description="测试输入数据")
    parameters: Optional[Dict[str, Any]] = Field(None, description="执行参数")


class OperatorDebugResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    stdout: Optional[str] = None
    execution_time_ms: Optional[float] = None


class OperatorGenerateRequest(BaseModel):
    prompt: str = Field(..., description="自然语言描述，用于生成算子脚本")


class OperatorModifyRequest(BaseModel):
    instruction: str = Field(..., description="自然语言修改指令")


class OperatorCloneRequest(BaseModel):
    name: str = Field(..., max_length=100, description="新算子名称")


class OperatorDebugChatRequest(BaseModel):
    message: str = Field(..., description="用户调试消息")
    history: Optional[List[Dict[str, str]]] = Field(default=[], description="对话历史")
    context: Optional[Dict[str, Any]] = Field(default={}, description="调试上下文")


class SimilarOperatorCheckRequest(BaseModel):
    prompt: str = Field(..., description="用户的需求描述，用于检测是否有相似算子可复用")


class SimilarOperatorItem(BaseModel):
    id: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    similarity: float = Field(..., description="相似度 0~1")
    can_use: bool = Field(..., description="当前用户是否有权限使用")
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None


class SimilarOperatorCheckResponse(BaseModel):
    has_similar: bool
    operators: List[SimilarOperatorItem] = []