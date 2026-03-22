# 本地模型部署设计文档

## 1. 背景与目标

随着本地算力（Apple Silicon、NVIDIA GPU）和隐私/离线推理需求的提升，平台通过 **Manifest 驱动** 的本地模型方案，支持多种格式与运行时，并与现有 Agent、聊天、知识库等能力集成。

**目标**：
- **零代码接入**：用户放置模型文件并编写 `model.json` 即可完成部署。
- **多类型支持**：LLM（大语言）、Embedding（向量）、VLM（视觉语言）、ASR、Perception、Image Generation（文生图）等。
- **多后端可选**：LLM/VLM 支持 `llama.cpp`（GGUF）与 `torch`（Transformers），Embedding 支持 ONNX，文生图支持 `diffusers` 与 `mlx`。

## 2. 核心架构

整体将模型生命周期划分为 **扫描 → 注册 → 执行** 三阶段，由统一描述符与运行时工厂衔接。

### 2.1 模型元数据 (ModelDescriptor)

模型在系统内由 `ModelDescriptor` 统一描述，主要字段包括：

| 字段 | 说明 |
|------|------|
| `id` | 全局唯一标识，本地模型为 `local:{model_id}` |
| `model_type` | 类型：`llm`、`embedding`、`vlm`、`asr`、`perception`、`image_generation` |
| `runtime` | 执行引擎：`llama.cpp`、`torch`、`onnx`、`diffusers`、`mlx` 等 |
| `capabilities` | 能力标签，如 `["chat"]`、`["chat","vision"]`、`["embedding"]`、`["object_detection"]`、`["instance_segmentation"]`、`["text_to_image"]` |
| `metadata` | 运行时专用参数（路径、上下文长度、GPU 层数、architecture、Perception 的 task/device/confidence_threshold、Image Generation 的 pipeline/device/torch_dtype/default_width 等） |

本地模型的 `metadata.path` 由 Scanner 解析为**主权重文件的绝对路径**，供各 Runtime 加载。

### 2.2 自动发现 (LocalScanner)

`LocalScanner` 在启动时扫描配置的模型根目录（默认来自系统设置 `dataDirectory` 或配置中的 `local_model_directory`）：

- **分层目录**：优先扫描 `llm/`、`embedding/`、`vlm/`、`asr/`、`perception/`、`image_generation/` 下各子目录。
- **Manifest 驱动**：每个模型目录必须包含 `model.json`；`path` 为相对该目录的主文件路径，Scanner 会将其转为绝对路径写入 `metadata.path`。
- **平铺兼容**：根目录下含 `model.json` 的子目录也会被扫描（与分层不重复），兼容旧版平铺结构。

### 2.3 注册中心 (ModelRegistry)

扫描得到的 `ModelDescriptor` 写入 `ModelRegistry`（SQLite 持久化），用于：
- 模型列表与筛选（含 Tags、能力）。
- 聊天/Agent/VLM 等接口按 `model_id` 查找并选择对应 Runtime。

## 3. 运行时 (Runtime)

### 3.1 LLM

- **runtime**：`llama.cpp`
- **实现**：`LlamaCppRuntime`，基于 `llama-cpp-python`，加载 GGUF。
- **行为**：异步通过 `anyio.to_thread.run_sync` 封装同步推理；内置 ChatML / Llama3 等 prompt 模板与停止词；支持 `n_ctx`、`n_gpu_layers` 等 metadata。

### 3.2 Embedding

- **runtime**：`onnx`
- **实现**：`OnnxEmbeddingRuntime`，按 metadata 中的 `embedding_dim`、`tokenizer` 等加载 ONNX 与分词器。

### 3.3 VLM（视觉语言模型）

支持两种后端，由 `model.json` 的 `runtime` 决定：

| runtime | 格式 | 实现 | 典型模型 |
|---------|------|------|----------|
| `llama.cpp` | GGUF + mmproj | `LlamaCppVLMRuntime` | LLaVA、Qwen2.5-VL（GGUF） |
| `torch` | SafeTensors / HuggingFace | `TorchVLMRuntime` | InternVL、Qwen2-VL、Qwen3-VL、Qwen 3.5 |

- **llama.cpp VLM**：需在 metadata 中提供主 GGUF 路径及 `mmproj_path`（视觉编码器）、`vlm_family` 等，由 `LlamaCppVLMRuntime` 构建 chat handler（如 Llava15、Qwen25VL）。
- **Torch VLM**：按 `architecture` 选择 Adapter（`InternVLAdapter`、`QwenVLAdapter`）。`architecture` 可从 `model.json` 的 `architecture` 或 `metadata.architecture` 读取，缺省时由模型目录下 `config.json` 的 `model_type` 推断（如 `qwen3_5` → `qwen3.5`）。Qwen 3.5 需使用 `Qwen3_5ForConditionalGeneration`（transformers ≥ 5.2.0）。

### 3.4 Perception（视觉感知：YOLO / FastSAM）

- **runtime**：`torch`
- **实现**：`TorchPerceptionRuntime`，根据 `metadata.task` 选择适配器：
  - **object_detection**：`YoloObjectDetectionAdapter`（Ultralytics YOLO），用于 **vision.detect_objects** 工具；支持多 backend（yolov8 / yolov11 / yolov26 / onnx），路径可由 `perception/` 下各子目录的 `model.json` 或 UI/环境变量解析。
  - **instance_segmentation**：`FastSAMAdapter`（Ultralytics FastSAM），用于 **vision.segment_objects** 工具；输出多实例 mask + 可选彩色标注图（每实例一色 + 轮廓）。
- **行为**：统一接口 `detect(image_input, options) -> DetectionResult`；DetectionResult 含 `objects`（label、confidence、bbox，实例分割时含可选 mask base64）与 `image_size`。模型按 `model_id` 在 RuntimeFactory 中缓存，Tool 层通过 backend 路由或 Factory 获取已加载的 Perception Runtime。
- **Manifest**：`model_type: perception`，`capabilities` 为 `["object_detection"]` 或 `["instance_segmentation"]`（Scanner 可根据 `metadata.task` 自动补全）；`metadata` 需包含 `task`，可选 `device`、`confidence_threshold`。

### 3.5 异步与实例管理

- **LLM**：同步推理经 `to_thread` 桥接到异步，避免阻塞事件循环；模型实例按路径缓存，减少重复加载。
- **VLM**：VLM Runtime 按模型 id 缓存，初始化时加载权重与 processor；Torch VLM 的 `generate`/`chat` 在线程池中执行。
- **Perception**：同步推理，TorchPerceptionRuntime 按 `model_id` 在 Factory 中缓存；YOLO/FastSAM 的 `detect` 在 Tool 的 async 上下文中通过 `to_thread` 或 backend 同步调用。
- **Image Generation**：出图通常耗时更长、显存更重，建议单独的 Runtime 缓存与并发治理；图片生成过程应走异步任务或线程池，不与聊天请求共用轻量推理通道。

### 3.6 Image Generation（文生图）

当前平台的文生图目录主要分两类：

| 子类型 | runtime | 目录特征 | 典型模型 |
|--------|---------|----------|----------|
| MLX 自定义 pipeline | `mlx` | 不一定带 `model_index.json`，通常是自定义目录与权重组织 | Qwen Image |
| Diffusers pipeline | `diffusers` | 带 `model_index.json`，可从 `_class_name` 识别 pipeline class | FLUX.1-dev、FLUX.2 [klein] 4B、SDXL Base、SD 1.5 |

- **当前实现**：
  - `DiffusersImageGenerationRuntime`
  - `MLXImageGenerationRuntime`
  - `RuntimeFactory` 已支持 `image_generation + diffusers` 与 `image_generation + mlx`

当前输入输出契约：
- **输入**：`prompt`、可选 `negative_prompt`、`width`、`height`、`num_inference_steps`、`guidance_scale`、`seed`
- **输出**：结果对象 + 落盘文件路径 + 下载接口；主路径已支持任务化执行、历史记录、缩略图与 warmup

设计原则：
- **不要复用 VLM 类型**：VLM 是 `image -> text`，文生图是 `text -> image`，二者的 API 语义、缓存策略、UI 形态都不同。
- **Manifest 明确声明 pipeline**：例如 `qwen-image`、`flux`、`flux2-klein`、`stable-diffusion-xl`、`stable-diffusion-v1`，避免仅凭目录名或权重文件名猜测。
- **Diffusers 目录模型建议保留 `pipeline_class`**：例如 `FluxPipeline`、`Flux2KleinPipeline`。对于带 `model_index.json` 的目录，可从 `_class_name` 推断并回填到 `metadata.pipeline_class`。
- **路径按目录加载**：对 Diffusers 目录模型，`path` 推荐填 `"."`，Runtime 以目录整体加载，而不是仅把某个 `.safetensors` 当成唯一入口。
- **结果与会话解耦**：文生图结果可以返回图片引用，但不应强行塞入标准 Chat token 流；建议提供独立图片生成 API 与独立响应 schema。
- **资源治理单独处理**：文生图通常比 LLM 占用更大的显存与执行时间。当前实现已接入独立任务队列、pending 上限、取消、warmup、按 `image_generation` 类型单独缓存上限，以及切换图片模型时主动释放其他文生图 runtime。
- **编辑能力先作为 metadata 保留**：像 FLUX.2 [klein] 这类模型同时支持 `text-to-image` 与 `image editing`。当前平台主路径仍以 `text_to_image` 为准，编辑能力建议先记录在 `metadata.supports_image_editing`，待独立 API 和运行时完成后再提升为正式 capability。

当前图片任务控制面能力：
- 异步 job 模式：提交、轮询、取消、删除
- 任务历史持久化：数据库保存 job 元信息与结果引用
- 文件落盘：原图与缩略图单独存储
- warmup：支持预热并记录最近一次 warmup 状态
- 进度回填：运行阶段可回写 `current_step / total_steps / progress`
- 结果下载：原图与缩略图独立接口

当前资源治理实现：
- 图片任务走独立 queue，不与聊天轻量请求通道混用
- `runtime_max_cached_local_image_generation_runtimes` 单独控制图片 runtime 缓存上限
- 切换文生图模型前，会主动释放其他已缓存的 `image_generation` runtime
- Apple Silicon / MPS 下，若加载 Diffusers 模型时出现 OOM，会先强制回收其他图片 runtime，再重试一次
- 历史查询默认不回传整块 base64，优先通过文件与缩略图接口展示

建议的 metadata 约定：
- `pipeline`: `qwen-image` / `flux` / `flux2-klein` / `stable-diffusion-xl` / `stable-diffusion-v1`
- `pipeline_class`: 如 `FluxPipeline` / `Flux2KleinPipeline`
- `device`: `auto` / `cuda` / `mps` / `cpu`
- `torch_dtype`: `float16` / `bfloat16` / `float32`
- `variant`: 如 `fp16`
- `default_width` / `default_height`
- `max_width` / `max_height`
- `default_num_inference_steps`
- `default_guidance_scale`
- `negative_prompt_supported`
- `scheduler`
- `model_path`：MLX 目录模型可填写 `"."`
- `quantization`：MLX 目录模型可标记 `4bit` 等量化方式
- `supports_image_editing`：是否具备编辑 / 多参考编辑能力

建议的 API 边界：
- **聊天 / Agent / Workflow 中的文生图节点**：通过统一推理网关调用独立图片生成接口，而不是复用 `/chat/completions` 或 `/v1/vlm/generate`。
- **当前已实现**：
  - `POST /api/v1/images/generate`
  - `GET /api/v1/images/jobs`
  - `GET /api/v1/images/jobs/{job_id}`
  - `POST /api/v1/images/jobs/{job_id}/cancel`
  - `DELETE /api/v1/images/jobs/{job_id}`
  - `GET /api/v1/images/jobs/{job_id}/file`
  - `GET /api/v1/images/jobs/{job_id}/thumbnail`
  - `POST /api/v1/images/warmup`
  - `GET /api/v1/images/warmup/latest`

## 4. 设计要点小结

- **Manifest 即契约**：`model.json` 声明 `model_type`、`runtime`、`path`、`capabilities` 与 `metadata`，无需改代码即可接入新模型。
- **Runtime 与类型解耦**：由 `RuntimeFactory` 根据 `model_type` + `runtime` 选择具体实现（含 VLM 的 builder 注册、Perception 的 task → Adapter 映射、Image Generation 的 pipeline builder），便于扩展新后端。
- **路径与配置**：Scanner 统一把相对 `path` 解析为绝对路径并写入 metadata；Torch VLM 的 `model_dir` 可由 `metadata.path` 的父目录推导；Perception 的模型路径可由 `perception/` 下子目录的 `model.json` 解析；Image Generation 既支持 MLX 目录模型（如 Qwen Image），也支持 Diffusers 目录模型（如 FLUX.2 [klein]、SDXL），均由 `image_generation/` 下子目录整体加载。
- **多模态与多架构**：VLM 通过 architecture + Adapter 支持多系列（InternVL、Qwen2-VL、Qwen3-VL、Qwen 3.5）；Perception 通过 task + Adapter 支持目标检测（YOLO）与实例分割（FastSAM）；Image Generation 通过 pipeline / pipeline_class 支持 Qwen Image（MLX）、FLUX / FLUX.2 [klein] / SDXL / SD1.5 等图片生成模型，且当前已具备独立工作台、历史页、详情页与运行控制能力。

## 5. 模型配置文件备份 (model.json)

- **目的**：对本地模型目录下的 `model.json` 做快照与恢复，避免误改或误删后无法回滚；与数据库备份（`/api/backup`）并列，API 前缀为 `/api/model-backups`。
- **备份路径**：备份根目录由配置项 `model_json_backup_directory` 指定，默认 **`backend/data/backups`**；其下固定子结构为 `model_json/snapshots/<model_id_safe>/`（快照文件）、`model_json/index/model_backup_index.jsonl`（索引）、`model_json/manifests/`（每日清单）。`model_id` 安全化规则：`:`、`/` 等替换为 `_`，仅保留 `[a-zA-Z0-9_.-]`。
- **策略与能力**：支持单模型备份（设置页选择模型或模型配置侧栏一键）、全量快照、定时全量、按时间点批量恢复、保留策略（dry-run 与清理）。索引与快照写入采用临时文件 + fsync + 原子 rename，恢复前对当前版本做保护性备份。
- **与部署的关系**：备份解析 `model.json` 路径时使用与 LocalScanner 相同的「数据目录」（`dataDirectory` 或 `local_model_directory`），因此只有已被扫描并出现在模型列表中的本地模型才能被单模型备份；列表中的备份记录与磁盘上的快照文件一一对应，列表有记录即表示该次备份已成功写入文件。
