"""
Workflow Control Plane ORM Models

Governance note (AGENTS.md §7):
- Workflow persistence MUST go through the project ORM layer.
- Avoid raw SQL in business modules; repositories should use these ORM models.
"""

from sqlalchemy import Column, String, Text, DateTime, Integer, JSON
from sqlalchemy.sql import func

from core.data.base import Base


class WorkflowORM(Base):
    __tablename__ = "workflows"

    id = Column(String(36), primary_key=True)
    namespace = Column(String(128), nullable=False, default="default", index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    lifecycle_state = Column(String(32), nullable=False, default="draft", index=True)

    latest_version_id = Column(String(36), nullable=True)
    published_version_id = Column(String(36), nullable=True)

    owner_id = Column(String(128), nullable=False, index=True)
    acl = Column(JSON, nullable=False, default=dict)
    tags = Column(JSON, nullable=False, default=list)
    meta_data = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    created_by = Column(String(128), nullable=True)
    updated_by = Column(String(128), nullable=True)


class WorkflowDefinitionORM(Base):
    __tablename__ = "workflow_definitions"

    definition_id = Column(String(36), primary_key=True)
    workflow_id = Column(String(36), nullable=False, index=True)
    description = Column(Text, nullable=True)
    change_log = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    created_by = Column(String(128), nullable=True)
    source_version_id = Column(String(36), nullable=True)


class WorkflowVersionORM(Base):
    __tablename__ = "workflow_versions"

    version_id = Column(String(36), primary_key=True)
    workflow_id = Column(String(36), nullable=False, index=True)
    definition_id = Column(String(36), nullable=False, index=True)
    version_number = Column(String(32), nullable=False)

    dag_json = Column(Text, nullable=False)  # serialized DAG
    checksum = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False, default="draft", index=True)

    description = Column(Text, nullable=True)
    change_notes = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    created_by = Column(String(128), nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(String(128), nullable=True)


class WorkflowExecutionORM(Base):
    __tablename__ = "workflow_executions"

    execution_id = Column(String(36), primary_key=True)
    workflow_id = Column(String(36), nullable=False, index=True)
    version_id = Column(String(36), nullable=False, index=True)
    graph_instance_id = Column(String(36), nullable=True, index=True)

    state = Column(String(32), nullable=False, default="pending", index=True)

    input_data = Column(JSON, nullable=False, default=dict)
    output_data = Column(JSON, nullable=True)
    global_context = Column(JSON, nullable=False, default=dict)
    node_states_json = Column(Text, nullable=False, default="[]")

    triggered_by = Column(String(128), nullable=True)
    trigger_type = Column(String(32), nullable=True)

    resource_quota = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    error_details = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now(), index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    queue_position = Column(Integer, nullable=True)
    queued_at = Column(DateTime, nullable=True)
    wait_duration_ms = Column(Integer, nullable=True)


class WorkflowGovernanceAuditORM(Base):
    __tablename__ = "workflow_governance_audits"

    id = Column(String(36), primary_key=True)
    workflow_id = Column(String(36), nullable=False, index=True)
    changed_by = Column(String(128), nullable=True, index=True)
    old_config = Column(JSON, nullable=False, default=dict)
    new_config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=func.now(), index=True)
