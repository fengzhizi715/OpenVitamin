import psutil
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class SystemMemoryTool(Tool):
    @property
    def name(self) -> str:
        return "system.memory"

    @property
    def description(self) -> str:
        return "Get system memory (RAM) usage information: total, available, used, percentage."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({})

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "total": {"type": "integer"},
                "available": {"type": "integer"},
                "used": {"type": "integer"},
                "percent": {"type": "number"}
            }
        }

    @property
    def required_permissions(self):
        return ["system.info"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "System Memory",
            "icon": "MemoryStick",
            "category": "system",
            "permissions_hint": [
                {"key": "system.info", "label": "Access system information."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            # 权限检查
            if ctx.permissions and not ctx.permissions.get("system.info"):
                return ToolResult(
                    success=False,
                    data=None,
                    error="Permission denied: system.info permission required"
                )

            mem = psutil.virtual_memory()

            result = {
                "total": mem.total,
                "available": mem.available,
                "used": mem.used,
                "percent": mem.percent
            }

            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
