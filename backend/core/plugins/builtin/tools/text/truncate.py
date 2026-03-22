from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class TextTruncateTool(Tool):
    @property
    def name(self) -> str:
        return "text.truncate"

    @property
    def description(self) -> str:
        return "Truncate text to a maximum length with optional ellipsis."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "text": {
                "type": "string",
                "description": "The text to truncate."
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum length of the truncated text."
            },
            "ellipsis": {
                "type": "string",
                "description": "String to append when truncating (default: '...').",
                "default": "..."
            },
            "mode": {
                "type": "string",
                "description": "Truncation mode: 'start' (keep end), 'end' (keep start), 'middle' (keep both ends).",
                "enum": ["start", "end", "middle"],
                "default": "end"
            }
        }, required=["text", "max_length"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "string"}

    @property
    def required_permissions(self):
        return []

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Text Truncate",
            "icon": "FileText",
            "category": "text",
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            text = input_data.get("text", "")
            max_length = input_data.get("max_length")
            ellipsis = input_data.get("ellipsis", "...")
            mode = input_data.get("mode", "end")

            if max_length is None:
                return ToolResult(success=False, data=None, error="max_length is required")

            if len(text) <= max_length:
                return ToolResult(success=True, data=text)

            ellipsis_len = len(ellipsis)
            available_length = max_length - ellipsis_len

            if mode == "end":
                # Keep start
                result = text[:available_length] + ellipsis
            elif mode == "start":
                # Keep end
                result = ellipsis + text[-available_length:]
            elif mode == "middle":
                # Keep both ends
                half = available_length // 2
                result = text[:half] + ellipsis + text[-half:]
            else:
                return ToolResult(success=False, data=None, error=f"Invalid mode: {mode}")

            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
