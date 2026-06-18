"""工作流相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime
from uuid import UUID


class WorkflowNode(BaseModel):
    id: str
    type: str = "skill"
    skill_id: Optional[str] = None
    name: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    position: Dict[str, int] = Field(default_factory=lambda: {"x": 0, "y": 0})
    retry: int = 0
    timeout: int = 300


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    source_port: Optional[str] = "output"
    target_port: Optional[str] = "input"
    condition: Optional[str] = None


class WorkflowCreate(BaseModel):
    name: str = Field(..., max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    engine: str = "local"
    nodes: List[WorkflowNode] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)
    parameters: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = "private"


class WorkflowUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    engine: Optional[str] = None
    nodes: Optional[List[WorkflowNode]] = None
    edges: Optional[List[WorkflowEdge]] = None
    parameters: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = None


class WorkflowResponse(BaseModel):
    id: UUID
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    engine: str = "local"
    nodes: List[Any] = []
    edges: List[Any] = []
    parameters: Optional[Dict[str, Any]] = None
    source_skill_id: Optional[UUID] = None
    version: int = 1
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    visibility: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowRunRequest(BaseModel):
    inputs: Optional[Dict[str, Any]] = None


class WorkflowValidationResult(BaseModel):
    valid: bool
    errors: List[str] = []
    warnings: List[str] = []


class WorkflowExecutionResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    status: str
    inputs: Optional[Dict[str, Any]] = None
    node_results: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    failed_node: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
