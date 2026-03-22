"""
Workflow Runtime

Workflow 运行时，协调执行流程，集成 governance 和 execution_kernel。
"""

from typing import Optional, Dict, Any, Callable, List
from datetime import datetime, timedelta
import asyncio
import json
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from core.workflows.models import (
    WorkflowExecution,
    WorkflowExecutionState,
    WorkflowExecutionNode,
    WorkflowExecutionNodeState,
    WorkflowVersion,
    WorkflowVersionState
)
from core.workflows.repository import WorkflowExecutionRepository, WorkflowVersionRepository
from core.workflows.governance import ExecutionManager, ExecutionRequest
from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter
from core.inference.client.inference_client import InferenceClient
from core.tools.registry import ToolRegistry
from core.tools.context import ToolContext
from core.agent_runtime.definition import get_agent_registry
from core.agent_runtime.executor import get_agent_executor
from core.agent_runtime.session import AgentSession
from core.agent_runtime.v2.runtime import get_agent_runtime
from core.types import Message
from execution_kernel.engine.control_flow import execute_condition_node
from execution_kernel.engine.scheduler import Scheduler
from execution_kernel.engine.state_machine import StateMachine
from execution_kernel.engine.executor import Executor
from execution_kernel.persistence.db import Database, get_platform_db_path
from execution_kernel.cache.node_cache import NodeCache
from execution_kernel.persistence.repositories import NodeCacheRepository
from config.settings import settings
from log import logger


class _WorkflowNodeCacheRepository:
    """
    为 WorkflowRuntime 提供 NodeCache 所需的最小仓储适配层。
    NodeCache 当前依赖 async Session 级 repository，这里按调用粒度创建 session。
    """

    def __init__(self, db: Database):
        self._db = db

    async def get(self, node_id: str, input_hash: str):
        async with self._db.async_session() as session:
            repo = NodeCacheRepository(session)
            return await repo.get(node_id, input_hash)

    async def save(self, entry):
        async with self._db.async_session() as session:
            repo = NodeCacheRepository(session)
            return await repo.save(entry)

    async def delete_expired(self) -> int:
        async with self._db.async_session() as session:
            repo = NodeCacheRepository(session)
            return await repo.delete_expired()


class WorkflowRuntime:
    """
    Workflow 运行时
    
    负责 Workflow 的执行协调：
    1. 执行治理检查（并发、配额）
    2. 转换为 execution_kernel 格式
    3. 调用 execution_kernel 执行
    4. 状态同步和结果处理
    """
    
    def __init__(
        self,
        db: Session,
        execution_manager: ExecutionManager,
        scheduler: Optional[Scheduler] = None
    ):
        self.db = db
        self.execution_repository = WorkflowExecutionRepository(db)
        self.version_repository = WorkflowVersionRepository(db)
        self.execution_manager = execution_manager
        
        # 初始化 execution_kernel 组件
        if scheduler:
            self.scheduler = scheduler
        else:
            # 创建默认 scheduler，使用平台统一的 DB 路径
            db_instance = Database()
            state_machine = StateMachine(db=db_instance)
            cache_repo = _WorkflowNodeCacheRepository(db_instance)
            cache = NodeCache(cache_repo)
            # Workflow 使用基础 node handlers（llm, tool, condition 等）
            node_handlers = self._create_default_node_handlers()
            executor = Executor(state_machine, cache, node_handlers)
            self.scheduler = Scheduler(db_instance, state_machine, executor)
    
    @staticmethod
    def _validate_simple_output_schema(
        output: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """轻量 schema 校验（required + properties.type + 嵌套 object/array）。返回结构化错误。"""
        if not isinstance(schema, dict) or not schema:
            return None

        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "object": dict,
            "array": list,
        }

        def _err(
            *,
            message: str,
            schema_path: str,
            output_path: str,
            expected_type: Optional[str] = None,
            actual_type: Optional[str] = None,
        ) -> Dict[str, Any]:
            return {
                "error_code": "AGENT_OUTPUT_SCHEMA_VALIDATION_ERROR",
                "message": message,
                "schema_path": schema_path,
                "output_path": output_path,
                "expected_type": expected_type,
                "actual_type": actual_type,
            }

        def _validate(value: Any, rule: Dict[str, Any], schema_path: str, output_path: str) -> Optional[Dict[str, Any]]:
            expected = str((rule or {}).get("type") or "").strip()
            if expected:
                py_type = type_map.get(expected)
                actual_type = type(value).__name__
                if py_type and not isinstance(value, py_type):
                    return _err(
                        message=f"type mismatch: expected {expected}, got {actual_type}",
                        schema_path=schema_path,
                        output_path=output_path,
                        expected_type=expected,
                        actual_type=actual_type,
                    )

            if expected == "object":
                required = (rule or {}).get("required") or []
                for key in required:
                    if not isinstance(value, dict) or key not in value:
                        return _err(
                            message=f"missing required field: {key}",
                            schema_path=f"{schema_path}.required[{key}]",
                            output_path=f"{output_path}.{key}",
                            expected_type=None,
                            actual_type="missing",
                        )
                properties = (rule or {}).get("properties") or {}
                for key, child_rule in properties.items():
                    if not isinstance(value, dict) or key not in value:
                        continue
                    child_schema_path = f"{schema_path}.properties.{key}"
                    child_output_path = f"{output_path}.{key}"
                    err = _validate(value.get(key), child_rule or {}, child_schema_path, child_output_path)
                    if err:
                        return err

            if expected == "array":
                items_rule = (rule or {}).get("items")
                if items_rule and isinstance(value, list):
                    for idx, item in enumerate(value):
                        err = _validate(
                            item,
                            items_rule,
                            f"{schema_path}.items",
                            f"{output_path}[{idx}]",
                        )
                        if err:
                            return err
            return None

        root_rule = dict(schema)
        if "type" not in root_rule:
            root_rule["type"] = "object"
        return _validate(output, root_rule, "schema", "output")

    def _create_default_node_handlers(self) -> Dict[str, Callable]:
        """创建默认的节点处理器"""
        client = InferenceClient()
        AGENT_NODE_MAX_CALL_DEPTH = 2
        AGENT_NODE_DEFAULT_MAX_CALLS = 20

        def _ensure_execution_not_cancelled(context: Any) -> None:
            global_ctx = getattr(context, "global_data", {}) or {}
            execution_id = str(global_ctx.get("execution_id") or "").strip()
            if not execution_id:
                return
            execution = self.execution_repository.get_by_id(execution_id)
            if execution and execution.state == WorkflowExecutionState.CANCELLED:
                raise RuntimeError(f"WORKFLOW_CANCELLED: execution_id={execution_id}")

        async def _tool_handler(node_def, input_data, context):
            def _infer_prompt_from_payload(payload: Any) -> Optional[str]:
                if payload is None:
                    return None
                if isinstance(payload, str):
                    s = payload.strip()
                    return s or None
                if isinstance(payload, (int, float, bool)):
                    return str(payload)
                if isinstance(payload, dict):
                    preferred_keys = [
                        "prompt", "message", "query", "text",
                        "question", "task", "instruction", "content",
                        "topic", "input",
                    ]
                    for k in preferred_keys:
                        v = payload.get(k)
                        if isinstance(v, str) and v.strip():
                            return v.strip()
                    # 兜底：取首个非空字符串字段
                    for v in payload.values():
                        if isinstance(v, str) and v.strip():
                            return v.strip()
                    return None
                return None

            _ensure_execution_not_cancelled(context)
            cfg = node_def.config or {}
            workflow_node_type = str(cfg.get("workflow_node_type") or "").strip().lower()
            if workflow_node_type == "input":
                # Input 节点：
                # 1) 默认透传 workflow input_data（可被 fixed_input / node input 覆盖）
                # 2) 若配置 input_key，则仅输出该 key 的裁剪结果
                global_ctx = getattr(context, "global_data", {}) or {}
                base = global_ctx.get("input_data") if isinstance(global_ctx.get("input_data"), dict) else {}
                out = dict(base or {})
                fixed_input = cfg.get("fixed_input")
                if isinstance(fixed_input, dict):
                    out = {**out, **fixed_input}
                if isinstance(input_data, dict) and input_data:
                    out = {**out, **input_data}
                input_key = str(cfg.get("input_key") or "").strip()
                if input_key:
                    if input_key in out:
                        return {input_key: out.get(input_key)}
                    return {}
                return out
            if workflow_node_type == "output":
                # Output 节点：
                # 根据 config.output_key + config.expression 计算输出；
                # expression 复用 Context.resolve 语义。
                out = dict(input_data or {})
                fixed_input = cfg.get("fixed_input")
                if isinstance(fixed_input, dict):
                    out = {**fixed_input, **out}
                allow_output_auto_fallback = bool(cfg.get("allow_auto_fallback", False))
                if allow_output_auto_fallback and not out and hasattr(context, "node_outputs"):
                    try:
                        values = list((context.node_outputs or {}).values())
                        for candidate in reversed(values):
                            if isinstance(candidate, dict) and candidate:
                                out = candidate
                                break
                    except Exception:
                        pass
                # 兜底：若当前仅拿到 input/query 等“输入类字段”，优先回退到最近的 agent_result，避免最终输出只回显用户输入。
                if allow_output_auto_fallback and isinstance(out, dict):
                    semantic_keys = {"query", "text", "prompt", "message", "topic", "input"}
                    has_result_like = any(k in out for k in ("response", "result", "output", "content"))
                    only_semantic_input = (not has_result_like) and set(out.keys()).issubset(semantic_keys)
                    if only_semantic_input and hasattr(context, "node_outputs"):
                        try:
                            values = list((context.node_outputs or {}).values())
                            for candidate in reversed(values):
                                if not isinstance(candidate, dict) or not candidate:
                                    continue
                                if str(candidate.get("type") or "").strip().lower() == "agent_result":
                                    out = candidate
                                    break
                                if any(k in candidate for k in ("response", "result", "output", "content")):
                                    out = candidate
                                    break
                        except Exception:
                            pass
                output_key = str(cfg.get("output_key") or "").strip()
                expression = cfg.get("expression")
                if output_key:
                    if isinstance(expression, str) and expression.strip():
                        value = context.resolve(expression)
                        source_mode = "expression"
                    else:
                        value = out.get(output_key) if isinstance(out, dict) and output_key in out else out
                        source_mode = "passthrough"
                    return {
                        output_key: value,
                        "__workflow_output_source": {
                            "mode": source_mode,
                            "output_key": output_key,
                            "expression": expression if isinstance(expression, str) and expression.strip() else None,
                        },
                    }
                if isinstance(out, dict):
                    return {
                        **out,
                        "__workflow_output_source": {
                            "mode": "passthrough",
                            "output_key": None,
                            "expression": expression if isinstance(expression, str) and expression.strip() else None,
                        },
                    }
                return out
            if workflow_node_type == "agent":
                agent_id = str(cfg.get("agent_id") or "").strip()
                if not agent_id:
                    raise ValueError("AGENT_NODE_CONFIG_ERROR: missing agent_id")

                registry = get_agent_registry()
                target_agent = registry.get_agent(agent_id)
                if not target_agent:
                    raise ValueError(f"AGENT_NODE_NOT_FOUND: {agent_id}")
                # 关键约束：不要修改注册中心返回的全局 Agent 对象，避免跨 workflow/会话污染。
                run_agent = target_agent.model_copy(deep=True)

                global_ctx = getattr(context, "global_data", {}) or {}
                workspace = global_ctx.get("workspace") or "."
                workflow_execution_id = str(global_ctx.get("execution_id") or "").strip()
                user_id = str(global_ctx.get("user_id") or "default").strip() or "default"

                call_chain = global_ctx.get("agent_call_chain")
                if not isinstance(call_chain, list):
                    call_chain = []
                call_chain = [str(x).strip() for x in call_chain if str(x).strip()]
                if agent_id in call_chain:
                    raise RuntimeError(
                        f"AGENT_NODE_RECURSION_GUARD: loop detected in agent_call_chain={call_chain + [agent_id]}"
                    )
                if len(call_chain) >= AGENT_NODE_MAX_CALL_DEPTH:
                    raise RuntimeError(
                        f"AGENT_NODE_RECURSION_GUARD: max depth exceeded ({AGENT_NODE_MAX_CALL_DEPTH})"
                    )

                max_calls = int(global_ctx.get("agent_node_max_calls") or AGENT_NODE_DEFAULT_MAX_CALLS)
                if cfg.get("agent_max_calls") is not None:
                    max_calls = max(1, int(cfg.get("agent_max_calls")))
                current_calls = int(global_ctx.get("__agent_node_call_count") or 0)
                if current_calls >= max_calls:
                    raise RuntimeError(f"AGENT_NODE_GOVERNANCE_LIMIT: max calls exceeded ({max_calls})")
                global_ctx["__agent_node_call_count"] = current_calls + 1

                # agent 节点也支持 fixed_input 作为默认入参，允许前端用配置面板提供默认 prompt/message/query/text
                effective_input = dict(input_data or {})
                fixed_input = cfg.get("fixed_input")
                if isinstance(fixed_input, dict):
                    effective_input = {**fixed_input, **effective_input}
                # 若上游未显式传入，尝试从最近的节点输出中补齐输入（兼容部分编排未做映射的场景）
                allow_agent_auto_input_fallback = bool(cfg.get("allow_auto_input_fallback", False))
                if allow_agent_auto_input_fallback and not effective_input and hasattr(context, "node_outputs"):
                    try:
                        values = list((context.node_outputs or {}).values())
                        for candidate in reversed(values):
                            if isinstance(candidate, dict) and candidate:
                                effective_input = dict(candidate)
                                break
                    except Exception:
                        pass

                prompt = cfg.get("prompt") or effective_input.get("prompt")
                if prompt is None:
                    prompt = (
                        effective_input.get("message")
                        or effective_input.get("query")
                        or effective_input.get("text")
                    )
                if prompt is None:
                    prompt = _infer_prompt_from_payload(effective_input)
                # 当节点输入为空时，回退到 workflow 全局 input_data，避免 agent 收到 "{}" 后误触发无关技能。
                if prompt is None:
                    workflow_input = global_ctx.get("input_data") or {}
                    if isinstance(workflow_input, dict):
                        prompt = (
                            workflow_input.get("prompt")
                            or workflow_input.get("message")
                            or workflow_input.get("query")
                            or workflow_input.get("text")
                        )
                    elif workflow_input not in (None, ""):
                        prompt = str(workflow_input)
                if prompt is None:
                    workflow_input = global_ctx.get("input_data")
                    prompt = _infer_prompt_from_payload(workflow_input)
                if prompt is None:
                    if effective_input:
                        prompt = json.dumps(effective_input, ensure_ascii=False, sort_keys=True)
                    else:
                        workflow_input = global_ctx.get("input_data") or {}
                        if isinstance(workflow_input, dict) and workflow_input:
                            prompt = json.dumps(workflow_input, ensure_ascii=False, sort_keys=True)
                if prompt is None:
                    dbg_node_keys = sorted([str(k) for k in effective_input.keys()]) if isinstance(effective_input, dict) else []
                    workflow_input = global_ctx.get("input_data")
                    dbg_workflow_keys = (
                        sorted([str(k) for k in workflow_input.keys()])
                        if isinstance(workflow_input, dict)
                        else []
                    )
                    raise ValueError(
                        "AGENT_NODE_INPUT_EMPTY: missing prompt/message/query/text in node input and workflow input_data; "
                        f"node_input_keys={dbg_node_keys}, workflow_input_keys={dbg_workflow_keys}; "
                        "fix_by=provide one of: "
                        "1) node.config.prompt, "
                        "2) node.config.fixed_input.query|text|message|prompt, "
                        "3) execution input_data.query|text|message|prompt"
                    )

                pass_context_keys = cfg.get("pass_context_keys")
                if isinstance(pass_context_keys, list) and pass_context_keys:
                    passed = {}
                    for key in pass_context_keys:
                        k = str(key).strip()
                        if not k:
                            continue
                        if isinstance(input_data, dict) and k in input_data:
                            passed[k] = input_data.get(k)
                        elif k in global_ctx:
                            passed[k] = global_ctx.get(k)
                    if passed:
                        prompt = f"{prompt}\n\nContext:\n{json.dumps(passed, ensure_ascii=False)}"

                if cfg.get("max_steps") is not None:
                    run_agent.max_steps = max(1, int(cfg.get("max_steps")))
                model_override = str(cfg.get("model_override") or "").strip()
                if model_override:
                    run_agent.model_id = model_override

                node_session_id = (
                    f"wf_{workflow_execution_id}_{node_def.id}"
                    if workflow_execution_id else f"wf_{node_def.id}"
                )
                session = AgentSession(
                    session_id=node_session_id,
                    agent_id=run_agent.agent_id,
                    user_id=user_id,
                    messages=[Message(role="user", content=str(prompt))],
                    status="idle",
                )
                session.workspace_dir = workspace
                session.state = {
                    "workflow_agent_context": {
                        "workflow_execution_id": workflow_execution_id,
                        "source_node_id": str(node_def.id),
                        "call_depth": len(call_chain) + 1,
                        "call_chain": call_chain + [agent_id],
                    }
                }

                runtime = get_agent_runtime(get_agent_executor())
                timeout_sec = cfg.get("timeout")
                if timeout_sec is None:
                    timeout_sec = cfg.get("agent_timeout_seconds")
                if timeout_sec is not None:
                    result_session = await asyncio.wait_for(
                        runtime.run(run_agent, session, workspace=workspace),
                        timeout=float(timeout_sec),
                    )
                else:
                    result_session = await runtime.run(run_agent, session, workspace=workspace)

                if result_session.status == "error":
                    raise RuntimeError(
                        f"AGENT_NODE_RUNTIME_ERROR: {result_session.error_message or f'Agent run failed: {agent_id}'}"
                    )

                assistant_reply = ""
                for msg in reversed(result_session.messages):
                    if msg.role == "assistant":
                        assistant_reply = msg.content if isinstance(msg.content, str) else str(msg.content)
                        break

                agent_output = {
                    "type": "agent_result",
                    "status": "success",
                    "agent_id": agent_id,
                    "agent_session_id": result_session.session_id,
                    "workflow_node_id": str(node_def.id),
                    "response": assistant_reply,
                    "response_preview": assistant_reply[:500],
                }
                schema = {}
                if isinstance(cfg.get("output_schema"), dict):
                    schema = cfg.get("output_schema")
                elif isinstance(getattr(node_def, "output_schema", None), dict):
                    schema = getattr(node_def, "output_schema")
                err = self._validate_simple_output_schema(agent_output, schema)
                if err:
                    raise ValueError(
                        f"AGENT_NODE_OUTPUT_SCHEMA_ERROR: {json.dumps(err, ensure_ascii=False)}"
                    )
                _ensure_execution_not_cancelled(context)
                return agent_output

            tool_name = cfg.get("tool_name") or cfg.get("tool_id")
            if not tool_name:
                return {"error": "Tool node missing tool_name/tool_id"}

            # ToolContext is explicit + user-in-control: default deny.
            global_ctx = getattr(context, "global_data", {}) or {}
            permissions = global_ctx.get("permissions") or {}
            workspace = global_ctx.get("workspace") or "."
            trace_id = global_ctx.get("trace_id")
            agent_id = global_ctx.get("agent_id")

            tool_ctx = ToolContext(
                agent_id=agent_id,
                trace_id=trace_id,
                workspace=workspace,
                permissions=permissions,
            )

            # Default behavior: use resolved node input as tool input.
            tool_input = dict(input_data or {})
            fixed_input = cfg.get("fixed_input")
            if isinstance(fixed_input, dict):
                tool_input.update(fixed_input)

            result = await ToolRegistry.execute(tool_name, tool_input, tool_ctx)
            if not result.success:
                return {"error": result.error or f"Tool failed: {tool_name}"}
            _ensure_execution_not_cancelled(context)
            return result.data if isinstance(result.data, dict) else {"output": result.data}

        async def _script_handler(node_def, input_data, context):
            cfg = node_def.config or {}
            # script is treated as a constrained tool call to builtin_shell.run (still permissioned)
            command = cfg.get("command") or (input_data or {}).get("command")
            if not command:
                return {"error": "Script node missing command"}
            cfg = dict(cfg)
            cfg["tool_name"] = cfg.get("tool_name") or "builtin_shell.run"
            # Reuse tool handler with command injected
            return await _tool_handler(
                node_def=type(node_def)(**{**node_def.model_dump(), "config": cfg}),
                input_data={**(input_data or {}), "command": command},
                context=context,
            )

        async def _llm_handler(node_def, input_data, context):
            _ensure_execution_not_cancelled(context)
            cfg = node_def.config or {}
            # 优先使用 model_id（编辑器当前字段），兼容历史字段 model
            model_id = cfg.get("model_id")
            legacy_model = cfg.get("model")
            model = model_id or legacy_model
            if not model:
                return {"error": "LLM node missing model"}
            if model_id and legacy_model and model_id != legacy_model:
                logger.warning(
                    "[WorkflowRuntime] LLM node %s has both model_id=%s and legacy model=%s, using model_id",
                    node_def.id,
                    model_id,
                    legacy_model,
                )

            prompt = cfg.get("prompt") or (input_data or {}).get("prompt")
            if prompt is None:
                # fallback: stringify input_data deterministically
                import json

                prompt = json.dumps(input_data or {}, ensure_ascii=False, sort_keys=True)

            system_prompt = cfg.get("system_prompt")
            temperature = float(cfg.get("temperature", 0.7))
            max_tokens = int(cfg.get("max_tokens", 2048))
            stop = cfg.get("stop")

            resp = await client.generate(
                model=model,
                prompt=str(prompt),
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop if isinstance(stop, list) else None,
                metadata={"source": "workflow_runtime", "node_id": node_def.id},
            )
            _ensure_execution_not_cancelled(context)
            return resp.to_dict()

        async def _condition_handler(node_def, input_data, context):
            return await execute_condition_node(node_def, input_data, context)

        return {
            "tool": _tool_handler,
            "llm": _llm_handler,
            "condition": _condition_handler,
            "script": _script_handler,
        }
    
    async def execute(
        self,
        execution: WorkflowExecution,
        wait_for_completion: bool = True,
        wait_timeout_seconds: Optional[float] = None,
        on_state_change: Optional[Callable[[WorkflowExecution], None]] = None
    ) -> WorkflowExecution:
        """
        执行 Workflow
        
        Args:
            execution: 执行实例
            wait_for_completion: 是否等待完成
            wait_timeout_seconds: wait_for_completion=True 时的等待超时（秒），None 表示不额外超时
            on_state_change: 状态变更回调
        
        Returns:
            执行实例（最终状态）
        """
        execution_id = execution.execution_id
        workflow_id = execution.workflow_id
        version_id = execution.version_id
        
        try:
            # 防重复/跨进程一致性：以 DB 当前状态为准，避免已取消或已启动执行被再次启动。
            latest = self.execution_repository.get_by_id(execution_id)
            if not latest:
                raise ValueError(f"Execution not found: {execution_id}")
            if latest.is_terminal():
                logger.info(
                    f"[WorkflowRuntime] Skip execute for terminal execution: "
                    f"{execution_id} state={latest.state.value}"
                )
                return latest
            if latest.state == WorkflowExecutionState.RUNNING and latest.graph_instance_id:
                logger.info(
                    f"[WorkflowRuntime] Skip duplicate execute for running execution: "
                    f"{execution_id} instance={latest.graph_instance_id}"
                )
                return latest
            execution = latest
            workflow_id = execution.workflow_id
            version_id = execution.version_id

            # 1. 获取版本
            version = self.version_repository.get_version_by_id(version_id)
            if not version:
                raise ValueError(f"Version not found: {version_id}")
            
            trigger_type = str(execution.trigger_type or "manual").lower()
            allow_draft_for_manual_run = trigger_type in {"manual", "api", "debug"}
            if not version.can_execute():
                if not (version.state == WorkflowVersionState.DRAFT and allow_draft_for_manual_run):
                    raise ValueError(f"Version cannot be executed: {version.state.value}")
            
            # 2. 验证兼容性
            compatibility_errors = GraphRuntimeAdapter.validate_compatibility(version)
            if compatibility_errors:
                raise ValueError(f"Compatibility check failed: {'; '.join(compatibility_errors)}")
            
            # 3. 请求执行治理
            request = ExecutionRequest(
                execution_id=execution_id,
                workflow_id=workflow_id,
                version_id=version_id,
                estimated_tokens=self._estimate_tokens(version)
            )
            
            result = await self.execution_manager.wait_for_execution(request)
            
            if not result.allowed:
                raise RuntimeError(f"Execution not allowed: {result.reason}")

            # 记录治理侧排队观测信息（如果有）
            queued_at_dt = None
            if result.queued_at:
                try:
                    queued_at_dt = datetime.fromisoformat(result.queued_at)
                except Exception:
                    queued_at_dt = None
            self.execution_repository.update_queue_metrics(
                execution_id,
                queue_position=result.queue_position,
                queued_at=queued_at_dt,
                wait_duration_ms=result.wait_duration_ms,
            )

            # 3.5 跨进程并发兜底：基于 DB 的 running 数进行软限制，缓解多 worker 下内存治理不一致。
            await self._wait_distributed_running_slot(workflow_id, execution_id)
            
            # 4. 更新执行状态为 RUNNING
            execution = self.execution_repository.update_state(
                execution_id,
                WorkflowExecutionState.RUNNING
            )
            if on_state_change:
                on_state_change(execution)
            
            # 5. 转换为 execution_kernel 格式
            graph_def = GraphRuntimeAdapter.adapt(version)
            
            # 6. 确定 instance_id（使用 execution_id 保持一致性）
            instance_id = execution.execution_id
            
            # 7. 构造 global_context
            workspace_dir = str(
                Path("data/workflow_workspaces").joinpath(execution.execution_id).resolve()
            )
            Path(workspace_dir).mkdir(parents=True, exist_ok=True)
            global_context = {
                "workflow_id": execution.workflow_id,
                "version_id": execution.version_id,
                "execution_id": execution.execution_id,
                "input_data": execution.input_data or {},
                "workspace": workspace_dir,
                **(execution.global_context or {})
            }
            
            # 更新 GraphInstance ID
            self.execution_repository.update_graph_instance_id(
                execution_id,
                instance_id
            )
            
            # 8. 使用 scheduler 启动实例
            await self.scheduler.start_instance(
                graph_def=graph_def,
                instance_id=instance_id,
                global_context=global_context
            )
            
            # 9. 等待完成或异步执行
            if wait_for_completion:
                # 同步执行 - 等待完成
                final_state = await self.scheduler.wait_for_completion(
                    instance_id=instance_id,
                    timeout=wait_timeout_seconds,
                )
                final_state_value = final_state.value if hasattr(final_state, "value") else str(final_state)
                if wait_timeout_seconds and final_state_value == "running":
                    # 等待超时不应判定为执行失败：实例可能仍在后台继续运行。
                    timeout_msg = (
                        f"WORKFLOW_WAIT_TIMEOUT: wait={int(wait_timeout_seconds)}s exceeded, "
                        f"execution still running (execution_id={execution_id})"
                    )
                    execution = self.execution_repository.update_state(
                        execution_id,
                        WorkflowExecutionState.RUNNING,
                        error_message=timeout_msg,
                        error_details={
                            "code": "WORKFLOW_WAIT_TIMEOUT",
                            "message": timeout_msg,
                            "wait_timeout_seconds": wait_timeout_seconds,
                            "execution_id": execution_id,
                        },
                    )
                    logger.warning(f"[WorkflowRuntime] {timeout_msg}")
                    if on_state_change:
                        on_state_change(execution)
                    return execution

                # 10. 从 kernel 查询结果并处理
                execution = await self._handle_completion(
                    execution_id,
                    instance_id,
                    on_state_change
                )
            else:
                # 异步执行
                asyncio.create_task(
                    self._execute_async(execution_id, instance_id, on_state_change)
                )
            
            return execution
            
        except Exception as e:
            logger.error(f"[WorkflowRuntime] Execution failed: {execution_id} - {e}")
            
            # 标记执行失败
            execution = self.execution_repository.update_state(
                execution_id,
                WorkflowExecutionState.FAILED,
                error_message=str(e),
                error_details={"exception_type": type(e).__name__}
            )
            
            # 释放治理资源
            self.execution_manager.complete_execution(execution_id, workflow_id)
            
            if on_state_change:
                on_state_change(execution)
            
            return execution

    async def _wait_distributed_running_slot(self, workflow_id: str, execution_id: str) -> None:
        if not bool(getattr(settings, "workflow_distributed_running_limit_enabled", True)):
            return
        limit = max(1, int(getattr(settings, "workflow_distributed_running_limit_per_workflow", 3) or 3))
        timeout_s = float(getattr(settings, "workflow_distributed_running_limit_wait_seconds", 15.0) or 15.0)
        fail_open = bool(getattr(settings, "workflow_distributed_running_limit_fail_open", True))
        stale_seconds = max(60, int(getattr(settings, "workflow_distributed_running_stale_seconds", 1800) or 1800))
        auto_reconcile_stale = bool(getattr(settings, "workflow_distributed_running_auto_reconcile_stale", True))
        deadline = datetime.utcnow().timestamp() + max(0.0, timeout_s)
        while True:
            now = datetime.utcnow()
            stale_cutoff = now - timedelta(seconds=stale_seconds)
            running_execs = self.execution_repository.get_running_executions(workflow_id)
            active_running = []
            stale_running = []
            for ex in running_execs:
                if ex.execution_id == execution_id:
                    continue
                started = ex.started_at or ex.created_at
                if started and started < stale_cutoff:
                    stale_running.append(ex)
                    continue
                active_running.append(ex)

            if stale_running and auto_reconcile_stale:
                for ex in stale_running:
                    try:
                        msg = (
                            "AUTO_RECONCILED_STALE_RUNNING: "
                            f"started_at={ex.started_at.isoformat() if ex.started_at else 'unknown'} "
                            f"older_than={stale_seconds}s"
                        )
                        self.execution_repository.update_state(
                            ex.execution_id,
                            WorkflowExecutionState.FAILED,
                            error_message=msg,
                            error_details={"code": "STALE_RUNNING_RECONCILED"},
                        )
                        logger.warning(
                            f"[WorkflowRuntime] Reconciled stale running execution: "
                            f"workflow_id={workflow_id} execution_id={ex.execution_id}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[WorkflowRuntime] Failed to reconcile stale running execution: "
                            f"execution_id={ex.execution_id} error={e}"
                        )

            running = len(active_running)
            if running < limit:
                return
            if datetime.utcnow().timestamp() >= deadline:
                if fail_open:
                    logger.warning(
                        "[WorkflowRuntime] Distributed running limit wait timeout, fail-open continue: "
                        f"workflow_id={workflow_id} execution_id={execution_id} "
                        f"running={running} limit={limit} stale_ignored={len(stale_running)}"
                    )
                    return
                raise RuntimeError(
                    f"DISTRIBUTED_CONCURRENCY_LIMIT_REACHED: workflow_id={workflow_id} "
                    f"running={running} limit={limit} "
                    f"stale_ignored={len(stale_running)}"
                )
            await asyncio.sleep(0.2)
    
    async def _execute_async(
        self,
        execution_id: str,
        instance_id: str,
        on_state_change: Optional[Callable[[WorkflowExecution], None]]
    ) -> None:
        """异步执行"""
        try:
            # 等待完成
            final_state = await self.scheduler.wait_for_completion(
                instance_id=instance_id,
                timeout=3600
            )
            await self._handle_completion(execution_id, instance_id, on_state_change)
        except Exception as e:
            logger.error(f"[WorkflowRuntime] Async execution failed: {execution_id} - {e}")
            
            execution = self.execution_repository.update_state(
                execution_id,
                WorkflowExecutionState.FAILED,
                error_message=str(e)
            )
            
            if on_state_change:
                on_state_change(execution)
    
    async def _handle_completion(
        self,
        execution_id: str,
        instance_id: str,
        on_state_change: Optional[Callable[[WorkflowExecution], None]]
    ) -> WorkflowExecution:
        """处理执行完成"""
        # 从 kernel DB 查询实例状态和节点结果
        result = await GraphRuntimeAdapter.extract_execution_result_from_kernel(
            instance_id,
            self.scheduler.db
        )
        
        # 确定最终状态
        kernel_state = result.get("state", "failed")
        if kernel_state == "completed":
            final_state = WorkflowExecutionState.COMPLETED
        elif kernel_state == "failed":
            final_state = WorkflowExecutionState.FAILED
        elif kernel_state == "cancelled":
            final_state = WorkflowExecutionState.CANCELLED
        else:
            final_state = WorkflowExecutionState.FAILED
        
        # 更新执行输出和状态
        output_data = result.get("output_data", {})
        agent_summaries = result.get("agent_summaries", [])
        if isinstance(output_data, dict) and isinstance(agent_summaries, list) and agent_summaries:
            output_data = {**output_data, "agent_summaries": agent_summaries}
        if output_data:
            self.execution_repository.update_output(execution_id, output_data)
        raw_node_states = result.get("node_states", [])
        if isinstance(raw_node_states, list) and raw_node_states:
            normalized_nodes: List[WorkflowExecutionNode] = []
            for item in raw_node_states:
                if not isinstance(item, dict):
                    continue
                node_id = str(item.get("node_id") or "").strip()
                if not node_id:
                    continue
                state_raw = str(item.get("state") or "pending").lower()
                if state_raw == "retrying":
                    state_raw = "running"
                if state_raw not in {s.value for s in WorkflowExecutionNodeState}:
                    state_raw = "pending"
                try:
                    normalized_nodes.append(
                        WorkflowExecutionNode(
                            node_id=node_id,
                            state=WorkflowExecutionNodeState(state_raw),
                            input_data=item.get("input_data") or {},
                            output_data=item.get("output_data") or {},
                            error_message=item.get("error_message"),
                            error_details=item.get("error_details"),
                            started_at=item.get("started_at"),
                            finished_at=item.get("finished_at"),
                            retry_count=int(item.get("retry_count") or 0),
                        )
                    )
                except Exception:
                    continue
            if normalized_nodes:
                self.execution_repository.update_node_states(execution_id, normalized_nodes)
        
        execution = self.execution_repository.update_state(
            execution_id,
            final_state
        )
        
        # 释放治理资源
        execution_id_val = execution.execution_id if execution else execution_id
        workflow_id = execution.workflow_id if execution else ""
        tokens_consumed = result.get("tokens_consumed", 0)
        
        self.execution_manager.complete_execution(
            execution_id_val,
            workflow_id,
            tokens_consumed
        )
        
        if on_state_change:
            on_state_change(execution)
        
        logger.info(f"[WorkflowRuntime] Execution completed: {execution_id} - {final_state.value}")
        
        return execution
    
    async def cancel(self, execution_id: str) -> bool:
        """取消执行"""
        execution = self.execution_repository.get_by_id(execution_id)
        if not execution:
            return False
        
        if not execution.can_cancel():
            return False
        
        # 取消 governance
        self.execution_manager.cancel_execution(
            execution_id,
            execution.workflow_id
        )

        # 先持久化取消状态，作为跨进程统一取消信号（让后续执行路径可尽快感知）。
        await self._update_state_with_retry(
            execution_id,
            WorkflowExecutionState.CANCELLED,
        )
        
        # 如果有 GraphInstance，取消它
        if execution.graph_instance_id:
            try:
                cancelled = await self.scheduler.cancel_instance(
                    execution.graph_instance_id,
                    reason="cancelled_by_user",
                )
                if not cancelled:
                    logger.warning(
                        f"[WorkflowRuntime] Graph instance not found for cancel: {execution.graph_instance_id}"
                    )
            except Exception as e:
                logger.warning(f"[WorkflowRuntime] Failed to cancel graph instance: {e}")
        
        logger.info(f"[WorkflowRuntime] Cancelled execution: {execution_id}")
        return True

    async def _update_state_with_retry(
        self,
        execution_id: str,
        state: WorkflowExecutionState,
        *,
        retries: int = 6,
        base_delay_seconds: float = 0.1,
    ) -> Optional[WorkflowExecution]:
        last_err: Optional[Exception] = None
        for i in range(retries):
            try:
                return self.execution_repository.update_state(execution_id, state)
            except OperationalError as e:
                last_err = e
                msg = str(e).lower()
                if "database is locked" not in msg:
                    raise
                delay = base_delay_seconds * (2 ** i)
                logger.warning(
                    f"[WorkflowRuntime] update_state retry due to DB lock: "
                    f"execution_id={execution_id} state={state.value} attempt={i + 1}/{retries} delay={delay:.2f}s"
                )
                await asyncio.sleep(delay)
        if last_err:
            raise last_err
        return None
    
    def get_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """获取执行状态"""
        execution = self.execution_repository.get_by_id(execution_id)
        if not execution:
            return None
        
        # 获取 governance 状态
        governance_status = self.execution_manager.get_workflow_status(
            execution.workflow_id
        )
        
        return {
            "execution": execution.model_dump(),
            "governance": governance_status
        }
    
    def _estimate_tokens(self, version: WorkflowVersion) -> int:
        """估计 Token 消耗"""
        # 简化估计：每个节点约 1000 tokens
        return len(version.dag.nodes) * 1000
    
    def _count_tokens(self, result: Dict[str, Any]) -> int:
        """计算实际 Token 消耗"""
        # 简化计算，实际应该从 execution_kernel 获取
        return 0
