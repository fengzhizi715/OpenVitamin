import json
from typing import Dict, Any, Optional
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from log import logger
from core.plugins.builtin.tools.http.security import check_http_permission_and_url

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class HttpGetTool(Tool):
    @property
    def name(self) -> str:
        return "http.get"

    @property
    def description(self) -> str:
        return "Make an HTTP GET request to a URL. Returns JSON or text response."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "url": {
                "type": "string",
                "description": "The URL to request (e.g., https://api.example.com/data)."
            },
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers as key-value pairs.",
                "additionalProperties": {"type": "string"}
            },
            "timeout": {
                "type": "number",
                "description": "Request timeout in seconds (default: 30).",
                "default": 30
            },
            "params": {
                "type": "object",
                "description": "Optional query parameters as key-value pairs.",
                "additionalProperties": {"type": "string"}
            }
        }, required=["url"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status_code": {"type": "integer"},
                "headers": {"type": "object"},
                "body": {"type": ["string", "object"]},
                "content_type": {"type": "string"}
            }
        }

    @property
    def required_permissions(self):
        return ["net.http"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "HTTP GET",
            "icon": "Globe",
            "category": "http",
            "permissions_hint": [
                {"key": "net.http", "label": "Requires network access (HTTP)."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        if not HTTPX_AVAILABLE:
            return ToolResult(
                success=False,
                data=None,
                error="httpx is not installed. Please install it: pip install httpx"
            )

        url = input_data.get("url")
        if not url:
            return ToolResult(success=False, data=None, error="URL is required")

        headers = input_data.get("headers") or {}
        timeout = input_data.get("timeout", 30)
        params = input_data.get("params")

        ok, err = check_http_permission_and_url(url, ctx)
        if not ok:
            return ToolResult(success=False, data=None, error=err or "Permission denied")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers=headers, params=params)
                
                # 尝试解析 JSON，否则返回文本
                content_type = response.headers.get("content-type", "")
                body: Any = response.text
                if "application/json" in content_type:
                    try:
                        body = response.json()
                    except Exception:
                        pass

                return ToolResult(
                    success=True,
                    data={
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": body,
                        "content_type": content_type
                    }
                )
        except httpx.TimeoutException:
            return ToolResult(success=False, data=None, error=f"Request timeout after {timeout}s")
        except Exception as e:
            logger.exception(f"[http.get] Request failed: {e}")
            return ToolResult(success=False, data=None, error=f"HTTP request failed: {str(e)}")
