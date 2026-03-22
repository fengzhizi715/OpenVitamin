import subprocess
import sys
import tempfile
import os
import shutil
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema

class PythonRunTool(Tool):
    @property
    def name(self) -> str:
        return "python.run"

    @property
    def description(self) -> str:
        return "Run Python code in a sandboxed environment and return stdout/stderr."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "code": {"type": "string", "description": "The Python code to execute."}
        }, required=["code"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "exit_code": {"type": "integer"},
            },
            "required": ["stdout", "stderr", "exit_code"],
        }

    @property
    def required_permissions(self):
        return ["python.run"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Python Run",
            "icon": "Code2",
            "category": "python",
            "permissions_hint": [
                {"key": "python.run", "label": "Execute Python code in sandbox."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        code = input_data.get("code")
        if not code:
            return ToolResult(success=False, data=None, error="Code is required")

        # Simple sandbox using a separate process and timeout
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode='w', encoding='utf-8') as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            # Try to use conda environment if available
            conda_env = os.getenv("CONDA_DEFAULT_ENV", "ai-inference-platform")
            python_cmd = None
            
            # Check if conda is available
            if shutil.which("conda"):
                # Use conda run to execute in the specified environment
                python_cmd = ["conda", "run", "-n", conda_env, "--no-capture-output", "python", tmp_path]
            else:
                # Fallback to sys.executable
                python_cmd = [sys.executable, tmp_path]
            
            result = subprocess.run(
                python_cmd,
                capture_output=True,
                text=True,
                timeout=10,  # 10 seconds timeout
                cwd=ctx.workspace,
            )
            
            output = {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode
            }
            
            return ToolResult(success=True, data=output)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, data=None, error="Execution timed out (max 10s)")
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
