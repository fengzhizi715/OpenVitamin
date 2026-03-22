# ORM 迁移计划

> 引入 ORM 抽象层，为未来数据库切换做准备

## 📋 概述

### 目标

1. **引入 SQLAlchemy ORM**：统一数据访问层，提升代码可维护性
2. **保持 SQLite 兼容**：迁移期间仍使用 SQLite，不影响现有功能
3. **降低未来切换成本**：切换到 PostgreSQL/MySQL 时，**CRUD 与基础查询**可主要通过修改连接配置/方言完成；但 **向量检索、索引与性能调优**仍需额外适配
4. **抽象向量检索**：统一向量检索接口，支持多种向量后端：当前 `sqlite-vec`；未来可为 **pgvector / MySQL 向量索引**，或 **专用向量库（Chroma、Milvus 等）**，通过同一 Provider 接口切换

### 原则

- **渐进式迁移**：逐个 Store 重构，不一次性改动
- **向后兼容**：迁移过程中保持 API 接口不变
- **测试驱动**：每个 Store 重构后立即测试，确保功能正常

---

## 🔍 当前状态分析

### Store 类清单（9 个）

| Store 类 | 文件路径 | 表数量 | SQLite 特性 | 复杂度 |
|---------|---------|--------|------------|--------|
| `ModelRegistry` | `core/models/registry.py` | 2 | `ON CONFLICT`, `sqlite3.Row` | ⭐⭐ |
| `AgentRegistry` | `core/agent_runtime/definition.py` | 1 | `ON CONFLICT`, `sqlite3.Row` | ⭐⭐ |
| `AgentSessionStore` | `core/agent_runtime/session.py` | 1 | `ON CONFLICT`, `PRAGMA table_info` | ⭐⭐⭐ |
| `AgentTraceStore` | `core/agent_runtime/trace.py` | 1 | `PRAGMA table_info`, `sqlite3.Row` | ⭐⭐ |
| `SkillStore` | `core/skills/store.py` | 1 | `sqlite3.Row` | ⭐⭐ |
| `KnowledgeBaseStore` | `core/knowledge/knowledge_base_store.py` | 3+ | `sqlite-vec MATCH`, `ON CONFLICT` | ⭐⭐⭐⭐⭐ |
| `HistoryStore` | `core/conversation/history_store.py` | 2 | `sqlite-vec MATCH` | ⭐⭐⭐⭐ |
| `MemoryStore` | `core/memory/memory_store.py` | 2 | `sqlite-vec MATCH`, `PRAGMA table_info` | ⭐⭐⭐⭐ |
| `SystemSettingsStore` | `core/system/settings_store.py` | 1 | `ON CONFLICT` | ⭐ |

### SQLite 特有特性使用情况

| 特性 | 使用位置 | 影响范围 | ORM 替代方案 |
|------|---------|---------|------------|
| `ON CONFLICT ... DO UPDATE SET` | 所有 Store（UPSERT） | 高 | SQLAlchemy `insert().on_conflict_do_update()` |
| `PRAGMA table_info()` | 3 个 Store（元数据查询） | 中 | SQLAlchemy `inspect()` 或 `__table__.columns` |
| `sqlite3.Row` | 所有 Store（行对象） | 中 | SQLAlchemy ORM 对象或 `RowMapping` |
| `sqlite-vec` 扩展 | 3 个 Store（向量检索） | 高 | 抽象为 `VectorSearchProvider` 接口 |
| `conn.enable_load_extension()` | 向量检索 Store | 中 | 封装在 `VectorSearchProvider` 实现中 |

---

## 🛠️ 技术选型

### SQLAlchemy 2.0

**选择理由：**
- Python 生态最成熟的 ORM
- 支持多数据库后端（SQLite / PostgreSQL / MySQL）
- 类型提示完善（SQLAlchemy 2.0 + `mapped_column`）
- 异步支持（`AsyncSession`）
- 向量扩展支持（通过自定义类型）

**版本要求：**
```python
sqlalchemy>=2.0.0
```

### 向量检索抽象层

**设计原则：**
- 与**关系型库内嵌向量**（sqlite-vec / pgvector / MySQL）兼容：通过 rowid 或主键与业务表 JOIN。
- 与**专用向量库**（Chroma、Milvus 等）兼容：通过 collection/namespace + 业务主键（如 chunk_id）标识，检索返回 `(distance, id)`，由 Store 用 id 查业务数据。
- 接口契约：`search()` 统一返回 `List[Tuple[float, Any]]`（如 `(distance, rowid)` 或 `(distance, chunk_id)`），由各 Store 根据 id 类型自行解析。

**接口示意（详见 ORM_MIGRATION_GUIDE）：**
```python
# core/data/vector_search.py
class VectorSearchProvider(ABC):
    """向量检索提供者抽象接口（支持 sqlite-vec / pgvector / Chroma / Milvus 等）"""
    
    @abstractmethod
    def create_table(self, table_name: str, dimension: int, **kwargs) -> None: ...
    
    @abstractmethod
    def upsert_vector(self, table_name: str, *, vector_id: Any, embedding: ..., metadata: Optional[Dict]=None, namespace: Optional[str]=None, **kwargs) -> None:
        """写入/覆盖向量：sqlite-vec/pg 下 vector_id 通常是 rowid；Chroma/Milvus 下 vector_id 通常是业务 id"""
        pass
    
    @abstractmethod
    def search(self, table_name: str, query_vector: List[float], limit: int, filters: Optional[Dict]=None, **kwargs) -> List[Tuple[float, Any]]:
        """返回 (distance, id)，id 可能是 rowid 或外部向量库的 doc_id"""
        pass

# 实现示例：SQLiteVecProvider（当前）、PgVectorProvider、ChromaProvider、MilvusProvider（未来）
```

---

## 📅 迁移计划（分阶段）

### 0. 架构决策点（ADR）

以下 3 项已定，后续迁移按此执行：

1. **Schema 迁移方式** → **已选 B：Alembic**  
   - ~~选项 A：继续“运行时自检 + `ALTER TABLE`”~~  
   - **选项 B**：引入 **Alembic**，把 schema 变更收敛为“迁移脚本唯一入口”

2. **同步/异步 ORM 模式** → **已选 A：同步 SQLAlchemy**  
   - **选项 A**：先用同步 SQLAlchemy（`Session`）覆盖所有 Store  
   - ~~选项 B：直接上异步 SQLAlchemy（AsyncSession）~~

3. **KnowledgeBase 向量表结构策略** → **已选 B：统一单表**  
   - ~~选项 A：保留 per-KB 动态 vec 表（`embedding_chunk_{kb_id}`）~~  
   - **选项 B**：改为**统一单表**（加 `knowledge_base_id` 列 + 索引），更利于 ORM 与后续 PG/向量索引及 Chroma/Milvus

### 阶段 1：基础设施搭建（3-4 天）

#### 1.1 安装依赖与基础配置

**任务：**
- [x] 添加 `sqlalchemy>=2.0.0` 到 `requirements.txt`
- [x] 引入 **Alembic**（与 ADR 一致）：`alembic init`，配置 `env.py` 使用 `core.data.base` 的 engine/metadata
- [x] 创建 `core/data/__init__.py` 和 `core/data/base.py`
- [x] 定义数据库连接工厂（支持 SQLite，预留 PostgreSQL/MySQL）
- [x] 创建 `core/data/models/__init__.py` 目录结构

**代码结构：**
```
backend/core/data/
├── __init__.py
├── base.py              # Base, SessionLocal, get_db()
├── models/
│   ├── __init__.py
│   ├── model.py         # Model 表模型
│   ├── agent.py         # Agent 相关表模型
│   ├── session.py       # Session 表模型
│   ├── skill.py         # Skill 表模型
│   ├── knowledge.py     # Knowledge Base 表模型
│   ├── memory.py        # Memory 表模型
│   └── ...
└── vector_search.py     # 向量检索抽象层
```

**时间估算：** 1 天

#### 1.2 向量检索抽象层实现

**任务：**
- [x] 定义 `VectorSearchProvider` 抽象基类
- [x] 实现 `SQLiteVecProvider`（封装现有 `sqlite-vec` 逻辑）
- [x] 创建向量检索工厂 `get_vector_provider()`
- [x] 单元测试：SQLiteVecProvider 基本功能（`tests/test_vector_search.py`，3 个测试用例通过）

**时间估算：** 2-3 天

---

### 阶段 2：简单 Store 迁移（5-6 天）

**策略：** 先迁移无向量检索、逻辑简单的 Store，积累经验。

#### 2.1 SystemSettingsStore（1 天）

**任务：**
- [x] 定义 `SystemSetting` ORM 模型
- [x] 重构 `SystemSettingsStore` 使用 SQLAlchemy
- [x] 替换 `ON CONFLICT` → `insert().on_conflict_do_update()`
- [x] 单元测试：CRUD 操作（已通过）
- [x] 集成测试：与现有 API 兼容（已通过）

**复杂度：** ⭐（最简单）

#### 2.2 ModelRegistry（1.5 天）

**任务：**
- [x] 定义 `Model` 和 `ModelConfig` ORM 模型
- [x] 重构 `ModelRegistry` 使用 SQLAlchemy
- [x] 替换 `ON CONFLICT` → `insert().on_conflict_do_update()`
- [x] 替换 `sqlite3.Row` → ORM 对象
- [x] 迁移 `_row_to_descriptor()` → `_orm_to_descriptor()`（ORM 对象转 `ModelDescriptor`）
- [x] 单元测试 + 集成测试（已通过）

**复杂度：** ⭐⭐

#### 2.3 AgentRegistry（1.5 天）

**任务：**
- [x] 定义 `Agent` ORM 模型
- [x] 重构 `AgentRegistry` 使用 SQLAlchemy
- [x] JSON 字段处理（`definition_json`）
- [x] 保留 `_normalize_definition_data()` 兼容旧数据
- [x] 单元测试 + 集成测试（已通过）

**复杂度：** ⭐⭐

#### 2.4 SkillStore（1.5 天）

**任务：**
- [x] 定义 `Skill` ORM 模型
- [x] 重构 `SkillStore` 使用 SQLAlchemy
- [x] JSON 字段处理（`input_schema`, `definition`）
- [x] 替换 `sqlite3.Row` → ORM 对象（`_orm_to_skill()`）
- [x] 单元测试 + 集成测试（已通过）

**复杂度：** ⭐⭐

---

### 阶段 3：复杂 Store 迁移（8-10 天）

#### 3.1 AgentSessionStore（2 天）

**任务：**
- [x] 定义 `AgentSession` ORM 模型
- [x] JSON 字段处理（`messages_json`, `state_json`）
- [x] 替换 `PRAGMA table_info` → SQLAlchemy `inspect()` 或迁移脚本
- [x] 替换 `ON CONFLICT` → `insert().on_conflict_do_update()`
- [x] 迁移 `_row_to_session()` → ORM 对象转 `AgentSession`
- [x] 单元测试 + 集成测试

**复杂度：** ⭐⭐⭐

**难点：**
- `PRAGMA table_info` 用于动态字段检查（兼容性迁移），已改为：
  - 方案 B：一次性迁移脚本，后续不再需要动态检查（Alembic迁移脚本已创建表）

#### 3.2 AgentTraceStore（1.5 天）

**任务：**
- [x] 定义 `AgentTrace` ORM 模型
- [x] JSON 字段处理（`input_data`, `output_data`）
- [x] 替换 `PRAGMA table_info` → SQLAlchemy `inspect()`
- [x] 替换 `sqlite3.Row` → ORM 对象
- [x] 单元测试 + 集成测试

**复杂度：** ⭐⭐

---

### 阶段 4：向量检索 Store 迁移（10-12 天）

**策略：** 这是最复杂的部分，需要仔细设计向量检索抽象层。

#### 4.1 MemoryStore（3-4 天）

**任务：**
- [x] 定义 `MemoryItem` ORM 模型 ✓
- [x] 重构向量检索逻辑使用 `VectorSearchProvider` ✓
- [x] 替换 `sqlite-vec MATCH` → `SQLiteVecProvider.search()` ✓
- [x] 替换 `PRAGMA table_info` → SQLAlchemy `inspect()` ✓（已迁移，带降级路径）
- [x] 保留 Python cosine 降级路径 ✓
- [ ] 单元测试：向量检索功能 ⚠️（待补充）
- [ ] 集成测试：记忆存储与检索 ⚠️（待补充）

**复杂度：** ⭐⭐⭐⭐

**关键代码变更：**
```python
# 之前：直接使用 sqlite-vec
rows = conn.execute(
    "SELECT ... FROM memory_vec v WHERE v.embedding MATCH ? AND v.k = ?",
    (blob, user_id, limit)
).fetchall()

# 之后：使用抽象接口
provider = get_vector_provider()
results = provider.search(
    table_name="memory_vec",
    query_vector=qvec,
    limit=limit,
    filters={"user_id": user_id}
)
```

#### 4.2 HistoryStore（3-4 天）

**任务：**
- [x] 定义 `Session` 和 `Message` ORM 模型 ✓
- [x] 重构向量检索逻辑使用 `VectorSearchProvider` ✓
- [x] 替换 `sqlite-vec MATCH` → `SQLiteVecProvider.search()` ✓
- [x] JSON 字段处理（`content` 中的附件 base64）✓（已在 `to_dict()` 和 `list_messages()` 中处理）
- [ ] 单元测试 + 集成测试 ⚠️（待补充）

**复杂度：** ⭐⭐⭐⭐

#### 4.3 KnowledgeBaseStore（4-5 天）

**任务：**
- [x] 定义 `KnowledgeBase`, `Document`, `EmbeddingChunk` ORM 模型 ✓
- [x] 重构向量检索逻辑使用 `VectorSearchProvider` ✓
- [x] 替换 `sqlite-vec MATCH` → `SQLiteVecProvider.search()` ✓（统一表路径）
- [x] **统一单表**：`embedding_chunks` + `kb_chunks_vec`，`knowledge_base_id` 列与索引 ✓
- [x] 迁移 `_ensure_kb_vec_table()`：统一表路径使用 `_ensure_unified_vec_table()`，per-KB 表保留兼容 ✓
- [x] JSON 字段处理（`metadata_json`）— Alembic `d4e5f6a7b8c9`，按需读写 ✓
- [x] 单元测试：知识库 CRUD + 统一表检测 + 空 list_chunks/get_chunk_count ✓
- [x] 集成测试：RAG 检索返回结构（TestRAGFlowIntegration）✓

**复杂度：** ⭐⭐⭐⭐⭐（最复杂）

**难点：**
- 从 per-KB 动态表迁移到统一单表：已实现双路径（`_use_unified_chunks_table()` 为 True 时用统一表，否则回退 per-KB 表）；旧数据仍可在 per-KB 表中使用，新写入走统一表。
- 表结构/索引已由 Alembic 迁移 `a1b2c3d4e5f6_add_embedding_chunks_unified_table` 管理。

**部署与依赖说明：**
1. **Alembic 迁移**：使用统一表前必须在实际数据库上执行迁移，否则 `_use_unified_chunks_table()` 为 False（通过 `sqlite_master` 检查表是否存在）。命令：`conda run -n <env> bash -c "cd backend && alembic upgrade head"`。迁移会创建 `embedding_chunks` 表及可选列 `metadata_json`（`d4e5f6a7b8c9`）。
2. **sqlite-vec**：`requirements.txt` 中已包含 `sqlite-vec>=0.1.6`（Windows 除外）。若未安装，向量检索会不可用；生产环境建议安装以保证 RAG/向量检索功能正常。

---

### 阶段 5：清理与优化（长期计划 - 可选）

> **⚠️ 重要说明**：此阶段为**长期优化目标**，非紧急任务。当前实现已稳定运行，SQLite 直接连接在单进程应用中没有性能问题。

#### 5.1 代码清理（长期计划）

**当前状态（2025-02）：**

| 组件 | 状态 | 说明 |
|------|------|------|
| `import sqlite3` | ⚠️ 4个Store仍在使用 | `history_store.py`, `memory_store.py`, `knowledge_base_store.py`, `trace_store.py` |
| `_connect()` 方法 | ⚠️ 4个Store仍保留 | 返回 `sqlite3.Connection` |
| `sqlite3.Row` | ⚠️ 仍在使用 | 4个Store + backup模块 |

**任务（可选清理）：**
- [ ] 移除 Store 层的 `sqlite3` 直接导入（保留 `VectorSearchProvider` 内部使用）
- [ ] 统一数据库连接管理（所有 Store 使用 `get_db()` 或 `db_session()`）
- [ ] 移除 `_connect()` 方法（统一使用 SQLAlchemy Session）
- [ ] 代码审查：确保无遗留的 `sqlite3.Row` 使用

**工作量估算**：4-6人天（含测试）

**触发条件**：当需要切换到 PostgreSQL/MySQL 时再执行此清理

#### 5.2 文档更新

**任务：**
- [ ] 更新 `ARCHITECTURE.md`：数据层架构说明
- [ ] 更新 `DEVELOPMENT_STATUS.md`：ORM 迁移完成状态
- [ ] 创建 `core/data/README.md`：数据层使用指南

#### 5.3 性能测试

**任务：**
- [ ] 对比迁移前后性能（查询延迟、吞吐量）
- [ ] 向量检索性能测试（sqlite-vec 封装后是否有性能损失）
- [ ] 内存占用测试

---

## 📊 工作量总览

| 阶段 | Store/任务 | 工作量 | 累计 |
|------|-----------|--------|------|
| 阶段 1 | 基础设施 + 向量抽象 | 3-4 天 | 3-4 天 |
| 阶段 2 | SystemSettingsStore | 1 天 | 4-5 天 |
| 阶段 2 | ModelRegistry | 1.5 天 | 5.5-6.5 天 |
| 阶段 2 | AgentRegistry | 1.5 天 | 7-8 天 |
| 阶段 2 | SkillStore | 1.5 天 | 8.5-9.5 天 |
| 阶段 3 | AgentSessionStore | 2 天 | 10.5-11.5 天 |
| 阶段 3 | AgentTraceStore | 1.5 天 | 12-13 天 |
| 阶段 4 | MemoryStore | 3-4 天 | 15-17 天 |
| 阶段 4 | HistoryStore | 3-4 天 | 18-21 天 |
| 阶段 4 | KnowledgeBaseStore | 4-5 天 | 22-26 天 |
| 阶段 5 | 清理与优化 | 2-3 天 | 24-29 天 |

**总计：** 约 **3-4 周**（按每天 6-8 小时有效工作时间）  
**建议预留 buffer：** 阶段 4（向量检索）通常最容易超期，建议在整体计划上预留 **+30% buffer**（尤其当需要重构 KB 向量表结构/索引时）。

---

## 🎯 关键技术点

### 1. 数据库连接管理

**当前：**
```python
def _connect(self) -> sqlite3.Connection:
    conn = sqlite3.connect(str(self.db_path))
    conn.row_factory = sqlite3.Row
    return conn
```

**迁移后：**
```python
# core/data/base.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

engine = create_engine(
    f"sqlite:///{db_path}",
    connect_args={"check_same_thread": False},  # SQLite 需要
    echo=False  # 生产环境关闭 SQL 日志
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Session:
    """获取数据库会话（依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### 2. UPSERT 语法迁移

**当前（SQLite）：**
```python
conn.execute(
    "INSERT INTO models (...) VALUES (...) ON CONFLICT(id) DO UPDATE SET ..."
)
```

**迁移后（SQLAlchemy）：**
```python
from sqlalchemy.dialects.sqlite import insert

stmt = insert(Model).values(**data)
stmt = stmt.on_conflict_do_update(
    index_elements=['id'],
    set_=update_dict
)
db.execute(stmt)
```

**未来切换 PostgreSQL：**
```python
# 只需修改 dialect，语法自动适配
from sqlalchemy.dialects.postgresql import insert  # 自动使用 PostgreSQL 语法
```

### 3. 元数据查询迁移

**当前：**
```python
cols = [r[1] for r in conn.execute("PRAGMA table_info(agent_sessions)").fetchall()]
if "trace_id" not in cols:
    conn.execute("ALTER TABLE agent_sessions ADD COLUMN trace_id TEXT;")
```

**迁移后：**
```python
from sqlalchemy import inspect

inspector = inspect(engine)
columns = [col['name'] for col in inspector.get_columns('agent_sessions')]
if "trace_id" not in columns:
    # 使用 Alembic 迁移脚本，而不是动态 ALTER TABLE
    pass
```

**建议：** 一次性运行迁移脚本，后续不再需要动态字段检查。

### 4. JSON 字段处理

**当前：**
```python
messages_json = json.dumps([m.model_dump() for m in session.messages])
conn.execute("INSERT INTO agent_sessions (messages_json, ...) VALUES (?, ...)", (messages_json, ...))
```

**迁移后：**
```python
class AgentSession(Base):
    __tablename__ = "agent_sessions"
    # 建议在 SQLite 阶段保持与当前一致：Text + dumps/loads（最确定、最可控）
    # 后续切换到 PostgreSQL 时再升级为 JSONB 并利用原生 JSON 查询能力
    messages_json = Column(Text)
    state_json = Column(Text)
```

### 5. 向量检索抽象

**当前（KnowledgeBaseStore）：**
```python
# 直接使用 sqlite-vec
conn.enable_load_extension(True)
sqlite_vec.load(conn)
rows = conn.execute(
    f"SELECT ... FROM {table_name} c WHERE c.embedding MATCH ? AND c.k = ?",
    (json.dumps(query_embedding), limit)
).fetchall()
```

**迁移后（统一单表 + knowledge_base_id，与 ADR 一致）：**
```python
# 使用抽象接口；统一表名，用 filters 限定 KB
provider = get_vector_provider()
results = provider.search(
    table_name="embedding_chunks",
    query_vector=query_embedding,
    limit=limit,
    filters={"knowledge_base_id": kb_id}
)
```

**未来切换 PostgreSQL：**
```python
# 只需修改工厂函数返回 PgVectorProvider
def get_vector_provider() -> VectorSearchProvider:
    if settings.database_url.startswith("postgresql"):
        return PgVectorProvider()
    return SQLiteVecProvider()
```

---

## ⚠️ 风险评估

### 高风险项

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 向量检索性能下降 | 高 | 封装层保持最小开销，必要时直接调用底层 API |
| 数据迁移失败 | 高 | 分阶段迁移，每个 Store 迁移后立即测试 |
| API 接口破坏 | 中 | 保持 Store 类接口不变，仅内部实现变更 |
| 并发问题 | 中 | SQLAlchemy Session 线程安全，但需注意连接池配置 |

### 中风险项

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 学习曲线 | 中 | 团队熟悉 SQLAlchemy 需要时间 |
| 代码量增加 | 低 | ORM 模型定义会增加代码，但提升可维护性 |
| 依赖增加 | 低 | SQLAlchemy 是成熟库，风险低 |

---

## ✅ 验收标准

### 功能验收

- [ ] 所有 Store 的 CRUD 操作功能正常
- [ ] 向量检索功能正常（KnowledgeBaseStore, HistoryStore, MemoryStore）
- [ ] API 接口完全兼容（无需修改调用方代码）
- [ ] 数据完整性：迁移前后数据一致

### 性能验收

- [ ] 查询延迟：迁移后不超过迁移前的 110%
- [ ] 向量检索性能：封装后不超过直接调用的 105%
- [ ] 内存占用：无明显增加

### 代码质量验收

- [ ] 所有 Store 使用 SQLAlchemy ORM
- [ ] 无直接 `sqlite3` 调用（VectorSearchProvider 内部除外）
- [ ] 类型提示完整
- [ ] 单元测试覆盖率 ≥ 80%

---

## 📝 迁移检查清单

### 每个 Store 迁移时需检查

- [ ] ORM 模型定义完成
- [ ] `_connect()` 方法替换为 `get_db()`
- [ ] `ON CONFLICT` 替换为 SQLAlchemy `on_conflict_do_update()`
- [ ] `sqlite3.Row` 替换为 ORM 对象
- [ ] `PRAGMA table_info` 替换为 SQLAlchemy `inspect()` 或移除
- [ ] JSON 字段使用 SQLAlchemy `JSON` 类型
- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] API 接口兼容性测试通过

### 向量检索 Store 额外检查

- [ ] 使用 `VectorSearchProvider` 抽象接口
- [ ] `SQLiteVecProvider` 实现正确
- [ ] 向量检索功能测试通过
- [ ] 降级路径（Python cosine）测试通过

---

## 🔮 未来扩展

### 关系型库切换（PostgreSQL / MySQL）

**工作量：** 1-2 周（若已有 ORM 抽象）

**主要工作：**
1. 修改连接字符串与方言
2. 实现对应 `VectorSearchProvider`（如 `PgVectorProvider`、MySQL 向量 Provider）
3. 数据迁移脚本

### 向量后端切换为专用向量库（Chroma / Milvus 等）

**说明：** 向量存储不一定与主库绑定，未来可改为 Chroma、Milvus 等专用向量库。

**设计要点：**
- **Provider 接口保持统一**：`search()` 仍返回 `List[Tuple[float, id]]`，id 在 Chroma/Milvus 下为业务主键（如 chunk_id、memory_id），由 Store 用该 id 查 SQLite/ORM 取业务行。
- **语义差异**：Chroma/Milvus 无 rowid，需用「collection/namespace + 业务 id」做映射；Provider 内部负责「写入时落库 + 向量库」「检索时查向量库拿 id 列表」。
- **工作量**：实现 `ChromaProvider` / `MilvusProvider`（含 create_collection、upsert_by_id、search 返回 id），各 Store 调用方式不变，仅数据落在不同后端。

---

## 📚 参考资源

- [SQLAlchemy 2.0 文档](https://docs.sqlalchemy.org/en/20/)
- [SQLAlchemy 迁移指南](https://docs.sqlalchemy.org/en/20/changelog/migration_20.html)
- 向量后端（按需选型）：[pgvector](https://github.com/pgvector/pgvector)、[Chroma](https://docs.trychroma.com/)、[Milvus](https://milvus.io/docs)

---

## 📅 时间线建议

**建议按以下顺序执行：**

1. **第 1 周**：阶段 1（基础设施）+ 阶段 2（简单 Store）
2. **第 2 周**：阶段 3（复杂 Store）
3. **第 3 周**：阶段 4（向量检索 Store）
4. **第 4 周**：阶段 5（清理优化）+ 测试与文档

**里程碑：**
- ✅ 里程碑 1：基础设施完成，SystemSettingsStore 迁移完成
- ✅ 里程碑 2：所有非向量 Store 迁移完成
- ✅ 里程碑 3：向量检索抽象层完成
- ✅ 里程碑 4：所有 Store 迁移完成，代码清理完成

---

**文档版本：** v1.0  
**创建日期：** 2026-02-02  
**最后更新：** 2026-02-02
