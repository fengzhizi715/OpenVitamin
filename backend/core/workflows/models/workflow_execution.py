"""
Workflow Execution Model

WorkflowExecution 表示工作流的一次执行实例。
它与 execution_kernel 的 GraphInstance 关联。
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class WorkflowExecutionState(str, Enum):
    """工作流执行状态"""
    PENDING = "pending"           # 等待执行
    QUEUED = "queued"             # 已在队列中
    RUNNING = "running"           # 执行中
    PAUSED = "paused"             # 已暂停
    COMPLETED = "completed"       # 成功完成
    FAILED = "failed"             # 执行失败
    CANCELLED = "cancelled"       # 已取消
    TIMEOUT = "timeout"           # 执行超时


class WorkflowExecutionNodeState(str, Enum):
    """执行节点状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class WorkflowExecutionNode(BaseModel):
    """
    工作流执行节点状态
    
    记录每个节点的执行状态，与 execution_kernel 的 NodeRuntime 对应。
    """
    node_id: str = Field(..., description="节点定义 ID")
    state: WorkflowExecutionNodeState = Field(
        default=WorkflowExecutionNodeState.PENDING,
        description="节点状态"
    )
    input_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="输入数据"
    )
    output_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="输出数据"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="错误信息"
    )
    error_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="结构化错误详情"
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="开始时间"
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description="结束时间"
    )
    retry_count: int = Field(
        default=0,
        description="重试次数"
    )
    
    class Config:
        from_attributes = True


class WorkflowExecution(BaseModel):
    """
    工作流执行实例
    
    表示工作流的一次执行，关联到 execution_kernel 的 GraphInstance。
    """
    execution_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="执行唯一标识"
    )
    
    # 关联关系
    workflow_id: str = Field(
        ...,
        description="所属工作流 ID"
    )
    version_id: str = Field(
        ...,
        description="执行的版本 ID"
    )
    
    # 与 execution_kernel 的关联
    graph_instance_id: Optional[str] = Field(
        default=None,
        description="关联的 GraphInstance ID"
    )
    
    # 执行状态
    state: WorkflowExecutionState = Field(
        default=WorkflowExecutionState.PENDING,
        description="执行状态"
    )
    
    # 执行上下文
    input_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="执行输入数据"
    )
    output_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="执行输出数据"
    )
    global_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="全局上下文"
    )
    
    # 节点执行状态
    node_states: List[WorkflowExecutionNode] = Field(
        default_factory=list,
        description="节点执行状态列表"
    )
    
    # 执行元数据
    triggered_by: Optional[str] = Field(
        default=None,
        description="触发者"
    )
    trigger_type: str = Field(
        default="manual",
        description="触发类型 (manual, scheduled, api, webhook)"
    )
    
    # 资源配额
    resource_quota: Dict[str, Any] = Field(
        default_factory=dict,
        description="资源配额配置"
    )
    
    # 错误信息
    error_message: Optional[str] = Field(
        default=None,
        description="错误信息"
    )
    error_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="错误详情"
    )
    
    # 时间戳
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="创建时间"
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="开始时间"
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description="结束时间"
    )
    
    # 执行统计
    duration_ms: Optional[int] = Field(
        default=None,
        description="执行时长（毫秒）"
    )
    queue_position: Optional[int] = Field(
        default=None,
        description="进入队列时的位置（1-based）"
    )
    queued_at: Optional[datetime] = Field(
        default=None,
        description="入队时间"
    )
    wait_duration_ms: Optional[int] = Field(
        default=None,
        description="排队等待时长（毫秒）"
    )
    
    class Config:
        from_attributes = True
    
    def is_terminal(self) -> bool:
        """检查是否处于终态"""
        return self.state in {
            WorkflowExecutionState.COMPLETED,
            WorkflowExecutionState.FAILED,
            WorkflowExecutionState.CANCELLED,
            WorkflowExecutionState.TIMEOUT
        }
    
    def can_cancel(self) -> bool:
        """检查是否可以取消"""
        return self.state in {
            WorkflowExecutionState.PENDING,
            WorkflowExecutionState.QUEUED,
            WorkflowExecutionState.RUNNING,
            WorkflowExecutionState.PAUSED
        }
    
    def get_node_state(self, node_id: str) -> Optional[WorkflowExecutionNode]:
        """获取节点执行状态"""
        for node in self.node_states:
            if node.node_id == node_id:
                return node
        return None
    
    def update_duration(self) -> None:
        """更新执行时长"""
        if self.started_at and self.finished_at:
            delta = self.finished_at - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)


class WorkflowExecutionCreateRequest(BaseModel):
    """创建执行请求"""
    workflow_id: str = Field(..., description="工作流 ID")
    version_id: Optional[str] = Field(
        default=None,
        description="版本 ID（不指定则使用 published 版本）"
    )
    input_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="输入数据"
    )
    global_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="全局上下文"
    )
    trigger_type: str = Field(default="manual", description="触发类型")


class WorkflowExecutionCancelRequest(BaseModel):
    """取消执行请求"""
    reason: Optional[str] = Field(default=None, description="取消原因")
