"""
KnowledgeBaseStore 单元测试：CRUD、向量检索、统一表路径。

运行（在 backend 目录）：
  pytest tests/test_knowledge_base_store.py -v
  pytest tests/test_knowledge_base_store.py -v -k "test_crud"  # 仅 CRUD

说明：
- 默认 store 使用临时 DB，未跑 Alembic，故 _use_unified_chunks_table() 为 False。
- store_with_unified 会在同一临时 DB 上创建 embedding_chunks 表，用于测试统一表路径。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.knowledge.knowledge_base_store import (
    UNIFIED_CHUNKS_TABLE,
    KnowledgeBaseConfig,
    KnowledgeBaseStore,
)
from core.knowledge.status import KnowledgeBaseStatus, DocumentStatus


def _create_embedding_chunks_table(store: KnowledgeBaseStore) -> None:
    """在 store 的 DB 中创建 embedding_chunks 表（与 Alembic a1b2c3d4e5f6 一致），便于测试统一表路径。"""
    with store._connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_chunks (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                knowledge_base_id VARCHAR NOT NULL,
                document_id VARCHAR NOT NULL,
                chunk_id VARCHAR NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_chunks_kb_id ON embedding_chunks (knowledge_base_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_chunks_doc_id ON embedding_chunks (document_id)"
        )
        conn.commit()


@pytest.fixture
def db_path() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    Path(path).unlink(missing_ok=True)
    return Path(path)


@pytest.fixture
def store(db_path: Path) -> KnowledgeBaseStore:
    return KnowledgeBaseStore(KnowledgeBaseConfig(db_path=db_path))


@pytest.fixture
def store_with_unified(db_path: Path) -> KnowledgeBaseStore:
    """Store 使用同一临时 DB，并已创建 embedding_chunks 表，_use_unified_chunks_table() 为 True。"""
    s = KnowledgeBaseStore(KnowledgeBaseConfig(db_path=db_path))
    _create_embedding_chunks_table(s)
    return s


class TestKnowledgeBaseCRUD:
    """知识库 CRUD 测试（不依赖 sqlite-vec）。"""

    def test_create_and_get_knowledge_base(self, store: KnowledgeBaseStore) -> None:
        kb_id = store.create_knowledge_base(
            name="Test KB",
            description="Desc",
            embedding_model_id="embedding:test",
        )
        assert kb_id.startswith("kb_")
        kb = store.get_knowledge_base(kb_id)
        assert kb is not None
        assert kb["name"] == "Test KB"
        assert kb["description"] == "Desc"
        assert kb["embedding_model_id"] == "embedding:test"
        assert kb["status"] == KnowledgeBaseStatus.EMPTY

    def test_list_knowledge_bases(self, store: KnowledgeBaseStore) -> None:
        assert store.list_knowledge_bases() == []
        store.create_knowledge_base("A", None, "emb:1")
        store.create_knowledge_base("B", "B desc", "emb:1")
        lst = store.list_knowledge_bases()
        assert len(lst) == 2
        names = {x["name"] for x in lst}
        assert names == {"A", "B"}

    def test_update_and_delete_knowledge_base(self, store: KnowledgeBaseStore) -> None:
        kb_id = store.create_knowledge_base("Original", None, "emb:1")
        store.update_knowledge_base(kb_id, name="Updated", description="New desc")
        kb = store.get_knowledge_base(kb_id)
        assert kb["name"] == "Updated"
        assert kb["description"] == "New desc"
        assert store.delete_knowledge_base(kb_id) is True
        assert store.get_knowledge_base(kb_id) is None

    def test_create_and_list_documents(self, store: KnowledgeBaseStore) -> None:
        kb_id = store.create_knowledge_base("KB", None, "emb:1")
        doc_id = store.create_document(
            knowledge_base_id=kb_id,
            source="file.pdf",
            doc_type="pdf",
        )
        assert doc_id.startswith("doc_")
        docs = store.list_documents(kb_id)
        assert len(docs) == 1
        assert docs[0]["source"] == "file.pdf"
        assert docs[0]["doc_type"] == "pdf"
        assert docs[0]["status"] == DocumentStatus.UPLOADED

    def test_get_and_delete_document(self, store: KnowledgeBaseStore) -> None:
        kb_id = store.create_knowledge_base("KB", None, "emb:1")
        doc_id = store.create_document(kb_id, "x.txt", "text")
        doc = store.get_document(doc_id)
        assert doc is not None
        assert doc["knowledge_base_id"] == kb_id
        assert store.delete_document(doc_id) is True
        assert store.get_document(doc_id) is None


class TestKnowledgeBaseUnifiedChunks:
    """统一表 embedding_chunks 相关测试。"""

    def test_use_unified_table_detection_without_table(self, store: KnowledgeBaseStore) -> None:
        """临时 DB 未创建 embedding_chunks 时，应为 False。"""
        assert store._use_unified_chunks_table() is False

    def test_use_unified_table_detection_with_table(self, store_with_unified: KnowledgeBaseStore) -> None:
        """创建 embedding_chunks 表后，应为 True（与 Alembic 迁移后行为一致）。"""
        assert store_with_unified._use_unified_chunks_table() is True

    def test_list_chunks_empty(self, store: KnowledgeBaseStore) -> None:
        kb_id = store.create_knowledge_base("KB", None, "emb:1")
        chunks = store.list_chunks(knowledge_base_id=kb_id, limit=10)
        assert chunks == []

    def test_list_chunks_empty_unified_path(self, store_with_unified: KnowledgeBaseStore) -> None:
        """统一表路径下无 chunk 时 list_chunks 返回空。"""
        kb_id = store_with_unified.create_knowledge_base("KB", None, "emb:1")
        chunks = store_with_unified.list_chunks(knowledge_base_id=kb_id, limit=10)
        assert chunks == []

    def test_get_chunk_count_empty(self, store: KnowledgeBaseStore) -> None:
        kb_id = store.create_knowledge_base("KB", None, "emb:1")
        assert store.get_chunk_count(knowledge_base_id=kb_id) == 0
        assert store.get_chunk_count(knowledge_base_id=None) >= 0

    def test_get_chunk_count_empty_unified_path(self, store_with_unified: KnowledgeBaseStore) -> None:
        """统一表路径下 get_chunk_count 为 0。"""
        kb_id = store_with_unified.create_knowledge_base("KB", None, "emb:1")
        assert store_with_unified.get_chunk_count(knowledge_base_id=kb_id) == 0


def _vec_available(store: KnowledgeBaseStore) -> bool:
    return getattr(store, "_vec_available", False)


@pytest.mark.skipif(
    True,  # 仅当 sqlite-vec 可用且统一表存在时可改为 False，或通过 env 控制
    reason="Optional: run with sqlite-vec and unified table to test vector path",
)
class TestKnowledgeBaseVectorSearch:
    """向量检索测试（需 sqlite-vec + 统一表）。"""

    def test_insert_and_search_chunks(self, store: KnowledgeBaseStore) -> None:
        if not _vec_available(store) or not store._use_unified_chunks_table():
            pytest.skip("sqlite-vec or unified table not available")
        kb_id = store.create_knowledge_base("KB", None, "emb:1")
        doc_id = store.create_document(kb_id, "doc1", "txt")
        vec = [0.1] * 256 + [0.9] * 256  # 512-dim placeholder
        store.insert_chunk(kb_id, doc_id, "chunk_1", "hello world", vec)
        results = store.search_chunks(kb_id, vec, limit=5)
        assert len(results) >= 1
        assert results[0]["content"] == "hello world"
        assert results[0]["document_id"] == doc_id
        assert results[0]["chunk_id"] == "chunk_1"


class TestRAGFlowIntegration:
    """RAG 检索流程集成测试（轻量：只测接口与返回结构）。"""

    def test_search_chunks_return_shape(self, store: KnowledgeBaseStore) -> None:
        kb_id = store.create_knowledge_base("KB", None, "emb:1")
        # 无向量时 search_chunks 可能抛或返回 []，取决于是否启用 vec
        try:
            results = store.search_chunks(
                knowledge_base_id=kb_id,
                query_embedding=[0.0] * 512,
                limit=5,
            )
            for r in results:
                assert "content" in r
                assert "distance" in r
                assert "document_id" in r
                assert "chunk_id" in r
                assert "doc_source" in r or "doc_type" in r
        except RuntimeError as e:
            if "sqlite-vec is not available" in str(e) or "Vector search provider" in str(e):
                pytest.skip("Vector search not available")

    def test_search_chunks_multi_kb_return_shape(self, store: KnowledgeBaseStore) -> None:
        kb1 = store.create_knowledge_base("KB1", None, "emb:1")
        try:
            results = store.search_chunks_multi_kb(
                knowledge_base_ids=[kb1],
                query_embedding=[0.0] * 512,
                limit=5,
            )
            for r in results:
                assert "content" in r
                assert "distance" in r
                assert "knowledge_base_id" in r
        except RuntimeError as e:
            if "sqlite-vec is not available" in str(e):
                pytest.skip("Vector search not available")
