from __future__ import annotations

import json
import math
import sqlite3
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from log import logger
from core.memory.embedding import EmbeddingConfig, EmbeddingProvider
from core.memory.memory_item import MemoryCandidate, MemoryItem, MemoryType
from core.memory.key_schema import normalize_key, normalize_value, validate_key
from core.data.vector_search import get_vector_provider
from core.data.base import get_engine
from sqlalchemy import inspect as sqlalchemy_inspect


@dataclass(frozen=True)
class MemoryStoreConfig:
    db_path: Path
    embedding_dim: int = 256
    vector_enabled: bool = False
    default_confidence: float = 0.6
    merge_enabled: bool = True
    merge_similarity_threshold: float = 0.92
    conflict_enabled: bool = True
    conflict_similarity_threshold: float = 0.85
    key_schema_enforced: bool = True
    key_schema_allow_unlisted: bool = False


class MemoryStore:
    """
    SQLite 记忆存储（MVP）

    - 先实现 CRUD + 最近 N 条查询 + 简单 LIKE 搜索
    - 后续可在同一 DB 上接入 sqlite-vss（向量检索）
    """

    def __init__(self, config: MemoryStoreConfig):
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
        # backend/core/memory/memory_store.py -> project_root = parents[3]
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
                    CREATE TABLE IF NOT EXISTS memory_items (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        type TEXT NOT NULL,
                        key TEXT,
                        value TEXT,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_used_at TEXT,
                        confidence REAL,
                        embedding_json TEXT,
                        status TEXT NOT NULL DEFAULT 'active',
                        source TEXT NOT NULL,
                        meta_json TEXT
                    );
                    """
                )
                # 兼容迁移：为已存在的旧表补列（不依赖外部迁移框架）
                self._migrate_if_needed(conn)

                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memory_items_user_created_at ON memory_items(user_id, created_at);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memory_items_user_last_used_at ON memory_items(user_id, last_used_at);"
                )

                # 尝试启用 sqlite-vec（可用则使用，不可用则自动降级）
                if self.config.vector_enabled:
                    self._vec_available = self._try_enable_vec(conn)
        except Exception as e:
            logger.error(f"[MemoryStore] init db failed: {e}", exc_info=True)
            raise

    def _try_enable_vec(self, conn: sqlite3.Connection) -> bool:
        """
        尝试启用向量检索（使用 VectorSearchProvider）
        注意：conn 参数保留用于兼容性，但实际使用 VectorSearchProvider 内部连接
        """
        try:
            provider = get_vector_provider()
            if not provider.is_available():
                logger.warning("[MemoryStore] VectorSearchProvider not available, fallback to python cosine")
                return False
            
            # 使用 VectorSearchProvider 创建向量表
            if not provider.table_exists("memory_vec"):
                provider.create_table("memory_vec", dimension=self.config.embedding_dim)
                logger.info("[MemoryStore] memory_vec table created via VectorSearchProvider")
            else:
                logger.info("[MemoryStore] memory_vec table already exists")
            
            return True
        except Exception as e:
            logger.warning(f"[MemoryStore] VectorSearchProvider init failed, fallback to python cosine: {e}")
            return False

    def _migrate_if_needed(self, conn: sqlite3.Connection) -> None:
        """
        向后兼容迁移：为已存在的旧表补列（使用 SQLAlchemy inspect）
        注意：虽然接收 sqlite3.Connection，但使用 SQLAlchemy inspect 检查列
        """
        try:
            # 使用 SQLAlchemy inspect 检查表结构
            engine = get_engine()
            insp = sqlalchemy_inspect(engine)
            
            # 检查表是否存在
            if "memory_items" not in insp.get_table_names():
                return
            
            # 获取现有列名
            cols = {col["name"] for col in insp.get_columns("memory_items")}
            
            # 定义需要添加的列（如果不存在）
            columns_to_add = [
                ("user_id", "ALTER TABLE memory_items ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default';"),
                ("last_used_at", "ALTER TABLE memory_items ADD COLUMN last_used_at TEXT;"),
                ("confidence", "ALTER TABLE memory_items ADD COLUMN confidence REAL;"),
                ("embedding_json", "ALTER TABLE memory_items ADD COLUMN embedding_json TEXT;"),
                ("status", "ALTER TABLE memory_items ADD COLUMN status TEXT NOT NULL DEFAULT 'active';"),
                ("key", "ALTER TABLE memory_items ADD COLUMN key TEXT;"),
                ("value", "ALTER TABLE memory_items ADD COLUMN value TEXT;"),
            ]
            
            # 添加缺失的列
            for col_name, sql in columns_to_add:
                if col_name not in cols:
                    conn.execute(sql)
                    logger.info(f"[MemoryStore] Added missing column: {col_name}")
        except Exception as e:
            # 如果 SQLAlchemy inspect 失败，降级到 PRAGMA table_info（向后兼容）
            logger.warning(f"[MemoryStore] SQLAlchemy inspect failed, fallback to PRAGMA: {e}")
            try:
                cols = {row["name"] for row in conn.execute("PRAGMA table_info(memory_items);").fetchall()}
                
                def add_col(sql: str) -> None:
                    conn.execute(sql)
                
                if "user_id" not in cols:
                    add_col("ALTER TABLE memory_items ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default';")
                if "last_used_at" not in cols:
                    add_col("ALTER TABLE memory_items ADD COLUMN last_used_at TEXT;")
                if "confidence" not in cols:
                    add_col("ALTER TABLE memory_items ADD COLUMN confidence REAL;")
                if "embedding_json" not in cols:
                    add_col("ALTER TABLE memory_items ADD COLUMN embedding_json TEXT;")
                if "status" not in cols:
                    add_col("ALTER TABLE memory_items ADD COLUMN status TEXT NOT NULL DEFAULT 'active';")
                if "key" not in cols:
                    add_col("ALTER TABLE memory_items ADD COLUMN key TEXT;")
                if "value" not in cols:
                    add_col("ALTER TABLE memory_items ADD COLUMN value TEXT;")
            except Exception as e2:
                logger.error(f"[MemoryStore] Migration fallback also failed: {e2}")

    def add_candidates(
        self,
        candidates: Iterable[MemoryCandidate],
        *,
        user_id: str,
        source: str = "memory_extractor",
        meta: Optional[dict] = None,
    ) -> list[MemoryItem]:
        """
        结构化写入入口：支持 key/value，便于确定性冲突/合并。
        """
        items: list[tuple[MemoryType, str, Optional[str], Optional[str], Optional[float]]] = []
        for c in candidates:
            items.append((c.type, c.content or "", c.key, c.value, c.confidence))
        return self._add_items_internal(items, user_id=user_id, source=source, meta=meta)

    def add_items(
        self,
        items: Iterable[tuple[MemoryType, str]],
        *,
        user_id: str,
        source: str = "memory_extractor",
        meta: Optional[dict] = None,
        confidence: Optional[float] = None,
    ) -> list[MemoryItem]:
        items2: list[tuple[MemoryType, str, Optional[str], Optional[str], Optional[float]]] = [
            (t, c, None, None, confidence) for (t, c) in items
        ]
        return self._add_items_internal(items2, user_id=user_id, source=source, meta=meta)

    def _add_items_internal(
        self,
        items: Iterable[tuple[MemoryType, str, Optional[str], Optional[str], Optional[float]]],
        *,
        user_id: str,
        source: str,
        meta: Optional[dict],
    ) -> list[MemoryItem]:
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        created: list[MemoryItem] = []

        with self._connect() as conn:
            for t, content, key, value, conf in items:
                content_norm = self._normalize_content(content)
                key_norm = normalize_key(key) if key else None
                # schema 校验/标准化 value
                if key_norm and validate_key(key_norm):
                    value_norm = normalize_value(key_norm, value or "") if value else None
                else:
                    value_norm = self._normalize_content(value) if value else None
                if not content_norm:
                    continue

                # schema enforcement：key 不在白名单时丢弃或降级为无 key
                if key_norm and not validate_key(key_norm):
                    if self.config.key_schema_allow_unlisted:
                        pass
                    elif self.config.key_schema_enforced:
                        # 严格模式：直接丢弃
                        continue
                    else:
                        # 非严格：降级为无 key/value
                        key_norm = None
                        value_norm = None

                # schema 校验失败（例如 timezone 非法 / language 非法）→ 丢弃
                if key_norm and validate_key(key_norm) and value_norm is None:
                    continue

                # 结构化冲突/合并：同 user_id + type + key
                if key_norm:
                    ex = conn.execute(
                        """
                        SELECT id, value, status, confidence
                        FROM memory_items
                        WHERE user_id = ? AND type = ? AND key = ? AND status = 'active'
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (user_id, t, key_norm),
                    ).fetchone()
                    if ex is not None:
                        old_id = ex["id"]
                        old_value = ex["value"]
                        if (old_value or "") == (value_norm or ""):
                            # 同值：提升 confidence/updated_at，不插入
                            self._bump_confidence(conn, user_id=user_id, memory_id=old_id)
                            continue
                        # 值变化：deprecated 旧条目，插入新条目
                        self._deprecate(conn, user_id=user_id, memory_id=old_id)

                # fallback 去重：type+content 精确去重
                if self.exists_exact(user_id=user_id, mem_type=t, content=content_norm):
                    continue

                text_for_embed = f"{key_norm}:{value_norm} {content_norm}" if key_norm and value_norm else content_norm
                vec = self._embedder.embed(text_for_embed)
                embedding_json = json.dumps(vec)

                # 非结构化：再做相似度 merge/conflict（保留原逻辑）
                candidate = self._find_best_candidate(conn, user_id=user_id, mem_type=t, vec=vec)
                if candidate is not None:
                    existing_item, sim = candidate
                    if (
                        self.config.conflict_enabled
                        and existing_item.status == "active"
                        and sim >= self.config.conflict_similarity_threshold
                        and self._is_conflict(existing_item.content, content_norm)
                    ):
                        self._deprecate(conn, user_id=user_id, memory_id=existing_item.id)
                    elif (
                        self.config.merge_enabled
                        and existing_item.status == "active"
                        and sim >= self.config.merge_similarity_threshold
                    ):
                        self._merge_into(
                            conn,
                            user_id=user_id,
                            memory_id=existing_item.id,
                            new_content=content_norm,
                            new_embedding_json=embedding_json,
                            source=source,
                            meta=meta,
                        )
                        continue

                mid = str(uuid.uuid4())
                cur = conn.execute(
                    """
                    INSERT INTO memory_items (id, user_id, type, key, value, content, created_at, updated_at, last_used_at, confidence, embedding_json, status, source, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mid,
                        user_id,
                        t,
                        key_norm,
                        value_norm,
                        content_norm,
                        now,
                        now,
                        None,
                        conf if conf is not None else self.config.default_confidence,
                        embedding_json,
                        "active",
                        source,
                        meta_json,
                    ),
                )

                # 使用 VectorSearchProvider 插入向量
                if self.config.vector_enabled:
                    try:
                        provider = get_vector_provider()
                        if provider.is_available():
                            rowid = cur.lastrowid
                            try:
                                # 使用 VectorSearchProvider 插入向量（vector_id = rowid）
                                provider.upsert_vector(
                                    table_name="memory_vec",
                                    vector_id=rowid,
                                    embedding=vec,  # 直接传递 list[float]，provider 会处理转换
                                )
                            except Exception as upsert_error:
                                logger.warning(f"[MemoryStore] Vector upsert failed for rowid {rowid}: {upsert_error}")
                    except Exception as e:
                        logger.warning(f"[MemoryStore] VectorSearchProvider upsert failed, fallback python only: {e}")

                created.append(
                    MemoryItem(
                        id=mid,
                        user_id=user_id,
                        type=t,
                        key=key_norm,
                        value=value_norm,
                        content=content_norm,
                        created_at=datetime.fromisoformat(now),
                        updated_at=datetime.fromisoformat(now),
                        last_used_at=None,
                        confidence=conf if conf is not None else self.config.default_confidence,
                        embedding=vec,
                        status="active",
                        source=source,
                        meta=meta,
                    )
                )

        return created

    def _bump_confidence(self, conn: sqlite3.Connection, *, user_id: str, memory_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute(
            "SELECT confidence FROM memory_items WHERE user_id = ? AND id = ?;",
            (user_id, memory_id),
        ).fetchone()
        old_conf = float(row["confidence"]) if row and row["confidence"] is not None else self.config.default_confidence
        new_conf = min(1.0, old_conf * 0.85 + 0.15)
        conn.execute(
            "UPDATE memory_items SET confidence = ?, updated_at = ? WHERE user_id = ? AND id = ?;",
            (new_conf, now, user_id, memory_id),
        )

    def exists_exact(self, *, user_id: str, mem_type: MemoryType, content: str) -> bool:
        """
        最小去重：同一 user_id 下，同 type + content 完全一致则认为重复
        """
        content_norm = self._normalize_content(content)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM memory_items
                WHERE user_id = ? AND type = ? AND content = ?
                LIMIT 1
                """,
                (user_id, mem_type, content_norm),
            ).fetchone()
            return row is not None

    @staticmethod
    def _normalize_content(content: str) -> str:
        return " ".join((content or "").strip().split())

    @staticmethod
    def _vec_to_blob(vec: list[float]) -> bytes:
        # sqlite-vss 通常期望 float32 blob
        return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])

    def search(self, *, query: str, top_k: int = 5, user_id: str = "default") -> list[MemoryItem]:
        """
        统一检索接口：优先使用向量搜索，失败或未启用则降级为关键字搜索
        """
        if self.config.vector_enabled:
            try:
                return self.search_vector(user_id=user_id, query=query, limit=top_k)
            except Exception as e:
                logger.warning(f"[MemoryStore] Vector search failed, falling back: {e}")
        
        return self.search_like(user_id=user_id, query=query, limit=top_k)

    def search_vector(self, *, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
        """
        向量检索（VectorSearchProvider 优先，失败则 python cosine）
        """
        q = self._normalize_content(query)
        if not q:
            return []
        qvec = self._embedder.embed(q)

        # 1) VectorSearchProvider 路径（可用则尝试）
        if self.config.vector_enabled:
            try:
                provider = get_vector_provider()
                if provider.is_available():
                    # 使用 VectorSearchProvider 进行向量检索
                    # 返回 List[(distance, rowid)]
                    results = provider.search(
                        table_name="memory_vec",
                        query_vector=qvec,
                        limit=limit,
                        filters={"user_id": user_id},
                        business_table="memory_items"  # 用于 JOIN 过滤
                    )
                    
                    if results:
                        # 通过 rowid 批量查询 memory_items 获取完整数据
                        rowids = [int(rowid) for _, rowid in results]
                        if not rowids:
                            return []
                        
                        placeholders = ",".join(["?"] * len(rowids))
                        
                        with self._connect() as conn:
                            # 使用 rowid 查询，保持顺序
                            rows = conn.execute(
                                f"""
                                SELECT id, user_id, type, key, value, content, created_at, updated_at, last_used_at, confidence, embedding_json, status, source, meta_json, rowid
                                FROM memory_items
                                WHERE rowid IN ({placeholders}) AND user_id = ?
                                """,
                                tuple(rowids) + (user_id,),
                            ).fetchall()
                        
                        # 按 VectorSearchProvider 返回的距离顺序排序
                        # 创建 rowid -> row 的映射
                        rowid_to_row = {r["rowid"]: r for r in rows}
                        
                        # 按 results 的顺序构建返回列表（保持距离排序）
                        ordered_items = []
                        for _, rowid in results:
                            row = rowid_to_row.get(int(rowid))
                            if row:
                                ordered_items.append(self._row_to_item(row))
                        
                        return ordered_items
            except Exception as e:
                logger.warning(f"[MemoryStore] VectorSearchProvider search failed, fallback to python cosine: {e}")

        # 2) Python cosine 降级路径（保持不变）
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, type, key, value, content, created_at, updated_at, last_used_at, confidence, embedding_json, status, source, meta_json
                FROM memory_items
                WHERE user_id = ? AND embedding_json IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 500
                """,
                (user_id,),
            ).fetchall()

        scored: list[tuple[float, sqlite3.Row]] = []
        for r in rows:
            try:
                vec = json.loads(r["embedding_json"]) if r["embedding_json"] else None
                if not isinstance(vec, list):
                    continue
                score = self._cosine(qvec, vec)
                scored.append((score, r))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [r for _, r in scored[: max(0, limit)]]
        return [self._row_to_item(r) for r in top]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n == 0:
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for i in range(n):
            ai = float(a[i])
            bi = float(b[i])
            dot += ai * bi
            na += ai * ai
            nb += bi * bi
        if na <= 0 or nb <= 0:
            return 0.0
        return dot / (math.sqrt(na) * math.sqrt(nb))

    def list_recent(self, *, user_id: str, limit: int = 20) -> list[MemoryItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, type, key, value, content, created_at, updated_at, last_used_at, confidence, embedding_json, status, source, meta_json
                FROM memory_items
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def search_like(self, *, user_id: str, query: str, limit: int = 10) -> list[MemoryItem]:
        q = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, type, key, value, content, created_at, updated_at, last_used_at, confidence, embedding_json, status, source, meta_json
                FROM memory_items
                WHERE user_id = ? AND content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, q, limit),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list(self, *, user_id: str, limit: int = 50, include_deprecated: bool = False) -> list[MemoryItem]:
        if include_deprecated:
            return self.list_recent(user_id=user_id, limit=limit)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, type, key, value, content, created_at, updated_at, last_used_at, confidence, embedding_json, status, source, meta_json
                FROM memory_items
                WHERE user_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def delete(self, *, user_id: str, memory_id: str) -> bool:
        with self._connect() as conn:
            # 先获取 rowid（用于删除向量）
            rowid_row = conn.execute(
                "SELECT rowid FROM memory_items WHERE user_id = ? AND id = ?;",
                (user_id, memory_id),
            ).fetchone()
            
            # 删除 memory_items 记录
            cur = conn.execute(
                "DELETE FROM memory_items WHERE user_id = ? AND id = ?;",
                (user_id, memory_id),
            )
            
            # 删除对应的向量（如果向量检索已启用）
            if cur.rowcount > 0 and self.config.vector_enabled and rowid_row:
                try:
                    rowid = rowid_row["rowid"]
                    provider = get_vector_provider()
                    if provider.is_available():
                        provider.delete_vectors(
                            table_name="memory_vec",
                            vector_ids=[rowid],
                        )
                except Exception as e:
                    logger.warning(f"[MemoryStore] VectorSearchProvider delete failed: {e}")
            
            return cur.rowcount > 0

    def clear(self, *, user_id: str) -> int:
        with self._connect() as conn:
            # 先获取所有要删除的记录的 rowid（用于删除向量）
            rowid_rows = conn.execute(
                "SELECT rowid FROM memory_items WHERE user_id = ?;",
                (user_id,),
            ).fetchall()
            rowids = [r["rowid"] for r in rowid_rows]
            
            # 删除 memory_items 记录
            cur = conn.execute("DELETE FROM memory_items WHERE user_id = ?;", (user_id,))
            deleted_count = cur.rowcount
            
            # 批量删除对应的向量（如果向量检索已启用）
            if deleted_count > 0 and self.config.vector_enabled and rowids:
                try:
                    provider = get_vector_provider()
                    if provider.is_available():
                        provider.delete_vectors(
                            table_name="memory_vec",
                            vector_ids=rowids,
                        )
                except Exception as e:
                    logger.warning(f"[MemoryStore] VectorSearchProvider batch delete failed: {e}")
            
            return deleted_count

    def touch_last_used(self, *, user_id: str, memory_ids: list[str]) -> int:
        if not memory_ids:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join(["?"] * len(memory_ids))
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE memory_items SET last_used_at = ?, updated_at = ? WHERE user_id = ? AND id IN ({placeholders});",
                [now, now, user_id, *memory_ids],
            )
            return cur.rowcount

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MemoryItem:
        meta = None
        if row["meta_json"]:
            try:
                meta = json.loads(row["meta_json"])
            except Exception:
                meta = None
        embedding = None
        if "embedding_json" in row.keys() and row["embedding_json"]:
            try:
                embedding = json.loads(row["embedding_json"])
            except Exception:
                embedding = None
        return MemoryItem(
            id=row["id"],
            user_id=row["user_id"] if "user_id" in row.keys() else "default",
            type=row["type"],
            key=row["key"] if "key" in row.keys() else None,
            value=row["value"] if "value" in row.keys() else None,
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
            confidence=row["confidence"] if "confidence" in row.keys() else None,
            embedding=embedding,
            status=row["status"] if "status" in row.keys() else "active",
            source=row["source"],
            meta=meta,
        )

    def _find_best_candidate(
        self, conn: sqlite3.Connection, *, user_id: str, mem_type: MemoryType, vec: list[float]
    ) -> Optional[tuple[MemoryItem, float]]:
        rows = conn.execute(
            """
            SELECT id, user_id, type, content, created_at, updated_at, last_used_at, confidence, embedding_json, status, source, meta_json
            FROM memory_items
            WHERE user_id = ? AND type = ? AND embedding_json IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 200
            """,
            (user_id, mem_type),
        ).fetchall()
        best: Optional[tuple[MemoryItem, float]] = None
        for r in rows:
            try:
                emb = json.loads(r["embedding_json"]) if r["embedding_json"] else None
                if not isinstance(emb, list):
                    continue
                sim = self._cosine(vec, emb)
                item = self._row_to_item(r)
                if best is None or sim > best[1]:
                    best = (item, sim)
            except Exception:
                continue
        return best

    @staticmethod
    def _polarity(text: str) -> int:
        s = (text or "").lower()
        neg = ["不喜欢", "不想", "不要", "讨厌", "避免", "prefer not", "don't like", "do not like", "hate"]
        pos = ["喜欢", "偏好", "更喜欢", "prefer", "like"]
        if any(k in s for k in neg):
            return -1
        if any(k in s for k in pos):
            return 1
        return 0

    def _is_conflict(self, old: str, new: str) -> bool:
        a = self._polarity(old)
        b = self._polarity(new)
        return a != 0 and b != 0 and a != b

    def _deprecate(self, conn: sqlite3.Connection, *, user_id: str, memory_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE memory_items SET status = 'deprecated', updated_at = ? WHERE user_id = ? AND id = ?;",
            (now, user_id, memory_id),
        )

    def _merge_into(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        memory_id: str,
        new_content: str,
        new_embedding_json: str,
        source: str,
        meta: Optional[dict],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute(
            "SELECT confidence, meta_json FROM memory_items WHERE user_id = ? AND id = ?;",
            (user_id, memory_id),
        ).fetchone()
        old_conf = float(row["confidence"]) if row and row["confidence"] is not None else self.config.default_confidence
        new_conf = min(1.0, old_conf * 0.85 + 0.15)

        merged_meta = {}
        if row and row["meta_json"]:
            try:
                merged_meta = json.loads(row["meta_json"]) or {}
            except Exception:
                merged_meta = {}
        merged_meta["merged"] = True
        merged_meta["merged_at"] = now
        merged_meta["merged_source"] = source
        if meta:
            merged_meta["last_merge_meta"] = meta

        # 更新 memory_items 表
        cur = conn.execute(
            """
            UPDATE memory_items
            SET content = ?, embedding_json = ?, confidence = ?, updated_at = ?, meta_json = ?
            WHERE user_id = ? AND id = ?
            """,
            (
                new_content,
                new_embedding_json,
                new_conf,
                now,
                json.dumps(merged_meta, ensure_ascii=False),
                user_id,
                memory_id,
            ),
        )
        
        # 更新向量表（如果向量检索已启用）
        if self.config.vector_enabled and cur.rowcount > 0:
            try:
                # 获取更新后的 rowid
                rowid_row = conn.execute(
                    "SELECT rowid FROM memory_items WHERE user_id = ? AND id = ?;",
                    (user_id, memory_id),
                ).fetchone()
                
                if rowid_row:
                    rowid = rowid_row["rowid"]
                    # 解析 embedding_json 获取向量
                    new_vec = json.loads(new_embedding_json) if new_embedding_json else None
                    if new_vec and isinstance(new_vec, list):
                        provider = get_vector_provider()
                        if provider.is_available():
                            try:
                                provider.upsert_vector(
                                    table_name="memory_vec",
                                    vector_id=rowid,
                                    embedding=new_vec,
                                )
                            except Exception as upsert_error:
                                logger.warning(f"[MemoryStore] Vector upsert failed during merge for rowid {rowid}: {upsert_error}")
            except Exception as e:
                logger.warning(f"[MemoryStore] VectorSearchProvider upsert failed during merge: {e}")

