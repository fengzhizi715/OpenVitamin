"""
Execution Kernel Main Entry
启动执行示例和可运行的最小 demo
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
import os

from execution_kernel.models.graph_definition import (
    GraphDefinition,
    NodeDefinition,
    EdgeDefinition,
    NodeType,
    EdgeTrigger,
    RetryPolicy,
)
from execution_kernel.models.node_models import NodeState, GraphInstanceState
from execution_kernel.persistence.db import Database, init_database
from execution_kernel.persistence.repositories import (
    NodeRuntimeRepository,
    GraphInstanceRepository,
    NodeCacheRepository,
    GraphDefinitionRepository,
)
from execution_kernel.engine.state_machine import StateMachine
from execution_kernel.engine.executor import Executor
from execution_kernel.engine.scheduler import Scheduler
from execution_kernel.engine.context import GraphContext
from execution_kernel.cache.node_cache import NodeCache


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# 示例节点处理器（签名为 (node_def, input_data) 以与 Kernel Executor 一致）
async def tool_handler(node_def, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """工具节点处理器示例"""
    logger.info(f"Tool handler called with: {input_data}")
    await asyncio.sleep(0.5)
    return {
        "result": f"Processed: {input_data.get('data', 'unknown')}",
        "timestamp": datetime.utcnow().isoformat(),
    }


async def condition_handler(node_def, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """条件节点处理器示例"""
    logger.info(f"Condition handler called with: {input_data}")
    condition_value = input_data.get("condition", True)
    return {
        "result": bool(condition_value),
        "branch": "true" if condition_value else "false",
    }


async def script_handler(node_def, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """脚本节点处理器示例"""
    logger.info(f"Script handler called with: {input_data}")
    values = input_data.get("values", [])
    total = sum(values) if values else 0
    return {
        "total": total,
        "count": len(values),
    }


def create_sample_graph() -> GraphDefinition:
    """
    创建示例 Graph（3-5 个节点）
    
    拓扑结构：
    
    start (tool)
       |
       v
    check (condition)
       /    \\
      v      v
   true_path  false_path
   (tool)     (tool)
       \\      /
        v    v
       end (script)
    """
    graph = GraphDefinition(
        id="sample_graph_v1",
        version="1.0.0",
        nodes=[
            # 入口节点
            NodeDefinition(
                id="start",
                type=NodeType.TOOL,
                config={"default_input": {"data": "initial_data"}},
                retry_policy=RetryPolicy(max_retries=2, backoff_seconds=1.0),
                timeout_seconds=30.0,
                cacheable=True,
            ),
            # 条件节点
            NodeDefinition(
                id="check",
                type=NodeType.CONDITION,
                config={"default_input": {"condition": True}},
                retry_policy=RetryPolicy(max_retries=0),
                timeout_seconds=10.0,
            ),
            # True 分支
            NodeDefinition(
                id="true_path",
                type=NodeType.TOOL,
                config={"default_input": {"data": "${nodes.start.output.result}"}},
                retry_policy=RetryPolicy(max_retries=2),
                timeout_seconds=30.0,
            ),
            # False 分支
            NodeDefinition(
                id="false_path",
                type=NodeType.TOOL,
                config={"default_input": {"data": "fallback"}},
                retry_policy=RetryPolicy(max_retries=1),
                timeout_seconds=30.0,
            ),
            # 汇聚节点
            NodeDefinition(
                id="end",
                type=NodeType.SCRIPT,
                config={"default_input": {"values": [1, 2, 3, 4, 5]}},
                retry_policy=RetryPolicy(max_retries=0),
                timeout_seconds=10.0,
            ),
        ],
        edges=[
            # start -> check
            EdgeDefinition(from_node="start", to_node="check", on=EdgeTrigger.SUCCESS),
            # check -> true_path (条件为 true)
            EdgeDefinition(from_node="check", to_node="true_path", on=EdgeTrigger.SUCCESS),
            # check -> false_path (条件为 false，实际需要条件表达式)
            EdgeDefinition(from_node="check", to_node="false_path", on=EdgeTrigger.SUCCESS),
            # true_path -> end
            EdgeDefinition(from_node="true_path", to_node="end", on=EdgeTrigger.SUCCESS),
            # false_path -> end
            EdgeDefinition(from_node="false_path", to_node="end", on=EdgeTrigger.SUCCESS),
        ],
    )
    
    # 验证图定义
    errors = graph.validate()
    if errors:
        logger.error(f"Graph validation errors: {errors}")
        raise ValueError(f"Invalid graph: {errors}")
    
    return graph


async def run_demo():
    """运行最小 demo"""
    logger.info("=" * 60)
    logger.info("Execution Kernel Demo")
    logger.info("=" * 60)
    
    # 1. 初始化数据库（使用统一的 platform.db）
    from execution_kernel.persistence.db import get_platform_db_path
    db_path = get_platform_db_path()
    db_url = f"sqlite+aiosqlite:///{db_path}"
    
    db = init_database(db_url)
    await db.create_tables()
    logger.info(f"Database initialized: {db_path}")
    
    # 2. 创建组件
    async with db.async_session() as session:
        node_repo = NodeRuntimeRepository(session)
        instance_repo = GraphInstanceRepository(session)
        cache_repo = NodeCacheRepository(session)
        def_repo = GraphDefinitionRepository(session)
        
        state_machine = StateMachine(node_repo)
        cache = NodeCache(cache_repo)
        
        # 注册处理器
        executor = Executor(
            state_machine=state_machine,
            cache=cache,
            node_handlers={
                NodeType.TOOL.value: tool_handler,
                NodeType.CONDITION.value: condition_handler,
                NodeType.SCRIPT.value: script_handler,
            },
        )
        
        scheduler = Scheduler(db, state_machine, executor)
    
    # 3. 创建示例图
    graph = create_sample_graph()
    logger.info(f"Sample graph created: {graph.id}")
    logger.info(f"  Nodes: {[n.id for n in graph.nodes]}")
    logger.info(f"  Entry nodes: {graph.get_entry_nodes()}")
    
    # 4. 启动执行
    instance_id = f"demo_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    logger.info(f"\nStarting execution: {instance_id}")
    await scheduler.start_instance(graph, instance_id, {"user": "demo"})
    
    # 5. 等待完成
    final_state = await scheduler.wait_for_completion(instance_id, timeout=60.0)
    logger.info(f"\nExecution completed with state: {final_state.value}")
    
    # 6. 输出结果
    async with db.async_session() as session:
        node_repo = NodeRuntimeRepository(session)
        all_nodes = await node_repo.get_all_by_instance(instance_id)
        
        logger.info("\nNode Execution Results:")
        logger.info("-" * 40)
        for node in all_nodes:
            logger.info(f"  {node.node_id}: {node.state.value}")
            if node.output_data:
                logger.info(f"    Output: {node.output_data}")
            if node.error_message:
                logger.info(f"    Error: {node.error_message}")
    
    # 7. 关闭数据库
    await db.close()
    logger.info("\nDemo completed!")


async def run_parallel_demo():
    """
    并行执行验证 Demo
    
    演示多个独立节点并行执行
    """
    logger.info("=" * 60)
    logger.info("Parallel Execution Demo")
    logger.info("=" * 60)
    
    # 初始化（使用统一的 platform.db）
    from execution_kernel.persistence.db import get_platform_db_path
    db_path = get_platform_db_path()
    db_url = f"sqlite+aiosqlite:///{db_path}"
    
    db = init_database(db_url)
    await db.create_tables()
    
    # 创建并行图
    parallel_graph = GraphDefinition(
        id="parallel_graph_v1",
        version="1.0.0",
        nodes=[
            # 入口节点
            NodeDefinition(
                id="start",
                type=NodeType.TOOL,
                config={"default_input": {"data": "start"}},
                timeout_seconds=5.0,
            ),
            # 三个并行节点
            NodeDefinition(
                id="parallel_1",
                type=NodeType.TOOL,
                config={"default_input": {"data": "parallel_1"}},
                timeout_seconds=5.0,
            ),
            NodeDefinition(
                id="parallel_2",
                type=NodeType.TOOL,
                config={"default_input": {"data": "parallel_2"}},
                timeout_seconds=5.0,
            ),
            NodeDefinition(
                id="parallel_3",
                type=NodeType.TOOL,
                config={"default_input": {"data": "parallel_3"}},
                timeout_seconds=5.0,
            ),
            # 汇聚节点
            NodeDefinition(
                id="end",
                type=NodeType.SCRIPT,
                config={"default_input": {"values": [100, 200, 300]}},
                timeout_seconds=5.0,
            ),
        ],
        edges=[
            EdgeDefinition(from_node="start", to_node="parallel_1"),
            EdgeDefinition(from_node="start", to_node="parallel_2"),
            EdgeDefinition(from_node="start", to_node="parallel_3"),
            EdgeDefinition(from_node="parallel_1", to_node="end"),
            EdgeDefinition(from_node="parallel_2", to_node="end"),
            EdgeDefinition(from_node="parallel_3", to_node="end"),
        ],
    )
    
    # 创建组件
    async with db.async_session() as session:
        node_repo = NodeRuntimeRepository(session)
        instance_repo = GraphInstanceRepository(session)
        cache_repo = NodeCacheRepository(session)
        
        state_machine = StateMachine(node_repo)
        cache = NodeCache(cache_repo)
        
        executor = Executor(
            state_machine=state_machine,
            cache=cache,
            node_handlers={
                NodeType.TOOL.value: tool_handler,
                NodeType.SCRIPT.value: script_handler,
            },
        )
        
        scheduler = Scheduler(db, state_machine, executor)
    
    # 执行
    instance_id = f"parallel_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    logger.info(f"\nStarting parallel execution: {instance_id}")
    
    start_time = datetime.utcnow()
    await scheduler.start_instance(parallel_graph, instance_id)
    
    final_state = await scheduler.wait_for_completion(instance_id, timeout=60.0)
    elapsed = (datetime.utcnow() - start_time).total_seconds()
    
    logger.info(f"\nParallel execution completed in {elapsed:.2f}s")
    logger.info(f"Final state: {final_state.value}")
    
    # 如果是顺序执行，应该需要 2.5s (5 * 0.5s)
    # 并行执行应该只需要约 1.5s (start + parallel + end)
    if elapsed < 2.0:
        logger.info("✓ Parallel execution verified!")
    else:
        logger.info("⚠ Execution may not be fully parallel")
    
    await db.close()


async def run_retry_demo():
    """
    重试机制验证 Demo
    """
    logger.info("=" * 60)
    logger.info("Retry Demo")
    logger.info("=" * 60)
    
    # 初始化（使用统一的 platform.db）
    from execution_kernel.persistence.db import get_platform_db_path
    db_path = get_platform_db_path()
    db_url = f"sqlite+aiosqlite:///{db_path}"
    
    db = init_database(db_url)
    await db.create_tables()
    
    # 失败计数器
    fail_count = 0
    
    async def failing_handler(node_def, input_data: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal fail_count
        fail_count += 1
        if fail_count < 3:
            logger.info(f"Failing attempt {fail_count}")
            raise Exception(f"Simulated failure {fail_count}")
        logger.info(f"Success on attempt {fail_count}")
        return {"result": "success", "attempts": fail_count}
    
    # 创建重试图
    retry_graph = GraphDefinition(
        id="retry_graph_v1",
        version="1.0.0",
        nodes=[
            NodeDefinition(
                id="flaky_node",
                type=NodeType.TOOL,
                config={"default_input": {"data": "test"}},
                retry_policy=RetryPolicy(max_retries=3, backoff_seconds=0.5),
                timeout_seconds=10.0,
            ),
        ],
        edges=[],
    )
    
    # 创建组件
    async with db.async_session() as session:
        node_repo = NodeRuntimeRepository(session)
        cache_repo = NodeCacheRepository(session)
        
        state_machine = StateMachine(node_repo)
        cache = NodeCache(cache_repo)
        
        executor = Executor(
            state_machine=state_machine,
            cache=cache,
            node_handlers={
                NodeType.TOOL.value: failing_handler,
            },
        )
        
        scheduler = Scheduler(db, state_machine, executor)
    
    # 执行
    instance_id = f"retry_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    logger.info(f"\nStarting retry execution: {instance_id}")
    await scheduler.start_instance(retry_graph, instance_id)
    
    final_state = await scheduler.wait_for_completion(instance_id, timeout=30.0)
    
    logger.info(f"\nRetry execution completed with state: {final_state.value}")
    
    if fail_count == 3 and final_state == GraphInstanceState.COMPLETED:
        logger.info("✓ Retry mechanism verified!")
    else:
        logger.info(f"⚠ Unexpected result: fail_count={fail_count}, state={final_state.value}")
    
    await db.close()


async def main():
    """主入口"""
    print("\n" + "=" * 60)
    print("Execution Kernel - DAG Execution Engine")
    print("=" * 60)
    print("\nAvailable demos:")
    print("  1. Basic execution (sample graph)")
    print("  2. Parallel execution")
    print("  3. Retry mechanism")
    print("  4. Run all demos")
    print()
    
    try:
        choice = input("Select demo (1-4): ").strip()
    except EOFError:
        choice = "4"  # 默认运行所有
    
    if choice == "1":
        await run_demo()
    elif choice == "2":
        await run_parallel_demo()
    elif choice == "3":
        await run_retry_demo()
    elif choice == "4":
        await run_demo()
        print("\n")
        await run_parallel_demo()
        print("\n")
        await run_retry_demo()
    else:
        print("Invalid choice, running basic demo...")
        await run_demo()


if __name__ == "__main__":
    asyncio.run(main())
