from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal, Optional, List, Union

from log import logger
from core.memory.embedding import EmbeddingConfig, EmbeddingProvider
from core.data.vector_search import get_vector_provider

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class HistoryStoreConfig:
    db_path: Path
    embedding_dim: int = 256
    vector_enabled: bool = False


class HistoryStore:
    """
    聊天历史存储（MVP）

    - 多用户隔离：按 user_id（来自 X-User-Id）
    - 会话：sessions
    - 消息：messages
    - 语义检索：messages_vec (sqlite-vec)
    """

    def __init__(self, config: HistoryStoreConfig):
        self.config = config
        self._embedder = EmbeddingProvider(EmbeddingConfig(dim=self.config.embedding_dim))
        self._vec_available = False
        self._ensure_db()

    @staticmethod
    def default_db_path() -> Path:
        """
        返回默认数据库路径
        
        注意：系统统一使用 platform.db 存储所有数据（模型、历史、记忆、设置）。
        此方法返回统一的数据库路径以保持一致性。
        """
        root = Path(__file__).resolve().parents[3]
        data_dir = root / "backend" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "platform.db"

    def _connect(self) -> sqlite3.Connection:
        # 确保父目录存在
        self.config.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.config.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_model TEXT,
                        deleted_at TEXT
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        request_id TEXT,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        model TEXT,
                        meta_json TEXT,
                        FOREIGN KEY(session_id) REFERENCES sessions(id)
                    );
                    """
                )
                # 兼容旧表：添加 user_id 列并回填（SQLite ADD COLUMN 不会给已有行填默认值）
                try:
                    conn.execute("ALTER TABLE messages ADD COLUMN user_id TEXT DEFAULT 'default'")
                    conn.execute("UPDATE messages SET user_id = COALESCE("
                        "(SELECT user_id FROM sessions WHERE sessions.id = messages.session_id), 'default') "
                        "WHERE user_id IS NULL")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE messages ADD COLUMN request_id TEXT")
                except sqlite3.OperationalError:
                    pass
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_user_updated_at ON sessions(user_id, updated_at);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_messages_session_created_at ON messages(session_id, created_at);"
                )
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_messages_session_role_request_id "
                    "ON messages(session_id, role, request_id) WHERE request_id IS NOT NULL;"
                )

                # 尝试启用 sqlite-vec（用于历史语义搜索）
                if self.config.vector_enabled:
                    self._vec_available = self._try_enable_vec(conn)
        except Exception as e:
            logger.error(f"[HistoryStore] init db failed: {e}", exc_info=True)
            raise

    # ----------------------------
    # Sessions
    # ----------------------------
    def create_session(self, *, user_id: str, title: str, last_model: Optional[str] = None) -> str:
        sid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, title, created_at, updated_at, last_model, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (sid, user_id, title, now, now, last_model),
            )
        return sid

    def touch_session(self, *, user_id: str, session_id: str, last_model: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET updated_at = ?, last_model = COALESCE(?, last_model)
                WHERE user_id = ? AND id = ? AND deleted_at IS NULL
                """,
                (now, last_model, user_id, session_id),
            )

    def rename_session(self, *, user_id: str, session_id: str, title: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE sessions
                SET title = ?, updated_at = ?
                WHERE user_id = ? AND id = ? AND deleted_at IS NULL
                """,
                (title, now, user_id, session_id),
            )
            return cur.rowcount > 0

    def delete_session(self, *, user_id: str, session_id: str, hard: bool = True) -> bool:
        with self._connect() as conn:
            if hard:
                conn.execute("DELETE FROM messages WHERE session_id = ?;", (session_id,))
                cur = conn.execute(
                    "DELETE FROM sessions WHERE user_id = ? AND id = ?;",
                    (user_id, session_id),
                )
                return cur.rowcount > 0
            else:
                now = datetime.now(timezone.utc).isoformat()
                cur = conn.execute(
                    "UPDATE sessions SET deleted_at = ? WHERE user_id = ? AND id = ?;",
                    (now, user_id, session_id),
                )
                return cur.rowcount > 0

    def list_sessions(self, *, user_id: str, limit: int = 50, include_deleted: bool = False) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if include_deleted:
                rows = conn.execute(
                    """
                    SELECT id, user_id, title, created_at, updated_at, last_model, deleted_at
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, user_id, title, created_at, updated_at, last_model, deleted_at
                    FROM sessions
                    WHERE user_id = ? AND deleted_at IS NULL
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def session_exists(self, *, user_id: str, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE user_id = ? AND id = ? AND deleted_at IS NULL LIMIT 1;",
                (user_id, session_id),
            ).fetchone()
            return row is not None

    def get_session(self, *, user_id: str, session_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, title, created_at, updated_at, last_model, deleted_at
                FROM sessions
                WHERE user_id = ? AND id = ? AND deleted_at IS NULL
                LIMIT 1
                """,
                (user_id, session_id),
            ).fetchone()
        return dict(row) if row else None

    def get_recent_active_session_id(self, *, user_id: str, within_minutes: int = 15) -> Optional[str]:
        """返回用户最近活跃会话 ID（用于无会话头时的自动复用）"""
        if within_minutes <= 0:
            return None
        threshold = (datetime.now(timezone.utc) - timedelta(minutes=within_minutes)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM sessions
                WHERE user_id = ? AND deleted_at IS NULL AND updated_at >= ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, threshold),
            ).fetchone()
        return row["id"] if row else None

    # ----------------------------
    # Messages
    # ----------------------------
    def append_message(
        self,
        *,
        session_id: str,
        role: Role,
        content: Union[str, List],
        model: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> str:
        mid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        
        # 序列化 content（如果是列表则转为 JSON 字符串）
        if isinstance(content, list):
            # 将 Pydantic 模型转换为字典后再序列化
            serializable_content = []
            for item in content:
                if hasattr(item, 'model_dump'):  # Pydantic v2
                    serializable_content.append(item.model_dump())
                elif hasattr(item, 'dict'):  # Pydantic v1
                    serializable_content.append(item.dict())
                else:
                    serializable_content.append(item)
            content_str = json.dumps(serializable_content, ensure_ascii=False)
        else:
            content_str = content
        
        with self._connect() as conn:
            # 获取 user_id（从 sessions 表查询，用于冗余存储）
            user_id_row = conn.execute(
                "SELECT user_id FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            
            if not user_id_row:
                raise ValueError(f"Session {session_id} not found")
            
            user_id = user_id_row["user_id"]
            
            # 插入消息（包含冗余的 user_id）
            if request_id:
                existing = conn.execute(
                    """
                    SELECT id FROM messages
                    WHERE session_id = ? AND role = ? AND request_id = ?
                    LIMIT 1
                    """,
                    (session_id, role, request_id),
                ).fetchone()
                if existing:
                    return existing["id"]
            cur = conn.execute(
                """
                INSERT INTO messages (id, session_id, user_id, role, content, created_at, model, meta_json, request_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (mid, session_id, user_id, role, content_str, now, model, meta_json, request_id),
            )
            conn.commit()
            rowid = cur.lastrowid

            # 如果开启了向量化，则同步存入 vec 表（使用 VectorSearchProvider）
            # 必须先 commit 再调 provider，否则 provider 另开连接写同库会触发 SQLite "database is locked"
            if self.config.vector_enabled and role in ["user", "assistant"]:
                try:
                    provider = get_vector_provider()
                    if provider.is_available():
                        # 预处理内容（去除多余空格，仅对字符串）
                        if isinstance(content, str):
                            norm_content = " ".join(content.strip().split())
                        else:
                            # 对于多模态内容，转换为字典后序列化为字符串进行向量化
                            serializable_content = []
                            for item in content:
                                if hasattr(item, 'model_dump'):  # Pydantic v2
                                    serializable_content.append(item.model_dump())
                                elif hasattr(item, 'dict'):  # Pydantic v1
                                    serializable_content.append(item.dict())
                                else:
                                    serializable_content.append(item)
                            norm_content = " ".join(json.dumps(serializable_content, ensure_ascii=False).strip().split())
                        
                        if norm_content:
                            vec = self._embedder.embed(norm_content)
                            # 直接调用 provider.upsert_vector（内部已处理 UPDATE/INSERT，无需预先检查）
                            # 注意：不能用 self._connect() 检查 messages_vec，因为该连接未加载 sqlite-vec 扩展
                            try:
                                provider.upsert_vector(
                                    table_name="messages_vec",
                                    vector_id=rowid,
                                    embedding=vec,
                                )
                            except Exception as upsert_error:
                                logger.warning(f"[HistoryStore] VectorSearchProvider upsert failed for rowid {rowid}: {upsert_error}")
                except Exception as e:
                    # 向量存储失败不应该影响消息存储，只记录警告
                    logger.warning(f"[HistoryStore] VectorSearchProvider upsert failed: {e}")
                    
        return mid

    def search_history(
        self, 
        *, 
        user_id: str, 
        query: str, 
        limit: int = 5
    ) -> List[dict[str, Any]]:
        """
        语义搜索历史消息（跨会话，使用 VectorSearchProvider）
        """
        if not self.config.vector_enabled:
            return []

        norm_query = " ".join(query.strip().split())
        if not norm_query:
            return []

        try:
            provider = get_vector_provider()
            if not provider.is_available():
                return []
            
            # 使用 VectorSearchProvider 进行向量检索
            # 注意：先获取 rowid，然后通过 messages JOIN sessions 过滤 user_id
            qvec = self._embedder.embed(norm_query)
            results = provider.search(
                table_name="messages_vec",
                query_vector=qvec,
                limit=limit * 2,  # 获取更多结果，因为后续会过滤 user_id
            )
            
            if not results:
                return []
            
            # 通过 rowid 批量查询 messages（直接过滤 user_id，避免 JOIN）
            rowids = [int(rowid) for _, rowid in results]
            if not rowids:
                return []
            
            placeholders = ",".join(["?"] * len(rowids))
            
            with self._connect() as conn:
                # 优化：直接使用 messages.user_id 过滤，避免 JOIN sessions 表
                rows = conn.execute(
                    f"""
                    SELECT 
                        m.id, m.session_id, m.role, m.content, m.created_at, m.model, m.meta_json,
                        s.title as session_title,
                        m.rowid
                    FROM messages m
                    LEFT JOIN sessions s ON s.id = m.session_id
                    WHERE m.rowid IN ({placeholders}) AND m.user_id = ?
                    LIMIT ?
                    """,
                    tuple(rowids) + (user_id, limit),
                ).fetchall()
            
            # 按 VectorSearchProvider 返回的距离顺序排序
            rowid_to_row = {r["rowid"]: r for r in rows}
            ordered_results = []
            for distance, rowid in results:
                row = rowid_to_row.get(int(rowid))
                if row:
                    d = dict(row)
                    # 解析 content（可能是 JSON 列表）
                    content_str = d.get("content", "")
                    try:
                        parsed_content = json.loads(content_str)
                        if isinstance(parsed_content, list):
                            d["content"] = parsed_content
                    except (json.JSONDecodeError, TypeError):
                        pass
                    
                    # 解析 meta_json
                    if d.get("meta_json"):
                        try:
                            d["meta"] = json.loads(d["meta_json"])
                        except Exception:
                            d["meta"] = None
                    d.pop("meta_json", None)
                    d.pop("rowid", None)
                    d["distance"] = float(distance)  # 添加距离信息
                    ordered_results.append(d)
            
            return ordered_results
        except Exception as e:
            logger.error(f"[HistoryStore] Semantic history search failed: {e}")
            return []

    def _try_enable_vec(self, conn: sqlite3.Connection) -> bool:
        """
        尝试启用向量检索（使用 VectorSearchProvider）
        注意：conn 参数保留用于兼容性，但实际使用 VectorSearchProvider 内部连接
        """
        try:
            provider = get_vector_provider()
            if not provider.is_available():
                logger.warning("[HistoryStore] VectorSearchProvider not available, history search disabled")
                return False
            
            # 使用 VectorSearchProvider 创建向量表
            if not provider.table_exists("messages_vec"):
                provider.create_table("messages_vec", dimension=self.config.embedding_dim)
                logger.info("[HistoryStore] messages_vec table created via VectorSearchProvider")
            else:
                logger.info("[HistoryStore] messages_vec table already exists")
            
            return True
        except Exception as e:
            logger.warning(f"[HistoryStore] VectorSearchProvider init failed: {e}")
            return False

    def list_messages(self, *, user_id: str, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        # session 归属校验
        if not self.session_exists(user_id=user_id, session_id=session_id):
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, created_at, model, meta_json
                FROM (
                    SELECT id, session_id, role, content, created_at, model, meta_json, rowid
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                ) AS sub
                ORDER BY created_at ASC, rowid ASC
                """,
                (session_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # 反序列化 content（如果是 JSON 列表）
            content_str = d.get("content", "")
            try:
                # 尝试解析为 JSON 列表
                parsed_content = json.loads(content_str)
                if isinstance(parsed_content, list):
                    d["content"] = parsed_content
            except (json.JSONDecodeError, TypeError):
                # 如果不是有效的 JSON，保持原字符串
                pass
            
            # 反序列化 meta_json
            if d.get("meta_json"):
                try:
                    d["meta"] = json.loads(d["meta_json"])
                except Exception:
                    d["meta"] = None
            d.pop("meta_json", None)
            out.append(d)
        return out
