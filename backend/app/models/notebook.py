"""Notebook数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class Notebook(Base):
    """Notebook模型"""
    __tablename__ = "notebooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name = Column(String(200), nullable=False)
    cells = Column(JSON, nullable=False)  # 单元格列表
    kernel = Column(String(50), default="python3")
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="notebooks")
    versions = relationship("NotebookVersion", back_populates="notebook", lazy="selectin")


class NotebookVersion(Base):
    """Notebook版本历史模型"""
    __tablename__ = "notebook_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notebook_id = Column(UUID(as_uuid=True), ForeignKey("notebooks.id", ondelete="CASCADE"), index=True)
    version = Column(Integer, nullable=False)
    cells = Column(JSON, nullable=False)
    change_description = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    notebook = relationship("Notebook", back_populates="versions")
