from pathlib import Path
from typing import Dict, Any, List
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError
from log import logger


def _get_allowed_absolute_roots() -> list[str]:
    """Allowed roots for absolute paths."""
    try:
        from config.settings import settings
        raw = getattr(settings, "file_read_allowed_roots", None) or ""
        roots = [r.strip() for r in str(raw).split(",") if r.strip()]
        if not roots:
            roots = [str(Path.home())]
        return roots
    except Exception:
        return [str(Path.home())]


class FileTreeTool(Tool):
    """Generate a tree view of directory structure."""

    @property
    def name(self) -> str:
        return "file.tree"

    @property
    def description(self) -> str:
        return "Generate a tree view of directory structure. Shows files and subdirectories up to specified depth."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "path": {
                "type": "string",
                "description": "Root directory path: relative to workspace, or absolute path."
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth to display (default: 3).",
                "default": 3
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Include hidden files/directories (default: false).",
                "default": False
            },
            "exclude_dirs": {
                "type": "array",
                "description": "Directories to exclude (default: ['node_modules', '__pycache__', '.git', 'venv', '.venv']).",
                "default": ["node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build", ".next", "target"]
            }
        }, required=["path"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {
            "tree": {"type": "string"},
            "total_dirs": {"type": "integer"},
            "total_files": {"type": "integer"},
            "max_depth_reached": {"type": "integer"}
        }}

    @property
    def required_permissions(self):
        return ["file.read"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Project Tree",
            "icon": "FolderTree",
            "category": "file",
            "permissions_hint": [
                {"key": "file.read", "label": "Read directory structure within the workspace."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = input_data.get("path")
            max_depth = input_data.get("max_depth", 3)
            include_hidden = input_data.get("include_hidden", False)
            exclude_dirs = input_data.get("exclude_dirs", ["node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"])

            if not path:
                return ToolResult(success=False, data=None, error="Path is required")

            if max_depth < 1:
                max_depth = 1
            if max_depth > 10:
                max_depth = 10  # Limit to prevent too deep recursion

            try:
                root_path = resolve_in_workspace(
                    workspace=ctx.workspace,
                    path=path.strip(),
                    allowed_absolute_roots=_get_allowed_absolute_roots(),
                )
            except WorkspacePathError as e:
                return ToolResult(success=False, data=None, error=str(e))

            if not root_path.exists():
                return ToolResult(success=False, data=None, error=f"Path does not exist: {root_path}")

            if not root_path.is_dir():
                # If it's a file, just return its path
                return ToolResult(
                    success=True,
                    data={
                        "tree": root_path.name,
                        "total_dirs": 0,
                        "total_files": 1,
                        "max_depth_reached": 1
                    }
                )

            # Generate tree
            tree_lines = []
            total_dirs = 0
            total_files = 0
            max_depth_reached = 0

            def walk_directory(dir_path: Path, prefix: str = "", depth: int = 0):
                nonlocal total_dirs, total_files, max_depth_reached

                if depth > max_depth:
                    return

                max_depth_reached = max(max_depth_reached, depth)

                try:
                    entries = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                except PermissionError:
                    return

                dirs = []
                files = []

                for entry in entries:
                    # Skip hidden files/dirs if not included
                    if not include_hidden and entry.name.startswith('.'):
                        continue
                    # Skip excluded directories
                    if entry.is_dir() and entry.name in exclude_dirs:
                        continue

                    if entry.is_dir():
                        dirs.append(entry)
                        total_dirs += 1
                    else:
                        files.append(entry)
                        total_files += 1

                # Print directories first
                for i, d in enumerate(dirs):
                    is_last = (i == len(dirs) - 1 and len(files) == 0)
                    connector = "└── " if is_last else "├── "
                    tree_lines.append(f"{prefix}{connector}{d.name}/")

                    new_prefix = prefix + ("    " if is_last else "│   ")
                    walk_directory(d, new_prefix, depth + 1)

                # Then print files
                for i, f in enumerate(files):
                    is_last = (i == len(files) - 1)
                    connector = "└── " if is_last else "├── "
                    tree_lines.append(f"{prefix}{connector}{f.name}")

            # Add root path name
            tree_lines.append(f"{root_path.name}/")
            walk_directory(root_path, "", 1)

            tree_output = "\n".join(tree_lines)

            logger.info(f"[file.tree] Generated tree for {root_path}: {total_dirs} dirs, {total_files} files")

            return ToolResult(
                success=True,
                data={
                    "tree": tree_output,
                    "total_dirs": total_dirs,
                    "total_files": total_files,
                    "max_depth_reached": max_depth_reached
                }
            )

        except Exception as e:
            logger.error(f"[file.tree] Error: {e}")
            return ToolResult(success=False, data=None, error=str(e))
