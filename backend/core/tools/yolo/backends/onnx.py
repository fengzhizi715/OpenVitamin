"""
ONNXBackend: 占位实现，待补充
"""

from typing import List, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None

from .base import Detection, YOLOBackend


class ONNXBackend(YOLOBackend):
    name = "onnx"

    async def load(self) -> None:
        pass

    async def detect(
        self,
        image: "Image.Image",
        confidence_threshold: float = 0.25,
        image_size: Tuple[int, int] | None = None,
    ) -> List[Detection]:
        raise NotImplementedError("ONNX backend not yet implemented")
