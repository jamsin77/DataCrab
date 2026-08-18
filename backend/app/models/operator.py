"""算子数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON

from app.core.database import Base


class Operator(Base):
    """算子模型 - 基于上传Python脚本自动解析生成"""
    __tablename__ = "operators"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)
    category = Column(String(50))

    inputs = Column(JSON)
    outputs = Column(JSON)
    parameters = Column(JSON)

    execution_config = Column(JSON)
    code_template = Column(Text)

    script_content = Column(Text)
    script_filename = Column(String(200))
    function_name = Column(String(100))

    version = Column(String(20), default="1.0.0")
    tags = Column(JSON)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    visibility = Column(String(20))
    permissions = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)