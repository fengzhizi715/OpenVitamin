"""
V2.7: Optimization Layer - Snapshot Module

生成不可变、版本化的 OptimizationSnapshot
"""

from execution_kernel.optimization.snapshot.snapshot import OptimizationSnapshot
from execution_kernel.optimization.snapshot.builder import SnapshotBuilder

__all__ = [
    "OptimizationSnapshot",
    "SnapshotBuilder",
]
