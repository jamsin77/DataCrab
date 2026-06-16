"""数据源数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, Float, ForeignKey, BigInteger
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class DataSource(Base):
    """数据源模型"""
    __tablename__ = "data_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False, index=True)  # mysql, postgres, csv, excel, etc.
    connection_config = Column(JSON, nullable=False)  # 加密存储
    tech_metadata = Column(JSON)  # 技术元数据
    business_metadata = Column(JSON)  # 业务元数据
    security_level = Column(String(20))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # 关系
    creator = relationship("User", back_populates="data_sources")
    table_metadata = relationship("TableMetadata", back_populates="data_source", lazy="selectin")


class TableMetadata(Base):
    """表元数据模型"""
    __tablename__ = "table_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    data_source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    table_name = Column(String(200), nullable=False)
    table_type = Column(String(50))
    table_schema = Column(JSON)
    row_count = Column(BigInteger)
    size_bytes = Column(BigInteger)
    business_name = Column(String(200))
    business_description = Column(Text)
    data_domain = Column(String(100))
    data_owner = Column(String(100))
    quality_rules = Column(JSON)
    quality_score = Column(Float)
    security_level = Column(String(20))
    lineage = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    data_source = relationship("DataSource", back_populates="table_metadata")
