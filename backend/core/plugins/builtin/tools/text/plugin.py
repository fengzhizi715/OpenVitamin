from core.tools.registry import ToolRegistry
from .split import TextSplitTool
from .truncate import TextTruncateTool
from .regex_extract import TextRegexExtractTool
from .diff import TextDiffTool

def register():
    ToolRegistry.register(TextSplitTool())
    ToolRegistry.register(TextTruncateTool())
    ToolRegistry.register(TextRegexExtractTool())
    ToolRegistry.register(TextDiffTool())
