"""
project.build Tool - Execute project build safely.

Features:
- Reads session.state.project_context.build_command
- Uses SafeShellExecutor for security
- Returns stdout/stderr/exit_code
- If no build_command, returns success directly
"""
from typing import Any, Dict, List

from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.safe_shell import get_safe_shell_executor
from log import logger


class ProjectBuildTool(Tool):
    """
    Execute project build safely.
    
    Reads build_command from project_context (stored in session.state).
    Uses SafeShellExecutor for security controls.
    If no build_command, returns success directly.
    """

    @property
    def name(self) -> str:
        return "project.build"

    @property
    def description(self) -> str:
        return (
            "Execute project build. Reads build_command from project_context "
            "(requires project.scan to be called first). "
            "Uses SafeShellExecutor with security controls. "
            "If no build_command configured, returns success directly."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "project_context": {
                "type": "object",
                "description": "Project context from session.state.project_context (optional, will use if not provided).",
                "properties": {
                    "build_command": {"type": "string"},
                    "project_root": {"type": "string"},
                },
            },
            "extra_args": {
                "type": "string",
                "description": "Extra arguments to append to build command (optional).",
            },
        }, required=[])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "build_command": {"type": "string"},
                "exit_code": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "timed_out": {"type": "boolean"},
                "duration_seconds": {"type": "number"},
                "command_count": {"type": "integer"},
                "skipped": {"type": "boolean", "description": "True if no build command configured."},
            },
        }

    @property
    def required_permissions(self) -> List[str]:
        return ["shell.run"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Project Build",
            "icon": "Wrench",
            "category": "project",
            "permissions_hint": [{"key": "shell.run", "label": "Execute build commands in workspace."}],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        # Get project context from input or context
        project_context = input_data.get("project_context")
        
        # If not provided, try to get from context (passed by runtime)
        if not project_context:
            project_context = getattr(ctx, "project_context", None)
        
        # If still not available, return error
        if not project_context:
            return ToolResult(
                success=False,
                error="project_context not found. Run project.scan first.",
            )
        
        # Get build command
        build_command = project_context.get("build_command")
        if not build_command:
            # No build command - return success
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "build_command": None,
                    "exit_code": 0,
                    "stdout": "No build command configured for this project. Skipping build step.",
                    "stderr": "",
                    "timed_out": False,
                    "duration_seconds": 0,
                    "command_count": 0,
                    "skipped": True,
                },
            )
        
        # Get project root
        project_root = project_context.get("project_root") or ctx.workspace or "."
        
        # Append extra args if provided
        extra_args = input_data.get("extra_args")
        if extra_args:
            build_command = f"{build_command} {extra_args}"
        
        # Execute using SafeShellExecutor
        session_id = getattr(ctx, "session_id", "default") or "default"
        executor = get_safe_shell_executor(
            workspace=project_root,
            session_id=session_id,
        )
        
        logger.info(f"[project.build] Executing: {build_command} in {project_root}")
        
        result = await executor.execute_build(build_command)
        
        return ToolResult(
            success=result.success,
            data={
                "success": result.success,
                "build_command": result.command,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
                "duration_seconds": result.duration_seconds,
                "command_count": result.command_count,
                "error": result.error,
                "skipped": False,
            },
            error=result.error,
        )
