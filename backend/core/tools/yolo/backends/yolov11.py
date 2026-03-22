"""
YOLOv11Backend: 基于 TorchPerceptionRuntime 的 YOLOv11 实现

优先使用 RuntimeFactory 中已加载的 perception 模型；
若无则回退到 _config 的路径配置（兼容无显式 load 的场景）。
"""

from typing import List, Tuple
from contextlib import asynccontextmanager

try:
    from PIL import Image
except ImportError:
    Image = None

from .base import Detection, YOLOBackend
from log import logger


class YOLOv11Backend(YOLOBackend):
    name = "yolov11"

    def __init__(self):
        self._runtime = None

    async def load(self) -> None:
        """模型在首次 detect 时按需加载"""
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        """同步加载，供 detect 调用。优先从 Factory 获取已加载 runtime，否则用 _config 回退"""
        if self._runtime is not None:
            return
        from core.runtimes.factory import get_runtime_factory
        from core.runtimes.perception import TorchPerceptionRuntime
        from core.tools.yolo.backends._config import get_yolov11_config

        factory = get_runtime_factory()
        rt = factory.get_active_perception_runtime()
        if rt is not None:
            cfg = getattr(rt, "_config", {}) or {}
            model_path = str(cfg.get("model_path", "")).lower()
            model_id = str(cfg.get("model_id", "")).lower()
            if "yolo11" in model_id or "yolo11" in model_path:
                self._runtime = rt
            else:
                rt = None
        if rt is None:
            self._runtime = TorchPerceptionRuntime(get_yolov11_config())
        logger.info(f"[YOLO] backend={self.name} model_path={self._runtime._config.get('model_path')} device={self._runtime._config.get('device')}")
        self._runtime._get_adapter()

    async def detect(
        self,
        image: "Image.Image",
        confidence_threshold: float = 0.25,
        image_size: Tuple[int, int] | None = None,
    ) -> List[Detection]:
        self._ensure_loaded()

        @asynccontextmanager
        async def _noop():
            yield

        from core.runtimes.factory import get_runtime_factory
        factory = get_runtime_factory()
        descriptor_id = getattr(self._runtime, "_descriptor_id", None)
        usage_ctx = factory.model_usage(descriptor_id) if isinstance(descriptor_id, str) and descriptor_id.strip() else _noop()
        async with usage_ctx:
            result = self._runtime.detect(
                image,
                options={"confidence_threshold": confidence_threshold},
            )
        return [
            Detection(label=o.label, confidence=o.confidence, bbox=o.bbox)
            for o in result.objects
        ]
