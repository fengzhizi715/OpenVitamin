from typing import Dict, Any, List
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class TextSplitTool(Tool):
    @property
    def name(self) -> str:
        return "text.split"

    @property
    def description(self) -> str:
        return "Split text into parts by delimiter or by length (chunks). Returns array of strings."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "text": {
                "type": "string",
                "description": "The text to split."
            },
            "delimiter": {
                "type": "string",
                "description": "Delimiter to split by (e.g., '\\n', ',', ' '). If not provided, splits by length."
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum length per chunk when splitting by length (ignored if delimiter is provided)."
            },
            "overlap": {
                "type": "integer",
                "description": "Number of characters to overlap between chunks when splitting by length (default: 0).",
                "default": 0
            }
        }, required=["text"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "array",
            "items": {"type": "string"}
        }

    @property
    def required_permissions(self):
        return []

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Text Split",
            "icon": "FileText",
            "category": "text",
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            text = input_data.get("text", "")
            delimiter = input_data.get("delimiter")
            max_length = input_data.get("max_length")
            overlap = input_data.get("overlap", 0)

            if delimiter:
                # Split by delimiter
                parts = text.split(delimiter)
            elif max_length:
                # Split by length with optional overlap
                parts = []
                start = 0
                while start < len(text):
                    end = start + max_length
                    chunk = text[start:end]
                    parts.append(chunk)
                    start = end - overlap
                    if start >= len(text):
                        break
            else:
                return ToolResult(
                    success=False,
                    data=None,
                    error="Either 'delimiter' or 'max_length' must be provided"
                )

            return ToolResult(success=True, data=parts)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
