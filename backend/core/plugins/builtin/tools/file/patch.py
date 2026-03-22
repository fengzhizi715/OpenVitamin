import difflib
import re
from pathlib import Path
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError
from log import logger


def _get_allowed_absolute_roots() -> list[str]:
    """Allowed roots for absolute paths: from config (comma-separated)."""
    try:
        from config.settings import settings
        raw = getattr(settings, "file_read_allowed_roots", None) or ""
        roots = [r.strip() for r in str(raw).split(",") if r.strip()]
        if not roots:
            roots = [str(Path.home())]
        return roots
    except Exception:
        return [str(Path.home())]


class FilePatchTool(Tool):
    """Patch a file using unified diff format."""

    @property
    def name(self) -> str:
        return "file.patch"

    @property
    def description(self) -> str:
        return "Patch a file using unified diff format. Input requires 'path' and 'patch' (unified diff string). Creates backup before applying."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "path": {
                "type": "string",
                "description": "File path to patch: relative to workspace, or absolute path under allowed roots."
            },
            "patch": {
                "type": "string",
                "description": "Unified diff string (e.g., '--- a/file.py\\n+++ b/file.py\\n@@ -1,3 +1,4 @@\\n+new line')"
            },
            "create_if_missing": {
                "type": "boolean",
                "description": "Create the file if it doesn't exist (default: false)",
                "default": False
            }
        }, required=["path", "patch"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {
            "path": {"type": "string"},
            "patched": {"type": "boolean"},
            "backup_path": {"type": "string"},
            "lines_added": {"type": "integer"},
            "lines_removed": {"type": "integer"}
        }}

    @property
    def required_permissions(self):
        return ["file.write"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "File Patch",
            "icon": "FileDiff",
            "category": "file",
            "permissions_hint": [
                {"key": "file.write", "label": "Patch files within the workspace."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = input_data.get("path")
            patch_content = input_data.get("patch")
            create_if_missing = input_data.get("create_if_missing", False)

            if not path:
                return ToolResult(success=False, data=None, error="Path is required")
            if not patch_content:
                return ToolResult(success=False, data=None, error="Patch content is required")

            try:
                target_abs = resolve_in_workspace(
                    workspace=ctx.workspace,
                    path=path.strip(),
                    allowed_absolute_roots=_get_allowed_absolute_roots(),
                )
            except WorkspacePathError as e:
                return ToolResult(success=False, data=None, error=str(e))

            # Check if file exists
            if not target_abs.exists():
                if create_if_missing:
                    # Create empty file
                    target_abs.parent.mkdir(parents=True, exist_ok=True)
                    target_abs.write_text("")
                    logger.info(f"[file.patch] Created new file: {target_abs}")
                else:
                    return ToolResult(success=False, data=None, error=f"File not found: {target_abs}. Use create_if_missing=true to create it.")

            # Read original content
            original_lines = target_abs.read_text(encoding="utf-8").splitlines(keepends=True)

            # Parse unified diff
            try:
                patched_lines = self._apply_unified_diff(original_lines, patch_content)
            except Exception as e:
                return ToolResult(success=False, data=None, error=f"Failed to parse/apply patch: {str(e)}")

            # 防御：若 patch 应用后内容无变化，视为失败，避免“patched=true 但实际未修改”
            if patched_lines == original_lines:
                return ToolResult(
                    success=False,
                    data=None,
                    error="Patch had no effect on target file",
                )

            # Create backup
            backup_path = target_abs.with_suffix(target_abs.suffix + ".bak")
            target_abs.rename(backup_path)
            logger.info(f"[file.patch] Created backup: {backup_path}")

            # Write patched content
            target_abs.write_text("".join(patched_lines), encoding="utf-8")

            # Count changes from patch text (not from patched file content)
            lines_added = 0
            lines_removed = 0
            for line in patch_content.splitlines():
                if line.startswith("+++ ") or line.startswith("--- ") or line.startswith("@@"):
                    continue
                if line.startswith("+"):
                    lines_added += 1
                elif line.startswith("-"):
                    lines_removed += 1

            logger.info(f"[file.patch] Patched {target_abs}: +{lines_added} -{lines_removed} lines")

            return ToolResult(
                success=True,
                data={
                    "path": str(target_abs),
                    "patched": True,
                    "backup_path": str(backup_path),
                    "lines_added": lines_added,
                    "lines_removed": lines_removed
                }
            )

        except Exception as e:
            logger.error(f"[file.patch] Error: {e}")
            return ToolResult(success=False, data=None, error=str(e))

    def _apply_unified_diff(self, original_lines: list, patch_content: str) -> list:
        """Apply unified diff to original lines."""
        # Parse unified diff format
        lines = patch_content.splitlines(keepends=True)
        
        # Find the start of file content in diff
        original_file = None
        new_file = None
        hunks = []
        current_hunk = None
        
        for i, line in enumerate(lines):
            if line.startswith("--- "):
                original_file = line[4:].split('\t')[0]
            elif line.startswith("+++ "):
                new_file = line[4:].split('\t')[0]
            elif line.startswith("@@"):
                # Parse hunk header: @@ -start,count +start,count @@
                match = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@', line)
                if match:
                    if current_hunk:
                        hunks.append(current_hunk)
                    old_start = int(match.group(1))
                    old_count = int(match.group(2)) if match.group(2) else 1
                    new_start = int(match.group(3))
                    new_count = int(match.group(4)) if match.group(4) else 1
                    current_hunk = {
                        "old_start": old_start,
                        "old_count": old_count,
                        "new_start": new_start,
                        "new_count": new_count,
                        "old_lines": [],
                        "new_lines": []
                    }
            elif current_hunk is not None:
                if line.startswith('-'):
                    current_hunk["old_lines"].append(line[1:])
                elif line.startswith('+'):
                    current_hunk["new_lines"].append(line[1:])
                elif line.startswith(' '):
                    # Context line belongs to both sides
                    current_hunk["old_lines"].append(line[1:])
                    current_hunk["new_lines"].append(line[1:])
        
        if current_hunk:
            hunks.append(current_hunk)
        
        if not hunks:
            # No hunks found, try simple line-by-line patch
            return self._apply_simple_patch(original_lines, lines)
        
        # Apply hunks in reverse order to maintain line numbers
        result = original_lines[:]
        for hunk in reversed(hunks):
            old_start = hunk["old_start"] - 1  # Convert to 0-indexed
            old_count = hunk["old_count"]
            new_lines = hunk["new_lines"]
            
            # Replace old lines with new lines
            result[old_start:old_start + old_count] = new_lines
        
        return result

    def _apply_simple_patch(self, original_lines: list, patch_lines: list) -> list:
        """Apply patch when unified diff parsing fails - try simple approach."""
        # Try to use Python's difflib
        from io import StringIO
        diff = StringIO(''.join(patch_lines))
        
        # Find where original content should go
        result = []
        old_idx = 0
        
        for line in patch_lines:
            if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
                continue
            elif line.startswith('-'):
                # Skip this line from original
                old_idx += 1
            elif line.startswith('+'):
                # Add new line
                result.append(line[1:])
            elif line.startswith(' '):
                # Keep original line
                if old_idx < len(original_lines):
                    result.append(original_lines[old_idx])
                    old_idx += 1
        
        # Add remaining original lines
        while old_idx < len(original_lines):
            result.append(original_lines[old_idx])
            old_idx += 1
        
        return result
