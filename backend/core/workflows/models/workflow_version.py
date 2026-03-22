"""
Workflow Version Model

WorkflowVersion 包含实际的 DAG 定义。
这是 Workflow Control Plane 的核心版本控制单元。
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
import uuid
import hashlib
import json


class WorkflowVersionState(str, Enum):
    """版本状态"""
    DRAFT = "draft"           # 草稿，可编辑
    PUBLISHED = "published"   # 已发布，可执行
    DEPRECATED = "deprecated" # 已弃用
    ARCHIVED = "archived"     # 已归档


class WorkflowNode(BaseModel):
    """工作流节点定义（DAG 节点）"""
    id: str = Field(..., description="节点唯一标识")
    type: str = Field(..., description="节点类型 (llm, tool, condition, etc.)")
    name: Optional[str] = Field(default=None, description="节点显示名称")
    description: Optional[str] = Field(default=None, description="节点描述")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="节点配置"
    )
    position: Optional[Dict[str, float]] = Field(
        default=None,
        description="UI 位置 {x, y}"
    )
    
    class Config:
        frozen = True


class WorkflowEdge(BaseModel):
    """工作流边定义（DAG 边）"""
    from_node: str = Field(..., description="源节点 ID")
    to_node: str = Field(..., description="目标节点 ID")
    source_handle: Optional[str] = Field(
        default=None,
        description="源节点 handle（true/false/continue/exit 等）"
    )
    target_handle: Optional[str] = Field(
        default=None,
        description="目标节点 handle"
    )
    condition: Optional[str] = Field(
        default=None,
        description="条件表达式（条件边）"
    )
    label: Optional[str] = Field(default=None, description="边标签")
    
    class Config:
        frozen = True


class WorkflowDAG(BaseModel):
    """
    工作流 DAG 定义
    
    这是实际的可执行 DAG 结构。
    """
    nodes: List[WorkflowNode] = Field(
        default_factory=list,
        description="节点列表"
    )
    edges: List[WorkflowEdge] = Field(
        default_factory=list,
        description="边列表"
    )
    
    # 执行配置
    entry_node: Optional[str] = Field(
        default=None,
        description="入口节点 ID（默认第一个节点）"
    )
    global_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="全局执行配置"
    )
    
    class Config:
        frozen = True
    
    @staticmethod
    def _normalize_node_type(node_type: Optional[str]) -> str:
        t = str(node_type or "").strip().lower()
        if t == "start":
            return "input"
        if t == "end":
            return "output"
        return t

    @classmethod
    def _resolve_node_semantic_type(cls, node: "WorkflowNode") -> str:
        cfg = node.config or {}
        cfg_type = cls._normalize_node_type(cfg.get("workflow_node_type"))
        if cfg_type:
            return cfg_type
        return cls._normalize_node_type(node.type)

    def validate(
        self,
        require_condition_branches: bool = False,
        require_loop_branches: bool = False,
    ) -> List[str]:
        """验证 DAG 有效性"""
        errors = []
        
        # 检查节点 ID 唯一性
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            errors.append("Duplicate node IDs found")
        
        # 检查边引用的节点是否存在
        node_id_set = set(node_ids)
        for edge in self.edges:
            if edge.from_node not in node_id_set:
                errors.append(f"Edge references non-existent from_node: {edge.from_node}")
            if edge.to_node not in node_id_set:
                errors.append(f"Edge references non-existent to_node: {edge.to_node}")
        
        # 检查入口节点
        entry = self.entry_node or (node_ids[0] if node_ids else None)
        if entry and entry not in node_id_set:
            errors.append(f"Entry node not found: {entry}")
        
        # 检查循环依赖
        if self._has_cycle():
            errors.append("Cycle detected in DAG")

        if require_condition_branches:
            condition_node_ids = {
                node.id
                for node in self.nodes
                if self._resolve_node_semantic_type(node) == "condition"
            }
            if condition_node_ids:
                outgoing_by_node: Dict[str, List[WorkflowEdge]] = {nid: [] for nid in condition_node_ids}
                for edge in self.edges:
                    if edge.from_node in outgoing_by_node:
                        outgoing_by_node[edge.from_node].append(edge)

                for node_id, outgoing in outgoing_by_node.items():
                    has_true = False
                    has_false = False
                    for edge in outgoing:
                        trigger_hint = str(edge.source_handle or edge.label or "").strip().lower()
                        if trigger_hint in {"true", "condition_true"}:
                            has_true = True
                        elif trigger_hint in {"false", "condition_false"}:
                            has_false = True
                        elif edge.condition:
                            # 兼容历史定义：有 condition 但无显式 handle/label 时按 true 分支处理
                            has_true = True

                    missing = []
                    if not has_true:
                        missing.append("true")
                    if not has_false:
                        missing.append("false")
                    if missing:
                        errors.append(
                            f"Condition node '{node_id}' missing required branch edge(s): {', '.join(missing)}"
                        )

        if require_loop_branches:
            loop_node_ids = {
                node.id
                for node in self.nodes
                if self._resolve_node_semantic_type(node) == "loop"
            }
            if loop_node_ids:
                outgoing_by_node: Dict[str, List[WorkflowEdge]] = {nid: [] for nid in loop_node_ids}
                for edge in self.edges:
                    if edge.from_node in outgoing_by_node:
                        outgoing_by_node[edge.from_node].append(edge)

                for node_id, outgoing in outgoing_by_node.items():
                    has_continue = False
                    has_exit = False
                    for edge in outgoing:
                        trigger_hint = str(edge.source_handle or edge.label or "").strip().lower()
                        if trigger_hint in {"continue", "loop_continue"}:
                            has_continue = True
                        elif trigger_hint in {"exit", "loop_exit"}:
                            has_exit = True

                    missing = []
                    if not has_continue:
                        missing.append("continue")
                    if not has_exit:
                        missing.append("exit")
                    if missing:
                        errors.append(
                            f"Loop node '{node_id}' missing required branch edge(s): {', '.join(missing)}"
                        )
        
        return errors
    
    def _has_cycle(self) -> bool:
        """检查是否有循环依赖"""
        # 构建邻接表
        graph = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            graph[edge.from_node].append(edge.to_node)
        
        visited = set()
        rec_stack = set()
        
        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            for neighbor in graph.get(node_id, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node_id)
            return False
        
        for node_id in graph:
            if node_id not in visited:
                if dfs(node_id):
                    return True
        return False
    
    def compute_checksum(self) -> str:
        """计算 DAG 校验和"""
        # Pydantic v2 的 model_dump_json 不支持 sort_keys，改为先 dump 再稳定序列化
        data = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()


class WorkflowVersion(BaseModel):
    """
    工作流版本（不可变）
    
    这是 Workflow Control Plane 的核心版本控制单元。
    包含完整的 DAG 定义和版本元数据。
    """
    version_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="版本唯一标识"
    )
    workflow_id: str = Field(
        ...,
        description="所属工作流 ID"
    )
    definition_id: str = Field(
        ...,
        description="所属定义 ID"
    )
    
    # 版本号（语义化版本）
    version_number: str = Field(
        ...,
        description="版本号 (e.g., 1.0.0)"
    )
    
    # DAG 定义
    dag: WorkflowDAG = Field(
        ...,
        description="工作流 DAG 定义"
    )
    
    # 校验和（用于完整性验证）
    checksum: str = Field(
        ...,
        description="DAG 校验和"
    )
    
    # 版本状态
    state: WorkflowVersionState = Field(
        default=WorkflowVersionState.DRAFT,
        description="版本状态"
    )
    
    # 版本元数据
    description: Optional[str] = Field(
        default=None,
        description="版本说明"
    )
    change_notes: Optional[str] = Field(
        default=None,
        description="变更说明"
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
    
    # 发布信息
    published_at: Optional[datetime] = Field(
        default=None,
        description="发布时间"
    )
    published_by: Optional[str] = Field(
        default=None,
        description="发布者"
    )
    
    class Config:
        from_attributes = True
        frozen = True
    
    def validate_dag(
        self,
        require_condition_branches: bool = False,
        require_loop_branches: bool = False,
    ) -> List[str]:
        """验证 DAG 有效性"""
        return self.dag.validate(
            require_condition_branches=require_condition_branches,
            require_loop_branches=require_loop_branches,
        )
    
    def is_published(self) -> bool:
        """检查是否已发布"""
        return self.state == WorkflowVersionState.PUBLISHED
    
    def can_execute(self) -> bool:
        """检查是否可以执行"""
        return self.state in {
            WorkflowVersionState.PUBLISHED,
            WorkflowVersionState.DEPRECATED
        }


class WorkflowVersionCreateRequest(BaseModel):
    """创建版本请求"""
    workflow_id: str = Field(..., description="所属工作流 ID")
    definition_id: str = Field(..., description="所属定义 ID")
    version_number: str = Field(..., description="版本号")
    dag: WorkflowDAG = Field(..., description="DAG 定义")
    description: Optional[str] = Field(default=None, description="版本说明")
    change_notes: Optional[str] = Field(default=None, description="变更说明")


class WorkflowVersionPublishRequest(BaseModel):
    """发布版本请求"""
    change_notes: Optional[str] = Field(default=None, description="发布说明")
