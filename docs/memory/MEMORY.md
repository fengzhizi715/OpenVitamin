# Memory 模块说明（Long-term Memory）

> 本文档记录当前项目中 `backend/core/memory/` 的 **功能、设计与实现**。
> 目标是：**可控、可解释、可审计、可遗忘**，并为后续能力（更强 embedding / sqlite-vss / UI）留好演进空间。

---

## 1. 模块定位

Memory 模块负责长期记忆的：

- **提取（Extraction）**：从一轮对话中提取长期有效的信息
- **存储（Storage）**：本地 SQLite 持久化（本地优先）
- **检索（Retrieval）**：recent / keyword / vector（sqlite-vec 优先，失败自动降级）
- **注入（Injection）**：以 **system message** 的形式注入到上下文（明确“供参考”）
- **管理（Management）**：提供 list/delete/clear API，支持可遗忘

该模块 **不负责**：
- 聊天历史管理（由 `ConversationManager` 负责）
- 推理生成（由 `ModelAgent` 负责）
- Tool/Workflow 逻辑
- UI 展示细节

---

## 2. 运行时整体流程

### 2.1 对话请求进入（Injection）

在 `/v1/chat/completions` 请求进入模型前：

- 从 Header 读取 `X-User-Id`（缺省为 `default`）
- 若开启 `enable_long_term_memory`：
  - `MemoryInjector.inject(messages, user_id=...)`
  - 仅注入 `status=active` 的记忆，最多 5 条
  - 注入内容以 system message 的形式插入，便于审计
  - 注入后会更新注入条目的 `last_used_at`

### 2.2 一轮对话完成（Extraction + Store）

在模型完成生成后（非流式与流式都覆盖）：

- 收集本轮 `user_text` 与 `assistant_text`
- 若开启 `memory_extractor_enabled`：
  - `MemoryExtractor.extract_and_store(user_id, model_id=req.model, ...)`
  - **Extractor 跟随当前聊天模型**（使用同一 `model_id`）
  - 解析 LLM 输出 JSON → `MemoryCandidate[]`
  - 交给 `MemoryStore.add_candidates(...)` 落库

---

## 3. 数据模型（MemoryItem / MemoryCandidate）

### 3.1 MemoryCandidate（Extractor 输出）

Extractor 期望输出 JSON 数组，每项结构：

```json
{
  "type": "preference | profile | project | fact",
  "key": "preference.language",
  "value": "zh",
  "content": "用户偏好中文回答",
  "confidence": 0.8
}
```

说明：
- `content` 可选（缺省会自动生成可读陈述句）
- `confidence` 可选（缺省使用系统默认值）

### 3.2 MemoryItem（落库条目）

主要字段：
- `id`：uuid
- `user_id`：来自 `X-User-Id`
- `type`：`preference/profile/project/fact`
- `key/value`：结构化字段（用于确定性合并/冲突）
- `content`：人类可读陈述句（必须可读）
- `confidence`：0~1（用于排序/衰减）
- `created_at/updated_at/last_used_at`
- `status`：`active | deprecated`
- `embedding`：向量（当前存 json；sqlite-vss 可用则同时入 vss 表）
- `meta/source`：可选元信息（如 completion_id、模型等）

---

## 4. Key Schema（规范 key + 值标准化）

实现文件：`backend/core/memory/key_schema.py`

### 4.1 为什么需要 Key Schema

目标是让冲突/合并**不依赖启发式**（如“喜欢/不喜欢”词匹配），而是基于：

> 同一 `user_id + type + key` 的值变化 → 确定性冲突处理

### 4.2 白名单 key（可扩展）

当前内置示例：
- `preference.language`（ISO 639-1：`zh/en/...`）
- `preference.timezone`（IANA TZ：`Asia/Shanghai`）
- `profile.role`（短字符串）
- `project.name`（短字符串）

### 4.3 值标准化/校验

- `preference.language`：
  - 允许 `zh` / `zh-cn` / `en-us` 等
  - 统一标准化为前两位：`zh` / `en`
- `preference.timezone`：
  - 使用 `zoneinfo.ZoneInfo` 校验 IANA TZ
  - 非法值直接拒绝写入

### 4.4 Enforcement 策略

相关配置：
- `memory_key_schema_enforced`（默认 True）
- `memory_key_schema_allow_unlisted`（默认 False）

默认行为（更安全更可控）：
- key 不在白名单 → 丢弃
- key 在白名单但 value 校验失败 → 丢弃

---

## 5. 存储实现（SQLite + sqlite-vec）

实现文件：`backend/core/memory/memory_store.py`

### 5.1 表结构

主表：`memory_items`
- `user_id/type/key/value/content/confidence/status/...`

向量表（可选）：`memory_vec`
- 启用 `memory_vector_enabled=True` 时尝试加载 `sqlite_vec`
- 成功则创建 `vec0(embedding float[dim])` 虚表并写入/检索
- 失败则自动降级（不会影响主流程）

### 5.2 自动迁移

启动时会执行：
- `PRAGMA table_info(memory_items)` 检测缺列
- `ALTER TABLE` 自动补齐列（不依赖外部迁移框架）

---

## 6. 冲突 / 合并 / 衰减（确定性优先）

### 6.1 确定性冲突/合并（基于 key/value）

写入时（`add_candidates`）：
- 若存在 `user_id + type + key` 的 active 记录：
  - value 相同 → **不插入新记录**，提升旧记录 `confidence/updated_at`
  - value 不同 → 旧记录 `status=deprecated`，插入新记录 `status=active`

### 6.2 非结构化兜底（向量相似度）

当没有 key 或 key 不可用时：
- 仍可走“向量相似度” merge/conflict（用于兼容旧格式与非结构化记忆）
- 阈值由配置控制：
  - `memory_merge_similarity_threshold`
  - `memory_conflict_similarity_threshold`

### 6.3 衰减策略（Injection 时排序）

注入前，对候选记忆计算评分：

score = confidence × decay(age) × type_weight

- age：优先 `last_used_at`，否则 `created_at`
- decay：半衰期 `memory_decay_half_life_days`（默认 30 天）
- type_weight：`preference > project > profile > fact`

---

## 7. Memory API（可控 / 可遗忘）

实现文件：`backend/api/memory.py`

统一约定：
- `X-User-Id`：用户隔离（无则 `default`）

接口：
- `GET /api/memory?limit=50&include_deprecated=false`
- `DELETE /api/memory/{memory_id}`
- `POST /api/memory/clear`

返回结构：
- list：`{ object: "list", data: MemoryItem[] }`

---

## 8. 配置开关（settings.py）

核心开关：
- `enable_long_term_memory`：是否注入记忆
- `memory_extractor_enabled`：是否提取并落库

检索相关：
- `memory_inject_mode`: `recent | keyword | vector`
- `memory_vector_enabled`: 是否尝试启用 sqlite-vec
- `memory_embedding_dim`: embedding 维度（默认 256）

策略相关：
- `memory_default_confidence`
- `memory_decay_half_life_days`
- `memory_merge_enabled / memory_merge_similarity_threshold`
- `memory_conflict_enabled / memory_conflict_similarity_threshold`
- `memory_key_schema_enforced / memory_key_schema_allow_unlisted`

---

## 9. 后续优化建议（不在本文实现范围内）

- 增强 Key Schema（扩充 key 列表 + 更严格 value 类型）
- 为 Memory 引入 UI 管理界面（已在 `project_plan.md` 记录 ToDo）
- 将提取任务从 `create_task` 演进为可控队列/worker（避免高并发丢任务/堆积）
- 使用更强、更语义化的 embedding（本地优先），并稳定接入 sqlite-vec 检索语法

