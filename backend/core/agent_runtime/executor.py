from typing import List, Dict, Any, Optional
import time
from log import logger
from core.types import Message, ChatCompletionRequest
from core.agents.router import get_router
from core.plugins.registry import get_plugin_registry
from core.plugins.executor import get_plugin_executor
from core.plugins.context import PluginContext
from core.tools.registry import ToolRegistry
from core.tools.context import ToolContext
from core.skills import get_skill, SkillExecutor
import jsonschema

# V2.8: Import InferenceClient for unified LLM access
from core.inference import get_inference_client


class AgentExecutor:
    """
    智能体调度器
    负责 LLM 调用和工具执行的统一分发
    
    V2.8: LLM calls now go through InferenceClient for decoupling.
    """
    def __init__(self):
        self.router = get_router()  # Keep for backward compatibility
        self.plugin_registry = get_plugin_registry()
        self.plugin_executor = get_plugin_executor()
        self._inference_client = None  # Lazy init
    
    @property
    def inference_client(self):
        """Lazy initialization of InferenceClient"""
        if self._inference_client is None:
            self._inference_client = get_inference_client()
        return self._inference_client

    async def llm_call(
        self,
        model_id: str,
        messages: List[Message],
        temperature: float = 0.7,
        model_params: Optional[Dict[str, Any]] = None,
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        """
        调用 LLM 后端
        
        V2.8: Now routes through InferenceClient for unified access.
        
        Args:
            model_id: Model alias or direct model_id
            messages: List of Message objects
            temperature: Sampling temperature
            model_params: Additional model parameters (max_tokens, stop, etc.)
            session_id: Optional session ID for observability
            trace_id: Optional trace ID for observability
            agent_id: Optional agent ID for observability
            
        Returns:
            Generated text string
        """
        # Build metadata for observability
        metadata = {
            "caller": "AgentExecutor",
            "session_id": session_id or "",
            "trace_id": trace_id or "",
            "agent_id": agent_id or "",
        }
        
        # Extract additional params
        max_tokens = model_params.get("max_tokens") if model_params else None
        stop = model_params.get("stop") if model_params else None
        
        # V2.8: Use InferenceClient for unified access
        response = await self.inference_client.generate(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens or 2048,
            stop=stop,
            metadata=metadata,
        )
        
        return response.text

    async def execute_tool(self, tool_id: str, input_data: Dict[str, Any], session_id: str, agent_id: str = None) -> Any:
        """
        执行工具 (优先通过 ToolRegistry, 兜底 PluginExecutor)
        """
        # 1. 尝试从 ToolRegistry 获取
        tool = ToolRegistry.get(tool_id)
        if tool:
            logger.info(f"[AgentExecutor] Executing core tool: {tool_id}")
            context = ToolContext(
                agent_id=agent_id,
                trace_id=f"tool_{session_id}_{int(time.time())}", # 简单 trace_id
                workspace=".", # TODO: 从配置获取
                permissions={}
            )
            # 权限校验：当 ctx.permissions 非空时才强制校验（兼容旧调用方）
            required_perms = getattr(tool, "required_permissions", []) or []
            if required_perms and context.permissions:
                missing = [p for p in required_perms if not context.permissions.get(p)]
                if missing:
                    logger.warning(f"[AgentExecutor] Permission denied for tool {tool_id}: missing {missing}")
                    return f"Error: permission denied for '{tool_id}' (missing: {missing})"

            # 输入 schema 校验（确定性优先：非法输入不执行）
            try:
                jsonschema.validate(instance=input_data, schema=tool.input_schema or {})
            except Exception as e:
                logger.warning(f"[AgentExecutor] Tool input schema validation failed for {tool_id}: {e}")
                return f"Error: invalid tool input for '{tool_id}': {e}"

            result = await tool.run(input_data, context)
            if not result.success:
                return f"Error: {result.error}"

            # 输出 schema 校验（如果声明了）
            try:
                out_schema = getattr(tool, "output_schema", {}) or {}
                if out_schema:
                    jsonschema.validate(instance=result.data, schema=out_schema)
            except Exception as e:
                logger.warning(f"[AgentExecutor] Tool output schema validation failed for {tool_id}: {e}")
                return f"Error: invalid tool output for '{tool_id}': {e}"

            return result.data

        # 2. 兜底 PluginExecutor
        logger.info(f"[AgentExecutor] Tool {tool_id} not in ToolRegistry, trying PluginExecutor")
        context = PluginContext(
            session_id=session_id,
            user_id="default",
            metadata={"agent_v1": True}
        )
        
        return await self.plugin_executor.execute(
            name=tool_id,
            input_data=input_data,
            context=context
        )

    async def execute_skill(
        self,
        skill_id: str,
        inputs: Dict[str, Any],
        *,
        agent_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        workspace: str = ".",
        permissions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行 Skill（供 Agent Runtime 使用）。返回 { type, output?, error?, prompt? }。
        """
        from core.skills.contract import SkillExecutionRequest
        
        skill = get_skill(skill_id)
        if not skill:
            return {"type": "error", "output": None, "error": f"Skill not found: {skill_id}"}
        
        # 构建执行请求
        request = SkillExecutionRequest(
            skill_id=skill_id,
            input=inputs,
            trace_id=trace_id or f"skill_{skill_id}",
            caller_id=agent_id or "agent_runtime",
            metadata={
                "workspace": workspace,
                "permissions": permissions or {},
            }
        )
        
        # 使用 SkillExecutor 统一入口执行
        response = await SkillExecutor.execute(request)
        
        # 转换响应格式
        if response.status == "success":
            return {"type": "success", "output": response.output, "error": None}
        elif response.status == "timeout":
            return {"type": "error", "output": None, "error": response.error.get("message", "Timeout")}
        else:
            return {"type": "error", "output": None, "error": response.error.get("message", "Unknown error")}

_executor = None

def get_agent_executor() -> AgentExecutor:
    global _executor
    if _executor is None:
        _executor = AgentExecutor()
    return _executor
