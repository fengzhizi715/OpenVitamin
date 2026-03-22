"""
V2.7 Optimization Layer Integration Test

测试 V2.7 优化层的完整流程：
1. OptimizationConfig 配置
2. StatisticsCollector 收集统计
3. SnapshotBuilder 构建快照
4. DefaultPolicy / LearnedPolicy 策略排序
5. Scheduler 集成策略和快照
6. ExecutionKernelAdapter 集成
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from typing import Dict, Any, List


def print_section(title: str):
    """打印章节标题"""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def print_result(name: str, success: bool, details: str = None):
    """打印测试结果"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"  {status} - {name}")
    if details:
        print(f"         {details}")


async def test_optimization_config():
    """测试 V2.7 OptimizationConfig 配置"""
    print_section("Test 1: OptimizationConfig")
    
    from execution_kernel.optimization import OptimizationConfig, get_optimization_config, set_optimization_config
    
    # 1. 默认配置
    default_config = OptimizationConfig()
    print_result("Default config disabled", default_config.enabled == False)
    print_result("Default policy is 'default'", default_config.scheduler_policy == "default")
    
    # 2. 自定义配置
    custom_config = OptimizationConfig(
        enabled=True,
        scheduler_policy="learned",
        policy_params={
            "node_weight_factor": 15.0,
            "latency_penalty_factor": 2.0,
            "skill_weight_factor": 3.0,
            "consider_skill": True,
        },
        auto_build_snapshot=True,
        collect_statistics=True,
    )
    print_result("Custom config enabled", custom_config.enabled == True)
    print_result("Custom policy is 'learned'", custom_config.scheduler_policy == "learned")
    print_result("is_learned_policy() works", custom_config.is_learned_policy() == True)
    
    # 3. 全局配置设置/获取
    set_optimization_config(custom_config)
    retrieved = get_optimization_config()
    print_result("Global config round-trip", retrieved.enabled == True and retrieved.scheduler_policy == "learned")
    
    # 4. to_dict 序列化
    config_dict = custom_config.to_dict()
    print_result("to_dict() works", "enabled" in config_dict and "policy_params" in config_dict)
    print(f"         Config dict: {config_dict}")
    
    return custom_config


async def test_statistics_models():
    """测试 V2.7 统计模型"""
    print_section("Test 2: Statistics Models (NodeStatistics, SkillStatistics)")
    
    from execution_kernel.optimization.statistics.models import NodeStatistics, SkillStatistics
    
    # 1. NodeStatistics
    node_stats = NodeStatistics(
        node_id="node_tool_1",
        skill_name="builtin_file.read",
        execution_count=100,
        success_count=80,
        failure_count=20,
        total_latency_ms=10000.0,
    )
    
    print_result("NodeStatistics created", node_stats.node_id == "node_tool_1")
    print_result("success_rate computed", node_stats.success_rate == 0.8)
    print_result("avg_latency_ms computed", node_stats.avg_latency_ms == 100.0)
    print(f"         Node stats: execution_count={node_stats.execution_count}, success_rate={node_stats.success_rate:.2f}")
    
    # 2. SkillStatistics
    skill_stats = SkillStatistics(
        skill_name="builtin_file.read",
        execution_count=60,
        success_count=50,
        failure_count=10,
        total_latency_ms=5000.0,
        node_count=5,
    )
    
    print_result("SkillStatistics created", skill_stats.skill_name == "builtin_file.read")
    print_result("success_rate computed", abs(skill_stats.success_rate - 50/60) < 0.01)
    print_result("avg_latency_ms computed", skill_stats.avg_latency_ms == 5000.0/60)
    print(f"         Skill stats: execution_count={skill_stats.execution_count}, success_rate={skill_stats.success_rate:.2f}")
    
    return node_stats, skill_stats


async def test_optimization_dataset():
    """测试 V2.7 OptimizationDataset"""
    print_section("Test 3: OptimizationDataset")
    
    from execution_kernel.optimization.statistics.models import NodeStatistics, SkillStatistics
    from execution_kernel.optimization.statistics.dataset import OptimizationDataset
    
    # 创建数据集
    node_stats_1 = NodeStatistics(
        node_id="node_tool_1", 
        skill_name="builtin_file.read",
        execution_count=100, 
        success_count=80, 
        failure_count=20, 
        total_latency_ms=10000.0
    )
    node_stats_2 = NodeStatistics(
        node_id="node_script_1", 
        execution_count=100, 
        success_count=90, 
        failure_count=10, 
        total_latency_ms=20000.0
    )
    skill_stats = SkillStatistics(
        skill_name="builtin_file.read", 
        execution_count=55, 
        success_count=50, 
        failure_count=5, 
        total_latency_ms=5000.0
    )
    
    dataset = OptimizationDataset(
        node_stats={
            "node_tool_1": node_stats_1,
            "node_script_1": node_stats_2,
        },
        skill_stats={
            "builtin_file.read": skill_stats,
        },
        event_count=100,
        instance_count=10,
    )
    
    print_result("Dataset created", len(dataset.node_stats) == 2)
    print_result("Event count", dataset.event_count == 100)
    
    # 测试 merge
    node_stats_3 = NodeStatistics(
        node_id="node_tool_1", 
        execution_count=25, 
        success_count=20, 
        failure_count=5, 
        total_latency_ms=3000.0
    )
    dataset2 = OptimizationDataset(
        node_stats={"node_tool_1": node_stats_3},
        event_count=25,
        instance_count=2,
    )
    
    merged = dataset.merge(dataset2)
    print_result("Merge works", merged.event_count == 125)
    print_result("Merge combines instance_count", merged.instance_count == 12)
    print_result("Merge combines node stats", "node_tool_1" in merged.node_stats)
    
    return dataset


async def test_snapshot_builder():
    """测试 V2.7 SnapshotBuilder 和 OptimizationSnapshot"""
    print_section("Test 4: SnapshotBuilder & OptimizationSnapshot")
    
    from execution_kernel.optimization.statistics.models import NodeStatistics, SkillStatistics
    from execution_kernel.optimization.statistics.dataset import OptimizationDataset
    from execution_kernel.optimization.snapshot import SnapshotBuilder, OptimizationSnapshot
    
    # 创建数据集
    node_stats = NodeStatistics(
        node_id="node_tool_1", 
        skill_name="builtin_file.read",
        execution_count=100, 
        success_count=80, 
        failure_count=20, 
        total_latency_ms=10000.0
    )
    skill_stats = SkillStatistics(
        skill_name="builtin_file.read", 
        execution_count=55, 
        success_count=50, 
        failure_count=5, 
        total_latency_ms=5000.0
    )
    
    dataset = OptimizationDataset(
        node_stats={"node_tool_1": node_stats, "node_script_1": node_stats},
        skill_stats={"builtin_file.read": skill_stats},
        event_count=100,
        instance_count=10,
    )
    
    # 构建快照
    builder = SnapshotBuilder()
    snapshot = builder.build(dataset)
    
    print_result("Snapshot created", snapshot is not None)
    print_result("Snapshot has version", snapshot.version is not None)
    print_result("Snapshot has node_weights", len(snapshot.node_weights) == 2)
    print_result("Snapshot has skill_weights", len(snapshot.skill_weights) == 1)
    print_result("Snapshot has metadata", snapshot.metadata is not None)
    
    print(f"         Snapshot version: {snapshot.version}")
    print(f"         Node weights: {dict(snapshot.node_weights)}")
    print(f"         Skill weights: {dict(snapshot.skill_weights)}")
    
    # 测试空快照
    empty = OptimizationSnapshot.empty()
    print_result("Empty snapshot works", empty.version == "empty_00000000")
    print_result("Empty snapshot has empty weights", len(empty.node_weights) == 0)
    
    # 测试 get_node_weight / get_skill_weight
    tool_weight = snapshot.get_node_weight("node_tool_1")
    print_result("get_node_weight works", tool_weight > 0, f"node_tool_1 weight={tool_weight:.4f}")
    
    skill_weight = snapshot.get_skill_weight("builtin_file.read")
    print_result("get_skill_weight works", skill_weight > 0, f"skill_weight={skill_weight:.4f}")
    
    # 测试未知节点（返回默认值 1.0）
    unknown_weight = snapshot.get_node_weight("unknown_node")
    print_result("get_node_weight returns default 1.0", unknown_weight == 1.0)
    
    return snapshot


async def test_scheduler_policies():
    """测试 V2.7 DefaultPolicy 和 LearnedPolicy"""
    print_section("Test 5: SchedulerPolicies (DefaultPolicy, LearnedPolicy)")
    
    from execution_kernel.optimization.scheduler import DefaultPolicy, LearnedPolicy, PolicyContext
    from execution_kernel.optimization.snapshot import OptimizationSnapshot
    from execution_kernel.models.graph_definition import NodeDefinition, NodeType
    
    # 创建测试快照
    from execution_kernel.optimization.statistics.models import NodeStatistics, SkillStatistics
    from execution_kernel.optimization.statistics.dataset import OptimizationDataset
    from execution_kernel.optimization.snapshot import SnapshotBuilder
    
    node_stats = NodeStatistics(
        node_id="node_tool_1", 
        execution_count=100, 
        success_count=80, 
        failure_count=20, 
        total_latency_ms=10000.0
    )
    dataset = OptimizationDataset(
        node_stats={"node_tool_1": node_stats},
        event_count=100,
        instance_count=10,
    )
    builder = SnapshotBuilder()
    snapshot = builder.build(dataset)
    
    # 创建测试节点
    nodes = [
        NodeDefinition(id="node_a", type=NodeType.TOOL, config={"skill_id": "builtin_file.read"}),
        NodeDefinition(id="node_b", type=NodeType.TOOL, config={"skill_id": "builtin_file.write"}),
        NodeDefinition(id="node_c", type=NodeType.SCRIPT, config={}),
    ]
    
    # 1. DefaultPolicy
    default_policy = DefaultPolicy()
    print_result("DefaultPolicy created", default_policy is not None)
    print_result("DefaultPolicy get_name", default_policy.get_name() == "DefaultPolicy")
    print_result("DefaultPolicy get_version", default_policy.get_version() == "default_1.0.0")
    
    # 创建空的 PolicyContext（PolicyContext 不包含 snapshot，snapshot 作为单独参数传入）
    from execution_kernel.models.graph_definition import GraphDefinition
    dummy_graph = GraphDefinition(
        id="test_graph",
        nodes=nodes,
        edges=[],
    )
    ctx = PolicyContext.create_empty("test_instance", dummy_graph)
    sorted_nodes_default = default_policy.sort_nodes(nodes, ctx, snapshot)
    print_result("DefaultPolicy sort_nodes works", len(sorted_nodes_default) == 3)
    # DefaultPolicy 应该保持拓扑顺序，不做重排
    print(f"         Default order: {[n.id for n in sorted_nodes_default]}")
    
    # 2. LearnedPolicy
    learned_policy = LearnedPolicy(
        node_weight_factor=10.0,
        latency_penalty_factor=1.0,
        skill_weight_factor=2.0,
        consider_skill=True,
    )
    print_result("LearnedPolicy created", learned_policy is not None)
    print_result("LearnedPolicy get_name", learned_policy.get_name() == "LearnedPolicy")
    
    version = learned_policy.get_version()
    print_result("LearnedPolicy get_version has hash", "learned_1.0.0_" in version, f"version={version}")
    
    sorted_nodes_learned = learned_policy.sort_nodes(nodes, ctx, snapshot)
    print_result("LearnedPolicy sort_nodes works", len(sorted_nodes_learned) == 3)
    print(f"         Learned order: {[n.id for n in sorted_nodes_learned]}")
    
    # 3. 验证版本包含参数哈希
    learned_policy_2 = LearnedPolicy(
        node_weight_factor=20.0,  # 不同参数
        latency_penalty_factor=1.0,
        skill_weight_factor=2.0,
        consider_skill=True,
    )
    version_2 = learned_policy_2.get_version()
    print_result("Different params produce different version", version != version_2)
    print(f"         Version 1: {version}")
    print(f"         Version 2: {version_2}")
    
    return default_policy, learned_policy


async def test_scheduler_with_policy():
    """测试 V2.7 Scheduler 集成策略"""
    print_section("Test 6: Scheduler with Policy Integration")
    
    from execution_kernel.models.graph_definition import GraphDefinition, NodeDefinition, EdgeDefinition, NodeType
    from execution_kernel.persistence.db import init_database, get_platform_db_path
    from execution_kernel.persistence.repositories import NodeCacheRepository
    from execution_kernel.engine.state_machine import StateMachine
    from execution_kernel.engine.executor import Executor
    from execution_kernel.engine.scheduler import Scheduler
    from execution_kernel.optimization.scheduler import DefaultPolicy, LearnedPolicy
    from execution_kernel.optimization.snapshot import OptimizationSnapshot
    
    # 初始化数据库
    db_path = get_platform_db_path()
    db_url = f"sqlite+aiosqlite:///{db_path}"
    db = init_database(db_url)
    await db.create_tables()
    
    # 创建简单图
    graph = GraphDefinition(
        id="test_v27_graph",
        nodes=[
            NodeDefinition(id="node_1", type=NodeType.TOOL, config={"skill_id": "test_skill"}),
            NodeDefinition(id="node_2", type=NodeType.TOOL, config={"skill_id": "test_skill"}),
        ],
        edges=[
            EdgeDefinition(from_node="node_1", to_node="node_2"),
        ],
    )
    
    # 创建快照
    snapshot = OptimizationSnapshot.empty()
    
    # 创建策略
    policy = DefaultPolicy()
    
    # 创建 Scheduler（带策略和快照）
    async with db.async_session() as session:
        cache_repo = NodeCacheRepository(session)
        from execution_kernel.cache.node_cache import NodeCache
        cache = NodeCache(cache_repo)
        
        state_machine = StateMachine(db=db)
        
        scheduler = Scheduler(
            db=db,
            state_machine=state_machine,
            executor=None,
            scheduler_policy=policy,
            optimization_snapshot=snapshot,
        )
        
        print_result("Scheduler created with policy", scheduler is not None)
        print_result("Scheduler has policy", scheduler._scheduler_policy is not None)
        print_result("Scheduler has snapshot", scheduler._optimization_snapshot is not None)
        
        # 测试 get_scheduler_policy_info
        info = scheduler.get_scheduler_policy_info()
        print_result("get_scheduler_policy_info works", "policy_name" in info and "policy_version" in info)
        print(f"         Policy info: {info}")
    
    # 测试动态切换策略
    learned_policy = LearnedPolicy(
        node_weight_factor=15.0,
        latency_penalty_factor=2.0,
    )
    scheduler.set_scheduler_policy(learned_policy, snapshot)
    
    info_after = scheduler.get_scheduler_policy_info()
    print_result("Policy switch works", info_after["policy_name"] == "LearnedPolicy")
    print(f"         New policy info: {info_after}")
    
    await db.close()
    return True


async def test_kernel_adapter_integration():
    """测试 V2.7 ExecutionKernelAdapter 集成"""
    print_section("Test 7: ExecutionKernelAdapter Integration")
    
    from core.execution.adapters.kernel_adapter import ExecutionKernelAdapter
    from execution_kernel.optimization import OptimizationConfig
    
    # 1. 创建带优化配置的 Adapter
    config = OptimizationConfig(
        enabled=True,
        scheduler_policy="learned",
        policy_params={
            "node_weight_factor": 10.0,
            "latency_penalty_factor": 1.5,
        },
    )
    
    adapter = ExecutionKernelAdapter(optimization_config=config)
    print_result("Adapter created with config", adapter is not None)
    print_result("Adapter has config", adapter._optimization_config is not None)
    
    # 2. 初始化（会初始化策略）
    await adapter.initialize()
    print_result("Adapter initialized", adapter._initialized)
    print_result("Policy initialized", adapter._scheduler_policy is not None)
    print_result("Policy is LearnedPolicy", adapter._scheduler_policy.get_name() == "LearnedPolicy")
    
    # 3. 获取优化状态
    status = adapter.get_optimization_status()
    print_result("get_optimization_status works", "enabled" in status)
    print_result("Status has policy info", "scheduler_policy" in status)
    print(f"         Status: {status}")
    
    # 4. 测试动态切换策略
    from execution_kernel.optimization import DefaultPolicy
    adapter.set_scheduler_policy(DefaultPolicy())
    
    status_after = adapter.get_optimization_status()
    print_result("Policy switched to DefaultPolicy", status_after["scheduler_policy"]["name"] == "DefaultPolicy")
    
    # 5. 测试配置更新
    new_config = OptimizationConfig(
        enabled=False,
        scheduler_policy="default",
    )
    adapter.set_optimization_config(new_config)
    print_result("Config updated", adapter._optimization_config.enabled == False)
    
    await adapter.close()
    return True


async def test_event_payload_builders():
    """测试 V2.7 事件负载构建器"""
    print_section("Test 8: V2.7 Event Payload Builders")
    
    from execution_kernel.events.event_model import EventPayloadBuilder
    from execution_kernel.events.event_types import ExecutionEventType, OPTIMIZATION_EVENTS
    
    # 1. scheduler_decision with policy versions
    scheduler_payload = EventPayloadBuilder.scheduler_decision(
        ready_nodes=["node_a", "node_b"],
        selected_node="node_a",
        strategy="LearnedPolicy",
        decision_reason="Highest score",
        policy_version="learned_1.0.0_abc12345",
        snapshot_version="snap_def456",
    )
    print_result("scheduler_decision with versions", "policy_version" in scheduler_payload)
    print_result("snapshot_version present", "snapshot_version" in scheduler_payload)
    print(f"         Payload: {scheduler_payload}")
    
    # 2. snapshot_built
    snapshot_payload = EventPayloadBuilder.snapshot_built(
        snapshot_version="snap_abc123",
        node_count=15,
        skill_count=8,
        event_count=500,
        source="global",
    )
    print_result("snapshot_built payload", snapshot_payload["snapshot_version"] == "snap_abc123")
    
    # 3. policy_changed
    policy_payload = EventPayloadBuilder.policy_changed(
        policy_name="LearnedPolicy",
        policy_version="learned_1.0.0_abc12345",
        previous_policy="DefaultPolicy",
        previous_version="default_1.0.0",
        snapshot_version="snap_abc123",
    )
    print_result("policy_changed payload", policy_payload["policy_name"] == "LearnedPolicy")
    
    # 4. statistics_collected
    stats_payload = EventPayloadBuilder.statistics_collected(
        instance_ids=["inst_001", "inst_002"],
        total_events=500,
        node_types=5,
        skill_ids=8,
    )
    print_result("statistics_collected payload", stats_payload["total_events"] == 500)
    
    # 5. 验证事件类型
    print_result("SNAPSHOT_BUILT event type exists", ExecutionEventType.SNAPSHOT_BUILT.value == "snapshot_built")
    print_result("POLICY_CHANGED event type exists", ExecutionEventType.POLICY_CHANGED.value == "policy_changed")
    print_result("STATISTICS_COLLECTED event type exists", ExecutionEventType.STATISTICS_COLLECTED.value == "statistics_collected")
    print_result("OPTIMIZATION_EVENTS group exists", len(OPTIMIZATION_EVENTS) == 3)
    
    return True


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print(" V2.7 Optimization Layer Integration Test Suite")
    print("="*60)
    
    results = []
    
    try:
        await test_optimization_config()
        results.append(("OptimizationConfig", True))
    except Exception as e:
        print(f"  ❌ FAIL - OptimizationConfig: {e}")
        results.append(("OptimizationConfig", False))
    
    try:
        await test_statistics_models()
        results.append(("Statistics Models", True))
    except Exception as e:
        print(f"  ❌ FAIL - Statistics Models: {e}")
        results.append(("Statistics Models", False))
    
    try:
        await test_optimization_dataset()
        results.append(("OptimizationDataset", True))
    except Exception as e:
        print(f"  ❌ FAIL - OptimizationDataset: {e}")
        results.append(("OptimizationDataset", False))
    
    try:
        await test_snapshot_builder()
        results.append(("SnapshotBuilder", True))
    except Exception as e:
        print(f"  ❌ FAIL - SnapshotBuilder: {e}")
        results.append(("SnapshotBuilder", False))
    
    try:
        await test_scheduler_policies()
        results.append(("SchedulerPolicies", True))
    except Exception as e:
        print(f"  ❌ FAIL - SchedulerPolicies: {e}")
        results.append(("SchedulerPolicies", False))
    
    try:
        await test_scheduler_with_policy()
        results.append(("Scheduler Integration", True))
    except Exception as e:
        print(f"  ❌ FAIL - Scheduler Integration: {e}")
        results.append(("Scheduler Integration", False))
    
    try:
        await test_kernel_adapter_integration()
        results.append(("KernelAdapter Integration", True))
    except Exception as e:
        print(f"  ❌ FAIL - KernelAdapter Integration: {e}")
        results.append(("KernelAdapter Integration", False))
    
    try:
        await test_event_payload_builders()
        results.append(("Event Payload Builders", True))
    except Exception as e:
        print(f"  ❌ FAIL - Event Payload Builders: {e}")
        results.append(("Event Payload Builders", False))
    
    # 汇总结果
    print_section("Test Summary")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    print(f"\n  Total: {passed}/{total} tests passed")
    print(f"\n  Details:")
    for name, success in results:
        status = "✅" if success else "❌"
        print(f"    {status} {name}")
    
    print("\n" + "="*60)
    if passed == total:
        print(" 🎉 All V2.7 tests passed!")
    else:
        print(f" ⚠️  {total - passed} test(s) failed")
    print("="*60 + "\n")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
