"""组合流程数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class ComposedCode(Base):
    """组合流程模型"""
    __tablename__ = "composed_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)

    # 自然语言描述
    nl_description = Column(Text, nullable=False)

    # 意图识别结果
    intent = Column(JSON)

    # 流程定义(基于Skills)
    steps = Column(JSON)

    # 流程元数据
    input_schema = Column(JSON)
    output_schema = Column(JSON)

    # 验证结果
    validation_result = Column(JSON)

    # 版本管理
    version = Column(Integer, default=1)

    # 执行统计
    execution_count = Column(Integer, default=0)
    last_executed_at = Column(DateTime)

    # 权限
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    visibility = Column(String(20))

    # 元数据
    tags = Column(JSON)
    category = Column(String(50), index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
