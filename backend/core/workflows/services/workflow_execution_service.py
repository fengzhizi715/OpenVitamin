"""
Workflow Execution Service

WorkflowExecution 的业务逻辑层。
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from core.workflows.models import (
    WorkflowExecution,
    WorkflowExecutionState,
    WorkflowExecutionNode,
    WorkflowExecutionCreateRequest
)
from core.workflows.repository import WorkflowExecutionRepository, WorkflowVersionRepository
from core.workflows.governance.execution_manager import ExecutionManager
from config.settings import settings
from log import logger


class WorkflowExecutionService:
    """Workflow 执行业务服务"""
    _draft_fallback_warn_ts_by_workflow: Dict[str, float] = {}
    
    def __init__(self, db: Session, execution_manager: Optional[ExecutionManager] = None):
        self.db = db
        self.repository = WorkflowExecutionRepository(db)
        self.version_repository = WorkflowVersionRepository(db)
        self.execution_manager = execution_manager

    @staticmethod
    def _allow_draft_execution() -> bool:
        """
        环境分级策略：
        - 显式开启 workflow_allow_draft_execution 时：始终允许
        - 未显式开启时：仅 debug 环境可由 debug override 放开
        """
        allow = bool(getattr(settings, "workflow_allow_draft_execution", False))
        if allow:
            return True
        debug_mode = bool(getattr(settings, "debug", False))
        debug_override = bool(getattr(settings, "workflow_allow_draft_execution_debug_override", True))
        return debug_mode and debug_override
    
    def create_execution(
        self,
        request: WorkflowExecutionCreateRequest,
        triggered_by: Optional[str] = None
    ) -> WorkflowExecution:
        """创建执行"""
        # 获取版本
        if request.version_id:
            version = self.version_repository.get_version_by_id(request.version_id)
        else:
            # 使用已发布版本
            version = self.version_repository.get_published_version(request.workflow_id)
            # 编辑联调场景：若尚未发布版本，回退到最新版本（通常是 draft）
            if not version:
                if not self._allow_draft_execution():
                    raise ValueError(
                        f"No published version for workflow {request.workflow_id}. "
                        "Draft execution is disabled by config."
                    )
                latest_versions = self.version_repository.list_versions_by_workflow(
                    workflow_id=request.workflow_id,
                    limit=1,
                    offset=0,
                )
                version = latest_versions[0] if latest_versions else None
                if version:
                    now_ts = datetime.utcnow().timestamp()
                    last_ts = float(self._draft_fallback_warn_ts_by_workflow.get(request.workflow_id, 0.0) or 0.0)
                    warn_interval_s = float(getattr(settings, "workflow_draft_fallback_warn_interval_seconds", 60.0) or 60.0)
                    if now_ts - last_ts >= max(1.0, warn_interval_s):
                        logger.warning(
                            "[WorkflowExecutionService] No published version for workflow %s, fallback to latest version %s (state=%s)",
                            request.workflow_id,
                            version.version_id,
                            version.state.value,
                        )
                        self._draft_fallback_warn_ts_by_workflow[request.workflow_id] = now_ts
        
        if not version:
            raise ValueError(f"No executable version found for workflow {request.workflow_id}")
        
        # 检查版本是否可执行
        trigger_type = (request.trigger_type or "manual").lower()
        allow_draft_for_manual_run = self._allow_draft_execution() and (
            trigger_type in {"manual", "api", "debug"}
        )
        if not version.can_execute():
            if not (version.state.value == "draft" and allow_draft_for_manual_run):
                raise ValueError(
                    f"Version {version.version_id} is not executable (state: {version.state.value})"
                )

        # 执行前兜底校验：Condition 节点必须具备 true/false 双分支
        # 防止前端边触发配置缺失导致两个分支都被调度。
        preflight_errors = version.dag.validate(
            require_condition_branches=True,
            require_loop_branches=True,
        )
        if preflight_errors:
            raise ValueError(
                "Workflow execution blocked by preflight validation: "
                + "; ".join(preflight_errors)
            )
        
        # 初始化节点状态
        node_states = [
            WorkflowExecutionNode(node_id=node.id)
            for node in version.dag.nodes
        ]
        
        # 创建执行
        execution = WorkflowExecution(
            workflow_id=request.workflow_id,
            version_id=version.version_id,
            state=WorkflowExecutionState.PENDING,
            input_data=request.input_data,
            global_context=request.global_context,
            node_states=node_states,
            triggered_by=triggered_by,
            trigger_type=request.trigger_type
        )
        
        created = self.repository.create(execution)
        logger.info(f"[WorkflowExecutionService] Created execution: {created.execution_id}")
        return created
    
    def get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """获取执行"""
        return self.repository.get_by_id(execution_id)
    
    def list_executions(
        self,
        workflow_id: Optional[str] = None,
        version_id: Optional[str] = None,
        state: Optional[WorkflowExecutionState] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkflowExecution]:
        """列出执行"""
        return self.repository.list_executions(
            workflow_id=workflow_id,
            version_id=version_id,
            state=state,
            limit=limit,
            offset=offset
        )

    def count_executions(
        self,
        workflow_id: Optional[str] = None,
        version_id: Optional[str] = None,
        state: Optional[WorkflowExecutionState] = None,
        trigger_type: Optional[str] = None,
    ) -> int:
        return self.repository.count_executions(
            workflow_id=workflow_id,
            version_id=version_id,
            state=state,
            trigger_type=trigger_type,
        )
    
    def start_execution(
        self,
        execution_id: str,
        graph_instance_id: Optional[str] = None
    ) -> Optional[WorkflowExecution]:
        """开始执行"""
        execution = self.repository.get_by_id(execution_id)
        if not execution:
            return None
        
        # 检查状态
        if execution.state != WorkflowExecutionState.PENDING:
            raise ValueError(f"Cannot start execution in state {execution.state.value}")
        
        # 更新 GraphInstance ID
        if graph_instance_id:
            self.repository.update_graph_instance_id(execution_id, graph_instance_id)
        
        # 更新状态
        updated = self.repository.update_state(
            execution_id,
            WorkflowExecutionState.RUNNING
        )
        
        logger.info(f"[WorkflowExecutionService] Started execution: {execution_id}")
        return updated
    
    def complete_execution(
        self,
        execution_id: str,
        output_data: Optional[Dict[str, Any]] = None
    ) -> Optional[WorkflowExecution]:
        """完成执行"""
        execution = self.repository.get_by_id(execution_id)
        if not execution:
            return None
        
        # 更新输出
        if output_data:
            self.repository.update_output(execution_id, output_data)
        
        # 更新状态
        updated = self.repository.update_state(
            execution_id,
            WorkflowExecutionState.COMPLETED
        )
        
        logger.info(f"[WorkflowExecutionService] Completed execution: {execution_id}")
        return updated
    
    def fail_execution(
        self,
        execution_id: str,
        error_message: str,
        error_details: Optional[Dict[str, Any]] = None
    ) -> Optional[WorkflowExecution]:
        """标记执行失败"""
        execution = self.repository.get_by_id(execution_id)
        if not execution:
            return None
        
        updated = self.repository.update_state(
            execution_id,
            WorkflowExecutionState.FAILED,
            error_message=error_message,
            error_details=error_details
        )
        
        logger.info(f"[WorkflowExecutionService] Failed execution: {execution_id} - {error_message}")
        return updated
    
    def cancel_execution(
        self,
        execution_id: str,
        reason: Optional[str] = None
    ) -> Optional[WorkflowExecution]:
        """取消执行"""
        execution = self.repository.get_by_id(execution_id)
        if not execution:
            return None
        
        if not execution.can_cancel():
            raise ValueError(f"Cannot cancel execution in state {execution.state.value}")
        
        updated = self.repository.update_state(
            execution_id,
            WorkflowExecutionState.CANCELLED,
            error_message=reason
        )
        
        logger.info(f"[WorkflowExecutionService] Cancelled execution: {execution_id}")
        return updated
    
    def update_node_state(
        self,
        execution_id: str,
        node_id: str,
        state: WorkflowExecutionState,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> Optional[WorkflowExecution]:
        """更新节点状态"""
        execution = self.repository.get_by_id(execution_id)
        if not execution:
            return None
        
        # 更新节点状态
        for node in execution.node_states:
            if node.node_id == node_id:
                node.state = state
                if output_data:
                    node.output_data = output_data
                if error_message:
                    node.error_message = error_message
                if state == WorkflowExecutionState.RUNNING and not node.started_at:
                    node.started_at = datetime.utcnow()
                if state in [
                    WorkflowExecutionState.COMPLETED,
                    WorkflowExecutionState.FAILED,
                    WorkflowExecutionState.CANCELLED
                ]:
                    node.finished_at = datetime.utcnow()
                break
        
        updated = self.repository.update_node_states(execution_id, execution.node_states)
        return updated
    
    def get_running_executions(
        self,
        workflow_id: Optional[str] = None
    ) -> List[WorkflowExecution]:
        """获取正在执行的记录"""
        return self.repository.get_running_executions(workflow_id)
    
    def get_execution_stats(
        self,
        workflow_id: str
    ) -> Dict[str, Any]:
        """获取执行统计"""
        stats = {
            "total": self.repository.count_by_state(workflow_id),
            "completed": self.repository.count_by_state(
                workflow_id, WorkflowExecutionState.COMPLETED
            ),
            "failed": self.repository.count_by_state(
                workflow_id, WorkflowExecutionState.FAILED
            ),
            "running": self.repository.count_by_state(
                workflow_id, WorkflowExecutionState.RUNNING
            ),
        }
        return stats
    
    def cleanup_old_executions(
        self,
        workflow_id: str,
        keep_count: int = 100
    ) -> int:
        """清理旧执行记录"""
        deleted = self.repository.delete_old_executions(workflow_id, keep_count)
        logger.info(f"[WorkflowExecutionService] Cleaned up {deleted} old executions for {workflow_id}")
        return deleted

    def delete_execution(self, execution_id: str) -> bool:
        """删除单条执行记录（仅允许终态）"""
        execution = self.repository.get_by_id(execution_id)
        if not execution:
            return False
        if execution.state in {WorkflowExecutionState.PENDING, WorkflowExecutionState.RUNNING}:
            raise ValueError(
                f"Cannot delete execution in state {execution.state.value}; cancel or wait for completion first"
            )
        return self.repository.delete_by_id(execution_id)
