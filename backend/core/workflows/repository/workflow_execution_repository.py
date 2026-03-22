"""
Workflow Execution Repository (ORM)

WorkflowExecution 的 CRUD 操作。

Governance note (AGENTS.md §7):
- 禁止在业务模块里写裸 SQL。
- 所有持久化必须通过项目 ORM 完成。
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import time
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from core.workflows.models import (
    WorkflowExecution,
    WorkflowExecutionState,
    WorkflowExecutionNode,
)
from core.data.models.workflow import WorkflowExecutionORM
from config.settings import settings
from log import logger


class WorkflowExecutionRepository:
    """工作流执行仓库"""

    def __init__(self, db: Session):
        self.db = db

    def _run_write_with_retry(self, op_name: str, fn):
        attempts = max(1, int(getattr(settings, "workflow_db_write_retry_attempts", 4) or 4))
        base_delay_ms = max(1, int(getattr(settings, "workflow_db_write_retry_base_delay_ms", 50) or 50))

        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except OperationalError as e:
                msg = str(e).lower()
                self.db.rollback()
                if "database is locked" not in msg or attempt >= attempts:
                    raise
                sleep_s = (base_delay_ms / 1000.0) * (2 ** (attempt - 1))
                logger.debug(
                    "[WorkflowExecutionRepository] %s retry due to DB lock (%s/%s), sleep=%.3fs",
                    op_name,
                    attempt,
                    attempts,
                    sleep_s,
                )
                time.sleep(sleep_s)

    def _deserialize_from_orm(self, row: WorkflowExecutionORM) -> WorkflowExecution:
        # node_states_json 存的是 JSON 字符串数组（保持与旧 schema 兼容）
        node_states = []
        try:
            import json

            raw = row.node_states_json or "[]"
            node_states_data = json.loads(raw)
            node_states = [WorkflowExecutionNode(**n) for n in (node_states_data or [])]
        except Exception:
            node_states = []

        return WorkflowExecution(
            execution_id=row.execution_id,
            workflow_id=row.workflow_id,
            version_id=row.version_id,
            graph_instance_id=row.graph_instance_id,
            state=WorkflowExecutionState(row.state),
            input_data=row.input_data or {},
            output_data=row.output_data,
            global_context=row.global_context or {},
            node_states=node_states,
            triggered_by=row.triggered_by,
            trigger_type=row.trigger_type,
            resource_quota=row.resource_quota,
            error_message=row.error_message,
            error_details=row.error_details or {},
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_ms=row.duration_ms,
            queue_position=row.queue_position,
            queued_at=row.queued_at,
            wait_duration_ms=row.wait_duration_ms,
        )

    def create(self, execution: WorkflowExecution) -> WorkflowExecution:
        import json

        def _write():
            orm = WorkflowExecutionORM(
                execution_id=execution.execution_id,
                workflow_id=execution.workflow_id,
                version_id=execution.version_id,
                graph_instance_id=execution.graph_instance_id,
                state=execution.state.value,
                input_data=execution.input_data or {},
                output_data=execution.output_data,
                global_context=execution.global_context or {},
                node_states_json=json.dumps([n.model_dump(mode="json") for n in (execution.node_states or [])]),
                triggered_by=execution.triggered_by,
                trigger_type=execution.trigger_type,
                resource_quota=execution.resource_quota,
                error_message=execution.error_message,
                error_details=execution.error_details,
                created_at=execution.created_at,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
                duration_ms=execution.duration_ms,
                queue_position=execution.queue_position,
                queued_at=execution.queued_at,
                wait_duration_ms=execution.wait_duration_ms,
            )
            self.db.add(orm)
            self.db.commit()

        self._run_write_with_retry("create", _write)
        logger.info(f"[WorkflowExecutionRepository] Created execution: {execution.execution_id}")
        return execution

    def get_by_id(self, execution_id: str) -> Optional[WorkflowExecution]:
        row = (
            self.db.query(WorkflowExecutionORM)
            .filter(WorkflowExecutionORM.execution_id == execution_id)
            .first()
        )
        return self._deserialize_from_orm(row) if row else None

    def list_executions(
        self,
        workflow_id: Optional[str] = None,
        version_id: Optional[str] = None,
        state: Optional[WorkflowExecutionState] = None,
        trigger_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[WorkflowExecution]:
        q = self.db.query(WorkflowExecutionORM)
        if workflow_id:
            q = q.filter(WorkflowExecutionORM.workflow_id == workflow_id)
        if version_id:
            q = q.filter(WorkflowExecutionORM.version_id == version_id)
        if state:
            q = q.filter(WorkflowExecutionORM.state == state.value)
        if trigger_type:
            q = q.filter(WorkflowExecutionORM.trigger_type == trigger_type)
        rows = (
            q.order_by(WorkflowExecutionORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._deserialize_from_orm(r) for r in rows]

    def count_executions(
        self,
        workflow_id: Optional[str] = None,
        version_id: Optional[str] = None,
        state: Optional[WorkflowExecutionState] = None,
        trigger_type: Optional[str] = None,
    ) -> int:
        q = self.db.query(WorkflowExecutionORM)
        if workflow_id:
            q = q.filter(WorkflowExecutionORM.workflow_id == workflow_id)
        if version_id:
            q = q.filter(WorkflowExecutionORM.version_id == version_id)
        if state:
            q = q.filter(WorkflowExecutionORM.state == state.value)
        if trigger_type:
            q = q.filter(WorkflowExecutionORM.trigger_type == trigger_type)
        return q.count()

    def update_state(
        self,
        execution_id: str,
        state: WorkflowExecutionState,
        error_message: Optional[str] = None,
        error_details: Optional[Dict[str, Any]] = None,
    ) -> Optional[WorkflowExecution]:
        def _write():
            row = (
                self.db.query(WorkflowExecutionORM)
                .filter(WorkflowExecutionORM.execution_id == execution_id)
                .first()
            )
            if not row:
                return

            row.state = state.value

            # 根据状态更新时间戳
            now = datetime.utcnow()
            if state == WorkflowExecutionState.RUNNING and row.started_at is None:
                row.started_at = now
            if state in {
                WorkflowExecutionState.COMPLETED,
                WorkflowExecutionState.FAILED,
                WorkflowExecutionState.CANCELLED,
                WorkflowExecutionState.TIMEOUT,
            }:
                if row.finished_at is None:
                    row.finished_at = now

            if error_message is not None:
                row.error_message = error_message
            elif state in {
                WorkflowExecutionState.RUNNING,
                WorkflowExecutionState.COMPLETED,
                WorkflowExecutionState.FAILED,
                WorkflowExecutionState.CANCELLED,
                WorkflowExecutionState.TIMEOUT,
            }:
                # 进入运行态或终态时，若调用方未显式传入错误信息，则清理历史错误，避免陈旧信息残留。
                row.error_message = None
            if error_details is not None:
                row.error_details = error_details
            elif state in {
                WorkflowExecutionState.RUNNING,
                WorkflowExecutionState.COMPLETED,
                WorkflowExecutionState.FAILED,
                WorkflowExecutionState.CANCELLED,
                WorkflowExecutionState.TIMEOUT,
            }:
                row.error_details = None

            # duration_ms 计算
            if row.started_at and row.finished_at:
                row.duration_ms = int((row.finished_at - row.started_at).total_seconds() * 1000)

            self.db.commit()

        existing = self.get_by_id(execution_id)
        if not existing:
            return None
        self._run_write_with_retry("update_state", _write)
        logger.info(f"[WorkflowExecutionRepository] Updated execution state: {execution_id} -> {state.value}")
        return self.get_by_id(execution_id)

    def update_node_states(
        self,
        execution_id: str,
        node_states: List[WorkflowExecutionNode],
    ) -> Optional[WorkflowExecution]:
        import json

        existing = self.get_by_id(execution_id)
        if not existing:
            return None

        def _write():
            row = (
                self.db.query(WorkflowExecutionORM)
                .filter(WorkflowExecutionORM.execution_id == execution_id)
                .first()
            )
            if not row:
                return
            # use JSON mode to convert datetime/enum into serializable primitives
            row.node_states_json = json.dumps(
                [n.model_dump(mode="json") for n in (node_states or [])]
            )
            self.db.commit()

        self._run_write_with_retry("update_node_states", _write)
        return self.get_by_id(execution_id)

    def update_output(self, execution_id: str, output_data: Dict[str, Any]) -> Optional[WorkflowExecution]:
        existing = self.get_by_id(execution_id)
        if not existing:
            return None

        def _write():
            row = (
                self.db.query(WorkflowExecutionORM)
                .filter(WorkflowExecutionORM.execution_id == execution_id)
                .first()
            )
            if not row:
                return
            row.output_data = output_data
            self.db.commit()

        self._run_write_with_retry("update_output", _write)
        return self.get_by_id(execution_id)

    def update_queue_metrics(
        self,
        execution_id: str,
        *,
        queue_position: Optional[int] = None,
        queued_at: Optional[datetime] = None,
        wait_duration_ms: Optional[int] = None,
    ) -> Optional[WorkflowExecution]:
        existing = self.get_by_id(execution_id)
        if not existing:
            return None

        def _write():
            row = (
                self.db.query(WorkflowExecutionORM)
                .filter(WorkflowExecutionORM.execution_id == execution_id)
                .first()
            )
            if not row:
                return
            if queue_position is not None:
                row.queue_position = int(queue_position)
            if queued_at is not None:
                row.queued_at = queued_at
            if wait_duration_ms is not None:
                row.wait_duration_ms = int(wait_duration_ms)
            self.db.commit()

        self._run_write_with_retry("update_queue_metrics", _write)
        return self.get_by_id(execution_id)

    def update_graph_instance_id(self, execution_id: str, graph_instance_id: str) -> Optional[WorkflowExecution]:
        existing = self.get_by_id(execution_id)
        if not existing:
            return None

        def _write():
            row = (
                self.db.query(WorkflowExecutionORM)
                .filter(WorkflowExecutionORM.execution_id == execution_id)
                .first()
            )
            if not row:
                return
            row.graph_instance_id = graph_instance_id
            self.db.commit()

        self._run_write_with_retry("update_graph_instance_id", _write)
        return self.get_by_id(execution_id)

    def get_running_executions(self, workflow_id: Optional[str] = None) -> List[WorkflowExecution]:
        q = self.db.query(WorkflowExecutionORM).filter(
            WorkflowExecutionORM.state == WorkflowExecutionState.RUNNING.value
        )
        if workflow_id:
            q = q.filter(WorkflowExecutionORM.workflow_id == workflow_id)
        rows = q.order_by(WorkflowExecutionORM.started_at.desc()).all()
        return [self._deserialize_from_orm(r) for r in rows]

    def count_by_state(self, workflow_id: str, state: Optional[WorkflowExecutionState] = None) -> int:
        q = self.db.query(WorkflowExecutionORM).filter(WorkflowExecutionORM.workflow_id == workflow_id)
        if state:
            q = q.filter(WorkflowExecutionORM.state == state.value)
        return q.count()

    def delete_old_executions(self, workflow_id: str, keep_count: int = 100) -> int:
        # keep newest N by created_at
        rows = (
            self.db.query(WorkflowExecutionORM.execution_id)
            .filter(WorkflowExecutionORM.workflow_id == workflow_id)
            .order_by(WorkflowExecutionORM.created_at.desc())
            .offset(keep_count)
            .all()
        )
        ids = [r[0] for r in rows]
        if not ids:
            return 0
        deleted = 0

        def _write():
            nonlocal deleted
            deleted = (
                self.db.query(WorkflowExecutionORM)
                .filter(WorkflowExecutionORM.execution_id.in_(ids))
                .delete(synchronize_session=False)
            )
            self.db.commit()

        self._run_write_with_retry("delete_old_executions", _write)
        logger.info(f"[WorkflowExecutionRepository] Deleted {deleted} old executions for workflow: {workflow_id}")
        return int(deleted or 0)

    def delete_by_id(self, execution_id: str) -> bool:
        existing = self.get_by_id(execution_id)
        if not existing:
            return False

        deleted = 0

        def _write():
            nonlocal deleted
            deleted = (
                self.db.query(WorkflowExecutionORM)
                .filter(WorkflowExecutionORM.execution_id == execution_id)
                .delete(synchronize_session=False)
            )
            self.db.commit()

        self._run_write_with_retry("delete_by_id", _write)
        if deleted:
            logger.info(f"[WorkflowExecutionRepository] Deleted execution: {execution_id}")
        return bool(deleted)
