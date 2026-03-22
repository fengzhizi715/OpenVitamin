from core.tools.registry import ToolRegistry
from .now import TimeNowTool
from .format import TimeFormatTool
from .sleep import TimeSleepTool

def register():
    ToolRegistry.register(TimeNowTool())
    ToolRegistry.register(TimeFormatTool())
    ToolRegistry.register(TimeSleepTool())
