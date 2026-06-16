"""技能数据模型 - 遵循 Agent Skills 开放标准"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class Skill(Base):
    """技能模型 - 管理 Skill 包（文件夹）"""
    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)

    skill_path = Column(String(500))

    tags = Column(JSON)
    category = Column(String(50), index=True)

    version = Column(String(20), default="1.0.0")
    author = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    visibility = Column(String(20), index=True)

    usage_count = Column(Integer, default=0)
    success_rate = Column(Float, default=1.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)