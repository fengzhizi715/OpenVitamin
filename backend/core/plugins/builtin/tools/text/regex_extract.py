import re
from typing import Dict, Any, List
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class TextRegexExtractTool(Tool):
    @property
    def name(self) -> str:
        return "text.regex_extract"

    @property
    def description(self) -> str:
        return "Extract text matching a regular expression pattern. Returns array of matches or captured groups."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "text": {
                "type": "string",
                "description": "The text to search."
            },
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern (e.g., r'\\d+' for numbers, r'\\w+@\\w+\\.\\w+' for emails)."
            },
            "flags": {
                "type": "integer",
                "description": "Regex flags: 0=none, 1=IGNORECASE, 2=MULTILINE, 4=DOTALL, 8=VERBOSE. Can combine (e.g., 1|2).",
                "default": 0
            },
            "all": {
                "type": "boolean",
                "description": "Whether to return all matches (default: true) or just the first.",
                "default": True
            },
            "groups": {
                "type": "boolean",
                "description": "Whether to return captured groups as arrays (default: false, returns full match).",
                "default": False
            }
        }, required=["text", "pattern"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "array",
            "items": {"type": ["string", "array"]}
        }

    @property
    def required_permissions(self):
        return []

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Regex Extract",
            "icon": "FileText",
            "category": "text",
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            text = input_data.get("text", "")
            pattern = input_data.get("pattern")
            flags = input_data.get("flags", 0)
            all_matches = input_data.get("all", True)
            return_groups = input_data.get("groups", False)

            if not pattern:
                return ToolResult(success=False, data=None, error="pattern is required")

            # Convert flags integer to re flags
            re_flags = 0
            if flags & 1:
                re_flags |= re.IGNORECASE
            if flags & 2:
                re_flags |= re.MULTILINE
            if flags & 4:
                re_flags |= re.DOTALL
            if flags & 8:
                re_flags |= re.VERBOSE

            try:
                compiled_pattern = re.compile(pattern, re_flags)
            except re.error as e:
                return ToolResult(success=False, data=None, error=f"Invalid regex pattern: {str(e)}")

            if return_groups:
                # Return captured groups
                if all_matches:
                    matches = compiled_pattern.findall(text)
                else:
                    match = compiled_pattern.search(text)
                    matches = [match.groups()] if match else []
            else:
                # Return full matches
                if all_matches:
                    matches = compiled_pattern.findall(text)
                else:
                    match = compiled_pattern.search(text)
                    matches = [match.group(0)] if match else []

            return ToolResult(success=True, data=matches)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
