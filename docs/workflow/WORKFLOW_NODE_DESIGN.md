# Workflow 节点设计文档

> 本文档描述 Workflow Editor 中各节点类型的能力、配置项与数据流约定，供评审与后续开发参考。不涉及具体实现代码。

---

## 1. 文档目的与范围

- **目的**：统一「节点语义、配置结构、与上下游连线」的设计，便于前端画布、后端执行引擎与持久化对齐。
- **范围**：节点类型定义、配置 Schema、输入/输出约定、与现有系统（Agent、Skill、Knowledge Base）的对接方式。
- **非范围**：具体 UI 交互、API 路径、数据库表结构（可另文档）。

---

## 2. 设计原则（与 AGENTS.md 对齐）

- **User-in-Control**：节点行为可配置、可预测，不隐式改写用户意图。
- **Gateway-Centric**：LLM/Agent 等推理均经推理网关，不直连模型。
- **确定性优于魔法**：变量与条件显式声明，避免隐藏 Prompt 或隐式注入。
- **本地与隐私优先**：默认无外网依赖，数据外传需显式配置（如 Webhook、API）。

---

## 3. 节点总览

| 分类     | 节点类型        | 说明                         |
|----------|-----------------|------------------------------|
| **Input**  | Input           | 多种输入来源（用户/文件/API/定时） |
| **Prompt** | Prompt Template | 模板 + 变量占位               |
| **AI**     | LLM             | 大模型调用，参数可配           |
| **AI**     | Agent           | 调用现有 Agent 系统           |
| **Tool**   | Tool/Skill      | 调用已有 Tool/Skill（file/web/code 等） |
| **Knowledge** | Knowledge    | 连接知识库，执行 RAG           |
| **Logic**  | Condition       | 分支条件                      |
| **Logic**  | Loop            | 循环（如 Self Refine）         |
| **Output** | Output          | 多种输出形态（Chat/File/Webhook/API） |

说明：**System Prompt** 可合并进 Prompt Template（通过配置区分 role），或单独作为节点类型，由实现阶段决定。

---

## 4. 节点详细设计

### 4.1 Input Node（输入节点）

**职责**：定义 Workflow 的入口数据来源。

**子类型 / 模式**（通过 `config.mode` 或 `config.input_type` 区分）：

| 模式               | 说明                     | 典型配置项 |
|--------------------|--------------------------|------------|
| **User Input**     | 对话、表单等用户输入     | 可选：变量名、是否必填、提示文案 |
| **File Input**     | 用户上传文件             | 接受格式（如 pdf/txt）、单/多文件、大小限制 |
| **API Input**      | 外部系统调用本 Workflow 的入参 | 与 API 路由约定一致（如 body schema） |
| **Schedule Trigger** | 定时/周期触发           | cron 或间隔、时区、可选 payload |

**输出约定**：

- 输出一个结构化对象，供下游引用。例如：`user_message`、`files`、`trigger_time`、`payload` 等 key，由模式决定。
- 下游节点通过变量引用，如 `{{input.user_message}}`。

**与现有系统**：无直接复用；执行层需在运行时根据模式注入或接收数据。

**待定**：Schedule 的重试、幂等、超时策略是否在本节点配置，还是全局 Workflow 配置。

---

### 4.2 Prompt Node（Prompt Template）

**职责**：定义一段带变量的文本模板，用于生成发给 LLM/Agent 的提示内容。

**示例**：

```text
Write a news summary about:

{{topic}}
```

**配置项**：

| 配置项       | 类型   | 说明 |
|--------------|--------|------|
| template     | string | 模板正文，变量用 `{{name}}` 表示 |
| variables    | array  | 可选：变量名列表及默认值/描述，便于校验与 UI 展示 |
| role         | string | 可选：`system` / `user` / `assistant`，用于多段对话时区分 |

**输入**：变量可从上游节点输出或全局 Variable 注入；执行时做占位符替换。

**输出**：渲染后的字符串（或带 role 的消息对象），供下游 LLM/Agent 节点消费。

**与现有系统**：与现有「Prompt Template」节点一致；可扩展为支持多段模板（如 system + user）。

---

### 4.3 LLM Node（大模型节点）

**职责**：调用推理网关完成一次 LLM/VLM 生成。

**配置项**：

| 配置项       | 类型   | 说明 |
|--------------|--------|------|
| model        | string | **运行时模型别名（推荐）**，例如 `local:qwen3-8b`（经 Inference Gateway 路由） |
| model_id     | string | **编辑器兼容字段**：模型 ID（本地或云端）。最终需映射到 `model` |
| model_display_name | string | 展示用名称 |
| temperature  | number | 默认 0.7 |
| top_p        | number | 默认 0.9 |
| max_tokens   | number | 默认 2048 |

**输入**：通常为上游 Prompt 节点的输出（或拼接多段内容）。

**输出**：统一结构（建议）：`{ text: string, usage?: {...}, latency_ms?: number, finish_reason?: string, metadata?: {...} }`。

**与现有系统**：经 Inference Gateway，与现有 LLM 节点一致。

---

### 4.4 Agent Node（智能体节点）

**职责**：调用平台已有 Agent，复用其配置（模型、System Prompt、Tools/Skills）。

**状态说明**：

- 该节点属于 **设计目标中的节点类型**
- 当前文档将其保留为一等节点语义，但 **运行时映射仍需明确落地**
- 在实现完成前，不应将其视为“已可执行”的稳定节点类型

**配置项**：

| 配置项       | 类型   | 说明 |
|--------------|--------|------|
| agent_id     | string | Agent 唯一标识 |
| agent_display_name | string | 展示用名称 |
| input_mapping | object | 可选：将上游输出映射到 Agent 的 input schema |

**输入**：用户消息或上游 Prompt/LLM 输出；可由 input_mapping 指定如何填入 Agent 的输入。

**输出**：Agent 的回复（及可选 tool_calls 等），结构可与现有 Agent 执行结果一致。

**与现有系统**：

- 目标是复用现有 Agent 执行层，不重复实现推理与工具调用
- 但当前需要先明确运行时方案，二选一：
  - **专用 handler**：`agent` 节点由 WorkflowRuntime/Execution Kernel 显式分发
  - **Tool 封装**：将 Agent 调用封装为统一 Tool，再由 Tool 节点执行

**约束**：

- 在运行时映射未最终确定前，前端不应默认把该节点当作已上线节点提供给用户执行
- 文档中的 `input_mapping` 仅作为目标设计，不代表当前 runtime 已支持

**整合建议**（如何接入当前 Workflow 体系）：

1. **先定义稳定契约（避免前后端反复改）**
   - 节点类型保持 `type: "agent"` 不变。
   - 最小配置契约：`agent_id`（必填）、`agent_display_name`（可选）、`input_mapping`（可选）。
   - 输出契约建议统一为：`{ text, tool_calls?, artifacts?, usage?, metadata? }`，便于下游 LLM/Tool/Output 节点消费。

2. **分阶段上线（推荐）**
   - **阶段 A：设计可用，执行受控**
     - 编辑器允许配置 Agent Node（可拖拽、可保存、可版本化）。
     - 运行前校验明确报错：当运行时未开启 Agent 能力时，拒绝执行并返回可读错误（而非静默降级）。
     - 建议增加能力开关：`agent_node_enabled`（全局或租户级），默认关闭。
   - **阶段 B：运行时可执行**
     - 二选一实现路径：
       - **专用 handler**：Workflow Runtime 显式支持 Agent Node；
       - **Tool 封装**：将 Agent 调用封装为统一 Tool，并由 Tool 节点执行。
     - 无论选哪条路，UI/Definition 契约不变（对用户透明）。

3. **解耦要求（关键）**
   - Workflow 层只关心 `agent_id + input/output contract`，不耦合具体 Agent 内部提示词、技能编排细节。
   - Runtime 通过统一 Gateway/Agent 调用入口执行，禁止在 Workflow 里复制一套 Agent 执行逻辑。
   - 失败语义统一：Agent 调用失败应进入节点失败态，并携带标准错误结构（`code/message/details`）。

4. **验收标准（建议）**
   - 保存/发布：含 Agent Node 的 DAG 能正常入库、版本化与 diff。
   - 执行（开关关闭）：返回明确“能力未开启”错误。
   - 执行（开关开启）：可完成一次端到端调用，且节点 I/O、耗时、错误在 Execution 详情页可观测。

---

### 4.5 Skill Node（技能节点）

**职责**：调用平台已注册的 Tool/Skill，如 `builtin_file.read`、`builtin_web.search`、`builtin_shell.run` 等。

**配置项**：

| 配置项       | 类型   | 说明 |
|--------------|--------|------|
| tool_name / tool_id | string | Tool 唯一标识（推荐统一称 `tool_name`） |
| tool_display_name | string | 展示用名称 |
| inputs       | object | 该 Tool 的入参，值可引用上游变量，如 `path: "{{input.file_path}}"` |

**输入**：通过 `inputs` 从上游 Output 或 Variable 拉取。

**输出**：该 Skill 的返回结果，供下游引用。

**与现有系统**：与现有 Skill 注册表、执行层对接。

---

### 4.6 Knowledge Node（知识库节点）

**职责**：连接指定知识库，执行 RAG（检索 + 将结果注入上下文）。

**配置项**：

| 配置项       | 类型   | 说明 |
|--------------|--------|------|
| knowledge_base_id | string | 知识库 ID |
| knowledge_base_display_name | string | 展示用名称 |
| top_k        | number | 检索条数，如 5 |
| score_threshold | number | 可选：相似度阈值 |
| query_source | string | 可选：检索 query 来自哪一上游节点输出（如 `{{llm_output.query}}` 或固定变量） |

**输入**：query 来源由 `query_source` 或连线约定；可选地接收「当前对话上下文」用于混合检索。

**输出**：检索到的片段列表（或拼接后的上下文字符串），供下游 LLM/Prompt 使用。

**与现有系统**：与现有 Knowledge Base、Embedding、检索 API 对接；若平台已有 RAG 服务，可封装为单节点。

**待定**：是否支持「仅检索不注入」或「多库合并」等模式，可在同一节点用 `mode` 区分。

---

### 4.7 Condition Node（条件节点）

**职责**：根据条件表达式或字段比较，将执行流导向不同分支。

**示例**：`if sentiment == negative` → 分支 A；否则分支 B。

**配置项**：

| 配置项       | 类型   | 说明 |
|--------------|--------|------|
| condition_type | string | 如 `expression` / `field_compare` |
| left         | string | 左侧：上游输出字段或变量，如 `sentiment` |
| operator     | string | 如 `==`、`!=`、`>`、`in` 等 |
| right        | string/number/array | 比较值或变量 |
| branches     | array  | 可选：多分支时每支的 label 与条件片段，便于画布展示 |

**输入**：上游节点输出或全局变量；条件基于这些数据求值。

**输出**：不产生数据，仅决定从哪条边（outgoing edge）进入下游。每条边可标注为对应分支（如 `true`/`false` 或 `negative`/`neutral`/`positive`）。

**安全与可维护性**：建议限制为「字段 + 运算符 + 值」或白名单内的简单表达式，避免任意代码执行。

**表达式语法约定（建议）**：
- **模板渲染**：`{{node_id.field}}`（仅用于字符串模板）
- **条件表达式**：`${input.foo} > 0 and ${global.bar} == "x"`（仅用于条件求值）

当前执行上下文建议统一以下根变量：

- `${global.key}`：引用 Workflow/Execution 的全局上下文
- `${nodes.node_id.output.key}`：引用上游节点输出
- `${input.key}`：引用当前节点输入

说明：

- 不建议在文档中使用 `${context.key}` 或 `${node.some_output}` 作为正式语法
- 若未来要支持别名，应明确标注为“语法糖”，并给出规范映射关系

**边触发语义（建议与执行内核对齐）**：
- `success`：上游节点成功
- `failure`：上游节点失败
- `always`：无论成功失败都触发
- `condition_true/condition_false`：Condition 节点输出的 `condition_result` 决定分支

---

### 4.8 Loop Node（循环节点）

**职责**：在满足条件或固定次数内重复执行子 DAG（Loop 内部节点），如 Self Refine。

**配置项**：

| 配置项       | 类型   | 说明 |
|--------------|--------|------|
| loop_type    | string | `fixed`（固定次数）/ `condition`（条件终止） |
| max_iterations | number | 最大轮数，防止死循环 |
| timeout_seconds | number | 循环总超时，防止长时间占用执行资源 |
| condition_expression | string | 当 `loop_type=condition` 时使用的终止表达式，使用 `${...}` 语法 |
| audit_log    | boolean | 是否记录循环审计日志，默认建议开启 |
| output_key   | string | 可选：当前轮结果写入的逻辑 key，供下一轮或下游引用 |

**输入**：首轮由上游提供；后续轮由上一轮 Loop 内部输出（通过 output_key）注入。

**输出**：最后一轮的结果，或达到 max_iterations 时的结果。

**与 Condition 的配合**：Loop 内部可包含 Condition 节点，实现「每轮判断是否达标再退出」。

**待定**：是否支持「并行循环」（对列表逐项执行）与「汇聚策略」，可后续扩展。

**实现对齐说明**：

- Loop 在运行时建议统一映射到 `loop_config.*`
- 文档不再使用 `condition: object` 作为主配置结构，避免与当前执行内核的 `condition_expression` 冲突
- 若后续希望支持结构化条件编辑器，可在前端将结构化条件编译为 `condition_expression`

---

### 4.9 Output Node（输出节点）

**职责**：定义 Workflow 的出口形态，将最终结果写入会话、文件或推送到外部。

**子类型 / 模式**（通过 `config.mode` 或 `config.output_type` 区分）：

| 模式       | 说明                     | 典型配置项 |
|------------|--------------------------|------------|
| **Chat**   | 结果写回当前会话         | 可选：消息 role、是否追加 |
| **File**   | 写入本地或存储          | 路径规则、文件名模板、覆盖策略 |
| **Webhook**| 以 HTTP 回调推送         | URL、方法、Headers、鉴权 |
| **API**    | 作为本次执行的响应体返回 | 与触发本 Workflow 的 API 约定一致 |

**输入**：来自上游节点（如 LLM/Agent 的最后一条输出）；可配置「取哪个上游的哪个字段」。

**多 Output**：若允许多个 Output 节点（如同时写 Chat + File），需约定执行顺序或「主输出」定义，避免歧义。

---

## 5. 数据流与变量约定

- **变量来源**：Input 节点输出、各节点执行结果（按节点 id 或配置的 output_key 命名）。
- **引用方式**：
  - **模板渲染（Prompt/Output 等字符串字段）**：`{{node_id.field}}` / `{{variable.name}}`
  - **条件求值（Condition/Loop 的 expression）**：`${input.key}` / `${global.key}` / `${nodes.node_id.output.key}`
- **执行顺序**：由 DAG 拓扑决定；Condition 与 Loop 按边与分支语义执行。

---

## 5.1 Runtime Contract（节点执行契约，建议）

为保证前端/后端/Trace 一致性，建议所有节点执行遵循统一的最小契约：

- **输入**：`input_data: object`
  - 由上游节点输出、全局变量、以及节点 config 中的 inputs 渲染/解析后组成
  - 不允许隐式注入（除非在 Workflow/Execution 的显式 global_context 中声明）
- **输出**：`output_data: object`
  - 节点输出必须是 JSON 可序列化结构
  - LLM/Agent 这类生成节点建议统一返回 `{ text, usage, latency_ms, finish_reason, metadata }`
- **失败语义**：
  - 节点失败时，必须返回可观测错误：`error_message` / `error_type`（或结构化 error）
  - DAG 是否继续由边触发策略决定（例如 `failure/always` 边）
- **超时/重试/缓存**（建议落到 NodeDefinition 层）：
  - `timeout_seconds`
  - `retry_policy`（最大重试、退避）
  - `cacheable`（决定是否允许 node-level cache）

---

## 5.2 Permissions & Workspace（权限与工作目录，建议）

为符合 **User-in-Control** 与 **Local-first**：

- 默认权限为 **deny-all**
- 允许的权限来源必须显式：
  - Workflow 执行请求的 `global_context.permissions`
  - 或 Workflow/Version 的显式配置（仍需最终由用户确认/授权）
- 文件类工具必须在 `workspace` 之下运行：
  - `global_context.workspace` 明确指定工作目录
  - 不允许在节点里隐式提升目录访问范围
- 外网/回调类能力（Webhook/HTTP）必须显式开关并记录审计信息

---

## 6. 与现有节点库的对应关系

| 本文档节点     | 当前编辑器类型     | 说明 |
|----------------|--------------------|------|
| Input          | input              | 用 config 区分 User/File/API/Schedule（当前编辑器未实现需新增） |
| Prompt Template| prompt_template    | 已有，可扩展 variables/role |
| LLM            | llm                | 已有；建议将 `model_id` 最终映射到运行时 `model` |
| Agent          | agent              | 编辑器可预留，但运行时映射尚未最终确定，暂不应视为稳定可执行节点 |
| Tool/Skill     | tool               | 已有；配置项建议统一为 `tool_name` + `inputs` |
| Knowledge      | **待新增**         | knowledge 或 rag |
| Condition      | condition          | 已有，需落实条件配置与分支边 |
| Loop           | loop               | 已有，需落实迭代与 output_key |
| Output         | output             | 用 config 区分 Chat/File/Webhook/API（当前编辑器未实现需新增） |

**可合并或延后**：System Prompt（并入 Prompt Template 或单独类型）、Variable（作为画布级或节点级配置）、Parallel（用多边 + 汇聚语义表达）。

---

## 6.1 Editor → Runtime 映射（建议）

该表用于避免“编辑器字段/运行时字段不一致”导致的不可执行问题。

| Editor 节点类型 | Runtime NodeType | 关键 config（Editor） | 关键 config（Runtime） | 备注 |
|---|---|---|---|---|
| llm | llm | `model_id` / `temperature` / `max_tokens` | `model` / `temperature` / `max_tokens` | `model_id` 需映射为 `model`（alias） |
| agent | 待定 | `agent_id` / `input_mapping` | 待定 | 需要先确定是专用 handler 还是 Tool 封装，当前不应写死 |
| tool | tool | `tool_name` / `inputs` | `tool_name` / `inputs` | ToolRegistry 负责 schema/permission 校验 |
| script | script（或 tool） | `command` | `tool_name=builtin_shell.run` + `command` | 仍走权限控制 |
| condition | condition | `condition_expression`（或结构化 compare） | `condition_expression` | 条件求值必须是安全子集 |
| loop | loop | `max_iterations` / `timeout_seconds` / `condition_expression` / `audit_log` | `loop_config.*` | 循环必须有限制与审计 |

---

## 7. 实施建议与优先级

1. **P0（先统一语义与配置）**  
   - 为上述 9 类节点定义统一的 **config schema**（JSON Schema 或 TypeScript 类型），前端表单与后端校验共用。  
   - 明确 Input/Output 的 mode 枚举与各模式的必填/可选配置。

2. **P1（与后端对齐）**  
   - Knowledge 节点：对接现有知识库与 RAG 接口。  
   - Condition：定义条件求值安全子集与分支边语义。  
   - Loop：定义固定次数与条件终止的执行语义及 output_key 传递。

3. **P2（体验与扩展）**  
   - 多段 Prompt、System vs User 的区分。  
   - Loop 的并行/汇聚、Schedule 的重试与幂等。  
   - 多 Output 的优先级与顺序约定。

---

## 8. 修订记录

| 日期       | 说明 |
|------------|------|
| 2025-02-02 | 初稿：节点类型、配置项、数据流与实施建议 |
| 2026-03-15 | 补充：Runtime Contract、权限/Workspace、变量语法与 Editor→Runtime 映射 |

---

*文档状态：供评审，待确认后进入开发阶段。*
