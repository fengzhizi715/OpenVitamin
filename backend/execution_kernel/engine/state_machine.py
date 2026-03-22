"""
State Machine
节点状态机，实现完整状态流转逻辑
"""

from datetime import datetime
from typing import Optional
import logging

from execution_kernel.models.node_models import (
    NodeState,
    NodeRuntime,
    VALID_TRANSITIONS,
)
from execution_kernel.persistence.repositories import NodeRuntimeRepository
from execution_kernel.persistence.db import Database


logger = logging.getLogger(__name__)


class InvalidStateTransitionError(Exception):
    """非法状态转换异常"""
    def __init__(self, current_state: NodeState, target_state: NodeState):
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(
            f"Invalid state transition: {current_state.value} -> {target_state.value}"
        )


class StateMachine:
    """
    节点状态机
    
    允许状态：
    - PENDING: 待执行
    - RUNNING: 执行中
    - SUCCESS: 执行成功（终态）
    - FAILED: 执行失败
    - RETRYING: 重试中
    - SKIPPED: 跳过（终态）
    - CANCELLED: 取消（终态）
    - TIMEOUT: 超时
    
    状态转换规则：
    PENDING -> RUNNING, SKIPPED, CANCELLED
    RUNNING -> SUCCESS, FAILED, TIMEOUT, CANCELLED
    FAILED -> RETRYING, CANCELLED
    RETRYING -> RUNNING, CANCELLED
    TIMEOUT -> RETRYING, CANCELLED
    """
    
    def __init__(self, repository: Optional[NodeRuntimeRepository] = None, db: Optional[Database] = None):
        # 兼容旧调用：可直接传 repository；推荐传 db 以实现短事务 session
        self.repository = repository
        self.db = db

    async def _get_node(self, node_id: str, for_update: bool = False):
        if self.db is not None:
            async with self.db.async_session() as session:
                repo = NodeRuntimeRepository(session)
                node = await repo.get(node_id, for_update=for_update)
                return node
        if self.repository is None:
            raise ValueError("StateMachine repository is not initialized")
        return await self.repository.get(node_id, for_update=for_update)

    async def _update_node_state(
        self,
        *,
        node_id: str,
        new_state: NodeState,
        output_data: dict = None,
        error_message: str = None,
        error_type: str = None,
        started_at: datetime = None,
        finished_at: datetime = None,
        retry_count: int = None,
    ) -> None:
        if self.db is not None:
            async with self.db.async_session() as session:
                repo = NodeRuntimeRepository(session)
                await repo.update_state(
                    node_id=node_id,
                    new_state=new_state,
                    output_data=output_data,
                    error_message=error_message,
                    error_type=error_type,
                    started_at=started_at,
                    finished_at=finished_at,
                    retry_count=retry_count,
                )
                await session.commit()
            return
        if self.repository is None:
            raise ValueError("StateMachine repository is not initialized")
        await self.repository.update_state(
            node_id=node_id,
            new_state=new_state,
            output_data=output_data,
            error_message=error_message,
            error_type=error_type,
            started_at=started_at,
            finished_at=finished_at,
            retry_count=retry_count,
        )
        try:
            await self.repository.session.commit()
        except Exception:
            await self.repository.session.rollback()
            raise
    
    def validate_transition(self, current: NodeState, target: NodeState) -> bool:
        """验证状态转换是否合法"""
        allowed = VALID_TRANSITIONS.get(current, set())
        return target in allowed
    
    async def transition(
        self,
        node_id: str,
        target_state: NodeState,
        output_data: dict = None,
        error_message: str = None,
        error_type: str = None,
        started_at: datetime = None,
        finished_at: datetime = None,
        retry_count: int = None,
    ) -> NodeRuntime:
        """
        执行状态转换（幂等）
        
        Args:
            node_id: 节点运行时 ID
            target_state: 目标状态
            output_data: 输出数据
            error_message: 错误信息
            error_type: 错误类型
            started_at: 开始时间
            finished_at: 结束时间
            retry_count: 重试次数
            
        Returns:
            更新后的节点运行时
            
        Raises:
            InvalidStateTransitionError: 非法状态转换
        """
        # 获取当前节点（加锁）
        node_db = await self._get_node(node_id, for_update=True)
        if not node_db:
            raise ValueError(f"Node runtime not found: {node_id}")
        
        current_state = NodeState(node_db.state.value)
        
        # 幂等检查：如果已经是目标状态，直接返回
        if current_state == target_state:
            logger.debug(f"Node {node_id} already in state {target_state.value}")
            return NodeRuntime(
                id=node_db.id,
                graph_instance_id=node_db.graph_instance_id,
                node_id=node_db.node_id,
                state=current_state,
                input_data=node_db.input_data,
                output_data=node_db.output_data or output_data or {},
                retry_count=node_db.retry_count,
                error_message=node_db.error_message,
                error_type=node_db.error_type,
                started_at=node_db.started_at,
                finished_at=node_db.finished_at,
                created_at=node_db.created_at,
                updated_at=node_db.updated_at,
            )
        
        # 验证状态转换
        if not self.validate_transition(current_state, target_state):
            raise InvalidStateTransitionError(current_state, target_state)
        
        # 执行状态更新
        await self._update_node_state(
            node_id=node_id,
            new_state=target_state,
            output_data=output_data,
            error_message=error_message,
            error_type=error_type,
            started_at=started_at,
            finished_at=finished_at,
            retry_count=retry_count,
        )
        
        logger.info(f"Node {node_id} state transition: {current_state.value} -> {target_state.value}")
        
        # 返回更新后的节点
        node_db = await self._get_node(node_id)
        return NodeRuntime(
            id=node_db.id,
            graph_instance_id=node_db.graph_instance_id,
            node_id=node_db.node_id,
            state=NodeState(node_db.state.value),
            input_data=node_db.input_data,
            output_data=node_db.output_data,
            retry_count=node_db.retry_count,
            error_message=node_db.error_message,
            error_type=node_db.error_type,
            started_at=node_db.started_at,
            finished_at=node_db.finished_at,
            created_at=node_db.created_at,
            updated_at=node_db.updated_at,
        )

    async def get_node(self, node_id: str):
        """获取节点运行时（供重试逻辑读取 retry_count 等字段）"""
        return await self._get_node(node_id)

    async def set_pending(self, node_id: str) -> None:
        """将节点重置为 pending（用于重试回退）。"""
        await self._update_node_state(node_id=node_id, new_state=NodeState.PENDING)
    
    async def start(self, node_id: str) -> NodeRuntime:
        """开始执行节点"""
        return await self.transition(
            node_id=node_id,
            target_state=NodeState.RUNNING,
            started_at=datetime.utcnow(),
        )
    
    async def succeed(self, node_id: str, output_data: dict) -> NodeRuntime:
        """节点执行成功"""
        return await self.transition(
            node_id=node_id,
            target_state=NodeState.SUCCESS,
            output_data=output_data,
            finished_at=datetime.utcnow(),
        )
    
    async def fail(
        self, 
        node_id: str, 
        error_message: str, 
        error_type: str = None
    ) -> NodeRuntime:
        """节点执行失败"""
        return await self.transition(
            node_id=node_id,
            target_state=NodeState.FAILED,
            error_message=error_message,
            error_type=error_type,
            finished_at=datetime.utcnow(),
        )
    
    async def timeout(self, node_id: str) -> NodeRuntime:
        """节点执行超时"""
        return await self.transition(
            node_id=node_id,
            target_state=NodeState.TIMEOUT,
            error_message="Execution timeout",
            error_type="TimeoutError",
            finished_at=datetime.utcnow(),
        )
    
    async def retry(self, node_id: str, retry_count: int) -> NodeRuntime:
        """进入重试状态"""
        return await self.transition(
            node_id=node_id,
            target_state=NodeState.RETRYING,
            retry_count=retry_count,
        )
    
    async def cancel(self, node_id: str, reason: str = None) -> NodeRuntime:
        """取消节点执行"""
        return await self.transition(
            node_id=node_id,
            target_state=NodeState.CANCELLED,
            error_message=reason,
            finished_at=datetime.utcnow(),
        )
    
    async def skip(self, node_id: str, reason: str = None) -> NodeRuntime:
        """跳过节点执行"""
        return await self.transition(
            node_id=node_id,
            target_state=NodeState.SKIPPED,
            error_message=reason,
        )
