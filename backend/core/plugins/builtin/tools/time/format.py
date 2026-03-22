from datetime import datetime
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class TimeFormatTool(Tool):
    @property
    def name(self) -> str:
        return "time.format"

    @property
    def description(self) -> str:
        return "Format a date/time string or Unix timestamp into a different format."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "input": {
                "type": ["string", "number"],
                "description": "Input date/time: ISO 8601 string or Unix timestamp (integer)."
            },
            "output_format": {
                "type": "string",
                "description": "Output format string (Python strftime format, e.g., '%Y-%m-%d %H:%M:%S')."
            },
            "input_format": {
                "type": "string",
                "description": "Input format string (Python strptime format). Only needed if input is a non-standard string."
            }
        }, required=["input", "output_format"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "string"}

    @property
    def required_permissions(self):
        return []

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Time Format",
            "icon": "Clock",
            "category": "time",
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            input_val = input_data.get("input")
            output_format = input_data.get("output_format")
            input_format = input_data.get("input_format")

            if input_val is None:
                return ToolResult(success=False, data=None, error="input is required")
            if not output_format:
                return ToolResult(success=False, data=None, error="output_format is required")

            # Parse input
            if isinstance(input_val, (int, float)):
                # Unix timestamp
                dt = datetime.fromtimestamp(input_val)
            elif isinstance(input_val, str):
                if input_format:
                    dt = datetime.strptime(input_val, input_format)
                else:
                    # Try ISO format first
                    try:
                        dt = datetime.fromisoformat(input_val.replace("Z", "+00:00"))
                    except ValueError:
                        return ToolResult(
                            success=False,
                            data=None,
                            error="Cannot parse input. Provide input_format for non-ISO strings."
                        )
            else:
                return ToolResult(success=False, data=None, error="input must be string or number")

            # Format output
            result = dt.strftime(output_format)
            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
