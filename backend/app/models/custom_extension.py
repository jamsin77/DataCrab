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
    is_seed = Column(Boolean, default=False)  # seed=预置的，所有用户可见；非 seed=用户自建，私有
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
    flash_model = Column(String(100))
    vision_model = Column(String(100))
    embedding_model = Column(String(100))
    api_key_encrypted = Column(Text)
    code = Column(Text)
    is_seed = Column(Boolean, default=False)  # seed=预置的，所有用户可见；非 seed=用户自建，私有
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class UserLLMConfig(Base):
    """用户级 LLM 配置 — 每个用户自己的 Provider/API Key/模型选择（API Key 加密存储）"""
    __tablename__ = "user_llm_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    api_key_encrypted = Column(Text)
    api_base = Column(String(255))
    model = Column(String(100))
    flash_model = Column(String(100))
    vision_model = Column(String(100))
    embedding_model = Column(String(100))
    fallback_models = Column(JSON, default=list)  # [{provider, api_base, model, api_key_encrypted}]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
