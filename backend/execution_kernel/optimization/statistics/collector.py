"""
V2.7: Optimization Layer - Statistics Collector

从 ExecutionEvent 收集统计信息，生成 OptimizationDataset
"""

from typing import Dict, List, Optional
from datetime import datetime
from collections import defaultdict
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from execution_kernel.events.event_store import EventStore
from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.optimization.statistics.models import NodeStatistics, SkillStatistics
from execution_kernel.optimization.statistics.dataset import OptimizationDataset


logger = logging.getLogger(__name__)


class StatisticsCollector:
    """
    统计收集器
    
    从 ExecutionEvent 流中收集节点和 Skill 的执行统计
    
    职责：
    - 从 EventStore 读取事件
    - 统计每个节点和 Skill 的执行数据
    - 生成 OptimizationDataset
    
    注意：
    - 只读取事件，不修改事件
    - 可以按实例、按时间范围或全局收集
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.event_store = EventStore(session)
    
    async def collect_from_instance(
        self,
        instance_id: str,
        start_sequence: int = 1,
        end_sequence: Optional[int] = None,
    ) -> OptimizationDataset:
        """
        从指定实例收集统计信息
        
        Args:
            instance_id: 图实例 ID
            start_sequence: 起始序列号
            end_sequence: 结束序列号（None 表示到最后）
            
        Returns:
            OptimizationDataset
        """
        events = await self.event_store.get_events(
            instance_id=instance_id,
            start_sequence=start_sequence,
            end_sequence=end_sequence,
        )
        
        if not events:
            logger.debug(f"No events found for instance {instance_id}")
            return OptimizationDataset(
                created_at=datetime.utcnow(),
                event_count=0,
                instance_count=1,
            )
        
        node_stats = self._collect_node_stats(events)
        skill_stats = self._collect_skill_stats(node_stats)
        
        return OptimizationDataset(
            node_stats=node_stats,
            skill_stats=skill_stats,
            created_at=datetime.utcnow(),
            event_count=len(events),
            instance_count=1,
        )
    
    async def collect_from_instances(
        self,
        instance_ids: List[str],
    ) -> OptimizationDataset:
        """
        从多个实例收集统计信息
        
        Args:
            instance_ids: 图实例 ID 列表
            
        Returns:
            合并后的 OptimizationDataset
        """
        datasets = []
        for instance_id in instance_ids:
            dataset = await self.collect_from_instance(instance_id)
            datasets.append(dataset)
        
        # 合并所有数据集
        if not datasets:
            return OptimizationDataset(
                created_at=datetime.utcnow(),
                event_count=0,
                instance_count=0,
            )
        
        merged = datasets[0]
        for dataset in datasets[1:]:
            merged = merged.merge(dataset)
        
        return merged
    
    async def collect_global(
        self,
        limit_instances: int = 1000,
    ) -> OptimizationDataset:
        """
        从所有可用实例收集统计信息
        
        注意：此方法会查询所有实例的事件，可能耗时较长
        
        Args:
            limit_instances: 最大实例数量限制
            
        Returns:
            OptimizationDataset
        """
        # 获取所有有事件的实例 ID
        instance_ids = await self._get_instance_ids_with_events(limit_instances)
        
        if not instance_ids:
            return OptimizationDataset(
                created_at=datetime.utcnow(),
                event_count=0,
                instance_count=0,
            )
        
        return await self.collect_from_instances(instance_ids)
    
    async def collect_with_metrics(
        self,
        instance_ids: List[str],
    ) -> OptimizationDataset:
        """
        V2.7: 收集统计信息并计算指标
        
        使用 MetricsCalculator 计算每个实例的指标，聚合到 OptimizationDataset
        
        Args:
            instance_ids: 实例 ID 列表
            
        Returns:
            OptimizationDataset
        """
        from execution_kernel.analytics.metrics import MetricsCalculator
        
        calculator = MetricsCalculator(self.session)
        
        # 收集所有实例的统计信息
        dataset = await self.collect_from_instances(instance_ids)
        
        # 使用 MetricsCalculator 计算每个实例的指标
        instance_metrics = {}
        for instance_id in instance_ids:
            try:
                metrics = await calculator.compute_for_optimization(instance_id)
                instance_metrics[instance_id] = metrics
            except Exception as e:
                logger.warning(f"Failed to compute metrics for {instance_id}: {e}")
        
        # 将指标信息写入新 dataset（frozen 不可变，需新建实例）
        if instance_metrics:
            total_success_rate = sum(m["success_rate"] for m in instance_metrics.values())
            avg_success_rate = total_success_rate / len(instance_metrics) if instance_metrics else 0.0
            total_duration = sum(m["avg_duration_ms"] for m in instance_metrics.values())
            avg_duration = total_duration / len(instance_metrics) if instance_metrics else 0.0
            metrics_summary = {
                "instance_count": len(instance_metrics),
                "avg_success_rate": round(avg_success_rate, 4),
                "avg_duration_ms": round(avg_duration, 2),
                "instance_metrics": instance_metrics,
            }
            dataset = OptimizationDataset(
                node_stats=dataset.node_stats,
                skill_stats=dataset.skill_stats,
                created_at=dataset.created_at,
                event_count=dataset.event_count,
                instance_count=dataset.instance_count,
                metrics_summary=metrics_summary,
            )
        return dataset
    
    def _collect_node_stats(
        self,
        events: List[ExecutionEvent],
    ) -> Dict[str, NodeStatistics]:
        """
        从事件流中收集节点统计
        
        处理以下事件类型：
        - NODE_STARTED: 记录节点开始
        - NODE_SUCCEEDED: 记录成功和延迟
        - NODE_FAILED: 记录失败
        - NODE_RETRY_SCHEDULED: 记录重试
        """
        # 临时存储节点执行状态
        node_data: Dict[str, dict] = defaultdict(lambda: {
            "execution_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_latency_ms": 0.0,
            "retry_success_count": 0,
            "skill_name": None,
            "last_retry_count": 0,
        })
        
        # 记录节点开始时间用于计算延迟
        node_start_times: Dict[str, datetime] = {}
        
        for event in events:
            event_type = event.event_type
            payload = event.payload
            
            if event_type == ExecutionEventType.NODE_STARTED:
                node_id = payload.get("node_id")
                if node_id:
                    node_start_times[node_id] = datetime.utcnow()
                    node_data[node_id]["skill_name"] = payload.get("node_type")
            
            elif event_type == ExecutionEventType.NODE_SUCCEEDED:
                node_id = payload.get("node_id")
                if node_id:
                    data = node_data[node_id]
                    data["execution_count"] += 1
                    data["success_count"] += 1
                    
                    # 记录延迟
                    duration_ms = payload.get("duration_ms", 0)
                    if duration_ms:
                        data["total_latency_ms"] += duration_ms
                    
                    # 如果有重试记录，计入重试成功
                    if data["last_retry_count"] > 0:
                        data["retry_success_count"] += 1
                        data["last_retry_count"] = 0
                    
                    # 获取 skill_name（从 NODE_SCHEDULED 或 NODE_STARTED）
                    if not data["skill_name"]:
                        data["skill_name"] = payload.get("node_type")
            
            elif event_type == ExecutionEventType.NODE_FAILED:
                node_id = payload.get("node_id")
                if node_id:
                    data = node_data[node_id]
                    data["execution_count"] += 1
                    data["failure_count"] += 1
                    data["last_retry_count"] = payload.get("retry_count", 0)
            
            elif event_type == ExecutionEventType.NODE_RETRY_SCHEDULED:
                node_id = payload.get("node_id")
                if node_id:
                    node_data[node_id]["last_retry_count"] = payload.get("retry_count", 1)
        
        # 转换为 NodeStatistics 对象
        stats = {}
        for node_id, data in node_data.items():
            stats[node_id] = NodeStatistics(
                node_id=node_id,
                skill_name=data["skill_name"],
                execution_count=data["execution_count"],
                success_count=data["success_count"],
                failure_count=data["failure_count"],
                total_latency_ms=data["total_latency_ms"],
                retry_success_count=data["retry_success_count"],
                last_updated=datetime.utcnow(),
            )
        
        return stats
    
    def _collect_skill_stats(
        self,
        node_stats: Dict[str, NodeStatistics],
    ) -> Dict[str, SkillStatistics]:
        """
        从节点统计中聚合 Skill 统计
        """
        skill_data: Dict[str, dict] = defaultdict(lambda: {
            "execution_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_latency_ms": 0.0,
            "retry_success_count": 0,
            "node_ids": set(),
        })
        
        for node_id, node_stat in node_stats.items():
            skill_name = node_stat.skill_name
            if not skill_name:
                continue
            
            data = skill_data[skill_name]
            data["execution_count"] += node_stat.execution_count
            data["success_count"] += node_stat.success_count
            data["failure_count"] += node_stat.failure_count
            data["total_latency_ms"] += node_stat.total_latency_ms
            data["retry_success_count"] += node_stat.retry_success_count
            data["node_ids"].add(node_id)
        
        # 转换为 SkillStatistics 对象
        stats = {}
        for skill_name, data in skill_data.items():
            stats[skill_name] = SkillStatistics(
                skill_name=skill_name,
                execution_count=data["execution_count"],
                success_count=data["success_count"],
                failure_count=data["failure_count"],
                total_latency_ms=data["total_latency_ms"],
                retry_success_count=data["retry_success_count"],
                node_count=len(data["node_ids"]),
                last_updated=datetime.utcnow(),
            )
        
        return stats
    
    async def _get_instance_ids_with_events(
        self,
        limit: int = 1000,
    ) -> List[str]:
        """
        获取有事件的实例 ID 列表
        
        通过查询 execution_event 表获取唯一的 instance_id
        """
        from sqlalchemy import select, func, desc, asc
        from execution_kernel.events.event_store import ExecutionEventDB
        
        # P2: 稳定采样，避免 limit 子集随查询计划抖动导致 snapshot 不可复现
        result = await self.session.execute(
            select(
                ExecutionEventDB.instance_id,
                func.max(ExecutionEventDB.timestamp).label("last_ts"),
            )
            .group_by(ExecutionEventDB.instance_id)
            .order_by(desc("last_ts"), asc(ExecutionEventDB.instance_id))
            .limit(limit)
        )

        return [row[0] for row in result.fetchall() if row and row[0]]
