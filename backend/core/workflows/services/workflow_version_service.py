"""
Workflow Version Service

WorkflowVersion 和 WorkflowDefinition 的业务逻辑层。
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from core.workflows.models import (
    WorkflowVersion,
    WorkflowDefinition,
    WorkflowVersionState,
    WorkflowDAG,
    WorkflowNode,
    WorkflowEdge
)
from core.workflows.repository import WorkflowVersionRepository
from log import logger


class WorkflowVersionService:
    """Workflow 版本业务服务"""
    
    def __init__(self, db: Session):
        self.db = db
        self.repository = WorkflowVersionRepository(db)
    
    def create_definition(
        self,
        workflow_id: str,
        description: Optional[str] = None,
        change_log: Optional[str] = None,
        source_version_id: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> WorkflowDefinition:
        """创建定义"""
        definition = WorkflowDefinition(
            workflow_id=workflow_id,
            description=description,
            change_log=change_log,
            source_version_id=source_version_id,
            created_by=created_by
        )
        
        created = self.repository.create_definition(definition)
        logger.info(f"[WorkflowVersionService] Created definition: {created.definition_id}")
        return created
    
    def get_definition(self, definition_id: str) -> Optional[WorkflowDefinition]:
        """获取定义"""
        return self.repository.get_definition_by_id(definition_id)
    
    def list_definitions(
        self,
        workflow_id: str,
        limit: int = 100
    ) -> List[WorkflowDefinition]:
        """列出定义"""
        return self.repository.list_definitions_by_workflow(workflow_id, limit)
    
    def create_version(
        self,
        workflow_id: str,
        definition_id: str,
        dag: WorkflowDAG,
        version_number: Optional[str] = None,
        description: Optional[str] = None,
        change_notes: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> WorkflowVersion:
        """创建版本"""
        dag = self._normalize_dag(dag)

        # 验证 DAG
        errors = dag.validate()
        if errors:
            raise ValueError(f"DAG validation failed: {'; '.join(errors)}")
        
        # 生成版本号
        if version_number is None:
            version_number = self.repository.get_next_version_number(workflow_id)
        
        # 计算校验和
        checksum = dag.compute_checksum()
        
        # 创建版本
        version = WorkflowVersion(
            workflow_id=workflow_id,
            definition_id=definition_id,
            version_number=version_number,
            dag=dag,
            checksum=checksum,
            state=WorkflowVersionState.DRAFT,
            description=description,
            change_notes=change_notes,
            created_by=created_by
        )
        
        created = self.repository.create_version(version)
        logger.info(f"[WorkflowVersionService] Created version: {created.version_id} ({version_number})")
        return created

    @staticmethod
    def _normalize_dag(dag: WorkflowDAG) -> WorkflowDAG:
        """配置归一化：收敛历史字段，降低前后端字段漂移风险。"""
        normalized_nodes: List[WorkflowNode] = []
        for node in dag.nodes:
            cfg = dict(node.config or {})
            node_type = str(node.type or "").strip().lower()
            workflow_node_type = str(cfg.get("workflow_node_type") or node_type).strip().lower()

            if workflow_node_type == "llm":
                model_id = str(cfg.get("model_id") or "").strip()
                legacy_model = str(cfg.get("model") or "").strip()
                if not model_id and legacy_model:
                    cfg["model_id"] = legacy_model
                cfg.pop("model", None)

            if workflow_node_type == "agent":
                timeout = cfg.get("timeout")
                legacy_timeout = cfg.get("agent_timeout_seconds")
                if (timeout is None or timeout == "") and (legacy_timeout is not None and legacy_timeout != ""):
                    cfg["timeout"] = legacy_timeout
                cfg.pop("agent_timeout_seconds", None)

            if workflow_node_type in {"tool", "skill"}:
                tool_name = str(cfg.get("tool_name") or "").strip()
                tool_id = str(cfg.get("tool_id") or "").strip()
                if not tool_name and tool_id:
                    cfg["tool_name"] = tool_id
                cfg.pop("tool_id", None)

            normalized_nodes.append(
                WorkflowNode(
                    id=node.id,
                    type=node.type,
                    name=node.name,
                    description=node.description,
                    config=cfg,
                    position=node.position,
                )
            )

        normalized_edges: List[WorkflowEdge] = []
        for edge in dag.edges:
            source_handle = str(edge.source_handle or "").strip().lower() or None
            label = str(edge.label or "").strip().lower() or None

            if not source_handle and label in {"true", "false", "continue", "exit", "condition_true", "condition_false", "loop_continue", "loop_exit"}:
                source_handle = label
            if not label and source_handle in {"true", "false", "continue", "exit"}:
                label = source_handle

            normalized_edges.append(
                WorkflowEdge(
                    from_node=edge.from_node,
                    to_node=edge.to_node,
                    source_handle=source_handle,
                    target_handle=edge.target_handle,
                    condition=edge.condition,
                    label=label,
                )
            )

        return WorkflowDAG(
            nodes=normalized_nodes,
            edges=normalized_edges,
            entry_node=dag.entry_node,
            global_config=dag.global_config,
        )
    
    def get_version(self, version_id: str) -> Optional[WorkflowVersion]:
        """获取版本"""
        return self.repository.get_version_by_id(version_id)
    
    def get_version_by_number(
        self,
        workflow_id: str,
        version_number: str
    ) -> Optional[WorkflowVersion]:
        """根据版本号获取版本"""
        return self.repository.get_version_by_number(workflow_id, version_number)
    
    def list_versions(
        self,
        workflow_id: str,
        state: Optional[WorkflowVersionState] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkflowVersion]:
        """列出版本"""
        return self.repository.list_versions_by_workflow(
            workflow_id,
            state=state,
            limit=limit,
            offset=offset
        )

    def count_versions(
        self,
        workflow_id: str,
        state: Optional[WorkflowVersionState] = None,
    ) -> int:
        return self.repository.count_versions_by_workflow(workflow_id, state=state)
    
    def publish_version(
        self,
        version_id: str,
        published_by: str
    ) -> Optional[WorkflowVersion]:
        """发布版本"""
        version = self.repository.get_version_by_id(version_id)
        if not version:
            return None
        
        # 验证 DAG
        errors = version.dag.validate(
            require_condition_branches=True,
            require_loop_branches=True,
        )
        if errors:
            raise ValueError(f"Cannot publish invalid DAG: {'; '.join(errors)}")
        
        # 验证校验和
        if not self.repository.validate_dag_checksum(version_id):
            raise ValueError("DAG checksum validation failed")
        
        published = self.repository.publish_version(version_id, published_by)
        logger.info(f"[WorkflowVersionService] Published version: {version_id}")
        return published
    
    def deprecate_version(
        self,
        version_id: str,
        deprecated_by: str
    ) -> Optional[WorkflowVersion]:
        """弃用版本"""
        version = self.repository.get_version_by_id(version_id)
        if not version:
            return None
        
        deprecated = self.repository.deprecate_version(version_id, deprecated_by)
        logger.info(f"[WorkflowVersionService] Deprecated version: {version_id}")
        return deprecated
    
    def get_published_version(self, workflow_id: str) -> Optional[WorkflowVersion]:
        """获取已发布版本"""
        return self.repository.get_published_version(workflow_id)
    
    def validate_dag(
        self,
        dag: WorkflowDAG,
        require_condition_branches: bool = False,
        require_loop_branches: bool = False,
    ) -> List[str]:
        """验证 DAG"""
        return dag.validate(
            require_condition_branches=require_condition_branches,
            require_loop_branches=require_loop_branches,
        )
    
    def build_dag(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        entry_node: Optional[str] = None,
        global_config: Optional[Dict[str, Any]] = None
    ) -> WorkflowDAG:
        """构建 DAG"""
        workflow_nodes = [
            WorkflowNode(
                id=node["id"],
                type=node["type"],
                name=node.get("name"),
                description=node.get("description"),
                config=node.get("config", {}),
                position=node.get("position")
            )
            for node in nodes
        ]
        
        workflow_edges = [
            WorkflowEdge(
                from_node=edge["from"],
                to_node=edge["to"],
                source_handle=edge.get("source_handle"),
                target_handle=edge.get("target_handle"),
                condition=edge.get("condition"),
                label=edge.get("label")
            )
            for edge in edges
        ]
        
        return WorkflowDAG(
            nodes=workflow_nodes,
            edges=workflow_edges,
            entry_node=entry_node,
            global_config=global_config or {}
        )
