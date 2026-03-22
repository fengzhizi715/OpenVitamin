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


class HttpRequestTool(Tool):
    @property
    def name(self) -> str:
        return "http.request"

    @property
    def description(self) -> str:
        return "Make an HTTP request with any method (GET, POST, PUT, DELETE, etc.). Supports headers, auth, timeout, and custom body."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "url": {
                "type": "string",
                "description": "The URL to request."
            },
            "method": {
                "type": "string",
                "description": "HTTP method (GET, POST, PUT, DELETE, PATCH, etc.). Default: GET.",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                "default": "GET"
            },
            "body": {
                "type": ["object", "string"],
                "description": "Request body: JSON object (auto-serialized) or raw string."
            },
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers as key-value pairs.",
                "additionalProperties": {"type": "string"}
            },
            "params": {
                "type": "object",
                "description": "Optional query parameters as key-value pairs.",
                "additionalProperties": {"type": "string"}
            },
            "auth": {
                "type": "object",
                "description": "Authentication: {type: 'bearer', token: 'xxx'} or {type: 'basic', username: 'xxx', password: 'xxx'}.",
                "properties": {
                    "type": {"type": "string", "enum": ["bearer", "basic"]},
                    "token": {"type": "string"},
                    "username": {"type": "string"},
                    "password": {"type": "string"}
                }
            },
            "timeout": {
                "type": "number",
                "description": "Request timeout in seconds (default: 30).",
                "default": 30
            },
            "json": {
                "type": "boolean",
                "description": "Whether to send body as JSON (default: true if body is object).",
                "default": None
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
            "display_name": "HTTP Request",
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

        method = input_data.get("method", "GET").upper()
        body = input_data.get("body")
        headers = input_data.get("headers") or {}
        params = input_data.get("params")
        auth_config = input_data.get("auth")
        timeout = input_data.get("timeout", 30)
        send_json = input_data.get("json")

        ok, err = check_http_permission_and_url(url, ctx)
        if not ok:
            return ToolResult(success=False, data=None, error=err or "Permission denied")

        # 处理认证
        auth = None
        if auth_config:
            auth_type = auth_config.get("type")
            if auth_type == "bearer":
                token = auth_config.get("token")
                if token:
                    headers.setdefault("Authorization", f"Bearer {token}")
            elif auth_type == "basic":
                username = auth_config.get("username")
                password = auth_config.get("password")
                if username and password:
                    auth = httpx.BasicAuth(username, password)

        # 自动判断是否发送 JSON
        if send_json is None:
            send_json = isinstance(body, dict) and method in ("POST", "PUT", "PATCH")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                request_kwargs = {
                    "headers": headers,
                    "params": params,
                }
                if auth:
                    request_kwargs["auth"] = auth
                if body is not None:
                    if send_json:
                        request_kwargs["json"] = body
                    else:
                        request_kwargs["content"] = str(body) if body else None

                response = await client.request(method, url, **request_kwargs)
                
                # 尝试解析 JSON，否则返回文本
                content_type = response.headers.get("content-type", "")
                response_body: Any = response.text
                if "application/json" in content_type:
                    try:
                        response_body = response.json()
                    except Exception:
                        pass

                return ToolResult(
                    success=True,
                    data={
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": response_body,
                        "content_type": content_type
                    }
                )
        except httpx.TimeoutException:
            return ToolResult(success=False, data=None, error=f"Request timeout after {timeout}s")
        except Exception as e:
            logger.exception(f"[http.request] Request failed: {e}")
            return ToolResult(success=False, data=None, error=f"HTTP request failed: {str(e)}")
