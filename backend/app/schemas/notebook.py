"""Notebook相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID


class NotebookCellSchema(BaseModel):
    id: str
    type: str = "code"  # code, markdown
    content: str = ""
    output: Optional[dict] = None
    is_executing: bool = False
    execution_time: Optional[int] = None
    execution_order: Optional[int] = None


class NotebookCreate(BaseModel):
    name: str = Field(..., max_length=200)
    kernel: str = "python3"


class NotebookUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    cells: Optional[List[NotebookCellSchema]] = None
    kernel: Optional[str] = None


class NotebookResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    cells: List[dict]
    kernel: str
    version: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CellExecuteRequest(BaseModel):
    cell_id: str
    code: str


class CellExecuteResponse(BaseModel):
    cell_id: str
    output: Optional[dict] = None
    error: Optional[str] = None
    execution_time: Optional[int] = None


class VariableInfo(BaseModel):
    name: str
    type: str
    value: Any
    size: int


class NotebookVersionResponse(BaseModel):
    id: UUID
    version: int
    change_description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
