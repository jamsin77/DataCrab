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
    is_virtual = Column(Boolean, default=False)  # 虚拟数据源（聊天上传，受保护不可修改/删除/测试/同步）

    # 关系
    creator = relationship("User", back_populates="data_sources")
    table_metadata = relationship("TableMetadata", back_populates="data_source", lazy="noload")


class TableMetadata(Base):
    """数据集元数据模型（一个数据源的一张表/文件 = 一条元数据记录）"""
    __tablename__ = "table_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    data_source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)

    # ========== 技术元数据 ==========
    table_name = Column(String(200), nullable=False)
    table_type = Column(String(50))
    storage_format = Column(String(50))
    storage_location = Column(String(500))
    source_connector = Column(String(50))
    table_schema = Column(JSON)
    primary_keys = Column(JSON)
    indexes = Column(JSON)
    row_count = Column(BigInteger)
    size_bytes = Column(BigInteger)
    column_count = Column(Integer)
    sample_data = Column(JSON)
    column_stats = Column(JSON)
    partition_info = Column(JSON)

    # ========== 业务元数据 ==========
    business_name = Column(String(200))
    business_description = Column(Text)
    business_tags = Column(JSON)
    business_purpose = Column(Text)
    source_system = Column(String(200))
    data_domain = Column(String(100))
    data_owner = Column(String(100))
    data_steward = Column(String(100))
    security_level = Column(String(20))
    retention_policy = Column(String(200))

    # ========== 运营元数据 ==========
    last_synced_at = Column(DateTime)
    data_updated_at = Column(DateTime)  # 数据源端数据的真实最后更新时间（区别于元数据记录的 updated_at）
    last_accessed_at = Column(DateTime)
    access_count = Column(Integer, default=0)
    quality_rules = Column(JSON)
    quality_score = Column(Float)
    quality_details = Column(JSON)
    lineage = Column(JSON)

    # AI 补充
    ai_enriched = Column(Boolean, default=False)
    ai_enriched_at = Column(DateTime)
    schema_hash = Column(String(64))  # 表结构的哈希值，schema 未变则跳过 AI 增强

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    data_source = relationship("DataSource", back_populates="table_metadata")
