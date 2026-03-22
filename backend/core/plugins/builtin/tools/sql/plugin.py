from core.tools.registry import ToolRegistry
from .query import SqlQueryTool

def register():
    ToolRegistry.register(SqlQueryTool())
