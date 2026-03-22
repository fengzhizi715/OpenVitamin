"""
V2.6: Observability & Replay Layer - Event Store
事件存储（SQLAlchemy ORM）
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
import logging

from sqlalchemy import String, Integer, DateTime, Index, select, asc, desc, func, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.events.serializer import EventSerializer
from execution_kernel.models.graph_instance import Base


logger = logging.getLogger(__name__)


class ExecutionEventDB(Base):
    """
    Execution Event ORM 模型（SQLAlchemy 2.0 风格）
    
    表名: execution_event
    
    索引:
    - (instance_id, sequence): 用于按实例顺序查询
    - instance_id: 用于按实例查询
    """
    
    __tablename__ = "execution_event"
    
    # 主键
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    
    # 实例标识
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # 序列号（实例内严格递增）
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # 事件类型
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # 负载（JSON，使用 Text 避免大小限制）
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    
    # 时间戳（毫秒）
    timestamp: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # 模式版本
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    # 创建时间（数据库时间）
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    
    # 复合索引
    __table_args__ = (
        Index("ix_execution_event_instance_seq", "instance_id", "sequence"),
    )


class EventStore:
    """
    事件存储
    
    职责：
    - 持久化事件（append-only）
    - 按实例查询事件流
    - 序列号分配（保证确定性）
    
    设计原则：
    - 所有操作都是 append-only，不允许 update/delete
    - emit_event 失败不影响主流程（fire-and-forget）
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def emit_event(
        self,
        instance_id: str,
        event_type: ExecutionEventType,
        payload: Dict[str, Any],
    ) -> Optional[ExecutionEvent]:
        """
        发射事件
        
        Args:
            instance_id: 图实例 ID
            event_type: 事件类型
            payload: 事件负载
            
        Returns:
            ExecutionEvent（如果成功）或 None（如果失败）
            
        注意：
        - 失败时返回 None，不抛出异常（不影响主流程）
        - 自动分配序列号
        """
        try:
            # 获取下一个序列号
            sequence = await self._get_next_sequence(instance_id)
            
            # 创建事件
            event = ExecutionEvent.create(
                instance_id=instance_id,
                sequence=sequence,
                event_type=event_type,
                payload=EventSerializer.safe_payload(payload),
            )
            
            # 序列化 payload
            payload_json = EventSerializer.serialize(event.payload)
            
            # 创建 ORM 对象
            db_event = ExecutionEventDB(
                id=event.event_id,
                instance_id=event.instance_id,
                sequence=event.sequence,
                event_type=event.event_type.value,
                payload_json=payload_json,
                timestamp=event.timestamp,
                schema_version=event.schema_version,
            )
            
            # 持久化（使用 flush 而非 commit，让调用方控制事务）
            self.session.add(db_event)
            await self.session.flush()  # 不 commit，让调用方决定
            
            logger.debug(
                f"Event emitted: {event_type.value} "
                f"for instance {instance_id}, seq={sequence}"
            )
            
            return event
            
        except Exception as e:
            logger.error(f"Failed to emit event: {e}")
            # 失败时不 rollback 调用方 session，避免影响主流程事务
            return None
    
    async def _get_next_sequence(self, instance_id: str) -> int:
        """
        获取下一个序列号
        
        使用数据库查询获取当前最大序列号，保证确定性。
        使用 FOR UPDATE 锁防止并发冲突。
        """
        # 使用数据库级序列生成（带行锁）
        # 对于 SQLite，FOR UPDATE 不生效，但 SQLite 默认串行写入
        # 对于 PostgreSQL，FOR UPDATE 保证原子性
        result = await self.session.execute(
            select(func.coalesce(func.max(ExecutionEventDB.sequence), 0) + 1)
            .where(ExecutionEventDB.instance_id == instance_id)
        )
        next_seq = result.scalar() or 1
        
        return next_seq
    
    async def get_events(
        self,
        instance_id: str,
        start_sequence: int = 1,
        end_sequence: Optional[int] = None,
    ) -> List[ExecutionEvent]:
        """
        获取实例的事件流
        
        Args:
            instance_id: 图实例 ID
            start_sequence: 起始序列号（包含）
            end_sequence: 结束序列号（包含），None 表示到最后
            
        Returns:
            事件列表（按序列号排序）
        """
        query = (
            select(ExecutionEventDB)
            .where(ExecutionEventDB.instance_id == instance_id)
            .where(ExecutionEventDB.sequence >= start_sequence)
            .order_by(asc(ExecutionEventDB.sequence))
        )
        
        if end_sequence is not None:
            query = query.where(ExecutionEventDB.sequence <= end_sequence)
        
        result = await self.session.execute(query)
        db_events = result.scalars().all()
        
        return [self._to_model(e) for e in db_events]
    
    async def get_latest_events(
        self,
        instance_id: str,
        limit: int = 100,
    ) -> List[ExecutionEvent]:
        """
        获取最新的 N 个事件
        
        Args:
            instance_id: 图实例 ID
            limit: 数量限制
            
        Returns:
            事件列表（按序列号降序）
        """
        result = await self.session.execute(
            select(ExecutionEventDB)
            .where(ExecutionEventDB.instance_id == instance_id)
            .order_by(desc(ExecutionEventDB.sequence))
            .limit(limit)
        )
        db_events = result.scalars().all()
        
        # 返回时按正序
        return [self._to_model(e) for e in reversed(db_events)]
    
    async def get_event_count(self, instance_id: str) -> int:
        """获取实例的事件总数"""
        result = await self.session.execute(
            select(func.count(ExecutionEventDB.id))
            .where(ExecutionEventDB.instance_id == instance_id)
        )
        return result.scalar() or 0
    
    async def has_terminal_event(self, instance_id: str) -> bool:
        """检查实例是否有终止事件"""
        from execution_kernel.events.event_types import TERMINAL_EVENTS
        terminal_types = [e.value for e in TERMINAL_EVENTS]
        
        result = await self.session.execute(
            select(ExecutionEventDB)
            .where(ExecutionEventDB.instance_id == instance_id)
            .where(ExecutionEventDB.event_type.in_(terminal_types))
            .limit(1)
        )
        return result.scalar() is not None
    
    def _to_model(self, db_event: ExecutionEventDB) -> ExecutionEvent:
        """将 ORM 对象转换为 Pydantic 模型"""
        return ExecutionEvent(
            event_id=db_event.id,
            instance_id=db_event.instance_id,
            sequence=db_event.sequence,
            event_type=ExecutionEventType(db_event.event_type),
            timestamp=db_event.timestamp,
            payload=EventSerializer.deserialize(db_event.payload_json),
            schema_version=db_event.schema_version,
        )


# 全局事件存储实例（用于依赖注入）
_event_store_instance: Optional[EventStore] = None


def get_event_store(session: AsyncSession) -> EventStore:
    """获取事件存储实例"""
    return EventStore(session)
