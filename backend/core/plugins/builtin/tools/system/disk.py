import psutil
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class SystemDiskTool(Tool):
    @property
    def name(self) -> str:
        return "system.disk"

    @property
    def description(self) -> str:
        return "Get disk usage information for a path or all mounted partitions: total, used, free, percentage."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "path": {
                "type": "string",
                "description": "Path to check disk usage for (default: '/'). If not provided, returns all partitions.",
                "default": "/"
            },
            "all": {
                "type": "boolean",
                "description": "Whether to return all mounted partitions (default: false).",
                "default": False
            }
        })

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": ["object", "array"],
            "description": "Single partition object or array of partition objects"
        }

    @property
    def required_permissions(self):
        return ["system.info"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "System Disk",
            "icon": "HardDrive",
            "category": "system",
            "permissions_hint": [
                {"key": "system.info", "label": "Access system information."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            path = input_data.get("path", "/")
            all_partitions = input_data.get("all", False)

            # 权限检查
            if ctx.permissions and not ctx.permissions.get("system.info"):
                return ToolResult(
                    success=False,
                    data=None,
                    error="Permission denied: system.info permission required"
                )

            if all_partitions:
                # Return all partitions
                partitions = []
                for partition in psutil.disk_partitions():
                    try:
                        usage = psutil.disk_usage(partition.mountpoint)
                        partitions.append({
                            "device": partition.device,
                            "mountpoint": partition.mountpoint,
                            "fstype": partition.fstype,
                            "total": usage.total,
                            "used": usage.used,
                            "free": usage.free,
                            "percent": usage.percent
                        })
                    except PermissionError:
                        continue
                return ToolResult(success=True, data=partitions)
            else:
                # Return usage for specific path
                usage = psutil.disk_usage(path)
                result = {
                    "path": path,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent
                }
                return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
