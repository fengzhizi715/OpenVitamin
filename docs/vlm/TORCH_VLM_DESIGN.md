# TorchVLMRuntime 设计文档

## 一、统一 Runtime 抽象

### VLMRuntime 接口（与现有 vlm_runtime.py 对齐）

```
- initialize(model_path, **kwargs)  # 加载模型
- infer(image, prompt, temperature, max_tokens, **kwargs) -> str  # 单图+文本，兼容现有 API
- generate(VLMRequest) -> VLMResponse  # 完整 messages + 多图
- unload()
- is_loaded, model_info
- health()  # 可选
```

### VLMRequest

```python
messages: List[Dict]  # role: system|user|assistant, content: str | [{"type":"text"|"image_url", ...}]
images: Optional[List[path|bytes|PIL.Image]]  # 当 content 未内联 image_url 时按序对应
generation_config: { max_tokens, temperature, top_p, stop }
```

### VLMResponse（与 llama.cpp 一致）

```python
id, object="chat.completion", created, model
choices: [{"message": {"role":"assistant","content":"..."}, "finish_reason":"stop"}]
usage: {"prompt_tokens", "completion_tokens", "total_tokens"}
```

---

## 二、TorchVLMRuntime 架构

```
TorchVLMRuntime
    ├── ModelAdapter (抽象)
    │   ├── InternVLAdapter (支持 internvl, internvl2, internvl3)
    │   └── QwenVLAdapter (支持 qwen-vl, qwen2-vl, qwen3-vl)
    └── manifest (model.json) → 选择 Adapter
```

- Runtime 不感知具体模型结构，仅依赖 `manifest.architecture` 选择 Adapter
- 当前支持的架构：
  - `internvl`, `internvl2`, `internvl3` → InternVLAdapter
  - `qwen-vl`, `qwen2-vl`, `qwen3-vl` → QwenVLAdapter
- 新模型（MiniCPM-V、Phi-3-V、CogVLM）只需新增 Adapter，注册到 `_ADAPTER_REGISTRY`

---

## 三、ModelAdapter 职责

1. **load(model_dir, options)**：加载 tokenizer / model / processor
2. **generate(messages, images, max_tokens, temperature, top_p, stop)**：推理
3. **unload()**：释放资源

---

## 四、Image + Text 统一处理逻辑

### 输入格式

- **messages**：OpenAI 风格，`content` 可为：
  - `str`：纯文本
  - `[{"type":"text","text":"..."}, {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}]`
- **images**：`[path, bytes, PIL.Image]`，当 content 中未内联 base64 时使用

### 映射规则

1. 遍历 messages，对每个 `content`：
   - 若为 array，遍历 item：
     - `image_url` 且 `url` 以 `data:` 开头 → base64 解码为 PIL
     - `image_url` 无 data → 从 `images` 按序取一张
   - 若为 str 且 `images` 有剩余 → 将首条 user 消息改为 `[image1,...,imageN, text]`
2. 输出：`(pil_images, processed_messages)`，供 Adapter 调用 processor

### InternVL

- `processor.apply_chat_template(messages)` 或手动拼接
- 图像放在 user content 中：`[{"type":"image","image":PIL}, {"type":"text","text":"..."}]`
- `processor(text=..., images=...)` 或 `processor(images=..., text=...)`

### Qwen-VL

- `processor.apply_chat_template(messages)` 构建多模态输入
- 支持多图、多轮对话
- `processor(text=[...], images=[...])`

---

## 五、Manifest (model.json) 扩展

```json
{
  "model_id": "internvl3-2b",
  "name": "InternVL3-2B",
  "model_type": "vlm",
  "runtime": "torch",
  "architecture": "internvl3",
  "model_name": "OpenGVLab/InternVL3-2B",
  "torch_dtype": "float16",
  "device": "auto",
  "vision": {
    "image_size": 448,
    "patch_size": 14
  },
  "metadata": {
    "modality": "vlm"
  }
}
```

**字段说明**：
- `model_type`: 必须为 `"vlm"`（与现有 manifest 兼容）
- `runtime`: 必须为 `"torch"`
- `architecture`: 支持的架构：
  - `internvl`, `internvl2`, `internvl3` → InternVLAdapter
  - `qwen-vl`, `qwen2-vl`, `qwen3-vl` → QwenVLAdapter
- `model_name`: HuggingFace 模型 ID 或本地路径（相对于 model.json 的目录）
- `torch_dtype`: `float16`, `bfloat16`, `float32` 等
- `device`: `auto`, `cuda`, `cpu`, `mps` 等
- `vision`: 可选的视觉配置（image_size, patch_size 等）

---

## 六、与 llama.cpp 行为对齐

- messages 语义一致
- image 插入位置一致（user content 中）
- generation 参数：max_tokens, temperature, top_p, stop
- VLMResponse 结构一致

---

## 七、可扩展性

新增 MiniCPM-V：

1. 创建 `minicpm_v_adapter.py`，实现 `ModelAdapter`
2. 在 `torch_vlm_runtime.py` 的 `_ADAPTER_REGISTRY` 添加 `"minicpm-v": MiniCPMVAdapter`
3. manifest 中 `architecture: "minicpm-v"`

无需修改 Runtime 主体。
