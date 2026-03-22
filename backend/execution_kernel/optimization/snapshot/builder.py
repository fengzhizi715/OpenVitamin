"""
V2.7: Optimization Layer - Snapshot Builder

从 OptimizationDataset 构建 OptimizationSnapshot
"""

import hashlib
import json
import logging
from typing import Dict, Optional
from datetime import datetime

from execution_kernel.optimization.statistics.dataset import OptimizationDataset
from execution_kernel.optimization.statistics.models import NodeStatistics, SkillStatistics
from execution_kernel.optimization.snapshot.snapshot import OptimizationSnapshot


logger = logging.getLogger(__name__)


class SnapshotBuilder:
    """
    快照构建器
    
    将 OptimizationDataset 转换为 OptimizationSnapshot
    
    职责：
    - 计算节点权重
    - 计算 Skill 权重
    - 估计延迟
    - 生成版本化、不可变的快照
    
    权重计算策略：
    - 节点权重基于成功率和执行频率
    - Skill 权重基于全局成功率
    - 延迟估计基于历史平均延迟
    """
    
    def __init__(
        self,
        success_weight: float = 0.6,
        frequency_weight: float = 0.4,
        latency_penalty_factor: float = 0.001,
    ):
        """
        初始化构建器
        
        Args:
            success_weight: 成功率在权重计算中的权重
            frequency_weight: 执行频率在权重计算中的权重
            latency_penalty_factor: 延迟惩罚因子（每毫秒延迟的惩罚）
        """
        self.success_weight = success_weight
        self.frequency_weight = frequency_weight
        self.latency_penalty_factor = latency_penalty_factor
    
    def build(self, dataset: OptimizationDataset) -> OptimizationSnapshot:
        """
        从数据集构建快照
        
        Args:
            dataset: 优化数据集
            
        Returns:
            OptimizationSnapshot
        """
        if not dataset.node_stats and not dataset.skill_stats:
            logger.debug("Building empty snapshot from empty dataset")
            return OptimizationSnapshot.empty()
        
        # 计算数据集哈希
        dataset_hash = self._compute_dataset_hash(dataset)
        
        # 计算节点权重
        node_weights = self._compute_node_weights(dataset)
        
        # 计算 Skill 权重
        skill_weights = self._compute_skill_weights(dataset)
        
        # 计算延迟估计
        latency_estimates = self._compute_latency_estimates(dataset)
        
        # 构建快照数据
        snapshot_data = {
            "node_weights": node_weights,
            "skill_weights": skill_weights,
            "latency_estimates": latency_estimates,
            "source_dataset_hash": dataset_hash,
            "metadata": {
                "node_count": len(node_weights),
                "skill_count": len(skill_weights),
                "source_event_count": dataset.event_count,
                "source_instance_count": dataset.instance_count,
                "success_weight": self.success_weight,
                "frequency_weight": self.frequency_weight,
            },
        }
        
        # 计算版本
        version = OptimizationSnapshot.compute_version(snapshot_data)
        
        return OptimizationSnapshot(
            version=version,
            created_at=datetime.utcnow(),
            node_weights=node_weights,
            skill_weights=skill_weights,
            latency_estimates=latency_estimates,
            source_dataset_hash=dataset_hash,
            metadata=snapshot_data["metadata"],
        )
    
    def _compute_node_weights(self, dataset: OptimizationDataset) -> Dict[str, float]:
        """
        计算节点权重
        
        权重公式：
        weight = (success_rate * success_weight) + (normalized_frequency * frequency_weight)
        
        其中 normalized_frequency 是当前节点执行次数 / 最大执行次数
        """
        if not dataset.node_stats:
            return {}
        
        # 计算最大执行次数用于归一化
        max_execution_count = max(
            (stat.execution_count for stat in dataset.node_stats.values()),
            default=1,
        )
        
        weights = {}
        for node_id, stat in dataset.node_stats.items():
            # 成功率分量
            success_component = stat.success_rate * self.success_weight
            
            # 频率分量（归一化）
            frequency_component = 0.0
            if max_execution_count > 0:
                frequency_component = (
                    stat.execution_count / max_execution_count * self.frequency_weight
                )
            
            # 基础权重
            base_weight = success_component + frequency_component
            
            # 确保权重在合理范围内
            weights[node_id] = round(max(0.1, min(10.0, base_weight)), 4)
        
        return weights
    
    def _compute_skill_weights(self, dataset: OptimizationDataset) -> Dict[str, float]:
        """
        计算 Skill 权重
        
        基于全局成功率，用于跨节点的 Skill 优先级调整
        """
        if not dataset.skill_stats:
            return {}
        
        weights = {}
        for skill_name, stat in dataset.skill_stats.items():
            # 基于成功率计算权重
            # 成功率越高，权重越高
            base_weight = 0.5 + (stat.success_rate * 0.5)
            
            # 考虑重试成功率（如果有失败记录）
            if stat.failure_count > 0:
                retry_bonus = stat.retry_success_rate * 0.2
                base_weight += retry_bonus
            
            weights[skill_name] = round(max(0.1, min(2.0, base_weight)), 4)
        
        return weights
    
    def _compute_latency_estimates(
        self,
        dataset: OptimizationDataset,
    ) -> Dict[str, float]:
        """
        计算延迟估计
        
        使用历史平均延迟作为估计值
        """
        estimates = {}
        
        for node_id, stat in dataset.node_stats.items():
            if stat.avg_latency_ms > 0:
                estimates[node_id] = round(stat.avg_latency_ms, 2)
        
        return estimates
    
    def _compute_dataset_hash(self, dataset: OptimizationDataset) -> str:
        """
        计算数据集的内容哈希
        
        用于追踪快照的数据来源
        """
        data = {
            "node_stats": {
                node_id: stat.to_dict()
                for node_id, stat in dataset.node_stats.items()
            },
            "skill_stats": {
                skill_name: stat.to_dict()
                for skill_name, stat in dataset.skill_stats.items()
            },
            "event_count": dataset.event_count,
            "instance_count": dataset.instance_count,
        }
        
        json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
        hash_value = hashlib.sha256(json_str.encode('utf-8')).hexdigest()
        
        return hash_value[:16]
    
    def build_with_custom_weights(
        self,
        dataset: OptimizationDataset,
        custom_node_weights: Optional[Dict[str, float]] = None,
        custom_skill_weights: Optional[Dict[str, float]] = None,
    ) -> OptimizationSnapshot:
        """
        使用自定义权重构建快照
        
        用于手动调整权重或注入外部知识
        """
        snapshot = self.build(dataset)
        
        # 合并自定义权重
        final_node_weights = dict(snapshot.node_weights)
        if custom_node_weights:
            final_node_weights.update(custom_node_weights)
        
        final_skill_weights = dict(snapshot.skill_weights)
        if custom_skill_weights:
            final_skill_weights.update(custom_skill_weights)
        
        # 重新计算版本
        snapshot_data = {
            "node_weights": final_node_weights,
            "skill_weights": final_skill_weights,
            "latency_estimates": snapshot.latency_estimates,
            "source_dataset_hash": snapshot.source_dataset_hash,
            "metadata": {
                **snapshot.metadata,
                "custom_weights_applied": True,
            },
        }
        
        version = OptimizationSnapshot.compute_version(snapshot_data)
        
        return OptimizationSnapshot(
            version=version,
            created_at=datetime.utcnow(),
            node_weights=final_node_weights,
            skill_weights=final_skill_weights,
            latency_estimates=snapshot.latency_estimates,
            source_dataset_hash=snapshot.source_dataset_hash,
            metadata=snapshot_data["metadata"],
        )
    
    async def build_and_persist(
        self,
        dataset: OptimizationDataset,
        repository,
    ) -> OptimizationSnapshot:
        """
        V2.7: 构建快照并持久化
        
        Args:
            dataset: OptimizationDataset 实例
            repository: OptimizationSnapshotRepository 实例
            
        Returns:
            OptimizationSnapshot
        """
        # 构建快照
        snapshot = self.build(dataset)
        
        # 持久化到数据库
        try:
            await repository.save(snapshot)
            logger.info(f"V2.7: Snapshot v{snapshot.version} persisted to database")
        except Exception as e:
            logger.warning(f"V2.7: Failed to persist snapshot: {e}")
        
        return snapshot
