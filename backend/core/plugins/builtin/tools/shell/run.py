import os
import re
from typing import Dict, Any, List
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from core.tools.safe_shell import get_safe_shell_executor
from log import logger


# Note: blocked/allowed commands are now handled by SafeShellExecutor
# Config values are read in _get_shell_config() and passed to SafeShellExecutor


def _get_shell_config() -> Dict[str, Any]:
    """Get shell tool configuration from settings."""
    try:
        from config.settings import settings
        return {
            "enabled": getattr(settings, "tool_shell_enabled", True),
            "allowed_commands": getattr(settings, "tool_shell_allowed_commands", None),  # None = allow all
            "blocked_commands": getattr(settings, "tool_shell_blocked_commands", []),  # Extra blocked patterns
            "default_timeout": getattr(settings, "tool_shell_timeout", 30),
            "max_timeout": getattr(settings, "tool_shell_max_timeout", 300),
            "working_dir": getattr(settings, "tool_shell_working_dir", None),  # None = allow any
        }
    except Exception:
        return {
            "enabled": True,
            "allowed_commands": None,
            "blocked_commands": [],
            "default_timeout": 30,
            "max_timeout": 300,
            "working_dir": None,
        }


class ShellRunTool(Tool):
    """Execute shell commands with security controls."""

    @property
    def name(self) -> str:
        return "shell.run"

    @property
    def description(self) -> str:
        return "Execute shell commands. Returns stdout, stderr, and exit code. Requires 'shell.run' permission."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "command": {
                "type": "string",
                "description": "Shell command to execute."
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30, max: 300).",
                "default": 30
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for command (optional).",
                "default": None
            },
            "env": {
                "type": "object",
                "description": "Environment variables to set (optional).",
                "default": {}
            }
        }, required=["command"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {
            "command": {"type": "string"},
            "exit_code": {"type": "integer"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "timed_out": {"type": "boolean"},
            "duration_seconds": {"type": "number"},
            "command_count": {"type": "integer", "description": "Session command count after this execution"},
        }}

    @property
    def required_permissions(self):
        return ["shell.run"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Shell Run",
            "icon": "Terminal",
            "category": "system",
            "permissions_hint": [
                {"key": "shell.run", "label": "Execute shell commands (requires explicit permission)."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """
        Execute shell command using SafeShellExecutor.
        
        All security controls (blocked patterns, allowed commands, timeout, 
        command count limits) are handled by SafeShellExecutor.
        """
        try:
            command = input_data.get("command")
            timeout = input_data.get("timeout", 30)
            working_dir = input_data.get("working_dir")
            env_vars = input_data.get("env", {})

            if not command:
                return ToolResult(success=False, data=None, error="Command is required")

            # Get config
            config = _get_shell_config()
            
            # Check if shell is enabled
            if not config["enabled"]:
                return ToolResult(success=False, data=None, error="Shell execution is disabled")

            # Determine workspace: prefer explicit input, then tool config, then agent workspace
            workspace = working_dir or config["working_dir"] or ctx.workspace or os.getcwd()

            # 支持用户显式命令：cd /abs/path && <cmd>
            # 若命中则将 workspace 切到该路径，并移除前缀 cd，避免被 SafeShell 的路径检查误拦截
            if isinstance(command, str):
                cmd_stripped = command.strip()
                m = re.match(r"^\s*cd\s+((?:\"[^\"]+\")|(?:'[^']+')|(?:\S+))\s*&&\s*(.+)$", cmd_stripped, re.DOTALL)
                if m:
                    raw_target = m.group(1).strip().strip("\"'")
                    trailing_cmd = (m.group(2) or "").strip()
                    if trailing_cmd:
                        # 校验目标目录：必须存在，且在允许根目录内（默认由 settings.file_read_allowed_roots 控制）
                        target_dir = os.path.abspath(os.path.expanduser(raw_target))
                        if not os.path.isdir(target_dir):
                            return ToolResult(
                                success=False,
                                data=None,
                                error=f"Working directory not found: {target_dir}",
                            )
                        try:
                            from config.settings import settings
                            roots_raw = (getattr(settings, "file_read_allowed_roots", "") or "").strip()
                            allowed_roots = [r.strip() for r in roots_raw.split(",") if r.strip()]
                            if not allowed_roots:
                                allowed_roots = [os.path.expanduser("~")]
                        except Exception:
                            allowed_roots = [os.path.expanduser("~")]

                        def _in_allowed_roots(path: str) -> bool:
                            p = os.path.realpath(path)
                            for root in allowed_roots:
                                rr = os.path.realpath(os.path.abspath(os.path.expanduser(root)))
                                try:
                                    if os.path.commonpath([p, rr]) == rr:
                                        return True
                                except ValueError:
                                    continue
                            return False

                        if not _in_allowed_roots(target_dir):
                            return ToolResult(
                                success=False,
                                data=None,
                                error=f"Path '{target_dir}' is outside allowed roots",
                            )

                        workspace = target_dir
                        command = trailing_cmd
            
            # Get session_id for command count tracking
            session_id = getattr(ctx, "session_id", "default") or "default"
            
            # Create SafeShellExecutor with config-based settings
            executor = get_safe_shell_executor(
                workspace=workspace,
                session_id=session_id,
                timeout_seconds=config["default_timeout"],
                max_timeout=config["max_timeout"],
                extra_blocked_patterns=config["blocked_commands"],
                allowed_commands=config["allowed_commands"],
            )
            
            logger.info(f"[shell.run] Executing via SafeShellExecutor: {command}")
            
            # Execute via SafeShellExecutor
            result = await executor.execute(command, env=env_vars, timeout_override=timeout)
            
            return ToolResult(
                success=result.success,
                data={
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "timed_out": result.timed_out,
                    "duration_seconds": result.duration_seconds,
                    "command_count": result.command_count,
                },
                error=result.error,
            )

        except Exception as e:
            logger.error(f"[shell.run] Error: {e}")
            return ToolResult(success=False, data=None, error=str(e))
