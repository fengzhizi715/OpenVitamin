"""
Executor
节点执行器，实现幂等执行、超时处理、重试逻辑
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Awaitable, Union
import logging
import traceback

from execution_kernel.models.graph_definition import GraphDefinition, NodeDefinition, NodeType
from execution_kernel.models.node_models import NodeRuntime, NodeState
from execution_kernel.engine.state_machine import StateMachine, InvalidStateTransitionError
from execution_kernel.engine.context import GraphContext
from execution_kernel.cache.node_cache import NodeCache
from execution_kernel.persistence.repositories import NodeRuntimeRepository


logger = logging.getLogger(__name__)


class NodeExecutionError(Exception):
    """节点执行异常"""
    def __init__(self, message: str, error_type: str = "ExecutionError"):
        super().__init__(message)
        self.error_type = error_type


def _is_non_retryable_error(exc: Exception) -> bool:
    msg = str(exc or "")
    markers = (
        "AGENT_NODE_INPUT_EMPTY",
        "AGENT_NODE_CONFIG_ERROR",
        "AGENT_NODE_NOT_FOUND",
        "SCHEMA_VALIDATION_ERROR",
    )
    return any(m in msg for m in markers)


class NodeTimeoutError(NodeExecutionError):
    """节点超时异常"""
    def __init__(self, timeout_seconds: float):
        super().__init__(
            f"Node execution timeout after {timeout_seconds}s",
            "TimeoutError"
        )


class Executor:
    """
    节点执行器
    
    职责：
    - execute_node(node_runtime)
    - 幂等检查（非 pending 不执行）
    - timeout 处理
    - retry 逻辑
    - 错误捕获
    - 状态更新
    - 触发调度
    
    不得实现：
    - 动态重排序
    - 智能决策
    - 自动替换节点
    """
    
    def __init__(
        self,
        state_machine: StateMachine,
        cache: NodeCache,
        node_handlers: Dict[str, Callable] = None,
    ):
        self.state_machine = state_machine
        self.cache = cache
        self.node_handlers = node_handlers or {}

    def register_handler(self, node_type: str, handler: Callable):
        """
        注册节点类型处理器。
        handler 签名为 (node_def: NodeDefinition, input_data: Dict) -> Awaitable[Dict]，
        以便根据 node_def.config 分发到不同执行逻辑（如 skill / internal）。
        """
        self.node_handlers[node_type] = handler
    
    async def execute_node(
        self,
        node_runtime: NodeRuntime,
        node_def: NodeDefinition,
        context: GraphContext,
    ) -> Dict[str, Any]:
        """
        执行节点
        
        流程：
        1. 幂等检查
        2. 缓存检查
        3. 状态转换 -> RUNNING
        4. 执行节点逻辑
        5. 状态转换 -> SUCCESS/FAILED/TIMEOUT
        6. 更新上下文
        
        Returns:
            节点输出数据
        """
        # 1. 幂等检查：非 pending 不执行
        if node_runtime.state != NodeState.PENDING:
            logger.warning(
                f"Node {node_runtime.id} is not pending (state={node_runtime.state.value}), "
                f"skipping execution"
            )
            return node_runtime.output_data

        # 2. 状态转换 -> RUNNING（尽早进入可失败状态，避免前置异常导致节点长期停留 pending）
        try:
            await self.state_machine.start(node_runtime.id)
        except InvalidStateTransitionError as e:
            logger.error(f"Failed to start node {node_runtime.id}: {e}")
            return {}

        # 3. 前置处理（输入解析 + 缓存检查）
        try:
            input_data = context.resolve_dict(node_runtime.input_data)
            cached_output = await self.cache.get(node_def, input_data)
            if cached_output is not None:
                logger.info(f"Node {node_runtime.id} cache hit, skipping execution")
                await self.state_machine.succeed(node_runtime.id, cached_output)
                return cached_output
        except Exception as e:
            error_type = type(e).__name__
            error_message = str(e)
            await self.state_machine.fail(
                node_runtime.id,
                error_message=error_message,
                error_type=error_type,
            )
            logger.error(f"Node {node_runtime.id} pre-execution failed: {error_message}")
            raise NodeExecutionError(error_message, error_type)

        # 4. 执行节点逻辑（带超时）
        try:
            output_data = await self._execute_with_timeout(
                node_def=node_def,
                input_data=input_data,
                context=context,
            )
            
            # 执行成功
            await self.state_machine.succeed(node_runtime.id, output_data)
            
            # 设置缓存
            await self.cache.set(node_def, input_data, output_data)
            
            logger.info(f"Node {node_runtime.id} executed successfully")
            return output_data
            
        except asyncio.TimeoutError:
            await self.state_machine.timeout(node_runtime.id)
            logger.error(f"Node {node_runtime.id} timeout after {node_def.timeout_seconds}s")
            raise NodeTimeoutError(node_def.timeout_seconds)
            
        except Exception as e:
            error_type = type(e).__name__
            error_message = str(e)
            await self.state_machine.fail(
                node_runtime.id, 
                error_message=error_message,
                error_type=error_type,
            )
            logger.error(f"Node {node_runtime.id} failed: {error_message}")
            raise NodeExecutionError(error_message, error_type)
    
    async def _execute_with_timeout(
        self,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: GraphContext,
    ) -> Dict[str, Any]:
        """带超时控制的执行"""
        handler = self.node_handlers.get(node_def.type.value)

        if handler is None:
            # 默认处理器：直接返回输入（用于测试）
            logger.warning(f"No handler for node type {node_def.type.value}, returning input")
            return input_data

        try:
            # Phase C: 传入 node_def, input_data 和 GraphContext
            # handler 签名: handler(node_def, input_data, graph_context) -> Dict
            result = await asyncio.wait_for(
                handler(node_def, input_data, context),
                timeout=node_def.timeout_seconds,
            )
            # 统一失败语义：handler 返回 {"error": "..."} 视为执行失败，交由状态机标记 FAILED/RETRY
            if isinstance(result, dict) and result.get("error"):
                raise NodeExecutionError(str(result.get("error")), "HandlerError")
            return result
        except asyncio.TimeoutError:
            raise
        except Exception as e:
            raise NodeExecutionError(str(e), type(e).__name__)
    
    async def execute_with_retry(
        self,
        node_runtime: NodeRuntime,
        node_def: NodeDefinition,
        context: GraphContext,
    ) -> Dict[str, Any]:
        """
        带重试的执行
        
        流程：
        1. 执行节点
        2. 失败时检查是否可重试
        3. 计算 backoff 时间
        4. 等待后重试
        """
        max_retries = node_def.retry_policy.max_retries
        
        while True:
            try:
                return await self.execute_node(node_runtime, node_def, context)
                
            except (NodeExecutionError, NodeTimeoutError) as e:
                if _is_non_retryable_error(e):
                    logger.error(
                        f"Node {node_runtime.id} non-retryable error, skip retries: {e}"
                    )
                    raise
                # 检查是否可以重试
                current_node = await self.state_machine.get_node(node_runtime.id)
                if current_node is None:
                    raise
                
                retry_count = current_node.retry_count
                
                if retry_count >= max_retries:
                    logger.error(
                        f"Node {node_runtime.id} exceeded max retries ({max_retries})"
                    )
                    raise
                
                # 计算退避时间
                backoff = node_def.retry_policy.calculate_backoff(retry_count)
                
                # 进入重试状态
                await self.state_machine.retry(node_runtime.id, retry_count + 1)
                
                logger.info(
                    f"Node {node_runtime.id} retry {retry_count + 1}/{max_retries}, "
                    f"backoff {backoff}s"
                )
                
                # 等待退避时间
                await asyncio.sleep(backoff)
                
                # 重置为 pending 状态以便重新执行
                await self.state_machine.set_pending(node_runtime.id)
                
                # 更新 node_runtime 状态
                node_runtime = NodeRuntime(
                    id=current_node.id,
                    graph_instance_id=current_node.graph_instance_id,
                    node_id=current_node.node_id,
                    state=NodeState.PENDING,
                    input_data=current_node.input_data,
                    output_data=current_node.output_data,
                    retry_count=current_node.retry_count,
                    error_message=current_node.error_message,
                    error_type=current_node.error_type,
                    started_at=current_node.started_at,
                    finished_at=current_node.finished_at,
                    created_at=current_node.created_at,
                    updated_at=current_node.updated_at,
                )
