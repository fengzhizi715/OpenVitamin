from datetime import datetime, timezone
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class TimeNowTool(Tool):
    @property
    def name(self) -> str:
        return "time.now"

    @property
    def description(self) -> str:
        return "Get the current date and time. Returns ISO 8601 format string or Unix timestamp."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "format": {
                "type": "string",
                "description": "Output format: 'iso' (ISO 8601), 'unix' (Unix timestamp), 'custom' (use format string).",
                "enum": ["iso", "unix", "custom"],
                "default": "iso"
            },
            "format_string": {
                "type": "string",
                "description": "Custom format string (Python strftime format, e.g., '%Y-%m-%d %H:%M:%S'). Used when format='custom'."
            },
            "timezone": {
                "type": "string",
                "description": "Timezone name (e.g., 'UTC', 'Asia/Shanghai', 'America/New_York'). Default: UTC.",
                "default": "UTC"
            }
        })

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": ["string", "number"],
            "description": "ISO string or Unix timestamp"
        }

    @property
    def required_permissions(self):
        return []

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Time Now",
            "icon": "Clock",
            "category": "time",
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            format_type = input_data.get("format", "iso")
            format_string = input_data.get("format_string")
            tz_name = input_data.get("timezone", "UTC")

            # Get timezone
            if tz_name == "UTC":
                tz = timezone.utc
            else:
                try:
                    import pytz
                    tz = pytz.timezone(tz_name)
                except ImportError:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"pytz is not installed. Install it for timezone support: pip install pytz"
                    )
                except Exception as e:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"Invalid timezone: {tz_name}. Error: {str(e)}"
                    )

            now = datetime.now(tz)

            if format_type == "iso":
                result = now.isoformat()
            elif format_type == "unix":
                result = int(now.timestamp())
            elif format_type == "custom":
                if not format_string:
                    return ToolResult(success=False, data=None, error="format_string is required when format='custom'")
                result = now.strftime(format_string)
            else:
                return ToolResult(success=False, data=None, error=f"Invalid format: {format_type}")

            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
