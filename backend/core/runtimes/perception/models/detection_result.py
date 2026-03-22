"""
DetectionResult: 视觉感知的结构化输出

字段命名稳定，可直接 JSON 序列化，供 Agent 调用。
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class DetectedObject:
    """单个检测目标（检测或实例分割）"""

    label: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 (normalized 0~1)
    mask: Optional[str] = None  # 实例分割时可选：mask 二值图 base64 PNG

    def to_dict(self) -> dict:
        out = {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "bbox": list(self.bbox),
        }
        if self.mask is not None:
            out["mask"] = self.mask
        return out


@dataclass
class DetectionResult:
    """目标检测结果"""

    objects: List[DetectedObject]
    image_size: Tuple[int, int]

    def to_dict(self) -> dict:
        return {
            "objects": [o.to_dict() for o in self.objects],
            "image_size": list(self.image_size),
        }
