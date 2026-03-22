"""
Knowledge Base ORM 模型（RAG 知识库）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import Index, String, Text, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.sqlite import INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.data.base import Base


class KnowledgeBase(Base):
    """知识库 ORM 模型"""

    __tablename__ = "knowledge_base"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding_model_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="READY")
    user_id: Mapped[str] = mapped_column(String, nullable=False, server_default="default")
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=True,
    )

    documents: Mapped[List["Document"]] = relationship(
        "Document", back_populates="knowledge_base", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "embedding_model_id": self.embedding_model_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Document(Base):
    """文档 ORM 模型"""

    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String, ForeignKey("knowledge_base.id"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    doc_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="UPLOADED")
    user_id: Mapped[str] = mapped_column(String, nullable=False, server_default="default")
    chunks_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=True,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=True,
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="documents"
    )

    __table_args__ = (Index("idx_document_kb_id", "knowledge_base_id"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "knowledge_base_id": self.knowledge_base_id,
            "source": self.source,
            "doc_type": self.doc_type,
            "status": self.status,
            "chunks_count": self.chunks_count,
            "file_path": self.file_path,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EmbeddingChunk(Base):
    """
    统一 embedding chunk 表（与 vec 表 rowid 对齐）
    向量存储在 kb_chunks_vec 虚拟表中，本表存 metadata。
    """

    __tablename__ = "embedding_chunks"

    id: Mapped[int] = mapped_column(INTEGER, primary_key=True, autoincrement=True)

    knowledge_base_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_embedding_chunks_kb_id", "knowledge_base_id"),
        Index("idx_embedding_chunks_doc_id", "document_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_base_id": self.knowledge_base_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "content": self.content,
        }
