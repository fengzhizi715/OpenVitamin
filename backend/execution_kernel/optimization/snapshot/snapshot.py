"""
V2.7: Optimization Layer - Optimization Snapshot

Kernel 可读的唯一优化数据源
"""

from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json


@dataclass(frozen=True)
class OptimizationSnapshot:
    """
    优化快照
    
    Kernel 允许读取的唯一优化数据源。
    不可变、版本化、Replay-safe。
    
    数据流：
    ExecutionEvent → StatisticsCollector → OptimizationDataset → 
    SnapshotBuilder → OptimizationSnapshot → SchedulerPolicy
    
    Attributes:
        version: 快照版本（基于内容哈希）
        created_at: 创建时间
        node_weights: 节点权重 {node_id: weight}
        skill_weights: Skill 权重 {skill_name: weight}
        latency_estimates: 延迟估计（毫秒）{node_id: latency_ms}
        source_dataset_hash: 来源数据集的哈希
        metadata: 额外元数据
    """
    version: str
    created_at: datetime
    node_weights: Dict[str, float] = field(default_factory=dict)
    skill_weights: Dict[str, float] = field(default_factory=dict)
    latency_estimates: Dict[str, float] = field(default_factory=dict)
    source_dataset_hash: str = ""
    metadata: Dict[str, any] = field(default_factory=dict)
    
    def get_node_weight(self, node_id: str) -> float:
        """
        获取节点权重
        
        Returns:
            权重值（默认 1.0）
        """
        return self.node_weights.get(node_id, 1.0)
    
    def get_skill_weight(self, skill_name: str) -> float:
        """
        获取 Skill 权重
        
        Returns:
            权重值（默认 1.0）
        """
        return self.skill_weights.get(skill_name, 1.0)
    
    def get_latency_estimate(self, node_id: str) -> float:
        """
        获取节点延迟估计
        
        Returns:
            延迟估计（毫秒，默认 0.0）
        """
        return self.latency_estimates.get(node_id, 0.0)
    
    def has_node(self, node_id: str) -> bool:
        """检查是否有指定节点的数据"""
        return node_id in self.node_weights or node_id in self.latency_estimates
    
    def has_skill(self, skill_name: str) -> bool:
        """检查是否有指定 Skill 的数据"""
        return skill_name in self.skill_weights
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "node_weights": self.node_weights,
            "skill_weights": self.skill_weights,
            "latency_estimates": self.latency_estimates,
            "source_dataset_hash": self.source_dataset_hash,
            "metadata": self.metadata,
        }
    
    @staticmethod
    def compute_version(data: dict) -> str:
        """
        计算快照版本（基于内容哈希）
        
        确保相同内容产生相同的 version，支持 Replay determinism
        """
        # 排除 created_at 和 version 本身
        hash_data = {
            "node_weights": data.get("node_weights", {}),
            "skill_weights": data.get("skill_weights", {}),
            "latency_estimates": data.get("latency_estimates", {}),
            "source_dataset_hash": data.get("source_dataset_hash", ""),
            "metadata": data.get("metadata", {}),
        }
        
        # 使用 JSON 序列化后计算哈希
        json_str = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
        hash_value = hashlib.sha256(json_str.encode('utf-8')).hexdigest()
        
        # 返回前 16 位作为版本号
        return hash_value[:16]
    
    @classmethod
    def empty(cls) -> "OptimizationSnapshot":
        """创建空快照"""
        return cls(
            version="empty_00000000",
            created_at=datetime.utcnow(),
            node_weights={},
            skill_weights={},
            latency_estimates={},
            source_dataset_hash="",
            metadata={"empty": True},
        )
