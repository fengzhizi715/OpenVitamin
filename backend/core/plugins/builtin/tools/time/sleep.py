import asyncio
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from log import logger


class TimeSleepTool(Tool):
    @property
    def name(self) -> str:
        return "time.sleep"

    @property
    def description(self) -> str:
        return "Sleep/wait for a specified number of seconds. Useful for rate limiting or delays."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "seconds": {
                "type": "number",
                "description": "Number of seconds to sleep (can be decimal, e.g., 0.5 for 500ms). Maximum: 60 seconds.",
                "minimum": 0,
                "maximum": 60
            }
        }, required=["seconds"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"slept": {"type": "number"}}}

    @property
    def required_permissions(self):
        return []

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Time Sleep",
            "icon": "Clock",
            "category": "time",
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            seconds = input_data.get("seconds")
            if seconds is None:
                return ToolResult(success=False, data=None, error="seconds is required")

            if seconds < 0 or seconds > 60:
                return ToolResult(
                    success=False,
                    data=None,
                    error="seconds must be between 0 and 60"
                )

            logger.info(f"[time.sleep] Sleeping for {seconds} seconds")
            await asyncio.sleep(seconds)

            return ToolResult(success=True, data={"slept": seconds})
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
