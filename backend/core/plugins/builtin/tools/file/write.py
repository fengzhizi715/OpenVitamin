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


class FileWriteTool(Tool):
    @property
    def name(self) -> str:
        return "file.write"

    @property
    def description(self) -> str:
        return "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. Accepts: (1) relative path under workspace, (2) absolute path under allowed roots."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "path": {
                "type": "string",
                "description": "File path: relative to workspace root, or absolute path under allowed roots."
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file."
            },
            "encoding": {
                "type": "string",
                "description": "File encoding (default: utf-8).",
                "default": "utf-8"
            }
        }, required=["path", "content"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"path": {"type": "string"}, "bytes_written": {"type": "integer"}}}

    @property
    def required_permissions(self):
        return ["file.write"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "File Write",
            "icon": "FileText",
            "category": "file",
            "permissions_hint": [
                {"key": "file.write", "label": "Write files within the workspace sandbox."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = input_data.get("path")
            content = input_data.get("content")
            encoding = input_data.get("encoding", "utf-8")

            if not path:
                return ToolResult(success=False, data=None, error="Path is required")
            if content is None:
                return ToolResult(success=False, data=None, error="Content is required")

            path_stripped = path.strip()
            if not path_stripped or path_stripped == ".":
                return ToolResult(
                    success=False,
                    data=None,
                    error="path must be a file path (e.g. filename or path/to/file), not a directory or '.'",
                )

            try:
                target_abs = resolve_in_workspace(
                    workspace=ctx.workspace,
                    path=path_stripped,
                    allowed_absolute_roots=_get_allowed_absolute_roots(),
                )
            except WorkspacePathError as e:
                return ToolResult(success=False, data=None, error=str(e))

            if target_abs.exists() and target_abs.is_dir():
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Path is a directory, not a file: {target_abs}",
                )

            # 确保父目录存在
            target_abs.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            bytes_written = target_abs.write_text(content, encoding=encoding)
            
            logger.info(f"[file.write] Wrote {bytes_written} bytes to {target_abs}")
            
            return ToolResult(
                success=True,
                data={"path": str(target_abs), "bytes_written": bytes_written}
            )
        except Exception as e:
            logger.exception(f"[file.write] Failed: {e}")
            return ToolResult(success=False, data=None, error=str(e))
