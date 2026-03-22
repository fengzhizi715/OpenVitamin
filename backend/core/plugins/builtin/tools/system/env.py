import os
from typing import Dict, Any
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from config.settings import settings


def _parse_allowed_names(raw: str) -> set[str]:
    return {x.strip() for x in (raw or "").split(",") if x.strip()}


class SystemEnvTool(Tool):
    @property
    def name(self) -> str:
        return "system.env"

    @property
    def description(self) -> str:
        return "Get environment variable(s). Returns single value or all environment variables as object."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "name": {
                "type": "string",
                "description": "Environment variable name to get. If not provided, returns all environment variables."
            },
            "all": {
                "type": "boolean",
                "description": "Whether to return all environment variables (default: false if name is provided, true if name is not provided).",
                "default": None
            }
        })

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": ["string", "object"],
            "description": "Single value or object of all environment variables"
        }

    @property
    def required_permissions(self):
        # env access is more sensitive than other system.info tools
        return ["system.env"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "System Env",
            "icon": "Settings",
            "category": "system",
            "permissions_hint": [
                {"key": "system.env", "label": "Access environment variables (sensitive)."}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            name = input_data.get("name")
            all_vars = input_data.get("all")

            # Permission gate (default deny)
            permitted = bool((ctx.permissions or {}).get("system.env")) or bool(settings.tool_system_env_enabled)
            if not permitted:
                return ToolResult(success=False, data=None, error="Permission denied: system.env is disabled")

            allowed_names = _parse_allowed_names(getattr(settings, "tool_system_env_allowed_names", "") or "")

            if name:
                if allowed_names and name not in allowed_names and not bool((ctx.permissions or {}).get("system.env.unrestricted")):
                    return ToolResult(success=False, data=None, error=f"Permission denied: env var '{name}' not in allowlist")
                # Return single variable
                value = os.environ.get(name)
                if value is None:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"Environment variable '{name}' not found"
                    )
                return ToolResult(success=True, data=value)
            else:
                # Return all variables
                if all_vars is None:
                    all_vars = True
                if all_vars:
                    if not bool(getattr(settings, "tool_system_env_allow_all", False)) and not bool((ctx.permissions or {}).get("system.env.allow_all")):
                        return ToolResult(success=False, data=None, error="Permission denied: returning all env vars is disabled")

                    envs = dict(os.environ)
                    if allowed_names and not bool((ctx.permissions or {}).get("system.env.unrestricted")):
                        envs = {k: v for k, v in envs.items() if k in allowed_names}
                    return ToolResult(success=True, data=envs)
                else:
                    return ToolResult(
                        success=False,
                        data=None,
                        error="Either 'name' or 'all=true' must be provided"
                    )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
