from typing import Dict, Any, List
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError

class FileListTool(Tool):
    @property
    def name(self) -> str:
        return "file.list"

    @property
    def description(self) -> str:
        return "List files in a directory. Restricted to the workspace directory."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "path": {"type": "string", "description": "The relative path to the directory from the workspace root."}
        }, required=["path"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "array", "items": {"type": "string"}}

    @property
    def required_permissions(self):
        return ["file.list"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "File List",
            "icon": "FileText",
            "category": "file",
            "permissions_hint": [
                {"key": "file.list", "label": "List files/directories within the workspace sandbox."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = input_data.get("path") or "."

            try:
                # Import the function to get allowed roots
                from .read import _get_allowed_absolute_roots
                target_abs = resolve_in_workspace(workspace=ctx.workspace, path=path, allowed_absolute_roots=_get_allowed_absolute_roots())
            except WorkspacePathError as e:
                return ToolResult(success=False, data=None, error=str(e))

            if not target_abs.is_dir():
                return ToolResult(success=False, data=None, error=f"Directory not found: {path}")

            files = [p.name for p in target_abs.iterdir()]
            return ToolResult(success=True, data=files)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
