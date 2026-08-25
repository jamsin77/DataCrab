"""用户与权限数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base

# 用户角色关联表
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    display_name = Column(String(100))
    avatar = Column(String(500))

    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)

    # 关系
    roles = relationship("Role", secondary=user_roles, back_populates="users", lazy="selectin")
    data_sources = relationship("DataSource", back_populates="creator", lazy="selectin")
    chat_sessions = relationship("ChatSession", back_populates="user", lazy="selectin")
    file_links = relationship("FileLink", back_populates="creator", lazy="selectin")


class Role(Base):
    """角色模型"""
    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100))
    description = Column(Text)

    permissions = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    users = relationship("User", secondary=user_roles, back_populates="roles", lazy="selectin")


class Permission(Base):
    """权限模型"""
    __tablename__ = "permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_type = Column(String(50), nullable=False)  # code, operator, datasource, schedule
    resource_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"))

    permission_level = Column(String(20), nullable=False)  # view, use, manage

    created_at = Column(DateTime, default=datetime.utcnow)


class PermissionRequest(Base):
    """权限申请模型"""
    __tablename__ = "permission_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(UUID(as_uuid=True), nullable=False)
    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    requested_level = Column(String(20), nullable=False)  # view, use, manage
    reason = Column(Text)

    status = Column(String(20), default="pending")  # pending/approved/rejected
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_note = Column(Text, nullable=True)

    escalated = Column(Boolean, default=False)
    escalated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
