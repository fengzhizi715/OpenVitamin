"""Image generation tools registration."""

from core.tools.image import (
    ImageCancelJobTool,
    ImageGenerateTool,
    ImageGetJobTool,
    ImageListModelsTool,
)
from core.tools.registry import ToolRegistry


def register():
    ToolRegistry.register(ImageListModelsTool())
    ToolRegistry.register(ImageGenerateTool())
    ToolRegistry.register(ImageGetJobTool())
    ToolRegistry.register(ImageCancelJobTool())
