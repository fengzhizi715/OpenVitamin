# Memory Module — AGENTS.md

## 1. 模块定位（Module Purpose）

Memory 模块负责 **长期记忆（Long-term Memory）与中期记忆（Summarized Memory）** 的管理，是推理网关中用于“让模型逐渐理解用户”的核心基础设施。

本模块 **不直接参与推理生成**，而是通过：
- 记忆提取（Extraction）
- 记忆存储（Storage）
- 记忆检索（Retrieval）
- 记忆注入（Injection）

为模型提供 **稳定、可控、可解释的背景信息**。

---

## 2. 设计原则（Design Principles）

### 2.1 记忆不等于上下文

- ❌ 不把所有历史对话都当作记忆
- ❌ 不把完整对话直接向量化
- ✅ 记忆必须是 **被提炼过的、长期有效的信息**

> Memory = Extracted Facts / Preferences / Background

---

### 2.2 人类可读优先

- 所有记忆条目必须包含 **人类可读的文本内容**
- 向量（embedding）只是索引手段，不是唯一数据

> 如果人看不懂这条记忆，它就不应该存在。

---

### 2.3 可控、可遗忘

- 记忆必须支持：
  - 删除
  - 合并
  - 权重衰减
- 系统不得假装“永不遗忘”

---

### 2.4 与模型无关

- Memory 模块 **不绑定具体 LLM**
- 可使用任意 embedding provider
- 可独立替换 Vector Store 实现

---

## 3. 模块职责边界（Responsibilities）

### Memory 模块负责：

- 定义 MemoryItem 数据结构
- 决定什么信息可以成为长期记忆
- 存储与检索记忆
- 将检索结果注入到推理上下文（system prompt）

### Memory 模块不负责：

- 聊天历史管理（由 ConversationManager 负责）
- 推理生成（由 ModelAgent 负责）
- Tool 调用逻辑
- UI 展示细节

---

## 4. 核心概念（Core Concepts）

### 4.1 MemoryItem

MemoryItem 是最小记忆单元，必须满足：

- 可读
- 可分类
- 可检索

推荐字段：

- `id`
- `user_id`
- `type`（preference / profile / project / fact）
- `content`（简短、客观、陈述句）
- `embedding`
- `confidence`
- `created_at`
- `last_used_at`

---

### 4.2 Memory Types

| 类型 | 含义 | 示例 |
|---|---|---|
| preference | 用户偏好 | 用户更喜欢中文回答 |
| profile | 用户背景 | 用户是软件工程师 |
| project | 长期项目 | 用户正在开发 AI 推理平台 |
| fact | 稳定事实 | 用户使用 macOS Apple Silicon |

---

## 5. Memory 生命周期（Lifecycle）

```text
对话完成
   ↓
MemoryExtractorAgent
   ↓
生成 MemoryItem（可选）
   ↓
Embedding
   ↓
MemoryStore.add()
```

---

## 6. MemoryExtractorAgent 规范

### 6.1 角色定位

MemoryExtractorAgent 是一种 **后台 Agent**：

- 不面向用户
- 不直接输出给前端
- 仅在对话完成后运行

---

### 6.2 输入

- 当前轮 user + assistant 对话
- 可选：最近几轮摘要

---

### 6.3 输出

- JSON 数组
- 每一项为候选 MemoryItem
- 允许返回空数组

---

### 6.4 约束

- 不得编造事实
- 不得重复已有记忆
- 内容必须简短、稳定、长期有效

---

## 7. MemoryStore 规范

### 7.1 接口抽象

MemoryStore 必须实现：

- `add(memory_item)`
- `search(query_embedding, k)`
- `list(user_id)`
- `delete(id)`

---

### 7.2 推荐实现

- SQLite + sqlite-vss（MVP / 本地优先）
- Chroma（可选）
- Qdrant（未来）

---

## 8. Memory Injection 规范

### 8.1 注入位置

- 记忆只允许注入到 **system prompt**
- 不得伪装为 assistant 或 user 消息

---

### 8.2 推荐格式

```text
以下是与当前用户相关的长期背景信息（供参考）：
- ...
- ...
```

---

### 8.3 注入约束

- 必须显式声明“供参考”
- 不暗示模型具有真实记忆能力
- 注入条目数量应受限（通常 ≤ 5 条）

---

## 9. 安全与隐私原则

- Memory 模块默认本地存储
- 不得未经用户许可上传记忆
- 必须支持用户清空全部记忆

---

## 10. 演进路线（Roadmap）

### Phase 1（当前）
- 单用户
- SQLite + vss
- 手动调试

### Phase 2
- 记忆合并 / 压缩
- confidence 衰减
- UI 可视化

### Phase 3
- 多用户隔离
- 权限控制
- 可迁移存储

---

## 11. 成功标准

- 记忆内容可解释、可追溯
- 不污染上下文、不导致 token 爆炸
- 对模型行为产生稳定、正向影响

---

> 本模块遵循项目根目录 `/AGENTS.md` 中定义的所有通用 Agent 行为规范。

