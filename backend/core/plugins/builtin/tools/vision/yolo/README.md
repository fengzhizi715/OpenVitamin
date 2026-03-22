# vision.detect_objects

YOLO 目标检测 Tool。感知工具，仅返回结构化 JSON，不生成自然语言。

实现位于 `core/tools/yolo/`，支持多 backend 路由（yolov8 / yolov11 / onnx）。

## 输入

- `image`: base64 data URL 或 workspace 内文件路径
- `confidence_threshold`: 置信度阈值（可选，默认 0.25）
- `backend`: 高级参数，可选 yolov8 / yolov11 / onnx，默认 yolov8

## 输出

```json
{
  "objects": [
    {"label": "person", "confidence": 0.98, "bbox": [0.12, 0.08, 0.45, 0.92]}
  ],
  "image_size": [1280, 720]
}
```

## 配置

- `yolo_model_path`: 模型路径（可选，显式配置时文件不存在会抛错）
- `yolo_device`: 运行设备（cpu / cuda / mps / auto，auto 自动选择）
- `yolo_default_backend`: 默认 backend（yolov8 / yolov11 / onnx）

配置来源优先级：1) yolo_model_path  2) perception/model.json  3) 默认路径 + 扫描  
模型根目录与 LocalScanner 一致：dataDirectory 或 local_model_directory
