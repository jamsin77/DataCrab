"""对话数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChatSession(Base):
    """对话会话模型"""
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title = Column(String(200))
    context = Column(JSON)  # 会话级上下文：{source_datasource_id, source_datasource_name, source_data_name, target_datasource_id, target_datasource_name, target_data_name}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", lazy="selectin", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    """对话消息模型"""
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    code_blocks = Column(JSON)
    table_data = Column(JSON)
    charts = Column(JSON)
    meta = Column(JSON)  # 前端临时字段持久化（model/reasoning/executingMsgs/suggestion/agentName/noMatch）
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    session = relationship("ChatSession", back_populates="messages")
