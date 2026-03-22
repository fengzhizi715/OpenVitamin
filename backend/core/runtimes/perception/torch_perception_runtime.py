"""
TorchPerceptionRuntime: 视觉感知运行时

- 管理模型加载
- 统一对外接口 detect(image_input, options) -> DetectionResult
- 不关心具体模型细节
- 仅做感知，输出结构化 JSON，不参与对话
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union

from .adapters.yolo_object_detection_adapter import YoloObjectDetectionAdapter
from .adapters.fastsam_adapter import FastSAMAdapter
from .models.detection_result import DetectionResult
from .utils.image_loader import load_image


class TorchPerceptionRuntime:
    """视觉感知运行时"""

    def __init__(self, model_config: Dict[str, Any]):
        self._config = model_config
        self._adapter: Optional[Union[YoloObjectDetectionAdapter, FastSAMAdapter]] = None

    def _get_adapter(self) -> Union[YoloObjectDetectionAdapter, FastSAMAdapter]:
        if self._adapter is not None:
            return self._adapter

        task = (self._config.get("task") or "object_detection").lower()
        model_path = self._config.get("model_path")
        if not model_path:
            raise ValueError("model_config.model_path 必填")

        device = self._config.get("device") or "cpu"

        if task == "object_detection":
            self._adapter = YoloObjectDetectionAdapter(model_path=model_path, device=device)
        elif task == "instance_segmentation":
            self._adapter = FastSAMAdapter(model_path=model_path, device=device)
        else:
            raise ValueError(f"不支持的 task: {task}，支持 object_detection | instance_segmentation")

        self._adapter.load()
        return self._adapter

    def detect(
        self,
        image_input: Union[str, Path, Any],
        options: Optional[Dict[str, Any]] = None,
    ) -> DetectionResult:
        """
        执行目标检测。

        Args:
            image_input: 本地路径、PIL.Image、numpy.ndarray
            options: 可选参数，如 confidence_threshold

        Returns:
            DetectionResult，可直接 JSON 序列化
        """
        options = options or {}
        tensor, image_size = load_image(image_input)
        conf = options.get("confidence_threshold") or self._config.get("confidence_threshold") or 0.25

        adapter = self._get_adapter()
        objects = adapter.detect(tensor, conf_threshold=conf)

        return DetectionResult(objects=objects, image_size=image_size)

    def unload(self) -> None:
        """卸载模型，释放资源"""
        self._adapter = None

    @property
    def is_loaded(self) -> bool:
        """检查模型是否已加载"""
        return self._adapter is not None
