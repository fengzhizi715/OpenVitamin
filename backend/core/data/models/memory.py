"""
MemoryItem ORM 模型
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from core.data.base import Base
from core.memory.memory_item import MemoryType, MemoryStatus


class MemoryItem(Base):
    """MemoryItem ORM 模型"""
    
    __tablename__ = "memory_items"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # MemoryType
    key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
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
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    embedding_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # MemoryStatus
    source: Mapped[str] = mapped_column(String, nullable=False)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容 Pydantic MemoryItem）"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "key": self.key,
            "value": self.value,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "confidence": self.confidence,
            "embedding": json.loads(self.embedding_json) if self.embedding_json else None,
            "status": self.status,
            "source": self.source,
            "meta": json.loads(self.meta_json) if self.meta_json else None,
        }
