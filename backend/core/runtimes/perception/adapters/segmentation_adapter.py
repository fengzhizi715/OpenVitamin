"""
SegmentationAdapter: 预留接口，不实现

未来扩展：实例分割能力。
"""

from abc import ABC, abstractmethod
from typing import Any


class SegmentationAdapter(ABC):
    """实例分割适配器（预留）"""

    @abstractmethod
    def segment(self, image_tensor: Any, **kwargs) -> Any:
        """执行分割，返回结构化结果。"""
        ...
