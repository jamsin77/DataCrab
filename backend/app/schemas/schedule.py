"""调度相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class ScheduleCreate(BaseModel):
    code_id: UUID
    schedule_type: str = Field(..., max_length=20)  # cron, event, manual
    cron_expression: Optional[str] = None
    timezone: str = "Asia/Shanghai"
    event_config: Optional[dict] = None
    max_retries: int = 3
    retry_interval: int = 60
    timeout: int = 3600


class ScheduleUpdate(BaseModel):
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    event_config: Optional[dict] = None
    max_retries: Optional[int] = None
    retry_interval: Optional[int] = None
    timeout: Optional[int] = None
    status: Optional[str] = None


class ScheduleResponse(BaseModel):
    id: UUID
    code_id: UUID
    schedule_type: str
    cron_expression: Optional[str] = None
    timezone: str = "Asia/Shanghai"
    event_config: Optional[dict] = None
    max_retries: int = 3
    retry_interval: int = 60
    timeout: int = 3600
    status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TaskExecutionResponse(BaseModel):
    id: UUID
    schedule_id: UUID
    code_id: Optional[UUID] = None
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration: Optional[int] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True
