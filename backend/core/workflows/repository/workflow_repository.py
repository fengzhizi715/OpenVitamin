"""
Workflow Repository

Workflow 资源的 CRUD 操作（ORM 版本）。

Governance note (AGENTS.md §7):
- 禁止在业务模块里写裸 SQL。
- 所有持久化必须通过项目 ORM/数据层抽象完成。
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import time
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from core.workflows.models import Workflow, WorkflowLifecycleState
from core.data.models.workflow import WorkflowORM
from config.settings import settings
from log import logger


class WorkflowRepository:
    """Workflow 资源仓库"""

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
                    "[WorkflowRepository] %s retry due to DB lock (%s/%s), sleep=%.3fs",
                    op_name,
                    attempt,
                    attempts,
                    sleep_s,
                )
                time.sleep(sleep_s)

    def _deserialize_from_orm(self, row: WorkflowORM) -> Workflow:
        return Workflow(
            id=row.id,
            namespace=row.namespace,
            name=row.name,
            description=row.description,
            lifecycle_state=WorkflowLifecycleState(row.lifecycle_state),
            latest_version_id=row.latest_version_id,
            published_version_id=row.published_version_id,
            owner_id=row.owner_id,
            acl=row.acl or {},
            tags=row.tags or [],
            metadata=row.meta_data or {},
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            updated_by=row.updated_by,
        )

    def create(self, workflow: Workflow) -> Workflow:
        def _write():
            orm = WorkflowORM(
                id=workflow.id,
                namespace=workflow.namespace,
                name=workflow.name,
                description=workflow.description,
                lifecycle_state=workflow.lifecycle_state.value,
                latest_version_id=workflow.latest_version_id,
                published_version_id=workflow.published_version_id,
                owner_id=workflow.owner_id,
                acl=workflow.acl or {},
                tags=workflow.tags or [],
                meta_data=workflow.metadata or {},
                created_at=workflow.created_at,
                updated_at=workflow.updated_at,
                created_by=workflow.created_by,
                updated_by=workflow.updated_by,
            )
            self.db.add(orm)
            self.db.commit()

        self._run_write_with_retry("create", _write)
        logger.info(f"[WorkflowRepository] Created workflow: {workflow.id}")
        return workflow

    def get_by_id(self, workflow_id: str) -> Optional[Workflow]:
        row = (
            self.db.query(WorkflowORM)
            .filter(
                WorkflowORM.id == workflow_id,
                WorkflowORM.lifecycle_state != WorkflowLifecycleState.DELETED.value,
            )
            .first()
        )
        return self._deserialize_from_orm(row) if row else None

    def get_by_namespace_and_name(self, namespace: str, name: str) -> Optional[Workflow]:
        row = (
            self.db.query(WorkflowORM)
            .filter(
                WorkflowORM.namespace == namespace,
                WorkflowORM.name == name,
                WorkflowORM.lifecycle_state != WorkflowLifecycleState.DELETED.value,
            )
            .first()
        )
        return self._deserialize_from_orm(row) if row else None

    def list_workflows(
        self,
        namespace: Optional[str] = None,
        owner_id: Optional[str] = None,
        lifecycle_state: Optional[WorkflowLifecycleState] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Workflow]:
        q = self.db.query(WorkflowORM).filter(
            WorkflowORM.lifecycle_state != WorkflowLifecycleState.DELETED.value
        )
        if namespace:
            q = q.filter(WorkflowORM.namespace == namespace)
        if owner_id:
            q = q.filter(WorkflowORM.owner_id == owner_id)
        if lifecycle_state:
            q = q.filter(WorkflowORM.lifecycle_state == lifecycle_state.value)

        # tags filter intentionally omitted (SQLite JSON portability varies)
        _ = tags

        rows = (
            q.order_by(WorkflowORM.updated_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._deserialize_from_orm(r) for r in rows]

    def count_workflows(
        self,
        namespace: Optional[str] = None,
        owner_id: Optional[str] = None,
        lifecycle_state: Optional[WorkflowLifecycleState] = None,
        tags: Optional[List[str]] = None,
    ) -> int:
        q = self.db.query(WorkflowORM).filter(
            WorkflowORM.lifecycle_state != WorkflowLifecycleState.DELETED.value
        )
        if namespace:
            q = q.filter(WorkflowORM.namespace == namespace)
        if owner_id:
            q = q.filter(WorkflowORM.owner_id == owner_id)
        if lifecycle_state:
            q = q.filter(WorkflowORM.lifecycle_state == lifecycle_state.value)
        _ = tags
        return q.count()

    def update(
        self,
        workflow_id: str,
        updates: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> Optional[Workflow]:
        row = self.db.query(WorkflowORM).filter(WorkflowORM.id == workflow_id).first()
        if not row:
            return None

        updates = dict(updates or {})
        updates["updated_at"] = datetime.utcnow()
        if updated_by:
            updates["updated_by"] = updated_by

        if "lifecycle_state" in updates and isinstance(updates["lifecycle_state"], WorkflowLifecycleState):
            updates["lifecycle_state"] = updates["lifecycle_state"].value

        allowed = {
            "namespace",
            "name",
            "description",
            "lifecycle_state",
            "latest_version_id",
            "published_version_id",
            "owner_id",
            "acl",
            "tags",
            "meta_data",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        }
        for k, v in updates.items():
            if k in allowed:
                setattr(row, k, v)
            # Handle mapping from domain model 'metadata' to ORM 'meta_data'
            if k == "metadata" and "meta_data" in allowed:
                setattr(row, "meta_data", v)

        self._run_write_with_retry("update", lambda: self.db.commit())
        logger.info(f"[WorkflowRepository] Updated workflow: {workflow_id}")
        return self.get_by_id(workflow_id)

    def update_version_refs(
        self,
        workflow_id: str,
        latest_version_id: Optional[str] = None,
        published_version_id: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> Optional[Workflow]:
        updates: Dict[str, Any] = {}
        if latest_version_id is not None:
            updates["latest_version_id"] = latest_version_id
        if published_version_id is not None:
            updates["published_version_id"] = published_version_id
        return self.update(workflow_id, updates, updated_by=updated_by)

    def delete(self, workflow_id: str, soft: bool = True) -> bool:
        row = self.db.query(WorkflowORM).filter(WorkflowORM.id == workflow_id).first()
        if not row:
            return False

        if soft:
            row.lifecycle_state = WorkflowLifecycleState.DELETED.value
            row.updated_at = datetime.utcnow()
        else:
            self.db.delete(row)

        self._run_write_with_retry("delete", lambda: self.db.commit())
        logger.info(f"[WorkflowRepository] Deleted workflow: {workflow_id} (soft={soft})")
        return True

    def exists(self, workflow_id: str) -> bool:
        row = (
            self.db.query(WorkflowORM.id)
            .filter(
                WorkflowORM.id == workflow_id,
                WorkflowORM.lifecycle_state != WorkflowLifecycleState.DELETED.value,
            )
            .first()
        )
        return row is not None

    def count_by_namespace(self, namespace: str) -> int:
        return (
            self.db.query(WorkflowORM)
            .filter(
                WorkflowORM.namespace == namespace,
                WorkflowORM.lifecycle_state != WorkflowLifecycleState.DELETED.value,
            )
            .count()
        )
