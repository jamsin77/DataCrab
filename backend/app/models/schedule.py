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
    name = Column(String(100), nullable=False)
    description = Column(Text)
    
    # 任务类型和目标
    task_type = Column(String(20), nullable=False)  # pipeline, operator, skill
    task_target_id = Column(UUID(as_uuid=True), nullable=False)  # 对应的pipeline/operator/skill ID
    task_params = Column(JSON)  # 执行参数

    # 调度类型
    schedule_type = Column(String(20), nullable=False)  # cron, interval, manual

    # Cron配置
    cron_expression = Column(String(100))
    timezone = Column(String(50), default="Asia/Shanghai")
    
    # 间隔配置（秒）
    interval_seconds = Column(Integer)

    # 事件配置
    event_config = Column(JSON)

    # 执行配置
    max_retries = Column(Integer, default=3)
    retry_interval = Column(Integer, default=60)
    timeout = Column(Integer, default=3600)
    concurrent_runs = Column(Integer, default=1)  # 允许并发数
    run_mode = Column(String(20), default="normal")  # normal: 普通运行, auto_fix: 自修复运行(走 DataProcessor+DataInspector)

    # 状态
    status = Column(String(20), index=True, default="active")  # active, paused, stopped
    last_run_at = Column(DateTime)
    next_run_at = Column(DateTime)
    last_run_status = Column(String(20))  # success, failed, running

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    executions = relationship("TaskExecution", back_populates="schedule", lazy="selectin", order_by="desc(TaskExecution.created_at)")


class TaskExecution(Base):
    """任务执行模型"""
    __tablename__ = "task_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="CASCADE"), index=True)
    
    # 任务信息
    task_type = Column(String(20), nullable=False)  # pipeline, operator, skill
    task_target_id = Column(UUID(as_uuid=True), nullable=False)

    # 执行信息
    status = Column(String(20), nullable=False, index=True)  # pending, running, success, failed, timeout
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration = Column(Integer)  # 秒

    # 执行结果
    result = Column(JSON)
    error_message = Column(Text)
    exit_code = Column(Integer)

    # 重试信息
    retry_count = Column(Integer, default=0)

    # 执行日志
    logs = Column(Text)

    # 血缘关系
    input_data = Column(JSON)
    output_data = Column(JSON)
    
    # 触发方式
    trigger_type = Column(String(20), default="schedule")  # schedule, manual, event
    triggered_by = Column(UUID(as_uuid=True))  # 触发用户ID

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    schedule = relationship("Schedule", back_populates="executions")
