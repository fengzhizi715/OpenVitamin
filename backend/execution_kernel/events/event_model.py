"""
V2.6: Observability & Replay Layer - Event Model
定义 ExecutionEvent 数据模型
"""

from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
import uuid

from execution_kernel.events.event_types import ExecutionEventType


class ExecutionEvent(BaseModel):
    """
    执行事件模型
    
    核心设计：
    - event_id: 全局唯一标识
    - instance_id: 所属 GraphInstance
    - sequence: 实例内严格递增序列号（用于确定性 replay）
    - event_type: 事件类型
    - timestamp: 观察时间戳（不参与 replay 决策）
    - payload: 事件负载数据
    - schema_version: 事件模式版本（支持升级）
    """
    
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    instance_id: str
    sequence: int  # 单实例内严格递增，用于确定性 replay
    event_type: ExecutionEventType
    timestamp: int = Field(default_factory=lambda: int(datetime.utcnow().timestamp() * 1000))
    payload: Dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 1
    
    class Config:
        frozen = True  # 不可变，保证事件不可篡改
    
    @classmethod
    def create(
        cls,
        instance_id: str,
        sequence: int,
        event_type: ExecutionEventType,
        payload: Dict[str, Any],
    ) -> "ExecutionEvent":
        """
        创建事件（工厂方法）
        
        Args:
            instance_id: 图实例 ID
            sequence: 序列号（由 EventStore 分配）
            event_type: 事件类型
            payload: 事件负载
        """
        return cls(
            instance_id=instance_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
        )
    
    def is_terminal(self) -> bool:
        """是否为终止事件"""
        from execution_kernel.events.event_types import TERMINAL_EVENTS
        return self.event_type in TERMINAL_EVENTS
    
    def is_graph_lifecycle(self) -> bool:
        """是否为 Graph 生命周期事件"""
        from execution_kernel.events.event_types import GRAPH_LIFECYCLE_EVENTS
        return self.event_type in GRAPH_LIFECYCLE_EVENTS
    
    def is_node_lifecycle(self) -> bool:
        """是否为 Node 生命周期事件"""
        from execution_kernel.events.event_types import NODE_LIFECYCLE_EVENTS
        return self.event_type in NODE_LIFECYCLE_EVENTS
    
    def is_optimization_event(self) -> bool:
        """V2.7: 是否为 Optimization Layer 事件"""
        from execution_kernel.events.event_types import OPTIMIZATION_EVENTS
        return self.event_type in OPTIMIZATION_EVENTS


class EventPayloadBuilder:
    """
    事件负载构建器
    
    提供类型安全的事件负载构建方法
    """
    
    @staticmethod
    def graph_started(
        graph_id: str,
        graph_version: str,
        initial_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "graph_id": graph_id,
            "graph_version": graph_version,
            "initial_context": initial_context,
        }
    
    @staticmethod
    def graph_completed(
        final_state: str,
        completed_nodes: int,
        failed_nodes: int,
    ) -> Dict[str, Any]:
        return {
            "final_state": final_state,
            "completed_nodes": completed_nodes,
            "failed_nodes": failed_nodes,
        }
    
    @staticmethod
    def node_scheduled(
        node_id: str,
        node_type: str,
        dependencies: list,
    ) -> Dict[str, Any]:
        return {
            "node_id": node_id,
            "node_type": node_type,
            "dependencies": dependencies,
        }
    
    @staticmethod
    def node_started(
        node_id: str,
        node_type: str,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "node_id": node_id,
            "node_type": node_type,
            "input_data": input_data,
        }
    
    @staticmethod
    def node_succeeded(
        node_id: str,
        output_data: Dict[str, Any],
        duration_ms: int,
    ) -> Dict[str, Any]:
        return {
            "node_id": node_id,
            "output_data": output_data,
            "duration_ms": duration_ms,
        }
    
    @staticmethod
    def node_failed(
        node_id: str,
        error_type: str,
        error_message: str,
        retry_count: int,
    ) -> Dict[str, Any]:
        return {
            "node_id": node_id,
            "error_type": error_type,
            "error_message": error_message,
            "retry_count": retry_count,
        }
    
    @staticmethod
    def node_retry_scheduled(
        node_id: str,
        retry_count: int,
        backoff_ms: int,
    ) -> Dict[str, Any]:
        return {
            "node_id": node_id,
            "retry_count": retry_count,
            "backoff_ms": backoff_ms,
        }
    
    @staticmethod
    def scheduler_decision(
        ready_nodes: list,
        selected_node: str,
        strategy: str,
        decision_reason: str = "",
        policy_version: Optional[str] = None,
        snapshot_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        V2.7: 调度决策事件
        
        Args:
            ready_nodes: 就绪节点列表
            selected_node: 选中的节点
            strategy: 策略名称
            decision_reason: 决策原因
            policy_version: 策略版本（V2.7，用于 Replay determinism）
            snapshot_version: 快照版本（V2.7，用于 Replay determinism）
        """
        payload = {
            "ready_nodes": ready_nodes,
            "selected_node": selected_node,
            "strategy": strategy,
            "decision_reason": decision_reason,
        }
        # V2.7: 添加策略和快照版本，用于 Replay 确定性验证
        if policy_version is not None:
            payload["policy_version"] = policy_version
        if snapshot_version is not None:
            payload["snapshot_version"] = snapshot_version
        return payload
    
    @staticmethod
    def state_transition(
        node_id: str,
        from_state: str,
        to_state: str,
    ) -> Dict[str, Any]:
        return {
            "node_id": node_id,
            "from_state": from_state,
            "to_state": to_state,
        }
    
    @staticmethod
    def context_updated(
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "updates": updates,
        }
    
    # ========== Patch Events ==========
    
    @staticmethod
    def patch_applied(
        patch_id: str,
        target_nodes: list,
        patch_type: str,
    ) -> Dict[str, Any]:
        return {
            "patch_id": patch_id,
            "target_nodes": target_nodes,
            "patch_type": patch_type,
        }
    
    @staticmethod
    def patch_failed(
        patch_id: str,
        error_message: str,
    ) -> Dict[str, Any]:
        return {
            "patch_id": patch_id,
            "error_message": error_message,
        }
    
    # ========== Crash Recovery Events ==========
    
    @staticmethod
    def crash_recovery_started(
        instance_id: str,
        recovery_strategy: str,
    ) -> Dict[str, Any]:
        return {
            "instance_id": instance_id,
            "recovery_strategy": recovery_strategy,
        }
    
    @staticmethod
    def crash_recovery_completed(
        instance_id: str,
        recovered_nodes: int,
        failed_nodes: int,
    ) -> Dict[str, Any]:
        return {
            "instance_id": instance_id,
            "recovered_nodes": recovered_nodes,
            "failed_nodes": failed_nodes,
        }
    
    # ========== V2.7: Optimization Layer Events ==========
    
    @staticmethod
    def snapshot_built(
        snapshot_version: str,
        node_count: int,
        skill_count: int,
        event_count: int,
        source: str = "global",
    ) -> Dict[str, Any]:
        """
        V2.7: OptimizationSnapshot 构建事件
        
        Args:
            snapshot_version: 快照版本（内容哈希）
            node_count: 节点统计数量
            skill_count: Skill 统计数量
            event_count: 基于的事件数量
            source: 数据来源（global / instance_ids）
        """
        return {
            "snapshot_version": snapshot_version,
            "node_count": node_count,
            "skill_count": skill_count,
            "event_count": event_count,
            "source": source,
        }
    
    @staticmethod
    def policy_changed(
        policy_name: str,
        policy_version: str,
        previous_policy: Optional[str] = None,
        previous_version: Optional[str] = None,
        snapshot_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        V2.7: SchedulerPolicy 变更事件
        
        Args:
            policy_name: 新策略名称
            policy_version: 新策略版本
            previous_policy: 之前策略名称
            previous_version: 之前策略版本
            snapshot_version: 关联的快照版本
        """
        return {
            "policy_name": policy_name,
            "policy_version": policy_version,
            "previous_policy": previous_policy,
            "previous_version": previous_version,
            "snapshot_version": snapshot_version,
        }
    
    @staticmethod
    def statistics_collected(
        instance_ids: list,
        total_events: int,
        node_types: int,
        skill_ids: int,
    ) -> Dict[str, Any]:
        """
        V2.7: 统计收集事件
        
        Args:
            instance_ids: 收集的实例 ID 列表
            total_events: 总事件数
            node_types: 节点类型数
            skill_ids: Skill ID 数
        """
        return {
            "instance_ids": instance_ids,
            "total_events": total_events,
            "node_types": node_types,
            "skill_ids": skill_ids,
        }
