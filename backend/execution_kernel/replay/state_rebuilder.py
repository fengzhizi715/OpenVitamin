"""
V2.6: Observability & Replay Layer - State Rebuilder
基于事件流重建执行状态
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.models.node_models import NodeState


logger = logging.getLogger(__name__)


class RebuiltNodeState:
    """重建的节点状态"""
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.state = NodeState.PENDING
        self.input_data: Dict[str, Any] = {}
        self.output_data: Dict[str, Any] = {}
        self.retry_count = 0
        self.error_message: Optional[str] = None
        self.error_type: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "state": self.state.value,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class RebuiltGraphState:
    """重建的图状态"""
    
    def __init__(self, instance_id: str, graph_id: str):
        self.instance_id = instance_id
        self.graph_id = graph_id
        self.graph_version: str = "1.0.0"
        self.state = "running"  # running, completed, failed, cancelled
        self.nodes: Dict[str, RebuiltNodeState] = {}
        self.context: Dict[str, Any] = {}
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.event_count = 0
        self.last_sequence = 0
    
    def get_node(self, node_id: str) -> RebuiltNodeState:
        """获取或创建节点状态"""
        if node_id not in self.nodes:
            self.nodes[node_id] = RebuiltNodeState(node_id)
        return self.nodes[node_id]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "state": self.state,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "context": self.context,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "event_count": self.event_count,
            "last_sequence": self.last_sequence,
        }


class StateRebuilder:
    """
    状态重建器
    
    基于事件流重建执行状态，用于：
    - Debug Replay（不重新执行节点）
    - 状态审计
    - 崩溃恢复验证
    
    注意：此类是无状态的，每次 rebuild 调用创建新的状态对象。
    """
    
    def rebuild(self, events: List[ExecutionEvent]) -> RebuiltGraphState:
        """
        从事件流重建状态
        
        Args:
            events: 按 sequence 排序的事件列表
            
        Returns:
            重建的图状态
        """
        if not events:
            raise ValueError("No events to rebuild")
        
        # 初始化状态（局部变量，非实例变量）
        first_event = events[0]
        state = RebuiltGraphState(
            instance_id=first_event.instance_id,
            graph_id="",  # 将从 GraphStarted 事件填充
        )
        
        # 按顺序应用事件
        for event in events:
            self._apply_event(state, event)
        
        return state
    
    def _apply_event(self, state: RebuiltGraphState, event: ExecutionEvent):
        """应用单个事件"""
        state.event_count += 1
        state.last_sequence = event.sequence
        
        handlers = {
            ExecutionEventType.GRAPH_STARTED: lambda p: self._on_graph_started(state, p),
            ExecutionEventType.GRAPH_COMPLETED: lambda p: self._on_graph_completed(state, p),
            ExecutionEventType.GRAPH_FAILED: lambda p: self._on_graph_failed(state, p),
            ExecutionEventType.GRAPH_CANCELLED: lambda p: self._on_graph_cancelled(state, p),
            ExecutionEventType.NODE_SCHEDULED: lambda p: self._on_node_scheduled(state, p),
            ExecutionEventType.NODE_STARTED: lambda p: self._on_node_started(state, p),
            ExecutionEventType.NODE_SUCCEEDED: lambda p: self._on_node_succeeded(state, p),
            ExecutionEventType.NODE_FAILED: lambda p: self._on_node_failed(state, p),
            ExecutionEventType.NODE_RETRY_SCHEDULED: lambda p: self._on_node_retry(state, p),
            ExecutionEventType.NODE_SKIPPED: lambda p: self._on_node_skipped(state, p),
            ExecutionEventType.NODE_TIMEOUT: lambda p: self._on_node_timeout(state, p),
            ExecutionEventType.CONTEXT_UPDATED: lambda p: self._on_context_updated(state, p),
            # V2.6: Patch & Recovery events
            ExecutionEventType.PATCH_APPLIED: lambda p: self._on_patch_applied(state, p),
            ExecutionEventType.PATCH_FAILED: lambda p: self._on_patch_failed(state, p),
            ExecutionEventType.CRASH_RECOVERY_STARTED: lambda p: self._on_crash_recovery_started(state, p),
            ExecutionEventType.CRASH_RECOVERY_COMPLETED: lambda p: self._on_crash_recovery_completed(state, p),
        }
        
        handler = handlers.get(event.event_type)
        if handler:
            try:
                handler(event.payload)
            except Exception as e:
                logger.warning(f"Failed to apply event {event.event_type}: {e}")
        else:
            logger.debug(f"No handler for event type: {event.event_type}")
    
    def _on_graph_started(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Graph 开始"""
        state.graph_id = payload.get("graph_id", "")
        state.graph_version = payload.get("graph_version", "1.0.0")
        state.context = payload.get("initial_context", {})
        state.started_at = datetime.utcnow()
    
    def _on_graph_completed(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Graph 完成"""
        state.state = "completed"
        state.finished_at = datetime.utcnow()
    
    def _on_graph_failed(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Graph 失败"""
        state.state = "failed"
        state.finished_at = datetime.utcnow()
    
    def _on_graph_cancelled(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Graph 取消"""
        state.state = "cancelled"
        state.finished_at = datetime.utcnow()
    
    def _on_node_scheduled(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Node 被调度"""
        node_id = payload.get("node_id")
        if node_id:
            node = state.get_node(node_id)
            node.state = NodeState.PENDING
    
    def _on_node_started(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Node 开始执行"""
        node_id = payload.get("node_id")
        if node_id:
            node = state.get_node(node_id)
            node.state = NodeState.RUNNING
            node.input_data = payload.get("input_data", {})
            node.started_at = datetime.utcnow()
    
    def _on_node_succeeded(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Node 成功"""
        node_id = payload.get("node_id")
        if node_id:
            node = state.get_node(node_id)
            node.state = NodeState.SUCCESS
            node.output_data = payload.get("output_data", {})
            node.finished_at = datetime.utcnow()
    
    def _on_node_failed(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Node 失败"""
        node_id = payload.get("node_id")
        if node_id:
            node = state.get_node(node_id)
            node.state = NodeState.FAILED
            node.error_type = payload.get("error_type")
            node.error_message = payload.get("error_message")
            node.finished_at = datetime.utcnow()
    
    def _on_node_retry(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Node 重试"""
        node_id = payload.get("node_id")
        if node_id:
            node = state.get_node(node_id)
            node.state = NodeState.RETRYING
            node.retry_count = payload.get("retry_count", 0)
    
    def _on_node_skipped(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Node 跳过"""
        node_id = payload.get("node_id")
        if node_id:
            node = state.get_node(node_id)
            node.state = NodeState.SKIPPED
    
    def _on_node_timeout(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Node 超时"""
        node_id = payload.get("node_id")
        if node_id:
            node = state.get_node(node_id)
            node.state = NodeState.TIMEOUT
            node.finished_at = datetime.utcnow()
    
    def _on_context_updated(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Context 更新"""
        updates = payload.get("updates", {})
        state.context.update(updates)
    
    # ========== Patch & Recovery Event Handlers ==========
    
    def _on_patch_applied(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Patch 应用成功"""
        # Patch 应用后可能影响多个节点状态
        # 当前仅记录到 context，不修改节点状态
        patch_id = payload.get("patch_id", "unknown")
        target_nodes = payload.get("target_nodes", [])
        state.context[f"_last_patch_id"] = patch_id
        state.context[f"_patch_target_nodes"] = target_nodes
    
    def _on_patch_failed(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """Patch 应用失败"""
        patch_id = payload.get("patch_id", "unknown")
        error_message = payload.get("error_message", "")
        state.context[f"_last_patch_error"] = {
            "patch_id": patch_id,
            "error": error_message,
        }
    
    def _on_crash_recovery_started(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """崩溃恢复开始"""
        recovery_strategy = payload.get("recovery_strategy", "unknown")
        state.context["_recovery_strategy"] = recovery_strategy
        state.context["_recovery_started"] = True
    
    def _on_crash_recovery_completed(self, state: RebuiltGraphState, payload: Dict[str, Any]):
        """崩溃恢复完成"""
        recovered_nodes = payload.get("recovered_nodes", 0)
        failed_nodes = payload.get("failed_nodes", 0)
        state.context["_recovery_completed"] = True
        state.context["_recovered_nodes"] = recovered_nodes
        state.context["_recovery_failed_nodes"] = failed_nodes
