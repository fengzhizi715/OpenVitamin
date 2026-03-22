"""
FastSAMBackend: 基于 TorchPerceptionRuntime 的 FastSAM 实例分割

优先使用 RuntimeFactory 中已加载的 perception 模型（task=instance_segmentation）；
若无则用 get_fastsam_config() 回退。
"""

from contextlib import asynccontextmanager
from typing import List, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None

from .base import Detection, YOLOBackend
from log import logger


class FastSAMBackend(YOLOBackend):
    name = "fastsam"

    def __init__(self):
        self._runtime = None

    async def load(self) -> None:
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._runtime is not None:
            return
        from core.runtimes.factory import get_runtime_factory
        from core.runtimes.perception import TorchPerceptionRuntime
        from core.tools.yolo.backends._config import get_fastsam_config

        factory = get_runtime_factory()
        rt = factory.get_active_perception_runtime()
        if rt is not None:
            cfg = getattr(rt, "_config", {}) or {}
            task = str(cfg.get("task", "")).lower()
            if task == "instance_segmentation":
                self._runtime = rt
            else:
                rt = None
        if rt is None:
            self._runtime = TorchPerceptionRuntime(get_fastsam_config())
        logger.info(
            f"[FastSAM] backend={self.name} model_path={self._runtime._config.get('model_path')} "
            f"device={self._runtime._config.get('device')}"
        )
        self._runtime._get_adapter()

    async def detect(
        self,
        image: "Image.Image",
        confidence_threshold: float = 0.4,
        image_size: Tuple[int, int] | None = None,
    ) -> List[Detection]:
        self._ensure_loaded()

        @asynccontextmanager
        async def _noop():
            yield

        from core.runtimes.factory import get_runtime_factory
        factory = get_runtime_factory()
        descriptor_id = getattr(self._runtime, "_descriptor_id", None)
        usage_ctx = (
            factory.model_usage(descriptor_id)
            if isinstance(descriptor_id, str) and descriptor_id.strip()
            else _noop()
        )
        async with usage_ctx:
            result = self._runtime.detect(
                image,
                options={"confidence_threshold": confidence_threshold},
            )
        return [
            Detection(
                label=o.label,
                confidence=o.confidence,
                bbox=o.bbox,
                mask=getattr(o, "mask", None),
            )
            for o in result.objects
        ]
