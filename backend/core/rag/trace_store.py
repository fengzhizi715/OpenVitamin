"""
RAG Trace Store
用于存储和检索 RAG 检索过程的完整证据链
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from log import logger


@dataclass
class RAGTraceStoreConfig:
    """RAG Trace Store 配置"""
    db_path: Path


class RAGTraceStore:
    """
    RAG Trace Store v1
    
    表结构：
    - rag_traces: RAG 行为索引摘要
    - rag_trace_chunks: 检索到的 chunks 详情
    """
    
    def __init__(self, config: RAGTraceStoreConfig):
        self.config = config
        self._ensure_db()
    
    @staticmethod
    def default_db_path() -> Path:
        """返回默认数据库路径（使用 platform.db）"""
        root = Path(__file__).resolve().parents[3]
        data_dir = root / "backend" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "platform.db"
    
    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接"""
        self.config.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.config.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _ensure_db(self) -> None:
        """初始化数据库表结构"""
        try:
            with self._connect() as conn:
                # 1. 创建 rag_traces 表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS rag_traces (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        message_id TEXT NOT NULL,
                        rag_id TEXT NOT NULL,
                        rag_type TEXT NOT NULL,
                        query TEXT NOT NULL,
                        embedding_model TEXT NOT NULL,
                        vector_store TEXT NOT NULL,
                        top_k INTEGER NOT NULL,
                        retrieved_count INTEGER NOT NULL DEFAULT 0,
                        injected_token_count INTEGER,
                        finalized BOOLEAN NOT NULL DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # 2. 创建 rag_trace_chunks 表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS rag_trace_chunks (
                        id TEXT PRIMARY KEY,
                        trace_id TEXT NOT NULL,
                        doc_id TEXT,
                        doc_name TEXT,
                        chunk_id TEXT,
                        score REAL,
                        content TEXT,
                        content_tokens INTEGER,
                        rank INTEGER NOT NULL,
                        FOREIGN KEY(trace_id) REFERENCES rag_traces(id) ON DELETE CASCADE
                    );
                """)
                
                # 创建索引
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rag_traces_message_id 
                    ON rag_traces(message_id);
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rag_traces_session_id 
                    ON rag_traces(session_id);
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rag_trace_chunks_trace_id 
                    ON rag_trace_chunks(trace_id);
                """)
                
                conn.commit()
        except Exception as e:
            logger.error(f"[RAGTraceStore] Failed to initialize database: {e}", exc_info=True)
            raise
    
    def create_trace(
        self,
        session_id: str,
        message_id: str,
        rag_id: str,
        rag_type: str,
        query: str,
        embedding_model: str,
        vector_store: str,
        top_k: int,
        user_id: str = "default",
    ) -> str:
        """
        创建 RAG Trace
        
        Args:
            user_id: 用户 ID（多用户架构）
            
        Returns:
            trace_id
        """
        trace_id = f"ragtrace_{uuid.uuid4().hex[:16]}"
        
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO rag_traces (
                    id, session_id, message_id, rag_id, rag_type,
                    query, embedding_model, vector_store, top_k, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trace_id, session_id, message_id, rag_id, rag_type,
                query, embedding_model, vector_store, top_k, user_id
            ))
            conn.commit()
        
        logger.debug(f"[RAGTraceStore] Created trace: {trace_id} for user: {user_id}")
        return trace_id
    
    def add_chunks(
        self,
        trace_id: str,
        chunks: List[Dict[str, Any]],
    ) -> None:
        """
        追加检索结果 chunks
        
        Args:
            trace_id: Trace ID
            chunks: Chunk 列表，每个包含 doc_id, doc_name, chunk_id, score, content, rank
        """
        with self._connect() as conn:
            # 检查 trace 是否已 finalized
            trace = conn.execute(
                "SELECT finalized FROM rag_traces WHERE id = ?",
                (trace_id,)
            ).fetchone()
            
            if not trace:
                raise ValueError(f"Trace {trace_id} not found")
            
            if trace["finalized"]:
                raise ValueError(f"Trace {trace_id} is finalized and cannot be modified")
            
            # 插入 chunks
            for chunk in chunks:
                chunk_id = f"chunk_{uuid.uuid4().hex[:12]}"
                content = chunk.get("content", "")
                content_tokens = chunk.get("content_tokens")
                if content_tokens is None:
                    # 粗略估算：1 token ≈ 4 chars
                    content_tokens = len(content) // 4
                
                conn.execute("""
                    INSERT INTO rag_trace_chunks (
                        id, trace_id, doc_id, doc_name, chunk_id,
                        score, content, content_tokens, rank
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chunk_id, trace_id,
                    chunk.get("doc_id"),
                    chunk.get("doc_name"),
                    chunk.get("chunk_id"),
                    chunk.get("score", 0.0),
                    content,
                    content_tokens,
                    chunk.get("rank", 0),
                ))
            
            # 更新 retrieved_count
            conn.execute("""
                UPDATE rag_traces
                SET retrieved_count = (
                    SELECT COUNT(*) FROM rag_trace_chunks WHERE trace_id = ?
                )
                WHERE id = ?
            """, (trace_id, trace_id))
            
            conn.commit()
        
        logger.debug(f"[RAGTraceStore] Added {len(chunks)} chunks to trace {trace_id}")
    
    def finalize_trace(
        self,
        trace_id: str,
        injected_token_count: int,
        final_message_id: Optional[str] = None,
    ) -> None:
        """
        完成 Trace（推理结束后调用）
        
        Args:
            trace_id: Trace ID
            injected_token_count: 注入的 token 数量
            final_message_id: 最终落库的 assistant message_id（用于把 trace 绑定到真实消息）
        """
        with self._connect() as conn:
            trace = conn.execute(
                "SELECT finalized FROM rag_traces WHERE id = ?",
                (trace_id,)
            ).fetchone()
            
            if not trace:
                raise ValueError(f"Trace {trace_id} not found")
            
            if trace["finalized"]:
                logger.warning(f"[RAGTraceStore] Trace {trace_id} is already finalized")
                return
            
            if final_message_id:
                conn.execute(
                    """
                    UPDATE rag_traces
                    SET injected_token_count = ?, finalized = 1, message_id = ?
                    WHERE id = ?
                    """,
                    (injected_token_count, final_message_id, trace_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE rag_traces
                    SET injected_token_count = ?, finalized = 1
                    WHERE id = ?
                    """,
                    (injected_token_count, trace_id),
                )
            
            conn.commit()
        
        logger.debug(f"[RAGTraceStore] Finalized trace {trace_id}")
    
    def get_trace_by_message_id(self, message_id: str, user_id: str = "default") -> Optional[Dict[str, Any]]:
        """
        通过 message_id 获取 Trace（按用户过滤）
        
        Returns:
            Trace 字典，包含 trace 信息和 chunks，如果不存在返回 None
        """
        with self._connect() as conn:
            trace = conn.execute("""
                SELECT * FROM rag_traces
                WHERE message_id = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (message_id, user_id)).fetchone()
            
            if not trace:
                return None
            
            # 获取 chunks
            chunks = conn.execute("""
                SELECT doc_id, doc_name, chunk_id, score, content, content_tokens, rank
                FROM rag_trace_chunks
                WHERE trace_id = ?
                ORDER BY rank ASC
            """, (trace["id"],)).fetchall()
            
            return {
                "id": trace["id"],
                "session_id": trace["session_id"],
                "message_id": trace["message_id"],
                "rag_id": trace["rag_id"],
                "rag_type": trace["rag_type"],
                "query": trace["query"],
                "embedding_model": trace["embedding_model"],
                "vector_store": trace["vector_store"],
                "top_k": trace["top_k"],
                "retrieved_count": trace["retrieved_count"],
                "injected_token_count": trace["injected_token_count"],
                "finalized": bool(trace["finalized"]),
                "created_at": trace["created_at"],
                "chunks": [
                    {
                        "doc_id": chunk["doc_id"],
                        "doc_name": chunk["doc_name"],
                        "chunk_id": chunk["chunk_id"],
                        "score": chunk["score"],
                        "content": chunk["content"],
                        "content_tokens": chunk["content_tokens"],
                        "rank": chunk["rank"],
                    }
                    for chunk in chunks
                ],
            }
    
    def get_trace_by_id(self, trace_id: str, user_id: str = "default") -> Optional[Dict[str, Any]]:
        '''通过 trace_id 获取 Trace（前端兜底：message_id 未同步时可用 meta.rag.trace_id 查询，按用户过滤）'''
        with self._connect() as conn:
            trace = conn.execute(
                "SELECT * FROM rag_traces WHERE id = ? AND user_id = ?", 
                (trace_id, user_id)
            ).fetchone()
            if not trace:
                return None
            chunks = conn.execute(
                "SELECT doc_id, doc_name, chunk_id, score, content, content_tokens, rank "
                "FROM rag_trace_chunks WHERE trace_id = ? ORDER BY rank ASC",
                (trace_id,),
            ).fetchall()
            return {
                "id": trace["id"],
                "session_id": trace["session_id"],
                "message_id": trace["message_id"],
                "rag_id": trace["rag_id"],
                "rag_type": trace["rag_type"],
                "query": trace["query"],
                "embedding_model": trace["embedding_model"],
                "vector_store": trace["vector_store"],
                "top_k": trace["top_k"],
                "retrieved_count": trace["retrieved_count"],
                "injected_token_count": trace["injected_token_count"],
                "finalized": bool(trace["finalized"]),
                "created_at": trace["created_at"],
                "chunks": [
                    {
                        "doc_id": c["doc_id"],
                        "doc_name": c["doc_name"],
                        "chunk_id": c["chunk_id"],
                        "score": c["score"],
                        "content": c["content"],
                        "content_tokens": c["content_tokens"],
                        "rank": c["rank"],
                    }
                    for c in chunks
                ],
            }

    def cleanup_old_traces(self, days: int = 7) -> int:
        """
        清理 N 天前的 traces（v1 存储策略）
        
        Args:
            days: 保留天数，默认 7 天
            
        Returns:
            删除的 trace 数量
        """
        with self._connect() as conn:
            # 删除旧 traces（CASCADE 会自动删除关联的 chunks）
            cursor = conn.execute("""
                DELETE FROM rag_traces
                WHERE created_at < datetime('now', '-' || ? || ' days')
            """, (days,))
            
            deleted_count = cursor.rowcount
            conn.commit()
        
        logger.info(f"[RAGTraceStore] Cleaned up {deleted_count} old traces (older than {days} days)")
        return deleted_count
