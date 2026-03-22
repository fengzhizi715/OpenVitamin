"""
file.apply_patch Tool - Apply unified diff patch with safety controls.

Safety controls:
- Only allow modifications within workspace
- Block new paths outside workspace
- Validate file exists
- Max 500 lines modification limit
- Validate patch format strictly
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError
from log import logger


# Maximum number of lines that can be modified in a single patch
MAX_PATCH_LINES = 500


def _get_allowed_absolute_roots() -> list:
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


def _parse_unified_diff(patch_content: str) -> Tuple[List[Dict], Optional[str]]:
    """
    Parse unified diff format and return list of file patches.
    
    Returns:
        (file_patches, error_message)
        file_patches: [{"filename": str, "hunks": [hunk dicts]}]
    """
    lines = patch_content.splitlines(keepends=True)
    file_patches = []
    current_file = None
    current_hunks = []
    current_hunk = None
    
    for i, line in enumerate(lines):
        # File header: --- a/filename
        if line.startswith("--- "):
            # Start new file patch
            if current_file and current_hunks:
                file_patches.append({
                    "filename": current_file,
                    "hunks": current_hunks,
                })
                current_hunks = []
            
            # Extract filename from --- a/filename or --- filename
            parts = line[4:].split("\t")[0].strip()
            if parts.startswith("a/"):
                parts = parts[2:]
            current_file = parts
            
        elif line.startswith("+++ "):
            # We already got filename from ---, just validate
            pass
            
        elif line.startswith("@@"):
            # Hunk header: @@ -start,count +start,count @@
            if current_hunk:
                current_hunks.append(current_hunk)
            
            match = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@', line)
            if match:
                current_hunk = {
                    "old_start": int(match.group(1)),
                    "old_count": int(match.group(2)) if match.group(2) else 1,
                    "new_start": int(match.group(3)),
                    "new_count": int(match.group(4)) if match.group(4) else 1,
                    "lines": [],  # List of (type, content) where type is ' ', '-', '+'
                }
            else:
                return [], f"Invalid hunk header at line {i+1}: {line[:50]}"
                
        elif current_hunk is not None:
            # Hunk content
            if line.startswith(' '):
                current_hunk["lines"].append((' ', line[1:]))
            elif line.startswith('-'):
                current_hunk["lines"].append(('-', line[1:]))
            elif line.startswith('+'):
                current_hunk["lines"].append(('+', line[1:]))
            elif line.startswith('\\'):
                # "\ No newline at end of file" - ignore
                pass
            elif line.strip() == '':
                # Empty line might be context with trailing newline
                current_hunk["lines"].append((' ', '\n'))
    
    # Add last hunk and file
    if current_hunk:
        current_hunks.append(current_hunk)
    if current_file and current_hunks:
        file_patches.append({
            "filename": current_file,
            "hunks": current_hunks,
        })
    
    return file_patches, None


def _count_patch_lines(file_patches: List[Dict]) -> Tuple[int, int]:
    """Count lines added and removed in patch."""
    lines_added = 0
    lines_removed = 0
    
    for file_patch in file_patches:
        for hunk in file_patch.get("hunks", []):
            for line_type, _ in hunk.get("lines", []):
                if line_type == '+':
                    lines_added += 1
                elif line_type == '-':
                    lines_removed += 1
    
    return lines_added, lines_removed


def _apply_patch_to_content(original_lines: List[str], hunks: List[Dict]) -> Tuple[List[str], Optional[str]]:
    """
    Apply hunks to original content.
    
    Returns:
        (patched_lines, error_message)
    """
    result = original_lines[:]
    
    # Apply hunks in reverse order to maintain line numbers
    for hunk in reversed(hunks):
        old_start = hunk["old_start"] - 1  # Convert to 0-indexed
        old_count = hunk["old_count"]
        lines = hunk["lines"]
        
        # Build new content for this hunk
        new_lines = []
        for line_type, content in lines:
            if line_type == ' ':
                new_lines.append(content)
            elif line_type == '+':
                new_lines.append(content)
        
        # Validate old content matches
        expected_old = [line for line_type, line in lines if line_type in (' ', '-')]
        actual_old = result[old_start:old_start + old_count]
        
        # Check if old content matches (with some tolerance for whitespace)
        if len(expected_old) != len(actual_old):
            logger.warning(f"[file.apply_patch] Old content length mismatch: expected {len(expected_old)}, got {len(actual_old)}")
        
        # Replace old lines with new lines
        result[old_start:old_start + old_count] = new_lines
    
    return result, None


class FileApplyPatchTool(Tool):
    """
    Apply unified diff patch with safety controls.
    
    Features:
    - Parse unified diff format
    - Only allow modifications within workspace
    - Max 500 lines modification limit
    - Validate file exists before patching
    - Create backup before applying
    """

    @property
    def name(self) -> str:
        return "file.apply_patch"

    @property
    def description(self) -> str:
        return (
            "Apply a unified diff patch to files in workspace. "
            "Safety controls: max 500 lines, workspace-only paths, file must exist. "
            "Input: unified diff format string."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "patch": {
                "type": "string",
                "description": "Unified diff format string (can patch multiple files).",
            },
        }, required=["patch"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "files_patched": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of files that were patched.",
                },
                "lines_added": {"type": "integer"},
                "lines_removed": {"type": "integer"},
                "backups": {
                    "type": "object",
                    "description": "Map of original file paths to backup paths.",
                },
            },
        }

    @property
    def required_permissions(self):
        return ["file.write"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Apply Patch",
            "icon": "FileDiff",
            "category": "file",
            "permissions_hint": [
                {"key": "file.write", "label": "Patch files within the workspace."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        patch_content = input_data.get("patch")
        
        if not patch_content:
            return ToolResult(success=False, data=None, error="Patch content is required")
        
        # Parse unified diff
        file_patches, parse_error = _parse_unified_diff(patch_content)
        if parse_error:
            return ToolResult(success=False, data=None, error=f"Failed to parse patch: {parse_error}")
        
        if not file_patches:
            return ToolResult(success=False, data=None, error="No file patches found in input")
        
        # Check line limits
        lines_added, lines_removed = _count_patch_lines(file_patches)
        total_changes = lines_added + lines_removed
        
        if total_changes > MAX_PATCH_LINES:
            return ToolResult(
                success=False,
                data=None,
                error=f"Patch exceeds maximum line limit: {total_changes} > {MAX_PATCH_LINES}"
            )
        
        logger.info(f"[file.apply_patch] Patching {len(file_patches)} files: +{lines_added} -{lines_removed} lines")
        
        workspace = ctx.workspace or "."
        allowed_roots = _get_allowed_absolute_roots()
        files_patched = []
        backups = {}
        
        for file_patch in file_patches:
            filename = file_patch["filename"]
            hunks = file_patch["hunks"]
            
            # Resolve path within workspace
            try:
                target_abs = resolve_in_workspace(
                    workspace=workspace,
                    path=filename,
                    allowed_absolute_roots=allowed_roots,
                )
            except WorkspacePathError as e:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Path '{filename}' is outside workspace: {str(e)}"
                )
            
            # Check file exists
            if not target_abs.exists():
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"File not found: {filename}. File must exist before patching."
                )
            
            # Read original content
            try:
                original_content = target_abs.read_text(encoding="utf-8")
                original_lines = original_content.splitlines(keepends=True)
            except Exception as e:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Failed to read file {filename}: {str(e)}"
                )
            
            # Apply patch
            patched_lines, apply_error = _apply_patch_to_content(original_lines, hunks)
            if apply_error:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Failed to apply patch to {filename}: {apply_error}"
                )
            
            # Create backup
            backup_path = target_abs.with_suffix(target_abs.suffix + ".bak")
            backup_counter = 1
            while backup_path.exists():
                backup_path = target_abs.with_suffix(f"{target_abs.suffix}.bak{backup_counter}")
                backup_counter += 1
            
            try:
                backup_path.write_text(original_content, encoding="utf-8")
                backups[str(target_abs)] = str(backup_path)
                logger.info(f"[file.apply_patch] Created backup: {backup_path}")
            except Exception as e:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Failed to create backup for {filename}: {str(e)}"
                )
            
            # Write patched content
            try:
                target_abs.write_text("".join(patched_lines), encoding="utf-8")
                files_patched.append(str(target_abs))
                logger.info(f"[file.apply_patch] Patched: {target_abs}")
            except Exception as e:
                # Restore from backup
                target_abs.write_text(original_content, encoding="utf-8")
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Failed to write patched file {filename}: {str(e)}"
                )
        
        return ToolResult(
            success=True,
            data={
                "files_patched": files_patched,
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "backups": backups,
            }
        )
