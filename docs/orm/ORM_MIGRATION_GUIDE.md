# ORM 迁移实施指南

> 详细的代码示例与最佳实践

本文档是 [ORM_MIGRATION_PLAN.md](ORM_MIGRATION_PLAN.md) 的补充，提供具体的代码示例和实施细节。

---

## 📦 阶段 1：基础设施搭建

### 1.1 依赖安装

**requirements.txt：**
```txt
sqlalchemy>=2.0.0
```

### 1.2 数据库连接管理

**文件：`backend/core/data/base.py`**

```python
"""
数据库连接与 Session 管理
"""
from pathlib import Path
from typing import Generator, Iterator
from contextlib import contextmanager
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from config.settings import settings
from core.logger import logger

# Base 类用于定义 ORM 模型
Base = declarative_base()

# 元数据（用于表创建）
metadata = MetaData()

def get_db_path() -> Path:
    """获取数据库路径"""
    if settings.db_path:
        return Path(settings.db_path)
    root = Path(__file__).resolve().parents[3]
    return root / "backend" / "data" / "platform.db"

def create_engine_instance():
    """创建数据库引擎"""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # SQLite 连接字符串
    db_url = f"sqlite:///{db_path}"
    
    engine = create_engine(
        db_url,
        connect_args={
            "check_same_thread": False,  # SQLite 需要（多线程）
            "timeout": 20.0,  # 连接超时
        },
        echo=False,  # 生产环境关闭 SQL 日志
        pool_pre_ping=True,  # 连接池健康检查
    )
    
    return engine

# 全局引擎实例
_engine = create_engine_instance()

# Session 工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=_engine,
    expire_on_commit=False,  # 提交后对象仍可用
)

def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话（依赖注入模式）
    
    ✅ 正确用法（FastAPI）：把它作为 Depends(get_db) 使用，
    yield 的 finally 会在请求结束时自动执行。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Iterator[Session]:
    """
    获取数据库会话（非 FastAPI Depends 场景）。

    ✅ 推荐用法（脚本/后台任务/纯函数）：
        with db_session() as db:
            ...
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    """初始化数据库（创建所有表）"""
    Base.metadata.create_all(bind=_engine)
    logger.info("[Data] Database tables created")

def get_engine():
    """获取引擎实例（用于迁移脚本等）"""
    return _engine
```

### 1.3 向量检索抽象层

**文件：`backend/core/data/vector_search.py`**

```python
"""
向量检索抽象层
"""
from abc import ABC, abstractmethod
from typing import List, Tuple, Any, Optional, Dict, Sequence
from pathlib import Path
from core.logger import logger
from config.settings import settings


class VectorSearchProvider(ABC):
    """
    向量检索提供者抽象接口。

    重要：当前系统的 sqlite-vec 用法是「vec 表 rowid 与业务表 rowid 对齐，然后 JOIN」。
    因此 Provider 的稳定契约应以 **rowid/主键映射** 为核心，而不是“插入时附带任意 metadata”。
    同一抽象可对接：sqlite-vec、pgvector、Chroma、Milvus 等；Chroma/Milvus 无 rowid，
    则用业务主键（如 chunk_id）作为向量 id，search() 仍返回 (distance, id)，由 Store 用 id 查业务表。
    """
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查提供者是否可用"""
        pass
    
    @abstractmethod
    def create_table(self, table_name: str, dimension: int, **kwargs) -> None:
        """
        创建向量表
        
        Args:
            table_name: 表名
            dimension: 向量维度
            **kwargs: 额外参数（如 knowledge_base_id）
        """
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
        **kwargs,
    ) -> None:
        """
        写入/覆盖向量。

        - sqlite-vec/pgvector/MySQL（嵌入式向量）：`vector_id` 通常就是业务表 rowid/主键（便于 JOIN）。
        - Chroma/Milvus（专用向量库）：`vector_id` 通常是业务主键（如 chunk_id、memory_id）。
        """
        pass
    
    @abstractmethod
    def search(
        self,
        table_name: str,
        query_vector: List[float],
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Tuple[float, Any]]:
        """
        向量检索
        
        Args:
            table_name: 表名
            query_vector: 查询向量
            limit: 返回数量
            filters: 过滤条件（如 user_id, knowledge_base_id）
            **kwargs: 额外参数
        
        Returns:
            List of (distance, vector_id)
        """
        pass
    
    @abstractmethod
    def delete_vectors(self, table_name: str, vector_ids: Sequence[Any], **kwargs) -> None:
        """删除向量（vector_ids 可能是 rowid，也可能是业务 id）"""
        pass


class SQLiteVecProvider(VectorSearchProvider):
    """sqlite-vec 实现"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._vec_available = False
        self._check_availability()
    
    def _check_availability(self) -> None:
        """检查 sqlite-vec 是否可用"""
        try:
            import sqlite_vec  # type: ignore
            self._vec_available = True
        except ImportError:
            self._vec_available = False
            logger.warning("[SQLiteVecProvider] sqlite-vec not available")
    
    def is_available(self) -> bool:
        return self._vec_available
    
    def _load_extension(self, conn) -> None:
        """加载 sqlite-vec 扩展"""
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available")
        try:
            import sqlite_vec  # type: ignore
            conn.enable_load_extension(True)
            try:
                sqlite_vec.load(conn)  # type: ignore
            finally:
                conn.enable_load_extension(False)
        except Exception as e:
            raise RuntimeError(f"Failed to load sqlite-vec: {e}") from e
    
    def create_table(self, table_name: str, dimension: int, **kwargs) -> None:
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            self._load_extension(conn)
            # sqlite-vec 表创建语法
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {table_name}
                USING vec0(
                    embedding float[{dimension}]
                )
            """)
            conn.commit()
    
    def table_exists(self, table_name: str) -> bool:
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            return cursor.fetchone() is not None
    
    def upsert_vector(
        self,
        table_name: str,
        *,
        vector_id: Any,
        embedding: Sequence[float] | bytes,
        metadata: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> None:
        import sqlite3
        
        with sqlite3.connect(str(self.db_path)) as conn:
            self._load_extension(conn)
            # 现有代码里有两种向量存储形态：
            # - JSON array（KnowledgeBaseStore 部分）
            # - float32 blob（MemoryStore 部分，_vec_to_blob）
            #
            # 因此这里允许 embedding 既可以是 Sequence[float]，也可以是 bytes。
            if isinstance(embedding, (bytes, bytearray)):
                value = bytes(embedding)
            else:
                # sqlite-vec 也支持 JSON array 形式
                import json
                value = json.dumps(list(embedding))

            # SQLiteVecProvider：vector_id 约定为 int rowid（与现有 Store JOIN 语义一致）
            rowid = int(vector_id)
            conn.execute(
                f"INSERT OR REPLACE INTO {table_name}(rowid, embedding) VALUES (?, ?);",
                (int(rowid), value),
            )
            conn.commit()
    
    def search(
        self,
        table_name: str,
        query_vector: List[float],
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Tuple[float, Any]]:
        import sqlite3
        import json
        
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available")
        
        query_vec_json = json.dumps(query_vector)
        
        with sqlite3.connect(str(self.db_path)) as conn:
            self._load_extension(conn)
            # sqlite-vec MATCH 查询语法
            # 注意：需要 JOIN 主表获取 metadata
            sql = f"""
                SELECT distance, rowid
                FROM {table_name}
                WHERE embedding MATCH ?
                AND k = ?
                ORDER BY distance
            """
            rows = conn.execute(sql, (query_vec_json, limit)).fetchall()
            
            # 返回 (distance, vector_id)；在 SQLiteVecProvider 下 vector_id == rowid(int)
            results = []
            for distance, rowid in rows:
                results.append((float(distance), int(rowid)))
            
            return results
    
    def delete_vectors(self, table_name: str, vector_ids: Sequence[Any], **kwargs) -> None:
        import sqlite3
        with sqlite3.connect(str(self.db_path)) as conn:
            # 根据实际表结构实现删除逻辑
            # sqlite-vec 表通常需要 JOIN 主表删除
            pass


# 全局 Provider 实例（单例）
_vector_provider: Optional[VectorSearchProvider] = None

def get_vector_provider() -> VectorSearchProvider:
    """获取向量检索提供者（工厂函数）"""
    global _vector_provider
    if _vector_provider is None:
        from core.data.base import get_db_path
        db_path = get_db_path()
        _vector_provider = SQLiteVecProvider(db_path)
    
    if not _vector_provider.is_available():
        raise RuntimeError("Vector search provider is not available")
    
    return _vector_provider
```

---

## 📝 阶段 2：简单 Store 迁移示例

### 2.1 SystemSettingsStore 迁移示例

**之前（SQLite 原生）：**
```python
# backend/core/system/settings_store.py
import sqlite3

class SystemSettingsStore:
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_setting(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = ?",
                (key,)
            ).fetchone()
            return row["value"] if row else None
    
    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value)
            )
```

**之后（SQLAlchemy ORM）：**
```python
# backend/core/data/models/system.py
from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from core.data.base import Base

class SystemSetting(Base):
    __tablename__ = "system_settings"
    
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

# backend/core/system/settings_store.py
from sqlalchemy.dialects.sqlite import insert
from core.data.base import get_db
from core.data.models.system import SystemSetting

class SystemSettingsStore:
    def get_setting(self, key: str) -> Optional[str]:
        from core.data.base import db_session
        with db_session() as db:
            setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            return setting.value if setting else None
    
    def set_setting(self, key: str, value: str) -> None:
        from core.data.base import db_session
        with db_session() as db:
            stmt = insert(SystemSetting).values(key=key, value=value)
            stmt = stmt.on_conflict_do_update(index_elements=['key'], set_={'value': stmt.excluded.value})
            db.execute(stmt)
```

### 2.2 ModelRegistry 迁移示例

**ORM 模型定义：**
```python
# backend/core/data/models/model.py
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from core.data.base import Base

class Model(Base):
    __tablename__ = "models"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    model_type = Column(String, default='llm')
    provider = Column(String, nullable=False)
    provider_model_id = Column(String, nullable=False)
    runtime = Column(String, nullable=False)
    base_url = Column(String)
    capabilities_json = Column(Text)  # JSON 存储
    context_length = Column(Integer)
    device = Column(String)
    quantization = Column(String)
    size = Column(String)
    format = Column(String)
    source = Column(String)
    family = Column(String)
    version = Column(String)
    description = Column(Text)
    tags_json = Column(Text)  # JSON 存储
    metadata_json = Column(Text)  # JSON 存储
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 关系
    config = relationship("ModelConfig", back_populates="model", uselist=False)

class ModelConfig(Base):
    __tablename__ = "model_configs"
    
    model_id = Column(String, ForeignKey("models.id"), primary_key=True)
    chat_params_json = Column(Text)  # JSON 存储
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 关系
    model = relationship("Model", back_populates="config")
```

**Store 重构：**
```python
# backend/core/models/registry.py
import json
from typing import List, Optional
from sqlalchemy.dialects.sqlite import insert
from core.data.base import db_session
from core.data.models.model import Model, ModelConfig
from core.models.descriptor import ModelDescriptor

class ModelRegistry:
    def upsert_model(self, descriptor: ModelDescriptor) -> None:
        with db_session() as db:
            # 1. UPSERT Model
            stmt = insert(Model).values(
                id=descriptor.id,
                name=descriptor.name,
                model_type=descriptor.model_type,
                provider=descriptor.provider,
                provider_model_id=descriptor.provider_model_id,
                runtime=descriptor.runtime,
                base_url=descriptor.base_url,
                capabilities_json=json.dumps(descriptor.capabilities),
                context_length=descriptor.context_length,
                device=descriptor.device,
                quantization=descriptor.quantization,
                size=descriptor.size,
                format=descriptor.format,
                source=descriptor.source,
                family=descriptor.family,
                version=descriptor.version,
                description=descriptor.description,
                tags_json=json.dumps(descriptor.tags),
                metadata_json=json.dumps(descriptor.metadata),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'name': stmt.excluded.name,
                    'model_type': stmt.excluded.model_type,
                    # ... 其他字段
                }
            )
            db.execute(stmt)
    
    def get_model(self, model_id: str) -> Optional[ModelDescriptor]:
        with db_session() as db:
            model = db.query(Model).filter(Model.id == model_id).first()
            if not model:
                return None
            return self._orm_to_descriptor(model)
    
    def _orm_to_descriptor(self, model: Model) -> ModelDescriptor:
        """ORM 对象转 ModelDescriptor"""
        return ModelDescriptor(
            id=model.id,
            name=model.name,
            model_type=model.model_type or 'llm',
            provider=model.provider,
            provider_model_id=model.provider_model_id,
            runtime=model.runtime,
            base_url=model.base_url,
            capabilities=json.loads(model.capabilities_json or "[]"),
            context_length=model.context_length,
            device=model.device,
            quantization=model.quantization,
            size=model.size,
            format=model.format,
            source=model.source,
            family=model.family,
            version=model.version,
            description=model.description,
            tags=json.loads(model.tags_json or "[]"),
            metadata=json.loads(model.metadata_json or "{}")
        )
```

---

## 🔄 阶段 4：向量检索 Store 迁移示例

### 4.1 MemoryStore 向量检索迁移

**之前：**
```python
# backend/core/memory/memory_store.py
def search(self, user_id: str, query: str, limit: int = 10) -> List[MemoryItem]:
    qvec = self._embedder.embed(query)
    
    if self._vec_available:
        blob = self._vec_to_blob(qvec)
        with self._connect() as conn:
            # 直接使用 sqlite-vec
            rows = conn.execute(
                """
                SELECT m.*, v.distance
                FROM memory_vec v
                JOIN memory_items m ON m.rowid = v.rowid
                WHERE v.embedding MATCH ?
                  AND m.user_id = ?
                  AND v.k = ?
                ORDER BY v.distance
                """,
                (blob, user_id, limit)
            ).fetchall()
            return [self._row_to_item(r) for r in rows]
```

**之后：**
```python
# backend/core/memory/memory_store.py
from core.data.vector_search import get_vector_provider

def search(self, user_id: str, query: str, limit: int = 10) -> List[MemoryItem]:
    qvec = self._embedder.embed(query)
    
    try:
        provider = get_vector_provider()
        # Provider 返回 (distance, rowid)
        results = provider.search(
            table_name="memory_vec",
            query_vector=qvec,
            limit=limit,
            filters={"user_id": user_id}
        )
        
        # Store 负责把 rowid 映射回业务表（与现有 JOIN 语义一致）
        memory_items = []
        from core.data.base import db_session
        with db_session() as db:
            for distance, rowid in results:
                memory = db.query(MemoryItemORM).filter(MemoryItemORM.rowid == rowid).first()
                if memory:
                    memory_items.append(self._orm_to_item(memory))
        
        return memory_items
    except RuntimeError:
        # 降级到 Python cosine
        return self._fallback_cosine_search(user_id, qvec, limit)
```

---

## 🧪 测试示例

### 单元测试示例

```python
# tests/test_model_registry.py
import pytest
from core.models.registry import ModelRegistry
from core.models.descriptor import ModelDescriptor

def test_upsert_model():
    registry = ModelRegistry()
    descriptor = ModelDescriptor(
        id="test:model1",
        name="Test Model",
        provider="test",
        provider_model_id="model1",
        runtime="test",
        capabilities=["chat"]
    )
    
    registry.upsert_model(descriptor)
    
    retrieved = registry.get_model("test:model1")
    assert retrieved is not None
    assert retrieved.name == "Test Model"
```

### 集成测试示例

```python
# tests/integration/test_agent_api.py
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_create_agent():
    response = client.post("/api/agents", json={
        "name": "Test Agent",
        "model_id": "test:model1",
        "enabled_skills": ["builtin_file.read"]
    })
    assert response.status_code == 200
    assert response.json()["success"] is True
```

---

## 📋 迁移检查清单模板

### Store 迁移检查清单

**Store 名称：** `[StoreName]`

- [ ] **ORM 模型定义**
  - [ ] 表结构映射正确
  - [ ] 字段类型正确（JSON 字段使用 `Text` + `json.loads/dumps`）
  - [ ] 关系定义正确（如 `relationship`）
  
- [ ] **连接管理**
  - [ ] `_connect()` 方法已移除
  - [ ] 使用 `get_db()` 获取 Session
  - [ ] Session 正确关闭（`try/finally`）
  
- [ ] **UPSERT 迁移**
  - [ ] `ON CONFLICT` 替换为 `insert().on_conflict_do_update()`
  - [ ] 测试：插入新记录
  - [ ] 测试：更新已存在记录
  
- [ ] **查询迁移**
  - [ ] `sqlite3.Row` 替换为 ORM 对象
  - [ ] `_row_to_*` 方法替换为 `_orm_to_*`
  - [ ] 复杂查询使用 SQLAlchemy Query API
  
- [ ] **元数据查询**
  - [ ] `PRAGMA table_info` 已移除或替换为 `inspect()`
  - [ ] 迁移脚本已运行（如需要）
  
- [ ] **测试**
  - [ ] 单元测试通过
  - [ ] 集成测试通过
  - [ ] API 接口兼容性测试通过

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd backend
conda activate ai-inference-platform
pip install sqlalchemy>=2.0.0
```

### 2. 创建基础结构

```bash
mkdir -p backend/core/data/models
touch backend/core/data/__init__.py
touch backend/core/data/base.py
touch backend/core/data/vector_search.py
touch backend/core/data/models/__init__.py
```

### 3. 从最简单的 Store 开始

建议顺序：
1. `SystemSettingsStore`（最简单，无复杂逻辑）
2. `ModelRegistry`（中等复杂度，有 JSON 字段）
3. `AgentRegistry`（类似 ModelRegistry）
4. `SkillStore`（类似 ModelRegistry）
5. 其他 Store...

---

## 💡 最佳实践

### 1. Session 管理

**✅ 正确：**
```python
from core.data.base import db_session

def some_function():
    with db_session() as db:
        return db.query(Model).all()
```

**✅ FastAPI 场景（依赖注入）：**
```python
from fastapi import Depends
from sqlalchemy.orm import Session
from core.data.base import get_db

@router.get("/something")
def handler(db: Session = Depends(get_db)):
    return db.query(Model).all()
```

### 2. JSON 字段处理

**✅ 正确：**
```python
class Model(Base):
    capabilities_json = Column(Text)  # 存储 JSON 字符串

# 序列化
model.capabilities_json = json.dumps(capabilities)

# 反序列化
capabilities = json.loads(model.capabilities_json or "[]")
```

**⚠️ 注意：** 建议在 SQLite 阶段继续使用 `Text` + `json.loads/dumps`（行为最确定）；切换 PostgreSQL 后再升级为 `JSONB` 并利用原生 JSON 查询能力。

### 3. 事务管理

**✅ 正确（推荐用 db_session，自动 commit/rollback）：**
```python
from core.data.base import db_session

with db_session() as db:
    db.add(new_model)
    # 正常退出时自动 commit，异常时自动 rollback
```

### 4. 批量操作

**✅ 使用 bulk 操作：**
```python
# 批量插入
db.bulk_insert_mappings(Model, [
    {"id": "1", "name": "Model 1"},
    {"id": "2", "name": "Model 2"},
])
db.commit()
```

---

## 🔍 常见问题

### Q1: 如何处理动态表名（如 `embedding_chunk_{kb_id}`）？

**A:** 使用 SQLAlchemy `Table` 对象动态创建：

```python
from sqlalchemy import Table, Column, String

def get_chunk_table(kb_id: str) -> Table:
    table_name = f"embedding_chunk_{kb_id}"
    return Table(
        table_name,
        metadata,
        Column("id", String, primary_key=True),
        # ... 其他列
    )
```

### Q2: 如何保持向后兼容（迁移期间）？

**A:** 使用适配器模式：

```python
class ModelRegistry:
    def __init__(self):
        self._use_orm = settings.use_orm  # 配置开关
    
    def get_model(self, model_id: str):
        if self._use_orm:
            return self._get_model_orm(model_id)
        else:
            return self._get_model_sqlite(model_id)
```

### Q3: 向量检索性能如何保证？

**A:** 
- 封装层保持最小开销（直接调用底层 API）
- 必要时在 `VectorSearchProvider` 中提供"快速路径"
- 性能测试：确保封装后性能损失 < 5%

---

**文档版本：** v1.0  
**创建日期：** 2026-02-02  
**最后更新：** 2026-02-02
