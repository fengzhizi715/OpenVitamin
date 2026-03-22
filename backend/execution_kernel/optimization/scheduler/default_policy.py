"""
V2.7: Optimization Layer - Default Scheduler Policy

默认调度策略，保持与 V2.6 完全一致的行为
"""

from typing import Optional

from execution_kernel.models.graph_definition import NodeDefinition
from execution_kernel.optimization.scheduler.policy_base import SchedulerPolicy, PolicyContext
from execution_kernel.optimization.snapshot.snapshot import OptimizationSnapshot


class DefaultPolicy(SchedulerPolicy):
    """
    默认调度策略
    
    行为与 V2.6 完全一致：
    - priority = topological_order（节点在图中的拓扑顺序）
    - 相同时按 node_id 字典序排序
    
    这是 optimization 未启用或 snapshot 为空时的回退策略。
    
    保证：
    - 系统行为与 V2.6 完全一致
    - 调度顺序完全可复现
    """
    
    version = "default_1.0.0"
    
    def priority(
        self,
        node: NodeDefinition,
        context: PolicyContext,
        snapshot: Optional[OptimizationSnapshot] = None,
    ) -> float:
        """
        计算节点优先级
        
        使用节点的拓扑顺序作为优先级。
        拓扑顺序越小，优先级越高（先执行）。
        
        由于 priority 返回的值越大优先级越高，
        我们使用负的拓扑顺序：
        - 拓扑顺序 0 -> priority = 0
        - 拓扑顺序 1 -> priority = -1
        
        但更简单的方式是直接使用拓扑顺序，
        然后在 sort_nodes 中按升序排列。
        
        为了保持与基类接口一致（priority 越高越优先），
        我们返回负的拓扑顺序值。
        """
        # 从节点配置中获取拓扑顺序，默认为 0
        topological_order = node.config.get("topological_order", 0)
        
        # 返回负值，使得拓扑顺序小的节点优先级高
        return -float(topological_order)
    
    def sort_nodes(
        self,
        nodes,
        context: PolicyContext,
        snapshot: Optional[OptimizationSnapshot] = None,
    ):
        """
        对节点列表进行排序
        
        覆盖基类实现，按拓扑顺序升序排列，
        相同时按 node_id 字典序排列。
        
        这与 V2.6 的行为完全一致。
        """
        # 按拓扑顺序升序，相同时按 node_id 升序
        return sorted(
            nodes,
            key=lambda n: (n.config.get("topological_order", 0), n.id)
        )
