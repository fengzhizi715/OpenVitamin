import psutil
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class SystemCpuTool(Tool):
    @property
    def name(self) -> str:
        return "system.cpu"

    @property
    def description(self) -> str:
        return "Get CPU usage information: overall percentage, per-core usage, count, frequency."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "per_cpu": {
                "type": "boolean",
                "description": "Whether to return per-core CPU usage (default: false).",
                "default": False
            },
            "interval": {
                "type": "number",
                "description": "Sampling interval in seconds for CPU percentage (default: 0.1).",
                "default": 0.1,
                "minimum": 0.1,
                "maximum": 1.0
            }
        })

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "percent": {"type": "number"},
                "per_cpu": {"type": "array", "items": {"type": "number"}},
                "freq": {"type": "object"}
            }
        }

    @property
    def required_permissions(self):
        return ["system.info"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "System CPU",
            "icon": "Cpu",
            "category": "system",
            "permissions_hint": [
                {"key": "system.info", "label": "Access system information."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            per_cpu = input_data.get("per_cpu", False)
            interval = input_data.get("interval", 0.1)

            # 权限检查
            if ctx.permissions and not ctx.permissions.get("system.info"):
                return ToolResult(
                    success=False,
                    data=None,
                    error="Permission denied: system.info permission required"
                )

            cpu_count = psutil.cpu_count()
            cpu_percent = psutil.cpu_percent(interval=interval)
            cpu_freq = psutil.cpu_freq()

            result: Dict[str, Any] = {
                "count": cpu_count,
                "percent": cpu_percent,
            }

            if per_cpu:
                result["per_cpu"] = psutil.cpu_percent(interval=interval, percpu=True)

            if cpu_freq:
                result["freq"] = {
                    "current": cpu_freq.current,
                    "min": cpu_freq.min,
                    "max": cpu_freq.max
                }

            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
