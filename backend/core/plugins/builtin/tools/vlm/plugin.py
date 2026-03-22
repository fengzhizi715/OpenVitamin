"""VLM 工具注册"""

from core.tools.registry import ToolRegistry
from core.tools.vlm import VLMGenerateTool


def register():
    ToolRegistry.register(VLMGenerateTool())

