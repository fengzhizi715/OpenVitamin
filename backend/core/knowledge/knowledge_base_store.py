"""
Knowledge Base Store v1
使用 sqlite-vec 实现 RAG 知识库的向量存储和检索
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from log import logger
from config.settings import settings
from core.knowledge.status import KnowledgeBaseStatus, DocumentStatus
from core.data.vector_search import get_vector_provider
from core.utils.user_context import UserAccessDeniedError, ResourceNotFoundError

# 统一单表：业务表与向量表名（阶段 4.3）
UNIFIED_CHUNKS_TABLE = "embedding_chunks"
UNIFIED_VEC_TABLE = "kb_chunks_vec"


@dataclass
class KnowledgeBaseConfig:
    """Knowledge Base 配置"""
    db_path: Path
    embedding_dim: int = 512  # 默认 512 维，需要与 embedding model 一致（可动态更新）


class KnowledgeBaseStore:
    """
    Knowledge Base Store v1
    
    表结构：
    - knowledge_base: RAG 实体
    - document: 原始文档
    - embedding_chunk: 向量 + chunk (sqlite-vec)
    """

    def __init__(self, config: KnowledgeBaseConfig):
        self.config = config
        self._vec_available = False
        self._ensure_db()

    @staticmethod
    def default_db_path() -> Path:
        """
        返回默认数据库路径
        
        注意：系统统一使用 platform.db 存储所有数据。
        """
        root = Path(__file__).resolve().parents[3]
        data_dir = root / "backend" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "platform.db"

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接"""
        self.config.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.config.db_path))
        conn.row_factory = sqlite3.Row
        
        # 如果 sqlite-vec 可用，每次连接时都需要加载扩展
        if self._vec_available:
            try:
                conn.enable_load_extension(True)
                try:
                    import sqlite_vec  # type: ignore
                    sqlite_vec.load(conn)  # type: ignore
                finally:
                    conn.enable_load_extension(False)
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Failed to load sqlite-vec in connection: {e}")
        
        return conn

    def _ensure_db(self) -> None:
        """初始化数据库表结构"""
        try:
            with self._connect() as conn:
                # 1. 创建 knowledge_base 表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_base (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        embedding_model_id TEXT NOT NULL,
                        status TEXT DEFAULT 'READY',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        user_id TEXT DEFAULT 'default'
                    );
                """)
                
                # 添加 status 字段（如果表已存在但字段不存在）
                try:
                    conn.execute("ALTER TABLE knowledge_base ADD COLUMN status TEXT DEFAULT 'READY'")
                except sqlite3.OperationalError:
                    pass
                # 添加 user_id 字段（兼容旧表）
                try:
                    conn.execute("ALTER TABLE knowledge_base ADD COLUMN user_id TEXT DEFAULT 'default'")
                    conn.execute("UPDATE knowledge_base SET user_id = 'default' WHERE user_id IS NULL")
                except sqlite3.OperationalError:
                    pass

                # 2. 创建 document 表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS document (
                        id TEXT PRIMARY KEY,
                        knowledge_base_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        doc_type TEXT,
                        status TEXT DEFAULT 'UPLOADED',
                        chunks_count INTEGER DEFAULT 0,
                        file_path TEXT,
                        error_message TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        user_id TEXT DEFAULT 'default',
                        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                    );
                """)
                
                # 添加 user_id 字段（兼容旧 document 表）
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN user_id TEXT DEFAULT 'default'")
                    conn.execute("UPDATE document SET user_id = 'default' WHERE user_id IS NULL")
                except sqlite3.OperationalError:
                    pass
                # 添加 status 字段（如果表已存在但字段不存在）
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN status TEXT DEFAULT 'UPLOADED'")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN chunks_count INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN file_path TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN error_message TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
                except sqlite3.OperationalError:
                    pass

                # 3. 创建索引
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_document_kb_id 
                    ON document(knowledge_base_id);
                """)

                # 4. 尝试启用 sqlite-vec（不再创建全局表，改为按知识库创建独立表）
                if self._try_enable_vec(conn):
                    self._vec_available = True
                    logger.info("[KnowledgeBaseStore] sqlite-vec enabled (per-KB tables)")
                else:
                    logger.warning("[KnowledgeBaseStore] sqlite-vec not available, embedding features disabled")

        except Exception as e:
            logger.error(f"[KnowledgeBaseStore] init db failed: {e}", exc_info=True)
            raise

    def _try_enable_vec(self, conn: sqlite3.Connection) -> bool:
        """尝试加载 sqlite-vec 扩展（不再创建全局表）"""
        try:
            conn.enable_load_extension(True)
            try:
                import sqlite_vec  # type: ignore
                sqlite_vec.load(conn)  # type: ignore
            finally:
                conn.enable_load_extension(False)
            return True
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] sqlite-vec extension not available: {e}")
            return False
    
    def _get_chunk_table_name(self, kb_id: str) -> str:
        """
        获取知识库对应的向量表名（旧版 per-KB 表）
        表名格式：embedding_chunk_{kb_id}
        """
        safe_kb_id = kb_id.replace("-", "_").replace(".", "_")
        return f"embedding_chunk_{safe_kb_id}"

    def _use_unified_chunks_table(self) -> bool:
        """是否使用统一单表 embedding_chunks（通过 sqlite_master 检查表是否存在，不依赖表内数据）"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (UNIFIED_CHUNKS_TABLE,),
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def _ensure_unified_vec_table(self, embedding_dim: int) -> None:
        """确保统一向量表 kb_chunks_vec 存在（由 VectorSearchProvider 创建）"""
        try:
            provider = get_vector_provider()
            if not provider.is_available():
                raise RuntimeError("Vector search provider is not available")
            if not provider.table_exists(UNIFIED_VEC_TABLE):
                provider.create_table(UNIFIED_VEC_TABLE, dimension=embedding_dim)
                logger.info(f"[KnowledgeBaseStore] Created unified vec table {UNIFIED_VEC_TABLE} dim={embedding_dim}")
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Failed to ensure unified vec table: {e}")
            raise

    def _ensure_kb_vec_table(self, kb_id: str, embedding_dim: int) -> None:
        """
        确保知识库的向量表存在且维度正确
        
        Args:
            kb_id: 知识库 ID
            embedding_dim: Embedding 维度
        """
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available, cannot create vec table")
        
        table_name = self._get_chunk_table_name(kb_id)
        
        with self._connect() as conn:
            if not self._try_enable_vec(conn):
                raise RuntimeError("sqlite-vec is not available")
            
            # 检查表是否存在
            try:
                # 尝试查询表，如果不存在会抛出异常
                conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
                # 表已存在，检查维度（通过尝试插入一个测试向量来验证）
                # 注意：sqlite-vec 不支持直接查询表结构，我们通过异常来判断
                logger.debug(f"[KnowledgeBaseStore] Table {table_name} already exists")
            except sqlite3.OperationalError:
                # 表不存在，创建新表
                logger.info(f"[KnowledgeBaseStore] Creating vec table {table_name} with dim={embedding_dim}")
                conn.execute(f"""
                    CREATE VIRTUAL TABLE {table_name}
                    USING vec0(
                        embedding FLOAT[{embedding_dim}],
                        document_id TEXT,
                        chunk_id TEXT,
                        content TEXT
                    );
                """)
                conn.commit()
                logger.info(f"[KnowledgeBaseStore] Created vec table {table_name}")
    
    def _ensure_vec_table_dimension(self, kb_id: str, required_dim: int) -> None:
        """
        确保知识库的向量表存在且维度正确
        
        注意：sqlite-vec 不支持 ALTER TABLE，如果维度不匹配，需要删除重建
        由于每个知识库有独立的表，重建不会影响其他知识库
        
        Args:
            kb_id: 知识库 ID
            required_dim: 所需的维度
        """
        # 直接调用 _ensure_kb_vec_table，它会检查表是否存在并创建
        self._ensure_kb_vec_table(kb_id, required_dim)
    

    # =========================
    # Knowledge Base CRUD
    # =========================

    def create_knowledge_base(
        self,
        name: str,
        description: Optional[str],
        embedding_model_id: str,
        kb_id: Optional[str] = None,
        user_id: str = "default",
    ) -> str:
        """
        创建知识库
        
        Args:
            name: 知识库名称
            description: 描述
            embedding_model_id: embedding 模型 ID（如 "embedding:bge-small-zh"）
            kb_id: 可选，不提供则自动生成 UUID
            user_id: 用户 ID（多用户架构）
            
        Returns:
            知识库 ID
        """
        if kb_id is None:
            kb_id = f"kb_{uuid.uuid4().hex[:12]}"

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO knowledge_base (id, name, description, embedding_model_id, status, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (kb_id, name, description, embedding_model_id, KnowledgeBaseStatus.EMPTY, user_id))
            conn.commit()

        logger.info(f"[KnowledgeBaseStore] Created knowledge base: {kb_id} for user: {user_id}")
        return kb_id

    def get_knowledge_base(self, kb_id: str, user_id: str = "default") -> Optional[Dict[str, Any]]:
        """获取知识库信息（按用户过滤）"""
        with self._connect() as conn:
            # 先检查 KB 是否存在
            kb_exists = conn.execute(
                "SELECT user_id FROM knowledge_base WHERE id = ?",
                (kb_id,)
            ).fetchone()
            
            if not kb_exists:
                raise ResourceNotFoundError("KnowledgeBase", kb_id)
            
            # 如果存在但不属于当前用户
            if kb_exists["user_id"] != user_id:
                raise UserAccessDeniedError("KnowledgeBase", kb_id, user_id)
            
            row = conn.execute(
                "SELECT * FROM knowledge_base WHERE id = ? AND user_id = ?",
                (kb_id, user_id)
            ).fetchone()
            
            if row:
                kb_info = dict(row)
                # 如果状态为空或不存在，计算并更新状态
                if not kb_info.get("status"):
                    self._update_kb_status_from_documents(kb_id)
                    # 重新获取
                    row = conn.execute(
                        "SELECT * FROM knowledge_base WHERE id = ? AND user_id = ?",
                        (kb_id, user_id)
                    ).fetchone()
                    if row:
                        kb_info = dict(row)
                return kb_info
        return None

    def list_knowledge_bases(self, user_id: str = "default") -> List[Dict[str, Any]]:
        """列出用户的所有知识库"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_base WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def update_knowledge_base(
        self,
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """
        更新知识库信息
        
        Args:
            kb_id: 知识库 ID
            name: 新的名称（可选）
            description: 新的描述（可选）
            
        Returns:
            bool: 是否更新成功
        """
        # 检查知识库是否存在
        if not self.get_knowledge_base(kb_id):
            return False
        
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        
        if not updates:
            return True  # 没有需要更新的字段
        
        params.append(kb_id)
        
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE knowledge_base SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
            
            logger.info(f"[KnowledgeBaseStore] Updated knowledge base: {kb_id}")
            return cursor.rowcount > 0

    def delete_knowledge_base(self, kb_id: str, user_id: str = "default") -> bool:
        """删除知识库（级联删除相关文档、chunks 和向量表）。统一表下会清理 embedding_chunks 与 kb_chunks_vec。"""
        # 先检查 KB 是否存在
        with self._connect() as conn:
            # 检查 KB 是否存在（不限制 user_id）
            kb_exists = conn.execute(
                "SELECT id, user_id FROM knowledge_base WHERE id = ?",
                (kb_id,)
            ).fetchone()
            
            if not kb_exists:
                raise ResourceNotFoundError("KnowledgeBase", kb_id)
            
            # 如果存在但不属于当前用户，抛出权限错误
            if kb_exists["user_id"] != user_id:
                raise UserAccessDeniedError("KnowledgeBase", kb_id, user_id)
        
        # 后续删除操作...
        # 统一表：先删该 KB 在 embedding_chunks 中的行，并同步删除向量
        if self._use_unified_chunks_table():
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"SELECT id FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ?",
                        (kb_id,),
                    ).fetchall()
                    rowids = [r["id"] for r in rows]
                    if rowids:
                        conn.execute(
                            f"DELETE FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ?",
                            (kb_id,),
                        )
                        conn.commit()
                        provider = get_vector_provider()
                        if provider.is_available():
                            provider.delete_vectors(table_name=UNIFIED_VEC_TABLE, vector_ids=rowids)
                        logger.info(f"[KnowledgeBaseStore] Deleted {len(rowids)} chunks from {UNIFIED_CHUNKS_TABLE} for KB {kb_id}")
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Failed to delete unified chunks for KB {kb_id}: {e}")

        with self._connect() as conn:
            # 删除 per-KB 向量表（若存在）
            if self._vec_available:
                try:
                    table_name = self._get_chunk_table_name(kb_id)
                    conn.execute(f"DROP TABLE IF EXISTS {table_name};")
                    logger.info(f"[KnowledgeBaseStore] Dropped vec table {table_name} for KB {kb_id}")
                except Exception as e:
                    logger.warning(f"[KnowledgeBaseStore] Failed to drop vec table for KB {kb_id}: {e}")

            conn.execute(
                "DELETE FROM document WHERE knowledge_base_id = ?",
                (kb_id,),
            )
            cursor = conn.execute(
                "DELETE FROM knowledge_base WHERE id = ? AND user_id = ?",
                (kb_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # =========================
    # Document CRUD
    # =========================

    def create_document(
        self,
        knowledge_base_id: str,
        source: str,
        doc_type: Optional[str] = None,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        status: str = "UPLOADED",
        user_id: str = "default",
    ) -> str:
        """
        创建文档记录
        
        Args:
            knowledge_base_id: 所属知识库 ID
            source: 文档来源（文件名/URL）
            doc_type: 文档类型（pdf/docx/md 等）
            doc_id: 可选，不提供则自动生成 UUID
            file_path: 文件存储路径
            status: 文档状态
            user_id: 用户 ID（多用户架构）
            
        Returns:
            文档 ID
        """
        if doc_id is None:
            doc_id = f"doc_{uuid.uuid4().hex[:12]}"

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO document (id, knowledge_base_id, source, doc_type, status, file_path, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (doc_id, knowledge_base_id, source, doc_type, status, file_path, user_id))
            conn.commit()

        logger.debug(f"[KnowledgeBaseStore] Created document: {doc_id} with status {status}")
        
        # 创建文档后更新知识库状态
        self._update_kb_status_from_documents(knowledge_base_id)
        
        return doc_id
    
    def update_document_status(
        self,
        doc_id: str,
        status: str,
        chunks_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """更新文档状态"""
        with self._connect() as conn:
            updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status]
            
            if chunks_count is not None:
                updates.append("chunks_count = ?")
                params.append(chunks_count)
            
            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)
            
            params.append(doc_id)
            
            conn.execute(
                f"UPDATE document SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
        
        logger.debug(f"[KnowledgeBaseStore] Updated document {doc_id} status to {status}")
        
        # 自动更新知识库状态
        doc = self.get_document(doc_id)
        if doc:
            kb_id = doc.get("knowledge_base_id")
            if kb_id:
                self._update_kb_status_from_documents(kb_id)

    def _compute_kb_status(self, kb_id: str) -> str:
        """
        根据所有文档的状态计算知识库状态
        
        规则：
        - 如果有任何文档处于索引中（UPLOADED, PARSING, PARSED, CHUNKING, CHUNKED, EMBEDDING）→ INDEXING
        - 如果有任何文档失败（FAILED_PARSE, FAILED_EMBED）→ ERROR
        - 如果所有文档都是 INDEXED → READY
        - 如果没有文档 → EMPTY
        """
        docs = self.list_documents(kb_id)
        
        if not docs:
            return KnowledgeBaseStatus.EMPTY
        
        indexing_states = {
            DocumentStatus.UPLOADED,
            DocumentStatus.PARSING,
            DocumentStatus.PARSED,
            DocumentStatus.CHUNKING,
            DocumentStatus.CHUNKED,
            DocumentStatus.EMBEDDING,
        }
        
        failed_states = {
            DocumentStatus.FAILED_PARSE,
            DocumentStatus.FAILED_EMBED,
        }
        
        has_indexing = False
        has_failed = False
        all_indexed = True
        
        for doc in docs:
            status = doc.get("status", DocumentStatus.UPLOADED)
            if status in indexing_states:
                has_indexing = True
                all_indexed = False
            elif status in failed_states:
                has_failed = True
                all_indexed = False
            elif status != DocumentStatus.INDEXED:
                all_indexed = False
        
        if has_indexing:
            return KnowledgeBaseStatus.INDEXING
        elif has_failed:
            return KnowledgeBaseStatus.ERROR
        elif all_indexed:
            return KnowledgeBaseStatus.READY
        else:
            # 混合状态：有已索引的，也有失败的，但没有正在索引的
            return KnowledgeBaseStatus.ERROR

    def _update_kb_status_from_documents(self, kb_id: str) -> None:
        """根据文档状态更新知识库状态"""
        new_status = self._compute_kb_status(kb_id)
        self.update_knowledge_base_status(kb_id, new_status)

    def update_knowledge_base_status(self, kb_id: str, status: str) -> None:
        """更新知识库状态"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE knowledge_base SET status = ? WHERE id = ?",
                (status, kb_id)
            )
            conn.commit()
        logger.debug(f"[KnowledgeBaseStore] Updated knowledge base {kb_id} status to {status}")

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """获取文档信息"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM document WHERE id = ?",
                (doc_id,)
            ).fetchone()
            
            if row:
                return dict(row)
        return None

    def list_documents(self, knowledge_base_id: str, user_id: str = "default") -> List[Dict[str, Any]]:
        """列出知识库下的所有文档（按用户过滤）"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM document WHERE knowledge_base_id = ? AND user_id = ? ORDER BY created_at DESC",
                (knowledge_base_id, user_id)
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_document(self, doc_id: str, user_id: str = "default") -> bool:
        """删除文档（不再级联删除 chunks，需要单独调用 delete_document_chunks）"""
        # 先获取文档信息，以便后续更新知识库状态
        doc = self.get_document(doc_id)
        kb_id = doc.get("knowledge_base_id") if doc else None
        
        # 验证用户权限
        if doc and doc.get("user_id") != user_id:
            logger.warning(f"[KnowledgeBaseStore] Document {doc_id} does not belong to user {user_id}")
            return False
        
        with self._connect() as conn:
            # 删除 document
            cursor = conn.execute(
                "DELETE FROM document WHERE id = ? AND user_id = ?",
                (doc_id, user_id)
            )
            conn.commit()
            
            result = cursor.rowcount > 0
        
        # 删除文档后更新知识库状态
        if result and kb_id:
            self._update_kb_status_from_documents(kb_id)
        
        return result
    
    def delete_document_chunks(self, kb_id: str, doc_id: str) -> int:
        """删除文档的所有 chunks。优先使用统一表。"""
        if self._use_unified_chunks_table():
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"SELECT id FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ? AND document_id = ?",
                        (kb_id, doc_id),
                    ).fetchall()
                    rowids = [r["id"] for r in rows]
                    if not rowids:
                        return 0
                    conn.execute(
                        f"DELETE FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ? AND document_id = ?",
                        (kb_id, doc_id),
                    )
                    conn.commit()
                provider = get_vector_provider()
                if provider.is_available():
                    provider.delete_vectors(table_name=UNIFIED_VEC_TABLE, vector_ids=rowids)
                logger.info(f"[KnowledgeBaseStore] Deleted {len(rowids)} chunks for document {doc_id} from {UNIFIED_CHUNKS_TABLE}")
                return len(rowids)
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified delete_document_chunks failed: {e}")

        if not self._vec_available:
            return 0
        table_name = self._get_chunk_table_name(kb_id)
        try:
            with self._connect() as conn:
                conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
        except sqlite3.OperationalError:
            return 0
        with self._connect() as conn:
            count_row = conn.execute(
                f"SELECT count(*) as cnt FROM {table_name} WHERE document_id = ?", (doc_id,)
            ).fetchone()
            chunk_count = count_row["cnt"] if count_row else 0
            conn.execute(f"DELETE FROM {table_name} WHERE document_id = ?", (doc_id,))
            conn.commit()
        logger.info(f"[KnowledgeBaseStore] Deleted {chunk_count} chunks for document {doc_id} from {table_name}")
        return chunk_count

    # =========================
    # Embedding Chunk Operations
    # =========================

    def _unified_table_has_metadata_json(self) -> bool:
        """检测统一表是否包含 metadata_json 列（Alembic 迁移 d4e5f6a7b8c9 之后有）"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM pragma_table_info(?) WHERE name = ?",
                    (UNIFIED_CHUNKS_TABLE, "metadata_json"),
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def insert_chunk(
        self,
        knowledge_base_id: str,
        document_id: str,
        chunk_id: str,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        插入 embedding chunk（优先使用统一表 embedding_chunks + kb_chunks_vec）。
        metadata 为可选扩展字段，写入 metadata_json（需先执行 Alembic 迁移 d4e5f6a7b8c9）。
        """
        actual_dim = len(embedding)

        if self._use_unified_chunks_table():
            try:
                self._ensure_unified_vec_table(actual_dim)
                provider = get_vector_provider()
                if not provider.is_available():
                    raise RuntimeError("Vector search provider is not available")
                with self._connect() as conn:
                    if self._unified_table_has_metadata_json() and metadata is not None:
                        conn.execute(
                            f"""
                            INSERT INTO {UNIFIED_CHUNKS_TABLE}
                            (knowledge_base_id, document_id, chunk_id, content, metadata_json)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (knowledge_base_id, document_id, chunk_id, content, json.dumps(metadata)),
                        )
                    else:
                        conn.execute(
                            f"""
                            INSERT INTO {UNIFIED_CHUNKS_TABLE}
                            (knowledge_base_id, document_id, chunk_id, content)
                            VALUES (?, ?, ?, ?)
                            """,
                            (knowledge_base_id, document_id, chunk_id, content),
                        )
                    rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.commit()
                provider.upsert_vector(
                    table_name=UNIFIED_VEC_TABLE,
                    vector_id=rowid,
                    embedding=embedding,
                )
                logger.debug(f"[KnowledgeBaseStore] Inserted chunk {chunk_id} into {UNIFIED_CHUNKS_TABLE}")
                return
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified insert failed, falling back to per-KB table: {e}")

        # 旧版：per-KB 向量表
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available, cannot insert chunks")
        self._ensure_kb_vec_table(knowledge_base_id, actual_dim)
        table_name = self._get_chunk_table_name(knowledge_base_id)
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {table_name}
                (embedding, document_id, chunk_id, content)
                VALUES (?, ?, ?, ?)
                """,
                (json.dumps(embedding), document_id, chunk_id, content),
            )
            conn.commit()
        logger.debug(f"[KnowledgeBaseStore] Inserted chunk: {chunk_id} into {table_name}")

    def search_chunks(
        self,
        knowledge_base_id: str,
        query_embedding: List[float],
        limit: int = 5,
        max_distance: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        向量检索（Top-K）。优先使用统一表 + VectorSearchProvider。
        """
        if self._use_unified_chunks_table():
            try:
                provider = get_vector_provider()
                if provider.is_available():
                    results = provider.search(
                        table_name=UNIFIED_VEC_TABLE,
                        query_vector=query_embedding,
                        limit=limit,
                        filters={"knowledge_base_id": knowledge_base_id},
                        business_table=UNIFIED_CHUNKS_TABLE,
                    )
                    if not results:
                        return []
                    rowids = [int(r) for _, r in results]
                    placeholders = ",".join(["?"] * len(rowids))
                    has_meta = self._unified_table_has_metadata_json()
                    meta_col = ", c.metadata_json" if has_meta else ""
                    with self._connect() as conn:
                        rows = conn.execute(
                            f"""
                            SELECT c.id, c.content, c.document_id, c.chunk_id, c.knowledge_base_id{meta_col},
                                   d.source as doc_source, d.doc_type
                            FROM {UNIFIED_CHUNKS_TABLE} c
                            LEFT JOIN document d ON d.id = c.document_id
                            WHERE c.id IN ({placeholders}) AND c.knowledge_base_id = ?
                            """,
                            tuple(rowids) + (knowledge_base_id,),
                        ).fetchall()
                    rowid_to_row = {r["id"]: r for r in rows}
                    out = []
                    for distance, rowid in results:
                        r = rowid_to_row.get(int(rowid))
                        if r:
                            item = {
                                "content": r["content"],
                                "distance": float(distance),
                                "document_id": r["document_id"],
                                "chunk_id": r["chunk_id"],
                                "doc_source": r["doc_source"],
                                "doc_type": r["doc_type"],
                            }
                            if has_meta and r.get("metadata_json"):
                                try:
                                    item["metadata"] = json.loads(r["metadata_json"])
                                except (TypeError, ValueError):
                                    pass
                            if max_distance is None or item["distance"] <= max_distance:
                                out.append(item)
                    return out
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified search failed, falling back: {e}")

        # 旧版：per-KB 表
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available, cannot search chunks")
        table_name = self._get_chunk_table_name(knowledge_base_id)
        try:
            with self._connect() as conn:
                conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
        except sqlite3.OperationalError:
            migrated = self.migrate_chunks_from_old_table(knowledge_base_id)
            if migrated == 0:
                return []
        with self._connect() as conn:
            query_sql = f"""
                SELECT c.content, c.distance, c.document_id, c.chunk_id,
                       d.source as doc_source, d.doc_type
                FROM {table_name} c
                LEFT JOIN document d ON c.document_id = d.id
                WHERE d.knowledge_base_id = ? AND c.embedding MATCH ? AND c.k = ?
                ORDER BY c.distance
            """
            rows = conn.execute(
                query_sql,
                (knowledge_base_id, json.dumps(query_embedding), limit),
            ).fetchall()
        results = [
            {
                "content": row["content"],
                "distance": row["distance"],
                "document_id": row["document_id"],
                "chunk_id": row["chunk_id"],
                "doc_source": row["doc_source"],
                "doc_type": row["doc_type"],
            }
            for row in rows
        ]
        if max_distance is not None:
            results = [r for r in results if r["distance"] <= max_distance]
        return results

    def search_chunks_multi_kb(
        self,
        knowledge_base_ids: List[str],
        query_embedding: List[float],
        limit: int = 5,
        max_distance: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """多知识库向量检索。统一表下按 kb 分别检索后合并排序取 top limit。"""
        if not knowledge_base_ids:
            return []

        if self._use_unified_chunks_table():
            try:
                combined: List[Dict[str, Any]] = []
                per_kb = max(1, (limit + len(knowledge_base_ids) - 1) // len(knowledge_base_ids))
                for kb_id in knowledge_base_ids:
                    part = self.search_chunks(
                        knowledge_base_id=kb_id,
                        query_embedding=query_embedding,
                        limit=per_kb,
                        max_distance=max_distance,
                    )
                    for r in part:
                        r["knowledge_base_id"] = kb_id
                        combined.append(r)
                combined.sort(key=lambda x: x["distance"])
                return combined[:limit]
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified search_chunks_multi_kb failed: {e}")

        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available, cannot search chunks")

        # 过滤出存在的表，如果不存在则尝试迁移
        valid_kb_ids = []
        table_names = []
        with self._connect() as conn:
            for kb_id in knowledge_base_ids:
                table_name = self._get_chunk_table_name(kb_id)
                try:
                    # 检查表是否存在
                    conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
                    valid_kb_ids.append(kb_id)
                    table_names.append(table_name)
                except sqlite3.OperationalError:
                    # 表不存在，尝试从旧表迁移数据
                    logger.info(f"[KnowledgeBaseStore] Vec table {table_name} does not exist for KB {kb_id}, attempting migration...")
                    migrated = self.migrate_chunks_from_old_table(kb_id)
                    if migrated > 0:
                        # 迁移成功，重新检查表
                        try:
                            conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
                            valid_kb_ids.append(kb_id)
                            table_names.append(table_name)
                            logger.info(f"[KnowledgeBaseStore] Migration successful, {table_name} is now available")
                        except sqlite3.OperationalError:
                            logger.debug(f"[KnowledgeBaseStore] Vec table {table_name} still does not exist after migration for KB {kb_id}")
                    else:
                        logger.debug(f"[KnowledgeBaseStore] Vec table {table_name} does not exist for KB {kb_id}, skipping")
                    continue
        
        if not valid_kb_ids:
            logger.warning(f"[KnowledgeBaseStore] No valid vec tables found for KBs: {knowledge_base_ids}")
            return []

        # 构建 UNION 查询
        # 注意：每个表的结构相同，但我们需要在 SELECT 中添加 knowledge_base_id
        union_parts = []
        query_params = []
        
        # sqlite-vec 要求每个 MATCH 查询必须有 LIMIT 或 k = ? 约束
        # 为了确保每个子查询都能返回足够的结果，我们给每个子查询设置一个较大的 LIMIT
        # 然后在外部再限制最终结果数量
        per_table_limit = limit * len(valid_kb_ids)  # 每个表返回更多结果，确保最终有足够的选择
        
        for kb_id, table_name in zip(valid_kb_ids, table_names):
            # sqlite-vec 要求 MATCH 查询必须有 k = ? 约束（在 WHERE 子句中）
            # 或者使用 LIMIT（但必须在 ORDER BY 之后）
            # 我们使用 k = ? 方式，因为它更符合 sqlite-vec 的语义
            union_parts.append(f"""
                SELECT 
                    c.content, 
                    c.distance, 
                    c.document_id, 
                    c.chunk_id,
                    ? as knowledge_base_id,
                    d.source as doc_source,
                    d.doc_type
                FROM {table_name} c
                LEFT JOIN document d ON c.document_id = d.id
                WHERE d.knowledge_base_id = ?
                AND c.embedding MATCH ?
                AND c.k = ?
            """)
            query_params.extend([kb_id, kb_id, json.dumps(query_embedding), per_table_limit])
        
        # 组合 UNION 查询
        union_query = " UNION ALL ".join(union_parts)
        final_query = f"""
            SELECT * FROM (
                {union_query}
            ) ORDER BY distance LIMIT ?
        """
        query_params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(final_query, query_params).fetchall()

            results = [
                {
                    "content": row["content"],
                    "distance": row["distance"],
                    "document_id": row["document_id"],
                    "chunk_id": row["chunk_id"],
                    "knowledge_base_id": row["knowledge_base_id"],
                    "doc_source": row["doc_source"],
                    "doc_type": row["doc_type"]
                } 
                for row in rows
            ]
            
            # 应用距离过滤
            if max_distance is not None:
                results = [r for r in results if r["distance"] <= max_distance]
            
            return results

    def get_chunk_count(self, knowledge_base_id: Optional[str] = None) -> int:
        """获取 chunk 数量。优先使用统一表。"""
        if self._use_unified_chunks_table():
            try:
                with self._connect() as conn:
                    if knowledge_base_id:
                        row = conn.execute(
                            f"SELECT count(*) as cnt FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ?",
                            (knowledge_base_id,),
                        ).fetchone()
                    else:
                        row = conn.execute(f"SELECT count(*) as cnt FROM {UNIFIED_CHUNKS_TABLE}").fetchone()
                    return row["cnt"] if row else 0
            except Exception:
                pass
        if not self._vec_available:
            return 0
        with self._connect() as conn:
            if knowledge_base_id:
                table_name = self._get_chunk_table_name(knowledge_base_id)
                try:
                    row = conn.execute(f"SELECT count(*) as cnt FROM {table_name}").fetchone()
                    return row["cnt"] if row else 0
                except sqlite3.OperationalError:
                    return 0
            else:
                total = 0
                kb_rows = conn.execute("SELECT id FROM knowledge_base").fetchall()
                for kb_row in kb_rows:
                    kb_id = kb_row["id"]
                    table_name = self._get_chunk_table_name(kb_id)
                    try:
                        row = conn.execute(f"SELECT count(*) as cnt FROM {table_name}").fetchone()
                        if row:
                            total += row["cnt"]
                    except sqlite3.OperationalError:
                        continue
                return total

    def list_chunks(
        self,
        knowledge_base_id: str,
        document_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列出 chunks。优先使用统一表 embedding_chunks。"""
        if self._use_unified_chunks_table():
            try:
                with self._connect() as conn:
                    has_meta = self._unified_table_has_metadata_json()
                    cols = "chunk_id, document_id, content" + (", metadata_json" if has_meta else "")
                    query = f"""
                        SELECT {cols}
                        FROM {UNIFIED_CHUNKS_TABLE}
                        WHERE knowledge_base_id = ?
                    """
                    params: List[Any] = [knowledge_base_id]
                    if document_id:
                        query += " AND document_id = ?"
                        params.append(document_id)
                    query += " ORDER BY chunk_id LIMIT ? OFFSET ?"
                    params.extend([limit, offset])
                    rows = conn.execute(query, params).fetchall()
                out = []
                for i, r in enumerate(rows):
                    item = {"chunk_id": r["chunk_id"], "document_id": r["document_id"], "content": r["content"], "index": offset + i}
                    if has_meta and r.get("metadata_json"):
                        try:
                            item["metadata"] = json.loads(r["metadata_json"])
                        except (TypeError, ValueError):
                            pass
                    out.append(item)
                return out
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified list_chunks failed: {e}")

        if not self._vec_available:
            return []
        table_name = self._get_chunk_table_name(knowledge_base_id)
        try:
            with self._connect() as conn:
                conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
        except sqlite3.OperationalError:
            return []
        with self._connect() as conn:
            query = f"""
                SELECT c.chunk_id, c.document_id, c.content
                FROM {table_name} c
                LEFT JOIN document d ON c.document_id = d.id
                WHERE d.knowledge_base_id = ?
            """
            params = [knowledge_base_id]
            if document_id:
                query += " AND c.document_id = ?"
                params.append(document_id)
            query += " ORDER BY c.chunk_id LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
        return [
            {"chunk_id": r["chunk_id"], "document_id": r["document_id"], "content": r["content"], "index": offset + i}
            for i, r in enumerate(rows)
        ]
    
    def get_knowledge_base_disk_size(self, kb_id: str) -> Dict[str, Any]:
        """
        计算知识库的磁盘使用量
        
        包括：
        1. 原始文件大小（knowledge_bases/{kb_id}/raw/ 目录）
        2. 数据库中的向量数据大小（统一表 embedding_chunks/kb_chunks_vec 或 per-KB 表）
        3. 数据库中的元数据大小（document 表中的记录）
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            Dict with:
            - raw_files_size: 原始文件总大小（字节）
            - vector_table_size: 向量表大小（字节）
            - metadata_size: 元数据大小（字节）
            - total_size: 总大小（字节）
        """
        from core.knowledge.file_storage import FileStorage
        
        result = {
            "raw_files_size": 0,
            "vector_table_size": 0,
            "metadata_size": 0,
            "total_size": 0,
        }
        
        # 1. 计算原始文件大小
        try:
            storage_dir = FileStorage.get_kb_storage_path(kb_id)
            if storage_dir.exists():
                for file_path in storage_dir.iterdir():
                    if file_path.is_file():
                        result["raw_files_size"] += file_path.stat().st_size
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Failed to calculate raw files size for KB {kb_id}: {e}")
        
        # 2. 计算数据库中的向量表大小（统一表或 per-KB 表）
        try:
            chunk_count = self.get_chunk_count(kb_id)
            if chunk_count == 0:
                result["vector_table_size"] = 0
            else:
                actual_embedding_dim = self.config.embedding_dim
                if self._use_unified_chunks_table() or self._vec_available:
                    kb_info = self.get_knowledge_base(kb_id)
                    if kb_info:
                        try:
                            from core.models.registry import get_model_registry
                            model_registry = get_model_registry()
                            embedding_model = model_registry.get_model(kb_info.get("embedding_model_id", ""))
                            if embedding_model:
                                actual_embedding_dim = embedding_model.metadata.get("embedding_dim", self.config.embedding_dim)
                        except Exception:
                            pass
                embedding_size = actual_embedding_dim * 4
                metadata_per_chunk = 200
                chunk_size = embedding_size + metadata_per_chunk
                result["vector_table_size"] = int(chunk_count * chunk_size * 1.2)  # 20% overhead
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Failed to calculate vector table size for KB {kb_id}: {e}")
        
        # 3. 计算元数据大小（document 表中的记录）
        try:
            with self._connect() as conn:
                # 获取该知识库的所有文档记录
                docs = conn.execute(
                    "SELECT id, source, doc_type, file_path FROM document WHERE knowledge_base_id = ?",
                    (kb_id,)
                ).fetchall()
                
                # 计算每条记录的实际大小
                for doc in docs:
                    # ID: 约 32 bytes (UUID)
                    # knowledge_base_id: 约 32 bytes
                    # source: 文件名长度
                    # doc_type: 约 10 bytes
                    # status: 约 20 bytes
                    # chunks_count: 约 8 bytes
                    # file_path: 路径长度
                    # created_at, updated_at: 约 30 bytes each
                    # error_message: 通常为空
                    # 注意：sqlite3.Row 对象使用索引或列名访问，不是 dict
                    source = doc["source"] if "source" in doc.keys() else ""
                    doc_type = doc["doc_type"] if "doc_type" in doc.keys() else ""
                    file_path = doc["file_path"] if "file_path" in doc.keys() else ""
                    record_size = (
                        32 +  # id
                        32 +  # knowledge_base_id
                        len(source or "") +
                        len(doc_type or "") +
                        len(file_path or "") +
                        20 +  # status
                        8 +   # chunks_count
                        60    # timestamps
                    )
                    result["metadata_size"] += record_size
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Failed to calculate metadata size for KB {kb_id}: {e}")
        
        # 4. 计算总大小
        result["total_size"] = (
            result["raw_files_size"] +
            result["vector_table_size"] +
            result["metadata_size"]
        )
        
        return result
    
    def migrate_chunks_from_old_table(self, kb_id: str) -> int:
        """
        从旧的共享表 embedding_chunk 迁移数据到新的独立表
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            迁移的 chunk 数量
        """
        if not self._vec_available:
            logger.warning(f"[KnowledgeBaseStore] sqlite-vec not available, cannot migrate chunks for KB {kb_id}")
            return 0
        
        old_table = "embedding_chunk"
        new_table = self._get_chunk_table_name(kb_id)
        
        migrated_count = 0
        
        with self._connect() as conn:
            # 检查旧表是否存在
            try:
                old_count = conn.execute(
                    f"SELECT count(*) as cnt FROM {old_table} WHERE knowledge_base_id = ?",
                    (kb_id,)
                ).fetchone()
                if not old_count or old_count["cnt"] == 0:
                    logger.debug(f"[KnowledgeBaseStore] No chunks to migrate from old table for KB {kb_id}")
                    return 0
                
                logger.info(f"[KnowledgeBaseStore] Found {old_count['cnt']} chunks in old table for KB {kb_id}, starting migration...")
            except sqlite3.OperationalError:
                logger.debug(f"[KnowledgeBaseStore] Old table {old_table} does not exist, nothing to migrate")
                return 0
            
            # 检查新表是否存在，如果不存在则创建
            try:
                conn.execute(f"SELECT count(*) FROM {new_table} LIMIT 1;").fetchone()
                logger.debug(f"[KnowledgeBaseStore] New table {new_table} already exists")
            except sqlite3.OperationalError:
                # 新表不存在，需要创建
                # 获取第一个 chunk 的 embedding 维度来确定表结构
                sample = conn.execute(
                    f"SELECT embedding FROM {old_table} WHERE knowledge_base_id = ? LIMIT 1",
                    (kb_id,)
                ).fetchone()
                if sample:
                    # 解析 embedding JSON 获取维度
                    import json
                    embedding = json.loads(sample["embedding"])
                    dim = len(embedding)
                    logger.info(f"[KnowledgeBaseStore] Creating new table {new_table} with dim={dim}")
                    self._ensure_kb_vec_table(kb_id, dim)
            
            # 从旧表读取数据并插入到新表
            rows = conn.execute(
                f"""
                SELECT embedding, document_id, chunk_id, content
                FROM {old_table}
                WHERE knowledge_base_id = ?
                """,
                (kb_id,)
            ).fetchall()
            
            for row in rows:
                try:
                    conn.execute(f"""
                        INSERT INTO {new_table}
                        (embedding, document_id, chunk_id, content)
                        VALUES (?, ?, ?, ?)
                    """, (
                        row["embedding"],  # 已经是 JSON 格式
                        row["document_id"],
                        row["chunk_id"],
                        row["content"],
                    ))
                    migrated_count += 1
                except Exception as e:
                    logger.warning(f"[KnowledgeBaseStore] Failed to migrate chunk {row['chunk_id']}: {e}")
                    continue
            
            conn.commit()
            logger.info(f"[KnowledgeBaseStore] Migrated {migrated_count} chunks from old table to {new_table}")
        
        return migrated_count

    # =========================
    # Utility Methods
    # =========================

    def health(self) -> Dict[str, Any]:
        """返回健康状态"""
        return {
            "status": "ok",
            "vec_available": self._vec_available,
            "embedding_dim": self.config.embedding_dim,
        }
