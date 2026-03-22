"""
V2.6: Observability & Replay Layer - Demo

演示：
1. 执行一个简单的 DAG
2. 删除内存状态
3. 使用 replay_engine 重建状态
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from execution_kernel.persistence.db import init_database
from execution_kernel.engine.scheduler import Scheduler
from execution_kernel.engine.state_machine import StateMachine
from execution_kernel.engine.executor import Executor
from execution_kernel.models.graph_definition import (
    GraphDefinition, NodeDefinition, NodeType, EdgeDefinition
)
from execution_kernel.models.node_models import GraphInstanceState
from execution_kernel.events.event_store import EventStore
from execution_kernel.replay.replay_engine import ReplayEngine
from execution_kernel.analytics.metrics import MetricsCalculator


async def demo():
    """
    Demo: Event Stream + Replay
    """
    print("=" * 60)
    print("V2.6: Observability & Replay Layer Demo")
    print("=" * 60)
    
    # 1. 创建内存数据库
    db = init_database("sqlite+aiosqlite:///:memory:")
    await db.create_tables()
    print("\n✅ Database initialized")
    
    # 2. 创建简单的 DAG
    graph = GraphDefinition(
        id="demo_graph",
        version="1.0.0",
        nodes=[
            NodeDefinition(id="node_a", type=NodeType.TOOL, config={"name": "A"}),
            NodeDefinition(id="node_b", type=NodeType.TOOL, config={"name": "B"}),
            NodeDefinition(id="node_c", type=NodeType.TOOL, config={"name": "C"}),
        ],
        edges=[
            EdgeDefinition(from_node="node_a", to_node="node_b", on="success"),
            EdgeDefinition(from_node="node_b", to_node="node_c", on="success"),
        ],
    )
    print(f"✅ Graph created: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    
    # 3. 创建 Scheduler 和 Executor
    async with db.async_session() as session:
        from execution_kernel.persistence.repositories import (
            NodeRuntimeRepository, NodeCacheRepository
        )
        node_repo = NodeRuntimeRepository(session)
        cache_repo = NodeCacheRepository(session)
        
        state_machine = StateMachine(db=db)
        from execution_kernel.cache.node_cache import NodeCache
        cache = NodeCache(cache_repo)
        
        # Mock handler
        async def mock_handler(node_def, input_data, context=None):
            print(f"  Executing {node_def.id}...")
            await asyncio.sleep(0.1)  # 模拟执行时间
            return {"result": f"output_of_{node_def.id}"}
        
        executor = Executor(
            state_machine=state_machine,
            cache=cache,
            node_handlers={"tool": mock_handler},
        )
        
        scheduler = Scheduler(db, state_machine, executor)
    
    print("✅ Scheduler initialized")
    
    # 4. 执行 DAG
    instance_id = "demo_instance_001"
    print(f"\n🚀 Starting execution: {instance_id}")
    
    await scheduler.start_instance(graph, instance_id, {"demo": True})
    final_state = await scheduler.wait_for_completion(instance_id, timeout=30.0)
    
    print(f"✅ Execution completed: {final_state}")
    
    # 5. 检查事件流
    async with db.async_session() as session:
        event_store = EventStore(session)
        events = await event_store.get_events(instance_id)
        print(f"\n📊 Event Stream:")
        print(f"  Total events: {len(events)}")
        
        for event in events:
            print(f"  [{event.sequence:3d}] {event.event_type.value:25s} "
                  f"ts={event.timestamp}")
    
    # 6. 计算指标
    async with db.async_session() as session:
        calculator = MetricsCalculator(session)
        metrics = await calculator.compute_metrics(instance_id)
        
        print(f"\n📈 Metrics:")
        print(f"  Total events: {metrics.total_events}")
        print(f"  Node success rate: {metrics.node_success_rate:.2%}")
        print(f"  Avg node duration: {metrics.avg_node_duration_ms:.2f}ms")
        print(f"  Total execution time: {metrics.total_execution_duration_ms:.2f}ms")
    
    # 7. 模拟 "删除内存状态"
    print(f"\n🗑️  Simulating memory state loss...")
    del scheduler
    del state_machine
    del executor
    print("  Memory state cleared")
    
    # 8. 使用 Replay Engine 重建状态
    print(f"\n🔄 Rebuilding state from event stream...")
    
    async with db.async_session() as session:
        replay_engine = ReplayEngine(session)
        rebuilt_state = await replay_engine.rebuild_instance(instance_id)
        
        print(f"✅ State rebuilt:")
        print(f"  Instance ID: {rebuilt_state.instance_id}")
        print(f"  Graph ID: {rebuilt_state.graph_id}")
        print(f"  Final state: {rebuilt_state.state}")
        print(f"  Nodes:")
        for node_id, node in rebuilt_state.nodes.items():
            print(f"    - {node_id}: {node.state.value}")
    
    # 9. 验证事件流完整性
    async with db.async_session() as session:
        replay_engine = ReplayEngine(session)
        validation = await replay_engine.validate_event_stream(instance_id)
        
        print(f"\n✅ Event Stream Validation:")
        print(f"  Valid: {validation['valid']}")
        print(f"  Event count: {validation['event_count']}")
        if validation['errors']:
            print(f"  Errors: {validation['errors']}")
    
    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print("=" * 60)
    
    await db.close()


if __name__ == "__main__":
    asyncio.run(demo())
