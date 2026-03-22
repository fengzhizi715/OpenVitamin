from core.tools.registry import ToolRegistry
from .detect import ProjectDetectTool
from .scan import ProjectScanTool
from .test import ProjectTestTool
from .build import ProjectBuildTool
from .analyze import ProjectAnalyzeTool


def register():
    ToolRegistry.register(ProjectDetectTool())
    ToolRegistry.register(ProjectScanTool())
    ToolRegistry.register(ProjectTestTool())
    ToolRegistry.register(ProjectBuildTool())
    ToolRegistry.register(ProjectAnalyzeTool())  # V2.3 - Project Intelligence
