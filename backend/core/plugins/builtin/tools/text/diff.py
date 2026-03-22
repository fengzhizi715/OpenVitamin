import difflib
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema


class TextDiffTool(Tool):
    @property
    def name(self) -> str:
        return "text.diff"

    @property
    def description(self) -> str:
        return "Compute the difference between two texts. Returns unified diff format or line-by-line comparison."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "text1": {
                "type": "string",
                "description": "The original text (or file path)."
            },
            "text2": {
                "type": "string",
                "description": "The modified text (or file path)."
            },
            "format": {
                "type": "string",
                "description": "Output format: 'unified' (unified diff), 'context' (context diff), 'html' (HTML table), 'lines' (line-by-line array).",
                "enum": ["unified", "context", "html", "lines"],
                "default": "unified"
            },
            "context": {
                "type": "integer",
                "description": "Number of context lines around changes (for unified/context format, default: 3).",
                "default": 3
            },
            "fromfile": {
                "type": "string",
                "description": "Label for the first text in diff output (default: 'text1').",
                "default": "text1"
            },
            "tofile": {
                "type": "string",
                "description": "Label for the second text in diff output (default: 'text2').",
                "default": "text2"
            }
        }, required=["text1", "text2"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": ["string", "array"],
            "description": "Diff output: string for unified/context/html, array for lines format"
        }

    @property
    def required_permissions(self):
        return []

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Text Diff",
            "icon": "FileText",
            "category": "text",
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            text1 = input_data.get("text1", "")
            text2 = input_data.get("text2", "")
            format_type = input_data.get("format", "unified")
            context = input_data.get("context", 3)
            fromfile = input_data.get("fromfile", "text1")
            tofile = input_data.get("tofile", "text2")

            # Split into lines for diff
            lines1 = text1.splitlines(keepends=True)
            lines2 = text2.splitlines(keepends=True)

            if format_type == "unified":
                diff = list(difflib.unified_diff(
                    lines1, lines2,
                    fromfile=fromfile,
                    tofile=tofile,
                    lineterm="",
                    n=context
                ))
                result = "".join(diff)
            elif format_type == "context":
                diff = list(difflib.context_diff(
                    lines1, lines2,
                    fromfile=fromfile,
                    tofile=tofile,
                    lineterm="",
                    n=context
                ))
                result = "".join(diff)
            elif format_type == "html":
                diff = difflib.HtmlDiff()
                result = diff.make_file(
                    lines1, lines2,
                    fromdesc=fromfile,
                    todesc=tofile,
                    context=context,
                    numlines=context
                )
            elif format_type == "lines":
                # Return line-by-line comparison
                matcher = difflib.SequenceMatcher(None, lines1, lines2)
                result = []
                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    if tag == "equal":
                        result.extend([("=", line) for line in lines1[i1:i2]])
                    elif tag == "delete":
                        result.extend([("-", line) for line in lines1[i1:i2]])
                    elif tag == "insert":
                        result.extend([("+", line) for line in lines2[j1:j2]])
                    elif tag == "replace":
                        result.extend([("-", line) for line in lines1[i1:i2]])
                        result.extend([("+", line) for line in lines2[j1:j2]])
            else:
                return ToolResult(success=False, data=None, error=f"Invalid format: {format_type}")

            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
