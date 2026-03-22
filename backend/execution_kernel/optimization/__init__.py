"""
V2.7: Optimization Layer

旁路优化层，为 Execution Kernel 提供:
- 执行统计收集
- 优化快照生成
- 调度策略插件
- 安全重规划

设计原则:
- Kernel 不学习，只读取 OptimizationSnapshot
- Optimization Layer 是旁路系统，不影响核心执行
- Replay 必须 deterministic，需记录 policy_version 和 snapshot_version
"""

__version__ = "2.7.0"

from execution_kernel.optimization.config import (
    OptimizationConfig,
    get_optimization_config,
    set_optimization_config,
)
from execution_kernel.optimization.statistics.models import NodeStatistics, SkillStatistics
from execution_kernel.optimization.statistics.dataset import OptimizationDataset
from execution_kernel.optimization.statistics.collector import StatisticsCollector
from execution_kernel.optimization.snapshot.snapshot import OptimizationSnapshot
from execution_kernel.optimization.snapshot.builder import SnapshotBuilder
from execution_kernel.optimization.scheduler.policy_base import SchedulerPolicy, PolicyContext
from execution_kernel.optimization.scheduler.default_policy import DefaultPolicy
from execution_kernel.optimization.scheduler.learned_policy import LearnedPolicy
from execution_kernel.optimization.replanner.replanner import Replanner, ReplanRecord

__all__ = [
    # Config
    "OptimizationConfig",
    "get_optimization_config",
    "set_optimization_config",
    # Statistics
    "NodeStatistics",
    "SkillStatistics",
    "OptimizationDataset",
    "StatisticsCollector",
    # Snapshot
    "OptimizationSnapshot",
    "SnapshotBuilder",
    # Scheduler Policy
    "SchedulerPolicy",
    "PolicyContext",
    "DefaultPolicy",
    "LearnedPolicy",
    # Replanner
    "Replanner",
    "ReplanRecord",
]
