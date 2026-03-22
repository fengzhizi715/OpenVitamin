"""
Workflow API Endpoints

Workflow Control Plane 的 REST API 接口。
"""

from typing import List, Optional, Dict, Any
import asyncio
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from core.workflows.models import (
    Workflow,
    WorkflowVersion,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionNode,
    WorkflowExecutionNodeState,
    WorkflowLifecycleState,
    WorkflowVersionState,
    WorkflowExecutionState,
    WorkflowDAG,
    WorkflowNode,
    WorkflowEdge,
    WorkflowCreateRequest,
    WorkflowUpdateRequest,
    WorkflowExecutionCreateRequest
)
from core.workflows.services import (
    WorkflowService,
    WorkflowVersionService,
    WorkflowExecutionService
)
from core.workflows.repository import WorkflowGovernanceAuditRepository
from core.workflows.governance import get_execution_manager, QuotaConfig
from core.workflows.runtime import WorkflowRuntime
from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter
from config.settings import settings
from middleware.user_context import get_current_user
from core.data.base import get_db, SessionLocal
from log import logger
from execution_kernel.persistence.db import Database
from execution_kernel.events.event_store import EventStore
from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.events.event_types import ExecutionEventType

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])
_WORKFLOW_BG_TASKS: set[asyncio.Task] = set()
_WORKFLOW_BG_TASK_BY_EXECUTION: Dict[str, asyncio.Task] = {}
_TERMINAL_RECONCILE_LOCK_UNTIL: Dict[str, datetime] = {}


# ==================== Response Models ====================

class WorkflowResponse(BaseModel):
    id: str
    namespace: str
    name: str
    description: Optional[str]
    lifecycle_state: str
    latest_version_id: Optional[str]
    published_version_id: Optional[str]
    owner_id: str
    tags: List[str]
    created_at: str
    updated_at: str


class WorkflowVersionResponse(BaseModel):
    version_id: str
    workflow_id: str
    version_number: str
    state: str
    description: Optional[str]
    created_by: Optional[str]
    published_by: Optional[str]
    created_at: str
    published_at: Optional[str]


class WorkflowExecutionResponse(BaseModel):
    execution_id: str
    workflow_id: str
    version_id: str
    state: str
    graph_instance_id: Optional[str] = None
    input_data: Dict[str, Any]
    output_data: Optional[Dict[str, Any]]
    global_context: Dict[str, Any] = Field(default_factory=dict)
    trigger_type: str = "manual"
    triggered_by: Optional[str] = None
    error_message: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    duration_ms: Optional[int]
    queue_position: Optional[int] = None
    queued_at: Optional[str] = None
    wait_duration_ms: Optional[int] = None
    node_states: List[Dict[str, Any]] = Field(default_factory=list)
    node_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    replay: Dict[str, Any] = Field(default_factory=dict)
    agent_summaries: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowExecutionStatusResponse(BaseModel):
    execution_id: str
    workflow_id: str
    version_id: str
    state: str
    started_at: Optional[str]
    finished_at: Optional[str]
    duration_ms: Optional[int]
    queue_position: Optional[int] = None
    wait_duration_ms: Optional[int] = None
    node_timeline: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowGovernanceConfigRequest(BaseModel):
    max_queue_size: Optional[int] = Field(default=None, ge=1, le=10000)
    backpressure_strategy: Optional[str] = Field(default=None, description="wait or reject")


class ListResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


def _extract_idempotency_key(http_request: Request) -> Optional[str]:
    key = (
        http_request.headers.get("Idempotency-Key")
        or http_request.headers.get("X-Idempotency-Key")
        or http_request.headers.get("X-Request-Id")
    )
    if not key:
        return None
    key = key.strip()
    return key[:256] if key else None


# ==================== Workflow Endpoints ====================

@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: WorkflowCreateRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """创建工作流"""
    service = WorkflowService(db)
    try:
        workflow = service.create_workflow(request, current_user)
        return _workflow_to_response(workflow)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """获取工作流"""
    service = WorkflowService(db)
    workflow = service.get_workflow(workflow_id)
    
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    return _workflow_to_response(workflow)


@router.get("", response_model=ListResponse)
async def list_workflows(
    namespace: Optional[str] = None,
    lifecycle_state: Optional[WorkflowLifecycleState] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """列出工作流"""
    service = WorkflowService(db)
    workflows = service.list_workflows(
        namespace=namespace,
        owner_id=current_user,
        lifecycle_state=lifecycle_state,
        limit=limit,
        offset=offset
    )
    total = service.count_workflows(
        namespace=namespace,
        owner_id=current_user,
        lifecycle_state=lifecycle_state,
    )
    
    return ListResponse(
        items=[_workflow_to_response(w).model_dump() for w in workflows],
        total=total,
        limit=limit,
        offset=offset
    )


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    request: WorkflowUpdateRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """更新工作流"""
    service = WorkflowService(db)
    
    try:
        workflow = service.update_workflow(workflow_id, request, current_user)
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        return _workflow_to_response(workflow)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    hard: bool = Query(default=False, description="Hard delete"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """删除工作流"""
    service = WorkflowService(db)
    
    try:
        result = service.delete_workflow(workflow_id, current_user, soft=not hard)
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/{workflow_id}/publish", response_model=WorkflowResponse)
async def publish_workflow(
    workflow_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """发布工作流"""
    service = WorkflowService(db)
    
    try:
        workflow = service.publish_workflow(workflow_id, version_id, current_user)
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        return _workflow_to_response(workflow)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# ==================== Version Endpoints ====================

class WorkflowVersionCreateBody(BaseModel):
    dag: WorkflowDAG
    version_number: Optional[str] = None
    description: Optional[str] = None


class WorkflowVersionRollbackBody(BaseModel):
    publish: bool = True
    description: Optional[str] = None


@router.post("/{workflow_id}/versions", response_model=WorkflowVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_version(
    workflow_id: str,
    request: WorkflowVersionCreateBody,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """创建工作流版本"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # 创建定义
    version_service = WorkflowVersionService(db)
    definition = version_service.create_definition(
        workflow_id=workflow_id,
        description=request.description,
        created_by=current_user
    )
    
    # 创建版本
    try:
        version = version_service.create_version(
            workflow_id=workflow_id,
            definition_id=definition.definition_id,
            dag=request.dag,
            version_number=request.version_number,
            description=request.description,
            created_by=current_user
        )
        
        # 更新工作流的 latest_version_id
        workflow_service.repository.update(
            workflow_id,
            {"latest_version_id": version.version_id},
            current_user,
        )
        
        return _version_to_response(version)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{workflow_id}/versions", response_model=ListResponse)
async def list_versions(
    workflow_id: str,
    state: Optional[WorkflowVersionState] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """列出工作流版本"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    version_service = WorkflowVersionService(db)
    versions = version_service.list_versions(
        workflow_id=workflow_id,
        state=state,
        limit=limit,
        offset=offset
    )
    total = version_service.count_versions(
        workflow_id=workflow_id,
        state=state,
    )
    
    return ListResponse(
        items=[_version_to_response(v).model_dump() for v in versions],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/{workflow_id}/versions/{version_id}", response_model=Dict[str, Any])
async def get_version(
    workflow_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """获取版本详情（包含 DAG）"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    version_service = WorkflowVersionService(db)
    version = version_service.get_version(version_id)
    
    if not version or version.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    
    return {
        **_version_to_response(version).model_dump(),
        "dag": version.dag.model_dump(),
        "checksum": version.checksum
    }


@router.get("/{workflow_id}/versions/compare", response_model=Dict[str, Any])
async def diff_versions(
    workflow_id: str,
    from_version_id: str = Query(..., description="Base version id"),
    to_version_id: str = Query(..., description="Target version id"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """比较两个版本的 DAG 差异"""
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    version_service = WorkflowVersionService(db)
    from_version = version_service.get_version(from_version_id)
    to_version = version_service.get_version(to_version_id)

    if not from_version or from_version.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="from_version not found")
    if not to_version or to_version.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="to_version not found")

    from_nodes = {n.id: n for n in from_version.dag.nodes}
    to_nodes = {n.id: n for n in to_version.dag.nodes}

    from_node_ids = set(from_nodes.keys())
    to_node_ids = set(to_nodes.keys())

    added_nodes = sorted(list(to_node_ids - from_node_ids))
    removed_nodes = sorted(list(from_node_ids - to_node_ids))
    changed_nodes = sorted([
        node_id
        for node_id in (from_node_ids & to_node_ids)
        if from_nodes[node_id].model_dump(mode="json") != to_nodes[node_id].model_dump(mode="json")
    ])

    def edge_key(edge: WorkflowEdge) -> str:
        return (
            f"{edge.from_node}->{edge.to_node}"
            f"|{edge.source_handle or ''}|{edge.target_handle or ''}"
            f"|{edge.label or ''}|{edge.condition or ''}"
        )

    from_edges_map = {edge_key(e): e for e in from_version.dag.edges}
    to_edges_map = {edge_key(e): e for e in to_version.dag.edges}

    from_edge_keys = set(from_edges_map.keys())
    to_edge_keys = set(to_edges_map.keys())

    added_edges = sorted(list(to_edge_keys - from_edge_keys))
    removed_edges = sorted(list(from_edge_keys - to_edge_keys))

    return {
        "workflow_id": workflow_id,
        "from_version_id": from_version_id,
        "to_version_id": to_version_id,
        "summary": {
            "node_added": len(added_nodes),
            "node_removed": len(removed_nodes),
            "node_changed": len(changed_nodes),
            "edge_added": len(added_edges),
            "edge_removed": len(removed_edges),
        },
        "nodes": {
            "added": added_nodes,
            "removed": removed_nodes,
            "changed": changed_nodes,
        },
        "edges": {
            "added": added_edges,
            "removed": removed_edges,
        },
    }


@router.post("/{workflow_id}/versions/{version_id}/publish", response_model=WorkflowVersionResponse)
async def publish_version(
    workflow_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """发布版本"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "publish"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    version_service = WorkflowVersionService(db)
    
    try:
        version = version_service.publish_version(version_id, current_user)
        if not version or version.workflow_id != workflow_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
        return _version_to_response(version)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{workflow_id}/versions/{version_id}/rollback", response_model=WorkflowVersionResponse)
async def rollback_version(
    workflow_id: str,
    version_id: str,
    body: WorkflowVersionRollbackBody,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """基于历史版本创建回滚版本（可选自动发布）"""
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "publish"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    version_service = WorkflowVersionService(db)
    source = version_service.get_version(version_id)
    if not source or source.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    definition = version_service.create_definition(
        workflow_id=workflow_id,
        description=body.description or f"Rollback from version {source.version_number}",
        source_version_id=source.version_id,
        created_by=current_user,
    )

    rollback_version = version_service.create_version(
        workflow_id=workflow_id,
        definition_id=definition.definition_id,
        dag=source.dag,
        version_number=None,
        description=body.description or f"Rollback from version {source.version_number}",
        change_notes=f"rollback:{source.version_id}",
        created_by=current_user,
    )

    workflow_service.repository.update(
        workflow_id,
        {"latest_version_id": rollback_version.version_id},
        current_user,
    )

    if body.publish:
        published = version_service.publish_version(rollback_version.version_id, current_user)
        if not published:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Rollback publish failed")
        workflow_service.repository.update(
            workflow_id,
            {
                "published_version_id": published.version_id,
                "lifecycle_state": WorkflowLifecycleState.ACTIVE,
            },
            current_user,
        )
        return _version_to_response(published)

    return _version_to_response(rollback_version)


# ==================== Execution Endpoints ====================

@router.post("/{workflow_id}/executions", response_model=WorkflowExecutionResponse, status_code=status.HTTP_201_CREATED)
async def create_execution(
    workflow_id: str,
    request: WorkflowExecutionCreateRequest,
    wait: Optional[bool] = Query(default=None, description="Wait for completion"),
    wait_timeout_seconds: Optional[int] = Query(
        default=None,
        ge=1,
        description="wait=true 时的同步等待超时（秒）",
    ),
    http_request: Request = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """创建并执行工作流"""
    if request.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"workflow_id mismatch: path={workflow_id} body={request.workflow_id}",
        )

    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "execute"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # 幂等键：相同 key 的重复提交直接返回已有 execution（避免双击/重试创建多次）
    idem_key = _extract_idempotency_key(http_request) if http_request else None

    # 创建执行
    execution_service = WorkflowExecutionService(db)
    if idem_key:
        recent = execution_service.list_executions(
            workflow_id=workflow_id,
            limit=50,
            offset=0,
        )
        for ex in recent:
            gctx = ex.global_context or {}
            if (
                str(gctx.get("__idempotency_key") or "").strip() == idem_key
                and str(ex.triggered_by or "").strip() == str(current_user or "").strip()
            ):
                logger.info(
                    f"[WorkflowAPI] Idempotent create hit: workflow_id={workflow_id} "
                    f"execution_id={ex.execution_id}"
                )
                ex = await _hydrate_execution_live_from_kernel(ex)
                node_timeline_override = None
                if ex.graph_instance_id:
                    node_timeline_override = await _node_timeline_from_event_store(ex.graph_instance_id)
                return _execution_to_response(ex, node_timeline_override=node_timeline_override)
    
    try:
        global_ctx = dict(request.global_context or {})
        if idem_key:
            global_ctx["__idempotency_key"] = idem_key
        create_req = WorkflowExecutionCreateRequest(
            workflow_id=request.workflow_id,
            version_id=request.version_id,
            input_data=request.input_data,
            global_context=global_ctx,
            trigger_type=request.trigger_type,
        )
        execution = execution_service.create_execution(create_req, current_user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    effective_wait = wait
    if effective_wait is None:
        effective_wait = bool(getattr(settings, "workflow_execution_wait_default", False))

    # 执行
    if effective_wait:
        execution_manager = get_execution_manager()
        runtime = WorkflowRuntime(db, execution_manager)
        default_timeout = max(1, int(getattr(settings, "workflow_wait_timeout_seconds", 120) or 120))
        max_timeout = max(default_timeout, int(getattr(settings, "workflow_wait_timeout_max_seconds", 3600) or 3600))
        requested_timeout = int(wait_timeout_seconds) if wait_timeout_seconds is not None else default_timeout
        effective_wait_timeout = max(1, min(requested_timeout, max_timeout))
        
        try:
            execution = await runtime.execute(
                execution,
                wait_for_completion=True,
                wait_timeout_seconds=effective_wait_timeout,
            )
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    else:
        # 异步模式：在后台真正启动执行（不能依赖当前 request 的 db session 生命周期）。
        async def _run_execution_background(exec_id: str) -> None:
            logger.info(f"[WorkflowAPI] Background run start: execution_id={exec_id}")
            db_bg: Session = SessionLocal()
            try:
                execution_service_bg = WorkflowExecutionService(db_bg)
                exec_obj = execution_service_bg.get_execution(exec_id)
                if not exec_obj:
                    logger.error(f"[WorkflowAPI] Background run skipped: execution not found {exec_id}")
                    return
                # 取消/终态执行不应再启动，避免跨进程下“已取消又被启动”。
                if exec_obj.is_terminal():
                    logger.info(
                        f"[WorkflowAPI] Background run skipped: execution already terminal "
                        f"{exec_id} state={exec_obj.state.value}"
                    )
                    return
                runtime_bg = WorkflowRuntime(db_bg, get_execution_manager())
                # 在后台任务里完整执行，避免 wait_for_completion=False 时 db session 过早关闭。
                final_exec = await runtime_bg.execute(exec_obj, wait_for_completion=True)
                logger.info(
                    f"[WorkflowAPI] Background run finished: execution_id={exec_id} state={final_exec.state}"
                )
            except asyncio.CancelledError:
                logger.info(f"[WorkflowAPI] Background run cancelled: execution_id={exec_id}")
                try:
                    runtime_bg = WorkflowRuntime(db_bg, get_execution_manager())
                    await runtime_bg.cancel(exec_id)
                except Exception as e:
                    logger.warning(f"[WorkflowAPI] Background cancel cleanup failed: execution_id={exec_id} error={e}")
                raise
            except Exception as e:
                logger.error(f"[WorkflowAPI] Background run failed: execution_id={exec_id} error={e}")
            finally:
                db_bg.close()

        # 优先直接投递事件循环，避免依赖 BackgroundTasks 触发时机导致 execution 长期停留 pending。
        try:
            task = asyncio.create_task(_run_execution_background(execution.execution_id))
            _WORKFLOW_BG_TASKS.add(task)
            _WORKFLOW_BG_TASK_BY_EXECUTION[execution.execution_id] = task
            def _on_done(t: asyncio.Task, exec_id: str = execution.execution_id) -> None:
                _WORKFLOW_BG_TASKS.discard(t)
                if _WORKFLOW_BG_TASK_BY_EXECUTION.get(exec_id) is t:
                    _WORKFLOW_BG_TASK_BY_EXECUTION.pop(exec_id, None)
            task.add_done_callback(_on_done)
        except RuntimeError:
            # 兜底：无 running loop 时退回 Starlette BackgroundTasks。
            if background_tasks is None:
                raise
            background_tasks.add_task(_run_execution_background, execution.execution_id)
    
    return _execution_to_response(execution)


@router.get("/{workflow_id}/executions", response_model=ListResponse)
async def list_executions(
    workflow_id: str,
    state: Optional[WorkflowExecutionState] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    live: bool = Query(default=True, description="实时对齐执行状态（从内核视图回填）"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """列出执行记录"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    execution_service = WorkflowExecutionService(db)
    executions = execution_service.list_executions(
        workflow_id=workflow_id,
        state=state,
        limit=limit,
        offset=offset
    )
    total = execution_service.count_executions(
        workflow_id=workflow_id,
        state=state,
    )

    if live and executions:
        hydrated = []
        for e in executions:
            item = e
            try:
                if e.state in {WorkflowExecutionState.PENDING, WorkflowExecutionState.RUNNING}:
                    item = await _hydrate_execution_live_from_kernel(e)
                    item = _maybe_persist_terminal_reconcile(execution_service, item)
            except Exception as ex:
                logger.debug(
                    f"[WorkflowAPI] list live hydrate skipped: execution_id={e.execution_id} err={ex}"
                )
            hydrated.append(item)
        executions = hydrated
    
    return ListResponse(
        items=[_execution_to_response(e).model_dump() for e in executions],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/{workflow_id}/executions/{execution_id}", response_model=WorkflowExecutionResponse)
async def get_execution(
    workflow_id: str,
    execution_id: str,
    reconcile: bool = Query(default=False, description="Force terminal reconcile write-back"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """获取执行详情"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id)
    
    if not execution or execution.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    execution = await _hydrate_execution_live_from_kernel(execution)
    if reconcile:
        execution = _maybe_persist_terminal_reconcile(execution_service, execution)
    node_timeline_override = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)
    return _execution_to_response(execution, node_timeline_override=node_timeline_override)


@router.delete("/{workflow_id}/executions/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_execution(
    workflow_id: str,
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除单个执行历史（仅允许终态）"""
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    try:
        deleted = execution_service.delete_execution(execution_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workflow_id}/executions/{execution_id}/status", response_model=WorkflowExecutionStatusResponse)
async def get_execution_status(
    workflow_id: str,
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """获取轻量执行状态（用于运行页高频轮询）"""
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    execution = await _hydrate_execution_live_from_kernel(execution)
    execution = _maybe_persist_terminal_reconcile(execution_service, execution)
    node_timeline_override = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)
    return _execution_to_status_response(execution, node_timeline_override=node_timeline_override)


@router.get("/{workflow_id}/executions/{execution_id}/stream")
async def stream_execution_status(
    workflow_id: str,
    execution_id: str,
    interval_ms: int = Query(default=900, ge=300, le=5000, description="SSE 推送间隔（毫秒）"),
    current_user: str = Depends(get_current_user),
):
    """SSE 推送执行状态（节点级），前端可替代高频轮询；轮询仍可作为降级路径。"""
    init_db = SessionLocal()
    try:
        workflow_service = WorkflowService(init_db)
        workflow = workflow_service.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        if not workflow.has_permission(current_user, "read"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        execution_service = WorkflowExecutionService(init_db)
        execution = execution_service.get_execution(execution_id)
        if not execution or execution.workflow_id != workflow_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    finally:
        init_db.close()

    async def _event_stream():
        last_hash: Optional[str] = None
        heartbeat_every = 15
        heartbeat_at = datetime.utcnow()
        sleep_s = max(0.3, interval_ms / 1000.0)

        while True:
            try:
                loop_db = SessionLocal()
                try:
                    loop_exec_svc = WorkflowExecutionService(loop_db)
                    current = loop_exec_svc.get_execution(execution_id)
                    if not current or current.workflow_id != workflow_id:
                        payload = {"type": "error", "message": "Execution not found"}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        break

                    current = await _hydrate_execution_live_from_kernel(current)
                    current = _maybe_persist_terminal_reconcile(loop_exec_svc, current)
                    timeline_override = None
                    if current.graph_instance_id:
                        timeline_override = await _node_timeline_from_event_store(current.graph_instance_id)
                    status_payload = _execution_to_status_response(current, node_timeline_override=timeline_override).model_dump(mode="json")
                    current_hash = json.dumps(status_payload, ensure_ascii=False, sort_keys=True)

                    if current_hash != last_hash:
                        last_hash = current_hash
                        yield f"data: {json.dumps({'type': 'status', 'payload': status_payload}, ensure_ascii=False)}\n\n"
                        heartbeat_at = datetime.utcnow()
                    elif (datetime.utcnow() - heartbeat_at).total_seconds() >= heartbeat_every:
                        yield f"data: {json.dumps({'type': 'heartbeat', 'at': datetime.utcnow().isoformat()}, ensure_ascii=False)}\n\n"
                        heartbeat_at = datetime.utcnow()

                    if current.is_terminal():
                        yield f"data: {json.dumps({'type': 'terminal', 'state': current.state.value}, ensure_ascii=False)}\n\n"
                        break
                finally:
                    loop_db.close()

                await asyncio.sleep(sleep_s)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(
                    f"[WorkflowAPI] status stream loop error: execution_id={execution_id} err={e}"
                )
                payload = {"type": "error", "message": str(e)}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(min(2.0, sleep_s))

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{workflow_id}/executions/{execution_id}/cancel", response_model=WorkflowExecutionResponse)
async def cancel_execution(
    workflow_id: str,
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """取消执行"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "execute"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    # 幂等取消：对已终态执行直接返回当前状态，不视为错误。
    if execution.is_terminal():
        return _execution_to_response(execution)
    
    try:
        # 优先取消 API 层后台任务，避免其持续占用等待链路。
        bg_task = _WORKFLOW_BG_TASK_BY_EXECUTION.get(execution_id)
        if bg_task and not bg_task.done():
            bg_task.cancel()
        _WORKFLOW_BG_TASK_BY_EXECUTION.pop(execution_id, None)
        runtime = WorkflowRuntime(db, get_execution_manager())
        ok = await runtime.cancel(execution_id)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
        execution = execution_service.get_execution(execution_id)
        if not execution or execution.workflow_id != workflow_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
        return _execution_to_response(execution)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{workflow_id}/executions/{execution_id}/reconcile", response_model=WorkflowExecutionResponse)
async def reconcile_execution(
    workflow_id: str,
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """手动触发终态对账，用于异常场景恢复（如节点已终态但 execution 仍显示 running）。"""
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    execution = await _hydrate_execution_live_from_kernel(execution)
    execution = _maybe_persist_terminal_reconcile(execution_service, execution)
    node_timeline_override = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)
    return _execution_to_response(execution, node_timeline_override=node_timeline_override)


# ==================== Quota Endpoints ====================

@router.get("/{workflow_id}/quota", response_model=Dict[str, Any])
async def get_quota_status(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """获取配额状态"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    execution_manager = get_execution_manager()
    return execution_manager.get_workflow_status(workflow_id)


@router.put("/{workflow_id}/quota", response_model=Dict[str, Any])
async def set_quota(
    workflow_id: str,
    config: QuotaConfig,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    """设置配额"""
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    
    execution_manager = get_execution_manager()
    execution_manager.set_quota(workflow_id, config)
    
    return execution_manager.get_workflow_status(workflow_id)


@router.get("/{workflow_id}/governance", response_model=Dict[str, Any])
async def get_governance_config(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取 workflow 执行治理参数与状态（队列/背压/并发）"""
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    execution_manager = get_execution_manager()
    return execution_manager.get_workflow_status(workflow_id)


@router.put("/{workflow_id}/governance", response_model=Dict[str, Any])
async def set_governance_config(
    workflow_id: str,
    config: WorkflowGovernanceConfigRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """设置 workflow 执行治理参数（队列/背压）"""
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if config.backpressure_strategy and config.backpressure_strategy not in {"wait", "reject"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="backpressure_strategy must be wait or reject")

    execution_manager = get_execution_manager()
    old_status = execution_manager.get_workflow_status(workflow_id)
    old_queue_cfg = dict((old_status.get("queue") or {}))
    execution_manager.set_workflow_governance_config(
        workflow_id,
        max_queue_size=config.max_queue_size,
        backpressure_strategy=config.backpressure_strategy,
    )
    new_status = execution_manager.get_workflow_status(workflow_id)
    new_queue_cfg = dict((new_status.get("queue") or {}))

    audit_repo = WorkflowGovernanceAuditRepository(db)
    audit_repo.create_audit(
        workflow_id=workflow_id,
        changed_by=current_user,
        old_config={
            "max_queue_size": old_queue_cfg.get("max_queue_size"),
            "backpressure_strategy": old_queue_cfg.get("backpressure_strategy"),
        },
        new_config={
            "max_queue_size": new_queue_cfg.get("max_queue_size"),
            "backpressure_strategy": new_queue_cfg.get("backpressure_strategy"),
        },
    )
    return new_status


@router.get("/{workflow_id}/governance/audits", response_model=ListResponse)
async def list_governance_audits(
    workflow_id: str,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """获取 workflow 治理配置变更审计记录"""
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.has_permission(current_user, "read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    audit_repo = WorkflowGovernanceAuditRepository(db)
    items = audit_repo.list_audits(workflow_id, limit=limit, offset=offset)
    total = audit_repo.count_audits(workflow_id)
    return ListResponse(items=items, total=total, limit=limit, offset=offset)


# ==================== Helper Functions ====================

def _workflow_to_response(workflow: Workflow) -> WorkflowResponse:
    """转换 Workflow 为响应格式"""
    return WorkflowResponse(
        id=workflow.id,
        namespace=workflow.namespace,
        name=workflow.name,
        description=workflow.description,
        lifecycle_state=workflow.lifecycle_state.value,
        latest_version_id=workflow.latest_version_id,
        published_version_id=workflow.published_version_id,
        owner_id=workflow.owner_id,
        tags=workflow.tags,
        created_at=workflow.created_at.isoformat() if workflow.created_at else "",
        updated_at=workflow.updated_at.isoformat() if workflow.updated_at else ""
    )


def _version_to_response(version: WorkflowVersion) -> WorkflowVersionResponse:
    """转换 WorkflowVersion 为响应格式"""
    return WorkflowVersionResponse(
        version_id=version.version_id,
        workflow_id=version.workflow_id,
        version_number=version.version_number,
        state=version.state.value,
        description=version.description,
        created_by=version.created_by,
        published_by=version.published_by,
        created_at=version.created_at.isoformat() if version.created_at else "",
        published_at=version.published_at.isoformat() if version.published_at else None
    )


def _build_node_timeline_from_events(events: List[ExecutionEvent]) -> List[Dict[str, Any]]:
    """
    从 execution_event 流构建 node_timeline，统一以事件为单一数据源。
    处理 NODE_SCHEDULED、NODE_STARTED 及节点终态事件；GRAPH_CANCELLED/GRAPH_FAILED 时将未终态节点回填为 cancelled。
    """
    # node_id -> { started_at_iso, finished_at_iso, state, duration_ms, retry_count, error_message }
    by_node: Dict[str, Dict[str, Any]] = {}
    retry_counts: Dict[str, int] = {}

    def _ts_to_iso(ts_ms: int) -> str:
        try:
            return datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        except Exception:
            return ""

    for ev in events:
        if ev.event_type == ExecutionEventType.NODE_SCHEDULED:
            node_id = (ev.payload or {}).get("node_id") or ""
            if node_id and node_id not in by_node:
                by_node[node_id] = {
                    "node_id": node_id,
                    "state": "pending",
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                    "retry_count": retry_counts.get(node_id, 0),
                    "error_message": None,
                }
        elif ev.event_type == ExecutionEventType.NODE_STARTED:
            node_id = (ev.payload or {}).get("node_id") or ""
            if node_id:
                by_node.setdefault(node_id, {"state": "running", "retry_count": retry_counts.get(node_id, 0)})
                by_node[node_id]["state"] = "running"
                by_node[node_id]["started_at"] = _ts_to_iso(ev.timestamp)
                by_node[node_id]["node_id"] = node_id
        elif ev.event_type == ExecutionEventType.NODE_SUCCEEDED:
            node_id = (ev.payload or {}).get("node_id") or ""
            if node_id:
                by_node.setdefault(node_id, {"node_id": node_id, "retry_count": retry_counts.get(node_id, 0)})
                by_node[node_id]["state"] = "success"
                by_node[node_id]["finished_at"] = _ts_to_iso(ev.timestamp)
                by_node[node_id]["duration_ms"] = (ev.payload or {}).get("duration_ms")
                by_node[node_id]["error_message"] = None
        elif ev.event_type == ExecutionEventType.NODE_FAILED:
            node_id = (ev.payload or {}).get("node_id") or ""
            if node_id:
                by_node.setdefault(node_id, {"node_id": node_id, "retry_count": retry_counts.get(node_id, 0)})
                by_node[node_id]["state"] = "failed"
                by_node[node_id]["finished_at"] = _ts_to_iso(ev.timestamp)
                by_node[node_id]["error_message"] = (ev.payload or {}).get("error_message")
                by_node[node_id]["retry_count"] = (ev.payload or {}).get("retry_count", 0)
        elif ev.event_type == ExecutionEventType.NODE_TIMEOUT:
            node_id = (ev.payload or {}).get("node_id") or ""
            if node_id:
                by_node.setdefault(node_id, {"node_id": node_id, "retry_count": retry_counts.get(node_id, 0)})
                by_node[node_id]["state"] = "timeout"
                by_node[node_id]["finished_at"] = _ts_to_iso(ev.timestamp)
        elif ev.event_type == ExecutionEventType.NODE_SKIPPED:
            node_id = (ev.payload or {}).get("node_id") or ""
            if node_id:
                by_node.setdefault(node_id, {"node_id": node_id, "retry_count": retry_counts.get(node_id, 0)})
                by_node[node_id]["state"] = "skipped"
                by_node[node_id]["finished_at"] = _ts_to_iso(ev.timestamp)
        elif ev.event_type == ExecutionEventType.NODE_RETRY_SCHEDULED:
            node_id = (ev.payload or {}).get("node_id") or ""
            if node_id:
                retry_counts[node_id] = retry_counts.get(node_id, 0) + 1
        elif ev.event_type == ExecutionEventType.GRAPH_CANCELLED:
            # 回填：未终态节点标为 cancelled，避免取消后仍显示 running/pending
            terminal_states = {"success", "failed", "skipped", "timeout", "cancelled"}
            finished_ts = _ts_to_iso(ev.timestamp)
            for r in by_node.values():
                if (r.get("state") or "").lower() not in terminal_states:
                    r["state"] = "cancelled"
                    r["finished_at"] = finished_ts
        elif ev.event_type == ExecutionEventType.GRAPH_FAILED:
            # 回填：未终态节点标为 failed，保持“失败”语义，避免被误判为取消。
            terminal_states = {"success", "failed", "skipped", "timeout", "cancelled"}
            finished_ts = _ts_to_iso(ev.timestamp)
            for r in by_node.values():
                if (r.get("state") or "").lower() not in terminal_states:
                    r["state"] = "failed"
                    r["finished_at"] = finished_ts

    for node_id, r in by_node.items():
        current_retry = int(r.get("retry_count") or 0)
        r["retry_count"] = max(current_retry, retry_counts.get(node_id, 0))
        r.setdefault("started_at", None)
        r.setdefault("finished_at", None)
        r.setdefault("duration_ms", None)
        r.setdefault("error_message", None)

    return list(by_node.values())


async def _node_timeline_from_event_store(instance_id: str) -> Optional[List[Dict[str, Any]]]:
    """从 execution_event 表拉取事件并构建 node_timeline；失败或无事件时返回 None。"""
    try:
        kernel_db = Database()
        async with kernel_db.async_session() as session:
            store = EventStore(session)
            events = await store.get_events(instance_id=instance_id)
        if not events:
            return None
        return _build_node_timeline_from_events(events)
    except Exception as e:
        logger.debug(
            f"[WorkflowAPI] node_timeline from events skipped: instance_id={instance_id} err={e}"
        )
        return None


def _merge_timeline_with_node_states(
    node_timeline_override: List[Dict[str, Any]],
    execution: WorkflowExecution,
) -> List[Dict[str, Any]]:
    """事件流部分缺失时用 node_states 补全，避免节点在 timeline 消失。"""
    seen = {r["node_id"] for r in node_timeline_override}
    out_list = list(node_timeline_override)
    for n in execution.node_states or []:
        if n.node_id in seen:
            continue
        duration_ms = None
        if n.started_at and n.finished_at:
            duration_ms = int((n.finished_at - n.started_at).total_seconds() * 1000)
        out_list.append({
            "node_id": n.node_id,
            "state": n.state.value if hasattr(n.state, "value") else str(n.state),
            "started_at": n.started_at.isoformat() if n.started_at else None,
            "finished_at": n.finished_at.isoformat() if n.finished_at else None,
            "duration_ms": duration_ms,
            "retry_count": n.retry_count,
            "error_message": n.error_message,
        })
    return out_list


def _execution_to_response(
    execution: WorkflowExecution,
    node_timeline_override: Optional[List[Dict[str, Any]]] = None,
) -> WorkflowExecutionResponse:
    """转换 WorkflowExecution 为响应格式；node_timeline_override 非空时以事件流为主，并与 node_states 合并补全缺失节点。"""
    node_states = [n.model_dump(mode="json") for n in (execution.node_states or [])]
    node_timeline: List[Dict[str, Any]] = []
    agent_summaries: List[Dict[str, Any]] = []
    if node_timeline_override:
        node_timeline = _merge_timeline_with_node_states(node_timeline_override, execution)
    for n in execution.node_states or []:
        duration_ms = None
        if n.started_at and n.finished_at:
            duration_ms = int((n.finished_at - n.started_at).total_seconds() * 1000)
        if not node_timeline_override:
            node_timeline.append(
                {
                    "node_id": n.node_id,
                    "state": n.state.value if hasattr(n.state, "value") else str(n.state),
                    "started_at": n.started_at.isoformat() if n.started_at else None,
                    "finished_at": n.finished_at.isoformat() if n.finished_at else None,
                    "duration_ms": duration_ms,
                    "retry_count": n.retry_count,
                    "error_message": n.error_message,
                }
            )
        out = n.output_data or {}
        if isinstance(out, dict) and out.get("type") == "agent_result":
            agent_summaries.append(
                {
                    "node_id": n.node_id,
                    "agent_id": out.get("agent_id"),
                    "agent_session_id": out.get("agent_session_id"),
                    "status": out.get("status", "success"),
                    "response_preview": out.get("response_preview"),
                    "duration_ms": duration_ms,
                }
            )
    if not agent_summaries and isinstance(execution.output_data, dict):
        fallback = execution.output_data.get("agent_summaries")
        if isinstance(fallback, list):
            agent_summaries = fallback

    return WorkflowExecutionResponse(
        execution_id=execution.execution_id,
        workflow_id=execution.workflow_id,
        version_id=execution.version_id,
        state=execution.state.value,
        graph_instance_id=execution.graph_instance_id,
        input_data=execution.input_data,
        output_data=execution.output_data,
        global_context=execution.global_context or {},
        trigger_type=execution.trigger_type,
        triggered_by=execution.triggered_by,
        error_message=execution.error_message,
        error_details=execution.error_details,
        created_at=execution.created_at.isoformat() if execution.created_at else "",
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        finished_at=execution.finished_at.isoformat() if execution.finished_at else None,
        duration_ms=execution.duration_ms,
        queue_position=execution.queue_position,
        queued_at=execution.queued_at.isoformat() if execution.queued_at else None,
        wait_duration_ms=execution.wait_duration_ms,
        node_states=node_states,
        node_timeline=node_timeline,
        replay={
            "execution_id": execution.execution_id,
            "graph_instance_id": execution.graph_instance_id,
            "replay_key": execution.graph_instance_id or execution.execution_id,
        },
        agent_summaries=agent_summaries,
    )


def _execution_to_status_response(
    execution: WorkflowExecution,
    node_timeline_override: Optional[List[Dict[str, Any]]] = None,
) -> WorkflowExecutionStatusResponse:
    node_timeline: List[Dict[str, Any]] = []
    if node_timeline_override:
        node_timeline = _merge_timeline_with_node_states(node_timeline_override, execution)
    else:
        for n in execution.node_states or []:
            duration_ms = None
            if n.started_at and n.finished_at:
                duration_ms = int((n.finished_at - n.started_at).total_seconds() * 1000)
            node_timeline.append(
                {
                    "node_id": n.node_id,
                    "state": n.state.value if hasattr(n.state, "value") else str(n.state),
                    "started_at": n.started_at.isoformat() if n.started_at else None,
                    "finished_at": n.finished_at.isoformat() if n.finished_at else None,
                    "duration_ms": duration_ms,
                    "retry_count": n.retry_count,
                    "error_message": n.error_message,
                }
            )
    return WorkflowExecutionStatusResponse(
        execution_id=execution.execution_id,
        workflow_id=execution.workflow_id,
        version_id=execution.version_id,
        state=execution.state.value,
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        finished_at=execution.finished_at.isoformat() if execution.finished_at else None,
        duration_ms=execution.duration_ms,
        queue_position=execution.queue_position,
        wait_duration_ms=execution.wait_duration_ms,
        node_timeline=node_timeline,
    )


def _map_kernel_graph_state_to_workflow_state(kernel_state: str) -> Optional[str]:
    s = str(kernel_state or "").strip().lower()
    mapping = {
        "running": WorkflowExecutionState.RUNNING.value,
        "pending": WorkflowExecutionState.PENDING.value,
        "completed": WorkflowExecutionState.COMPLETED.value,
        "failed": WorkflowExecutionState.FAILED.value,
        "cancelled": WorkflowExecutionState.CANCELLED.value,
    }
    return mapping.get(s)


async def _hydrate_execution_live_from_kernel(execution: WorkflowExecution) -> WorkflowExecution:
    """
    运行中实时回填：
    - 从 execution_kernel 读取 node_runtimes / graph_state
    - 覆盖 response 用 execution.node_states / state / output_data，避免前端看到陈旧状态
    """
    if not execution.graph_instance_id:
        return execution

    try:
        kernel_db = Database()
        result = await GraphRuntimeAdapter.extract_execution_result_from_kernel(
            execution.graph_instance_id,
            kernel_db,
        )
    except Exception as e:
        logger.debug(f"[WorkflowAPI] live hydrate skipped: execution_id={execution.execution_id} err={e}")
        return execution

    if not isinstance(result, dict):
        return execution

    # 1) 节点状态实时回填
    raw_nodes = result.get("node_states") or []
    hydrated_nodes: List[WorkflowExecutionNode] = []
    for item in raw_nodes:
        if not isinstance(item, dict):
            continue
        state_raw = str(item.get("state") or "pending").lower()
        if state_raw == "success":
            node_state = WorkflowExecutionNodeState.SUCCESS
        elif state_raw == "running":
            node_state = WorkflowExecutionNodeState.RUNNING
        elif state_raw == "failed":
            node_state = WorkflowExecutionNodeState.FAILED
        elif state_raw == "skipped":
            node_state = WorkflowExecutionNodeState.SKIPPED
        elif state_raw == "cancelled":
            node_state = WorkflowExecutionNodeState.CANCELLED
        elif state_raw == "timeout":
            node_state = WorkflowExecutionNodeState.TIMEOUT
        else:
            node_state = WorkflowExecutionNodeState.PENDING

        def _dt(v: Any) -> Optional[datetime]:
            if not v:
                return None
            try:
                return datetime.fromisoformat(str(v))
            except Exception:
                return None

        hydrated_nodes.append(
            WorkflowExecutionNode(
                node_id=str(item.get("node_id") or ""),
                state=node_state,
                input_data=item.get("input_data") or {},
                output_data=item.get("output_data") or {},
                error_message=item.get("error_message"),
                error_details=item.get("error_details") if isinstance(item.get("error_details"), dict) else None,
                started_at=_dt(item.get("started_at")),
                finished_at=_dt(item.get("finished_at")),
                retry_count=int(item.get("retry_count") or 0),
            )
        )
    if hydrated_nodes:
        execution.node_states = hydrated_nodes

    # 2) 图状态实时回填（response 级别）
    kernel_state = _map_kernel_graph_state_to_workflow_state(result.get("state"))
    if kernel_state:
        execution.state = WorkflowExecutionState(kernel_state)
        if execution.state in {
            WorkflowExecutionState.COMPLETED,
            WorkflowExecutionState.FAILED,
            WorkflowExecutionState.CANCELLED,
            WorkflowExecutionState.TIMEOUT,
        }:
            if execution.finished_at is None:
                # 用节点最大 finished_at 回填，缺失时用 now
                finished_candidates = [n.finished_at for n in (execution.node_states or []) if n.finished_at]
                execution.finished_at = max(finished_candidates) if finished_candidates else datetime.utcnow()
            if execution.started_at and execution.finished_at:
                execution.duration_ms = int((execution.finished_at - execution.started_at).total_seconds() * 1000)

    # 2.1) 边界兜底：若图状态尚未刷新，但节点已经全终态，则以节点终态覆盖 response 视图。
    # 仅影响 API 响应，不在 GET 默认路径落库写回。
    terminal_from_nodes = _derive_terminal_state_from_nodes(execution.node_states or [])
    if terminal_from_nodes is not None:
        execution.state = terminal_from_nodes
        if execution.finished_at is None:
            finished_candidates = [n.finished_at for n in (execution.node_states or []) if n.finished_at]
            execution.finished_at = max(finished_candidates) if finished_candidates else datetime.utcnow()
        if execution.started_at and execution.finished_at:
            execution.duration_ms = int((execution.finished_at - execution.started_at).total_seconds() * 1000)

    # 3) 输出实时回填
    if isinstance(result.get("output_data"), dict) and result.get("output_data"):
        execution.output_data = result.get("output_data")

    return execution


def _derive_terminal_state_from_nodes(nodes: List[WorkflowExecutionNode]) -> Optional[WorkflowExecutionState]:
    if not nodes:
        return None
    states = [n.state for n in nodes]
    terminal = {
        WorkflowExecutionNodeState.SUCCESS,
        WorkflowExecutionNodeState.FAILED,
        WorkflowExecutionNodeState.SKIPPED,
        WorkflowExecutionNodeState.CANCELLED,
        WorkflowExecutionNodeState.TIMEOUT,
    }
    if not all(s in terminal for s in states):
        return None
    if any(s in {WorkflowExecutionNodeState.FAILED, WorkflowExecutionNodeState.TIMEOUT} for s in states):
        return WorkflowExecutionState.FAILED
    if any(s == WorkflowExecutionNodeState.CANCELLED for s in states):
        return WorkflowExecutionState.CANCELLED
    return WorkflowExecutionState.COMPLETED


def _maybe_persist_terminal_reconcile(
    execution_service: WorkflowExecutionService,
    live_execution: WorkflowExecution,
) -> WorkflowExecution:
    """
    当 live 视图显示已终态而 workflow_executions 仍 running/pending 时，做一次幂等回写。
    """
    terminal_state = _derive_terminal_state_from_nodes(live_execution.node_states or [])
    if terminal_state is None:
        return live_execution
    now = datetime.utcnow()
    lock_until = _TERMINAL_RECONCILE_LOCK_UNTIL.get(live_execution.execution_id)
    if lock_until and now < lock_until:
        return live_execution
    try:
        # 先收敛主状态，确保前端尽快从 running 进入终态；重数据字段做 best-effort。
        persisted = execution_service.repository.update_state(
            live_execution.execution_id,
            terminal_state,
        )
        try:
            execution_service.repository.update_node_states(
                live_execution.execution_id,
                live_execution.node_states or [],
            )
            if isinstance(live_execution.output_data, dict):
                execution_service.repository.update_output(
                    live_execution.execution_id,
                    live_execution.output_data,
                )
        except OperationalError as oe:
            if "database is locked" in str(oe).lower():
                _TERMINAL_RECONCILE_LOCK_UNTIL[live_execution.execution_id] = now + timedelta(seconds=5)
                logger.debug(
                    f"[WorkflowAPI] Terminal reconcile payload skipped due to DB lock: "
                    f"execution_id={live_execution.execution_id}"
                )
            else:
                raise
        if persisted:
            _TERMINAL_RECONCILE_LOCK_UNTIL.pop(live_execution.execution_id, None)
            logger.info(
                f"[WorkflowAPI] Reconciled terminal state from live kernel: "
                f"execution_id={live_execution.execution_id} state={terminal_state.value}"
            )
            return persisted
    except OperationalError as e:
        if "database is locked" in str(e).lower():
            _TERMINAL_RECONCILE_LOCK_UNTIL[live_execution.execution_id] = now + timedelta(seconds=5)
            logger.debug(
                f"[WorkflowAPI] Terminal reconcile deferred by DB lock: "
                f"execution_id={live_execution.execution_id}"
            )
            return live_execution
        logger.warning(
            f"[WorkflowAPI] Terminal reconcile skipped: execution_id={live_execution.execution_id} err={e}"
        )
    except Exception as e:
        logger.warning(
            f"[WorkflowAPI] Terminal reconcile skipped: execution_id={live_execution.execution_id} err={e}"
        )
    return live_execution
