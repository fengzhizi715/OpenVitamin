"""
V2.7: Optimization Layer - Optimization Snapshot DB Model

持久化 OptimizationSnapshot 到数据库
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, JSON, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from execution_kernel.persistence.db import Base


class OptimizationSnapshotDB(Base):
    """
    优化快照数据库模型
    
    持久化存储 OptimizationSnapshot，支持历史版本查询
    
    Attributes:
        id: 自增主键
        version: 快照版本（内容哈希）
        created_at: 创建时间
        node_weights: 节点权重 JSON
        skill_weights: Skill 权重 JSON
        latency_estimates: 延迟估计 JSON
        source_dataset_hash: 来源数据集哈希
        extra_data: 额外元数据 JSON（避免与 SQLAlchemy metadata 冲突）
    """
    __tablename__ = "optimization_snapshots"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    node_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    skill_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_estimates: Mapped[dict] = mapped_column(JSON, default=dict)
    source_dataset_hash: Mapped[str] = mapped_column(String(64), default="")
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)  # renamed from metadata
    # V2.7: 追加来源事件数和实例数
    source_event_count: Mapped[int] = mapped_column(Integer, default=0)
    source_instance_count: Mapped[int] = mapped_column(Integer, default=0)
    
    def to_snapshot(self) -> "OptimizationSnapshot":
        """转换为 OptimizationSnapshot，metadata 含 source_event_count/source_instance_count 便于与 Builder 产出一致"""
        from execution_kernel.optimization.snapshot import OptimizationSnapshot
        
        extra = dict(self.extra_data or {})
        extra["source_event_count"] = self.source_event_count
        extra["source_instance_count"] = self.source_instance_count
        return OptimizationSnapshot(
            version=self.version,
            created_at=self.created_at,
            node_weights=self.node_weights or {},
            skill_weights=self.skill_weights or {},
            latency_estimates=self.latency_estimates or {},
            source_dataset_hash=self.source_dataset_hash or "",
            metadata=extra,
        )
    
    @classmethod
    def from_snapshot(cls, snapshot: "OptimizationSnapshot") -> "OptimizationSnapshotDB":
        """从 OptimizationSnapshot 创建数据库模型"""
        return cls(
            version=snapshot.version,
            created_at=snapshot.created_at,
            node_weights=dict(snapshot.node_weights),
            skill_weights=dict(snapshot.skill_weights),
            latency_estimates=dict(snapshot.latency_estimates),
            source_dataset_hash=snapshot.source_dataset_hash,
            extra_data=dict(snapshot.metadata),
            source_event_count=snapshot.metadata.get("source_event_count", 0),
            source_instance_count=snapshot.metadata.get("source_instance_count", 0),
        )
