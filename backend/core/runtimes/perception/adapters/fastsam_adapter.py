"""
FastSAMAdapter: Ultralytics FastSAM 实例分割适配器

与 YoloObjectDetectionAdapter 同属感知层，输出 DetectedObject（含可选 mask）。
"""

from __future__ import annotations

import base64
import io
from typing import List, Literal

import torch

from ..models.detection_result import DetectedObject
from log import logger


DeviceType = Literal["cpu", "cuda", "mps"]


class FastSAMAdapter:
    """FastSAM 实例分割适配器"""

    def __init__(self, model_path: str, device: str = "cpu"):
        self._model_path = model_path
        self._device = self._resolve_device(device)
        self._model = None

    def _resolve_device(self, device: str) -> str:
        import torch as t
        if device == "cuda" and not t.cuda.is_available():
            return "cpu"
        if device == "mps" and not (hasattr(t.backends, "mps") and t.backends.mps.is_available()):
            return "cpu"
        return device

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from ultralytics import FastSAM
        except ImportError:
            raise ImportError("ultralytics 未安装，请执行: pip install ultralytics")
        self._model = FastSAM(self._model_path)
        self._model.to(self._device)

    def detect(
        self,
        image_tensor: torch.Tensor,
        conf_threshold: float = 0.4,
    ) -> List[DetectedObject]:
        """
        执行实例分割。

        Args:
            image_tensor: (1, C, H, W) float32 0~1
            conf_threshold: 置信度阈值

        Returns:
            list[DetectedObject]，bbox 已归一化 (0~1)，mask 为 base64 PNG（若有）
        """
        self.load()
        _, _, h, w = image_tensor.shape
        img_size = (w, h)
        arr = (image_tensor[0].permute(1, 2, 0).cpu().numpy() * 255).astype("uint8")

        try:
            results = self._model.predict(
                arr,
                conf=conf_threshold,
                device=self._device,
                retina_masks=True,
                imgsz=1024,
                iou=0.9,
                verbose=False,
            )
        except Exception as e:
            logger.exception(f"[FastSAM] predict failed: {e}")
            raise

        objects: List[DetectedObject] = []
        if not results:
            return objects

        r = results[0]
        if r.boxes is None:
            return objects

        orig_shape = getattr(r, "orig_shape", None) or (h, w)
        norm_h, norm_w = orig_shape[0], orig_shape[1]
        masks_data = r.masks.data if r.masks is not None else None

        for idx, box in enumerate(r.boxes):
            xyxy = box.xyxy[0].cpu().numpy()
            x1, y1, x2, y2 = xyxy.tolist()
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            label = r.names.get(cls_id, "object")

            x1_n = max(0.0, min(1.0, x1 / norm_w))
            y1_n = max(0.0, min(1.0, y1 / norm_h))
            x2_n = max(0.0, min(1.0, x2 / norm_w))
            y2_n = max(0.0, min(1.0, y2 / norm_h))

            mask_b64: str | None = None
            if masks_data is not None and idx < masks_data.shape[0]:
                mask_b64 = _mask_tensor_to_base64_png(masks_data[idx].cpu().numpy())

            objects.append(
                DetectedObject(
                    label=label,
                    confidence=conf,
                    bbox=(x1_n, y1_n, x2_n, y2_n),
                    mask=mask_b64,
                )
            )

        return objects


def _mask_tensor_to_base64_png(mask: "torch.Tensor | object") -> str:
    """将单通道二值 mask (H,W) 转为 base64 PNG"""
    import numpy as np
    from PIL import Image

    if hasattr(mask, "cpu"):
        mask = mask.cpu().numpy()
    arr = np.asarray(mask, dtype=np.float32)
    if arr.max() > 1.0:
        arr = (arr > 0).astype(np.uint8) * 255
    else:
        arr = (arr > 0.5).astype(np.uint8) * 255
    img = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
