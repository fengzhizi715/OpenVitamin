"""
Image generation runtime abstraction.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any

from core.runtimes.image_generation_types import ImageGenerationRequest, ImageGenerationResponse


class ImageGenerationRuntime(ABC):
    @abstractmethod
    async def load(self) -> bool:
        pass

    @abstractmethod
    async def unload(self) -> bool:
        pass

    @abstractmethod
    async def is_loaded(self) -> bool:
        pass

    @abstractmethod
    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        pass

    async def cancel(self) -> bool:
        return False

    @property
    @abstractmethod
    def model_info(self) -> Dict[str, Any]:
        pass
