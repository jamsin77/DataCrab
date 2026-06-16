"""数据源相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, Any, List
from datetime import datetime
from uuid import UUID


class DataSourceCreate(BaseModel):
    name: str = Field(..., max_length=100)
    type: str = Field(..., max_length=50)
    connection_config: dict
    business_metadata: Optional[dict] = None
    security_level: Optional[str] = None


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    connection_config: Optional[dict] = None
    business_metadata: Optional[dict] = None
    security_level: Optional[str] = None
    is_active: Optional[bool] = None


class DataSourceResponse(BaseModel):
    id: UUID
    name: str
    type: str
    connection_config: dict
    tech_metadata: Optional[dict] = None
    business_metadata: Optional[dict] = None
    security_level: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True


class ConnectionTestResult(BaseModel):
    success: bool
    message: str
    details: Optional[dict] = None


class TableMetadataResponse(BaseModel):
    id: UUID
    table_name: str
    table_type: Optional[str] = None
    table_schema: Optional[dict] = None
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None
    business_name: Optional[str] = None
    quality_score: Optional[float] = None

    class Config:
        from_attributes = True


class TreeNode(BaseModel):
    id: str
    label: str
    type: str  # database, table, column
    children: Optional[List["TreeNode"]] = None
    metadata: Optional[dict] = None


class TableDataResponse(BaseModel):
    columns: List[dict]
    rows: List[dict]
    total: int
    page: int
    page_size: int


class TableStatsResponse(BaseModel):
    row_count: int
    column_count: int
    size_bytes: int
    quality_score: Optional[float] = None
    column_stats: Optional[List[dict]] = None


class QualityAnalysisResponse(BaseModel):
    completeness: float
    consistency: float
    issues: List[dict]
    suggestions: List[dict]
