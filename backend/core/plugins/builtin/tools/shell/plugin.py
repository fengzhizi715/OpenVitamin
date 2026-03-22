from core.tools.registry import ToolRegistry
from .run import ShellRunTool

def register():
    ToolRegistry.register(ShellRunTool())
