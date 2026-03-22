"""
Workflow Service

Workflow 资源的业务逻辑层。
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from core.workflows.models import (
    Workflow,
    WorkflowLifecycleState,
    WorkflowCreateRequest,
    WorkflowUpdateRequest
)
from core.workflows.repository import WorkflowRepository
from log import logger


class WorkflowService:
    """Workflow 业务服务"""
    
    def __init__(self, db: Session):
        self.db = db
        self.repository = WorkflowRepository(db)
    
    def create_workflow(
        self,
        request: WorkflowCreateRequest,
        owner_id: str
    ) -> Workflow:
        """创建工作流"""
        # 检查命名空间内名称唯一性
        existing = self.repository.get_by_namespace_and_name(
            request.namespace,
            request.name
        )
        if existing:
            raise ValueError(
                f"Workflow with name '{request.name}' already exists in namespace '{request.namespace}'"
            )
        
        # 创建工作流
        workflow = Workflow(
            namespace=request.namespace,
            name=request.name,
            description=request.description,
            lifecycle_state=WorkflowLifecycleState.DRAFT,
            owner_id=owner_id,
            tags=request.tags,
            metadata=request.metadata,
            created_by=owner_id,
            updated_by=owner_id
        )
        
        created = self.repository.create(workflow)
        logger.info(f"[WorkflowService] Created workflow: {created.id} by {owner_id}")
        return created
    
    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """获取工作流"""
        return self.repository.get_by_id(workflow_id)
    
    def get_workflow_by_name(
        self,
        namespace: str,
        name: str
    ) -> Optional[Workflow]:
        """根据名称获取工作流"""
        return self.repository.get_by_namespace_and_name(namespace, name)
    
    def list_workflows(
        self,
        namespace: Optional[str] = None,
        owner_id: Optional[str] = None,
        lifecycle_state: Optional[WorkflowLifecycleState] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Workflow]:
        """列出工作流"""
        return self.repository.list_workflows(
            namespace=namespace,
            owner_id=owner_id,
            lifecycle_state=lifecycle_state,
            limit=limit,
            offset=offset
        )

    def count_workflows(
        self,
        namespace: Optional[str] = None,
        owner_id: Optional[str] = None,
        lifecycle_state: Optional[WorkflowLifecycleState] = None,
    ) -> int:
        return self.repository.count_workflows(
            namespace=namespace,
            owner_id=owner_id,
            lifecycle_state=lifecycle_state,
        )
    
    def update_workflow(
        self,
        workflow_id: str,
        request: WorkflowUpdateRequest,
        updated_by: str
    ) -> Optional[Workflow]:
        """更新工作流"""
        workflow = self.repository.get_by_id(workflow_id)
        if not workflow:
            return None
        
        # 检查权限
        if not workflow.has_permission(updated_by, "write"):
            raise PermissionError(f"User {updated_by} has no write permission")
        
        # 检查是否可编辑
        if not workflow.can_edit():
            raise ValueError(f"Workflow is in state {workflow.lifecycle_state.value} and cannot be edited")
        
        # 构建更新
        updates: Dict[str, Any] = {}
        if request.name is not None:
            updates["name"] = request.name
        if request.description is not None:
            updates["description"] = request.description
        if request.tags is not None:
            updates["tags"] = request.tags
        if request.metadata is not None:
            updates["metadata"] = request.metadata
        if request.lifecycle_state is not None:
            updates["lifecycle_state"] = request.lifecycle_state
        
        if not updates:
            return workflow
        
        updated = self.repository.update(workflow_id, updates, updated_by)
        logger.info(f"[WorkflowService] Updated workflow: {workflow_id} by {updated_by}")
        return updated
    
    def delete_workflow(
        self,
        workflow_id: str,
        deleted_by: str,
        soft: bool = True
    ) -> bool:
        """删除工作流"""
        workflow = self.repository.get_by_id(workflow_id)
        if not workflow:
            return False
        
        # 检查权限
        if not workflow.has_permission(deleted_by, "delete"):
            raise PermissionError(f"User {deleted_by} has no delete permission")
        
        result = self.repository.delete(workflow_id, soft=soft)
        logger.info(f"[WorkflowService] Deleted workflow: {workflow_id} by {deleted_by}")
        return result
    
    def publish_workflow(
        self,
        workflow_id: str,
        version_id: str,
        published_by: str
    ) -> Optional[Workflow]:
        """发布工作流"""
        workflow = self.repository.get_by_id(workflow_id)
        if not workflow:
            return None
        
        # 检查权限
        if not workflow.has_permission(published_by, "publish"):
            raise PermissionError(f"User {published_by} has no publish permission")
        
        # 更新状态
        updates = {
            "lifecycle_state": WorkflowLifecycleState.ACTIVE,
            "published_version_id": version_id
        }
        
        updated = self.repository.update(workflow_id, updates, published_by)
        logger.info(f"[WorkflowService] Published workflow: {workflow_id} with version {version_id}")
        return updated
    
    def deprecate_workflow(
        self,
        workflow_id: str,
        deprecated_by: str
    ) -> Optional[Workflow]:
        """弃用工作流"""
        workflow = self.repository.get_by_id(workflow_id)
        if not workflow:
            return None
        
        # 检查权限
        if not workflow.has_permission(deprecated_by, "publish"):
            raise PermissionError(f"User {deprecated_by} has no permission")
        
        updates = {"lifecycle_state": WorkflowLifecycleState.DEPRECATED}
        
        updated = self.repository.update(workflow_id, updates, deprecated_by)
        logger.info(f"[WorkflowService] Deprecated workflow: {workflow_id}")
        return updated
    
    def archive_workflow(
        self,
        workflow_id: str,
        archived_by: str
    ) -> Optional[Workflow]:
        """归档工作流"""
        workflow = self.repository.get_by_id(workflow_id)
        if not workflow:
            return None
        
        # 检查权限
        if not workflow.has_permission(archived_by, "admin"):
            raise PermissionError(f"User {archived_by} has no admin permission")
        
        updates = {"lifecycle_state": WorkflowLifecycleState.ARCHIVED}
        
        updated = self.repository.update(workflow_id, updates, archived_by)
        logger.info(f"[WorkflowService] Archived workflow: {workflow_id}")
        return updated
    
    def check_permission(
        self,
        workflow_id: str,
        user_id: str,
        permission: str
    ) -> bool:
        """检查用户权限"""
        workflow = self.repository.get_by_id(workflow_id)
        if not workflow:
            return False
        return workflow.has_permission(user_id, permission)
