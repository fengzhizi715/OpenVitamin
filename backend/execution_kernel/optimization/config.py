"""
V2.7: Optimization Layer - Configuration

优化层配置管理
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field
import os


@dataclass
class OptimizationConfig:
    """
    优化层配置
    
    Attributes:
        enabled: 是否启用优化层
        scheduler_policy: 调度策略名称 (default | learned)
        snapshot_version: 指定快照版本（None 表示使用最新）
        auto_build_snapshot: 是否自动构建快照
        collect_statistics: 是否收集统计信息
        policy_params: 策略参数
    """
    enabled: bool = False
    scheduler_policy: str = "default"
    snapshot_version: Optional[str] = None
    auto_build_snapshot: bool = True
    collect_statistics: bool = True
    policy_params: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_env(cls) -> "OptimizationConfig":
        """从环境变量加载配置"""
        return cls(
            enabled=os.getenv("EXECUTION_KERNEL_OPTIMIZATION_ENABLED", "false").lower() == "true",
            scheduler_policy=os.getenv("EXECUTION_KERNEL_SCHEDULER_POLICY", "default"),
            snapshot_version=os.getenv("EXECUTION_KERNEL_SNAPSHOT_VERSION") or None,
            auto_build_snapshot=os.getenv("EXECUTION_KERNEL_AUTO_BUILD_SNAPSHOT", "true").lower() == "true",
            collect_statistics=os.getenv("EXECUTION_KERNEL_COLLECT_STATISTICS", "true").lower() == "true",
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OptimizationConfig":
        """从字典加载配置"""
        return cls(
            enabled=data.get("enabled", False),
            scheduler_policy=data.get("scheduler_policy", "default"),
            snapshot_version=data.get("snapshot_version"),
            auto_build_snapshot=data.get("auto_build_snapshot", True),
            collect_statistics=data.get("collect_statistics", True),
            policy_params=data.get("policy_params", {}),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "scheduler_policy": self.scheduler_policy,
            "snapshot_version": self.snapshot_version,
            "auto_build_snapshot": self.auto_build_snapshot,
            "collect_statistics": self.collect_statistics,
            "policy_params": self.policy_params,
        }
    
    def is_learned_policy(self) -> bool:
        """是否使用学习型策略"""
        return self.scheduler_policy == "learned"
    
    def is_default_policy(self) -> bool:
        """是否使用默认策略"""
        return self.scheduler_policy == "default"


# 全局配置实例
_optimization_config: Optional[OptimizationConfig] = None


def get_optimization_config() -> OptimizationConfig:
    """获取优化层配置"""
    global _optimization_config
    if _optimization_config is None:
        _optimization_config = OptimizationConfig.from_env()
    return _optimization_config


def set_optimization_config(config: OptimizationConfig) -> None:
    """设置优化层配置"""
    global _optimization_config
    _optimization_config = config


def reset_optimization_config() -> None:
    """重置优化层配置"""
    global _optimization_config
    _optimization_config = None
