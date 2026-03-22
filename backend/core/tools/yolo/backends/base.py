"""
YOLOBackend 抽象基类与 Detection 数据结构
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None


@dataclass
class Detection:
    """统一检测/分割输出：bbox 为归一化坐标 (0~1)，mask 可选 base64 PNG"""

    label: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 (normalized)
    mask: Optional[str] = None  # 实例分割时的 mask 二值图 base64


class YOLOBackend(ABC):
    """YOLO Backend 抽象基类"""

    name: str  # e.g. "yolov8", "yolov11", "onnx"

    @abstractmethod
    async def load(self) -> None:
        """Load model weights if needed."""

    @abstractmethod
    async def detect(
        self,
        image: "Image.Image",
        confidence_threshold: float = 0.25,
        image_size: Tuple[int, int] | None = None,
    ) -> List[Detection]:
        """Run object detection. Returns normalized bbox [x1,y1,x2,y2] in 0~1."""
