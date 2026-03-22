# 本地模型部署指南

本平台支持通过 **Manifest (model.json)** 机制实现本地模型的零代码部署。目前支持 `LLM (大语言模型)`、`Embedding (向量模型)`、`VLM (视觉语言模型)`、`Perception (视觉感知)` 与 `Image Generation (文生图 / 图像生成)` 五种类型。

## 1. 部署目录结构

为了更好地管理不同类型的模型，建议采用分层目录结构：

```text
~/.local-ai/models/
├── llm/                    # 存放语言模型 (GGUF 格式)
│   └── qwen2.5-7b/
│       ├── model.json
│       └── qwen2.5-7b.gguf
├── embedding/              # 存放向量模型 (ONNX/SafeTensors)
│   └── bge-m3/
│       ├── model.json
│       ├── model.onnx
│       └── tokenizer.json
├── vlm/                    # 存放视觉语言模型（llama.cpp 或 torch）
│   ├── Llava-v1.5-7B/      # llama.cpp VLM（GGUF）
│   │   ├── model.json
│   │   ├── llava-v1.5-7b-Q5_K_M.gguf
│   │   └── llava-v1.5-7b-mmproj-model-f16.gguf
│   └── Qwen3_5-9B/         # torch VLM（Transformers/SafeTensors）
│       ├── model.json
│       ├── config.json
│       ├── tokenizer.json
│       └── model-00001-of-0000N.safetensors
├── image_generation/       # 存放文生图模型（MLX / Diffusers）
│   ├── flux-dev/
│   │   ├── model.json
│   │   ├── model_index.json
│   │   ├── scheduler/
│   │   ├── text_encoder/
│   │   ├── text_encoder_2/
│   │   ├── tokenizer/
│   │   ├── tokenizer_2/
│   │   ├── transformer/
│   │   └── vae/
│   └── sdxl-base/
│       ├── model.json
│       ├── model_index.json
│       ├── scheduler/
│       ├── text_encoder/
│       ├── tokenizer/
│       ├── unet/
│       └── vae/
│   ├── Qwen-Image-2512-4bit/
│   │   ├── model.json
│   │   ├── configuration.json
│   │   ├── text_encoder/
│   │   ├── tokenizer/
│   │   ├── transformer/
│   │   └── vae/
│   └── FLUX_2-klein-4B/
│       ├── model.json
│       ├── model_index.json
│       ├── scheduler/
│       ├── text_encoder/
│       ├── tokenizer/
│       ├── transformer/
│       └── vae/
└── perception/            # 存放视觉感知模型（目标检测 / 实例分割）
    ├── yolov8/             # YOLO 目标检测（vision.detect_objects）
    │   ├── model.json
    │   └── yolov8s.pt
    ├── yolo11/
    │   ├── model.json
    │   └── yolo11s.pt
    └── cv_fastsam_image-instance-segmentation_sa1b/   # FastSAM 实例分割（vision.segment_objects）
        ├── model.json
        └── FastSAM-s.pt    # 或 pytorch_model.pt / FastSAM-x.pt
```

> **注**：系统也支持旧版的平铺结构（直接放在 `models/` 目录下），但强烈建议使用上述分层结构。

## 2. 配置文件说明 (`model.json`)

`model.json` 是模型部署的核心。每个模型目录**必须**包含此文件。

### 2.1 语言模型 (LLM) 示例
```json
{
  "model_id": "qwen2.5-7b",
  "name": "Qwen 2.5 7B",
  "model_type": "llm",
  "runtime": "llama.cpp",
  "format": "gguf",
  "path": "qwen2.5-7b.gguf",
  "capabilities": ["chat"],
  "description": "阿里云出品的 Qwen 2.5 7B",
  "metadata": {
    "n_ctx": 8192,
    "n_gpu_layers": 35
  }
}
```

### 2.2 向量模型 (Embedding) 示例
```json
{
  "model_id": "bge-m3",
  "name": "BGE M3",
  "model_type": "embedding",
  "runtime": "onnx",
  "path": "model.onnx",
  "capabilities": ["embedding"],
  "metadata": {
    "embedding_dim": 1024,
    "tokenizer": "tokenizer.json"
  }
}
```

### 2.3 视觉语言模型 (VLM) 示例
```json
{
  "model_id": "llava-v1.5-7b",
  "name": "LLaVA v1.5 7B",
  "model_type": "vlm",
  "runtime": "llama.cpp",
  "format": "gguf",
  "path": "llava-v1.5-7b-Q5_K_M.gguf",
  "capabilities": ["chat", "vision"],
  "description": "LLaVA v1.5 7B 视觉语言模型，支持图像理解和多模态对话",
  "metadata": {
    "modality": "vlm",
    "vlm_family": "llava-1.5",
    "mmproj_path": "llava-v1.5-7b-mmproj-model-f16.gguf",
    "context_length": 4096,
    "n_gpu_layers": 33,
    "n_threads": 8
  }
}
```
### 2.4 视觉语言模型 (Torch/Qwen3.5) 示例
```json
{
  "model_id": "qwen3.5-9b",
  "name": "Qwen 3.5 9B VLM",
  "model_type": "vlm",
  "runtime": "torch",
  "format": "safetensors",
  "path": "model-00001-of-00008.safetensors",
  "capabilities": ["chat", "vision"],
  "description": "Qwen3.5 多模态模型（本地 Torch 推理）",
  "metadata": {
    "modality": "vlm",
    "model_path": ".",
    "architecture": "qwen3.5",
    "device": "auto",
    "torch_dtype": "float16",
    "image_preprocess": {
      "max_image_side": 1280,
      "max_image_pixels": 1048576
    }
  }
}
```

### 2.5 语言模型 (LLM) MLX 示例
用于 **Apple Silicon** 上的 MLX 推理，模型为目录（内含 `config.json`、权重等）。`path` 填 `"."` 表示当前目录。

```json
{
  "model_id": "Mistral-7B-Instruct-4bit",
  "name": "Mistral 7B Instruct (4bit MLX)",
  "model_type": "llm",
  "runtime": "mlx",
  "format": "mlx",
  "path": ".",
  "capabilities": ["chat"],
  "description": "Mistral 7B 4bit 量化 MLX 版本",
  "metadata": {
    "context_length": 8192
  }
}
```

### 2.6 视觉感知模型 (Perception)：YOLO 目标检测 示例
用于 **vision.detect_objects** 工具，支持 YOLOv8 / YOLO11 / YOLO26 等。目录名建议为 `yolov8`、`yolo11`、`yolo26` 等（或 `YOLOv8`、`YOLO11`），便于自动发现。

```json
{
  "model_id": "yolov8s",
  "name": "YOLOv8 目标检测",
  "model_type": "perception",
  "runtime": "torch",
  "path": "yolov8s.pt",
  "capabilities": ["object_detection"],
  "description": "YOLOv8 目标检测（Ultralytics）",
  "metadata": {
    "task": "object_detection",
    "device": "auto",
    "confidence_threshold": 0.25
  }
}
```

### 2.7 视觉感知模型 (Perception)：FastSAM 实例分割 示例
用于 **vision.segment_objects** 工具，输出多实例彩色 mask + 轮廓。目录名可为 `cv_fastsam_image-instance-segmentation_sa1b`、`FastSAM`、`fastsam` 等。

```json
{
  "model_id": "cv_fastsam_image-instance-segmentation_sa1b",
  "name": "FastSAM 实例分割",
  "model_type": "perception",
  "runtime": "torch",
  "path": "FastSAM-s.pt",
  "capabilities": ["instance_segmentation"],
  "description": "Fast Segment Anything Model（Ultralytics），实例分割",
  "metadata": {
    "task": "instance_segmentation",
    "device": "auto",
    "confidence_threshold": 0.4
  }
}
```

- **path**：指向该目录下的 `.pt` 权重文件（如 `FastSAM-s.pt`、`FastSAM-x.pt` 或 `pytorch_model.pt`）。
- **MLX**：`path` 填 `"."` 表示模型目录即当前目录（Scanner 会写入该目录的绝对路径）；模型目录内需包含 mlx-lm 所需的 `config.json` 及权重文件。
- 若目录中无 `model.json`，可参考仓库内 `backend/core/runtimes/perception/fastsam_model.json.example` 复制后修改 `path`。

### 2.8 文生图模型 (Image Generation) 示例
用于 **文本生成图像**。当前平台建议按两类目录组织：
- **MLX 自定义目录**：如 Qwen Image，通常使用 `runtime: "mlx"`。
- **Diffusers 目录**：如 FLUX / SDXL，通常使用 `runtime: "diffusers"`，并包含 `model_index.json`。

当前平台已提供独立图片生成链路，包含：
- `POST /api/v1/images/generate`：同步或异步提交出图任务
- `GET /api/v1/images/jobs`、`GET /api/v1/images/jobs/{job_id}`：查询历史与任务详情
- `POST /api/v1/images/jobs/{job_id}/cancel`：取消任务
- `DELETE /api/v1/images/jobs/{job_id}`：删除任务历史
- `GET /api/v1/images/jobs/{job_id}/file`、`GET /api/v1/images/jobs/{job_id}/thumbnail`：下载原图与缩略图
- `POST /api/v1/images/warmup`、`GET /api/v1/images/warmup/latest`：运行时预热与最近一次预热状态

#### 2.8.1 FLUX / Diffusers 示例
推荐以 Diffusers 目录格式落盘；`path` 通常填写 `"."`，表示模型目录本身。

```json
{
  "model_id": "flux-dev",
  "name": "FLUX.1 Dev",
  "model_type": "image_generation",
  "runtime": "diffusers",
  "format": "safetensors",
  "path": ".",
  "capabilities": ["text_to_image"],
  "description": "FLUX 文生图模型（本地 Diffusers 推理）",
  "metadata": {
    "pipeline": "flux",
    "device": "auto",
    "torch_dtype": "bfloat16",
    "variant": "fp16",
    "default_width": 1024,
    "default_height": 1024,
    "default_num_inference_steps": 28,
    "default_guidance_scale": 3.5,
    "negative_prompt_supported": false,
    "max_width": 1536,
    "max_height": 1536
  }
}
```

SDXL 示例：

```json
{
  "model_id": "sdxl-base-1.0",
  "name": "SDXL Base 1.0",
  "model_type": "image_generation",
  "runtime": "diffusers",
  "format": "safetensors",
  "path": ".",
  "capabilities": ["text_to_image"],
  "description": "SDXL 文生图模型（本地 Diffusers 推理）",
  "metadata": {
    "pipeline": "stable-diffusion-xl",
    "device": "auto",
    "torch_dtype": "float16",
    "default_width": 1024,
    "default_height": 1024,
    "default_num_inference_steps": 30,
    "default_guidance_scale": 7.0,
    "negative_prompt_supported": true,
    "scheduler": "euler"
  }
}
```

#### 2.8.2 FLUX.2 [klein] 4B 示例
`FLUX.2 [klein] 4B` 与前面的 Qwen Image 不同：它是 **标准 Diffusers 目录模型**，包含 `model_index.json`，并显式声明 `_class_name = "Flux2KleinPipeline"`。因此应使用 `runtime: "diffusers"`，而不是 `mlx`。

```json
{
  "model_id": "flux-2-klein-4b",
  "name": "FLUX.2 [klein] 4B",
  "model_type": "image_generation",
  "runtime": "diffusers",
  "format": "safetensors",
  "path": ".",
  "capabilities": ["text_to_image"],
  "description": "FLUX.2 [klein] 4B 文生图模型（本地 Diffusers 推理）",
  "metadata": {
    "pipeline": "flux2-klein",
    "pipeline_class": "Flux2KleinPipeline",
    "device": "auto",
    "torch_dtype": "bfloat16",
    "default_width": 1024,
    "default_height": 1024,
    "max_width": 2048,
    "max_height": 2048,
    "default_num_inference_steps": 4,
    "default_guidance_scale": 1.0,
    "negative_prompt_supported": false,
    "scheduler": "FlowMatchEulerDiscreteScheduler",
    "supports_image_editing": true
  }
}
```

#### 2.8.3 Qwen Image / MLX 示例
Qwen Image 目录通常不带标准 Diffusers `model_index.json`，应按 MLX 自定义 pipeline 配置：

```json
{
  "model_id": "qwen-image-2512-4bit",
  "name": "Qwen Image 2512 4bit",
  "model_type": "image_generation",
  "runtime": "mlx",
  "format": "safetensors",
  "path": ".",
  "capabilities": ["text_to_image"],
  "description": "Qwen 文生图模型（MLX 4bit，本地推理）",
  "metadata": {
    "pipeline": "qwen-image",
    "model_path": ".",
    "device": "mps",
    "quantization": "4bit",
    "default_width": 1024,
    "default_height": 1024,
    "max_width": 1536,
    "max_height": 1536,
    "default_num_inference_steps": 28,
    "default_guidance_scale": 4.0,
    "negative_prompt_supported": true,
    "scheduler": "linear"
  }
}
```

建议：
- `path` 对文生图推荐填 `"."`，由 Runtime 以目录方式加载整个 Diffusers 模型。
- `pipeline` 建议显式声明，避免仅靠目录结构猜测 `flux` / `sdxl` / `sd15`。
- `pipeline_class` 建议在 Diffusers 目录模型中显式保留，便于区分 `FluxPipeline`、`Flux2KleinPipeline` 等不同 pipeline。
- `default_*` 用于 Web UI 默认表单值与 API 缺省参数，不建议把运行时请求参数硬编码在业务逻辑中。
- 若模型同时支持 **text-to-image** 与 **image editing / multi-reference editing**，当前 `capabilities` 仍建议先声明 `["text_to_image"]`；编辑类能力待独立 API 与运行时支持后再扩展。
- 当前平台会将图片结果落盘，并为历史记录生成缩略图；`result_json` 中不应依赖大块 base64 作为主展示方式。

### 2.9 核心字段详解
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `model_id` | String | 唯一 ID。注册后显示为 `local:llava-v1.5-7b` |
| `name` | String | UI 显示名称 |
| `model_type`| String | **必填**。可选值：`llm`, `embedding`, `vlm`, `perception`, **`image_generation`** |
| `runtime` | String | 运行环境。LLM 常用 `llama.cpp` 或 **`mlx`**（Apple Silicon），Embedding 常用 `onnx`，VLM 支持 `llama.cpp` 或 `torch`，Perception 为 `torch`，**Image Generation 可使用 `diffusers`（FLUX/SDXL）或 `mlx`（Qwen Image）** |
| `format` | String | 模型格式（如 `gguf`, `onnx`, `safetensors`，Perception 多为 `pytorch`，Image Generation 常为 `safetensors` + Diffusers 目录） |
| `path` | String | 模型主文件相对于 `model.json` 的路径 |
| `capabilities`| Array | 能力。LLM 设为 `["chat"]`，Embedding 设为 `["embedding"]`，VLM 设为 `["chat","vision"]`，Perception 为 `["object_detection"]` 或 `["instance_segmentation"]`，**Image Generation 设为 `["text_to_image"]`** |
| `metadata` | Object | **运行时特定参数**。VLM 类型推荐包含 `modality`；llama.cpp 可配置 `vlm_family/mmproj_path`；torch 可配置 `architecture/device/torch_dtype/image_preprocess`；Perception 需包含 `task`（`object_detection` / `instance_segmentation`）、可选 `device`、`confidence_threshold`；**Image Generation 推荐包含 `pipeline`，Diffusers 模型可补充 `pipeline_class/device/torch_dtype`，MLX 模型可补充 `model_path/quantization`，并统一声明 `default_width/default_height/default_num_inference_steps/default_guidance_scale`** |

## 3. 运行时特定参数 (Metadata)

### 3.1 llama.cpp (LLM/VLM)
- `context_length`: 上下文窗口大小（默认 4096）。
- `n_gpu_layers`: 卸载到 GPU 的层数。Mac 用户建议设为 `33+`（VLM）或 `35+`（LLM）。
- `n_threads`: 并行计算线程数。
- `verbose`: 是否输出详细日志（VLM 可设为 `false` 减少干扰）。
- **VLM 专用**：`vlm_family`（如 `llava-1.5`）、`mmproj_path`（mmproj 文件相对路径，LLaVA 等模型必填）。

### 3.2 mlx (LLM，Apple Silicon)
- `context_length`: 上下文窗口大小（可选，部分模型由 config 决定）。
- 模型路径为**目录**，`path` 填 `"."` 即可；需已安装 `mlx`、`mlx-lm`（仅 macOS 有意义）。

### 3.3 onnx (Embedding)
- `embedding_dim`: **必须**。向量维度（如 1024, 768）。
- `tokenizer`: 分词器配置文件名。
- `pooling`: 聚合方式（`mean`, `cls`，默认 `mean`）。

### 3.4 torch (VLM)
- `architecture`: 模型架构（如 `internvl3`、`qwen3.5`）。
- `device`: `auto/cuda/mps/cpu`。`auto` 按 `cuda -> mps -> cpu` 优先级选择。
- `torch_dtype`: 如 `float16`、`bfloat16`。
- `image_preprocess.max_image_side`: 输入图像最长边限制（推荐 1024~1536）。
- `image_preprocess.max_image_pixels`: 输入图像最大像素数限制（推荐 786432~1572864）。

说明：`max_image_side/max_image_pixels` 也支持放在 `model.json` 根级、`image_preprocess` 根级、或 `metadata` 根级；推荐统一放在 `metadata.image_preprocess`。

建议：
- 对 Torch VLM，优先把运行时参数统一放到 `metadata`，避免根级与 `metadata` 重复配置导致行为不一致。
- 在 CPU 环境下，建议不要使用 `float16`；优先 `float32`（平台运行时会在 CPU 下自动回退，文档建议也保持一致）。

### 3.5 torch (Perception：YOLO / FastSAM)
- `task`：**必填**。`object_detection`（YOLO 目标检测）或 `instance_segmentation`（FastSAM 实例分割）。
- `device`：`auto` / `cuda` / `mps` / `cpu`。`auto` 按 `cuda → mps → cpu` 选择。
- `confidence_threshold`：置信度阈值，默认 YOLO 常用 `0.25`，FastSAM 常用 `0.4`。

**对应工具**：
- `task: object_detection` → 使用 **vision.detect_objects**（多 backend 可选：yolov8 / yolov11 / yolov26 / onnx）。
- `task: instance_segmentation` → 使用 **vision.segment_objects**。

### 3.6 diffusers (Image Generation)
- 依赖：需已安装 `torch` 与 `diffusers`。
- `pipeline`：**建议必填**。如 `flux`、`stable-diffusion-xl`、`stable-diffusion-v1`。用于 Runtime 选择正确的 pipeline builder。
- `pipeline_class`：可选但推荐。用于显式声明 Diffusers pipeline 类型，如 `FluxPipeline`、`Flux2KleinPipeline`。
- `device`：`auto` / `cuda` / `mps` / `cpu`。`auto` 按 `cuda → mps → cpu` 选择。
- `torch_dtype`：如 `float16`、`bfloat16`、`float32`。Apple Silicon 建议优先 `float16`；FLUX on CUDA 通常可用 `bfloat16`。
- `variant`：可选。用于区分 `fp16` 等变体权重。
- `default_width` / `default_height`：默认出图分辨率。建议 SDXL / FLUX 默认 1024x1024。
- `max_width` / `max_height`：可选。用于限制请求尺寸，避免 UI 或 API 传入超大分辨率导致 OOM。
- `default_num_inference_steps`：默认采样步数。推荐 20~32。
- `default_guidance_scale`：默认 guidance。FLUX 一般较低（如 3.5），SDXL 一般更高（如 5~8）。
- `negative_prompt_supported`：是否支持负向提示词。FLUX 一般建议 `false`，SDXL 通常为 `true`。
- `scheduler`：可选。用于指定默认 scheduler，如 `euler`、`ddim`、`dpmpp_2m`。
- Apple Silicon / MPS 下切换不同文生图模型时，平台会优先释放其他已缓存的 `image_generation` runtime，并在遇到 `MPS backend out of memory` 时尝试一次强制回收后重试。

### 3.7 mlx (Image Generation，Apple Silicon)
- 依赖：需已安装 `mflux`；当前主路径用于 Qwen Image 类目录模型。
- `pipeline`：**建议必填**。当前典型值如 `qwen-image`。
- `model_path`：推荐填 `"."`，表示运行时按整个目录加载。
- `device`：通常为 `mps`。
- `quantization`：如 `4bit`。
- `default_width` / `default_height`：默认出图分辨率。
- `max_width` / `max_height`：可选。限制 UI 或 API 可提交的最大分辨率。
- `default_num_inference_steps`：默认采样步数。
- `default_guidance_scale`：默认 guidance。
- `negative_prompt_supported`：Qwen Image 这类模型通常可设为 `true`。
- `scheduler`：如 `linear`。
- 与 Diffusers 模型切换时，平台会主动释放其他文生图 runtime，以降低统一内存残留导致的 MPS OOM 风险。

建议：
- 文生图模型与 VLM 必须分开建模。**VLM 是图像输入、文本输出；Image Generation 是文本输入、图像输出**，不要共用同一个 `model_type`。
- 文生图模型尽量按目录整体部署，不建议只指向单个 `.safetensors` 文件后再依赖隐式目录推断。
- `task: instance_segmentation` → 使用 **vision.segment_objects**（多实例彩色 mask + 轮廓标注图）。

模型路径与 backend 的解析顺序：优先读取 `perception/` 下对应子目录中的 `model.json`（与 LocalScanner 一致）；若配置了 UI 或环境变量中的显式路径，则优先使用该路径。

## 4. 部署步骤

1. **准备目录**：
   如果目录不存在，请手动创建：
   ```bash
   mkdir -p ~/.local-ai/models/my-model
   ```

2. **放置文件**：
   将 `.gguf` 文件移动到该目录下。

3. **编写配置**：
   在该目录下创建 `model.json` 并填写上述模板。

4. **重启后端**：
   重启后端服务。系统会在启动时通过 `LocalScanner` 自动扫描并注册该模型。

5. **验证**：
   打开平台 UI，在模型选择下拉框中，你应该能看到带有 `Local` 标识的新模型。
   对于 VLM 模型，还可以通过 `/api/v1/vlm/generate` 接口进行图像理解测试。

## 5. 模型配置文件备份 (model.json)

平台对本地模型的 `model.json` 提供备份与恢复能力，便于在修改或误删后回滚。

### 5.1 备份路径与目录结构

- **备份根目录**：由配置项 `model_json_backup_directory` 指定；未配置时默认为 **`backend/data/backups`**（与数据库备份并列，其下再分子目录 `model_json/`）。
- **目录结构**：
  ```text
  <backup_root>/
  └── model_json/
      ├── index/
      │   └── model_backup_index.jsonl   # 变更索引（每条记录对应一次创建/恢复）
      ├── snapshots/
      │   └── <model_id_safe>/           # 按模型 ID 安全化后的子目录
      │       └── model_<safe>_<yyyyMMddTHHmmssZ>_<hash8>.json
      └── manifests/                     # 每日全量清单（阶段 2）
          └── <yyyyMMdd>.json
  ```
- **model_id 安全化**：`model_id` 中的 `:`、`/` 等会替换为 `_`，仅保留 `[a-zA-Z0-9_.-]`。例如 `local:qwen3.5-27b-mlx-4bit` → 目录名 `local_qwen3.5-27b-mlx-4bit`。

**新/旧快照目录说明**：为避免安全化后不同 `model_id` 撞目录（如 `a/b` 与 `a_b` 同变为 `a_b`），当前实现采用 **新布局** `snapshots/<model_id_safe>_<id8>/`，其中 `id8` 为 `sha256(model_id)` 的前 8 位，保证目录唯一。在此之前已产生的备份仍在 **旧布局** `snapshots/<model_id_safe>/` 下。列表、恢复、删除、保留策略会同时查找新目录与旧目录，旧备份无需迁移即可继续使用；新创建的备份一律写入新目录。

### 5.2 备份方式

| 方式 | 入口 | 说明 |
|------|------|------|
| **单模型备份** | 设置 → 模型配置备份 → 选择本地模型 →「创建备份」 | 仅对所选模型的当前 `model.json` 创建一份快照 |
| **单模型备份（快捷）** | 模型页 → 打开某本地模型 → 配置侧栏「备份 model.json」 | 对当前打开的本地模型一键创建快照 |
| **全量快照** | 设置 → 模型配置备份 →「立即全量快照」 | 对所有已扫描的本地模型各创建一份快照 |
| **定时全量** | 配置 `model_json_backup_daily_enabled`、`model_json_backup_daily_time` | 按设定时间每日自动全量快照并写每日 manifest |

### 5.3 备份策略与保留

- **索引**：每次创建或恢复都会在 `model_backup_index.jsonl` 中追加一条记录（含 `backup_id`、`model_id`、`backup_file`、`timestamp_utc`、`action`、`reason` 等），用于列表展示与恢复时定位快照文件。
- **保留策略**（阶段 2）：支持按时间保留（如 7 天内全部保留、30 天内每日保留、180 天内每周保留），通过「保留策略 dry-run」预览、「清理」执行删除；可在设置页模型配置备份中操作。
- **批量恢复**：可按目标时间点将多个模型（或全部）恢复至该时间点前的最近一次备份。

### 5.4 如何确认备份成功

- **列表中若有该模型的记录**（含 backup_id、时间），即表示该次备份已成功；快照文件位于 `<backup_root>/model_json/snapshots/` 下（新备份在 `<model_id_safe>_<id8>/`，旧备份可能在 `<model_id_safe>/`，见上文新/旧快照目录说明）。
- 单模型备份成功后，弹窗会提示 **文件位置**：`<backup_root>/model_json/<storage_path>`，便于在磁盘上核对。
- 默认根目录为项目下的 **`backend/data/backups`**，可在该目录下 `model_json/snapshots/` 中按模型子目录查找对应 `.json` 文件。

### 5.5 恢复

- 在「模型配置备份」页的备份列表中，对某条记录点击「恢复」；按提示输入 backup_id 确认后，将把该快照写回对应模型的 `model.json`（恢复前会对当前版本再做一次保护性备份）。
- 批量恢复：选择目标日期并可选指定模型列表，执行后将这些模型回滚到该时间点前的最近备份。

## 6. 常见问题

- **模型未显示**：检查 `model.json` 格式是否正确（必须是合法的 JSON），以及 `path` 指向的文件是否存在。
- **加载失败**：确保已在 Conda 环境中安装了 `llama-cpp-python` 依赖。
- **运行缓慢**：llama.cpp 检查 `n_gpu_layers`；torch 检查 `device` 是否命中 GPU/MPS，并适当降低 `max_tokens`。
- **VLM 推理失败（Invalid buffer size）**：通常是图像分辨率过大导致视觉注意力内存爆炸。请在 `metadata.image_preprocess` 中设置 `max_image_side` 与 `max_image_pixels`。
- **InternVL3 加载失败（`Tensor.item() cannot be called on meta tensors`）**：
  - 常见于 `transformers>=5` 与部分 InternVL3 remote code 的初始化兼容问题。
  - 请确保使用项目当前后端版本（已包含 InternVL3 兼容加载逻辑），并重启后端。
- **InternVL3 输出乱码/重复字符**：
  - 先确认运行设备与精度：CPU 环境建议 `torch_dtype=float32`。
  - 建议新建会话复测，避免旧会话历史干扰。
- **Perception（YOLO / FastSAM）未生效**：
  - 确认 `perception/` 下对应子目录中存在 `model.json`，且 `path` 指向的 `.pt` 文件存在。
  - 目标检测依赖 `ultralytics`（见 `requirements.txt`）；实例分割同样使用 Ultralytics 的 FastSAM。
  - 若使用 UI 或环境变量配置了显式模型路径，将优先于 `model.json` 的路径。
- **模型配置备份未找到模型**：单模型备份依赖「数据目录」下能扫描到该模型的 `model.json`。请确认设置 → 通用 → 数据目录 包含该模型所在路径，并在模型页执行过「扫描模型」；错误提示中会包含当前搜索目录便于核对。
