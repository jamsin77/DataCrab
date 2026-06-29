"""调度相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from uuid import UUID


class ScheduleCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    task_type: str = Field(..., pattern="^(pipeline|operator|skill)$")
    task_target_id: UUID
    task_params: Optional[dict] = None
    schedule_type: str = Field(..., pattern="^(cron|interval|manual)$")
    cron_expression: Optional[str] = None
    timezone: str = "Asia/Shanghai"
    interval_seconds: Optional[int] = None
    event_config: Optional[dict] = None
    max_retries: int = 3
    retry_interval: int = 60
    timeout: int = 3600
    concurrent_runs: int = 1


class ScheduleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    task_params: Optional[dict] = None
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    interval_seconds: Optional[int] = None
    event_config: Optional[dict] = None
    max_retries: Optional[int] = None
    retry_interval: Optional[int] = None
    timeout: Optional[int] = None
    concurrent_runs: Optional[int] = None
    status: Optional[str] = None


class ScheduleResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    task_type: str
    task_target_id: UUID
    task_params: Optional[dict] = None
    schedule_type: str
    cron_expression: Optional[str] = None
    timezone: str = "Asia/Shanghai"
    interval_seconds: Optional[int] = None
    event_config: Optional[dict] = None
    max_retries: int = 3
    retry_interval: int = 60
    timeout: int = 3600
    concurrent_runs: int = 1
    status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskExecutionCreate(BaseModel):
    schedule_id: UUID
    task_type: str
    task_target_id: UUID
    trigger_type: str = "manual"
    triggered_by: Optional[UUID] = None


class TaskExecutionResponse(BaseModel):
    id: UUID
    schedule_id: UUID
    task_type: str
    task_target_id: UUID
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration: Optional[int] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    exit_code: Optional[int] = None
    retry_count: int = 0
    logs: Optional[str] = None
    input_data: Optional[dict] = None
    output_data: Optional[dict] = None
    trigger_type: str = "schedule"
    triggered_by: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ManualTriggerRequest(BaseModel):
    task_params: Optional[dict] = None


class CronValidateRequest(BaseModel):
    cron_expression: str


class CronValidateResponse(BaseModel):
    valid: bool
    message: Optional[str] = None
    next_runs: Optional[list[datetime]] = None
