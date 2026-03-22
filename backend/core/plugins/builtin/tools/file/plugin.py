from core.tools.registry import ToolRegistry
from .read import FileReadTool
from .list import FileListTool
from .write import FileWriteTool
from .append import FileAppendTool
from .delete import FileDeleteTool
from .patch import FilePatchTool
from .apply_patch import FileApplyPatchTool
from .search import FileSearchTool
from .tree import FileTreeTool

def register():
    ToolRegistry.register(FileReadTool())
    ToolRegistry.register(FileListTool())
    ToolRegistry.register(FileWriteTool())
    ToolRegistry.register(FileAppendTool())
    ToolRegistry.register(FileDeleteTool())
    ToolRegistry.register(FilePatchTool())  # V2.2
    ToolRegistry.register(FileApplyPatchTool())  # V2.3 - AI Programming Agent
    ToolRegistry.register(FileSearchTool())  # V2.2
    ToolRegistry.register(FileTreeTool())  # V2.2
