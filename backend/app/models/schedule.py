"""调度数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class Schedule(Base):
    """调度配置模型"""
    __tablename__ = "schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code_id = Column(UUID(as_uuid=True), ForeignKey("composed_codes.id", ondelete="CASCADE"), index=True)

    # 调度类型
    schedule_type = Column(String(20), nullable=False)  # cron, event, manual

    # Cron配置
    cron_expression = Column(String(100))
    timezone = Column(String(50), default="Asia/Shanghai")

    # 事件配置
    event_config = Column(JSON)

    # 执行配置
    max_retries = Column(Integer, default=3)
    retry_interval = Column(Integer, default=60)
    timeout = Column(Integer, default=3600)

    # 状态
    status = Column(String(20), index=True)  # active, paused, stopped
    last_run_at = Column(DateTime)
    next_run_at = Column(DateTime)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    code = relationship("ComposedCode", back_populates="schedules")
    executions = relationship("TaskExecution", back_populates="schedule", lazy="selectin")


class TaskExecution(Base):
    """任务执行模型"""
    __tablename__ = "task_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="CASCADE"), index=True)
    code_id = Column(UUID(as_uuid=True), ForeignKey("composed_codes.id"))

    # 执行信息
    status = Column(String(20), nullable=False, index=True)  # pending, running, success, failed
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration = Column(Integer)

    # 执行结果
    result = Column(JSON)
    error_message = Column(Text)

    # 重试信息
    retry_count = Column(Integer, default=0)

    # 执行日志
    logs = Column(Text)

    # 血缘关系
    input_data = Column(JSON)
    output_data = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    schedule = relationship("Schedule", back_populates="executions")
