"""
Workflow Governance Audit Repository (ORM)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid
from sqlalchemy.orm import Session

from core.data.models.workflow import WorkflowGovernanceAuditORM


class WorkflowGovernanceAuditRepository:
    """治理配置变更审计仓库"""

    def __init__(self, db: Session):
        self.db = db

    def create_audit(
        self,
        workflow_id: str,
        changed_by: Optional[str],
        old_config: Dict[str, Any],
        new_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        row = WorkflowGovernanceAuditORM(
            id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            changed_by=changed_by,
            old_config=old_config or {},
            new_config=new_config or {},
            created_at=datetime.utcnow(),
        )
        self.db.add(row)
        self.db.commit()
        return {
            "id": row.id,
            "workflow_id": row.workflow_id,
            "changed_by": row.changed_by,
            "old_config": row.old_config or {},
            "new_config": row.new_config or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def list_audits(
        self,
        workflow_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        rows = (
            self.db.query(WorkflowGovernanceAuditORM)
            .filter(WorkflowGovernanceAuditORM.workflow_id == workflow_id)
            .order_by(WorkflowGovernanceAuditORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [
            {
                "id": r.id,
                "workflow_id": r.workflow_id,
                "changed_by": r.changed_by,
                "old_config": r.old_config or {},
                "new_config": r.new_config or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def count_audits(self, workflow_id: str) -> int:
        return (
            self.db.query(WorkflowGovernanceAuditORM)
            .filter(WorkflowGovernanceAuditORM.workflow_id == workflow_id)
            .count()
        )

