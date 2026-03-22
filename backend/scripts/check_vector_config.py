#!/usr/bin/env python3
"""
检查向量搜索配置和依赖
"""
import sys
from pathlib import Path

# 添加 backend 目录到路径（脚本位于 backend/scripts/）
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from config.settings import settings
from core.memory.memory_store import MemoryStore, MemoryStoreConfig
from log import logger

def check_sqlite_vec():
    """检查 sqlite-vec 是否可用"""
    try:
        import sqlite_vec
        print("✅ sqlite-vec 已安装")
        return True
    except ImportError:
        print("❌ sqlite-vec 未安装")
        print("   提示: pip install sqlite-vec")
        return False

def check_vector_config():
    """检查向量配置"""
    print("\n=== 向量搜索配置检查 ===\n")
    
    print(f"memory_vector_enabled: {settings.memory_vector_enabled}")
    print(f"memory_embedding_dim: {settings.memory_embedding_dim}")
    print(f"memory_inject_mode: {settings.memory_inject_mode}")
    
    if not settings.memory_vector_enabled:
        print("\n⚠️  向量搜索未启用，即使安装了 sqlite-vec 也不会使用")
        return
    
    # 检查 sqlite-vec
    vec_available = check_sqlite_vec()
    
    if not vec_available:
        print("\n⚠️  向量搜索已启用但 sqlite-vec 未安装")
        print("   系统将自动降级到 Python cosine 相似度计算")
        print("   性能可能受影响，建议安装 sqlite-vec")
        return
    
    # 尝试初始化 MemoryStore 并检查向量功能
    try:
        config = MemoryStoreConfig(
            db_path=MemoryStore.default_db_path(),
            embedding_dim=settings.memory_embedding_dim,
            vector_enabled=True,
        )
        store = MemoryStore(config)
        
        if store._vec_available:
            print("\n✅ sqlite-vec 已成功加载并可用")
            print("   向量搜索功能已启用")
        else:
            print("\n⚠️  sqlite-vec 已安装但初始化失败")
            print("   系统将使用 Python cosine 降级方案")
    except Exception as e:
        print(f"\n❌ MemoryStore 初始化失败: {e}")
        logger.exception("MemoryStore init failed")

if __name__ == "__main__":
    check_vector_config()
