"""
AgentTrace 存储（ORM 版本）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

from core.data.base import db_session
from core.data.models.trace import AgentTrace as AgentTraceORM
from log import logger


class AgentTraceEvent(BaseModel):
    trace_id: Optional[str] = None  # session-level trace id
    event_id: str
    session_id: str
    step: int
    event_type: str  # "llm_request", "tool_call", "error", "final_answer"

    agent_id: Optional[str] = None
    model_id: Optional[str] = None
    tool_id: Optional[str] = None

    input_data: Optional[dict] = None
    output_data: Optional[dict] = None

    duration_ms: Optional[int] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentTraceStore:
    """智能体运行轨迹存储（使用 SQLAlchemy ORM）"""

    def record_event(self, event: AgentTraceEvent) -> str:
        """记录事件"""
        try:
            input_json = json.dumps(event.input_data, default=str) if event.input_data is not None else None
            output_json = json.dumps(event.output_data, default=str) if event.output_data is not None else None

            with db_session() as db:
                trace_orm = AgentTraceORM(
                    id=event.event_id,
                    trace_id=event.trace_id,
                    session_id=event.session_id,
                    step=event.step,
                    event_type=event.event_type,
                    agent_id=event.agent_id,
                    model_id=event.model_id,
                    tool_id=event.tool_id,
                    input_json=input_json,
                    output_json=output_json,
                    duration_ms=event.duration_ms,
                    created_at=datetime.fromisoformat(event.created_at) if isinstance(event.created_at, str) else datetime.now(timezone.utc),
                )
                db.add(trace_orm)
            return event.event_id
        except Exception as e:
            logger.error(f"[AgentTraceStore] record_event failed: {e}")
            return ""

    def get_session_traces(self, session_id: str) -> List[AgentTraceEvent]:
        """获取会话的所有轨迹"""
        traces = []
        try:
            with db_session() as db:
                rows = db.query(AgentTraceORM).filter(
                    AgentTraceORM.session_id == session_id
                ).order_by(AgentTraceORM.step.asc(), AgentTraceORM.created_at.asc()).all()
                for row in rows:
                    traces.append(self._orm_to_event(row))
        except Exception as e:
            logger.error(f"[AgentTraceStore] get_session_traces failed: {e}")
        return traces

    def _orm_to_event(self, trace_orm: AgentTraceORM) -> AgentTraceEvent:
        """ORM 对象转 AgentTraceEvent"""
        return AgentTraceEvent(
            trace_id=trace_orm.trace_id,
            event_id=trace_orm.id,
            session_id=trace_orm.session_id,
            step=trace_orm.step,
            event_type=trace_orm.event_type,
            agent_id=trace_orm.agent_id,
            model_id=trace_orm.model_id,
            tool_id=trace_orm.tool_id,
            input_data=json.loads(trace_orm.input_json) if trace_orm.input_json else None,
            output_data=json.loads(trace_orm.output_json) if trace_orm.output_json else None,
            duration_ms=trace_orm.duration_ms,
            created_at=trace_orm.created_at.isoformat() if trace_orm.created_at else datetime.now(timezone.utc).isoformat(),
        )


_store: Optional[AgentTraceStore] = None


def get_agent_trace_store() -> AgentTraceStore:
    """获取 AgentTrace 存储单例"""
    global _store
    if _store is None:
        _store = AgentTraceStore()
    return _store
