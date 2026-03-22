from core.tools.registry import ToolRegistry
from .get import HttpGetTool
from .post import HttpPostTool
from .request import HttpRequestTool

def register():
    ToolRegistry.register(HttpGetTool())
    ToolRegistry.register(HttpPostTool())
    ToolRegistry.register(HttpRequestTool())
