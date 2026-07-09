"""扩展模型 — 数据源连接器和 LLM Provider"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON

from app.core.database import Base


class CustomConnector(Base):
    """数据源连接器 — AI 生成代码，沙箱加载"""
    __tablename__ = "custom_connectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False, unique=True, index=True)
    display_name = Column(String(100))
    description = Column(Text)
    code = Column(Text, nullable=False)
    config_template = Column(JSON, default=list)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class LLMProvider(Base):
    """LLM Provider — 所有 Provider 统一存储，地位平等"""
    __tablename__ = "llm_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_name = Column(String(50), nullable=False, unique=True, index=True)
    display_name = Column(String(100))
    description = Column(Text)
    api_base = Column(String(255))
    models = Column(JSON, default=list)
    default_model = Column(String(100))
    fast_model = Column(String(100))
    api_key_encrypted = Column(Text)
    code = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
