"""
Scheduler
事件驱动调度器，基于数据库查询实现拓扑安全执行
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Set, List, Optional
import logging
from collections import defaultdict
import os

from execution_kernel.models.graph_definition import GraphDefinition, EdgeTrigger, SubgraphDefinition
from execution_kernel.models.node_models import NodeRuntime, NodeState, GraphInstanceState
from execution_kernel.models.graph_instance import NodeRuntimeDB, NodeStateDB, GraphInstanceStateDB
from execution_kernel.models.graph_patch import (
    GraphPatch, 
    GraphPatchResult, 
    ExecutionPointer,
    PatchMigrationPlan,
)
from execution_kernel.engine.state_machine import StateMachine
from execution_kernel.engine.executor import Executor
from execution_kernel.engine.context import GraphContext
from execution_kernel.engine.graph_patcher import GraphPatcher
from execution_kernel.persistence.repositories import (
    GraphInstanceRepository,
    NodeRuntimeRepository,
    GraphDefinitionRepository,
    GraphPatchRepository,
    ExecutionPointerRepository,
)
from execution_kernel.persistence.db import Database
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.exc import OperationalError

# V2.6: Observability & Replay Layer
from execution_kernel.events.event_store import EventStore, ExecutionEventDB
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.events.event_model import EventPayloadBuilder

# V2.7: Optimization Layer
from execution_kernel.optimization.scheduler.policy_base import SchedulerPolicy, PolicyContext
from execution_kernel.optimization.scheduler.default_policy import DefaultPolicy
from execution_kernel.optimization.snapshot.snapshot import OptimizationSnapshot


logger = logging.getLogger(__name__)
POINTER_UPDATE_STRATEGY = (os.getenv("EXECUTION_POINTER_STRATEGY", "best_effort") or "best_effort").strip().lower()


class Scheduler:
    """
    事件驱动调度器
    
    特性：
    - 事件驱动调度
    - 基于数据库查询 pending 节点
    - 拓扑安全执行
    - 支持并行节点
    - 支持 retry
    
    要求：
    - 不允许 for-loop 顺序执行
    - 每个节点执行完成后触发下游节点调度
    - 依赖必须全部成功才可执行
    - 支持 retry backoff
    """
    
    def __init__(
        self,
        db: Database,
        state_machine: StateMachine,
        executor: Executor,
        scheduler_policy: Optional[SchedulerPolicy] = None,
        optimization_snapshot: Optional[OptimizationSnapshot] = None,
    ):
        self.db = db
        self.state_machine = state_machine
        self.executor = executor
        self.graph_patcher = GraphPatcher()
            
        # V2.7: 调度策略和优化快照
        self._scheduler_policy: SchedulerPolicy = scheduler_policy or DefaultPolicy()
        self._optimization_snapshot: Optional[OptimizationSnapshot] = optimization_snapshot
            
        # 运行中的任务跟踪
        self._running_tasks: Dict[str, asyncio.Task] = {}
        # 并发控制
        self._max_concurrency = 10
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
            
        # Phase B: 实例图定义缓存（支持动态更新）
        self._instance_graphs: Dict[str, GraphDefinition] = {}
        # 调度事件
        self._schedule_event = asyncio.Event()
        # 同一实例的执行指针写入串行化，避免 SQLite 行级写锁冲突
        self._pointer_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # 防重复分发（覆盖"排队中 + 运行中"两个阶段）
        self._dispatching_tasks: Set[str] = set()
            
        # V2.6: Event Store 不缓存，每次使用当前 session 创建（避免跨 session 复用导致已关闭 session 写入）
    
    async def _emit_event(
        self,
        session,
        instance_id: str,
        event_type: ExecutionEventType,
        payload: Dict[str, Any],
    ):
        """
        V2.6: 发射事件（fire-and-forget，失败不影响主流程）
        
        Args:
            session: 数据库会话
            instance_id: 实例 ID
            event_type: 事件类型
            payload: 事件负载
        """
        try:
            event_store = EventStore(session)
            await event_store.emit_event(instance_id, event_type, payload)
        except Exception as e:
            # 事件发射失败不影响主流程
            logger.warning(f"Failed to emit event {event_type.value}: {e}")
    
    async def start_instance(
        self,
        graph_def: GraphDefinition,
        instance_id: str,
        global_context: Dict[str, Any] = None,
    ) -> str:
        """
        启动图实例执行
        
        1. 创建图实例
        2. 创建所有节点运行时
        3. 调度入口节点
        """
        async with self.db.async_session() as session:
            instance_repo = GraphInstanceRepository(session)
            node_repo = NodeRuntimeRepository(session)
            def_repo = GraphDefinitionRepository(session)
            
            # 保存图定义
            await def_repo.save(graph_def)
            
            # 创建图实例
            from execution_kernel.models.node_models import GraphInstance
            instance = GraphInstance(
                id=instance_id,
                graph_definition_id=graph_def.id,
                graph_definition_version=graph_def.version,
                state=GraphInstanceState.RUNNING,
                global_context=global_context or {},
                started_at=datetime.utcnow(),
            )
            await instance_repo.create(instance)
            
            # 创建所有节点运行时（Phase B: 只创建启用的节点）
            entry_nodes = graph_def.get_entry_nodes()
            for node_def in graph_def.get_enabled_nodes():
                node_runtime = NodeRuntime(
                    graph_instance_id=instance_id,
                    node_id=node_def.id,
                    state=NodeState.PENDING,
                    input_data=node_def.config.get("default_input", {}),
                )
                await node_repo.create(node_runtime)
            
            # V2.6: 发射 GraphStarted 事件
            await self._emit_event(
                session,
                instance_id,
                ExecutionEventType.GRAPH_STARTED,
                EventPayloadBuilder.graph_started(
                    graph_id=graph_def.id,
                    graph_version=graph_def.version,
                    initial_context=global_context or {},
                ),
            )
            
            await session.commit()
        
        # Phase B: 缓存图定义
        self._instance_graphs[instance_id] = graph_def
        
        # Phase B: 初始化执行指针
        async with self.db.async_session() as session:
            pointer_repo = ExecutionPointerRepository(session)
            pointer = ExecutionPointer(
                instance_id=instance_id,
                graph_version=graph_def.version,
            )
            await pointer_repo.save(pointer)
        
        logger.info(f"Graph instance {instance_id} created with {len(graph_def.get_enabled_nodes())} enabled nodes")
        
        # 开始调度
        await self._schedule_next(instance_id)
        
        return instance_id

    async def cancel_instance(self, instance_id: str, reason: Optional[str] = None) -> bool:
        """
        Best-effort cancellation for a running instance.

        Semantics:
        - Mark GraphInstance as CANCELLED (terminal)
        - Mark all non-terminal nodes as CANCELLED
        - Cancel any in-flight asyncio tasks owned by this Scheduler for the instance

        Note: This cannot preempt external processes started by tools; tool handlers should
        handle cancellation cooperatively if needed.
        """
        # 1) Cancel in-flight tasks (best-effort)
        prefix = f"{instance_id}:"
        for task_key, task in list(self._running_tasks.items()):
            if task_key.startswith(prefix):
                try:
                    task.cancel()
                except Exception:
                    pass

        # 2) Update DB state（SQLite 锁冲突下做指数退避重试）
        max_retries = 6
        base_delay = 0.1
        for attempt in range(1, max_retries + 1):
            try:
                async with self.db.async_session() as session:
                    instance_repo = GraphInstanceRepository(session)
                    node_repo = NodeRuntimeRepository(session)

                    instance_db = await instance_repo.get(instance_id, for_update=True)
                    if not instance_db:
                        return False

                    # Idempotent: if already terminal, keep as-is.
                    if instance_db.state in {
                        GraphInstanceStateDB.COMPLETED,
                        GraphInstanceStateDB.FAILED,
                        GraphInstanceStateDB.CANCELLED,
                    }:
                        return True

                    await instance_repo.update_state(
                        instance_id,
                        GraphInstanceState.CANCELLED,
                        finished_at=datetime.utcnow(),
                    )

                    all_nodes = await node_repo.get_all_by_instance(instance_id)
                    now = datetime.utcnow()
                    for n in all_nodes:
                        if n.state in {NodeStateDB.SUCCESS, NodeStateDB.SKIPPED, NodeStateDB.CANCELLED}:
                            continue
                        n.state = NodeStateDB.CANCELLED
                        if reason:
                            n.error_message = reason
                        n.finished_at = now
                        n.updated_at = now

                    await session.commit()
                    return True
            except OperationalError as e:
                msg = str(e).lower()
                if "database is locked" not in msg or attempt >= max_retries:
                    raise
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "cancel_instance retry due to DB lock: instance_id=%s attempt=%s/%s delay=%.2fs",
                    instance_id,
                    attempt,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
        return False
    
    async def _schedule_next(self, instance_id: str):
        """
        调度下一批可执行节点
        
        查找所有 pending 状态且依赖已满足的节点
        """
        async with self.db.async_session() as session:
            node_repo = NodeRuntimeRepository(session)
            def_repo = GraphDefinitionRepository(session)
            instance_repo = GraphInstanceRepository(session)
            
            # 获取图实例
            instance_db = await instance_repo.get(instance_id)
            if not instance_db:
                logger.error(f"Instance {instance_id} not found")
                return
            if instance_db.state == GraphInstanceStateDB.CANCELLED:
                logger.info(f"Instance {instance_id} is cancelled, skipping scheduling")
                return
            
            # Phase B: 按版本获取图定义
            graph_version = instance_db.graph_definition_version
            graph_def = await def_repo.get_definition(
                instance_db.graph_definition_id,
                version=graph_version,  # 指定版本读取
            )
            if not graph_def:
                logger.error(
                    f"Graph definition {instance_db.graph_definition_id} v{graph_version} not found"
                )
                return
            
            # 获取所有节点运行时
            all_nodes = await node_repo.get_all_by_instance(instance_id)
            node_states = {n.node_id: NodeState(n.state.value) for n in all_nodes}
            
            # 查找可执行节点
            executable_nodes = []
            for node_db in all_nodes:
                if NodeState(node_db.state.value) != NodeState.PENDING:
                    continue
                
                # Phase C: 使用增强的依赖检查（支持条件边）
                deps_satisfied = await self._check_dependencies_with_edges(
                    node_db.node_id,
                    graph_def,
                    node_states,
                    all_nodes,
                )
                
                if deps_satisfied:
                    executable_nodes.append(node_db)
            
            # V2.7: 使用调度策略对可执行节点排序
            if len(executable_nodes) > 1 and self._scheduler_policy:
                executable_nodes = await self._sort_nodes_with_policy(
                    executable_nodes, graph_def, instance_id, all_nodes, node_states
                )
            else:
                # V2.6: 确定性排序 - 按 node_id 排序确保调度顺序一致
                executable_nodes.sort(key=lambda n: n.node_id)
            
            if not executable_nodes:
                # 将因分支路径未命中而“永远不可满足”的 pending 节点标记为 skipped，
                # 避免实例长期停留在 running。
                skipped_any = False
                now = datetime.utcnow()
                for node_db in all_nodes:
                    if NodeState(node_db.state.value) != NodeState.PENDING:
                        continue
                    if self._is_node_unreachable(node_db.node_id, graph_def, node_states, all_nodes):
                        node_db.state = NodeStateDB.SKIPPED
                        node_db.finished_at = now
                        node_db.updated_at = now
                        skipped_any = True
                        logger.info(
                            "Node %s marked as skipped (unreachable dependencies): instance_id=%s",
                            node_db.node_id,
                            instance_id,
                        )
                        await self._emit_event(
                            session,
                            instance_id,
                            ExecutionEventType.NODE_SKIPPED,
                            {
                                "node_id": node_db.node_id,
                                "reason": "unreachable_dependencies",
                            },
                        )

                if skipped_any:
                    # 刷新内存态用于后续完成态判断
                    node_states = {n.node_id: NodeState(n.state.value) for n in all_nodes}

                # 检查是否所有节点都完成
                all_finished = all(
                    node_states[n.node_id] in {NodeState.SUCCESS, NodeState.SKIPPED, NodeState.CANCELLED}
                    for n in all_nodes
                )
                
                if all_finished:
                    await instance_repo.update_state(
                        instance_id, 
                        GraphInstanceState.COMPLETED,
                        finished_at=datetime.utcnow(),
                    )
                    logger.info(f"Graph instance {instance_id} completed")
                    
                    # V2.6: 发射 GraphCompleted 事件
                    completed_count = sum(1 for n in all_nodes if node_states[n.node_id] == NodeState.SUCCESS)
                    failed_count = sum(1 for n in all_nodes if node_states[n.node_id] == NodeState.FAILED)
                    await self._emit_event(
                        session,
                        instance_id,
                        ExecutionEventType.GRAPH_COMPLETED,
                        EventPayloadBuilder.graph_completed(
                            final_state="completed",
                            completed_nodes=completed_count,
                            failed_nodes=failed_count,
                        ),
                    )
                    
                    # Phase B: 更新执行指针为完成状态
                    await self._update_pointer_on_completion(instance_id)
                else:
                    # 检查是否有失败的节点导致无法继续
                    has_failed = any(
                        node_states[n.node_id] == NodeState.FAILED
                        for n in all_nodes
                    )
                    if has_failed:
                        await instance_repo.update_state(
                            instance_id,
                            GraphInstanceState.FAILED,
                            finished_at=datetime.utcnow(),
                        )
                        logger.info(f"Graph instance {instance_id} failed")
                        
                        # V2.6: 发射 GraphFailed 事件
                        failed_count = sum(1 for n in all_nodes if node_states[n.node_id] == NodeState.FAILED)
                        await self._emit_event(
                            session,
                            instance_id,
                            ExecutionEventType.GRAPH_FAILED,
                            EventPayloadBuilder.graph_completed(
                                final_state="failed",
                                completed_nodes=0,
                                failed_nodes=failed_count,
                            ),
                        )
                        
                        # Phase B: 更新执行指针为失败状态
                        await self._update_pointer_on_failure(instance_id, all_nodes)
                # 关键：该分支会直接 return，必须提交 graph_instance 状态变更与事件写入
                await session.commit()
                return
            
            # 并行执行可执行节点
            await session.commit()
        
        # 在 session 外并行执行节点（受并发上限约束）
        available_slots = max(0, self._max_concurrency - len(self._running_tasks))
        if available_slots <= 0:
            logger.debug(
                f"Scheduler at concurrency limit ({self._max_concurrency}), "
                f"running={len(self._running_tasks)}"
            )
            return

        nodes_to_schedule = executable_nodes[:available_slots]
        
        # V2.6: 发射 SchedulerDecision 事件
        if nodes_to_schedule:
            async with self.db.async_session() as session:
                ready_node_ids = [n.node_id for n in executable_nodes]
                selected_node_ids = [n.node_id for n in nodes_to_schedule]
                
                # 构建决策原因
                if len(ready_node_ids) > len(selected_node_ids):
                    decision_reason = f"concurrency_limit({self._max_concurrency}): selected {len(selected_node_ids)} of {len(ready_node_ids)} ready nodes"
                elif len(ready_node_ids) == 1:
                    decision_reason = "single_ready_node"
                else:
                    decision_reason = f"all_ready_nodes({len(ready_node_ids)})"
                
                # V2.7: 获取策略信息
                policy_info = {
                    "policy_name": self._scheduler_policy.get_name(),
                    "policy_version": self._scheduler_policy.get_version(),
                    "snapshot_version": self._optimization_snapshot.version if self._optimization_snapshot else None,
                }
                
                for node_db in nodes_to_schedule:
                    selected_node = node_db.node_id
                    
                    # V2.7: SchedulerDecision 事件（包含 policy_version 和 snapshot_version）
                    await self._emit_event(
                        session,
                        instance_id,
                        ExecutionEventType.SCHEDULER_DECISION,
                        EventPayloadBuilder.scheduler_decision(
                            ready_nodes=ready_node_ids,
                            selected_node=selected_node,
                            strategy=policy_info["policy_name"],
                            decision_reason=decision_reason,
                            policy_version=policy_info["policy_version"],
                            snapshot_version=policy_info["snapshot_version"],
                        ),
                    )
                    
                    # V2.6: NodeScheduled 事件（节点被调度，等待执行）
                    node_def = graph_def.get_node(selected_node)
                    if node_def:
                        await self._emit_event(
                            session,
                            instance_id,
                            ExecutionEventType.NODE_SCHEDULED,
                            EventPayloadBuilder.node_scheduled(
                                node_id=selected_node,
                                node_type=node_def.type.value,
                                dependencies=[],  # 依赖已在 SchedulerDecision 中记录
                            ),
                        )
        
        tasks = [
            self._dispatch_node(instance_id, node_db.node_id, graph_def)
            for node_db in nodes_to_schedule
        ]
        if tasks:
            await asyncio.gather(*tasks)
    
    async def _dispatch_node(
        self,
        instance_id: str,
        node_id: str,
        graph_def: GraphDefinition,
    ):
        """分发节点执行"""
        task_key = f"{instance_id}:{node_id}"
        
        # 防重复分发：在任何 await 前占位，避免竞态导致同节点重复执行
        if task_key in self._dispatching_tasks:
            logger.debug(f"Node {node_id} already running")
            return
        self._dispatching_tasks.add(task_key)
        
        try:
            # 先检查节点状态，避免重复调度
            async with self.db.async_session() as session:
                node_repo = NodeRuntimeRepository(session)
                node_db = await node_repo.get_by_instance_and_node(instance_id, node_id)
                if node_db and NodeState(node_db.state.value) != NodeState.PENDING:
                    logger.debug(f"Node {node_id} not pending (state={node_db.state.value}), skipping dispatch")
                    return
            
            async with self._semaphore:
                # 创建执行任务
                task = asyncio.create_task(
                    self._execute_node_task(instance_id, node_id, graph_def)
                )
                self._running_tasks[task_key] = task
                
                try:
                    await task
                finally:
                    self._running_tasks.pop(task_key, None)
            
            # 触发下一轮调度（在释放并发槽后）
            await self._schedule_next(instance_id)
        finally:
            self._dispatching_tasks.discard(task_key)
    
    async def _execute_node_task(
        self,
        instance_id: str,
        node_id: str,
        graph_def: GraphDefinition,
    ):
        """执行单个节点"""
        node_def = graph_def.get_node(node_id)
        if not node_def:
            logger.error(f"Node definition {node_id} not found")
            return
        
        # Phase A: 检查是否是 Composite 节点（有子图）
        subgraph_def = None
        for sg in graph_def.subgraphs:
            if sg.parent_node_id == node_id:
                subgraph_def = sg
                break
        
        # 如果是 Composite 节点，先执行子图
        if subgraph_def:
            logger.info(f"Node {node_id} is COMPOSITE, executing subgraph first")
            subgraph_success = await self._execute_subgraph(
                instance_id, node_id, subgraph_def, graph_def
            )
            if not subgraph_success:
                logger.error(f"Subgraph execution failed for node {node_id}")
                return
        
        async with self.db.async_session() as session:
            node_repo = NodeRuntimeRepository(session)
            instance_repo = GraphInstanceRepository(session)
            
            # 获取节点运行时（加锁）
            node_db = await node_repo.get_by_instance_and_node(
                instance_id, node_id, for_update=True
            )
            if not node_db:
                logger.error(f"Node runtime {node_id} not found")
                return
            
            # 幂等检查
            if NodeState(node_db.state.value) != NodeState.PENDING:
                logger.debug(f"Node {node_id} not pending, skipping")
                return
            
            # 获取实例和构建上下文
            instance_db = await instance_repo.get(instance_id)
            
            # 获取所有已完成节点的输出
            all_nodes = await node_repo.get_all_by_instance(instance_id)
            merged_input = self._compose_node_input_from_upstreams(
                node_id=node_id,
                graph_def=graph_def,
                all_nodes=all_nodes,
                current_input=node_db.input_data,
            )
            if merged_input != (node_db.input_data or {}):
                node_db.input_data = merged_input
                flag_modified(node_db, "input_data")
            node_outputs = {}
            for n in all_nodes:
                if NodeState(n.state.value) == NodeState.SUCCESS:
                    node_outputs[n.node_id] = n.output_data
            
            context = GraphContext(
                global_data=instance_db.global_context,
                node_outputs=node_outputs,
            )
            
            # 构建 node_runtime
            node_runtime = NodeRuntime(
                id=node_db.id,
                graph_instance_id=node_db.graph_instance_id,
                node_id=node_db.node_id,
                state=NodeState(node_db.state.value),
                input_data=merged_input,
                output_data=node_db.output_data,
                retry_count=node_db.retry_count,
                error_message=node_db.error_message,
                error_type=node_db.error_type,
                started_at=node_db.started_at,
                finished_at=node_db.finished_at,
                created_at=node_db.created_at,
                updated_at=node_db.updated_at,
            )
            
            await session.commit()
        
        # Phase B: 更新执行指针为运行中
        await self._update_pointer_node_started(instance_id, node_id)
        
        # V2.6: 发射 NodeStarted 事件
        async with self.db.async_session() as session:
            await self._emit_event(
                session,
                instance_id,
                ExecutionEventType.NODE_STARTED,
                EventPayloadBuilder.node_started(
                    node_id=node_id,
                    node_type=node_def.type.value,
                    input_data=node_runtime.input_data,
                ),
            )
        
        # 执行节点（带重试）
        node_started_at = datetime.utcnow()
        try:
            output = await self.executor.execute_with_retry(
                node_runtime, node_def, context
            )
            
            # 更新上下文
            context.set_node_output(node_id, output)
            
            # Phase B: 更新执行指针为完成
            await self._update_pointer_node_completed(instance_id, node_id)
            
            # V2.6: 发射 NodeSucceeded 事件（duration 用本地时间差，避免依赖未刷新的 node_db）
            async with self.db.async_session() as session:
                duration_ms = int((datetime.utcnow() - node_started_at).total_seconds() * 1000)
                
                await self._emit_event(
                    session,
                    instance_id,
                    ExecutionEventType.NODE_SUCCEEDED,
                    EventPayloadBuilder.node_succeeded(
                        node_id=node_id,
                        output_data=output,
                        duration_ms=duration_ms,
                    ),
                )
            
            logger.info(f"Node {node_id} completed with output: {list(output.keys())}")
            
        except Exception as e:
            logger.exception(f"Node {node_id} execution failed: {e}")
            
            # V2.6: 发射 NodeFailed 事件
            async with self.db.async_session() as session:
                await self._emit_event(
                    session,
                    instance_id,
                    ExecutionEventType.NODE_FAILED,
                    EventPayloadBuilder.node_failed(
                        node_id=node_id,
                        error_type=type(e).__name__,
                        error_message=str(e),
                        retry_count=node_runtime.retry_count,
                    ),
                )
            
            # Phase B: 更新执行指针为失败
            await self._update_pointer_node_failed(instance_id, node_id)
    
    async def _execute_subgraph(
        self,
        parent_instance_id: str,
        parent_node_id: str,
        subgraph_def: "SubgraphDefinition",
        parent_graph_def: GraphDefinition,
    ) -> bool:
        """
        Phase A: 执行子图（Composite 步骤）
        
        1. 创建子图实例
        2. 执行子图所有节点
        3. 收集子图结果
        4. 回填到父节点
        """
        subgraph = subgraph_def.graph
        subgraph_instance_id = f"{parent_instance_id}_{parent_node_id}_sub"
        
        logger.info(f"Starting subgraph execution: {subgraph_instance_id}")
        
        try:
            # 启动子图实例
            await self.start_instance(subgraph, subgraph_instance_id, {})
            
            # 等待子图完成
            final_state = await self.wait_for_completion(subgraph_instance_id, timeout=600.0)
            
            # 检查子图执行结果
            if final_state == GraphInstanceState.COMPLETED:
                logger.info(f"Subgraph {subgraph_instance_id} completed successfully")
                
                # Phase A: 收集子图输出（显式 terminal 节点语义）
                # 策略：
                # 1. 优先查找标记为 terminal 的节点（node.config.is_terminal == True）
                # 2. 如果没有 terminal 节点，使用最后一个成功执行的节点（保持向后兼容）
                async with self.db.async_session() as session:
                    node_repo = NodeRuntimeRepository(session)
                    subgraph_nodes = await node_repo.get_all_by_instance(subgraph_instance_id)
                    
                    terminal_output = None
                    
                    # 1. 查找显式 terminal 节点
                    for node in subgraph_nodes:
                        if NodeState(node.state.value) == NodeState.SUCCESS and node.output_data:
                            # 检查节点是否标记为 terminal
                            node_def = subgraph.get_node(node.node_id)
                            if node_def and node_def.config.get("is_terminal"):
                                terminal_output = node.output_data
                                logger.info(f"Using terminal node {node.node_id} output for subgraph result")
                                break
                    
                    # 2. 如果没有 terminal 节点，使用最后一个成功执行的节点
                    if terminal_output is None:
                        for node in sorted(subgraph_nodes, key=lambda n: n.finished_at or datetime.min, reverse=True):
                            if NodeState(node.state.value) == NodeState.SUCCESS and node.output_data:
                                terminal_output = node.output_data
                                logger.info(f"Using last successful node {node.node_id} output for subgraph result (no terminal node found)")
                                break
                    
                    # 回填到父节点
                    parent_node = await node_repo.get_by_instance_and_node(parent_instance_id, parent_node_id)
                    if parent_node:
                        parent_node.output_data = terminal_output or {}
                        await session.commit()
                        logger.info(f"Subgraph output backfilled to parent node {parent_node_id}")
                
                return True
            else:
                logger.error(f"Subgraph {subgraph_instance_id} failed with state: {final_state}")
                
                # Phase A: 失败传播 - 将父节点标记为失败
                async with self.db.async_session() as session:
                    node_repo = NodeRuntimeRepository(session)
                    parent_node = await node_repo.get_by_instance_and_node(parent_instance_id, parent_node_id)
                    if parent_node:
                        from execution_kernel.models.graph_instance import NodeStateDB
                        parent_node.state = NodeStateDB.FAILED
                        parent_node.error_message = f"Subgraph failed: {final_state.value}"
                        await session.commit()
                
                return False
                
        except Exception as e:
            logger.error(f"Subgraph execution error: {e}")
            return False
    
    async def wait_for_completion(self, instance_id: str, timeout: float = None) -> GraphInstanceState:
        """等待图实例完成"""
        start_time = datetime.utcnow()
        
        while True:
            async with self.db.async_session() as session:
                instance_repo = GraphInstanceRepository(session)
                instance_db = await instance_repo.get(instance_id)
                
                if instance_db and instance_db.state not in {
                    GraphInstanceStateDB.RUNNING,
                    GraphInstanceStateDB.PENDING,
                }:
                    return GraphInstanceState(instance_db.state.value)
            
            # 超时检查
            if timeout:
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > timeout:
                    return GraphInstanceState.RUNNING
            
            await asyncio.sleep(0.1)
    
    async def apply_patch(
        self,
        instance_id: str,
        patch: GraphPatch,
    ) -> GraphPatchResult:
        """
        Phase B: 应用图补丁（RePlan 核心）
        
        流程：
        1. 获取当前图定义
        2. 应用补丁（CAS 版本检查）
        3. 迁移执行指针
        4. 保存新图定义
        5. 更新实例版本
        6. 重新调度就绪节点
        
        Args:
            instance_id: 图实例 ID
            patch: 图补丁
        
        Returns:
            Patch 应用结果
        """
        async with self.db.async_session() as session:
            patch_repo = GraphPatchRepository(session)
            pointer_repo = ExecutionPointerRepository(session)
            instance_repo = GraphInstanceRepository(session)
            node_repo = NodeRuntimeRepository(session)
            
            # 1. 创建补丁记录
            await patch_repo.create(
                patch_id=patch.patch_id,
                target_graph_id=patch.target_graph_id,
                base_version=patch.base_version,
                target_version=patch.target_version,
                operations=[op.model_dump() for op in patch.operations],
                created_by=patch.created_by,
                reason=patch.reason,
            )
            
            # 2. 获取当前图定义
            current_graph = self._instance_graphs.get(instance_id)
            if not current_graph:
                error = f"Instance {instance_id} graph not found in cache"
                await patch_repo.mark_failed(patch.patch_id, error)
                return GraphPatchResult(
                    success=False,
                    patch_id=patch.patch_id,
                    applied_version=patch.base_version,
                    previous_version=patch.base_version,
                    errors=[error],
                )
            
            # 3. 获取执行指针
            pointer_db = await pointer_repo.get(instance_id)
            pointer = None
            if pointer_db:
                pointer = ExecutionPointer(
                    instance_id=pointer_db.instance_id,
                    graph_version=pointer_db.graph_version,
                    completed_nodes=pointer_db.completed_nodes,
                    ready_nodes=pointer_db.ready_nodes,
                    running_nodes=pointer_db.running_nodes,
                    failed_nodes=pointer_db.failed_nodes,
                )
            
            # 4. 应用补丁
            new_graph, result, new_pointer = self.graph_patcher.apply_patch(
                current_graph, patch, pointer
            )
            
            if not result.success:
                await patch_repo.mark_failed(patch.patch_id, str(result.errors))
                
                # V2.6: 发射 PatchFailed 事件
                await self._emit_event(
                    session,
                    instance_id,
                    ExecutionEventType.PATCH_FAILED,
                    EventPayloadBuilder.patch_failed(
                        patch_id=patch.patch_id,
                        error_message=str(result.errors),
                    ),
                )
                
                return result
            
            # 5. 保存新图定义到数据库
            def_repo = GraphDefinitionRepository(session)
            await def_repo.save(new_graph)
            
            # 6. 更新实例版本
            instance_db = await instance_repo.get(instance_id)
            if instance_db:
                instance_db.graph_definition_version = result.applied_version
            
            # 7. 更新执行指针
            if new_pointer:
                await pointer_repo.update(new_pointer)
            
            # 8. 为新节点创建运行时
            existing_node_ids = {
                node.node_id for node in await node_repo.get_all_by_instance(instance_id)
            }
            for node_def in new_graph.get_enabled_nodes():
                if node_def.id not in existing_node_ids:
                    node_runtime = NodeRuntime(
                        graph_instance_id=instance_id,
                        node_id=node_def.id,
                        state=NodeState.PENDING,
                        input_data=node_def.config.get("default_input", {}),
                    )
                    await node_repo.create(node_runtime)
            
            # 9. 更新缓存
            self._instance_graphs[instance_id] = new_graph
            
            # 10. 标记补丁为已应用
            await patch_repo.mark_applied(patch.patch_id, result.model_dump())
            
            await session.commit()
            
            # V2.6: 发射 PatchApplied 事件
            await self._emit_event(
                session,
                instance_id,
                ExecutionEventType.PATCH_APPLIED,
                EventPayloadBuilder.patch_applied(
                    patch_id=patch.patch_id,
                    target_nodes=[n.id for n in new_graph.get_enabled_nodes()],
                    patch_type="graph_patch",
                ),
            )
            
            logger.info(
                f"Patch {patch.patch_id} applied to instance {instance_id}: "
                f"{result.applied_operations} operations, version {result.previous_version} -> {result.applied_version}"
            )
            
            # 11. 重新调度
            await self._schedule_next(instance_id)
            
            return result
    
    async def recover_from_crash(
        self,
        reschedule: bool = True,
        stale_only_seconds: Optional[int] = 120,
    ):
        """
        Phase B: 增强版 Crash 恢复
        
        支持：
        1. 基于 graph_version 恢复正确的图定义
        2. 从执行指针恢复执行状态
        3. 重置运行中的节点为 pending 并重新调度
        """
        async with self.db.async_session() as session:
            instance_repo = GraphInstanceRepository(session)
            node_repo = NodeRuntimeRepository(session)
            pointer_repo = ExecutionPointerRepository(session)
            def_repo = GraphDefinitionRepository(session)
            
            # 获取所有运行中的实例
            running_instances = await instance_repo.get_running_instances()
            if stale_only_seconds is not None and stale_only_seconds > 0:
                cutoff = datetime.utcnow() - timedelta(seconds=int(stale_only_seconds))
                filtered: List[Any] = []
                skipped_live = 0
                for inst in running_instances:
                    # updated_at 过新，视为活跃实例，跳过恢复，避免误伤正在执行的 run
                    if inst.updated_at and inst.updated_at > cutoff:
                        skipped_live += 1
                        continue
                    filtered.append(inst)
                if skipped_live > 0:
                    logger.info(
                        f"Crash recovery skipped {skipped_live} active instances "
                        f"(updated within {stale_only_seconds}s window)"
                    )
                running_instances = filtered
            
            for instance_db in running_instances:
                instance_id = instance_db.id
                graph_version = instance_db.graph_definition_version
                
                # V2.6: 发射 CrashRecoveryStarted 事件
                await self._emit_event(
                    session,
                    instance_id,
                    ExecutionEventType.CRASH_RECOVERY_STARTED,
                    EventPayloadBuilder.crash_recovery_started(
                        instance_id=instance_id,
                        recovery_strategy="version_aware_reset",
                    ),
                )
                
                recovered_nodes = 0
                failed_nodes = 0
                
                # Phase B: 恢复图定义（按版本）
                graph_def = await def_repo.get_definition(
                    instance_db.graph_definition_id,
                    version=graph_version,  # 指定版本恢复
                )
                if graph_def:
                    self._instance_graphs[instance_id] = graph_def
                    logger.info(
                        f"Crash recovery: restored graph {graph_def.id} v{graph_version} "
                        f"for instance {instance_id}"
                    )
                else:
                    logger.error(
                        f"Crash recovery: failed to restore graph "
                        f"{instance_db.graph_definition_id} v{graph_version}"
                    )
                
                # Phase B: 恢复执行指针
                pointer_db = await pointer_repo.get(instance_id)
                if pointer_db:
                    logger.info(
                        f"Crash recovery: restored pointer for instance {instance_id}: "
                        f"completed={len(pointer_db.completed_nodes)}, "
                        f"ready={len(pointer_db.ready_nodes)}, "
                        f"running={len(pointer_db.running_nodes)}"
                    )
                
                # 重置运行中的节点为 pending
                count = await node_repo.reset_running_to_pending(instance_id)
                
                recovered_nodes = count  # 重置的节点数即为恢复的节点数
                
                if count > 0:
                    logger.info(
                        f"Crash recovery: reset {count} running nodes "
                        f"in instance {instance_id} to pending"
                    )
                
                # V2.6: 发射 CrashRecoveryCompleted 事件
                await self._emit_event(
                    session,
                    instance_id,
                    ExecutionEventType.CRASH_RECOVERY_COMPLETED,
                    EventPayloadBuilder.crash_recovery_completed(
                        instance_id=instance_id,
                        recovered_nodes=recovered_nodes,
                        failed_nodes=failed_nodes,
                    ),
                )
                
                # 重新调度（可选）
                await session.commit()
                if reschedule:
                    await self._schedule_next(instance_id)

    async def cleanup_stale_running_instances(self, max_age_minutes: int = 30) -> int:
        """
        清理长期 RUNNING 的僵尸实例，避免持续占用恢复/调度路径。
        规则：
        - 实例状态 RUNNING
        - 且 updated_at 超过阈值
        - 且没有 RUNNING 节点
        -> 标记为 FAILED
        """
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        cleaned = 0
        async with self.db.async_session() as session:
            instance_repo = GraphInstanceRepository(session)
            node_repo = NodeRuntimeRepository(session)
            instances = await instance_repo.get_running_instances()
            for inst in instances:
                if inst.updated_at and inst.updated_at >= cutoff:
                    continue
                running_nodes = await node_repo.get_running_nodes(inst.id)
                if running_nodes:
                    continue
                await instance_repo.update_state(
                    inst.id,
                    GraphInstanceState.FAILED,
                    finished_at=datetime.utcnow(),
                )
                cleaned += 1
            await session.commit()
        if cleaned > 0:
            logger.info(f"ExecutionKernel cleaned stale RUNNING instances: {cleaned}")
        return cleaned
    
    # Phase B: 执行指针持续更新方法
    
    async def _update_pointer_node_started(self, instance_id: str, node_id: str) -> None:
        """更新执行指针：节点开始运行"""
        async def _mutate(pointer_db):
            if node_id in pointer_db.ready_nodes:
                pointer_db.ready_nodes.remove(node_id)
            if node_id not in pointer_db.running_nodes:
                pointer_db.running_nodes.append(node_id)
            pointer_db.updated_at = datetime.utcnow()
            flag_modified(pointer_db, "ready_nodes")
            flag_modified(pointer_db, "running_nodes")
        await self._update_pointer_with_retry(instance_id, _mutate)
    
    async def _update_pointer_node_completed(self, instance_id: str, node_id: str) -> None:
        """更新执行指针：节点完成"""
        async def _mutate(pointer_db):
            if node_id in pointer_db.running_nodes:
                pointer_db.running_nodes.remove(node_id)
            if node_id not in pointer_db.completed_nodes:
                pointer_db.completed_nodes.append(node_id)
            pointer_db.updated_at = datetime.utcnow()
            flag_modified(pointer_db, "running_nodes")
            flag_modified(pointer_db, "completed_nodes")
        await self._update_pointer_with_retry(instance_id, _mutate)
    
    async def _update_pointer_node_failed(self, instance_id: str, node_id: str) -> None:
        """更新执行指针：节点失败"""
        async def _mutate(pointer_db):
            if node_id in pointer_db.running_nodes:
                pointer_db.running_nodes.remove(node_id)
            if node_id not in pointer_db.failed_nodes:
                pointer_db.failed_nodes.append(node_id)
            pointer_db.updated_at = datetime.utcnow()
            flag_modified(pointer_db, "running_nodes")
            flag_modified(pointer_db, "failed_nodes")
        await self._update_pointer_with_retry(instance_id, _mutate)
    
    async def _update_pointer_on_completion(self, instance_id: str) -> None:
        """更新执行指针：图实例完成"""
        async def _mutate(pointer_db):
            pointer_db.running_nodes = []
            pointer_db.ready_nodes = []
            pointer_db.updated_at = datetime.utcnow()
            flag_modified(pointer_db, "running_nodes")
            flag_modified(pointer_db, "ready_nodes")
        await self._update_pointer_with_retry(instance_id, _mutate)
    
    async def _update_pointer_on_failure(self, instance_id: str, all_nodes: List) -> None:
        """更新执行指针：图实例失败"""
        async def _mutate(pointer_db):
            from execution_kernel.models.graph_instance import NodeStateDB
            for node in all_nodes:
                if node.state == NodeStateDB.FAILED and node.node_id not in pointer_db.failed_nodes:
                    pointer_db.failed_nodes.append(node.node_id)
            pointer_db.running_nodes = []
            pointer_db.ready_nodes = []
            flag_modified(pointer_db, "failed_nodes")
            flag_modified(pointer_db, "running_nodes")
            flag_modified(pointer_db, "ready_nodes")
            pointer_db.updated_at = datetime.utcnow()
        await self._update_pointer_with_retry(instance_id, _mutate)

    async def _update_pointer_with_retry(self, instance_id: str, mutator) -> None:
        """串行化并重试执行 execution_pointer 更新，降低 SQLite lock 冲突。"""
        lock = self._pointer_locks[instance_id]
        async with lock:
            last_error = None
            for attempt in range(5):
                try:
                    async with self.db.async_session() as session:
                        pointer_repo = ExecutionPointerRepository(session)
                        pointer_db = await pointer_repo.get(instance_id)
                        if not pointer_db:
                            return
                        await mutator(pointer_db)
                        await session.commit()
                        return
                except OperationalError as e:
                    last_error = e
                    if "database is locked" not in str(e).lower() or attempt == 4:
                        if "database is locked" not in str(e).lower():
                            raise
                        if POINTER_UPDATE_STRATEGY == "strict":
                            raise
                        logger.debug(
                            "Execution pointer update skipped after retries due to DB lock: instance_id=%s",
                            instance_id,
                        )
                        return
                    await asyncio.sleep(0.08 * (attempt + 1))
            if last_error:
                if POINTER_UPDATE_STRATEGY == "strict":
                    raise last_error
                logger.debug(
                    "Execution pointer update skipped due to DB lock: instance_id=%s",
                    instance_id,
                )
                return

    def _compose_node_input_from_upstreams(
        self,
        node_id: str,
        graph_def: GraphDefinition,
        all_nodes: List[NodeRuntimeDB],
        current_input: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        从满足触发条件的入边汇总上游输出，合并为当前节点输入。

        优先级：上游汇总 < 当前节点已有 input_data（后者优先覆盖）。
        """
        base_input = dict(current_input or {})
        incoming_edges = graph_def.get_incoming_edges(node_id)
        if not incoming_edges:
            return base_input

        node_map = {n.node_id: n for n in all_nodes}
        upstream_merged: Dict[str, Any] = {}

        for edge in incoming_edges:
            source = node_map.get(edge.from_node)
            if not source:
                continue
            source_state = NodeState(source.state.value)
            source_output = source.output_data if isinstance(source.output_data, dict) else source.output_data
            if not self._edge_trigger_satisfied(edge.on, source_state, source_output):
                continue
            if isinstance(source_output, dict):
                upstream_merged.update(self._sanitize_upstream_output(source_output))
            elif source_output is not None:
                upstream_merged[edge.from_node] = source_output

        if not upstream_merged:
            return base_input
        return {**upstream_merged, **base_input}

    def _sanitize_upstream_output(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        过滤上游输出中的内部控制字段，降低节点间隐式耦合。
        """
        if not isinstance(data, dict):
            return {}
        sanitized = {
            k: v
            for k, v in data.items()
            if not str(k).startswith("__workflow_")
        }
        # 条件/循环控制键仅用于边路由；有业务字段时不向下游透传这些控制键
        if len(sanitized) > 1:
            sanitized.pop("condition_result", None)
            sanitized.pop("loop_completed", None)
        return sanitized

    def _edge_trigger_satisfied(
        self,
        trigger: EdgeTrigger,
        from_node_state: Optional[NodeState],
        from_node_output: Any,
    ) -> bool:
        """判断一条边在当前源节点状态/输出下是否触发。"""
        output = from_node_output if isinstance(from_node_output, dict) else {}

        if trigger == EdgeTrigger.SUCCESS:
            return from_node_state == NodeState.SUCCESS
        if trigger == EdgeTrigger.FAILURE:
            return from_node_state == NodeState.FAILED
        if trigger == EdgeTrigger.ALWAYS:
            return from_node_state in {NodeState.SUCCESS, NodeState.FAILED}
        if trigger == EdgeTrigger.CONDITION_TRUE:
            return from_node_state == NodeState.SUCCESS and bool(output.get("condition_result", False))
        if trigger == EdgeTrigger.CONDITION_FALSE:
            return from_node_state == NodeState.SUCCESS and not bool(output.get("condition_result", True))
        if trigger == EdgeTrigger.LOOP_CONTINUE:
            return from_node_state == NodeState.SUCCESS and not bool(output.get("loop_completed", True))
        if trigger == EdgeTrigger.LOOP_EXIT:
            return from_node_state == NodeState.SUCCESS and bool(output.get("loop_completed", False))
        return False

    def _edge_can_still_satisfy(
        self,
        trigger: EdgeTrigger,
        from_node_state: Optional[NodeState],
        from_node_output: Any,
    ) -> bool:
        """
        判断边是否“未来仍可能”满足。
        - 源节点未终态（pending/running/retrying）时视为仍可能满足
        - 源节点终态时仅当当前已满足才为 True
        """
        if from_node_state in {NodeState.PENDING, NodeState.RUNNING, NodeState.RETRYING}:
            return True
        return self._edge_trigger_satisfied(trigger, from_node_state, from_node_output)

    def _is_node_unreachable(
        self,
        node_id: str,
        graph_def: GraphDefinition,
        node_states: Dict[str, NodeState],
        all_nodes: List[NodeRuntimeDB],
    ) -> bool:
        """
        判断 pending 节点是否已不可达（依赖未来不可能满足）。
        """
        incoming_edges = graph_def.get_incoming_edges(node_id)
        if not incoming_edges:
            return False

        node_def = graph_def.get_node(node_id)
        node_cfg = (node_def.config if node_def and isinstance(node_def.config, dict) else {}) or {}
        workflow_node_type = str(node_cfg.get("workflow_node_type") or "").strip().lower()
        dependency_mode = str(node_cfg.get("dependency_mode") or "").strip().lower()
        if not dependency_mode and workflow_node_type == "output":
            # Output 默认作为汇聚节点：多入边时默认 any，单入边保持 all 语义等价。
            # 如需严格等待所有上游，前端可显式配置 dependency_mode=all。
            dependency_mode = "any" if len(incoming_edges) > 1 else "all"
        if dependency_mode not in {"all", "any"}:
            dependency_mode = "all"

        node_map = {n.node_id: n for n in all_nodes}

        any_satisfied = False
        any_possible = False
        all_possible = True

        for edge in incoming_edges:
            source_state = node_states.get(edge.from_node)
            source_output = {}
            source_node = node_map.get(edge.from_node)
            if source_node and source_node.output_data:
                source_output = source_node.output_data

            satisfied = self._edge_trigger_satisfied(edge.on, source_state, source_output)
            possible = self._edge_can_still_satisfy(edge.on, source_state, source_output)

            any_satisfied = any_satisfied or satisfied
            any_possible = any_possible or possible
            all_possible = all_possible and possible

        if dependency_mode == "any":
            # any 模式下：只要未来有机会满足就不算不可达
            return (not any_satisfied) and (not any_possible)
        # all 模式下：任一依赖不可能满足即不可达
        return not all_possible
    
    async def _check_dependencies_with_edges(
        self,
        node_id: str,
        graph_def: GraphDefinition,
        node_states: Dict[str, "NodeState"],
        all_nodes: List,
    ) -> bool:
        """
        Phase C: 增强的依赖检查，支持条件边
        
        检查所有入边是否满足触发条件：
        - SUCCESS: 源节点成功
        - FAILURE: 源节点失败
        - ALWAYS: 始终触发
        - CONDITION_TRUE/FALSE: 条件节点输出匹配
        - LOOP_CONTINUE/EXIT: 循环节点状态匹配
        """
        incoming_edges = graph_def.get_incoming_edges(node_id)
        
        # 如果没有入边，是入口节点
        if not incoming_edges:
            return True

        node_def = graph_def.get_node(node_id)
        node_cfg = (node_def.config if node_def and isinstance(node_def.config, dict) else {}) or {}
        workflow_node_type = str(node_cfg.get("workflow_node_type") or "").strip().lower()
        dependency_mode = str(node_cfg.get("dependency_mode") or "").strip().lower()
        if not dependency_mode and workflow_node_type == "output":
            dependency_mode = "any" if len(incoming_edges) > 1 else "all"
        if dependency_mode not in {"all", "any"}:
            dependency_mode = "all"

        any_satisfied = False
        
        for edge in incoming_edges:
            from_node_id = edge.from_node
            from_node_state = node_states.get(from_node_id)
            
            # 获取源节点输出（用于条件评估）
            from_node_output = {}
            for n in all_nodes:
                if n.node_id == from_node_id and n.output_data:
                    from_node_output = n.output_data
                    break
            satisfied = self._edge_trigger_satisfied(edge.on, from_node_state, from_node_output)
            if dependency_mode == "any":
                any_satisfied = any_satisfied or satisfied
                continue
            if not satisfied:
                return False

        if dependency_mode == "any":
            return any_satisfied
        return True
    
    # V2.7: Optimization Layer - Policy-based node sorting
    
    async def _sort_nodes_with_policy(
        self,
        executable_nodes: list,
        graph_def: GraphDefinition,
        instance_id: str,
        all_nodes: list,
        node_states: Dict[str, NodeState],
    ) -> list:
        """
        使用调度策略对节点进行排序
        
        Args:
            executable_nodes: 可执行的节点运行时列表
            graph_def: 图定义
            instance_id: 实例 ID
            all_nodes: 所有节点运行时
            node_states: 节点状态字典
            
        Returns:
            排序后的节点运行时列表
        """
        # 构建策略上下文
        node_outputs = {}
        completed_nodes = []
        failed_nodes = []
        running_nodes = []
        ready_node_ids = [n.node_id for n in executable_nodes]
        
        for node_db in all_nodes:
            node_id = node_db.node_id
            state = node_states.get(node_id)
            
            if state == NodeState.SUCCESS and node_db.output_data:
                node_outputs[node_id] = node_db.output_data
                completed_nodes.append(node_id)
            elif state == NodeState.FAILED:
                failed_nodes.append(node_id)
            elif state == NodeState.RUNNING:
                running_nodes.append(node_id)
        
        # 获取全局上下文
        global_context = {}
        async with self.db.async_session() as session:
            instance_repo = GraphInstanceRepository(session)
            instance_db = await instance_repo.get(instance_id)
            if instance_db:
                global_context = instance_db.global_context or {}
        
        context = PolicyContext(
            instance_id=instance_id,
            graph_def=graph_def,
            node_outputs=node_outputs,
            global_context=global_context,
            ready_nodes=ready_node_ids,
            running_nodes=running_nodes,
            completed_nodes=completed_nodes,
            failed_nodes=failed_nodes,
        )
        
        # 获取节点定义列表
        node_defs = []
        for node_db in executable_nodes:
            node_def = graph_def.get_node(node_db.node_id)
            if node_def:
                node_defs.append(node_def)
        
        # 使用策略排序
        sorted_node_defs = self._scheduler_policy.sort_nodes(
            node_defs, context, self._optimization_snapshot
        )
        
        # 将排序后的 node_def 映射回 node_runtime
        node_def_order = {node_def.id: idx for idx, node_def in enumerate(sorted_node_defs)}
        
        # 按策略排序，同时保持确定性（相同优先级按 node_id 排序）
        sorted_executable_nodes = sorted(
            executable_nodes,
            key=lambda n: (node_def_order.get(n.node_id, float('inf')), n.node_id)
        )
        
        return sorted_executable_nodes
    
    def set_scheduler_policy(
        self,
        policy: SchedulerPolicy,
        snapshot: Optional[OptimizationSnapshot] = None,
    ) -> None:
        """
        设置调度策略和优化快照
        
        V2.7: 允许运行时切换策略
        
        Args:
            policy: 调度策略
            snapshot: 优化快照（可选）
        """
        self._scheduler_policy = policy
        self._optimization_snapshot = snapshot
        logger.info(
            f"Scheduler policy updated: {policy.get_name()} v{policy.get_version()}, "
            f"snapshot={snapshot.version if snapshot else None}"
        )
    
    def get_scheduler_policy_info(self) -> Dict[str, Any]:
        """
        获取当前调度策略信息
        
        Returns:
            策略信息字典
        """
        return {
            "policy_name": self._scheduler_policy.get_name(),
            "policy_version": self._scheduler_policy.get_version(),
            "snapshot_version": self._optimization_snapshot.version if self._optimization_snapshot else None,
        }
