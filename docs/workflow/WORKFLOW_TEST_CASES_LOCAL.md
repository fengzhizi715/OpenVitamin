# Workflow 本地联调完整测试 Case（基于现有模型与智能体）

更新时间：2026-03-17

## 1. 目标

提供一个可直接在你当前环境执行的 **完整 Workflow 测试流程**，覆盖：

- Workflow 编辑与保存版本
- 执行（Run）
- 节点级结果查看（Timeline / Inspector）
- Agent 节点调用（已有智能体）

---

## 2. 环境前置（按你当前资产）

已使用资产：

- 本地模型：`local:qwen3-8b`（LLM）
- 智能体：`agent_f6887b0e`（含 `builtin_web.search` 能力）
- 页面入口：
  - Workflow 编辑页：`/workflow/{workflow_id}/edit`
  - Workflow 运行页：`/workflow/{workflow_id}/run`

建议测试 workflow：

- `workflow_id = b0bd2300-a386-4a4d-8588-0af97c639696`

---

## 3. 完整 Case A（推荐先跑）

## 3.1 业务目标

用户输入一个学习主题（如“Rust 入门”），Workflow 调用智能体搜索并总结，输出结构化结果。

## 3.2 DAG 结构

1. `start`（`start` 节点，固定入口）
2. `user_input`（`input` 节点，承接执行入参）
3. `agent_search`（`agent` 节点，调用 `agent_f6887b0e`）
4. `final_output`（`output` 节点）

连线：

- `start -> user_input -> agent_search -> final_output`

## 3.3 节点配置

### `user_input`（input）

- `type`: `input`
- `config` 示例（可选）：
```json
{
  "input_key": "topic",
  "input_schema": {
    "type": "object",
    "properties": {
      "topic": { "type": "string" }
    },
    "required": ["topic"]
  }
}
```

> 说明：  
> - `input_key = "topic"` 表示从执行入参的 `input_data.topic` 读取本次学习主题；  
> - `input_schema` 仅用于在编辑器中约定期望结构，当前 Runtime 不强制校验。

### `agent_search`（agent）

- `type`: `agent`
- `config`:
```json
{
  "agent_id": "agent_f6887b0e",
  "prompt": "请基于用户主题给出 5 条高质量入门资源，并简要说明每条适用人群。",
  "timeout": 180,
  "max_steps": 6,
  "pass_context_keys": ["topic"],
  "output_schema": {
    "type": "object",
    "required": ["type", "status", "response"],
    "properties": {
      "type": { "type": "string" },
      "status": { "type": "string" },
      "response": { "type": "string" }
    }
  }
}
```

### `final_output`（output）

- `type`: `output`
- `config` 示例：
```json
{
  "output_key": "workflow_test_case_a_result",
  "expression": "${nodes.agent_search.output.response}"
}
```

> 说明：  
> - `output_key` 表示将最终结果写入 `execution.output_data.workflow_test_case_a_result`；  
> - `expression` 使用执行上下文，从 `agent_search` 节点输出中选取 `response` 作为最终结果。

---

## 4. 执行步骤（UI）

1. 打开 `/workflow/b0bd2300-a386-4a4d-8588-0af97c639696/edit`
2. 按上面的 DAG 与配置设置节点（`start / user_input / agent_search / final_output`）
3. 保存并创建新版本（编辑页点击 Save，返回 Workflow 详情页可看到最新版本）
4. 打开 `/workflow/b0bd2300-a386-4a4d-8588-0af97c639696/run`
5. 点击 `Start`（Run 页内部使用 `wait=false` + 轮询模式）
6. 在 Timeline 观察节点状态流转：
   - `start` -> `user_input` -> `agent_search` -> `final_output`
7. 点击左侧列表中的 `agent_search`，在 Node Inspector 查看：
   - Input（应包含从 `input_data.topic` 传入的主题内容）
   - Output（应含 `type=agent_result` 与 `response`）
   - 若失败，查看 `error_message` / `error_details`

---

## 5. 预期结果（通过标准）

通过标准：

1. execution 状态最终为 `completed`
2. `agent_search` 节点状态为 `success`
3. `agent_search.output_data` 中包含：
   - `type: "agent_result"`
   - `status: "success"`（或等价成功态）
   - `response`（非空文本）
4. `final_output` 节点成功，Execution Output 可看到汇总结果

---

## 6. 快速排障

1. **点击 Start 无反应**
- 先强刷前端（`Cmd+Shift+R`）
- 看后端是否有 `POST /executions?wait=false` 日志

2. **执行卡在 pending**
- 检查后端是否有后台执行日志
- 检查该 workflow 最新版本 DAG 是否可执行（节点类型/配置完整）

3. **agent 节点失败**
- 核查 `agent_id` 是否存在：`agent_f6887b0e`
- 查看 `error_details`（M5.1 已支持结构化 schema 错误）

4. **schema 校验失败**
- 对照 `output_schema` 与 `agent_result` 实际结构
- 先放宽 schema，再逐步收紧

---

## 7. 可选扩展 Case B（视觉链路）

若你希望再测视觉能力，可新增一个 workflow：

- `input(image_path)` -> `agent(agent_44a02aa6)` -> `output`

用途：验证视觉分析 Agent 在 Workflow 中可被调用并返回可读结果。  
建议先跑通 Case A 后再做。

---

## 8. 建议新增测试 Case（用于回归与稳定性）

下面这些 Case 建议分批加到本地回归，每个 Case 都尽量固定输入，便于复现。

## 8.1 Case C：并发与队列治理

目标：验证 Execution Governance（排队 / 并发限制 / 状态一致性）是否稳定。

DAG（最小）：

- `start -> input -> agent_search -> output`

执行方式：

1. 连续点击 `Start` 3~5 次（或并发请求 `/executions?wait=false`）。
2. 观察：
   - 是否有 execution 进入 `queued/pending` 后再转 `running`；
   - 是否出现重复 execution（同一次点击导致多条记录）；
   - 历史列表状态是否最终收敛到终态。

通过标准：

- 不出现“同一请求创建多条 execution”的异常；
- 不出现长期 `pending`（超过阈值应有告警日志）；
- execution 最终状态与 run 页一致。

## 8.2 Case D：停止（Cancel）一致性

目标：验证运行中 Stop 能正确终止，并且前后端状态一致。

DAG：

- `start -> input -> agent_search -> output`（让 agent 节点执行稍长一点）

步骤：

1. `Start` 后在 agent 节点运行中点击 `Stop`。
2. 检查：
   - run 页状态是否进入 `cancelled`；
   - 节点状态是否从 `running/pending` 回填为 `cancelled` 或终态；
   - `Execution History` 与 run 详情状态是否一致。

通过标准：

- 无“前端已停、后端仍 running”长期不一致；
- 不出现 cancel 后仍继续执行输出的情况。

## 8.3 Case E：Input/Output 语义校验

目标：验证 `input_key/output_key/expression` 的端到端正确性。

DAG：

- `start -> user_input(input_key=topic) -> agent_search -> final_output(output_key=learning_result)`

输入示例：

```json
{ "topic": "Python 入门路线" }
```

通过标准：

- `agent_search` 输入能看到 `topic`；
- `execution.output_data.learning_result` 存在且内容与 agent 输出一致；
- output 节点不会写入空值（除非表达式本身为空）。

## 8.4 Case F：节点失败路径与错误可观测性

目标：验证失败时错误信息可定位。

建议做两个失败子场景：

1. `agent_id` 填不存在值（如 `agent_not_exists`）；
2. 故意配置不合法 `output_schema`，触发 schema 校验失败。

通过标准：

- execution 为 `failed`；
- Node Inspector 有 `error_message/error_details`；
- Execution Logs 有可追踪错误（含 node_id）。

## 8.5 Case G：版本与回滚

目标：验证 Definition/Version/Execution 分离是否可用。

步骤：

1. 创建 v1（可运行）。
2. 修改成 v2（故意引入错误）。
3. 运行 v2 失败后回滚到 v1 并发布。
4. 再次运行应恢复成功。

通过标准：

- 执行记录明确关联到对应 `version_id`；
- 回滚后执行结果回到预期；
- 版本页可追溯。

## 8.6 Case H：历史列表行为（分页 + 删除）

目标：验证历史管理能力。

步骤：

1. 连续运行生成 > 1 页历史（例如 25 条）。
2. 在详情页翻页（Prev/Next）检查状态展示。
3. 删除单条终态 execution。

通过标准：

- 分页总数、区间显示正确；
- 删除后列表刷新，条目消失；
- 运行中 execution 不允许删除（返回明确错误）。

---

## 9. 推荐执行顺序（明日回归）

1. Case A（基础链路）  
2. Case C（并发队列）  
3. Case D（停止一致性）  
4. Case E（输入输出语义）  
5. Case F（失败可观测）  
6. Case H（历史管理）  
7. Case G（版本回滚）

---

## 10. Case I：条件分支型（Condition）- 节点配置模板

目标：根据用户问题是否“需要联网检索”走不同分支。

### 10.1 DAG

1. `start`（start）
2. `user_input`（input）
3. `need_web`（condition）
4. `web_agent`（agent，`agent_f6887b0e`）
5. `local_llm`（llm，`local:qwen3-8b`）
6. `final_output`（output）

连线建议：

- `start -> user_input -> need_web`
- `need_web(true) -> web_agent -> final_output`
- `need_web(false) -> local_llm -> final_output`

### 10.2 节点模板

#### `user_input`（input）

```json
{
  "input_key": "query",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": { "type": "string" }
    },
    "required": ["query"]
  }
}
```

#### `need_web`（condition）

```json
{
  "expression": "${input.query}",
  "operator": "contains_any",
  "value": ["最新", "today", "新闻", "资料", "官网", "教程", "search"],
  "output_key": "need_web_search"
}
```

> 说明：  
> - 当 `query` 包含上述关键词时判定 `true`，否则 `false`。  
> - 若你的 Condition 节点实现字段名不同（如 `left/right` 或 `rules`），保持语义一致即可。

#### `web_agent`（agent）

```json
{
  "agent_id": "agent_f6887b0e",
  "prompt": "请根据用户问题进行联网检索并给出结构化答案，包含来源链接。",
  "timeout": 180,
  "max_steps": 6,
  "pass_context_keys": ["query"]
}
```

#### `local_llm`（llm）

```json
{
  "model_id": "local:qwen3-8b",
  "temperature": 0.3,
  "max_tokens": 1024,
  "system_prompt": "你是本地离线助手。若问题不依赖实时信息，请直接给出清晰答案。"
}
```

#### `final_output`（output）

```json
{
  "output_key": "condition_case_result",
  "expression": "${nodes.web_agent.output.response || nodes.local_llm.output.response || nodes.web_agent.output.text || nodes.local_llm.output.text}"
}
```

### 10.3 运行输入样例

- 走 true 分支（web）：`{"query":"我想学 Rust，有什么最新入门资料？"}`
- 走 false 分支（local）：`{"query":"解释一下二分查找的时间复杂度"}`

### 10.4 通过标准

- true/false 分支可稳定命中；
- 未命中的分支节点保持未执行或 skipped；
- `execution.output_data.condition_case_result` 非空。

---

## 11. Case J：循环精炼型（Loop）- 节点配置模板

目标：对初稿进行多轮精炼（最多 2~3 轮），输出更结构化内容。

### 11.1 DAG

1. `start`（start）
2. `user_input`（input）
3. `draft_llm`（llm，生成初稿）
4. `refine_loop`（loop）
5. `refine_llm`（llm，循环体）
6. `final_output`（output）

连线建议：

- `start -> user_input -> draft_llm -> refine_loop -> final_output`
- `refine_loop(body) -> refine_llm -> refine_loop(next)`（循环回边）

### 11.2 节点模板

#### `user_input`（input）

```json
{
  "input_key": "topic",
  "input_schema": {
    "type": "object",
    "properties": {
      "topic": { "type": "string" }
    },
    "required": ["topic"]
  }
}
```

#### `draft_llm`（llm）

```json
{
  "model_id": "local:qwen3-8b",
  "temperature": 0.5,
  "max_tokens": 900,
  "prompt_template": "请围绕主题“${input.topic}”先写一版初稿，包含：定义、关键点、示例。"
}
```

#### `refine_loop`（loop）

```json
{
  "max_iterations": 2,
  "index_key": "loop_index",
  "item_key": "current_draft",
  "init_expression": "${nodes.draft_llm.output.response || nodes.draft_llm.output.text}",
  "continue_when": "${loop_index < 2}"
}
```

> 说明：  
> - 如果你的 Loop 节点用的是 `while_expression` / `break_when` / `iteration_limit` 等字段，请按同等语义映射。  
> - 建议先设 2 轮，避免耗时过长。

#### `refine_llm`（llm，循环体）

```json
{
  "model_id": "local:qwen3-8b",
  "temperature": 0.2,
  "max_tokens": 700,
  "prompt_template": "第 ${loop_index} 轮精炼。请在不丢信息的前提下，把下面内容改写得更清晰，输出 Markdown：\\n\\n${loop.current_draft}"
}
```

#### `final_output`（output）

```json
{
  "output_key": "loop_case_result",
  "expression": "${nodes.refine_llm.output.response || nodes.refine_llm.output.text || nodes.draft_llm.output.response}"
}
```

### 11.3 运行输入样例

```json
{
  "topic": "Python 生成器与迭代器"
}
```

### 11.4 通过标准

- Loop 轮次按上限停止（不死循环）；
- 每轮状态在 timeline 可见；
- `execution.output_data.loop_case_result` 非空且比初稿更结构化；
- Stop 按钮在循环执行中可生效。
