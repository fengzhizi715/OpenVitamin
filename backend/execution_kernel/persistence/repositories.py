"""
Repositories
数据访问层，封装所有数据库操作
"""

from datetime import datetime
from typing import Optional, List
import asyncio
import logging
import os
from sqlalchemy import select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError

from execution_kernel.models.graph_instance import (
    GraphDefinitionDB,
    GraphInstanceDB,
    NodeRuntimeDB,
    NodeCacheDB,
    NodeStateDB,
    GraphInstanceStateDB,
    GraphPatchDB,
    ExecutionPointerDB,
)
from execution_kernel.models.graph_definition import GraphDefinition
from execution_kernel.models.node_models import (
    NodeRuntime,
    GraphInstance,
    NodeState,
    GraphInstanceState,
    NodeCacheEntry,
)


logger = logging.getLogger("ai_platform")
POINTER_UPDATE_STRATEGY = (os.getenv("EXECUTION_POINTER_STRATEGY", "best_effort") or "best_effort").strip().lower()


class GraphDefinitionRepository:
    """图定义仓库（Phase B: 支持版本化存储）"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def save(self, graph_def: GraphDefinition) -> GraphDefinitionDB:
        """
        保存图定义（Phase B: 按 id + version 保存，支持多版本）
        
        同一 graph_id 的不同 version 会分别存储。
        """
        # Phase B: 检查 (id, version) 是否已存在
        existing = await self.get_by_version(graph_def.id, graph_def.version)
        if existing:
            return existing
        
        # Phase B: 使用复合主键 id_version
        db_obj = GraphDefinitionDB(
            id=f"{graph_def.id}_{graph_def.version}",  # 复合键: graph_id_version
            graph_id=graph_def.id,  # 原始 graph_id
            version=graph_def.version,
            definition_json=graph_def.model_dump(),
        )
        self.session.add(db_obj)
        await self.session.flush()
        return db_obj
    
    async def get(self, graph_id: str) -> Optional[GraphDefinitionDB]:
        """获取图定义（最新版本）"""
        result = await self.session.execute(
            select(GraphDefinitionDB)
            .where(GraphDefinitionDB.graph_id == graph_id)
            .order_by(GraphDefinitionDB.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def get_by_version(self, graph_id: str, version: str) -> Optional[GraphDefinitionDB]:
        """Phase B: 获取指定版本的图定义"""
        result = await self.session.execute(
            select(GraphDefinitionDB).where(
                and_(
                    GraphDefinitionDB.graph_id == graph_id,
                    GraphDefinitionDB.version == version,
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def get_definition(self, graph_id: str, version: Optional[str] = None) -> Optional[GraphDefinition]:
        """
        获取图定义（解析为 Pydantic 模型）
        
        Args:
            graph_id: 图 ID
            version: 指定版本（None 则返回最新版本）
        """
        if version:
            db_obj = await self.get_by_version(graph_id, version)
        else:
            db_obj = await self.get(graph_id)
        
        if db_obj:
            return GraphDefinition(**db_obj.definition_json)
        return None
    
    async def get_version_history(self, graph_id: str) -> List[GraphDefinitionDB]:
        """Phase B: 获取图的所有版本历史"""
        result = await self.session.execute(
            select(GraphDefinitionDB)
            .where(GraphDefinitionDB.graph_id == graph_id)
            .order_by(GraphDefinitionDB.created_at.asc())
        )
        return list(result.scalars().all())


class GraphInstanceRepository:
    """图实例仓库"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, instance: GraphInstance) -> GraphInstanceDB:
        """创建图实例"""
        db_obj = GraphInstanceDB(
            id=instance.id,
            graph_definition_id=instance.graph_definition_id,
            graph_definition_version=instance.graph_definition_version,
            state=GraphInstanceStateDB(instance.state.value),
            global_context=instance.global_context,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            started_at=instance.started_at,
            finished_at=instance.finished_at,
        )
        self.session.add(db_obj)
        await self.session.flush()
        return db_obj
    
    async def get(self, instance_id: str, for_update: bool = False) -> Optional[GraphInstanceDB]:
        """获取图实例"""
        query = select(GraphInstanceDB).where(GraphInstanceDB.id == instance_id)
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def update_state(
        self, 
        instance_id: str, 
        new_state: GraphInstanceState,
        started_at: datetime = None,
        finished_at: datetime = None,
    ) -> bool:
        """更新图实例状态（幂等）"""
        values = {
            "state": GraphInstanceStateDB(new_state.value),
            "updated_at": datetime.utcnow(),
        }
        if started_at:
            values["started_at"] = started_at
        if finished_at:
            values["finished_at"] = finished_at
        
        result = await self.session.execute(
            update(GraphInstanceDB)
            .where(GraphInstanceDB.id == instance_id)
            .values(**values)
        )
        return result.rowcount > 0
    
    async def get_running_instances(self) -> List[GraphInstanceDB]:
        """获取所有运行中的实例（用于 crash 恢复）"""
        result = await self.session.execute(
            select(GraphInstanceDB).where(
                GraphInstanceDB.state == GraphInstanceStateDB.RUNNING
            )
        )
        return list(result.scalars().all())


class NodeRuntimeRepository:
    """节点运行时仓库"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, node_runtime: NodeRuntime) -> NodeRuntimeDB:
        """创建节点运行时"""
        db_obj = NodeRuntimeDB(
            id=node_runtime.id,
            graph_instance_id=node_runtime.graph_instance_id,
            node_id=node_runtime.node_id,
            state=NodeStateDB(node_runtime.state.value),
            input_data=node_runtime.input_data,
            output_data=node_runtime.output_data,
            retry_count=node_runtime.retry_count,
            error_message=node_runtime.error_message,
            error_type=node_runtime.error_type,
            started_at=node_runtime.started_at,
            finished_at=node_runtime.finished_at,
            created_at=node_runtime.created_at,
            updated_at=node_runtime.updated_at,
        )
        self.session.add(db_obj)
        await self.session.flush()
        return db_obj
    
    async def get(self, node_id: str, for_update: bool = False) -> Optional[NodeRuntimeDB]:
        """获取节点运行时"""
        query = select(NodeRuntimeDB).where(NodeRuntimeDB.id == node_id)
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_instance_and_node(
        self, 
        instance_id: str, 
        node_def_id: str,
        for_update: bool = False
    ) -> Optional[NodeRuntimeDB]:
        """根据实例 ID 和节点定义 ID 获取运行时"""
        query = select(NodeRuntimeDB).where(
            and_(
                NodeRuntimeDB.graph_instance_id == instance_id,
                NodeRuntimeDB.node_id == node_def_id,
            )
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
    async def get_pending_nodes(self, instance_id: str) -> List[NodeRuntimeDB]:
        """获取实例的所有待执行节点"""
        result = await self.session.execute(
            select(NodeRuntimeDB)
            .where(
                and_(
                    NodeRuntimeDB.graph_instance_id == instance_id,
                    NodeRuntimeDB.state == NodeStateDB.PENDING,
                )
            )
            .order_by(NodeRuntimeDB.created_at)
        )
        return list(result.scalars().all())
    
    async def get_running_nodes(self, instance_id: str) -> List[NodeRuntimeDB]:
        """获取实例的所有运行中节点（用于 crash 恢复）"""
        result = await self.session.execute(
            select(NodeRuntimeDB)
            .where(
                and_(
                    NodeRuntimeDB.graph_instance_id == instance_id,
                    NodeRuntimeDB.state == NodeStateDB.RUNNING,
                )
            )
        )
        return list(result.scalars().all())
    
    async def update_state(
        self,
        node_id: str,
        new_state: NodeState,
        output_data: dict = None,
        error_message: str = None,
        error_type: str = None,
        started_at: datetime = None,
        finished_at: datetime = None,
        retry_count: int = None,
    ) -> bool:
        """更新节点状态（幂等）"""
        values = {
            "state": NodeStateDB(new_state.value),
            "updated_at": datetime.utcnow(),
        }
        if output_data is not None:
            values["output_data"] = output_data
        if error_message is not None:
            values["error_message"] = error_message
        if error_type is not None:
            values["error_type"] = error_type
        if started_at is not None:
            values["started_at"] = started_at
        if finished_at is not None:
            values["finished_at"] = finished_at
        if retry_count is not None:
            values["retry_count"] = retry_count
        
        result = await self.session.execute(
            update(NodeRuntimeDB)
            .where(NodeRuntimeDB.id == node_id)
            .values(**values)
        )
        return result.rowcount > 0
    
    async def reset_running_to_pending(self, instance_id: str) -> int:
        """将运行中节点重置为待执行（用于 crash 恢复）"""
        result = await self.session.execute(
            update(NodeRuntimeDB)
            .where(
                and_(
                    NodeRuntimeDB.graph_instance_id == instance_id,
                    NodeRuntimeDB.state == NodeStateDB.RUNNING,
                )
            )
            .values(
                state=NodeStateDB.PENDING,
                updated_at=datetime.utcnow(),
            )
        )
        return result.rowcount
    
    async def get_all_by_instance(self, instance_id: str) -> List[NodeRuntimeDB]:
        """获取实例的所有节点运行时"""
        result = await self.session.execute(
            select(NodeRuntimeDB)
            .where(NodeRuntimeDB.graph_instance_id == instance_id)
            .order_by(NodeRuntimeDB.created_at)
        )
        return list(result.scalars().all())


class NodeCacheRepository:
    """节点缓存仓库"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get(self, node_id: str, input_hash: str) -> Optional[NodeCacheDB]:
        """获取缓存"""
        result = await self.session.execute(
            select(NodeCacheDB).where(
                and_(
                    NodeCacheDB.node_id == node_id,
                    NodeCacheDB.input_hash == input_hash,
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def save(self, entry: NodeCacheEntry) -> NodeCacheDB:
        """保存缓存"""
        db_obj = NodeCacheDB(
            id=entry.id,
            node_id=entry.node_id,
            input_hash=entry.input_hash,
            output_data=entry.output_data,
            created_at=entry.created_at,
            expires_at=entry.expires_at,
        )
        self.session.add(db_obj)
        await self.session.flush()
        return db_obj
    
    async def delete_expired(self) -> int:
        """删除过期缓存"""
        result = await self.session.execute(
            select(NodeCacheDB).where(
                and_(
                    NodeCacheDB.expires_at.isnot(None),
                    NodeCacheDB.expires_at < datetime.utcnow(),
                )
            )
        )
        expired = list(result.scalars().all())
        for cache in expired:
            await self.session.delete(cache)


# Phase B: Graph Patch Repositories

class GraphPatchRepository:
    """图补丁仓库"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, patch_id: str, target_graph_id: str, base_version: str,
                     target_version: str, operations: list, created_by: Optional[str] = None,
                     reason: Optional[str] = None) -> GraphPatchDB:
        """创建补丁记录"""
        db_obj = GraphPatchDB(
            id=patch_id,
            target_graph_id=target_graph_id,
            base_version=base_version,
            target_version=target_version,
            operations=operations,
            state="pending",
            created_by=created_by,
            reason=reason,
        )
        self.session.add(db_obj)
        await self.session.flush()
        return db_obj
    
    async def get(self, patch_id: str) -> Optional[GraphPatchDB]:
        """获取补丁"""
        result = await self.session.execute(
            select(GraphPatchDB).where(GraphPatchDB.id == patch_id)
        )
        return result.scalar_one_or_none()
    
    async def mark_applied(self, patch_id: str, result: dict) -> None:
        """标记补丁为已应用"""
        # Phase B: 序列化 result，处理 datetime 字段
        import json
        from datetime import datetime
        
        def serialize_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        
        # 转换为 JSON 再解析，确保所有 datetime 被序列化为字符串
        serialized_result = json.loads(json.dumps(result, default=serialize_datetime))
        
        await self.session.execute(
            update(GraphPatchDB)
            .where(GraphPatchDB.id == patch_id)
            .values(
                state="applied",
                result=serialized_result,
                applied_at=datetime.utcnow(),
            )
        )
    
    async def mark_failed(self, patch_id: str, error: str) -> None:
        """标记补丁为失败"""
        await self.session.execute(
            update(GraphPatchDB)
            .where(GraphPatchDB.id == patch_id)
            .values(
                state="failed",
                result={"error": error},
            )
        )
    
    async def get_patches_for_graph(self, graph_id: str) -> List[GraphPatchDB]:
        """获取图的所有补丁"""
        result = await self.session.execute(
            select(GraphPatchDB)
            .where(GraphPatchDB.target_graph_id == graph_id)
            .order_by(GraphPatchDB.created_at)
        )
        return list(result.scalars().all())


class ExecutionPointerRepository:
    """执行指针仓库"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def save(self, pointer: "ExecutionPointer") -> ExecutionPointerDB:
        """保存执行指针"""
        db_obj = ExecutionPointerDB(
            id=f"ptr_{pointer.instance_id}",
            instance_id=pointer.instance_id,
            graph_version=pointer.graph_version,
            completed_nodes=pointer.completed_nodes,
            ready_nodes=pointer.ready_nodes,
            running_nodes=pointer.running_nodes,
            failed_nodes=pointer.failed_nodes,
            updated_at=datetime.utcnow(),
        )
        self.session.add(db_obj)
        await self.session.flush()
        return db_obj
    
    async def get(self, instance_id: str) -> Optional[ExecutionPointerDB]:
        """获取执行指针"""
        result = await self.session.execute(
            select(ExecutionPointerDB).where(ExecutionPointerDB.instance_id == instance_id)
        )
        return result.scalar_one_or_none()
    
    async def update(self, pointer: "ExecutionPointer") -> None:
        """更新执行指针"""
        # SQLite 在并发写入时可能出现短暂锁冲突，做轻量重试避免误回退
        last_error = None
        for attempt in range(3):
            try:
                await self.session.execute(
                    update(ExecutionPointerDB)
                    .where(ExecutionPointerDB.instance_id == pointer.instance_id)
                    .values(
                        graph_version=pointer.graph_version,
                        completed_nodes=pointer.completed_nodes,
                        ready_nodes=pointer.ready_nodes,
                        running_nodes=pointer.running_nodes,
                        failed_nodes=pointer.failed_nodes,
                        updated_at=datetime.utcnow(),
                    )
                )
                return
            except OperationalError as e:
                last_error = e
                if "database is locked" not in str(e).lower() or attempt == 2:
                    if "database is locked" not in str(e).lower():
                        raise
                    if POINTER_UPDATE_STRATEGY == "strict":
                        raise
                    logger.debug(
                        "[ExecutionPointerRepository] Skip pointer update after retries due to DB lock: instance_id=%s",
                        pointer.instance_id,
                    )
                    return
                await asyncio.sleep(0.05 * (attempt + 1))
        if last_error:
            if POINTER_UPDATE_STRATEGY == "strict":
                raise last_error
            logger.debug(
                "[ExecutionPointerRepository] Skip pointer update due to DB lock: instance_id=%s",
                pointer.instance_id,
            )
            return
    
    async def delete(self, instance_id: str) -> None:
        """删除执行指针"""
        result = await self.session.execute(
            select(ExecutionPointerDB).where(ExecutionPointerDB.instance_id == instance_id)
        )
        db_obj = result.scalar_one_or_none()
        if db_obj:
            await self.session.delete(db_obj)


# ==================== V2.7: Optimization Snapshot Repository ====================

class OptimizationSnapshotRepository:
    """
    V2.7: 优化快照仓库
    
    持久化 OptimizationSnapshot 到数据库
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def save(self, snapshot) -> str:
        """
        保存快照到数据库
        
        Args:
            snapshot: OptimizationSnapshot 实例
            
        Returns:
            快照版本号
        """
        from execution_kernel.models.optimization_snapshot_db import OptimizationSnapshotDB
        
        # 检查是否已存在
        existing = await self.get_by_version(snapshot.version)
        if existing:
            return snapshot.version
        
        db_obj = OptimizationSnapshotDB.from_snapshot(snapshot)
        self.session.add(db_obj)
        await self.session.flush()
        
        return snapshot.version
    
    async def get_by_version(self, version: str) -> Optional["OptimizationSnapshot"]:
        """
        按版本号查询快照
        
        Args:
            version: 快照版本
            
        Returns:
            OptimizationSnapshot 或 None
        """
        from execution_kernel.models.optimization_snapshot_db import OptimizationSnapshotDB
        
        result = await self.session.execute(
            select(OptimizationSnapshotDB).where(OptimizationSnapshotDB.version == version)
        )
        db_obj = result.scalar_one_or_none()
        
        if db_obj:
            return db_obj.to_snapshot()
        return None
    
    async def list_latest(self, limit: int = 10) -> List["OptimizationSnapshot"]:
        """
        列出最近的快照
        
        Args:
            limit: 最大数量
            
        Returns:
            OptimizationSnapshot 列表
        """
        from execution_kernel.models.optimization_snapshot_db import OptimizationSnapshotDB
        
        result = await self.session.execute(
            select(OptimizationSnapshotDB)
            .order_by(OptimizationSnapshotDB.created_at.desc())
            .limit(limit)
        )
        db_objs = result.scalars().all()
        
        return [obj.to_snapshot() for obj in db_objs]
    
    async def get_latest(self) -> Optional["OptimizationSnapshot"]:
        """
        获取最新快照
        
        Returns:
            最新的 OptimizationSnapshot 或 None
        """
        snapshots = await self.list_latest(limit=1)
        return snapshots[0] if snapshots else None
    
    async def delete_by_version(self, version: str) -> bool:
        """
        删除指定版本的快照
        
        Args:
            version: 快照版本
            
        Returns:
            是否删除成功
        """
        from execution_kernel.models.optimization_snapshot_db import OptimizationSnapshotDB
        
        result = await self.session.execute(
            select(OptimizationSnapshotDB).where(OptimizationSnapshotDB.version == version)
        )
        db_obj = result.scalar_one_or_none()
        
        if db_obj:
            await self.session.delete(db_obj)
            return True
        return False
