# Workflow Control Plane V3.0 联调验收 Checklist（API + 页面）

更新时间：2026-03-17

## 0. 环境前置

- 后端服务启动成功，无 import/migration 错误。
- 前端服务启动成功，可访问：
  - `/workflow`
  - `/workflow/:id/edit`
  - `/workflow/:id/versions`
  - `/workflow/:id/run`
  - `/workflow/:id`
- 准备一个可执行 workflow（建议含 1 个 `llm` 节点 + 1 个 `tool` 节点；可选 1 个 `agent` 节点）。

---

## 1. API 验收

## 1.1 Workflow 列表与分页

- 请求：`GET /api/v1/workflows?limit=10&offset=0`
- 验收：
  - 返回 `items/total/limit/offset`
  - `total` 为真实总数（非当前页条数）
  - 翻页后 `total` 不变化

## 1.2 Version 列表与分页

- 请求：`GET /api/v1/workflows/{workflow_id}/versions?limit=10&offset=0`
- 验收：
  - `total` 为真实版本总数
  - `items` 按创建时间倒序

## 1.3 Execution 列表与分页

- 请求：`GET /api/v1/workflows/{workflow_id}/executions?limit=10&offset=0`
- 验收：
  - `total` 为真实执行总数
  - `state` 过滤生效

## 1.4 创建执行（workflow_id 一致性）

- 请求（推荐默认）：`POST /api/v1/workflows/{workflow_id}/executions`（不传 wait，走默认异步）
- 请求（调试）：`POST /api/v1/workflows/{workflow_id}/executions?wait=true`
- body（正确）：`workflow_id == path workflow_id`
- 验收：
  - 请求成功创建并执行

- body（错误）：故意传另一个 `workflow_id`
- 验收：
  - 返回 `400`
  - `detail` 包含 `workflow_id mismatch`

## 1.5 Draft 版本执行策略

- 前置：该 workflow 无 published 版本，仅有 draft 最新版本。
- 场景 A（`workflow_allow_draft_execution=true`）：
  - 请求：`POST /api/v1/workflows/{workflow_id}/executions`
  - 验收：可 fallback 到最新 draft 并进入执行链路。
- 场景 B（`workflow_allow_draft_execution=false`）：
  - 请求：`POST /api/v1/workflows/{workflow_id}/executions`
  - 验收：返回明确失败（无 published 版本不可执行）。

## 1.6 Governance 配置读写

- 请求：`GET /api/v1/workflows/{workflow_id}/governance`
- 请求：`PUT /api/v1/workflows/{workflow_id}/governance`
  - 示例：`{"max_queue_size": 2, "backpressure_strategy": "reject"}`
- 验收：
  - 回读配置与写入一致
  - 非法策略值返回 `400`

## 1.7 版本 compare / rollback

- 请求：`GET /api/v1/workflows/{workflow_id}/versions/compare?from_version_id=...&to_version_id=...`
- 验收：
  - 返回 `summary/nodes/edges`

- 请求：`POST /api/v1/workflows/{workflow_id}/versions/{version_id}/rollback`
- 验收：
  - 生成新版本
  - `publish=true` 时工作流 `published_version_id` 更新

## 1.8 执行详情可观测字段

- 请求：`GET /api/v1/workflows/{workflow_id}/executions/{execution_id}`
- 验收：
  - 返回 `node_states`
  - 返回 `node_timeline`（事件流优先，必要时由 `node_states` 补全）
  - 返回 `replay`
  - 含 agent 节点时返回 `agent_summaries`

## 1.9 手动对账接口

- 请求：`POST /api/v1/workflows/{workflow_id}/executions/{execution_id}/reconcile`
- 验收：
  - 当 execution 状态与节点终态短时不一致时，可手动触发收敛。
  - 返回结构包含最新 `state/node_states/node_timeline`。

---

## 2. 页面验收

## 2.1 Workflow 首页（列表页）

- 验收：
  - 列表分页可用
  - 进入详情/编辑/运行跳转正确

## 2.2 Workflow 编辑页

- 验收：
  - 拖拽节点到画布后，节点不会丢失
  - 点击节点后右侧配置面板能稳定显示对应配置
  - 保存草稿后刷新仍能还原 DAG
  - Agent 节点可配置 `agent_id`
  - Input/Output 节点校验生效（`input_key` 类型、`expression` 对 `output_key` 的约束）
  - 当前已知限制：autosave 会创建版本（需重点观察是否出现版本膨胀）

## 2.3 Workflow 版本页

- 验收：
  - 版本列表可见且状态正确
  - compare 可得到差异摘要
  - rollback 操作可成功

## 2.4 Workflow 运行页

- 验收：
  - `Start/Stop/Restart` 正常
  - `强制对账` 按钮可用，异常场景可手动收敛状态
  - 节点结果区域显示 `input/output/error/retry/duration`
  - Timeline 与 Inspector 的节点状态一致（以事件流状态为主）
  - 失败节点能看到明确错误信息

## 2.5 Workflow 详情页

- 验收：
  - 可查看执行历史
  - 可查看节点级结果
  - governance 配置可编辑并保存

---

## 3. 并发与背压验收

- 配置：`max_queue_size=1`，`backpressure_strategy=reject`
- 并发触发 3 次执行
- 验收：
  - 至少 1 次请求被拒绝（可定位到背压/队列限制）
  - 系统无崩溃、无死锁

---

## 4. 回归验收（必须）

- 能跑通以下两条主链路：
  - `编辑 -> 保存版本 -> 运行 -> 查看执行详情`
  - `发布版本 -> 运行 -> 列表/详情状态一致`
- 回归无旧问题复现：
  - `NodeCache.__init__ missing repository`
  - `Version cannot be executed: draft`（manual/api/debug 场景）
  - 列表 `total` 错误
  - `workflow_id` path/body 不一致未拦截
  - 运行页节点长期 pending 但后端已完成
  - 事件缺失导致 timeline 节点消失
