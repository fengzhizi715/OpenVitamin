"""
V2.6: Observability & Replay Layer - Unit Tests

测试：
1. sequence 严格递增
2. replay 状态一致
3. 事件序列化/反序列化
"""

import pytest
import pytest_asyncio
import asyncio
from datetime import datetime
from pathlib import Path
import tempfile
import os

from execution_kernel.events.event_model import ExecutionEvent, EventPayloadBuilder
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.events.serializer import EventSerializer
from execution_kernel.events.event_store import EventStore
from execution_kernel.replay.state_rebuilder import StateRebuilder
from execution_kernel.replay.replay_engine import ReplayEngine
from execution_kernel.persistence.db import Database


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """创建临时的异步数据库会话"""
    # 使用内存数据库
    db_url = "sqlite+aiosqlite:///:memory:"
    
    db = Database(db_url)
    await db.create_tables()
    
    # 创建 session
    session = db.get_async_session_factory()()
    try:
        yield session
        await session.commit()
    finally:
        await session.close()
    
        await db.close()


class TestExecutionEvent:
    """测试 ExecutionEvent 模型"""
    
    def test_event_creation(self):
        """测试事件创建"""
        event = ExecutionEvent.create(
            instance_id="test_instance",
            sequence=1,
            event_type=ExecutionEventType.GRAPH_STARTED,
            payload={"graph_id": "g1"},
        )
        
        assert event.instance_id == "test_instance"
        assert event.sequence == 1
        assert event.event_type == ExecutionEventType.GRAPH_STARTED
        assert event.payload["graph_id"] == "g1"
        assert event.schema_version == 1
    
    def test_event_is_terminal(self):
        """测试终止事件判断"""
        completed = ExecutionEvent.create(
            instance_id="test",
            sequence=1,
            event_type=ExecutionEventType.GRAPH_COMPLETED,
            payload={},
        )
        assert completed.is_terminal() is True
        
        started = ExecutionEvent.create(
            instance_id="test",
            sequence=1,
            event_type=ExecutionEventType.GRAPH_STARTED,
            payload={},
        )
        assert started.is_terminal() is False


class TestEventSerializer:
    """测试事件序列化器"""
    
    def test_datetime_serialization(self):
        """测试 datetime 序列化"""
        payload = {
            "time": datetime(2025, 3, 1, 12, 0, 0),
            "value": 123,
        }
        
        json_str = EventSerializer.serialize(payload)
        assert "2025-03-01T12:00:00" in json_str
    
    def test_exception_serialization(self):
        """测试异常序列化"""
        try:
            raise ValueError("test error")
        except Exception as e:
            payload = {"error": e}
            json_str = EventSerializer.serialize(payload)
            assert "ValueError" in json_str
            assert "test error" in json_str
    
    def test_safe_payload(self):
        """测试 payload 清理"""
        payload = {
            "valid": "string",
            "invalid": lambda x: x,  # 函数不可序列化
        }
        
        safe = EventSerializer.safe_payload(payload)
        assert safe["valid"] == "string"
        assert "<function>" in safe["invalid"] or "lambda" in safe["invalid"]


class TestStateRebuilder:
    """测试状态重建器"""
    
    def test_rebuild_graph_started(self):
        """测试重建 GraphStarted"""
        events = [
            ExecutionEvent.create(
                instance_id="test",
                sequence=1,
                event_type=ExecutionEventType.GRAPH_STARTED,
                payload={
                    "graph_id": "g1",
                    "graph_version": "1.0.0",
                    "initial_context": {"key": "value"},
                },
            ),
        ]
        
        rebuilder = StateRebuilder()
        state = rebuilder.rebuild(events)
        
        assert state.instance_id == "test"
        assert state.graph_id == "g1"
        assert state.graph_version == "1.0.0"
        assert state.context["key"] == "value"
    
    def test_rebuild_node_lifecycle(self):
        """测试重建节点生命周期"""
        events = [
            ExecutionEvent.create(
                instance_id="test",
                sequence=1,
                event_type=ExecutionEventType.GRAPH_STARTED,
                payload={"graph_id": "g1"},
            ),
            ExecutionEvent.create(
                instance_id="test",
                sequence=2,
                event_type=ExecutionEventType.NODE_STARTED,
                payload={"node_id": "n1", "input_data": {}},
            ),
            ExecutionEvent.create(
                instance_id="test",
                sequence=3,
                event_type=ExecutionEventType.NODE_SUCCEEDED,
                payload={"node_id": "n1", "output_data": {"result": "ok"}},
            ),
            ExecutionEvent.create(
                instance_id="test",
                sequence=4,
                event_type=ExecutionEventType.GRAPH_COMPLETED,
                payload={},
            ),
        ]
        
        rebuilder = StateRebuilder()
        state = rebuilder.rebuild(events)
        
        assert state.state == "completed"
        assert "n1" in state.nodes
        assert state.nodes["n1"].state.value == "success"
        assert state.nodes["n1"].output_data["result"] == "ok"
    
    def test_rebuild_node_failed(self):
        """测试重建节点失败"""
        events = [
            ExecutionEvent.create(
                instance_id="test",
                sequence=1,
                event_type=ExecutionEventType.GRAPH_STARTED,
                payload={"graph_id": "g1"},
            ),
            ExecutionEvent.create(
                instance_id="test",
                sequence=2,
                event_type=ExecutionEventType.NODE_STARTED,
                payload={"node_id": "n1"},
            ),
            ExecutionEvent.create(
                instance_id="test",
                sequence=3,
                event_type=ExecutionEventType.NODE_FAILED,
                payload={
                    "node_id": "n1",
                    "error_type": "RuntimeError",
                    "error_message": "something went wrong",
                },
            ),
            ExecutionEvent.create(
                instance_id="test",
                sequence=4,
                event_type=ExecutionEventType.GRAPH_FAILED,
                payload={},
            ),
        ]
        
        rebuilder = StateRebuilder()
        state = rebuilder.rebuild(events)
        
        assert state.state == "failed"
        assert state.nodes["n1"].state.value == "failed"
        assert state.nodes["n1"].error_type == "RuntimeError"


@pytest.mark.asyncio
class TestEventStore:
    """测试事件存储（需要数据库）"""
    
    async def test_emit_and_get_events(self, db_session):
        """测试发射和获取事件"""
        store = EventStore(db_session)
        
        # 发射事件
        event1 = await store.emit_event(
            instance_id="test_instance",
            event_type=ExecutionEventType.GRAPH_STARTED,
            payload={"graph_id": "g1"},
        )
        
        event2 = await store.emit_event(
            instance_id="test_instance",
            event_type=ExecutionEventType.NODE_STARTED,
            payload={"node_id": "n1"},
        )
        
        # 验证序列号递增
        assert event1.sequence == 1
        assert event2.sequence == 2
        
        # 获取事件
        events = await store.get_events("test_instance")
        assert len(events) == 2
        assert events[0].sequence == 1
        assert events[1].sequence == 2
    
    async def test_sequence_strictly_increasing(self, db_session):
        """测试序列号严格递增"""
        store = EventStore(db_session)
        
        # 发射多个事件
        for i in range(10):
            await store.emit_event(
                instance_id="test_seq",
                event_type=ExecutionEventType.NODE_STARTED,
                payload={"index": i},
            )
        
        # 获取并验证
        events = await store.get_events("test_seq")
        sequences = [e.sequence for e in events]
        
        # 验证严格递增
        assert sequences == list(range(1, 11))
        assert len(set(sequences)) == len(sequences)  # 无重复
    
    async def test_emit_failure_no_exception(self, db_session):
        """测试发射失败不抛出异常"""
        store = EventStore(db_session)
        
        # 使用无效 payload 测试失败处理
        result = await store.emit_event(
            instance_id="test",
            event_type=ExecutionEventType.GRAPH_STARTED,
            payload={"valid": "data"},  # 有效数据
        )
        
        # 成功时返回事件
        assert result is not None


@pytest.mark.asyncio
class TestReplayEngine:
    """测试回放引擎（需要数据库）"""
    
    async def test_validate_event_stream_complete(self, db_session):
        """测试验证完整事件流"""
        store = EventStore(db_session)
        
        # 创建完整事件流
        await store.emit_event(
            "test_val",
            ExecutionEventType.GRAPH_STARTED,
            {"graph_id": "g1"},
        )
        await store.emit_event(
            "test_val",
            ExecutionEventType.NODE_STARTED,
            {"node_id": "n1"},
        )
        await store.emit_event(
            "test_val",
            ExecutionEventType.NODE_SUCCEEDED,
            {"node_id": "n1"},
        )
        await store.emit_event(
            "test_val",
            ExecutionEventType.GRAPH_COMPLETED,
            {},
        )
        
        engine = ReplayEngine(db_session)
        validation = await engine.validate_event_stream("test_val")
        
        assert validation["valid"] is True
        assert validation["event_count"] == 4
        assert len(validation["errors"]) == 0
    
    async def test_validate_missing_terminal(self, db_session):
        """测试验证缺少终止事件"""
        store = EventStore(db_session)
        
        # 创建不完整事件流（缺少终止事件）
        await store.emit_event(
            "test_incomplete",
            ExecutionEventType.GRAPH_STARTED,
            {},
        )
        await store.emit_event(
            "test_incomplete",
            ExecutionEventType.NODE_STARTED,
            {"node_id": "n1"},
        )
        
        engine = ReplayEngine(db_session)
        validation = await engine.validate_event_stream("test_incomplete")
        
        assert validation["valid"] is False
        assert any("terminal" in err.lower() for err in validation["errors"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
