"""
Node Runtime Models
运行态模型，与 Definition 完全隔离
"""

from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class NodeState(str, Enum):
    """节点执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class GraphInstanceState(str, Enum):
    """图实例状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 状态转换规则
VALID_TRANSITIONS: Dict[NodeState, set] = {
    NodeState.PENDING: {NodeState.RUNNING, NodeState.SKIPPED, NodeState.CANCELLED},
    NodeState.RUNNING: {NodeState.SUCCESS, NodeState.FAILED, NodeState.TIMEOUT, NodeState.CANCELLED},
    NodeState.FAILED: {NodeState.RETRYING, NodeState.CANCELLED},
    NodeState.RETRYING: {NodeState.RUNNING, NodeState.CANCELLED},
    NodeState.SUCCESS: set(),  # 终态
    NodeState.SKIPPED: set(),  # 终态
    NodeState.CANCELLED: set(),  # 终态
    NodeState.TIMEOUT: {NodeState.RETRYING, NodeState.CANCELLED},
}


class NodeRuntime(BaseModel):
    """节点运行时状态"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="运行时 ID")
    graph_instance_id: str = Field(..., description="所属图实例 ID")
    node_id: str = Field(..., description="节点定义 ID")
    state: NodeState = Field(default=NodeState.PENDING, description="执行状态")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="输入数据")
    output_data: Dict[str, Any] = Field(default_factory=dict, description="输出数据")
    retry_count: int = Field(default=0, ge=0, description="已重试次数")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    error_type: Optional[str] = Field(default=None, description="错误类型")
    started_at: Optional[datetime] = Field(default=None, description="开始时间")
    finished_at: Optional[datetime] = Field(default=None, description="结束时间")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
    
    class Config:
        from_attributes = True
    
    def can_transition_to(self, new_state: NodeState) -> bool:
        """检查是否可以转换到新状态"""
        return new_state in VALID_TRANSITIONS.get(self.state, set())
    
    def is_terminal(self) -> bool:
        """检查是否处于终态"""
        return len(VALID_TRANSITIONS.get(self.state, set())) == 0
    
    def is_retryable(self, max_retries: int) -> bool:
        """检查是否可以重试"""
        return self.state in {NodeState.FAILED, NodeState.TIMEOUT} and self.retry_count < max_retries


class GraphInstance(BaseModel):
    """图实例（运行态）"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="实例 ID")
    graph_definition_id: str = Field(..., description="图定义 ID")
    graph_definition_version: str = Field(default="1.0.0", description="图定义版本")
    state: GraphInstanceState = Field(default=GraphInstanceState.PENDING, description="实例状态")
    global_context: Dict[str, Any] = Field(default_factory=dict, description="全局上下文")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
    started_at: Optional[datetime] = Field(default=None, description="开始时间")
    finished_at: Optional[datetime] = Field(default=None, description="结束时间")
    
    class Config:
        from_attributes = True


class NodeCacheEntry(BaseModel):
    """节点缓存条目"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    node_id: str = Field(..., description="节点 ID")
    input_hash: str = Field(..., description="输入数据哈希")
    output_data: Dict[str, Any] = Field(default_factory=dict, description="输出数据")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    
    class Config:
        from_attributes = True
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
