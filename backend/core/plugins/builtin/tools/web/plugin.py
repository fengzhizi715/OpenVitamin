from core.tools.registry import ToolRegistry
from .search import WebSearchTool

def register():
    ToolRegistry.register(WebSearchTool())
