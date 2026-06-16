"""文件链接数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class FileLink(Base):
    """文件链接模型"""
    __tablename__ = "file_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)  # 链接名称
    path = Column(String(500), nullable=False)  # 本地文件路径
    description = Column(Text)  # 描述
    link_type = Column(String(20), default="file")  # file, directory
    is_public = Column(Boolean, default=False)  # 是否公开
    allowed_extensions = Column(JSON)  # 允许的文件扩展名列表
    file_metadata = Column(JSON)  # 元数据（文件大小、修改时间等）
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # 关系
    creator = relationship("User", back_populates="file_links")
