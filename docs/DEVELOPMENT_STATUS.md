# 开发状态

本文档记录项目功能开发状态：已完成功能与计划中功能。

---

## ✅ 已完成功能

### 🏗️ 核心架构

- **模型发现与注册**：解耦模型发现 (Scanner)、模型库 (Registry) 与执行引擎 (Runtime)
- **模型选择**：ModelSelector 支持按标签/能力自动选择模型，含 VRAM 充足性检查
- **智能 Auto 模式**：自动检测消息内容，有图像时切换 VLM，无图像时使用 LLM，优先本地模型
- **统一入口**：FastAPI 推理网关统一入口，屏蔽底层后端差异
- **Inference Gateway（V2.8）**：统一推理入口，协调 ModelRouter、ProviderRuntimeAdapter、Streaming 与 Fallback 链
- **Runtime Stabilization（V2.9）**：统一模型实例管理、按模型维度并发队列、运行时指标采集与稳定性治理
- **Workflow Control Plane（V3.0）**：Workflow Definition / Version / Execution 分层管理，Execution Kernel 专注 DAG 执行
- **Image Generation Control Plane**：文生图任务使用独立 API、任务状态、结果落盘、历史与缩略图链路

### 🤖 模型管理

- **多后端支持**
  - Ollama 自动同步
  - LM Studio 端口扫描
  - 本地 GGUF 目录扫描（Manifest 驱动）
  - `image_generation` 独立模型类型，支持 `mlx` 与 `diffusers` 两类运行时声明
- **统一卸载与并发保护**
  - RuntimeFactory `unload_model` 统一卸载入口（VLM/LLM/Perception/ASR/Embedding/Image Generation）
  - 推理与卸载使用读写锁隔离，允许并发推理，卸载等待进行中的请求
  - 本地运行时缓存上限按模型类型拆分（LLM / VLM / Image Generation），避免文生图与聊天模型互相误伤
  - 切换文生图模型时会主动释放其他 image generation runtime，并在 MPS OOM 场景下执行一次回收后重试
- **llama.cpp Runtime**
  - GGUF 模型支持
  - ChatML/Llama3 等模板适配
  - Apple Silicon / NVIDIA CUDA 支持
- **VLM Runtime (视觉语言模型)**
  - **LlamaCppVLMRuntime**：LLaVA v1.5 支持（Llava15ChatHandler + mmproj）
  - **TorchVLMRuntime**：支持 InternVL3、Qwen2-VL、Qwen3-VL 等 PyTorch 格式模型
    - InternVL3 适配器（InternVLAdapter）：优先使用 `model.chat()` 方法
    - Qwen-VL 适配器（QwenVLAdapter）：支持 Qwen2-VL 和 Qwen3-VL，自动识别模型类型并使用正确的类（Qwen2VLForConditionalGeneration / Qwen3VLForConditionalGeneration）
    - **真实卸载**：支持 GPU 释放（`torch.cuda.empty_cache()` + gc），避免模型切换占用累积
  - 相对路径兼容（model.json 中 path、mmproj_path 支持相对路径）
  - `/v1/vlm/generate` 多模态推理接口
  - 聊天页面图像上传与多模态对话
  - VLM 消息与会话持久化（含附件 base64 存储）
  - **内容顺序修复**：LLaVA 模型要求图像在文本前，已修复前端发送顺序与后端处理逻辑
  - **类型兼容性**：统一处理 dict 和 Pydantic MessageContentItem 对象
  - **System Prompt 优化**：明确说明图像已直接输入到视觉编码器，禁止"无法查看图像"等回复
  - **多模态消息处理**：修复了多模态消息合并时的错误，确保图像内容结构不被破坏
- **Perception 模型（视觉感知）**
  - 与 ASR/VLM 一致的模型生命周期：扫描 → 注册 → Factory 创建 runtime → 统一 load/unload
  - LocalScanner 扫描 `perception/` 目录，解析 `model.json`
  - RuntimeFactory：`create_perception_runtime`、`unload_perception_runtimes`、`get_active_perception_runtime`
  - Models 页支持 perception 模型注册与配置（运行时按需加载）
  - YOLO Tool 优先从 Factory 获取已加载 runtime，若无则回退到配置路径
- **Image Generation Runtime（文生图）**
  - `MLXImageGenerationRuntime`：支持 Qwen Image 等 MLX / mflux 路径
  - `DiffusersImageGenerationRuntime`：支持 FLUX / FLUX.2 / SDXL 等标准 Diffusers 目录
  - `/api/v1/images/*` 独立图片生成接口、任务治理与结果下载链路
  - 支持 load / unload / queue / cancel / warmup / job persistence / thumbnail
- **目录管理**：LLM (GGUF)、Embedding (ONNX)、ASR、Perception、VLM (GGUF + mmproj) 与 Image Generation 分层目录管理
- **模型配置编辑**
  - 独立全屏页面（`/models/:id/config`）编辑本地模型 `model.json`
  - 非本地模型仅支持侧边栏运行时配置
  - MODEL PATH 显示绝对路径，保存时自动转为相对路径
  - `GET /api/models/{model_id}/browse` 目录浏览 API，用于路径选择
  - Browse 弹窗：目录导航、文件选择，支持 MODEL PATH 与 PROJECTOR PATH
  - Capabilities 标签页可配置（chat、vision、embedding、text_to_image 等）
  - 模型注册表支持 `/models/image-generation` 独立分类视图
  - 系统设置支持 `/settings/image-generation` 配置默认文生图模型

### 💬 对话功能

- **流式输出**：全链路 SSE 流式输出
- **参数管理**：聊天参数 (Temperature/Top-P 等) 与模型绑定并持久化
- **会话管理**：多会话切换、重命名、删除，历史消息持久化
- **VLM 多模态**：选中 VLM 模型时可上传图像，图像与文本一并发送；回复后图像在历史中保留显示
  - **模型切换卸载**：会话内切换模型时，自动卸载上一个本地模型（VLM/LLM/Perception/ASR）

### 🧠 记忆与知识库

- **长期记忆**
  - sqlite-vec 向量索引
  - 语义检索
  - 记忆提取与注入
  - 统一存储与管理
- **知识库**
  - PDF/DOCX 解析
  - 文档上传/切分/向量化/检索
  - 状态机 (READY/INDEXING/ERROR)
  - RAG Trace 可追溯

### 👥 逻辑多用户架构

- **核心数据隔离**：知识库、文档、RAG Trace 等核心表添加 `user_id` 字段
- **用户 ID 获取**：通过 HTTP Header `X-User-Id` 获取，不存在时 fallback 到 `"default"`
- **Store 层改造**：所有 CRUD 方法添加 `user_id` 参数，查询时自动按用户过滤
- **API 层适配**：Knowledge API、RAG Trace API 等全面支持用户隔离
- **前端兼容**：UI 保持单用户体验，底层已具备多用户数据隔离能力
- **工具模块**：`core/utils/user_context.py` 提供统一用户 ID 获取函数

### 🔌 插件系统

- **生命周期**：load → initialize → ready → execute → teardown
- **校验与权限**：JSON Schema 校验与权限声明
- **工具注册**：插件注册工具，Agent 通过 ToolRegistry 调用，与核心解耦

### 🤖 智能体系统 (Agent)

- **核心循环**：Think-Action-Observation 单智能体循环；AgentExecutor 统一调度 LLM 与 Skill，输入/输出 Schema 校验
- **v1.5 架构升级**
  - Agent 通过 `enabled_skills` 使用 Skill
  - Skill 封装 Tool
  - Agent 仅调用 `execute_skill`，不直接接触 Tool
- **v2 Plan-Based 执行模式**
  - **Planner 智能意图识别**：根据用户输入自动匹配 Skill
    - 关键词匹配：如"记录"、"生成"、"周报"等触发对应 Skill
    - 日期型记录识别：自动识别"2月9日"或"2026-02-09"格式，优先使用 append 落盘
    - 周报/汇总识别：自动识别"周报"、"本周"、"汇总"等，优先使用 read 读取记录
    - 默认策略：当仅配置 file.read/file.append 时，默认优先 append 确保记录落盘
  - **记录文件名提取**：从 Agent 的 system_prompt 中自动提取约定的 .json 文件名（如 `weekly_records.json`）
  - **会话级工作目录持久化**：workspace 目录自动绑定到会话并持久化，同会话后续请求自动使用正确目录
  - 执行流程：Plan → Skill → LLM 生成最终回复
- **v2.1 层级执行追踪**
  - **StepLog 层级字段**：`parent_step_id` 和 `depth` 支持步骤层级追踪
  - **统一递归入口**：`execute_plan` 支持 `trace`、`parent_step_id`、`depth` 参数，实现所有递归共享同一个 ExecutionTrace
  - **_execute_composite 共享 trace**：不再新建 trace，子步骤日志统一合并到父 trace
  - **递归调用 final_status 保护**：仅顶层调用修改 trace.final_status，递归调用不修改，避免状态被覆盖
  - **层级信息持久化**：通过 input_data._parent_step_id 和 input_data._depth 保留层级信息（临时方案）
  - **composite 步骤状态判断**：根据子计划内步骤状态判断，而非依赖 trace.final_status
  - **执行树可视化支持**：通过 `parent_step_id` 和 `depth` 可构建完整的执行树结构，便于调试和失败定位
- **v2.2 动态重规划（RePlan，Intent Rules 配置化）**
  - **StepType.REPLAN**：新增重规划步骤类型，支持执行过程中动态生成新 Plan
  - **Step.replan_instruction**：重规划指令，由 LLM 决定如何重规划
  - **Step.on_failure_replan**：失败时可触发重规划（需配置开启）
  - **Plan.parent_plan_id**：父子 Plan 血缘关系
  - **ExecutionTrace.plan_stack**：Plan 栈管理，支持嵌套执行
  - **ExecutionTrace.root_plan_id**：根 Plan ID 追踪
  - **create_followup_plan()**：Planner 新增方法，根据 execution_context 生成后续 Plan
  - **当前状态说明**：默认流程仍以 v2.1 主链路为主；v2.2 作为可配置能力逐步启用
  - **向后兼容**：旧 Agent 和无 REPLAN 的 Plan 沿用 V2.1 逻辑
  - **model_params.intent_rules**：Agent 级配置，通过前端 UI 配置意图规则列表
  - **规则结构**：keyword（触发关键词）+ skill_id（对应 Skill）+ description（描述）
  - **前端 UI**：CreateAgentView/EditAgentView 支持添加/编辑/删除 Intent Rules
- **v2.3 Plan Contract（RePlan 结构化计划契约）**
  - **Plan Contract 模块**：新增 `core/plan_contract`，定义 `Plan / PlanStep / PlanMetadata` 结构化模型
  - **契约校验**：`validate_plan()` 校验空步骤、重复 step id、依赖缺失、循环依赖（DAG）
  - **最小接入策略**：在不改 Executor 执行模型前提下，将 Contract 通过适配层转换为 runtime Plan 串行执行
  - **RePlan 集成点**：`Planner.create_followup_plan()` 支持从上下文读取 Contract（按 source 优先级）
  - **Agent 配置项**：
    - `plan_contract_enabled`：开启 RePlan Contract 读取
    - `plan_contract_sources`：source 优先级（默认 `replan_contract_plan -> plan_contract -> followup_plan_contract`）
    - `plan_contract_strict`：严格模式（Contract 非法时 fail-fast，不回退 LLM）
  - **LLM Step 输入规范化**：Contract 中 `llm.*` 步骤要求 `messages` 或 `prompt`（`prompt` 自动转 `messages`）
  - **测试覆盖**：新增 RePlan Contract 集成测试（合法接入、非法拒绝、strict 模式、LLM prompt 规范化）
- **图片工具接入 Agent / Skill 体系**
  - 内置图片工具：`image.list_models`、`image.generate`、`image.get_job`、`image.cancel_job`
  - `image.generate` 支持默认模型选择、默认异步任务化（wait=false）与多模型扩展
  - Agent 侧支持 `Response Mode / Direct Tool Result`，适合工具型智能体直接返回结构化结果
  - built-in skill schema 启动时自动与 Tool 定义同步，避免历史 schema 漂移
  - Planner 补参策略已收敛：无参 skill 不再强塞 `user_input`，`job_id` 可从输入或最近上下文补全
- **v2.4 Skill 重构与语义发现**
  - **Skill Discovery 引擎**：基于向量相似度的语义检索能力
    - `SkillVectorIndex`：内存向量索引，余弦相似度计算
    - `SkillDiscoveryEngine`：语义检索 + 结构化过滤 + 权限控制
    - Hybrid 排序：语义相似度 (70%) + 标签匹配度 (30%)
    - 支持动态刷新索引（Skill 更新后重建）
  - **Skill 权限与范围**：
    - 可见性级别：public / org / private
    - Agent 级访问控制：`allowed_agents` 字段
    - 组织级隔离：`organization_id` 字段
    - `SkillScopeResolver`：统一权限解析器
  - **Skill Embedding**：
    - 自动生成：拼接 name + description + tags + category
    - 可插拔：支持 ONNX / 云端 Embedding 服务
    - 维度一致性验证：防止不同模型混用
  - **运行时语义发现**（仅 Plan-Based V2）：
    - 配置项：`model_params.use_skill_discovery`（bool），默认 false；前端仅在 execution_mode=plan_based 时展示「启用技能语义发现」
    - 触发时机：在 Planner 选技能时，当「精确 ID 匹配」与「intent_rules」均未命中时，若 use_skill_discovery 为 true，则执行语义发现流程（intent_type=semantic_discovery）
    - **语义发现流程**：**向量检索**（SkillDiscoveryEngine.search，扩大候选数量）→ **过滤 enabled_skills**（仅保留该 Agent 已启用技能）→ **LLM 选择**（多候选时由 LLM 从候选 id+描述中选最合适的一个）→ **降级 fallback**（LLM 未返回有效结果时取第一个候选）
    - 优先级：精确 ID > intent_rules > feature_fallback > **语义发现** > 降级为纯 LLM 计划
    - 启动时：main 中在 SkillRegistry 与 builtin skills 加载完成后，对 Discovery 执行 `bind_registry` + `build_index`，失败仅打 warning，不阻塞启动
  - **多 Agent 隔离能力**：
    - 会话级工作空间隔离：`data/agent_workspaces/{session_id}/`
    - 用户级数据隔离：`user_id` 字段 + 查询过滤
    - 命令执行隔离：每会话命令计数限制
    - RAG 缓存隔离：`{session_id}:{query_hash}` 缓存键
    - SQLite 并发优化：WAL 模式 + 忙时重试机制 + 复合索引
    - 索引优化：6 个复合索引覆盖常用查询模式
- **v2.5 Execution Kernel（DAG 执行引擎）**
  - **Execution Kernel 包**（`backend/execution_kernel/`，与 core 平级）：
    - `models/`：GraphDefinition、NodeDefinition、EdgeDefinition、GraphPatch、ExecutionPointer；NodeState、GraphInstance、NodeRuntime
    - `engine/`：Scheduler（图实例调度、并发上限 Semaphore、重试、RePlan 扩图、崩溃恢复）、Executor（节点执行、超时、Handler 按 NodeType 分发）、StateMachine（**短事务 session**：推荐传 db，每次状态读写独立事务）、GraphContext、GraphPatcher、control_flow（condition/loop）
    - `persistence/`：统一 **platform.db**，与核心平台共用；Database、repositories；**执行指针更新策略** `EXECUTION_POINTER_STRATEGY`（best_effort | strict）控制 DB 锁冲突时的行为
    - `cache/`：NodeCache
  - **实现与运维要点**：
    - **StateMachine 短事务**：生产路径使用 `StateMachine(db=self.db)`，每次状态读写通过 `db.async_session()` 独立短事务，减少长事务持锁；测试/demo 仍可传 NodeRuntimeRepository
    - **僵尸实例清理**：首次 `execute_plan` 时调用 `cleanup_stale_running_instances(max_age_minutes=30)`，将「RUNNING 且 updated_at 超阈值且无 RUNNING 节点」的实例标为 FAILED，仅执行一次
    - **执行指针策略**：环境变量 `EXECUTION_POINTER_STRATEGY`；`best_effort`（默认）重试后仍失败则 log 并跳过，`strict` 则抛异常
  - **Plan → Kernel 适配层**（`core/execution/adapters/`）：
    - **PlanCompiler**：Plan 编译为 GraphDefinition（nodes/edges/subgraphs），支持 Composite 子图、REPLAN/CONDITION/LOOP 节点类型；Step 映射为 NodeDefinition，inputs 写入 node config（含 default_input）
    - **ExecutionKernelAdapter**：PlanBasedExecutor 通过 adapter 将 Plan 交给 Kernel 执行；上下文拆分为 persisted_context（可 JSON 序列化入库）与 runtime_context（内存对象）；支持 apply_replan_patch（RePlan 动态扩图）
    - **Node Executors**：LLMExecutor、SkillExecutor、InternalExecutor 及 condition/loop/replan Handler 在 Kernel 内注册，内部复用既有 Agent 能力；错误通过抛异常或返回 `{error}` 由 Kernel 统一识别并标记节点失败
  - **状态与可观测性**：
    - Kernel 执行完成后，`_sync_plan_step_statuses` 将节点状态同步回 Plan.steps；`_collect_trace_with_subgraphs` 收集层级 Trace
    - 从 NodeRuntime 结果构建 ExecutionTrace（StepLog），与现有 Trace 存储、会话回写兼容；首条 trace 可带 `_execution_engine`、`tool_id` 便于前端展示
  - **并发与稳定性**：Scheduler 使用 asyncio.Semaphore 限制并发；Executor 对 Handler 返回的 `{error}` 统一识别并抛出 NodeExecutionError；Kernel 异常时自动回退 PlanBasedExecutor
- **v2.6 Deterministic Event-Sourced Runtime（可重建系统）**
  - **定位升级**：从「可运行引擎」升级为「可重建系统」——任意一次 Kernel 执行除可被调度运行外，还可通过持久化事件流在事后完整重建状态与决策序列，支持回放、校验与离线分析。
  - **事件模型**：`ExecutionEvent` 不可变、顺序编号；覆盖 Graph/Node/Scheduler/State/Patch/Recovery 等生命周期；`EventStore` 仅追加写入，fire-and-forget，不阻塞主流程。
  - **可复现性**：Scheduler 决策（如 NODE_SCHEDULED、executable_nodes 顺序）与节点起止、补丁应用、崩溃恢复均落事件流；同一 instance 的 replay 可得到确定性的 `RebuiltGraphState`。
  - **离线能力**：`StateRebuilder` 从事件流重建图状态与节点结果；`ReplayEngine` 支持 replay_to_point（断点式回放）与流完整性校验；`MetricsCalculator` 提供执行耗时与事件统计，便于离线分析。
  - **API 与 Debug**：`/api/events/instance/{instance_id}/events`、`replay`、`validate`、`metrics` 等接口；前端 Debug UI（EventStreamViewer）基于 `kernel_instance_id` 展示事件流、指标、校验结果与重建状态，支持按序列号回放到指定点。
  - **会话关联**：Agent 会话持久化 `kernel_instance_id`，执行页可跳转查看该次运行的 Event Stream 与 Replay。
- **v2.7 Optimization Layer（旁路优化层）**
  - **定位**：在**不改变** Execution Kernel 图结构与运行实例的前提下，仅影响调度策略、执行排序与失败恢复策略；可插拔、可关闭、可回滚，Kernel 仍保持 deterministic。
  - **可插拔**：`OptimizationConfig` 驱动；adapter 按配置构建 `run_policy` 与 `run_snapshot` 传入 Scheduler；`enabled=false` 时强制 DefaultPolicy、无快照，严格旁路。
  - **策略可版本化**：`SchedulerPolicy` 提供 `get_version()`；`SCHEDULER_DECISION` 事件 payload 含 `policy_version`、`snapshot_version`；Replay 可校验 `expected_policy_version` / `expected_snapshot_version`。
  - **可关闭/回滚**：API `POST /kernel/optimization/config` 可设 `enabled: false` 或 `scheduler_policy: default`，立即生效；配置仅作用于当前 adapter，支持 Agent 级覆盖（`model_params.execution_kernel_optimization` / `optimization_config` / `optimization`）。
  - **成功率可量化**：`StatisticsCollector` 从事件流汇总 success/failure/retry；`OptimizationDataset` 含 node/skill 统计与可选 `metrics_summary`；`SnapshotBuilder` 基于数据集构建 `OptimizationSnapshot`；`GET /kernel/optimization/impact-report` 对比当前快照与空快照，返回成功率提升、延迟变化及 `baseline_empty`/`note` 说明。
  - **安全重规划**：`Replanner` 从失败 GraphInstance 创建新实例（禁止修改运行中实例），记录 `ReplanRecord`（failed_instance_id → new_instance_id、reason、planner_version），支持从失败点恢复；与 V2.2 动态重规划的区别：V2.2 是 PlanBasedExecutor 层的 followup_plan 入栈，V2.7 Replanner 是 Kernel 层的新实例创建。
  - **快照持久化**：`OptimizationSnapshotDB` 表与 `OptimizationSnapshotRepository`（save/get_by_version/list_latest/get_latest/delete_by_version）；`SnapshotBuilder.build_and_persist()` 支持构建并落库；从 DB 加载时 `to_snapshot()` 将 `source_event_count`/`source_instance_count` 合并到 metadata，确保与 Builder 产出结构一致。
  - **API**：`GET /kernel/optimization`（状态）、`POST /kernel/optimization/rebuild-snapshot`、`POST /kernel/optimization/config`、`GET /kernel/optimization/impact-report`（效果报告）。
  - **前端**：Optimization Dashboard（`/optimization`）展示状态、开关、策略选择、重建快照、效果报告（含 baseline 说明）。
- **v2.8 Inference Gateway Layer（统一推理网关）**
  - **定位**：在 Agent/Skill 与模型运行时之间引入统一抽象层，实现调用方与提供方解耦；所有推理调用（LLM/VLM/Embedding/ASR）经统一入口。
  - **核心组件**：
    - `InferenceClient`：统一入口，提供 `generate()`、`stream()`、`embed()`、`transcribe()` 方法
    - `InferenceGateway`：中枢路由，协调 ModelRouter 与 ProviderRuntimeAdapter
    - `ModelRouter`：别名解析，支持 `alias → (provider, model_id)` 映射与 Fallback 链
    - `ProviderRuntimeAdapter`：后端适配，桥接现有 RuntimeFactory，不修改底层运行时
    - `InferenceModelRegistry`：别名管理，支持注册、解析、与 ModelRegistry 同步
    - `TokenStream`：流式抽象，统一 token 收集与延迟追踪
  - **模型别名**：逻辑名称映射到具体模型，如 `reasoning-model` → `deepseek-r1`，支持配置化切换
  - **Fallback 链**：主模型不可用时自动切换备用模型，提升系统韧性
  - **直通模式**：未知别名直接作为 model_id 使用，保持向后兼容
  - **Streaming 支持矩阵**：`RuntimeCapabilities` 声明各运行时流式能力（native/fake/none）
  - **OpenClaw 接入**：
    - 新增 `docs/OPENCLAW_BACKEND_CONFIG.md`，覆盖 provider/model 配置、局域网部署、CORS 边界、会话复用行为
    - 明确模型优先级：`agents.list[].model` 覆盖 `agents.defaults.model.primary`
  - **运行时边界说明**：
    - MLXRuntime 当前为文本 LLM 路径（不支持平台内 VLM 图像输入流程）
    - `docs/LLM_PARAMETER_GUIDE.md` 已改为平台一致版，仅保留当前主路径稳定生效参数
  - **数据模型**：`InferenceRequest/Response`、`EmbeddingRequest/Response`、`ASRRequest/Response` 统一 API 契约
  - **目录结构**：`core/inference/`（client/、gateway/、router/、providers/、registry/、models/、streaming/）
- **v2.9 Runtime Stabilization Layer（运行时稳定层）**
  - **定位**：在推理网关与 RuntimeFactory 之间增加稳定层，提升多模型/多请求下的稳定性，避免并发导致 OOM 或卡死。
  - **核心组件**：
    - **ModelInstanceManager**：统一模型实例管理，懒加载、单例缓存、可卸载；按 model_id 串行加载（asyncio.Lock），避免重复加载。
    - **InferenceQueue**：按模型维度的并发队列，`asyncio.Semaphore` 限制单模型并发；支持动态更新 `max_concurrency`（队列空闲时）。
    - **RuntimeMetrics**：线程安全按模型统计请求数、失败数、延迟、tokens、队列长度。
    - **RuntimeConfig**：`max_concurrency` 可配置，优先级：`model.json` metadata > `settings.runtime_max_concurrency_overrides` > 代码默认。
  - **集成点**：
    - **ProviderRuntimeAdapter**：`generate`/`stream`/`embed`/`transcribe` 经 `ModelInstanceManager.get_instance` + `InferenceQueue.run`，并记录 metrics、log_structured。
    - **UnifiedAgent**：`chat`/`stream_chat` 接入同一套队列与 metrics，流式完成/失败正确打点。
    - **VLM API**：`/v1/vlm/generate` 经队列与 metrics，并补充 `time` 模块用于耗时统计。
  - **API**：`GET /api/system/runtime-metrics` 返回按模型的请求/延迟/tokens/队列等指标。
  - **可观测性**：`log_structured` 记录 `model_loaded`、`inference_started`、`inference_completed`、`inference_error`。
  - **目录结构**：`core/runtime/`（config/、manager/、queue/、__init__.py）。
- **model.json 备份（阶段 1 + 阶段 2）**
  - **定位**：对本地模型 `model.json` 做写前/手动快照与恢复，与现有 DB 备份（`/api/backup`）并列，API 前缀 `/api/model-backups`。
  - **阶段 1 能力**：
    - **创建备份**：`POST /api/model-backups/create`（单模型）、`POST /api/model-backups/create-all`（全量）；快照命名 `model_<model_id_safe>_<timestamp>_<hash8>.json`，写入 `<backup_root>/model_json/snapshots/<model_id_safe>/`。
    - **索引与审计**：`index/model_backup_index.jsonl` 单行 JSON 事件（event_id、backup_id、model_id、action、after_hash、backup_file、timestamp_utc、reason 等）。
    - **列表**：`GET /api/model-backups?model_id=...&limit=50` 从索引查询备份记录。
    - **恢复**：`POST /api/model-backups/restore`（body 含 `backup_id`、`dry_run`）；恢复前对当前版本做保护性备份，快照与目标写入均采用临时文件→fsync→原子 rename；支持用索引中的 `after_hash` 校验快照完整性。
  - **阶段 2 能力**：
    - **定时全量快照**：`model_json_backup_daily_enabled`、`model_json_backup_daily_time` 配置；启动时 `run_daily_snapshot_loop()` 按设定时间执行全量备份并写每日 manifest。
    - **批量恢复**：`POST /api/model-backups/restore-batch`（`target_timestamp_utc`、可选 `model_ids`、`dry_run`），按时间点恢复多模型。
    - **保留策略**：`GET /api/model-backups/retention-dry-run`、`POST /api/model-backups/cleanup`（7 天全保留、30 天日保留、180 天周保留等策略）。
    - **每日 manifest**：`manifests/` 目录、`GET /api/model-backups/daily-manifests/{date_yyyymmdd}`、`GET /api/model-backups/status` 返回 `last_daily_manifest_date`、`daily_manifest_dates`。
  - **单模型备份入口**：
    - **设置页**：`/settings/model-backup` 顶部「单模型备份」区块，下拉选择本地模型、可选备注、一键创建备份；成功后刷新下方备份列表。
    - **模型配置侧栏**：模型管理页打开本地模型（backend 为 local/llama.cpp）时，在 GPU Layers 下方提供「备份 model.json」按钮，一键对当前模型创建备份。
  - **配置**：`settings.model_json_backup_directory`，为空时默认 `backend/data/backups`；model_id 安全化规则（`:`/`/` 等替换）见文档。
  - **目录结构**：`core/backup/model_json/`（sanitize、path_resolver、storage、service、scheduler）。
- **输出解析**
  - 支持 **skill_call** / tool_call（映射为 `builtin_<tool>`）/ final
  - 自然语言工具描述兜底（识别 "Calling skill ..."）
- **追踪与调试**
  - Session/Event 级 Trace
  - Trace 页可视化（时间线、步骤、JSON 输入输出）
- **会话管理**
  - 会话与消息增删
  - 创建时模型/Skill/知识库校验
  - RAG 上下文自动注入
  - slug 支持
- **文件上传**
  - `POST /api/agents/{agent_id}/run/with-files` 支持 multipart 文件上传
  - 文件保存到会话工作目录（`data/agent_workspaces/{session_id}/`）
  - `file.read` 可通过相对路径访问
  - **workspace 持久化到 Session**：所有会话请求自动绑定到会话工作目录，同会话后续请求自动使用正确目录
  - `session.state` 持久化（`state_json`）：`last_uploaded_images`、`last_uploaded_image`、`last_skill_observation` 等
- **执行页体验**
  - 会话级对话历史持久化与切换（与 /chat 行为一致）
  - 会话删除
  - 执行页「查看 Trace」跳转至 Trace 页；Trace 页时间线、步骤、JSON 输入输出
  - Skill/工具调用在对话中可折叠展示

### 🧩 Workflow Control Plane（V3.0）

- **Workflow 资源模型**
  - `Workflow`：工作流元信息与生命周期状态
  - `WorkflowVersion`：定义快照、校验和、发布状态（draft/published/archived）
  - `WorkflowExecution`：执行实例状态、输入输出、起止时间、触发类型
- **Definition / Runtime 分离**
  - UI 编辑与保存的是 definition/version
  - 运行时执行的是 execution + graph instance
  - Execution Kernel 仅负责 DAG 执行，不直接承载业务定义编辑
- **版本化能力**
  - 草稿保存、发布版本、历史版本查询
  - 版本 diff、回滚到历史版本
- **多实例安全执行（Governance）**
  - 全局并发上限 + 单 workflow 并发上限
  - 队列与 backpressure（含 pending 超时告警）
  - 配额与执行状态治理（pending/running/succeeded/failed/cancelled）
- **运行可观测性**
  - Execution 级状态、节点级状态、节点输入输出、错误信息
  - Timeline / List / Graph 视图与 Node Inspector
  - Execution Logs 与事件回填（含终态 reconcile）
- **前后端联动能力**
  - Workflow 首页：资源列表 + 最近执行
  - Workflow 编辑页：节点库 / 画布 / 配置面板
  - Workflow 运行页：实时状态、停止/重跑、结果展示（Result/Delivery）
  - Execution History：分页、详情跳转、单条删除

### 🎯 Skill 系统 (Skill v1 / v1.5)

- **SkillDefinition**
  - id, name, description, input_schema
  - type（prompt | tool | composite | **workflow**）
  - definition, enabled
- **SkillRegistry**
  - 内存 + SQLite 持久化
  - `list_for_agent(agent.enabled_skills)` 过滤
  - 启动时自动将 ToolRegistry 中的 Tool 注册为 Built-in Skill（id=`builtin_<tool.name>`）
- **SkillExecutor**
  - 校验输入
  - 按 type 执行：prompt 渲染 / tool 调用 / composite（先 prompt 再 tool）/ **workflow（顺序执行多步 tool）**
- **高层内置 Skill（引导型）**
  - 研究汇总（builtin_research.summarize）、文档分析（builtin_document.analyze）、数据分析（builtin_data.analyze）、代码助手（builtin_code.assistant）等为 prompt 型，作 Agent 引导
  - API 操作（builtin_api.operator）为 tool 型，封装 http.request
  - 视觉目标检测（builtin_vision.detect / builtin_vision.detect_objects）为 tool 型，封装 vision.detect_objects
  - 图片工具可通过 Built-in Skill 暴露为 `builtin_image.list_models`、`builtin_image.generate`、`builtin_image.get_job`、`builtin_image.cancel_job`
  - 知识库查询等可挂 RAG；定义见 `backend/core/plugins/builtin/skills/`
- **API 与保护**
  - `GET/POST /api/skills`、`GET/PUT/DELETE /api/skills/{skill_id}`、`POST /api/skills/{skill_id}/execute`
  - **内置 Skill（`builtin_*`）不可修改、不可删除**（API 与 Service 层硬性校验）
- **前端界面**
  - Skills 列表页（搜索、分页、删除）
  - 创建/编辑页（基本信息、逻辑、输入输出 Schema、规则配置）
  - 详情页：按 skill 类型与 `isBuiltin` 动态侧栏；内置 Skill 只读，不展示「规则」区块
  - Agent 创建/编辑页：Skill 选择增强（搜索、分类折叠、已选数量、批量操作）
  - Agent 创建/编辑页：`force_yolo_first` 开关（YOLO-first，仅当意图匹配时生效）

### 🛠️ 工具系统 (Tools v1)

- **基础能力**
  - Tool 基类与 JSON Schema 校验
  - ToolContext 注入 agent_id、trace_id、workspace、permissions
- **内置工具**

  | 工具 ID     | 作用       | 说明 |
  | ----------- | ---------- | ---- |
  | file.read   | 读文件     | 工作区 + 可配置绝对路径根；macOS Unicode NFC/NFD 归一化处理；默认允许所有目录 (`file_read_allowed_roots=/`)
  | file.list   | 列目录     | 工作区内 |
  | python.run  | 执行 Python | 沙箱/超时 |
  | web.search  | 网络搜索   | 可扩展 |
  | sql.query   | SQLite 查询 | 只读 SQLite |
  | http.request| HTTP 请求  | **默认禁止**；需 `net.http` 权限或 `tool_net_http_enabled`，可选主机白名单 |
  | system.env  | 读环境变量 | **默认禁止**；需 `system.env` 权限或 `tool_system_env_enabled`，可选变量名白名单 |
  | vision.detect_objects | YOLO 目标检测 | 支持 yolov8/yolov11/onnx；输入 image（路径/base64）、confidence_threshold；输出 objects + 可选 annotated_image（base64） |
  | image.list_models | 列出文生图模型 | 返回可用 `image_generation` 模型及默认参数，供 Agent / Skill 侧选择模型 |
  | image.generate | 提交文生图任务 | 支持 prompt、negative_prompt、尺寸、steps、guidance、seed；支持默认模型选择与异步 job |
  | image.get_job | 查询图片任务 | 根据 `job_id` 查询状态、phase、结果、下载地址与缩略图 |
  | image.cancel_job | 取消图片任务 | 对运行中或排队中的文生图任务执行取消 |

- **Project Intelligence（项目智能分析）**
  - **静态工程认知引擎**：将项目从"文件集合"转换为"结构化工程模型"
  - **9 层数据模型**：Meta、Structure、Modules、Entry Points、Tests、Dependencies、Framework、Build、Risk Profile
  - **平台工具暴露**：`project.analyze` Tool 供 Agent 通过 Skill 调用
  - **语言支持**：Python、JavaScript/TypeScript、Go、Rust、Java、Kotlin（含 KMP）、C/C++（含 CMake）
  - **Kotlin Multiplatform 识别**：从 `build.gradle.kts` 提取多平台目标与 Source Sets（commonMain、jvmMain 等）
  - **CMake 解析**：从 `CMakeLists.txt` 提取项目名、执行文件、库、依赖、链接、包含目录
  - **快速分析**：基于正则的导入扫描（无 AST），毫秒级分析速度
- **安全与权限**
  - HTTP 工具：默认拒绝外网；`tool_net_http_enabled`、`tool_net_http_allowed_hosts` 可配置
  - 环境变量工具：与 system.info 分离，`tool_system_env_enabled`、`tool_system_env_allowed_names`、`tool_system_env_allow_all` 可配置
  - 集中校验见 `backend/core/plugins/builtin/tools/http/security.py`
- **调用关系**：Tool 仅通过 SkillExecutor 被 Agent 间接调用；ToolRegistry 作为「可被 Skill 绑定的能力池」

### 🎨 用户界面

- **路由**：聊天、智能体、技能、模型、知识库、日志、设置、**优化看板（/optimization）**；技能详情（/skills/:id）时主导航「SKILLS」正确高亮；模型配置（/models/:id/config）独立全屏页；**模型配置备份**（/settings/model-backup）与数据库备份（/settings/backup）分页，设置侧栏统一展示「Database Backup」「Model Config Backup」入口
- **文生图工作台**
  - `/images`：图片生成工作台，支持参数配置、Job Status、结果预览、Warmup 与取消
  - `/images/history`：历史列表，支持表格/卡片切换、筛选、搜索、排序、批量删除
  - `/images/jobs/:job_id`：任务详情页，展示状态、结果、下载与缩略图
- **国际化**：中英文、语言切换持久化，主要页面与组件覆盖（含智能体执行、Trace、技能、模型、日志等）
- **主题**：系统/亮色/暗色，语义化适配
- **聊天输入优化**：防止误触发送
  - 移除 Enter 键直接发送功能
  - 仅通过点击发送按钮提交消息
  - Enter 键仅用于换行
- **VLM 聊天**：VLM 模型支持图像上传、预览与发送；非 VLM 模型附加图像时提示「将按纯文本发送」
- **多模态消息处理**：修复了多模态消息合并时的错误，确保图像内容结构不被破坏
- **智能体页面**
  - 列表与搜索筛选
  - 创建/编辑/删除/执行
  - Trace 页
  - Skill 调用按对话顺序展示、可折叠
  - 空状态与加载态
  - 执行页支持文件上传（拖拽/选择），文件预览与删除
  - 支持 `vision.detect_objects` 的文件上传（显示上传入口）
  - Trace 页：vision.detect_objects 结果中含 `annotated_image` 时，单独展示标注图预览
  - **Intent Rules 配置**：创建/编辑页支持配置 `model_params.intent_rules`，添加/编辑/删除意图规则（keyword + skill_id + description）
- **Skills 页面**
  - 列表页：表格（名称、描述、分类、类型、状态）、搜索、分页、删除按钮
  - 创建/编辑/详情页：基本信息、逻辑模板、输入输出 Schema、执行规则
  - 国际化完整覆盖
- **模型页面**
  - 模型注册表视图：能力导航（LLM/VLM/ASR/Perception/Embedding/Image Generation），路由驱动筛选与分页
  - 二级侧栏可折叠，与系统导航并列
  - 本地模型「编辑 model.json」全屏配置页；运行时配置继续走侧边栏
  - 文生图模型支持 `/models/image-generation` 独立分类与配置编辑
- **智能体执行页 Tool Result 卡片**
  - 直接工具结果支持结构化卡片展示，不再直接向用户暴露原始 JSON
  - 图片任务结果可直接预览图片，并显示 `status / phase / model / size / latency`
  - 原始结果保留折叠查看入口，兼顾可读性与可调试性
- **性能优化**：模型选择器与分页；keep-alive；虚拟滚动优化长对话

### 📊 系统监控与设置

- **硬件看板**：CPU、GPU、VRAM、RAM（NVIDIA/Apple Silicon）；SSE 实时日志
- **平台设置**：离线模式、主题、推理引擎、上下文窗口、GPU Offload；模型目录可配置（默认 `~/.local-ai/models/`）
- **运行时设置**
  - `/settings/runtime` 支持按模型类型配置缓存上限（LLM / VLM / Image Generation）
  - `/api/system/config` 已增加白名单与字段级校验，避免无效配置静默写入
  - 设置页面支持保存失败提示与未保存变更提示（unsaved changes）
- **文生图设置**
  - `/settings/image-generation` 支持配置默认文生图模型，供图片工作台与 Agent 图片工具复用
- **资源管理**：模型加载状态监控，自动 VRAM 安全检查

### 🖼️ 图片生成（Image Generation）

- **统一 API**
  - `POST /api/v1/images/generate`：提交同步或异步图片生成任务
  - `GET /api/v1/images/jobs`、`GET /api/v1/images/jobs/{job_id}`：查询任务列表与详情
  - `POST /api/v1/images/jobs/{job_id}/cancel`、`DELETE /api/v1/images/jobs/{job_id}`：取消或删除任务
  - `GET /api/v1/images/jobs/{job_id}/file`、`GET /api/v1/images/jobs/{job_id}/thumbnail`：获取原图与缩略图
  - `POST /api/v1/images/warmup`、`GET /api/v1/images/warmup/latest`：预热与预热状态查询
- **任务治理**
  - 文生图任务采用独立 Job 模型、独立队列与独立并发控制
  - 支持排队、进度状态、历史分页、筛选、搜索、排序、批量删除
  - 结果默认落盘，支持缩略图懒生成与下载接口
  - Job 历史与 Warmup 状态已持久化到数据库
- **运行时与资源治理**
  - `MLXImageGenerationRuntime` 适配本地 Qwen Image 等 MLX 路径
  - `DiffusersImageGenerationRuntime` 适配 FLUX / FLUX.2 / SDXL 等标准 Diffusers 模型
  - 切换不同文生图模型时主动释放其他 image runtimes，降低统一内存竞争风险
  - Apple Silicon / MPS 路径支持 OOM 检测、回收与单次重试

### 💾 数据库备份系统

- **可扩展架构**
  - 策略模式设计：`BackupStrategy` 接口支持多种数据库类型
  - 当前实现：`SQLiteBackupStrategy`（文件快照备份）
  - 扩展预留：PostgreSQL、MySQL 逻辑备份，云存储备份（S3/MinIO）
- **备份功能**
  - 手动备份：即时创建数据库备份
  - 自动备份：支持应用启动时、每日、每周自动备份
  - 备份验证：WAL checkpoint 确保一致性，完整性检查
  - 备份历史：完整的备份元数据记录（时间、大小、类型、状态）
- **恢复功能**
  - 安全恢复：恢复前创建临时备份，失败自动回滚
  - 备份验证：恢复前验证备份文件有效性
  - 结构化结果：详细的恢复结果和错误信息
- **保留策略**
  - 自动清理：保留最近 N 个成功备份，自动删除旧备份
  - 配置化：保留数量可配置，备份文件和元数据同步删除
- **线程安全**
  - 串行执行：使用 `threading.Lock` 确保备份/恢复操作串行执行
  - 防止并发：禁止并发备份，避免数据库锁定冲突
- **Web UI**
  - 数据库状态展示：类型、路径、大小、最后备份时间、备份状态
  - 备份策略配置：启用状态、频率、保留数量、备份目录
  - 备份历史表格：日期、大小、类型、状态、操作（恢复/删除）
  - 手动操作：立即创建备份、恢复备份（带确认对话框）

### 🚀 开发与启动

- 根目录 Shell 脚本，自动 Conda 环境与依赖
- **可靠的资源清理机制**：程序关闭时自动卸载所有加载的模型，释放 GPU 内存和文件句柄
  - **完善的信号处理**：支持 SIGINT、SIGTERM、SIGHUP 信号，涵盖 Ctrl+C、kill 命令和终端关闭场景
  - **进程组管理**：脚本层使用负 PID 杀戮确保子进程树完全终止，避免孤儿进程
  - **优雅关闭**：利用 FastAPI lifespan 机制进行异步清理，避免信号处理器中的阻塞操作
  - **多重保障**：
    - atexit 兜底清理（进程正常退出但 lifespan 未执行时）
    - Llama.cpp 运行时增强清理（实例跟踪、显式资源释放）
    - Embedding Runtime (ONNX) 显式关闭机制（`close()` 方法 + 工厂缓存清理）
    - 前端页面卸载事件处理

---

### ⚠️ 已知问题 / 待修复

- **Agent + VLM 图像输入链路仍有缺口**
  - 直接调用 `/v1/vlm/generate` 的多模态链路已可用
  - 但在部分 Agent 路径中，聊天消息到统一 LLM 请求的转换仍可能丢失 `image_url`，导致 VLM 实际退化为纯文本生成
  - 该问题主要影响「Agent 调 VLM 解释图像」场景，不影响图片生成控制面与文生图工具链路

---

## 🔮 计划中功能

### Agent / Skill / Tool 演进

- **技能编排进阶**：Workflow 型 Skill 已支持顺序执行；计划：可视化编排、条件分支、多步链式配置
- **多智能体**：多智能体协同与自主规划 (Multi-Agent Workflow)
- **规划能力**：Agent Graph / Plan 生成与执行

### 工具与能力扩展

- **工具扩展**：网页爬虫、知识图谱、本地命令执行等
- **Skill 市场**：Skill 市场 / 模板库，可分享与导入的 Skill 定义

### 知识库与检索

- **分段优化**：长文本分段优化（滑动窗口、重叠策略）
- **混合搜索**：向量 + 全文检索
- **多模态**：多模态知识库（图片、音频）

### 模型与推理

- **云端接入**：云端模型统一接入（OpenAI/Claude/DeepSeek 等）
- **推理后端**：vLLM 推理后端
- **模型优化**：模型量化与优化（GGUF Q4/Q8）
- **VLM 扩展**：更多 VLM 后端（如 Ollama VLM）接入

---

本文档随开发进度更新，详细变更见 Git 提交历史。
