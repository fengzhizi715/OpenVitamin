from pathlib import Path
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError
from log import logger


def _get_allowed_absolute_roots() -> list[str]:
    """Allowed roots for absolute paths: from config (comma-separated). Empty => [home] only."""
    try:
        from config.settings import settings
        raw = getattr(settings, "file_read_allowed_roots", None) or ""
        roots = [r.strip() for r in str(raw).split(",") if r.strip()]
        if not roots:
            roots = [str(Path.home())]
        return roots
    except Exception:
        return [str(Path.home())]


class FileDeleteTool(Tool):
    @property
    def name(self) -> str:
        return "file.delete"

    @property
    def description(self) -> str:
        return "Delete a file. Accepts: (1) relative path under workspace, (2) absolute path under allowed roots. Only deletes files, not directories."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "path": {
                "type": "string",
                "description": "File path: relative to workspace root, or absolute path under allowed roots."
            }
        }, required=["path"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"path": {"type": "string"}, "deleted": {"type": "boolean"}}}

    @property
    def required_permissions(self):
        return ["file.write"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "File Delete",
            "icon": "FileText",
            "category": "file",
            "permissions_hint": [
                {"key": "file.write", "label": "Delete files within the workspace sandbox."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = input_data.get("path")
            if not path:
                return ToolResult(success=False, data=None, error="Path is required")

            try:
                target_abs = resolve_in_workspace(
                    workspace=ctx.workspace,
                    path=path.strip(),
                    allowed_absolute_roots=_get_allowed_absolute_roots(),
                )
            except WorkspacePathError as e:
                return ToolResult(success=False, data=None, error=str(e))

            # 只允许删除文件，不允许删除目录
            if target_abs.is_dir():
                return ToolResult(success=False, data=None, error="Cannot delete directory. Use file.delete only for files.")

            deleted = False
            if target_abs.exists() and target_abs.is_file():
                target_abs.unlink()
                deleted = True
                logger.info(f"[file.delete] Deleted {target_abs}")
            else:
                logger.warning(f"[file.delete] File not found: {target_abs}")

            return ToolResult(
                success=True,
                data={"path": str(target_abs), "deleted": deleted}
            )
        except Exception as e:
            logger.exception(f"[file.delete] Failed: {e}")
            return ToolResult(success=False, data=None, error=str(e))
