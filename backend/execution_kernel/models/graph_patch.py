"""
Graph Patch Protocol (Phase B)
动态图扩展协议，支持 RePlan 场景下的增量图修改
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime


class PatchOperationType(str, Enum):
    """Patch 操作类型"""
    ADD_NODE = "add_node"
    ADD_EDGE = "add_edge"
    DISABLE_NODE = "disable_node"
    SET_METADATA = "set_metadata"


class AddNodeOperation(BaseModel):
    """添加节点操作"""
    type: PatchOperationType = PatchOperationType.ADD_NODE
    node_id: str = Field(..., description="新节点 ID")
    node_type: str = Field(..., description="节点类型")
    config: Dict[str, Any] = Field(default_factory=dict, description="节点配置")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="输入 Schema")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="输出 Schema")
    retry_policy: Optional[Dict[str, Any]] = Field(default=None, description="重试策略")
    timeout_seconds: float = Field(default=300.0, ge=1.0, description="超时时间")


class AddEdgeOperation(BaseModel):
    """添加边操作"""
    type: PatchOperationType = PatchOperationType.ADD_EDGE
    from_node: str = Field(..., description="源节点 ID")
    to_node: str = Field(..., description="目标节点 ID")
    on: str = Field(default="success", description="触发条件")
    condition: Optional[str] = Field(default=None, description="条件表达式")


class DisableNodeOperation(BaseModel):
    """禁用节点操作（逻辑终止）"""
    type: PatchOperationType = PatchOperationType.DISABLE_NODE
    node_id: str = Field(..., description="要禁用的节点 ID")
    reason: Optional[str] = Field(default=None, description="禁用原因")


class SetMetadataOperation(BaseModel):
    """设置元数据操作"""
    type: PatchOperationType = PatchOperationType.SET_METADATA
    key: str = Field(..., description="元数据键")
    value: Any = Field(..., description="元数据值")


# Patch 操作联合类型
PatchOperation = Union[
    AddNodeOperation,
    AddEdgeOperation,
    DisableNodeOperation,
    SetMetadataOperation,
]


class GraphPatch(BaseModel):
    """
    图补丁定义
    
    用于 RePlan 场景下的动态图扩展。
    支持版本控制（CAS/乐观锁）和事务化应用。
    """
    patch_id: str = Field(..., description="Patch 唯一标识")
    target_graph_id: str = Field(..., description="目标图 ID")
    base_version: str = Field(..., description="基于的图版本")
    target_version: str = Field(..., description="目标图版本")
    operations: List[PatchOperation] = Field(default_factory=list, description="操作列表")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    created_by: Optional[str] = Field(default=None, description="创建者")
    reason: Optional[str] = Field(default=None, description="Patch 原因（如 RePlan）")
    
    class Config:
        frozen = True


class GraphPatchResult(BaseModel):
    """Patch 应用结果"""
    success: bool = Field(..., description="是否成功")
    patch_id: str = Field(..., description="Patch ID")
    applied_version: str = Field(..., description="应用后的版本")
    previous_version: str = Field(..., description="应用前的版本")
    applied_operations: int = Field(default=0, description="成功应用的操作数")
    failed_operations: int = Field(default=0, description="失败的操作数")
    errors: List[str] = Field(default_factory=list, description="错误信息")
    applied_at: datetime = Field(default_factory=datetime.utcnow, description="应用时间")


class GraphVersionInfo(BaseModel):
    """图版本信息"""
    graph_id: str = Field(..., description="图 ID")
    current_version: str = Field(..., description="当前版本")
    version_history: List[str] = Field(default_factory=list, description="版本历史")
    patch_count: int = Field(default=0, description="已应用的 Patch 数量")
    last_patch_at: Optional[datetime] = Field(default=None, description="最后 Patch 时间")


class ExecutionPointer(BaseModel):
    """
    执行指针
    
    记录当前执行状态，用于 Patch 后的安全迁移。
    """
    instance_id: str = Field(..., description="实例 ID")
    completed_nodes: List[str] = Field(default_factory=list, description="已完成节点")
    ready_nodes: List[str] = Field(default_factory=list, description="就绪节点队列")
    running_nodes: List[str] = Field(default_factory=list, description="运行中节点")
    failed_nodes: List[str] = Field(default_factory=list, description="失败节点")
    graph_version: str = Field(..., description="当前图版本")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")


class PatchMigrationStrategy(str, Enum):
    """Patch 迁移策略"""
    PRESERVE_COMPLETED = "preserve_completed"  # 保留已完成节点
    RESET_READY_QUEUE = "reset_ready_queue"    # 重置就绪队列
    BLOCK_NEW_DEPENDENCIES = "block_new_dependencies"  # 阻塞新增依赖


class PatchMigrationPlan(BaseModel):
    """Patch 迁移计划"""
    strategy: PatchMigrationStrategy = Field(default=PatchMigrationStrategy.PRESERVE_COMPLETED)
    nodes_to_preserve: List[str] = Field(default_factory=list, description="保留的节点")
    nodes_to_reset: List[str] = Field(default_factory=list, description="重置的节点")
    new_dependencies: List[str] = Field(default_factory=list, description="新增依赖")
