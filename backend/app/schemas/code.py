"""组合流程相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class CodeStepSchema(BaseModel):
    id: str
    skill_id: UUID
    skill_name: str
    parameters: dict
    depends_on: Optional[List[str]] = None


class ComposedCodeCreate(BaseModel):
    name: str = Field(..., max_length=100)
    nl_description: str
    steps: Optional[List[dict]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = "public"


class ComposedCodeGenerateRequest(BaseModel):
    nl_description: str
    context: Optional[dict] = None


class ComposedCodeResponse(BaseModel):
    id: UUID
    name: str
    nl_description: str
    intent: Optional[dict] = None
    steps: Optional[List[dict]] = None
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    validation_result: Optional[dict] = None
    version: int = 1
    execution_count: int = 0
    last_executed_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    visibility: Optional[str] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CodeExecuteRequest(BaseModel):
    parameters: Optional[dict] = None


class CodeExecuteResponse(BaseModel):
    code_id: UUID
    status: str
    results: Optional[dict] = None
    error: Optional[str] = None
