"""
V2.7: Optimization Layer - Statistics Models

定义统计模型：NodeStatistics 和 SkillStatistics
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass(frozen=True)
class NodeStatistics:
    """
    节点执行统计
    
    从 ExecutionEvent 统计得到，用于生成 OptimizationSnapshot
    
    Attributes:
        node_id: 节点 ID
        skill_name: Skill 名称（如果节点是 skill 类型）
        execution_count: 总执行次数
        success_count: 成功次数
        failure_count: 失败次数
        total_latency_ms: 总延迟（毫秒）
        retry_success_count: 重试后成功次数
        last_updated: 最后更新时间
    """
    node_id: str
    skill_name: Optional[str] = None
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    retry_success_count: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def success_rate(self) -> float:
        """成功率 (0.0 - 1.0)"""
        if self.execution_count == 0:
            return 0.0
        return self.success_count / self.execution_count
    
    @property
    def avg_latency_ms(self) -> float:
        """平均延迟（毫秒）"""
        if self.execution_count == 0:
            return 0.0
        return self.total_latency_ms / self.execution_count
    
    @property
    def retry_success_rate(self) -> float:
        """重试成功率 (0.0 - 1.0)"""
        if self.failure_count == 0:
            return 0.0
        return self.retry_success_count / self.failure_count
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "node_id": self.node_id,
            "skill_name": self.skill_name,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_latency_ms": self.total_latency_ms,
            "retry_success_count": self.retry_success_count,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "retry_success_rate": self.retry_success_rate,
            "last_updated": self.last_updated.isoformat(),
        }


@dataclass(frozen=True)
class SkillStatistics:
    """
    Skill 执行统计
    
    按 skill_name 聚合的统计信息
    
    Attributes:
        skill_name: Skill 名称
        execution_count: 总执行次数
        success_count: 成功次数
        failure_count: 失败次数
        total_latency_ms: 总延迟（毫秒）
        retry_success_count: 重试后成功次数
        node_count: 使用此 skill 的节点数量
        last_updated: 最后更新时间
    """
    skill_name: str
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    retry_success_count: int = 0
    node_count: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def success_rate(self) -> float:
        """成功率 (0.0 - 1.0)"""
        if self.execution_count == 0:
            return 0.0
        return self.success_count / self.execution_count
    
    @property
    def avg_latency_ms(self) -> float:
        """平均延迟（毫秒）"""
        if self.execution_count == 0:
            return 0.0
        return self.total_latency_ms / self.execution_count
    
    @property
    def retry_success_rate(self) -> float:
        """重试成功率 (0.0 - 1.0)"""
        if self.failure_count == 0:
            return 0.0
        return self.retry_success_count / self.failure_count
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "skill_name": self.skill_name,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_latency_ms": self.total_latency_ms,
            "retry_success_count": self.retry_success_count,
            "node_count": self.node_count,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "retry_success_rate": self.retry_success_rate,
            "last_updated": self.last_updated.isoformat(),
        }
