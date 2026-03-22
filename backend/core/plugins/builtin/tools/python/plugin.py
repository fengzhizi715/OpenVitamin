from core.tools.registry import ToolRegistry
from .run import PythonRunTool

def register():
    ToolRegistry.register(PythonRunTool())
