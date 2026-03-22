"""
SafeShellExecutor - Secure shell command execution for AI programming agent.

Security controls:
- cwd forced to session.workspace
- Block sudo
- Block "../" path traversal
- Timeout (default 60s)
- Output size limit (50KB)
- Command count limit per session (default 20)
"""
import asyncio
import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from log import logger


# Default security configuration
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MAX_OUTPUT_SIZE = 50 * 1024  # 50KB
DEFAULT_MAX_COMMANDS_PER_SESSION = 20

# Blocked command patterns (security)
BLOCKED_PATTERNS = [
    "sudo",
    "su -",
    "su root",
    "../",
    "..\\",
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",  # Fork bomb
    "chmod 777 /",
    "chown -R",
    "> /dev/",
    "mkfs.ext",
    "fdisk",
    "parted",
]

# Allowed command prefixes for common development tools
ALLOWED_COMMAND_PREFIXES = [
    # Python
    "python", "python3", "pip", "pip3", "pytest", "pytest-3", "ruff", "black", "mypy", "uv", "poetry",
    # Node
    "npm", "node", "npx", "yarn", "pnpm",
    # Rust
    "cargo", "rustc", "rustup",
    # Go
    "go",
    # Java
    "mvn", "gradle", "java", "javac",
    # Build tools
    "make", "cmake",
    # Git
    "git",
    # Generic
    "ls", "cat", "grep", "find", "echo", "pwd", "mkdir", "touch", "rm", "cp", "mv",
]


@dataclass
class ShellExecutionResult:
    """Result of safe shell execution."""
    success: bool
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float
    error: Optional[str] = None
    command_count: int = 0  # Current session command count after execution


class SafeShellExecutor:
    """
    Secure shell command executor for AI programming agent.
    
    All shell commands (shell.run, project.test, project.build) must go through this executor
    to ensure unified security controls and shared command count limits.
    
    Usage:
        executor = SafeShellExecutor(workspace="/path/to/project")
        result = await executor.execute("pytest")
    """
    
    def __init__(
        self,
        workspace: str,
        session_id: str = "default",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE,
        max_commands_per_session: int = DEFAULT_MAX_COMMANDS_PER_SESSION,
        command_counts: Optional[Dict[str, int]] = None,  # Shared counter across instances
        extra_blocked_patterns: Optional[List[str]] = None,  # Additional blocked patterns from config
        allowed_commands: Optional[List[str]] = None,  # Whitelist (None = allow all non-blocked)
        max_timeout: int = 300,  # Maximum allowed timeout
    ):
        self.workspace = os.path.abspath(workspace)
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds
        self.max_output_size = max_output_size
        self.max_commands_per_session = max_commands_per_session
        self.max_timeout = max_timeout
        # Shared command counter (keyed by session_id)
        self._command_counts = command_counts if command_counts is not None else {}
        # Extra blocked patterns from config (merged with default)
        self._extra_blocked_patterns = extra_blocked_patterns or []
        # Allowed commands whitelist (None = allow all non-blocked)
        self._allowed_commands = allowed_commands
    
    def get_command_count(self) -> int:
        """Get current command count for this session."""
        return self._command_counts.get(self.session_id, 0)
    
    def _increment_command_count(self) -> int:
        """Increment and return command count for this session."""
        current = self._command_counts.get(self.session_id, 0)
        new_count = current + 1
        self._command_counts[self.session_id] = new_count
        return new_count
    
    def _validate_command(self, command: str) -> Optional[str]:
        """
        Validate command for security issues.
        
        Returns error message if validation fails, None if OK.
        """
        if not command or not command.strip():
            return "Command is empty"
        
        cmd_lower = command.lower()
        
        # Check default blocked patterns
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in cmd_lower:
                return f"Command contains blocked pattern: {pattern}"
        
        # Check extra blocked patterns from config
        for pattern in self._extra_blocked_patterns:
            if pattern.lower() in cmd_lower:
                return f"Command contains blocked pattern: {pattern}"
        
        # Check allowed commands whitelist (if configured)
        if self._allowed_commands:
            parts = shlex.split(command)
            base_cmd = parts[0] if parts else ""
            if base_cmd not in self._allowed_commands and command not in self._allowed_commands:
                return f"Command '{base_cmd}' not in allowed list"
        
        # Check for path traversal
        if "../" in command or "..\\" in command:
            return "Command contains path traversal pattern (../)"
        
        # Check for absolute paths outside workspace
        # Allow /usr/bin, /bin, etc. but block other absolute paths
        parts = shlex.split(command)
        for part in parts:
            if part.startswith("/") and not part.startswith(("/usr", "/bin", "/opt", "/etc", "/var", "/tmp")):
                # Check if it's within workspace
                try:
                    rel = os.path.relpath(part, self.workspace)
                    if rel.startswith(".."):
                        return f"Path '{part}' is outside workspace"
                except ValueError:
                    pass  # Different drives on Windows
        
        # Check command count limit
        current_count = self.get_command_count()
        if current_count >= self.max_commands_per_session:
            return f"Maximum command count ({self.max_commands_per_session}) exceeded for session"
        
        return None
    
    async def execute(
        self,
        command: str,
        env: Optional[Dict[str, str]] = None,
        timeout_override: Optional[int] = None,
    ) -> ShellExecutionResult:
        """
        Execute a shell command safely.
        
        Args:
            command: Shell command to execute
            env: Optional environment variables
            timeout_override: Optional timeout override (seconds)
        
        Returns:
            ShellExecutionResult with exit_code, stdout, stderr, etc.
        """
        start_time = time.time()
        
        # Validate command
        validation_error = self._validate_command(command)
        if validation_error:
            logger.warning(f"[SafeShellExecutor] Command blocked: {validation_error}")
            return ShellExecutionResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=validation_error,
                timed_out=False,
                duration_seconds=0,
                error=validation_error,
                command_count=self.get_command_count(),
            )
        
        # Use timeout override or default, but enforce max_timeout
        timeout = min(timeout_override or self.timeout_seconds, self.max_timeout)
        timeout = max(timeout, 1)  # Minimum 1 second
        
        # Build environment
        process_env = os.environ.copy()
        process_env["PWD"] = self.workspace
        if env:
            process_env.update(env)
        
        logger.info(f"[SafeShellExecutor] Executing: {command} (timeout: {timeout}s, cwd: {self.workspace})")
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace,
                env=process_env,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                timed_out = False
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                timed_out = True
                stdout = b""
                stderr = b"Command timed out"
            
            duration = time.time() - start_time
            
            # Decode and truncate output
            stdout_str = stdout.decode("utf-8", errors="replace")[:self.max_output_size]
            stderr_str = stderr.decode("utf-8", errors="replace")[:self.max_output_size]
            
            # Increment command count
            new_count = self._increment_command_count()
            
            success = not timed_out and process.returncode == 0
            
            logger.info(
                f"[SafeShellExecutor] Command finished: exit_code={process.returncode}, "
                f"duration={duration:.2f}s, success={success}, count={new_count}"
            )
            
            return ShellExecutionResult(
                success=success,
                command=command,
                exit_code=process.returncode if not timed_out else -1,
                stdout=stdout_str,
                stderr=stderr_str,
                timed_out=timed_out,
                duration_seconds=round(duration, 2),
                command_count=new_count,
            )
            
        except Exception as e:
            logger.error(f"[SafeShellExecutor] Execution error: {e}")
            return ShellExecutionResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=False,
                duration_seconds=time.time() - start_time,
                error=str(e),
                command_count=self.get_command_count(),
            )
    
    async def execute_test(self, test_command: str) -> ShellExecutionResult:
        """
        Execute test command.
        
        This is a convenience method for project.test skill.
        """
        return await self.execute(test_command, timeout_override=120)  # Tests get longer timeout
    
    async def execute_build(self, build_command: str) -> ShellExecutionResult:
        """
        Execute build command.
        
        This is a convenience method for project.build skill.
        """
        return await self.execute(build_command, timeout_override=180)  # Builds get longer timeout


# Global command counter (shared across all SafeShellExecutor instances)
# Keyed by session_id
_global_command_counts: Dict[str, int] = {}


def get_safe_shell_executor(
    workspace: str,
    session_id: str = "default",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE,
    max_commands_per_session: int = DEFAULT_MAX_COMMANDS_PER_SESSION,
    extra_blocked_patterns: Optional[List[str]] = None,
    allowed_commands: Optional[List[str]] = None,
    max_timeout: int = 300,
) -> SafeShellExecutor:
    """
    Get a SafeShellExecutor instance with shared command counter.
    
    This ensures command count limits are enforced across the entire session.
    All shell executions (shell.run, project.test, project.build) should use this factory.
    """
    return SafeShellExecutor(
        workspace=workspace,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
        max_output_size=max_output_size,
        max_commands_per_session=max_commands_per_session,
        command_counts=_global_command_counts,
        extra_blocked_patterns=extra_blocked_patterns,
        allowed_commands=allowed_commands,
        max_timeout=max_timeout,
    )
