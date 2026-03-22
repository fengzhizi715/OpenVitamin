"""
V2.6: Observability & Replay Layer - Event API
提供事件流查询、回放和指标计算的 API
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from log import logger

from execution_kernel.persistence.db import Database
from execution_kernel.events.event_store import EventStore
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.replay.replay_engine import ReplayEngine
from execution_kernel.analytics.metrics import MetricsCalculator

router = APIRouter(prefix="/api/events", tags=["Events & Replay"])


# =========================
# Response Models
# =========================

class EventResponse(BaseModel):
    """单个事件响应"""
    event_id: str
    instance_id: str
    sequence: int
    event_type: str
    timestamp: int
    payload: Dict[str, Any]
    schema_version: int


class EventListResponse(BaseModel):
    """事件列表响应"""
    instance_id: str
    total: int
    events: List[EventResponse]


class RebuiltStateResponse(BaseModel):
    """重建状态响应"""
    instance_id: str
    graph_id: str
    state: str
    nodes: Dict[str, Dict[str, Any]]
    context: Dict[str, Any]
    event_count: int
    last_sequence: int


class ValidationResponse(BaseModel):
    """验证响应"""
    valid: bool
    event_count: int
    node_count: int
    errors: List[str]
    first_sequence: Optional[int]
    last_sequence: Optional[int]


class MetricsResponse(BaseModel):
    """指标响应"""
    instance_id: str
    total_events: int
    node_success_rate: float
    avg_node_duration_ms: float
    total_retry_count: int
    total_execution_duration_ms: float
    completed_nodes: int
    failed_nodes: int
    details: Dict[str, Any]


# =========================
# Helper
# =========================

def _get_db() -> Database:
    """获取数据库实例"""
    return Database()


def _event_to_response(event: ExecutionEvent) -> EventResponse:
    """转换事件为响应模型"""
    return EventResponse(
        event_id=event.event_id,
        instance_id=event.instance_id,
        sequence=event.sequence,
        event_type=event.event_type.value,
        timestamp=event.timestamp,
        payload=event.payload,
        schema_version=event.schema_version,
    )


# =========================
# Events API
# =========================

@router.get("/instance/{instance_id}", response_model=EventListResponse)
async def get_instance_events(
    instance_id: str,
    start_sequence: int = Query(1, ge=1, description="起始序列号"),
    end_sequence: Optional[int] = Query(None, ge=1, description="结束序列号"),
):
    """
    获取实例的事件流
    
    Args:
        instance_id: 图实例 ID
        start_sequence: 起始序列号（默认 1）
        end_sequence: 结束序列号（默认到最后）
    
    Returns:
        事件列表（按序列号排序）
    """
    try:
        db = _get_db()
        
        async with db.async_session() as session:
            store = EventStore(session)
            events = await store.get_events(
                instance_id=instance_id,
                start_sequence=start_sequence,
                end_sequence=end_sequence,
            )
            
            return EventListResponse(
                instance_id=instance_id,
                total=len(events),
                events=[_event_to_response(e) for e in events],
            )
    except Exception as e:
        logger.error(f"Failed to get events for instance {instance_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instance/{instance_id}/event-types")
async def get_event_type_breakdown(instance_id: str):
    """
    获取实例的事件类型分布
    
    Returns:
        各事件类型的数量统计
    """
    try:
        db = _get_db()
        
        async with db.async_session() as session:
            store = EventStore(session)
            events = await store.get_events(instance_id)
            
            breakdown: Dict[str, int] = {}
            for event in events:
                event_type = event.event_type.value
                breakdown[event_type] = breakdown.get(event_type, 0) + 1
            
            return {
                "instance_id": instance_id,
                "total_events": len(events),
                "breakdown": breakdown,
            }
    except Exception as e:
        logger.error(f"Failed to get event breakdown for instance {instance_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# Replay API
# =========================

@router.get("/instance/{instance_id}/replay", response_model=RebuiltStateResponse)
async def replay_instance_state(
    instance_id: str,
    target_sequence: Optional[int] = Query(None, ge=1, description="目标序列号（用于断点调试）"),
):
    """
    回放实例状态
    
    从事件流重建执行状态，用于 Debug 和审计。
    
    Args:
        instance_id: 图实例 ID
        target_sequence: 目标序列号（可选，用于断点调试）
    
    Returns:
        重建的图状态
    """
    try:
        db = _get_db()
        
        async with db.async_session() as session:
            engine = ReplayEngine(session)
            
            if target_sequence:
                state = await engine.replay_to_point(instance_id, target_sequence)
            else:
                state = await engine.rebuild_instance(instance_id)
            
            return RebuiltStateResponse(
                instance_id=state.instance_id,
                graph_id=state.graph_id,
                state=state.state,
                nodes={k: v.to_dict() for k, v in state.nodes.items()},
                context=state.context,
                event_count=state.event_count,
                last_sequence=state.last_sequence,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to replay instance {instance_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instance/{instance_id}/validate", response_model=ValidationResponse)
async def validate_event_stream(instance_id: str):
    """
    验证事件流完整性
    
    检查：
    - 序列号连续性
    - 必须有 GraphStarted
    - 必须有终止事件
    - Node 状态转换合法性
    
    Returns:
        验证报告
    """
    try:
        db = _get_db()
        
        async with db.async_session() as session:
            engine = ReplayEngine(session)
            validation = await engine.validate_event_stream(instance_id)
            
            return ValidationResponse(
                valid=validation["valid"],
                event_count=validation.get("event_count", 0),
                node_count=validation.get("node_count", 0),
                errors=validation.get("errors", []),
                first_sequence=validation.get("first_sequence"),
                last_sequence=validation.get("last_sequence"),
            )
    except Exception as e:
        logger.error(f"Failed to validate event stream for instance {instance_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# Metrics API
# =========================

@router.get("/instance/{instance_id}/metrics", response_model=MetricsResponse)
async def get_instance_metrics(instance_id: str):
    """
    获取实例执行指标
    
    从事件流计算执行指标，用于离线分析。
    
    Returns:
        执行指标
    """
    try:
        db = _get_db()
        
        async with db.async_session() as session:
            calculator = MetricsCalculator(session)
            metrics = await calculator.compute_metrics(instance_id)
            
            return MetricsResponse(
                instance_id=metrics.instance_id,
                total_events=metrics.total_events,
                node_success_rate=metrics.node_success_rate,
                avg_node_duration_ms=metrics.avg_node_duration_ms,
                total_retry_count=metrics.total_retry_count,
                total_execution_duration_ms=metrics.total_execution_duration_ms,
                completed_nodes=metrics.completed_nodes,
                failed_nodes=metrics.failed_nodes,
                details=metrics.details,
            )
    except Exception as e:
        logger.error(f"Failed to get metrics for instance {instance_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
