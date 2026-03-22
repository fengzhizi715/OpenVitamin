"""
YoloObjectDetectionAdapter: YOLOv8 目标检测适配器

仅做感知，输出结构化数据，不参与对话、不生成自然语言。
"""

from __future__ import annotations

from typing import List, Literal

from ..models.detection_result import DetectedObject
from log import logger


DeviceType = Literal["cpu", "cuda", "mps"]


class YoloObjectDetectionAdapter:
    """YOLOv8 目标检测适配器"""

    def __init__(self, model_path: str, device: str = "cpu"):
        self._model_path = model_path
        self._device = self._resolve_device(device)
        self._model = None

    def _resolve_device(self, device: str) -> str:
        import torch
        if device == "cuda" and not torch.cuda.is_available():
            return "cpu"
        if device == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            return "cpu"
        return device

    def load(self) -> None:
        import torch
        """加载 YOLO 模型"""
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO
        except ImportError:
            raise ImportError("ultralytics 未安装，请执行: pip install ultralytics")
        self._model = YOLO(self._model_path)
        self._model.to(self._device)

    @staticmethod
    def _is_mps_oom_error(err: Exception) -> bool:
        msg = str(err).lower()
        return "mps backend out of memory" in msg or ("mps" in msg and "out of memory" in msg)

    @staticmethod
    def _cleanup_torch_cache() -> None:
        try:
            import torch
            if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
                torch.mps.empty_cache()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def detect(
        self,
        image_tensor: torch.Tensor,
        conf_threshold: float = 0.25,
    ) -> List[DetectedObject]:
        """
        执行目标检测。

        Args:
            image_tensor: (1, C, H, W) float32 0~1
            conf_threshold: 置信度阈值

        Returns:
            list[DetectedObject]，bbox 已归一化 (0~1)
        """
        self.load()
        _, _, h, w = image_tensor.shape
        img_size = (w, h)

        # ultralytics 接受 numpy (H,W,C) 或 tensor，此处转为 numpy 便于兼容
        # 格式: (1,C,H,W) float 0~1 -> (H,W,C) uint8 0~255
        arr = (image_tensor[0].permute(1, 2, 0).cpu().numpy() * 255).astype("uint8")
        try:
            results = self._model.predict(
                arr,
                conf=conf_threshold,
                device=self._device,
                verbose=False,
            )
        except Exception as e:
            # 通用降级策略：MPS OOM 时自动回退到 CPU 重试，避免整条 Agent 流程失败
            if self._device == "mps" and self._is_mps_oom_error(e):
                logger.warning("[YOLO] MPS OOM detected, falling back to CPU for detection retry")
                self._cleanup_torch_cache()
                try:
                    self._device = "cpu"
                    self._model.to("cpu")
                    results = self._model.predict(
                        arr,
                        conf=conf_threshold,
                        device="cpu",
                        verbose=False,
                    )
                except Exception:
                    raise e
            else:
                raise

        objects: List[DetectedObject] = []
        if not results:
            return objects

        r = results[0]
        if r.boxes is None:
            return objects

        # 使用 orig_shape 做归一化（YOLO 内部可能做 letterbox）
        orig_shape = getattr(r, "orig_shape", None) or (h, w)
        norm_h, norm_w = orig_shape[0], orig_shape[1]
        for box in r.boxes:
            xyxy = box.xyxy[0].cpu().numpy()
            x1, y1, x2, y2 = xyxy.tolist()
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            label = r.names.get(cls_id, "unknown")

            # 归一化到 0~1
            x1_n = max(0.0, min(1.0, x1 / norm_w))
            y1_n = max(0.0, min(1.0, y1 / norm_h))
            x2_n = max(0.0, min(1.0, x2 / norm_w))
            y2_n = max(0.0, min(1.0, y2 / norm_h))

            objects.append(
                DetectedObject(
                    label=label,
                    confidence=conf,
                    bbox=(x1_n, y1_n, x2_n, y2_n),
                )
            )

        return objects
