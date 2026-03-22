# AGENTS.md — Inference Gateway & Plugin Governance

> 本文件是本项目中 **优先级最高的行为与架构约束文档之一**。
>
> 所有 Agent / Plugin / 推理适配层的设计与实现，必须遵循本规范。

---

## 1. 项目与技术栈对齐说明

本项目是一个 **Web 形态的本地 AI 推理平台**，整体架构为：

* **前端（UI 层）**：Vue 3 + Vite + Tailwind CSS + shadcn-vue
* **后端（核心中枢）**：Python + FastAPI
* **角色定位**：

  * Web UI 只是“控制台”
  * FastAPI 推理网关是“大脑”
  * Agent / Plugin 是“能力模块”

* 后端的程序，都要在虚拟环境 conda 中运行。

本文件定义的 **Agent**，并不等同于“自主智能体”，而是指：

* 推理网关中的系统模块
* 推理后端的统一封装代理
* 以插件形式加载的能力增强模块

---

## 2. 核心设计原则（Core Principles）

所有 Agent / Plugin **必须遵循** 以下原则：

### 2.1 User-in-Control（用户始终掌控）

* Agent 不得擅自改变用户意图
* 默认不启用任何“自动决策”或“隐式代理”行为

---

### 2.2 Gateway-Centric（以推理网关为中心）

* 所有模型调用必须经过 FastAPI 推理网关
* 前端不得直连模型、推理引擎或工具

---

### 2.3 Determinism over Magic（确定性优于魔法）

* 禁止隐藏 Prompt
* 禁止隐式参数注入
* 行为必须可预测、可复现

---

### 2.4 Plugin-first（插件优先）

* 新能力优先设计为插件
* 插件必须可独立启停、替换、升级

---

### 2.5 Local-first & Privacy-first（本地与隐私优先）

* 默认假设系统运行在 **无外网环境**
* 不得未经授权进行任何数据外传

---

## 3. Agent 分类（Agent Taxonomy）

### 3.1 Gateway System Agents（系统代理）

**位置**：FastAPI 推理网关核心层

职责：

* 请求规范化（Request Normalization）
* 模型路由与选择
* 流式响应协调（SSE / Streaming）
* 错误捕获与恢复

约束：

* ❌ 不得包含业务逻辑
* ❌ 不得访问外部网络或文件系统

---

### 3.2 Model Agents（模型代理 / 推理适配层）

对不同推理后端的统一封装。

示例：

* OpenAI / API Agent
* Ollama Agent
* vLLM Agent
* llama.cpp Agent

职责：

* 将统一请求转换为后端调用
* 统一流式输出格式
* 明确暴露模型能力边界

约束：

* ❌ 不得修改用户输入语义
* ❌ 不得注入隐藏 Prompt 或系统提示

---

### 3.3 Capability Agents（能力插件）

以 **插件形式** 挂载在推理流程中的增强模块。

示例：

* RAG Agent（本地知识库）
* Tool Calling Agent
* Memory / History Agent
* Workflow / Agent Agent

职责：

* 明确声明权限与依赖
* 对输入输出负责

约束：

* 必须可被禁用
* 必须可观测、可审计

---

## 4. Agent / Plugin 生命周期

所有 Agent / Plugin 必须遵循以下生命周期：

```
load → initialize → ready → execute → teardown
```

规则：

* Agent 应尽量无状态
* 必须支持优雅失败（graceful failure）

---

## 5. Agent / Plugin 接口规范

每个 Agent / Plugin **必须声明**：

* name（名称）
* type（system / model / capability）
* version（版本）
* stage（pre / post / tool / router）
* input schema
* output schema
* required permissions

**可选声明**：

* configuration schema
* 前端 UI Hint（供 Web UI 自动渲染配置面板）

---

## 6. 权限与安全（Security & Permissions）

* 默认禁止网络访问
* 文件系统访问必须限定目录
* 插件权限需显式声明
* 所有执行过程必须可记录、可审计

---

## 7. 数据层与持久化（Data & Persistence）

后端已统一为 **ORM**（关系型）与 **VectorSearchProvider**（向量检索）两套抽象。凡有数据库或向量数据库需求的新功能，必须基于二者实现，不得绕过。

* **关系型持久化**：使用项目 **ORM**（如 `core/data` 层、SQLAlchemy 等）。禁止在业务中直接写裸 SQL、直接操作 DB 连接或自建表结构。
* **向量检索**：使用 **VectorSearchProvider** 抽象。禁止在业务中直连具体向量库或自实现向量读写。
* **适用范围**：Agent、Plugin、知识库、会话、Trace、配置等所有需要落库或向量检索的模块。

---

## 8. 可观测性（Observability）

Agent SHOULD 提供：

* 执行耗时
* Token / 资源消耗
* 错误与异常信息

用于：

* Debug
* 性能分析
* 成本评估

---

## 9. 版本与兼容性（Versioning）

* Agent 必须声明兼容的推理网关版本
* 不兼容变更必须升级主版本号

---

## 10. 扩展规范（Extension Policy）

新增 Agent / Plugin 时：

1. 明确分类（System / Model / Capability）
2. 明确权限声明
3. 避免与核心网关强耦合
4. 优先插件化
5. 补充文档与示例
6. 若有持久化或向量检索需求，遵循 [§7 数据层与持久化](#7-数据层与持久化data--persistence)。

---

## 11. 设计哲学（Philosophy）

> FastAPI 推理网关是大脑
>
> Agent / Plugin 是能力模块
>
> Web UI 只是控制台
>
> 用户永远拥有最终控制权

## 12. 文档规范
* 不要在完成功能开发后 **主动添加或总结任何文档**
* 仅在明确指示时才允许修改 `README.md / AGENTS.md`
* 不得擅自“补充说明”或“整理文档”

---

End of AGENTS.md
