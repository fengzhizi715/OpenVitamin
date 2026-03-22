"""
V2.7: Optimization Layer - Scheduler Policy Base

调度策略基类和上下文定义
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from execution_kernel.models.graph_definition import NodeDefinition, GraphDefinition
from execution_kernel.optimization.snapshot.snapshot import OptimizationSnapshot


@dataclass
class PolicyContext:
    """
    策略上下文
    
    传递给 SchedulerPolicy 的上下文信息
    
    Attributes:
        instance_id: 图实例 ID
        graph_def: 图定义
        node_outputs: 已完成节点的输出
        global_context: 全局上下文
        ready_nodes: 当前就绪的节点列表
        running_nodes: 正在运行的节点列表
        completed_nodes: 已完成的节点列表
        failed_nodes: 已失败的节点列表
    """
    instance_id: str
    graph_def: GraphDefinition
    node_outputs: Dict[str, Dict[str, Any]]
    global_context: Dict[str, Any]
    ready_nodes: List[str]
    running_nodes: List[str]
    completed_nodes: List[str]
    failed_nodes: List[str]
    
    @classmethod
    def create_empty(cls, instance_id: str, graph_def: GraphDefinition) -> "PolicyContext":
        """创建空上下文"""
        return cls(
            instance_id=instance_id,
            graph_def=graph_def,
            node_outputs={},
            global_context={},
            ready_nodes=[],
            running_nodes=[],
            completed_nodes=[],
            failed_nodes=[],
        )


class SchedulerPolicy(ABC):
    """
    调度策略基类
    
    定义调度器如何选择就绪节点的策略接口。
    
    所有策略必须：
    1. 声明 version（用于 Replay determinism）
    2. 实现 priority() 方法，返回节点的优先级分数
    3. 保证相同输入产生相同输出（确定性）
    
    优先级分数：
    - 分数越高，优先级越高
    - 分数相同时，按 node_id 字典序排序（保证确定性）
    """
    
    # 策略版本，用于 Replay 时加载相同策略
    version: str = "base_1.0.0"
    
    @abstractmethod
    def priority(
        self,
        node: NodeDefinition,
        context: PolicyContext,
        snapshot: Optional[OptimizationSnapshot] = None,
    ) -> float:
        """
        计算节点的优先级
        
        Args:
            node: 节点定义
            context: 策略上下文
            snapshot: 优化快照（可选）
            
        Returns:
            优先级分数（越高越优先）
        """
        pass
    
    def sort_nodes(
        self,
        nodes: List[NodeDefinition],
        context: PolicyContext,
        snapshot: Optional[OptimizationSnapshot] = None,
    ) -> List[NodeDefinition]:
        """
        对节点列表进行排序
        
        默认实现：按 priority 降序，相同时按 node_id 升序
        
        Args:
            nodes: 待排序的节点列表
            context: 策略上下文
            snapshot: 优化快照（可选）
            
        Returns:
            排序后的节点列表
        """
        # 计算每个节点的优先级
        node_priorities = [
            (node, self.priority(node, context, snapshot))
            for node in nodes
        ]
        
        # 按优先级降序，相同时按 node_id 升序（保证确定性）
        node_priorities.sort(key=lambda x: (-x[1], x[0].id))
        
        return [node for node, _ in node_priorities]
    
    def get_name(self) -> str:
        """获取策略名称"""
        return self.__class__.__name__
    
    def get_version(self) -> str:
        """获取策略版本"""
        return self.version
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "name": self.get_name(),
            "version": self.get_version(),
        }
