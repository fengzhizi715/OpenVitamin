"""
AgentSession 存储（ORM 版本）
并发优化：
1. 使用优化的 db_session（带重试机制）
2. 减少事务持有时间
3. 批量操作优化
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy import select, update, delete

from core.data.base import db_session
from core.data.models.session import AgentSession as AgentSessionORM
from log import logger
from core.types import Message


class AgentSession(BaseModel):
    session_id: str
    agent_id: str
    user_id: str = "default"
    trace_id: str = Field(default_factory=lambda: f"atrace_{uuid.uuid4().hex[:16]}")

    messages: List[Message] = Field(default_factory=list)
    step: int = 0
    status: str = "idle"  # running, finished, error, idle

    error_message: Optional[str] = None
    """上传文件时的工作目录（绝对路径），供后续同会话 run 时 file.read 使用。"""
    workspace_dir: Optional[str] = None
    # Structured state for recent tool observations (avoid parsing message text)
    state: dict = Field(default_factory=dict)
    
    # V2.6: Execution Kernel instance ID (for event stream replay/debug)
    kernel_instance_id: Optional[str] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentSessionStore:
    """智能体运行会话存储（使用 SQLAlchemy ORM）"""

    def save_session(self, session: AgentSession) -> bool:
        """保存会话（UPSERT，优化并发写入）"""
        try:
            now = datetime.now(timezone.utc)
            messages_json = json.dumps([m.model_dump() for m in session.messages])
            state_json = json.dumps(session.state or {})
            workspace_dir = getattr(session, "workspace_dir", None) or None

            # 转换 ISO 格式字符串为 datetime 对象
            created_at_dt = datetime.fromisoformat(session.created_at.replace('Z', '+00:00')) if isinstance(session.created_at, str) else session.created_at
            if isinstance(created_at_dt, str):
                created_at_dt = datetime.now(timezone.utc)

            # 使用优化的 db_session（自动重试）
            with db_session(retry_count=3, retry_delay=0.1) as db:
                stmt = insert(AgentSessionORM).values(
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    user_id=session.user_id,
                    trace_id=session.trace_id,
                    status=session.status,
                    step=session.step,
                    messages_json=messages_json,
                    state_json=state_json,
                    error_message=session.error_message,
                    workspace_dir=workspace_dir,
                    kernel_instance_id=getattr(session, "kernel_instance_id", None),
                    created_at=created_at_dt,
                    updated_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id"],
                    set_={
                        "trace_id": stmt.excluded.trace_id,
                        "status": stmt.excluded.status,
                        "step": stmt.excluded.step,
                        "messages_json": stmt.excluded.messages_json,
                        "state_json": stmt.excluded.state_json,
                        "error_message": stmt.excluded.error_message,
                        "workspace_dir": stmt.excluded.workspace_dir,
                        "kernel_instance_id": stmt.excluded.kernel_instance_id,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
                db.execute(stmt)
            return True
        except Exception as e:
            logger.error(f"[AgentSessionStore] save_session failed: {e}")
            return False

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """获取会话（优化查询性能）"""
        try:
            # 使用只读事务，减少锁竞争
            with db_session(retry_count=2, retry_delay=0.05) as db:
                session_orm = db.query(AgentSessionORM).filter(
                    AgentSessionORM.session_id == session_id
                ).first()
                if session_orm:
                    return self._orm_to_session(session_orm)
        except Exception as e:
            logger.error(f"[AgentSessionStore] get_session failed: {e}")
        return None

    def _orm_to_session(self, session_orm: AgentSessionORM) -> AgentSession:
        """ORM 对象转 AgentSession"""
        messages_data = json.loads(session_orm.messages_json)
        messages = [Message(**m) for m in messages_data]
        state = {}
        try:
            state = json.loads(session_orm.state_json) if session_orm.state_json else {}
        except Exception:
            state = {}

        return AgentSession(
            session_id=session_orm.session_id,
            agent_id=session_orm.agent_id,
            user_id=session_orm.user_id,
            trace_id=session_orm.trace_id or f"atrace_{session_orm.session_id}",
            status=session_orm.status,
            step=session_orm.step,
            messages=messages,
            error_message=session_orm.error_message,
            workspace_dir=session_orm.workspace_dir,
            state=state,
            kernel_instance_id=getattr(session_orm, "kernel_instance_id", None),
            created_at=session_orm.created_at.isoformat() if session_orm.created_at else datetime.now(timezone.utc).isoformat(),
            updated_at=session_orm.updated_at.isoformat() if session_orm.updated_at else datetime.now(timezone.utc).isoformat(),
        )

    def delete_message(self, session_id: str, message_index: int) -> bool:
        """删除会话中的一条消息"""
        try:
            session = self.get_session(session_id)
            if not session:
                return False

            if message_index < 0 or message_index >= len(session.messages):
                return False

            session.messages.pop(message_index)
            return self.save_session(session)
        except Exception as e:
            logger.error(f"[AgentSessionStore] delete_message failed: {e}")
            return False

    def delete_session(self, session_id: str, user_id: str = "default") -> bool:
        """删除会话（原子操作）"""
        try:
            with db_session(retry_count=3, retry_delay=0.1) as db:
                # 使用 DELETE 语句直接删除，避免先查后删的竞态
                result = db.execute(
                    delete(AgentSessionORM).where(
                        AgentSessionORM.session_id == session_id,
                        AgentSessionORM.user_id == user_id,
                    )
                )
                # 检查是否删除了记录
                deleted_count = result.rowcount
                if deleted_count > 0:
                    logger.info(f"[AgentSessionStore] Deleted session {session_id}")
                    return True
                else:
                    logger.debug(f"[AgentSessionStore] Session {session_id} not found")
                    return False
        except Exception as e:
            logger.error(f"[AgentSessionStore] delete_session failed: {e}")
            return False

    def list_sessions(
        self,
        user_id: str = "default",
        limit: int = 50,
        agent_id: Optional[str] = None,
    ) -> List[AgentSession]:
        """列出会话（分页查询优化）"""
        sessions = []
        try:
            # 使用只读模式，减少锁竞争
            with db_session(retry_count=2, retry_delay=0.05) as db:
                query = db.query(AgentSessionORM).filter(AgentSessionORM.user_id == user_id)
                if agent_id:
                    query = query.filter(AgentSessionORM.agent_id == agent_id)
                # 使用索引排序（updated_at DESC）
                rows = query.order_by(AgentSessionORM.updated_at.desc()).limit(limit).all()
                for row in rows:
                    sessions.append(self._orm_to_session(row))
        except Exception as e:
            logger.error(f"[AgentSessionStore] list_sessions failed: {e}")
        return sessions


_store: Optional[AgentSessionStore] = None


def get_agent_session_store() -> AgentSessionStore:
    """获取 AgentSession 存储单例"""
    global _store
    if _store is None:
        _store = AgentSessionStore()
    return _store
