# Workflow 节点配置指南（实操版）

更新时间：2026-03-17

## 1. 适用范围

本文用于本地联调时快速配置 Workflow 节点，覆盖当前常用节点：

- `start`
- `input`
- `output`
- `llm`
- `agent`
- `tool`
- `condition`
- `loop`
- `script`
- `replan`

---

## 2. 通用规则

1. **先连通再收紧**：先保证链路可跑，再加 schema/条件/超时。
2. **输入字段统一**：尽量统一使用 `query` 或 `topic`，减少节点映射复杂度。
3. **输出明确落 key**：`output` 节点建议始终配置 `output_key`。
4. **节点命名可读**：如 `user_input` / `agent_search` / `final_output`，方便排障。
5. **先发布再跑（生产）**：开发环境可跑 draft，生产建议只跑 published。

---

## 3. 节点模板

## 3.1 start

用途：流程入口，无需复杂配置。

```json
{
  "workflow_node_type": "start"
}
```

---

## 3.2 input

用途：承接执行入参，支持裁剪输入。

最小模板（透传所有 `input_data`）：

```json
{
  "workflow_node_type": "input"
}
```

按 key 裁剪：

```json
{
  "workflow_node_type": "input",
  "input_key": "topic"
}
```

带结构约定（编辑器提示用）：

```json
{
  "workflow_node_type": "input",
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

---

## 3.3 output

用途：把中间结果落到 `execution.output_data`。

推荐模板（显式 `output_key + expression`）：

```json
{
  "workflow_node_type": "output",
  "output_key": "result",
  "expression": "${nodes.agent_search.output.response}"
}
```

无 expression 时会尽量透传上游输出。

---

## 3.4 llm

用途：直接模型推理。

```json
{
  "workflow_node_type": "llm",
  "model_id": "local:qwen3-8b",
  "temperature": 0.3,
  "max_tokens": 1024,
  "system_prompt": "你是一个严谨的技术助手。",
  "prompt_template": "请回答：${input.query}"
}
```

建议：

- 优先设 `model_id`
- 长文本任务适当提高 `max_tokens`
- `prompt_template` 中只引用已存在字段

---

## 3.5 agent

用途：调用已有智能体执行复杂任务。

```json
{
  "workflow_node_type": "agent",
  "agent_id": "agent_f6887b0e",
  "prompt": "请根据用户问题给出 5 条高质量资料，并附链接。",
  "timeout": 180,
  "max_steps": 6,
  "pass_context_keys": ["query", "topic"]
}
```

可选默认输入（避免空输入）：

```json
{
  "workflow_node_type": "agent",
  "agent_id": "agent_f6887b0e",
  "fixed_input": {
    "query": "请总结 Rust 入门资料"
  }
}
```

注意：

- 常见错误：`AGENT_NODE_INPUT_EMPTY`
- 至少保证有可解析输入（`prompt/query/topic/...`）

---

## 3.6 tool

用途：直接执行工具（不经 agent 规划）。

```json
{
  "workflow_node_type": "tool",
  "tool_name": "builtin_web.search",
  "fixed_input": {
    "query": "Rust 入门资料",
    "top_k": 5
  }
}
```

注意：

- `tool_name` 或 `tool_id` 必须存在，否则会报兼容性错误。

---

## 3.7 condition

用途：布尔分支控制。

```json
{
  "workflow_node_type": "condition",
  "expression": "${input.query}",
  "operator": "contains_any",
  "value": ["最新", "新闻", "官网", "search"],
  "output_key": "need_web_search"
}
```

边建议：

- `condition -> web_branch`（true）
- `condition -> local_branch`（false）

---

## 3.8 loop

用途：多轮迭代优化结果。

```json
{
  "workflow_node_type": "loop",
  "max_iterations": 2,
  "index_key": "loop_index",
  "item_key": "current_draft",
  "init_expression": "${nodes.draft_llm.output.response}",
  "continue_when": "${loop_index < 2}"
}
```

注意：

- 建议先小轮次（2~3）验证
- 必须有明确退出条件，避免长时间运行

---

## 3.9 script

用途：执行脚本逻辑（转换、拼接、格式化等）。

```json
{
  "workflow_node_type": "script",
  "language": "python",
  "timeout": 900
}
```

建议：

- 长脚本用较大 `timeout`
- 输入输出尽量 JSON 化，便于下游节点消费

---

## 3.10 replan

用途：失败后重规划（恢复路径）。

```json
{
  "workflow_node_type": "replan",
  "max_replans": 1,
  "strategy": "fallback"
}
```

建议：

- 先在失败注入场景验证 replan 是否生效

---

## 4. 推荐最小可跑模板（A/B/C）

1. **A（基础）**：`start -> input -> agent -> output`
2. **B（分支）**：`start -> input -> condition -> (agent|llm) -> output`
3. **C（迭代）**：`start -> input -> llm -> loop -> llm -> output`

---

## 5. 常见报错与处理

1. `AGENT_NODE_INPUT_EMPTY`
- 原因：agent 节点没有拿到可解析输入。
- 处理：在 `agent` 节点加 `prompt` 或 `fixed_input.query`；确认上游 `input_key` 正确。

2. `Tool node ... missing 'tool_name' or 'tool_id'`
- 原因：tool 节点缺必填字段。
- 处理：补 `tool_name`。

3. `Version cannot be executed` / draft 相关告警
- 原因：执行版本状态不允许。
- 处理：发布版本后再执行，或仅在开发模式允许 draft。

4. 状态长时间 `pending/running`
- 原因：并发排队、长耗时节点、或状态回填延迟。
- 处理：看 run 页 logs + 后端 `ExecutionManager` 告警；必要时 `reconcile`。
