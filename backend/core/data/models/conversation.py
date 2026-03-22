"""
Conversation ORM 模型（聊天历史）
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.data.base import Base


class Session(Base):
    """聊天会话 ORM 模型"""
    
    __tablename__ = "sessions"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False
    )
    last_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # 关系
    messages: Mapped[list["Message"]] = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    
    # 索引
    __table_args__ = (
        Index('idx_sessions_user_updated_at', 'user_id', 'updated_at'),
    )
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_model": self.last_model,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Message(Base):
    """聊天消息 ORM 模型"""
    
    __tablename__ = "messages"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # "system", "user", "assistant", "tool"
    content: Mapped[str] = mapped_column(Text, nullable=False)  # JSON 字符串或纯文本
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False
    )
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 字符串
    
    # 关系
    session: Mapped["Session"] = relationship("Session", back_populates="messages")
    
    # 索引
    __table_args__ = (
        Index('idx_messages_session_created_at', 'session_id', 'created_at'),
    )
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        # 解析 content（可能是 JSON 列表或纯文本）
        content_value = self.content
        try:
            parsed_content = json.loads(self.content)
            if isinstance(parsed_content, list):
                content_value = parsed_content
        except (json.JSONDecodeError, TypeError):
            pass
        
        # 解析 meta_json
        meta_value = None
        if self.meta_json:
            try:
                meta_value = json.loads(self.meta_json)
            except (json.JSONDecodeError, TypeError):
                pass
        
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "role": self.role,
            "content": content_value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "model": self.model,
            "meta": meta_value,
        }
