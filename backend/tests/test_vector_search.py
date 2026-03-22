"""
SQLiteVecProvider 单元测试。需在 backend 目录下运行：pytest tests/test_vector_search.py
若未安装 sqlite-vec，相关测试会 skip。
"""
import tempfile
from pathlib import Path

import pytest

from core.data.vector_search import SQLiteVecProvider, VectorSearchProvider


def _provider_available() -> bool:
    p = SQLiteVecProvider(Path(tempfile.mktemp(suffix=".db")))
    return p.is_available()


@pytest.mark.skipif(not _provider_available(), reason="sqlite-vec not available")
class TestSQLiteVecProvider:
    """SQLiteVecProvider 基本功能（需 sqlite-vec 已安装）。"""

    @pytest.fixture
    def db_path(self) -> Path:
        fd, path = tempfile.mkstemp(suffix=".db")
        Path(path).unlink(missing_ok=True)
        return Path(path)

    @pytest.fixture
    def provider(self, db_path: Path) -> VectorSearchProvider:
        return SQLiteVecProvider(db_path)

    def test_create_table_and_exists(self, provider: VectorSearchProvider, db_path: Path) -> None:
        assert not provider.table_exists("vec_test")
        provider.create_table("vec_test", dimension=4)
        assert provider.table_exists("vec_test")

    def test_upsert_and_search(self, provider: VectorSearchProvider, db_path: Path) -> None:
        provider.create_table("vec_search_test", dimension=3)
        # rowid 1, 2, 3
        provider.upsert_vector("vec_search_test", vector_id=1, embedding=[1.0, 0.0, 0.0])
        provider.upsert_vector("vec_search_test", vector_id=2, embedding=[0.9, 0.1, 0.0])
        provider.upsert_vector("vec_search_test", vector_id=3, embedding=[0.0, 1.0, 0.0])
        # 查询与 [1,0,0] 最近
        results = provider.search("vec_search_test", query_vector=[1.0, 0.0, 0.0], limit=2)
        assert len(results) == 2
        distances, ids = zip(*results)
        assert 1 in ids
        assert 2 in ids
        assert ids[0] == 1  # 最近的是 rowid=1

    def test_delete_vectors(self, provider: VectorSearchProvider, db_path: Path) -> None:
        provider.create_table("vec_del_test", dimension=2)
        provider.upsert_vector("vec_del_test", vector_id=10, embedding=[1.0, 0.0])
        results = provider.search("vec_del_test", query_vector=[1.0, 0.0], limit=5)
        assert len(results) == 1 and results[0][1] == 10
        provider.delete_vectors("vec_del_test", [10])
        results2 = provider.search("vec_del_test", query_vector=[1.0, 0.0], limit=5)
        assert len(results2) == 0
