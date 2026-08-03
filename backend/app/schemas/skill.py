"""技能相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime
from uuid import UUID


class SkillCreate(BaseModel):
    name: str = Field(..., max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = "public"


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = None


class SkillResponse(BaseModel):
    id: UUID
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    skill_path: Optional[str] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    version: str = "1.0.0"
    visibility: Optional[str] = None
    usage_count: int = 0
    success_rate: float = 1.0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SkillDetailResponse(SkillResponse):
    skill_md: Optional[str] = None
    scripts: List[Dict[str, Any]] = []
    references: List[Dict[str, Any]] = []
    assets: List[str] = []


class SkillSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    category: Optional[str] = None
    tags: Optional[List[str]] = None


class SkillRunRequest(BaseModel):
    script_name: str = Field(default="main.py")
    datasource_id: Optional[str] = None
    table_name: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)
    input_data: Optional[Any] = None


class SkillRunNLRequest(BaseModel):
    query: str = Field(..., description="自然语言调用指令")
    script_name: str = Field(default="main.py")
    datasource_id: Optional[str] = None
    table_name: Optional[str] = None


class SkillRunResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    stdout: Optional[str] = None
    execution_time_ms: Optional[float] = None


class SkillGenerateRequest(BaseModel):
    prompt: str = Field(..., description="自然语言描述，用于生成完整的Skill")


class SkillCloneRequest(BaseModel):
    name: str = Field(..., max_length=100, description="新技能名称")


class SkillDocUpdate(BaseModel):
    content: str = Field(..., description="SKILL.md 完整内容")


class SkillScriptUpdate(BaseModel):
    content: str = Field(..., description="脚本内容")


class SkillModifyRequest(BaseModel):
    instruction: str = Field(..., description="自然语言修改指令")


class SkillDebugChatRequest(BaseModel):
    message: str = Field(..., description="用户调试消息")
    history: list = Field(default_factory=list, description="对话历史 [{role, content}]")
    script_name: str = Field(default="main.py", description="脚本名称")
    datasource_id: Optional[str] = Field(None, description="数据源ID")
    table_name: Optional[str] = Field(None, description="表名")
    context: Optional[dict] = Field(None, description="左侧执行面板上下文")


class SkillScriptInfo(BaseModel):
    name: str
    content: str
    size: int


class SkillParamDef(BaseModel):
    name: str
    display_name: Optional[str] = None
    type: str = "str"
    required: bool = False
    default: Optional[Any] = None
    description: Optional[str] = None
    example: Optional[str] = None
    is_datasource: bool = False
    is_table: bool = False
    is_list: bool = False


class SimilarSkillCheckRequest(BaseModel):
    prompt: str = Field(..., description="用户的需求描述，用于检测是否有相似技能可复用")


class SimilarSkillItem(BaseModel):
    id: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    similarity: float = Field(..., description="相似度 0~1")
    can_use: bool = Field(..., description="当前用户是否有权限使用")
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None


class SimilarSkillCheckResponse(BaseModel):
    has_similar: bool
    skills: List[SimilarSkillItem] = []