"""
YOLOBackendRouter: 管理 YOLO backend 注册与路由
"""

from typing import Dict

from config.settings import settings
from .backends.base import YOLOBackend


class YOLOBackendRouter:
    """YOLO Backend 路由器"""

    def __init__(self):
        self._backends: Dict[str, YOLOBackend] = {}

    def register(self, backend: YOLOBackend) -> None:
        self._backends[backend.name] = backend

    def get(self, name: str) -> YOLOBackend:
        if name not in self._backends:
            raise ValueError(f"YOLO backend '{name}' not found. Available: {list(self._backends.keys())}")
        return self._backends[name]

    def default(self) -> YOLOBackend:
        name = self._get_default_backend_name()
        return self.get(name)

    def _get_default_backend_name(self) -> str:
        """优先从 UI 配置读取，否则用 settings"""
        try:
            from core.system.settings_store import get_system_settings_store
            store = get_system_settings_store()
            v = store.get_setting("yoloDefaultBackend") or store.get_setting("yolo_default_backend")
            if v:
                return v
        except Exception:
            pass
        return getattr(settings, "yolo_default_backend", "yolov8") or "yolov8"


def create_and_register_routers() -> YOLOBackendRouter:
    """创建 Router 并注册所有 backend"""
    from .backends.yolov8 import YOLOv8Backend
    from .backends.yolov11 import YOLOv11Backend
    from .backends.yolov26 import YOLOv26Backend
    from .backends.onnx import ONNXBackend
    from .backends.fastsam import FastSAMBackend

    router = YOLOBackendRouter()
    router.register(YOLOv8Backend())
    router.register(YOLOv11Backend())
    router.register(YOLOv26Backend())
    router.register(ONNXBackend())
    router.register(FastSAMBackend())
    return router


_router: YOLOBackendRouter | None = None


def get_yolo_router() -> YOLOBackendRouter:
    global _router
    if _router is None:
        _router = create_and_register_routers()
    return _router
