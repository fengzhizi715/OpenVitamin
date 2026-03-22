import logging
from typing import Any, Dict, List, Optional
from .base import Tool
from .context import ToolContext
from .result import ToolResult
import jsonschema

logger = logging.getLogger(__name__)

class ToolRegistry:
    _tools: Dict[str, Tool] = {}

    @classmethod
    def register(cls, tool: Tool):
        if tool.name in cls._tools:
            logger.warning(f"Tool '{tool.name}' is already registered. Overwriting.")
        cls._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    @classmethod
    def get(cls, name: str) -> Optional[Tool]:
        return cls._tools.get(name)

    @classmethod
    def list(cls) -> List[Tool]:
        return list(cls._tools.values())

    @classmethod
    def clear(cls):
        cls._tools.clear()
        
    @classmethod
    async def execute(cls, tool_name: str, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """
        Execute a tool with full security checks.
        
        This is the SINGLE authorized entry point for tool execution.
        All permission, schema, and audit checks are enforced here.
        """
        tool = cls.get(tool_name)
        if not tool:
            return ToolResult(success=False, data=None, error=f"Tool not found: {tool_name}")
        
        # 1. Permission Check
        required_perms = getattr(tool, "required_permissions", []) or []
        if required_perms:
            missing = [p for p in required_perms if not ctx.permissions.get(p)]
            if missing:
                logger.warning(f"[ToolRegistry] Permission denied for tool {tool_name}: missing {missing}")
                return ToolResult(
                    success=False, 
                    data=None, 
                    error=f"Permission denied: missing {missing}"
                )
        
        # 2. Input Schema Validation
        try:
            input_schema = getattr(tool, "input_schema", {}) or {}
            if input_schema:
                jsonschema.validate(instance=input_data, schema=input_schema)
        except jsonschema.ValidationError as e:
            logger.warning(f"[ToolRegistry] Input validation failed for {tool_name}: {e}")
            return ToolResult(success=False, data=None, error=f"Invalid input: {e}")
        
        # 3. Audit Logging
        logger.info(f"[ToolRegistry] Executing tool {tool_name} with permissions {list(ctx.permissions.keys())}")
        
        # 4. Execute Tool
        try:
            result = await tool.run(input_data, ctx)
            
            # 5. Output Schema Validation (if declared)
            try:
                output_schema = getattr(tool, "output_schema", {}) or {}
                if output_schema and result.success and result.data is not None:
                    jsonschema.validate(instance=result.data, schema=output_schema)
            except jsonschema.ValidationError as e:
                logger.warning(f"[ToolRegistry] Output validation failed for {tool_name}: {e}")
                # Don't fail the tool execution, just log the validation error
                
            return result
        except Exception as e:
            logger.exception(f"[ToolRegistry] Tool {tool_name} execution failed: {e}")
            return ToolResult(success=False, data=None, error=str(e))
