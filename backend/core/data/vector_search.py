"""
向量检索抽象层。支持 sqlite-vec / pgvector / Chroma / Milvus 等后端。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pathlib import Path

from log import logger


class VectorSearchProvider(ABC):
    """
    向量检索提供者抽象接口。
    sqlite-vec/pg 下 vector_id 常为 rowid；Chroma/Milvus 下为业务主键；
    search() 统一返回 (distance, vector_id)，由 Store 用 id 查业务表。
    """

    @abstractmethod
    def is_available(self) -> bool:
        """检查提供者是否可用"""
        pass

    @abstractmethod
    def create_table(self, table_name: str, dimension: int, **kwargs: Any) -> None:
        """创建向量表"""
        pass

    @abstractmethod
    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        pass

    @abstractmethod
    def upsert_vector(
        self,
        table_name: str,
        *,
        vector_id: Any,
        embedding: Sequence[float] | bytes,
        metadata: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """写入/覆盖向量。vector_id 在 sqlite-vec 下为 rowid，Chroma/Milvus 下为业务 id。"""
        pass

    @abstractmethod
    def search(
        self,
        table_name: str,
        query_vector: List[float],
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Tuple[float, Any]]:
        """向量检索。返回 List[(distance, vector_id)]。"""
        pass

    @abstractmethod
    def delete_vectors(self, table_name: str, vector_ids: Sequence[Any], **kwargs: Any) -> None:
        """删除向量"""
        pass


class SQLiteVecProvider(VectorSearchProvider):
    """sqlite-vec 实现。vector_id 约定为 int rowid。"""

    def __init__(self, db_path: Path) -> None:
        import uuid
        self.instance_id = str(uuid.uuid4())[:8]
        logger.debug(f"[SQLiteVecProvider] Creating instance {self.instance_id}")
        self.db_path = Path(db_path)
        self._vec_available = False
        self._check_availability()
        logger.debug(f"[SQLiteVecProvider] Instance {self.instance_id} initialized with _vec_available={self._vec_available}")

    def _check_availability(self) -> None:
        logger.debug("[SQLiteVecProvider] _check_availability called")
        try:
            import sqlite_vec  # type: ignore
            logger.debug("[SQLiteVecProvider] sqlite_vec imported successfully")
            self._vec_available = True
        except ImportError as e:
            self._vec_available = False
            logger.warning(f"[SQLiteVecProvider] sqlite-vec not available: {e}")
        logger.debug(f"[SQLiteVecProvider] _vec_available set to: {self._vec_available}")

    def is_available(self) -> bool:
        return self._vec_available

    def _load_extension(self, conn: Any) -> None:
        logger.debug(f"[SQLiteVecProvider.{self.instance_id}] _load_extension called, _vec_available={self._vec_available}")
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available")
        try:
            import sqlite_vec  # type: ignore
            logger.debug(f"[SQLiteVecProvider.{self.instance_id}] Loading sqlite-vec extension for db: {self.db_path}")
            conn.enable_load_extension(True)
            try:
                sqlite_vec.load(conn)  # type: ignore
                logger.debug(f"[SQLiteVecProvider.{self.instance_id}] sqlite-vec extension loaded successfully")
                # 简单验证 vec0 模块是否可用（不创建临时表，避免潜在问题）
                try:
                    conn.execute("SELECT vec_version();").fetchone()
                    logger.debug(f"[SQLiteVecProvider.{self.instance_id}] vec0 module is available")
                except Exception as vec_error:
                    logger.warning(f"[SQLiteVecProvider.{self.instance_id}] vec0 module test failed (will continue anyway): {vec_error}")
                    # 不 raise，允许继续执行（实际 SQL 执行时会再次验证）
            finally:
                # 扩展应在连接生命周期内保持加载，不在此处禁用
                pass
        except Exception as e:
            logger.error(f"[SQLiteVecProvider.{self.instance_id}] Failed to load sqlite-vec: {e}", exc_info=True)
            raise RuntimeError(f"Failed to load sqlite-vec: {e}") from e

    def create_table(self, table_name: str, dimension: int, **kwargs: Any) -> None:
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            self._load_extension(conn)
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {table_name}
                USING vec0(
                    embedding float[{dimension}]
                )
                """
            )
            conn.commit()

    def table_exists(self, table_name: str) -> bool:
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            return cur.fetchone() is not None

    def upsert_vector(
        self,
        table_name: str,
        *,
        vector_id: Any,
        embedding: Sequence[float] | bytes,
        metadata: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        logger.debug(f"[SQLiteVecProvider.{self.instance_id}] upsert_vector called with table_name={table_name}, vector_id={vector_id}")
        if not self._vec_available:
            logger.error(f"[SQLiteVecProvider.{self.instance_id}] Provider not available (_vec_available=False)")
            raise RuntimeError("sqlite-vec extension not available")
            
        try:
            import json
            import sqlite3
            logger.debug(f"[SQLiteVecProvider.{self.instance_id}] About to connect to database and load extension")
            with sqlite3.connect(str(self.db_path)) as conn:
                # Double-check availability before loading extension
                if not self._vec_available:
                    logger.error(f"[SQLiteVecProvider.{self.instance_id}] Provider became unavailable during upsert")
                    raise RuntimeError("sqlite-vec extension not available")
                    
                self._load_extension(conn)
                logger.debug(f"[SQLiteVecProvider.{self.instance_id}] Extension loaded successfully, proceeding with upsert")
                
                # Test if vec0 module is available on this connection
                try:
                    test_cursor = conn.execute("SELECT sqlite_version();")
                    sqlite_version = test_cursor.fetchone()[0]
                    logger.debug(f"[SQLiteVecProvider.{self.instance_id}] SQLite version: {sqlite_version}")
                    
                    # Try to use vec0 module explicitly
                    test_result = conn.execute("SELECT vec_version();").fetchone()
                    logger.debug(f"[SQLiteVecProvider.{self.instance_id}] vec_version: {test_result[0] if test_result else 'None'}")
                except Exception as test_e:
                    logger.warning(f"[SQLiteVecProvider.{self.instance_id}] vec0 module test failed: {test_e}")
                if isinstance(embedding, (bytes, bytearray)):
                    value: Any = bytes(embedding)
                else:
                    value = json.dumps(list(embedding))
                rowid = int(vector_id)
                
                # 先尝试UPDATE，如果失败再INSERT
                # 这样可以避免UNIQUE constraint错误
                cursor = conn.execute(
                    f"UPDATE {table_name} SET embedding = ? WHERE rowid = ?;",
                    (value, rowid)
                )
                
                # 如果没有更新任何行，说明是新记录，执行INSERT
                if cursor.rowcount == 0:
                    conn.execute(
                        f"INSERT INTO {table_name}(rowid, embedding) VALUES (?, ?);",
                        (rowid, value),
                    )
                
                conn.commit()
                logger.debug(f"[SQLiteVecProvider.{self.instance_id}] Upsert completed successfully")
        except Exception as e:
            logger.error(f"[SQLiteVecProvider.{self.instance_id}] Exception in upsert_vector: {e}", exc_info=True)
            logger.error(f"[SQLiteVecProvider.{self.instance_id}] Error type: {type(e).__name__}")
            logger.error(f"[SQLiteVecProvider.{self.instance_id}] Error message: {str(e)}")
            raise

    def search(
        self,
        table_name: str,
        query_vector: List[float],
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Tuple[float, Any]]:
        """
        向量检索。支持通过 filters 过滤（需要 JOIN 业务表）。
        
        Args:
            table_name: 向量表名（如 memory_vec）
            query_vector: 查询向量
            limit: 返回数量
            filters: 过滤条件，如 {"user_id": "xxx"}，需要配合业务表名使用
            **kwargs: 额外参数，如 business_table（业务表名，用于 JOIN）
        
        Returns:
            List[(distance, rowid)]
        """
        import json
        import sqlite3
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available")
        query_vec_json = json.dumps(query_vector)
        
        business_table = kwargs.get("business_table")
        
        with sqlite3.connect(str(self.db_path)) as conn:
            self._load_extension(conn)
            
            # 如果有 filters 和 business_table，使用 JOIN
            if filters and business_table:
                where_clauses = []
                params = [query_vec_json, limit]
                
                # 构建 WHERE 子句
                for key, value in filters.items():
                    where_clauses.append(f"b.{key} = ?")
                    params.append(value)
                
                where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""
                
                sql = f"""
                    SELECT v.distance, v.rowid
                    FROM {table_name} v
                    JOIN {business_table} b ON b.rowid = v.rowid
                    WHERE v.embedding MATCH ?
                    AND v.k = ?
                    {where_sql}
                    ORDER BY v.distance
                """
            else:
                # 无 filters，直接查询向量表
                sql = f"""
                    SELECT distance, rowid
                    FROM {table_name}
                    WHERE embedding MATCH ?
                    AND k = ?
                    ORDER BY distance
                """
            
            rows = conn.execute(sql, params).fetchall()
        return [(float(d), int(r)) for d, r in rows]

    def delete_vectors(self, table_name: str, vector_ids: Sequence[Any], **kwargs: Any) -> None:
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            self._load_extension(conn)
            for vid in vector_ids:
                try:
                    conn.execute(f"DELETE FROM {table_name} WHERE rowid = ?", (int(vid),))
                except Exception:
                    pass
            conn.commit()


_vector_provider: Optional[VectorSearchProvider] = None


def get_vector_provider() -> VectorSearchProvider:
    """获取向量检索提供者（单例，使用 core.data.base 的 db_path）。"""
    logger.debug("[get_vector_provider] Function called")
    global _vector_provider
    if _vector_provider is None:
        logger.debug("[get_vector_provider] Creating new SQLiteVecProvider instance")
        from core.data.base import get_db_path
        _vector_provider = SQLiteVecProvider(get_db_path())
        logger.debug(f"[get_vector_provider] Created provider instance {_vector_provider.instance_id}, is_available: {_vector_provider.is_available()}")
    else:
        logger.debug(f"[get_vector_provider] Using cached provider instance {_vector_provider.instance_id}, is_available: {_vector_provider.is_available()}")
    if not _vector_provider.is_available():
        raise RuntimeError("Vector search provider is not available")
    logger.debug(f"[get_vector_provider] Returning provider instance {_vector_provider.instance_id}")
    return _vector_provider
