"""流程数据模型 - Pipeline = Python 主函数"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON

from app.core.database import Base


class Pipeline(Base):
    """流程定义 - 一个完整的 Python 主函数"""
    __tablename__ = "pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)

    main_code = Column(Text, nullable=False)
    entry_function = Column(String(100), default="main")
    parameters = Column(JSON, default=list)
    skill_calls = Column(JSON, default=list)

    source_skill_id = Column(UUID(as_uuid=True))
    related_skill_ids = Column(JSON, default=list)

    version = Column(Integer, default=1)

    tags = Column(JSON)
    pipeline_type = Column(String(20), index=True)  # analysis / processing / system
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    visibility = Column(String(20), default="private")

    is_active = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PipelineExecution(Base):
    """流程执行记录"""
    __tablename__ = "pipeline_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id = Column(UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False)

    status = Column(String(20), default="pending")

    inputs = Column(JSON)
    outputs = Column(JSON)

    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)

    error_message = Column(Text)
    logs = Column(Text)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
