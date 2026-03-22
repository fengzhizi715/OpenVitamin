"""
V2.6: Observability & Replay Layer - Analytics Metrics
基于事件流的指标计算
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from execution_kernel.events.event_store import EventStore
from execution_kernel.events.event_types import ExecutionEventType


logger = logging.getLogger(__name__)


class ExecutionMetrics:
    """
    执行指标
    
    所有指标从 event 表计算，不直接读取 runtime 状态
    """
    
    def __init__(
        self,
        instance_id: str,
        total_events: int,
        node_success_rate: float,
        avg_node_duration_ms: float,
        total_retry_count: int,
        total_execution_duration_ms: float,
        completed_nodes: int,
        failed_nodes: int,
        details: Dict[str, Any],
    ):
        self.instance_id = instance_id
        self.total_events = total_events
        self.node_success_rate = node_success_rate
        self.avg_node_duration_ms = avg_node_duration_ms
        self.total_retry_count = total_retry_count
        self.total_execution_duration_ms = total_execution_duration_ms
        self.completed_nodes = completed_nodes
        self.failed_nodes = failed_nodes
        self.details = details
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "total_events": self.total_events,
            "node_success_rate": round(self.node_success_rate, 4),
            "avg_node_duration_ms": round(self.avg_node_duration_ms, 2),
            "total_retry_count": self.total_retry_count,
            "total_execution_duration_ms": round(self.total_execution_duration_ms, 2),
            "completed_nodes": self.completed_nodes,
            "failed_nodes": self.failed_nodes,
            "details": self.details,
        }


class MetricsCalculator:
    """
    指标计算器
    
    从事件流计算执行指标
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.event_store = EventStore(session)
    
    async def compute_metrics(self, instance_id: str) -> ExecutionMetrics:
        """
        计算实例的执行指标
        
        Args:
            instance_id: 图实例 ID
            
        Returns:
            执行指标
        """
        events = await self.event_store.get_events(instance_id)
        
        if not events:
            return ExecutionMetrics(
                instance_id=instance_id,
                total_events=0,
                node_success_rate=0.0,
                avg_node_duration_ms=0.0,
                total_retry_count=0,
                total_execution_duration_ms=0.0,
                completed_nodes=0,
                failed_nodes=0,
                details={"error": "No events found"},
            )
        
        # 计算各项指标
        node_stats = self._compute_node_stats(events)
        retry_count = self._count_retries(events)
        execution_duration = self._compute_execution_duration(events)
        
        # 计算成功率
        total_finished = node_stats["succeeded"] + node_stats["failed"]
        success_rate = (
            node_stats["succeeded"] / total_finished if total_finished > 0 else 0.0
        )
        
        # 计算平均耗时
        avg_duration = self._compute_avg_duration(events)
        
        return ExecutionMetrics(
            instance_id=instance_id,
            total_events=len(events),
            node_success_rate=success_rate,
            avg_node_duration_ms=avg_duration,
            total_retry_count=retry_count,
            total_execution_duration_ms=execution_duration,
            completed_nodes=node_stats["succeeded"],
            failed_nodes=node_stats["failed"],
            details={
                "node_stats": node_stats,
                "event_type_breakdown": self._count_event_types(events),
            },
        )
    
    def _compute_node_stats(self, events: List) -> Dict[str, int]:
        """计算节点统计"""
        stats = {
            "scheduled": 0,
            "started": 0,
            "succeeded": 0,
            "failed": 0,
            "retried": 0,
            "skipped": 0,
            "timeout": 0,
        }
        
        for event in events:
            event_type = event.event_type
            if event_type == ExecutionEventType.NODE_SCHEDULED:
                stats["scheduled"] += 1
            elif event_type == ExecutionEventType.NODE_STARTED:
                stats["started"] += 1
            elif event_type == ExecutionEventType.NODE_SUCCEEDED:
                stats["succeeded"] += 1
            elif event_type == ExecutionEventType.NODE_FAILED:
                stats["failed"] += 1
            elif event_type == ExecutionEventType.NODE_RETRY_SCHEDULED:
                stats["retried"] += 1
            elif event_type == ExecutionEventType.NODE_SKIPPED:
                stats["skipped"] += 1
            elif event_type == ExecutionEventType.NODE_TIMEOUT:
                stats["timeout"] += 1
        
        return stats
    
    def _count_retries(self, events: List) -> int:
        """计算重试次数"""
        return sum(
            1 for e in events
            if e.event_type == ExecutionEventType.NODE_RETRY_SCHEDULED
        )
    
    def _compute_execution_duration(self, events: List) -> float:
        """计算总执行时长（毫秒）"""
        start_event = None
        end_event = None
        
        for event in events:
            if event.event_type == ExecutionEventType.GRAPH_STARTED:
                start_event = event
            elif event.event_type in {
                ExecutionEventType.GRAPH_COMPLETED,
                ExecutionEventType.GRAPH_FAILED,
                ExecutionEventType.GRAPH_CANCELLED,
            }:
                end_event = event
        
        if start_event and end_event:
            return end_event.timestamp - start_event.timestamp
        return 0.0
    
    def _compute_avg_duration(self, events: List) -> float:
        """计算节点平均执行时长（毫秒）"""
        node_durations = []
        
        for event in events:
            if event.event_type == ExecutionEventType.NODE_SUCCEEDED:
                duration = event.payload.get("duration_ms")
                if duration is not None:
                    node_durations.append(duration)
        
        if not node_durations:
            return 0.0
        
        return sum(node_durations) / len(node_durations)
    
    def _count_event_types(self, events: List) -> Dict[str, int]:
        """统计各事件类型数量"""
        breakdown = {}
        for event in events:
            event_type = event.event_type.value
            breakdown[event_type] = breakdown.get(event_type, 0) + 1
        return breakdown
    
    async def compute_batch_metrics(
        self,
        instance_ids: List[str],
    ) -> Dict[str, Any]:
        """
        批量计算多个实例的指标
        
        Args:
            instance_ids: 实例 ID 列表
            
        Returns:
            汇总指标
        """
        all_metrics = []
        
        for instance_id in instance_ids:
            try:
                metrics = await self.compute_metrics(instance_id)
                all_metrics.append(metrics)
            except Exception as e:
                logger.error(f"Failed to compute metrics for {instance_id}: {e}")
        
        if not all_metrics:
            return {"error": "No metrics computed"}
        
        # 计算汇总
        total_events = sum(m.total_events for m in all_metrics)
        avg_success_rate = sum(m.node_success_rate for m in all_metrics) / len(all_metrics)
        avg_duration = sum(m.avg_node_duration_ms for m in all_metrics) / len(all_metrics)
        total_retries = sum(m.total_retry_count for m in all_metrics)
        
        return {
            "instance_count": len(all_metrics),
            "total_events": total_events,
            "avg_success_rate": round(avg_success_rate, 4),
            "avg_node_duration_ms": round(avg_duration, 2),
            "total_retries": total_retries,
            "instances": [m.to_dict() for m in all_metrics],
        }
    
    async def compute_for_optimization(
        self,
        instance_id: str,
    ) -> Dict[str, Any]:
        """
        V2.7: 为 Optimization Layer 计算指标
        
        返回适合聚合到 OptimizationDataset 的数据格式
        
        Args:
            instance_id: 图实例 ID
            
        Returns:
            适合 OptimizationDataset 的数据格式
        """
        metrics = await self.compute_metrics(instance_id)
        
        # 转换为 OptimizationDataset 友好的格式
        return {
            "instance_id": instance_id,
            "success_rate": metrics.node_success_rate,
            "avg_duration_ms": metrics.avg_node_duration_ms,
            "total_events": metrics.total_events,
            "completed_nodes": metrics.completed_nodes,
            "failed_nodes": metrics.failed_nodes,
            "retry_count": metrics.total_retry_count,
            "execution_duration_ms": metrics.total_execution_duration_ms,
            "details": metrics.details,
        }


async def compute_metrics(instance_id: str, session: AsyncSession) -> Dict[str, Any]:
    """
    便捷函数：计算单个实例指标
    
    Args:
        instance_id: 图实例 ID
        session: 数据库会话
        
    Returns:
        指标字典
    """
    calculator = MetricsCalculator(session)
    metrics = await calculator.compute_metrics(instance_id)
    return metrics.to_dict()


# ==================== V2.7: Optimization Layer Integration ====================

def compute_optimization_impact(
    before_snapshot,  # OptimizationSnapshot
    after_snapshot,   # OptimizationSnapshot
) -> Dict[str, Any]:
    """
    V2.7: 计算优化效果
    
    对比两个 OptimizationSnapshot，计算成功率提升和延迟降低。
    
    Args:
        before_snapshot: 优化前的快照
        after_snapshot: 优化后的快照
        
    Returns:
        - success_rate_before: 优化前成功率
        - success_rate_after: 优化后成功率
        - improvement_pct: 提升百分比
        - latency_before_ms: 优化前平均延迟
        - latency_after_ms: 优化后平均延迟
        - latency_reduction_pct: 延迟降低百分比
        - node_count_before: 优化前节点数
        - node_count_after: 优化后节点数
        - skill_count_before: 优化前 Skill 数
        - skill_count_after: 优化后 Skill 数
    """
    # 从快照元数据提取统计信息
    before_meta = before_snapshot.metadata or {}
    after_meta = after_snapshot.metadata or {}
    
    # 计算平均成功率（从节点权重推导）
    def _compute_avg_success_rate(snapshot) -> float:
        if not snapshot.node_weights:
            return 0.0
        # 权重越高表示成功率越高，归一化到 [0, 1]
        weights = list(snapshot.node_weights.values())
        if not weights:
            return 0.0
        # 假设权重范围是 [0.1, 10.0]，归一化到成功率
        max_weight = max(weights) if weights else 1.0
        min_weight = min(weights) if weights else 0.0
        if max_weight == min_weight:
            return 1.0  # 所有权重相同，表示所有节点表现一致
        # 计算平均归一化权重作为成功率近似
        normalized = [(w - min_weight) / (max_weight - min_weight) for w in weights]
        return sum(normalized) / len(normalized) if normalized else 0.0
    
    success_rate_before = _compute_avg_success_rate(before_snapshot)
    success_rate_after = _compute_avg_success_rate(after_snapshot)
    
    # 计算成功率提升百分比
    if success_rate_before > 0:
        improvement_pct = ((success_rate_after - success_rate_before) / success_rate_before) * 100
    else:
        improvement_pct = 0.0 if success_rate_after == 0 else 100.0
    
    # 计算平均延迟
    def _compute_avg_latency(snapshot) -> float:
        latencies = list(snapshot.latency_estimates.values())
        return sum(latencies) / len(latencies) if latencies else 0.0
    
    latency_before_ms = _compute_avg_latency(before_snapshot)
    latency_after_ms = _compute_avg_latency(after_snapshot)
    
    # 计算延迟降低百分比
    if latency_before_ms > 0:
        latency_reduction_pct = ((latency_before_ms - latency_after_ms) / latency_before_ms) * 100
    else:
        latency_reduction_pct = 0.0
    
    return {
        "success_rate_before": round(success_rate_before, 4),
        "success_rate_after": round(success_rate_after, 4),
        "improvement_pct": round(improvement_pct, 2),
        "latency_before_ms": round(latency_before_ms, 2),
        "latency_after_ms": round(latency_after_ms, 2),
        "latency_reduction_pct": round(latency_reduction_pct, 2),
        "node_count_before": len(before_snapshot.node_weights),
        "node_count_after": len(after_snapshot.node_weights),
        "skill_count_before": len(before_snapshot.skill_weights),
        "skill_count_after": len(after_snapshot.skill_weights),
        "version_before": before_snapshot.version,
        "version_after": after_snapshot.version,
    }
