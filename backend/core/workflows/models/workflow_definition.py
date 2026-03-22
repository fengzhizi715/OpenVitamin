"""
Workflow Definition Model

WorkflowDefinition 是不可变的定义快照。
每次修改都会创建新的 Definition，而不是修改现有定义。
"""

from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid
import hashlib
import json


class WorkflowDefinition(BaseModel):
    """
    工作流定义（不可变）
    
    Definition 是 Workflow 的某个版本的完整定义快照。
    一旦创建，Definition 的内容不可修改。
    
    注意：这不是 DAG 本身，而是 DAG 的容器。
    实际的 DAG 存储在 WorkflowVersion 中。
    """
    definition_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="定义唯一标识"
    )
    workflow_id: str = Field(
        ...,
        description="所属工作流 ID"
    )
    
    # 定义元数据
    description: Optional[str] = Field(
        default=None,
        description="此版本的变更说明"
    )
    change_log: Optional[str] = Field(
        default=None,
        description="变更日志"
    )
    
    # 创建信息
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="创建时间"
    )
    created_by: Optional[str] = Field(
        default=None,
        description="创建者"
    )
    
    # 来源信息（用于追溯）
    source_version_id: Optional[str] = Field(
        default=None,
        description="基于哪个版本创建（用于 fork）"
    )
    
    class Config:
        from_attributes = True
        frozen = True  # Pydantic 不可变模型
    
    def get_id(self) -> str:
        """获取定义 ID"""
        return self.definition_id


class WorkflowDefinitionCreateRequest(BaseModel):
    """创建定义请求"""
    workflow_id: str = Field(..., description="所属工作流 ID")
    description: Optional[str] = Field(default=None, description="变更说明")
    change_log: Optional[str] = Field(default=None, description="变更日志")
    source_version_id: Optional[str] = Field(
        default=None,
        description="基于哪个版本创建"
    )
