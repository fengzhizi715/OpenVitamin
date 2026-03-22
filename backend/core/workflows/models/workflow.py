"""
Workflow Resource Model

Workflow 是平台一级资源，支持 RBAC、生命周期管理、审计日志。
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class WorkflowLifecycleState(str, Enum):
    """工作流生命周期状态"""
    DRAFT = "draft"           # 草稿，可编辑
    ACTIVE = "active"         # 已发布，可执行
    DEPRECATED = "deprecated" # 已弃用，仍可执行但会警告
    ARCHIVED = "archived"     # 已归档，不可执行
    DELETED = "deleted"       # 已删除（软删除）


class Workflow(BaseModel):
    """
    Workflow 资源定义
    
    作为平台资源，Workflow 本身不包含 DAG 定义，
    只包含元数据和指向最新版本的引用。
    """
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="工作流唯一标识"
    )
    namespace: str = Field(
        default="default",
        description="命名空间，用于多租户隔离"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="工作流名称"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="工作流描述"
    )
    
    # 生命周期管理
    lifecycle_state: WorkflowLifecycleState = Field(
        default=WorkflowLifecycleState.DRAFT,
        description="生命周期状态"
    )
    
    # 版本引用
    latest_version_id: Optional[str] = Field(
        default=None,
        description="最新版本 ID"
    )
    published_version_id: Optional[str] = Field(
        default=None,
        description="已发布版本 ID（可执行版本）"
    )
    
    # RBAC
    owner_id: str = Field(
        ...,
        description="所有者 ID"
    )
    acl: Dict[str, Any] = Field(
        default_factory=dict,
        description="访问控制列表 {user_id: permission}"
    )
    
    # 元数据
    tags: List[str] = Field(
        default_factory=list,
        description="标签列表"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据"
    )
    
    # 审计字段
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="更新时间"
    )
    created_by: Optional[str] = Field(
        default=None,
        description="创建者"
    )
    updated_by: Optional[str] = Field(
        default=None,
        description="最后更新者"
    )
    
    class Config:
        from_attributes = True
    
    def can_execute(self) -> bool:
        """检查是否可以执行"""
        return (
            self.lifecycle_state in {
                WorkflowLifecycleState.ACTIVE,
                WorkflowLifecycleState.DEPRECATED
            }
            and self.published_version_id is not None
        )
    
    def can_edit(self) -> bool:
        """检查是否可以编辑"""
        return self.lifecycle_state in {
            WorkflowLifecycleState.DRAFT,
            WorkflowLifecycleState.ACTIVE
        }
    
    def get_effective_version_id(self) -> Optional[str]:
        """获取有效版本 ID（优先 published，其次 latest）"""
        return self.published_version_id or self.latest_version_id
    
    def has_permission(self, user_id: str, permission: str) -> bool:
        """检查用户是否有指定权限"""
        if user_id == self.owner_id:
            return True
        user_acl = self.acl.get(user_id, "")
        return permission in user_acl.split(",")


class WorkflowCreateRequest(BaseModel):
    """创建工作流请求"""
    namespace: str = Field(default="default")
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1024)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdateRequest(BaseModel):
    """更新工作流请求"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1024)
    tags: Optional[List[str]] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default=None)
    lifecycle_state: Optional[WorkflowLifecycleState] = Field(default=None)
