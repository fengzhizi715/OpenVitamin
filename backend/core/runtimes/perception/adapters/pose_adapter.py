"""
PoseAdapter: 预留接口，不实现

未来扩展：姿态估计能力。
"""

from abc import ABC, abstractmethod
from typing import Any


class PoseAdapter(ABC):
    """姿态估计适配器（预留）"""

    @abstractmethod
    def estimate(self, image_tensor: Any, **kwargs) -> Any:
        """执行姿态估计，返回结构化结果。"""
        ...
