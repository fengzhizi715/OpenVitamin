"""
V2.7: Optimization Layer - Replanner

安全重规划：从失败的 GraphInstance 创建新的 GraphInstance

设计原则：
- 禁止修改运行中的 GraphInstance
- 禁止插入/删除节点
- 只能创建新的 GraphInstance
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from execution_kernel.models.graph_definition import GraphDefinition
from execution_kernel.models.node_models import GraphInstanceState, NodeState
from execution_kernel.models.graph_instance import GraphInstanceDB, NodeRuntimeDB
from execution_kernel.persistence.repositories import (
    GraphInstanceRepository,
    NodeRuntimeRepository,
    GraphDefinitionRepository,
)
from sqlalchemy import select
from execution_kernel.models.graph_instance import GraphInstanceStateDB


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplanRecord:
    """
    重规划记录
    
    记录从失败实例到新实例的转换
    
    Attributes:
        failed_instance_id: 失败的实例 ID
        new_instance_id: 新创建的实例 ID
        reason: 重规划原因
        planner_version: Planner 版本
        timestamp: 重规划时间
        metadata: 额外元数据
    """
    failed_instance_id: str
    new_instance_id: str
    reason: str
    planner_version: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "failed_instance_id": self.failed_instance_id,
            "new_instance_id": self.new_instance_id,
            "reason": self.reason,
            "planner_version": self.planner_version,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class Replanner:
    """
    重规划器
    
    职责：
    - 从失败的 GraphInstance 创建新的 GraphInstance
    - 记录重规划历史
    - 支持从失败点恢复状态
    
    安全约束：
    - 不修改原 GraphInstance
    - 不修改原 GraphDefinition
    - 创建全新的执行实例
    
    数据流：
    GraphInstance (failed)
          ↓
    Replanner.analyze_failure()
          ↓
    Planner (external)
          ↓
    New GraphDefinition
          ↓
    Replanner.create_new_instance()
          ↓
    New GraphInstance
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.instance_repo = GraphInstanceRepository(session)
        self.node_repo = NodeRuntimeRepository(session)
        self.def_repo = GraphDefinitionRepository(session)
    
    async def analyze_failure(
        self,
        instance_id: str,
    ) -> Dict[str, Any]:
        """
        分析失败实例的状态
        
        Args:
            instance_id: 失败的实例 ID
            
        Returns:
            失败分析报告
        """
        instance_db = await self.instance_repo.get(instance_id)
        if not instance_db:
            return {"error": f"Instance {instance_id} not found"}
        
        # 获取所有节点状态
        all_nodes = await self.node_repo.get_all_by_instance(instance_id)
        
        # 分析节点状态分布
        node_states = {}
        failed_nodes = []
        completed_nodes = []
        pending_nodes = []
        
        for node in all_nodes:
            state = NodeState(node.state.value)
            node_states[node.node_id] = {
                "state": state.value,
                "error_message": node.error_message,
                "error_type": node.error_type,
                "retry_count": node.retry_count,
            }
            
            if state == NodeState.FAILED:
                failed_nodes.append(node.node_id)
            elif state == NodeState.SUCCESS:
                completed_nodes.append(node.node_id)
            elif state == NodeState.PENDING:
                pending_nodes.append(node.node_id)
        
        # 获取图定义
        graph_def = await self.def_repo.get_definition(
            instance_db.graph_definition_id,
            version=instance_db.graph_definition_version,
        )
        
        return {
            "instance_id": instance_id,
            "graph_id": instance_db.graph_definition_id,
            "graph_version": instance_db.graph_definition_version,
            "instance_state": instance_db.state.value if instance_db.state else None,
            "total_nodes": len(all_nodes),
            "completed_nodes": completed_nodes,
            "failed_nodes": failed_nodes,
            "pending_nodes": pending_nodes,
            "node_states": node_states,
            "global_context": instance_db.global_context,
            "has_graph_definition": graph_def is not None,
        }
    
    async def create_new_instance(
        self,
        failed_instance_id: str,
        new_graph_def: GraphDefinition,
        new_instance_id: str,
        reason: str,
        planner_version: str = "unknown",
        carry_over_context: bool = True,
        preserve_completed_outputs: bool = True,
    ) -> ReplanRecord:
        """
        从失败的实例创建新的实例
        
        Args:
            failed_instance_id: 失败的实例 ID
            new_graph_def: 新的图定义（由 Planner 生成）
            new_instance_id: 新实例 ID
            reason: 重规划原因
            planner_version: Planner 版本
            carry_over_context: 是否携带全局上下文
            preserve_completed_outputs: 是否保留已完成节点的输出
            
        Returns:
            ReplanRecord
        """
        # 获取失败实例
        failed_instance = await self.instance_repo.get(failed_instance_id)
        if not failed_instance:
            raise ValueError(f"Failed instance {failed_instance_id} not found")
        
        # 保存新的图定义
        await self.def_repo.save(new_graph_def)
        
        # 构建全局上下文
        global_context = {}
        if carry_over_context:
            global_context = dict(failed_instance.global_context or {})
        
        # 添加重规划元数据
        global_context["_replan"] = {
            "failed_instance_id": failed_instance_id,
            "reason": reason,
            "planner_version": planner_version,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # 获取失败实例的节点输出（用于 preserve）
        preserved_outputs = {}
        if preserve_completed_outputs:
            failed_nodes = await self.node_repo.get_all_by_instance(failed_instance_id)
            for node in failed_nodes:
                if NodeState(node.state.value) == NodeState.SUCCESS and node.output_data:
                    preserved_outputs[node.node_id] = node.output_data
        
        # 创建新实例
        from execution_kernel.models.node_models import GraphInstance
        new_instance = GraphInstance(
            id=new_instance_id,
            graph_definition_id=new_graph_def.id,
            graph_definition_version=new_graph_def.version,
            state=GraphInstanceState.PENDING,
            global_context=global_context,
        )
        await self.instance_repo.create(new_instance)
        
        # 创建新实例的节点运行时
        for node_def in new_graph_def.get_enabled_nodes():
            # 检查是否有保留的输出
            output_data = preserved_outputs.get(node_def.id, {})
            
            # 如果该节点在旧实例中已完成，且新图中也有相同 ID 的节点，
            # 可以选择标记为已完成（可选优化）
            initial_state = NodeState.PENDING
            if preserve_completed_outputs and node_def.id in preserved_outputs:
                # 可选：自动标记为完成（跳过执行）
                # initial_state = NodeState.SUCCESS
                pass
            
            node_runtime = NodeRuntimeDB(
                graph_instance_id=new_instance_id,
                node_id=node_def.id,
                state=initial_state,
                input_data=node_def.config.get("default_input", {}),
                output_data=output_data if preserve_completed_outputs else {},
            )
            self.session.add(node_runtime)
        
        await self.session.flush()
        
        # 创建重规划记录
        record = ReplanRecord(
            failed_instance_id=failed_instance_id,
            new_instance_id=new_instance_id,
            reason=reason,
            planner_version=planner_version,
            metadata={
                "new_graph_id": new_graph_def.id,
                "new_graph_version": new_graph_def.version,
                "preserved_outputs_count": len(preserved_outputs),
                "carry_over_context": carry_over_context,
            },
        )
        
        logger.info(
            f"Replan created: {failed_instance_id} -> {new_instance_id}, "
            f"reason={reason}, planner={planner_version}"
        )
        
        return record
    
    async def get_replan_history(
        self,
        failed_instance_id: str,
    ) -> List[ReplanRecord]:
        """
        获取重规划历史
        
        通过查询新实例的上下文中是否包含 _replan 标记
        """
        # 查询所有实例，查找 _replan.failed_instance_id 匹配的
        result = await self.session.execute(
            select(GraphInstanceDB).where(
                GraphInstanceDB.global_context.contains({
                    "_replan": {"failed_instance_id": failed_instance_id}
                })
            )
        )
        
        records = []
        for instance in result.scalars().all():
            replan_info = instance.global_context.get("_replan", {})
            record = ReplanRecord(
                failed_instance_id=replan_info.get("failed_instance_id", ""),
                new_instance_id=instance.id,
                reason=replan_info.get("reason", ""),
                planner_version=replan_info.get("planner_version", "unknown"),
                timestamp=datetime.fromisoformat(replan_info.get("timestamp", "")),
            )
            records.append(record)
        
        return records
    
    async def can_replan(
        self,
        instance_id: str,
    ) -> bool:
        """
        检查实例是否可以重规划
        
        条件：
        - 实例存在
        - 实例状态为 FAILED
        """
        instance = await self.instance_repo.get(instance_id)
        if not instance:
            return False
        
        return instance.state == GraphInstanceStateDB.FAILED
