"""
Graph Instance Database Models
SQLAlchemy 2.0 模型，Postgres 兼容
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Integer, JSON, Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import enum


class Base(DeclarativeBase):
    """SQLAlchemy 基类"""
    pass


class NodeStateDB(str, enum.Enum):
    """节点状态（数据库枚举）"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class GraphInstanceStateDB(str, enum.Enum):
    """图实例状态（数据库枚举）"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GraphDefinitionDB(Base):
    """图定义表（Phase B: 支持版本化）"""
    __tablename__ = "graph_definitions"
    
    # Phase B: 复合主键 id = graph_id_version
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Phase B: 唯一约束 (graph_id, version)
    __table_args__ = (
        # 确保同一 graph_id 的 version 唯一
        {'sqlite_autoincrement': True},
    )


class GraphInstanceDB(Base):
    """图实例表"""
    __tablename__ = "graph_instances"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    graph_definition_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    graph_definition_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    state: Mapped[GraphInstanceStateDB] = mapped_column(
        SQLEnum(GraphInstanceStateDB), 
        nullable=False, 
        default=GraphInstanceStateDB.PENDING
    )
    global_context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class NodeRuntimeDB(Base):
    """节点运行时表"""
    __tablename__ = "node_runtimes"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    graph_instance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[NodeStateDB] = mapped_column(
        SQLEnum(NodeStateDB), 
        nullable=False, 
        default=NodeStateDB.PENDING
    )
    input_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class NodeCacheDB(Base):
    """节点缓存表"""
    __tablename__ = "node_cache"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    output_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# Phase B: Graph Patch 相关表

class GraphPatchDB(Base):
    """图补丁表"""
    __tablename__ = "graph_patches"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_graph_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_version: Mapped[str] = mapped_column(String(32), nullable=False)
    target_version: Mapped[str] = mapped_column(String(32), nullable=False)
    operations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending, applied, failed
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ExecutionPointerDB(Base):
    """执行指针表（用于崩溃恢复）"""
    __tablename__ = "execution_pointers"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, unique=True)
    graph_version: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ready_nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    running_nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    failed_nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
