"""工作流数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON

from app.core.database import Base


class Workflow(Base):
    """工作流定义"""
    __tablename__ = "workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)

    engine = Column(String(30), default="local")

    nodes = Column(JSON, nullable=False, default=list)
    edges = Column(JSON, nullable=False, default=list)

    parameters = Column(JSON, default=dict)

    source_skill_id = Column(UUID(as_uuid=True))

    version = Column(Integer, default=1)

    tags = Column(JSON)
    category = Column(String(50))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    visibility = Column(String(20), default="private")

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowExecution(Base):
    """工作流执行记录"""
    __tablename__ = "workflow_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=False)

    status = Column(String(20), default="pending")

    inputs = Column(JSON)
    node_results = Column(JSON, default=dict)
    outputs = Column(JSON)

    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)

    error_message = Column(Text)
    failed_node = Column(String(50))

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
