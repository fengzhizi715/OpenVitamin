import re
import os
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


class FileSearchTool(Tool):
    """Search for patterns in files (like grep)."""

    @property
    def name(self) -> str:
        return "file.search"

    @property
    def description(self) -> str:
        return "Search for text patterns in files. Supports regex, file glob, and line number output."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "path": {
                "type": "string",
                "description": "Directory or file path to search: relative to workspace, or absolute path."
            },
            "pattern": {
                "type": "string",
                "description": "Search pattern (regex supported)."
            },
            "glob": {
                "type": "string",
                "description": "File glob pattern (e.g., '*.py', '*.txt'). Default: all files.",
                "default": "*"
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case insensitive search (default: false).",
                "default": False
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default: 100).",
                "default": 100
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Include hidden files (default: false).",
                "default": False
            }
        }, required=["path", "pattern"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {
            "matches": {"type": "array"},
            "total_matches": {"type": "integer"},
            "files_searched": {"type": "integer"}
        }}

    @property
    def required_permissions(self):
        return ["file.read"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "File Search",
            "icon": "Search",
            "category": "file",
            "permissions_hint": [
                {"key": "file.read", "label": "Search files within the workspace."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = input_data.get("path")
            pattern = input_data.get("pattern")
            glob = input_data.get("glob", "*")
            ignore_case = input_data.get("ignore_case", False)
            max_results = input_data.get("max_results", 100)
            include_hidden = input_data.get("include_hidden", False)

            if not path:
                return ToolResult(success=False, data=None, error="Path is required")
            if not pattern:
                return ToolResult(success=False, data=None, error="Pattern is required")

            try:
                search_path = resolve_in_workspace(
                    workspace=ctx.workspace,
                    path=path.strip(),
                    allowed_absolute_roots=_get_allowed_absolute_roots(),
                )
            except WorkspacePathError as e:
                return ToolResult(success=False, data=None, error=str(e))

            if not search_path.exists():
                return ToolResult(success=False, data=None, error=f"Path does not exist: {search_path}")

            # Compile regex pattern
            try:
                flags = re.IGNORECASE if ignore_case else 0
                regex = re.compile(pattern, flags)
            except re.error as e:
                return ToolResult(success=False, data=None, error=f"Invalid regex pattern: {str(e)}")

            matches = []
            files_searched = 0

            # Determine files to search
            if search_path.is_file():
                files_to_search = [search_path]
            else:
                files_to_search = self._find_files(search_path, glob, include_hidden)

            for file_path in files_to_search:
                if len(matches) >= max_results:
                    break
                
                try:
                    # Skip binary files
                    if self._is_binary(file_path):
                        continue
                    
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.splitlines()
                    files_searched += 1
                    
                    for line_num, line in enumerate(lines, start=1):
                        if len(matches) >= max_results:
                            break
                        
                        if regex.search(line):
                            matches.append({
                                "file": str(file_path.relative_to(ctx.workspace) if ctx.workspace and file_path.is_relative_to(ctx.workspace) else file_path),
                                "line": line_num,
                                "content": line[:200],  # Truncate long lines
                            })
                            
                except Exception as e:
                    logger.warning(f"[file.search] Error reading {file_path}: {e}")
                    continue

            logger.info(f"[file.search] Found {len(matches)} matches in {files_searched} files")

            return ToolResult(
                success=True,
                data={
                    "matches": matches,
                    "total_matches": len(matches),
                    "files_searched": files_searched
                }
            )

        except Exception as e:
            logger.error(f"[file.search] Error: {e}")
            return ToolResult(success=False, data=None, error=str(e))

    def _find_files(self, directory: Path, glob_pattern: str, include_hidden: bool) -> List[Path]:
        """Find files matching glob pattern."""
        files = []
        
        try:
            for path in directory.rglob(glob_pattern):
                if path.is_file():
                    # Skip hidden files if not included
                    if not include_hidden and any(part.startswith('.') for part in path.parts):
                        continue
                    # Skip common non-code directories
                    skip_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build'}
                    if any(skip in path.parts for skip in skip_dirs):
                        continue
                    files.append(path)
        except Exception as e:
            logger.warning(f"[file.search] Error finding files: {e}")
        
        return files

    def _is_binary(self, file_path: Path) -> bool:
        """Check if file is binary."""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                return b'\x00' in chunk
        except:
            return False
