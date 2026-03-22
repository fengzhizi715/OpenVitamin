"""
Execution Kernel Adapter
将 Execution Kernel 适配到现有 Agent Runtime 接口

注意：使用统一的 platform.db 数据库，与系统其他模块共享。
V2.7: 集成 Optimization Layer，支持调度策略优化
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging
import json

from execution_kernel.models.graph_definition import GraphDefinition
from execution_kernel.models.node_models import GraphInstanceState
from execution_kernel.persistence.db import Database, init_database, get_platform_db_path
from execution_kernel.engine.scheduler import Scheduler
from execution_kernel.engine.state_machine import StateMachine
from execution_kernel.engine.executor import Executor
from execution_kernel.cache.node_cache import NodeCache
from execution_kernel.events.event_store import EventStore
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.persistence.repositories import (
    NodeRuntimeRepository,
    GraphInstanceRepository,
    NodeCacheRepository,
)

# V2.7: Optimization Layer
from execution_kernel.optimization import (
    OptimizationConfig,
    get_optimization_config,
    OptimizationSnapshot,
    SnapshotBuilder,
    StatisticsCollector,
    DefaultPolicy,
    LearnedPolicy,
)
from execution_kernel.optimization.scheduler.policy_base import SchedulerPolicy

from core.agent_runtime.v2.models import Plan, AgentState, ExecutionTrace, StepLog, StepStatus
from core.execution.adapters.plan_compiler import compile_plan
from core.execution.adapters.node_executors import init_executors, get_executor_registry


logger = logging.getLogger(__name__)


def _get_db_url() -> str:
    """获取统一的数据库 URL（使用 platform.db）"""
    db_path = get_platform_db_path()
    return f"sqlite+aiosqlite:///{db_path}"


class ExecutionKernelAdapter:
    """
    Execution Kernel 适配器
    
    将 Execution Kernel 适配到现有 PlanBasedExecutor 接口
    使用统一的 platform.db 数据库。
    
    V2.7: 支持通过 OptimizationConfig 配置调度策略
    """
    
    def __init__(
        self, 
        db_url: str = None,
        optimization_config: OptimizationConfig = None,
    ):
        # 默认使用统一的 platform.db
        self.db_url = db_url or _get_db_url()
        self.db: Optional[Database] = None
        self._initialized = False
        self._legacy_executor = None
        self._crash_recovery_done = False
        self._stale_cleanup_done = False
        
        # V2.7: Optimization Layer
        self._optimization_config = optimization_config
        self._scheduler_policy: Optional[SchedulerPolicy] = None
        self._optimization_snapshot: Optional[OptimizationSnapshot] = None
        self._rebuild_lock = asyncio.Lock()  # 串行化快照重建，避免并发覆盖
        self._policy_cache: Dict[str, SchedulerPolicy] = {}
        self._snapshot_cache: Dict[str, Optional[OptimizationSnapshot]] = {}
        self._agent_optimization_configs: Dict[str, OptimizationConfig] = {}
    
    async def initialize(self, legacy_executor=None):
        """初始化适配器；可传入 legacy_executor 供 LLMExecutor 使用。"""
        if self._initialized:
            return
        if legacy_executor is not None:
            self._legacy_executor = legacy_executor

        self.db = init_database(self.db_url)
        await self.db.create_tables()

        # 初始化执行器（传入 legacy executor 以便 LLM 节点走现有推理链路）
        init_executors(legacy_executor=self._legacy_executor)

        # V2.7: 初始化 Optimization Layer
        await self._initialize_optimization()

        self._initialized = True
        logger.info("ExecutionKernelAdapter initialized")
    
    async def _initialize_optimization(self) -> None:
        """
        V2.7: 初始化 Optimization Layer
        
        根据 OptimizationConfig 配置调度策略和快照
        """
        # 加载配置（优先使用传入的配置，否则从环境变量加载）
        if self._optimization_config is None:
            self._optimization_config = get_optimization_config()
        
        config = self._optimization_config

        # P1: enabled=false 时必须是严格旁路，不允许策略改变调度行为
        if not config.enabled:
            self._scheduler_policy = DefaultPolicy()
            self._optimization_snapshot = None
            logger.info(
                "V2.7: Optimization disabled, forced DefaultPolicy "
                f"v{self._scheduler_policy.get_version()}"
            )
            await self._emit_optimization_event(
                ExecutionEventType.POLICY_CHANGED,
                {"enabled": False, "policy": self._scheduler_policy.get_name(), "version": self._scheduler_policy.get_version()},
            )
            return
        
        # 创建调度策略
        if config.is_learned_policy():
            policy_params = config.policy_params or {}
            self._scheduler_policy = LearnedPolicy(
                node_weight_factor=policy_params.get("node_weight_factor", 10.0),
                latency_penalty_factor=policy_params.get("latency_penalty_factor", 1.0),
                skill_weight_factor=policy_params.get("skill_weight_factor", 2.0),
                consider_skill=policy_params.get("consider_skill", True),
            )
            logger.info(f"V2.7: Using LearnedPolicy v{self._scheduler_policy.get_version()}")
        else:
            self._scheduler_policy = DefaultPolicy()
            logger.info(f"V2.7: Using DefaultPolicy v{self._scheduler_policy.get_version()}")
        await self._emit_optimization_event(
            ExecutionEventType.POLICY_CHANGED,
            {
                "enabled": True,
                "policy": self._scheduler_policy.get_name(),
                "version": self._scheduler_policy.get_version(),
            },
        )
        
        # 如果启用了优化，尝试构建或加载快照
        if config.enabled and config.auto_build_snapshot:
            await self._build_or_load_snapshot(config.snapshot_version)
    
    async def _build_or_load_snapshot(
        self, 
        target_version: Optional[str] = None
    ) -> None:
        """
        V2.7: 构建或加载 OptimizationSnapshot
        
        Args:
            target_version: 目标快照版本（None 表示构建最新）
        """
        if target_version is not None:
            # TODO: 从持久化存储加载指定版本的快照
            logger.warning(f"V2.7: Loading snapshot version {target_version} not yet implemented, building new")
        
        # 从事件流收集统计信息并构建快照
        try:
            if not (self._optimization_config and self._optimization_config.collect_statistics):
                self._optimization_snapshot = OptimizationSnapshot.empty()
                logger.info("V2.7: collect_statistics disabled, using empty snapshot")
                return
            async with self.db.async_session() as session:
                collector = StatisticsCollector(session)
                dataset = await collector.collect_global(limit_instances=100)
                await self._emit_optimization_event(
                    ExecutionEventType.STATISTICS_COLLECTED,
                    {"event_count": dataset.event_count, "instance_count": dataset.instance_count},
                )
                
                if dataset.node_stats or dataset.skill_stats:
                    builder = SnapshotBuilder()
                    self._optimization_snapshot = builder.build(dataset)
                    logger.info(
                        f"V2.7: Built snapshot v{self._optimization_snapshot.version} "
                        f"from {dataset.event_count} events, {len(dataset.node_stats)} nodes"
                    )
                    await self._emit_optimization_event(
                        ExecutionEventType.SNAPSHOT_BUILT,
                        {
                            "version": self._optimization_snapshot.version,
                            "node_count": len(self._optimization_snapshot.node_weights),
                            "skill_count": len(self._optimization_snapshot.skill_weights),
                        },
                    )
                else:
                    self._optimization_snapshot = OptimizationSnapshot.empty()
                    logger.info("V2.7: No historical data, using empty snapshot")
        except Exception as e:
            logger.warning(f"V2.7: Failed to build snapshot: {e}, using empty snapshot")
            self._optimization_snapshot = OptimizationSnapshot.empty()

    @staticmethod
    def _config_key(config: OptimizationConfig) -> str:
        return json.dumps(config.to_dict(), sort_keys=True, ensure_ascii=False)

    def _resolve_agent_optimization_config(self, agent) -> OptimizationConfig:
        """
        Agent 级配置作用域：按 agent 独立生效，避免全局互扰。
        支持 model_params:
        - optimization
        - optimization_config
        - execution_kernel_optimization
        """
        base = self._optimization_config or get_optimization_config()
        base_dict = base.to_dict()
        params = getattr(agent, "model_params", None) or {}
        override = (
            params.get("execution_kernel_optimization")
            or params.get("optimization_config")
            or params.get("optimization")
            or {}
        )
        if not isinstance(override, dict):
            override = {}

        merged = dict(base_dict)
        for k in ("enabled", "scheduler_policy", "snapshot_version", "auto_build_snapshot", "collect_statistics"):
            if k in override:
                merged[k] = override[k]
        if "policy_params" in override and isinstance(override.get("policy_params"), dict):
            merged["policy_params"] = {
                **(base_dict.get("policy_params") or {}),
                **override["policy_params"],
            }

        cfg = OptimizationConfig.from_dict(merged)
        agent_id = getattr(agent, "agent_id", "") or ""
        if agent_id:
            self._agent_optimization_configs[agent_id] = cfg
        return cfg

    async def _build_policy_snapshot_for_config(
        self, config: OptimizationConfig
    ) -> Tuple[SchedulerPolicy, Optional[OptimizationSnapshot]]:
        """
        为一次执行构建策略与快照，不改变运行实例和图结构。
        """
        if not config.enabled:
            return DefaultPolicy(), None

        if config.is_learned_policy():
            policy_params = config.policy_params or {}
            policy: SchedulerPolicy = LearnedPolicy(
                node_weight_factor=policy_params.get("node_weight_factor", 10.0),
                latency_penalty_factor=policy_params.get("latency_penalty_factor", 1.0),
                skill_weight_factor=policy_params.get("skill_weight_factor", 2.0),
                consider_skill=policy_params.get("consider_skill", True),
            )
        else:
            policy = DefaultPolicy()

        key = self._config_key(config)
        if key in self._snapshot_cache:
            return policy, self._snapshot_cache[key]

        snapshot: Optional[OptimizationSnapshot] = None
        if config.auto_build_snapshot and config.collect_statistics:
            try:
                async with self.db.async_session() as session:
                    collector = StatisticsCollector(session)
                    dataset = await collector.collect_global(limit_instances=100)
                    await self._emit_optimization_event(
                        ExecutionEventType.STATISTICS_COLLECTED,
                        {"event_count": dataset.event_count, "instance_count": dataset.instance_count},
                    )
                    if dataset.node_stats or dataset.skill_stats:
                        snapshot = SnapshotBuilder().build(dataset)
                        await self._emit_optimization_event(
                            ExecutionEventType.SNAPSHOT_BUILT,
                            {
                                "version": snapshot.version,
                                "node_count": len(snapshot.node_weights),
                                "skill_count": len(snapshot.skill_weights),
                            },
                        )
                    else:
                        snapshot = OptimizationSnapshot.empty()
            except Exception as e:
                logger.warning(f"V2.7: failed to build run-scoped snapshot: {e}")
                snapshot = OptimizationSnapshot.empty()

        self._policy_cache[key] = policy
        self._snapshot_cache[key] = snapshot
        return policy, snapshot

    async def _emit_optimization_event(self, event_type: ExecutionEventType, payload: Dict[str, Any]) -> None:
        try:
            async with self.db.async_session() as session:
                store = EventStore(session)
                await store.emit_event(
                    instance_id="__optimization_global__",
                    event_type=event_type,
                    payload=payload,
                )
                await session.commit()
        except Exception:
            # 旁路能力：事件失败不影响主流程
            return
    
    async def close(self):
        """关闭适配器"""
        if self.db:
            await self.db.close()
            self.db = None
        self._initialized = False
        logger.info("ExecutionKernelAdapter closed")
    
    async def execute_plan(
        self,
        plan: Plan,
        state: AgentState,
        session,
        agent,
        messages: list,
        planner=None,
        workspace: str = ".",
        permissions: dict = None,
        metrics = None,
        **kwargs,
    ) -> Tuple[Plan, AgentState, Any]:
        """
        执行 Plan（兼容 PlanBasedExecutor 接口）
        
        Args:
            plan: 要执行的计划
            state: Agent 状态
            session: 会话对象
            agent: Agent 实例
            messages: 消息列表
            planner: Planner 实例（可选）
            
        Returns:
            (updated_plan, updated_state, trace)
        """
        legacy_executor = kwargs.get("executor")
        if not self._initialized:
            await self.initialize(legacy_executor=legacy_executor)
        elif legacy_executor is not None and self._legacy_executor is None:
            self._legacy_executor = legacy_executor
            init_executors(legacy_executor=legacy_executor)

        # 1. 编译 Plan -> GraphDefinition
        graph_def = compile_plan(plan)
        # Agent 级 Optimization Config Scope（运行级，不改图结构）
        effective_opt_config = self._resolve_agent_optimization_config(agent)
        run_policy, run_snapshot = await self._build_policy_snapshot_for_config(effective_opt_config)
        
        # 4. 执行
        instance_id = f"{plan.plan_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        # V2.6: 设置 kernel_instance_id 到 metrics（用于前端 Debug UI）
        if metrics:
            metrics.kernel_instance_id = instance_id
        
        # 2. 创建执行上下文（供 Node Executors 使用，内存态可含复杂对象）
        # Phase B: 延迟创建 runtime_context，以便注入 kernel_instance_id 和 scheduler
        runtime_context_base = {
            "agent": agent,
            "session": session,
            "state": state,
            "messages": messages,
            "planner": planner,
            "workspace": workspace,
            "permissions": permissions or {},
            "trace_id": getattr(session, "trace_id", ""),
            "agent_id": agent.agent_id if hasattr(agent, "agent_id") else "",
        }
        # 持久化到 Kernel DB 的 global_context 必须可 JSON 序列化，避免对象入库失败
        persisted_context = {
            "agent_id": runtime_context_base["agent_id"],
            "session_id": getattr(session, "session_id", ""),
            "trace_id": runtime_context_base["trace_id"],
            "workspace": workspace,
            "permissions": permissions or {},
            "user_id": getattr(session, "user_id", "default") or "default",
        }
        
        # 3. 创建 Scheduler 和 Executor（在 context 设置之前）
        async with self.db.async_session() as db_session:
            cache_repo = NodeCacheRepository(db_session)
            
            state_machine = StateMachine(db=self.db)
            cache = NodeCache(cache_repo)
            
            # V2.7: 创建 Scheduler 时传入 policy 和 snapshot
            scheduler = Scheduler(
                db=self.db,
                state_machine=state_machine,
                executor=None,
                scheduler_policy=run_policy,
                optimization_snapshot=run_snapshot,
            )
            
            # Phase B: 创建完整的 runtime_context（包含 RePlan 所需信息）
            runtime_context = {
                **runtime_context_base,
                "kernel_instance_id": instance_id,
                "kernel_graph_def": graph_def,
                "kernel_scheduler": scheduler,
                "enable_replan_handler": True,  # Phase B: 启用 RePlan handler
            }
            
            # 创建处理器映射
            node_handlers = self._create_handlers(runtime_context)
            
            executor = Executor(
                state_machine=state_machine,
                cache=cache,
                node_handlers=node_handlers,
            )
            
            # 更新 scheduler 的 executor
            scheduler.executor = executor

            # 接入主路径的一次性崩溃恢复（默认不立即重调度，避免无上下文实例被误执行）
            if not self._crash_recovery_done:
                try:
                    if not self._stale_cleanup_done:
                        await scheduler.cleanup_stale_running_instances(max_age_minutes=30)
                        self._stale_cleanup_done = True
                    await scheduler.recover_from_crash(reschedule=False)
                    self._crash_recovery_done = True
                    logger.info("ExecutionKernelAdapter crash recovery initialized (reschedule=False)")
                except Exception as recovery_error:
                    logger.warning(f"ExecutionKernelAdapter crash recovery skipped due to error: {recovery_error}")
        
        await scheduler.start_instance(graph_def, instance_id, persisted_context)
        
        # 5. 等待完成
        final_state = await scheduler.wait_for_completion(instance_id, timeout=600.0)
        
        # 6. 收集结果并转为 ExecutionTrace，便于 runtime 写回 session / trace store
        # Phase A: 收集主图 trace，同时递归收集子图 trace
        trace = await self._collect_trace_with_subgraphs(instance_id, plan.plan_id, final_state, graph_def)

        # 7. 按节点真实状态回写 Plan.step.status，避免失败场景被误标记为 completed
        await self._sync_plan_step_statuses(instance_id, plan)

        return plan, state, trace

    def _create_handlers(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        创建节点处理器；Kernel 调用 handler(node_def, input_data, graph_context)。
        - script -> LLMExecutor
        - tool -> 按 node_def.config.executor 分发到 SkillExecutor / InternalExecutor
        - condition -> 条件表达式求值
        - loop -> 循环控制
        """
        registry = get_executor_registry()
        llm_exec = registry.get("llm")
        skill_exec = registry.get("skill")
        internal_exec = registry.get("internal")

        async def script_handler(node_def, input_data: Dict[str, Any], graph_context=None) -> Dict[str, Any]:
            if not llm_exec:
                logger.warning("No LLM executor registered, returning input")
                return input_data
            runtime_ctx = dict(context)
            if graph_context is not None:
                runtime_ctx["_graph_context"] = graph_context
            return await llm_exec.execute(
                node_def=node_def,
                input_data=input_data,
                context=runtime_ctx,
            )

        async def tool_handler(node_def, input_data: Dict[str, Any], graph_context=None) -> Dict[str, Any]:
            runtime_ctx = dict(context)
            if graph_context is not None:
                runtime_ctx["_graph_context"] = graph_context
            executor_type = (node_def.config or {}).get("executor", "skill")
            if executor_type == "skill" and skill_exec:
                return await skill_exec.execute(
                    node_def=node_def,
                    input_data=input_data,
                    context=runtime_ctx,
                )
            if executor_type == "internal" and internal_exec:
                return await internal_exec.execute(
                    node_def=node_def,
                    input_data=input_data,
                    context=runtime_ctx,
                )
            if skill_exec:
                return await skill_exec.execute(
                    node_def=node_def,
                    input_data=input_data,
                    context=runtime_ctx,
                )
            return {"result": "default", "error": "no executor"}

        # Phase C: 条件节点处理器
        async def condition_handler(node_def, input_data: Dict[str, Any], graph_context=None) -> Dict[str, Any]:
            from execution_kernel.engine.control_flow import execute_condition_node
            from execution_kernel.engine.context import GraphContext
            
            # 创建或复用 GraphContext
            if graph_context is None:
                graph_context = GraphContext(
                    global_data=context.get("global_data", {}),
                    node_outputs=input_data.get("node_outputs", {}),
                )
            
            return await execute_condition_node(node_def, input_data, graph_context)

        # Phase C: 循环节点处理器（基础版，iteration_callback 需后续增强）
        async def loop_handler(node_def, input_data: Dict[str, Any], graph_context=None) -> Dict[str, Any]:
            from execution_kernel.engine.control_flow import execute_loop_node
            from execution_kernel.engine.context import GraphContext
            
            # 创建或复用 GraphContext
            if graph_context is None:
                graph_context = GraphContext(
                    global_data=context.get("global_data", {}),
                    node_outputs=input_data.get("node_outputs", {}),
                )
            
            # Phase C: iteration_callback 暂未与 Scheduler 打通，传 None
            # 完整语义需要 Scheduler 在调度 LOOP 节点时注入 callback
            return await execute_loop_node(
                node_def=node_def,
                input_data=input_data,
                context=graph_context,
                iteration_callback=None,  # TODO: 需 Scheduler 注入
            )

        handlers = {
            "script": script_handler,
            "tool": tool_handler,
            "condition": condition_handler,  # Phase C
            "loop": loop_handler,  # Phase C
        }
        
        # Phase B: 如果上下文包含 RePlan 所需信息，添加 replan_handler
        if context.get("enable_replan_handler"):
            handlers["replan"] = self._create_replan_handler(context)
        
        return handlers
    
    def _create_replan_handler(self, context: Dict[str, Any]):
        """
        Phase B: 创建 RePlan 节点处理器
        
        触发 Planner 生成 followup plan，并应用为 GraphPatch。
        """
        async def replan_handler(node_def, input_data: Dict[str, Any], graph_context=None) -> Dict[str, Any]:
            planner = context.get("planner")
            agent = context.get("agent")
            state = context.get("state")
            instance_id = context.get("kernel_instance_id")
            current_graph = context.get("kernel_graph_def")
            scheduler = context.get("kernel_scheduler")
            
            if not all([planner, agent, state, instance_id, current_graph, scheduler]):
                logger.error("RePlan handler missing required context")
                return {"error": "Missing RePlan context", "patched": False}
            
            # 检查重规划次数限制
            max_replan = getattr(agent, "max_replan_count", 3) or 3
            current_replan_count = state.runtime_state.get("replan_count", 0)
            if current_replan_count >= max_replan:
                logger.warning(f"RePlan: max count {max_replan} reached")
                return {"error": f"Max replan count ({max_replan}) exceeded", "patched": False}
            
            state.set_runtime("replan_count", current_replan_count + 1)
            
            # 构建 RePlan 上下文
            replan_context = {
                **context,
                "replan_instruction": node_def.config.get("replan_instruction", ""),
                "last_failed_step": input_data.get("last_failed_step"),
                "last_error": input_data.get("last_error"),
            }
            
            try:
                # 调用 Planner 生成 followup plan
                followup_plan = await planner.create_followup_plan(
                    agent=agent,
                    execution_context=replan_context,
                    parent_plan_id=current_graph.id,
                )
                
                # 应用 RePlan Patch
                success, message = await self.apply_replan_patch(
                    instance_id=instance_id,
                    followup_plan=followup_plan,
                    current_graph=current_graph,
                    scheduler=scheduler,
                )
                
                if success:
                    # 更新 context 中的 graph_def 引用
                    context["kernel_graph_def"] = scheduler._instance_graphs.get(instance_id, current_graph)
                    logger.info(f"RePlan patch applied: {message}")
                    return {"patched": True, "followup_plan_id": followup_plan.plan_id, "message": message}
                else:
                    logger.error(f"RePlan patch failed: {message}")
                    return {"error": message, "patched": False}
                    
            except Exception as e:
                logger.error(f"RePlan handler error: {e}")
                return {"error": str(e), "patched": False}
        
        return replan_handler

    async def _collect_trace(
        self, 
        instance_id: str, 
        plan_id: str, 
        final_state: GraphInstanceState,
        parent_step_id: str = None,
        depth: int = 0,
    ) -> ExecutionTrace:
        """
        收集执行追踪并转为 ExecutionTrace，兼容 runtime 的 _plan_result_to_session 与 trace store。
        
        Phase A: 支持层级追踪，通过 parent_step_id 和 depth 参数传递层级信息。
        """
        async with self.db.async_session() as session:
            node_repo = NodeRuntimeRepository(session)
            nodes = await node_repo.get_all_by_instance(instance_id)
            nodes_sorted = sorted(nodes, key=lambda n: (n.started_at or datetime.min).isoformat())

        step_logs = []
        for n in nodes_sorted:
            duration_ms = None
            if n.started_at and n.finished_at:
                delta = n.finished_at - n.started_at
                duration_ms = delta.total_seconds() * 1000
            state_val = getattr(n.state, "value", str(n.state)).lower()
            ts = n.started_at or getattr(n, "created_at", None)
            timestamp = ts.isoformat() if ts else ""
            finished_ts = n.finished_at.isoformat() if n.finished_at else timestamp
            input_payload = dict(n.input_data or {})
            input_payload["_step_id"] = n.node_id
            input_payload["_node_runtime_id"] = n.id
            tool_id = input_payload.get("skill_id") if isinstance(input_payload, dict) else None

            # 1) start 事件（便于前端还原生命周期）
            step_logs.append(
                StepLog(
                    step_id=n.node_id,
                    parent_step_id=parent_step_id,
                    depth=depth,
                    timestamp=timestamp,
                    event_type="start",
                    input_data=input_payload,
                    output_data={},
                    duration_ms=None,
                    tool_id=tool_id if isinstance(tool_id, str) else None,
                )
            )

            # 2) 终态事件（complete / error / output）
            event_type = "complete" if state_val == "success" else ("error" if state_val in ("failed", "timeout") else "output")
            output_payload = n.output_data if isinstance(n.output_data, dict) else {"value": str(n.output_data)}
            if event_type == "error":
                err_obj = output_payload.get("error") if isinstance(output_payload, dict) else None
                if not isinstance(err_obj, dict):
                    err_obj = {}
                if n.error_type and "type" not in err_obj:
                    err_obj["type"] = n.error_type
                if n.error_message and "message" not in err_obj:
                    err_obj["message"] = n.error_message
                if "code" not in err_obj:
                    err_obj["code"] = "EXECUTION_ERROR"
                output_payload = dict(output_payload or {})
                output_payload["error"] = err_obj
                output_payload["error_code"] = err_obj.get("code")
                output_payload["error_type"] = err_obj.get("type")

            step_logs.append(
                StepLog(
                    step_id=n.node_id,
                    parent_step_id=parent_step_id,
                    depth=depth,
                    timestamp=finished_ts,
                    event_type=event_type,
                    input_data=input_payload,
                    output_data=output_payload,
                    duration_ms=duration_ms,
                    tool_id=tool_id if isinstance(tool_id, str) else None,
                )
            )

        trace = ExecutionTrace(plan_id=plan_id, step_logs=step_logs)
        if final_state == GraphInstanceState.COMPLETED:
            trace.mark_completed()
        elif final_state == GraphInstanceState.FAILED:
            trace.mark_failed()
        else:
            trace.final_status = final_state.value
        return trace

    async def _collect_trace_with_subgraphs(
        self,
        instance_id: str,
        plan_id: str,
        final_state: GraphInstanceState,
        graph_def: GraphDefinition,
        parent_step_id: str = None,
        depth: int = 0,
    ) -> ExecutionTrace:
        """
        Phase A: 递归收集主图和子图的 trace，保持层级关系。
        
        1. 收集主图 trace
        2. 对于每个子图，递归收集并关联
        3. 返回包含 subgraph_traces 的完整 ExecutionTrace
        """
        # 1. 收集主图 trace
        trace = await self._collect_trace(instance_id, plan_id, final_state, parent_step_id, depth)
        
        # 2. 收集子图 traces
        for subgraph_def in graph_def.subgraphs:
            subgraph_instance_id = f"{instance_id}_{subgraph_def.parent_node_id}_sub"
            
            # 获取子图状态
            async with self.db.async_session() as session:
                from execution_kernel.persistence.repositories import GraphInstanceRepository
                instance_repo = GraphInstanceRepository(session)
                subgraph_instance = await instance_repo.get(subgraph_instance_id)
                subgraph_state = subgraph_instance.state if subgraph_instance else None
            
            if subgraph_state:
                from execution_kernel.models.node_models import GraphInstanceState
                subgraph_final_state = GraphInstanceState(subgraph_state.value)
                
                # 递归收集子图 trace（depth + 1）
                subgraph_trace = await self._collect_trace_with_subgraphs(
                    subgraph_instance_id,
                    subgraph_def.graph.id,
                    subgraph_final_state,
                    subgraph_def.graph,
                    parent_step_id=subgraph_def.parent_node_id,  # 子图的 parent 是 Composite 节点
                    depth=depth + 1,
                )
                
                # 关联子图 trace
                trace.add_subgraph_trace(subgraph_def.parent_node_id, subgraph_trace)
        
        return trace

    async def _sync_plan_step_statuses(self, instance_id: str, plan: Plan) -> None:
        """
        将 Kernel 节点状态映射回 Plan.step.status。
        映射：
        - success/skipped/cancelled -> completed
        - failed/timeout -> failed
        - running/retrying -> running
        - pending/unknown -> pending
        """
        async with self.db.async_session() as session:
            node_repo = NodeRuntimeRepository(session)
            nodes = await node_repo.get_all_by_instance(instance_id)

        node_map = {n.node_id: n for n in nodes}
        for step in plan.steps:
            node = node_map.get(step.step_id)
            state = str(node.state.value) if node is not None else "pending"
            if state in {"success", "skipped", "cancelled"}:
                step.status = StepStatus.COMPLETED
                if node is not None and isinstance(node.output_data, dict):
                    # 将 Kernel 节点输出回填到 Plan 步骤，供 Runtime 组装最终 assistant 回复
                    step.outputs = node.output_data
            elif state in {"failed", "timeout"}:
                step.status = StepStatus.FAILED
                if node is not None:
                    if isinstance(node.output_data, dict) and node.output_data:
                        step.outputs = node.output_data
                    if node.error_message:
                        step.error = node.error_message
            elif state in {"running", "retrying"}:
                step.status = StepStatus.RUNNING
            else:
                step.status = StepStatus.PENDING

    async def apply_replan_patch(
        self,
        instance_id: str,
        followup_plan: Plan,
        current_graph: GraphDefinition,
        scheduler: Scheduler,
    ) -> Tuple[bool, str]:
        """
        Phase B: RePlan 触发动态图扩展
        
        将 followup plan 编译为 GraphPatch 并应用到运行中的实例。
        
        Args:
            instance_id: 当前运行的实例 ID
            followup_plan: 生成的 followup plan
            current_graph: 当前图定义
            scheduler: Scheduler 实例
        
        Returns:
            (success, message)
        """
        from execution_kernel.models.graph_patch import (
            GraphPatch,
            AddNodeOperation,
            AddEdgeOperation,
            PatchOperationType,
        )
        from execution_kernel.engine.graph_patcher import GraphPatcher
        
        # 1. 编译 followup plan 为增量图
        followup_graph = compile_plan(followup_plan)
        
        # 2. 生成 Patch 操作
        operations = []
        
        # 添加新节点
        for node in followup_graph.nodes:
            if not current_graph.get_node(node.id):
                operations.append(AddNodeOperation(
                    node_id=node.id,
                    node_type=node.type.value,
                    config=dict(node.config),
                    input_schema=dict(node.input_schema),
                    output_schema=dict(node.output_schema),
                    timeout_seconds=node.timeout_seconds,
                ))
        
        # 添加新边
        for edge in followup_graph.edges:
            operations.append(AddEdgeOperation(
                from_node=edge.from_node,
                to_node=edge.to_node,
                on=edge.on.value,
                condition=edge.condition,
            ))
        
        if not operations:
            return True, "No new operations to apply"
        
        # 3. 生成 Patch
        patcher = GraphPatcher()
        next_version = patcher.generate_next_version(current_graph.version)
        
        patch = GraphPatch(
            patch_id=f"replan_{instance_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            target_graph_id=current_graph.id,
            base_version=current_graph.version,
            target_version=next_version,
            operations=operations,
            reason=f"RePlan: {followup_plan.goal}",
        )
        
        # 4. 应用 Patch
        try:
            result = await scheduler.apply_patch(instance_id, patch)
            if result.success:
                return True, f"Patch applied: {result.applied_operations} operations, version {result.applied_version}"
            else:
                return False, f"Patch failed: {result.errors}"
        except Exception as e:
            logger.error(f"RePlan patch error: {e}")
            return False, str(e)
    
    # ===================== V2.7: Optimization Layer Public API =====================
    
    def get_optimization_status(self) -> Dict[str, Any]:
        """
        V2.7: 获取 Optimization Layer 状态
        
        Returns:
            包含配置、策略和快照信息的字典
        """
        config = self._optimization_config or get_optimization_config()
        
        return {
            "enabled": config.enabled,
            "scheduler_policy": {
                "name": self._scheduler_policy.get_name() if self._scheduler_policy else None,
                "version": self._scheduler_policy.get_version() if self._scheduler_policy else None,
            },
            "snapshot": {
                "version": self._optimization_snapshot.version if self._optimization_snapshot else None,
                "node_count": len(self._optimization_snapshot.node_weights) if self._optimization_snapshot else 0,
                "skill_count": len(self._optimization_snapshot.skill_weights) if self._optimization_snapshot else 0,
            },
            "agent_scoped_configs": {
                "count": len(self._agent_optimization_configs),
                "agent_ids": list(self._agent_optimization_configs.keys())[:20],
            },
            "config": config.to_dict() if config else {},
        }
    
    async def rebuild_optimization_snapshot(
        self,
        instance_ids: Optional[list] = None,
        limit_instances: int = 100,
    ) -> OptimizationSnapshot:
        """
        V2.7: 重新构建 OptimizationSnapshot
        
        从事件流收集最新的统计信息并构建新快照。
        这可以定期调用以更新调度优化数据。
        使用锁串行化并发调用，避免同时重建导致快照被覆盖。
        
        Args:
            instance_ids: 指定收集的实例 ID 列表（None 表示全局收集）
            limit_instances: 最大实例数量限制
            
        Returns:
            新的 OptimizationSnapshot
        """
        async with self._rebuild_lock:
            try:
                config = self._optimization_config or get_optimization_config()
                if not config.collect_statistics:
                    self._optimization_snapshot = OptimizationSnapshot.empty()
                    return self._optimization_snapshot
                async with self.db.async_session() as session:
                    collector = StatisticsCollector(session)
                    
                    if instance_ids:
                        dataset = await collector.collect_from_instances(instance_ids)
                    else:
                        dataset = await collector.collect_global(limit_instances=limit_instances)
                    await self._emit_optimization_event(
                        ExecutionEventType.STATISTICS_COLLECTED,
                        {"event_count": dataset.event_count, "instance_count": dataset.instance_count},
                    )
                    
                    if dataset.node_stats or dataset.skill_stats:
                        builder = SnapshotBuilder()
                        self._optimization_snapshot = builder.build(dataset)
                        logger.info(
                            f"V2.7: Rebuilt snapshot v{self._optimization_snapshot.version} "
                            f"from {dataset.event_count} events"
                        )
                        await self._emit_optimization_event(
                            ExecutionEventType.SNAPSHOT_BUILT,
                            {
                                "version": self._optimization_snapshot.version,
                                "node_count": len(self._optimization_snapshot.node_weights),
                                "skill_count": len(self._optimization_snapshot.skill_weights),
                            },
                        )
                    else:
                        self._optimization_snapshot = OptimizationSnapshot.empty()
                        logger.info("V2.7: No data for snapshot, using empty")
                    
                    return self._optimization_snapshot
                
            except Exception as e:
                logger.error(f"V2.7: Failed to rebuild snapshot: {e}")
                raise
    
    def set_scheduler_policy(
        self,
        policy: SchedulerPolicy,
        snapshot: Optional[OptimizationSnapshot] = None,
    ) -> None:
        """
        V2.7: 动态设置调度策略
        
        允许运行时切换策略，无需重新初始化整个适配器。
        
        Args:
            policy: 新的调度策略
            snapshot: 可选的优化快照
        """
        self._scheduler_policy = policy
        if snapshot is not None:
            self._optimization_snapshot = snapshot
        
        logger.info(
            f"V2.7: Scheduler policy updated to {policy.get_name()} v{policy.get_version()}, "
            f"snapshot={self._optimization_snapshot.version if self._optimization_snapshot else None}"
        )
        # fire-and-forget
        try:
            asyncio.create_task(
                self._emit_optimization_event(
                    ExecutionEventType.POLICY_CHANGED,
                    {
                        "policy": policy.get_name(),
                        "version": policy.get_version(),
                        "snapshot_version": self._optimization_snapshot.version if self._optimization_snapshot else None,
                    },
                )
            )
        except Exception:
            pass
    
    def set_optimization_config(self, config: OptimizationConfig) -> None:
        """
        V2.7: 更新 Optimization 配置
        
        注意：更改配置后需要调用 initialize() 或 rebuild_optimization_snapshot()
        以应用新的策略设置。
        
        Args:
            config: 新的配置
        """
        self._optimization_config = config
        # 仅更新当前 adapter，避免跨 agent / 会话的全局配置污染
        self._policy_cache.clear()
        self._snapshot_cache.clear()
        logger.info(f"V2.7: Optimization config updated: enabled={config.enabled}, policy={config.scheduler_policy}")
