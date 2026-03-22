"""
将 per-KB 向量表（embedding_chunk_{kb_id}）迁移到统一表（embedding_chunks + kb_chunks_vec）。

用法（在 backend 目录、conda 环境）：
  conda run -n ai-inference-platform python scripts/migrate_kb_to_unified_chunks.py [--dry-run] [--kb-id KB_ID]

- 不传参数：迁移所有知识库的 per-KB 表到统一表。
- --kb-id：只迁移指定知识库。
- --dry-run：只打印将要迁移的表与行数，不写入。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# 确保 backend 在 path 中
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from core.knowledge.knowledge_base_store import (
    UNIFIED_CHUNKS_TABLE,
    UNIFIED_VEC_TABLE,
    KnowledgeBaseConfig,
    KnowledgeBaseStore,
)
from core.data.vector_search import get_vector_provider

import logging

logger = logging.getLogger(__name__)


def get_per_kb_table_names(store: KnowledgeBaseStore) -> list[tuple[str, str]]:
    """返回 (kb_id, table_name) 列表，仅包含存在的 per-KB 表。"""
    with store._connect() as conn:
        rows = conn.execute("SELECT id FROM knowledge_base").fetchall()
    out = []
    for row in rows:
        kb_id = row["id"]
        table_name = store._get_chunk_table_name(kb_id)
        try:
            with store._connect() as conn:
                if store._vec_available:
                    try:
                        conn.enable_load_extension(True)
                        try:
                            import sqlite_vec  # type: ignore
                            sqlite_vec.load(conn)  # type: ignore
                        finally:
                            conn.enable_load_extension(False)
                    except Exception:
                        pass
                conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
            out.append((kb_id, table_name))
        except sqlite3.OperationalError:
            continue
    return out


def migrate_one_kb(
    store: KnowledgeBaseStore,
    kb_id: str,
    table_name: str,
    dry_run: bool,
) -> int:
    """将单个 per-KB 表迁移到统一表。返回迁移行数。"""
    provider = get_vector_provider()
    if not provider.is_available() and not dry_run:
        raise RuntimeError("Vector search provider is not available")

    with store._connect() as conn:
        if store._vec_available:
            try:
                conn.enable_load_extension(True)
                try:
                    import sqlite_vec  # type: ignore
                    sqlite_vec.load(conn)  # type: ignore
                finally:
                    conn.enable_load_extension(False)
            except Exception:
                pass
        rows = conn.execute(
            f"SELECT embedding, document_id, chunk_id, content FROM {table_name}"
        ).fetchall()

    if not rows:
        return 0

    # 从第一行确定 embedding 维度
    first_emb = rows[0]["embedding"]
    if isinstance(first_emb, str):
        emb_list = json.loads(first_emb)
    else:
        emb_list = first_emb
    dim = len(emb_list)
    if not dry_run:
        store._ensure_unified_vec_table(dim)

    migrated = 0
    for row in rows:
        emb_raw = row["embedding"]
        document_id = row["document_id"]
        chunk_id = row["chunk_id"]
        content = row["content"] or ""
        if isinstance(emb_raw, str):
            embedding = json.loads(emb_raw)
        else:
            embedding = emb_raw

        if dry_run:
            migrated += 1
            continue

        with store._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {UNIFIED_CHUNKS_TABLE}
                (knowledge_base_id, document_id, chunk_id, content)
                VALUES (?, ?, ?, ?)
                """,
                (kb_id, document_id, chunk_id, content),
            )
            rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        provider.upsert_vector(
            table_name=UNIFIED_VEC_TABLE,
            vector_id=rowid,
            embedding=embedding,
        )
        migrated += 1

    return migrated


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate per-KB chunk tables to unified embedding_chunks + kb_chunks_vec")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be migrated")
    parser.add_argument("--kb-id", type=str, default=None, help="Migrate only this knowledge base ID")
    args = parser.parse_args()

    db_path = KnowledgeBaseStore.default_db_path()
    config = KnowledgeBaseConfig(db_path=db_path)
    store = KnowledgeBaseStore(config)

    if not store._use_unified_chunks_table():
        logger.error("Unified table embedding_chunks not found. Run: alembic upgrade head")
        return 1

    if args.kb_id:
        table_name = store._get_chunk_table_name(args.kb_id)
        try:
            with store._connect() as conn:
                if store._vec_available:
                    try:
                        conn.enable_load_extension(True)
                        try:
                            import sqlite_vec  # type: ignore
                            sqlite_vec.load(conn)  # type: ignore
                        finally:
                            conn.enable_load_extension(False)
                    except Exception:
                        pass
                conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            logger.error("Per-KB table %s does not exist", table_name)
            return 1
        candidates = [(args.kb_id, table_name)]
    else:
        candidates = get_per_kb_table_names(store)

    if not candidates:
        logger.info("No per-KB chunk tables to migrate.")
        return 0

    total = 0
    for kb_id, table_name in candidates:
        n = migrate_one_kb(store, kb_id, table_name, dry_run=args.dry_run)
        total += n
        logger.info("KB %s table %s: %s %d chunks", kb_id, table_name, "would migrate" if args.dry_run else "migrated", n)

    logger.info("Total: %s %d chunks", "would migrate" if args.dry_run else "migrated", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
