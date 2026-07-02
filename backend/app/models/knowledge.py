"""文档知识库数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class KnowledgeDocument(Base):
    """知识库文档"""
    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(500), nullable=False)
    file_type = Column(String(20))
    file_path = Column(String(1000))
    size_bytes = Column(Integer, default=0)
    content_hash = Column(String(64))
    chunk_count = Column(Integer, default=0)
    status = Column(String(20), default="processing")  # processing / ready / failed
    error = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    """文档切片（向量元信息；向量本身存于 ChromaDB）"""
    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    chunk_index = Column(Integer, default=0)
    content = Column(Text, nullable=False)
    location = Column(String(200))  # 证据链定位：如 “段落 3” / “Sheet1 行1-50”
    char_start = Column(Integer, default=0)
    char_end = Column(Integer, default=0)
    chroma_id = Column(String(100))  # ChromaDB 中的向量 id
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("KnowledgeDocument", back_populates="chunks")
