from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

MemoryType = Literal["preference", "profile", "project", "fact"]
MemoryStatus = Literal["active", "deprecated"]


class MemoryCandidate(BaseModel):
    """
    MemoryExtractor 输出候选（结构化）
    - key/value 用于确定性合并/冲突检测
    - content 为人类可读的陈述句（可选，缺失时由系统生成）
    """

    type: MemoryType
    key: Optional[str] = None
    value: Optional[str] = None
    content: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class MemoryItem(BaseModel):
    """
    长期记忆条目（MVP）

    - content 需要“短、客观、可复用”
    """

    id: str = Field(..., description="memory id (uuid)")
    user_id: str = Field(..., min_length=1)
    type: MemoryType
    key: Optional[str] = None
    value: Optional[str] = None
    content: str = Field(..., min_length=1)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: Optional[datetime] = None

    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # 预留：向量索引（sqlite-vss 接入后使用）
    embedding: Optional[list[float]] = None
    status: MemoryStatus = "active"

    # 可选：来源、模型、元信息
    source: str = "memory_extractor"
    meta: Optional[dict[str, Any]] = None

