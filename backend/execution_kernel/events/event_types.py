"""
V2.6: Observability & Replay Layer - Event Types
定义 Execution Kernel 的所有事件类型

V2.7: 新增 Optimization Layer 事件类型
"""

from enum import Enum


class ExecutionEventType(str, Enum):
    """
    执行事件类型枚举
    
    所有事件类型按执行生命周期分组：
    - Graph 生命周期事件
    - Node 生命周期事件
    - 调度决策事件
    - 状态变更事件
    - V2.7: Optimization Layer 事件
    """
    
    # Graph 生命周期
    GRAPH_STARTED = "graph_started"
    GRAPH_COMPLETED = "graph_completed"
    GRAPH_CANCELLED = "graph_cancelled"
    GRAPH_FAILED = "graph_failed"
    
    # Node 生命周期
    NODE_SCHEDULED = "node_scheduled"
    NODE_STARTED = "node_started"
    NODE_SUCCEEDED = "node_succeeded"
    NODE_FAILED = "node_failed"
    NODE_RETRY_SCHEDULED = "node_retry_scheduled"
    NODE_SKIPPED = "node_skipped"
    NODE_TIMEOUT = "node_timeout"
    
    # 调度决策
    SCHEDULER_DECISION = "scheduler_decision"
    
    # 状态变更
    STATE_TRANSITION = "state_transition"
    CONTEXT_UPDATED = "context_updated"
    
    # Patch 事件 (Phase B)
    PATCH_APPLIED = "patch_applied"
    PATCH_FAILED = "patch_failed"
    
    # 恢复事件
    CRASH_RECOVERY_STARTED = "crash_recovery_started"
    CRASH_RECOVERY_COMPLETED = "crash_recovery_completed"
    
    # V2.7: Optimization Layer 事件
    SNAPSHOT_BUILT = "snapshot_built"
    POLICY_CHANGED = "policy_changed"
    STATISTICS_COLLECTED = "statistics_collected"


# 事件类型分组（用于验证和查询）
GRAPH_LIFECYCLE_EVENTS = {
    ExecutionEventType.GRAPH_STARTED,
    ExecutionEventType.GRAPH_COMPLETED,
    ExecutionEventType.GRAPH_CANCELLED,
    ExecutionEventType.GRAPH_FAILED,
}

NODE_LIFECYCLE_EVENTS = {
    ExecutionEventType.NODE_SCHEDULED,
    ExecutionEventType.NODE_STARTED,
    ExecutionEventType.NODE_SUCCEEDED,
    ExecutionEventType.NODE_FAILED,
    ExecutionEventType.NODE_RETRY_SCHEDULED,
    ExecutionEventType.NODE_SKIPPED,
    ExecutionEventType.NODE_TIMEOUT,
}

TERMINAL_EVENTS = {
    ExecutionEventType.GRAPH_COMPLETED,
    ExecutionEventType.GRAPH_CANCELLED,
    ExecutionEventType.GRAPH_FAILED,
}

# V2.7: Optimization Layer 事件分组
OPTIMIZATION_EVENTS = {
    ExecutionEventType.SNAPSHOT_BUILT,
    ExecutionEventType.POLICY_CHANGED,
    ExecutionEventType.STATISTICS_COLLECTED,
}
