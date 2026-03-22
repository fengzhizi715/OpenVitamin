"""
V2.7: Optimization Layer - Learned Scheduler Policy

基于 OptimizationSnapshot 的学习型调度策略
"""

from typing import Optional
import hashlib
import logging

from execution_kernel.models.graph_definition import NodeDefinition
from execution_kernel.optimization.scheduler.policy_base import SchedulerPolicy, PolicyContext
from execution_kernel.optimization.snapshot.snapshot import OptimizationSnapshot


logger = logging.getLogger(__name__)


class LearnedPolicy(SchedulerPolicy):
    """
    学习型调度策略
    
    使用 OptimizationSnapshot 中的权重信息优化调度顺序。
    
    优先级公式：
    priority = (node_weight * 10) - latency_estimate
    
    其中：
    - node_weight: 来自 snapshot 的节点权重（默认 1.0）
    - latency_estimate: 来自 snapshot 的延迟估计（毫秒，默认 0.0）
    
    策略逻辑：
    - 权重高的节点优先（历史表现好）
    - 延迟低的节点优先（执行快）
    
    可选：考虑 Skill 权重
    - 如果节点有 skill_name，额外加上 skill_weight
    
    V2.7 注意：
    - version 包含参数哈希，确保不同参数产生不同的版本号
    - 这对于 Replay determinism 至关重要
    """
    
    # 基础版本号
    BASE_VERSION = "learned_1.0.0"
    
    def __init__(
        self,
        node_weight_factor: float = 10.0,
        latency_penalty_factor: float = 1.0,
        skill_weight_factor: float = 2.0,
        consider_skill: bool = True,
    ):
        """
        初始化学习型策略
        
        Args:
            node_weight_factor: 节点权重乘数
            latency_penalty_factor: 延迟惩罚乘数
            skill_weight_factor: Skill 权重乘数
            consider_skill: 是否考虑 Skill 权重
        """
        self.node_weight_factor = node_weight_factor
        self.latency_penalty_factor = latency_penalty_factor
        self.skill_weight_factor = skill_weight_factor
        self.consider_skill = consider_skill
        
        # V2.7: 动态计算版本号，包含参数哈希
        self._version = self._compute_version()
    
    def _compute_version(self) -> str:
        """
        计算包含参数哈希的版本号
        
        不同参数产生不同版本，确保 Replay determinism
        """
        param_str = (
            f"nwf={self.node_weight_factor}"
            f"lpf={self.latency_penalty_factor}"
            f"swf={self.skill_weight_factor}"
            f"cs={self.consider_skill}"
        )
        param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]
        return f"{self.BASE_VERSION}_{param_hash}"
    
    @property
    def version(self) -> str:
        """获取版本号（包含参数哈希）"""
        return self._version
    
    def priority(
        self,
        node: NodeDefinition,
        context: PolicyContext,
        snapshot: Optional[OptimizationSnapshot] = None,
    ) -> float:
        """
        计算节点优先级
        
        公式：
        priority = (node_weight * node_weight_factor) - 
                   (latency_estimate * latency_penalty_factor) +
                   (skill_weight * skill_weight_factor)
        """
        if snapshot is None:
            # 没有快照时，使用默认策略（按拓扑顺序）
            topological_order = node.config.get("topological_order", 0)
            return -float(topological_order)
        
        # 获取节点权重（默认 1.0）
        node_weight = snapshot.get_node_weight(node.id)
        
        # 获取延迟估计（默认 0.0）
        latency_estimate = snapshot.get_latency_estimate(node.id)
        
        # 基础优先级
        priority = (node_weight * self.node_weight_factor) - \
                   (latency_estimate * self.latency_penalty_factor)
        
        # 可选：加上 Skill 权重
        if self.consider_skill:
            skill_name = self._extract_skill_name(node)
            if skill_name:
                skill_weight = snapshot.get_skill_weight(skill_name)
                priority += skill_weight * self.skill_weight_factor
        
        return priority
    
    def _extract_skill_name(self, node: NodeDefinition) -> Optional[str]:
        """
        从节点定义中提取 Skill 名称
        
        优先从 config.skill 获取，其次使用 node_type
        """
        # 优先从 config 中获取 skill 名称
        skill_name = node.config.get("skill")
        if skill_name:
            return skill_name
        
        # 对于 tool 类型的节点，尝试使用 node_type
        if node.type.value == "tool":
            return node.config.get("tool_name")
        
        return None
    
    def sort_nodes(
        self,
        nodes,
        context: PolicyContext,
        snapshot: Optional[OptimizationSnapshot] = None,
    ):
        """
        对节点列表进行排序
        
        按优先级降序排列，相同时按 node_id 升序（保证确定性）
        """
        # 计算每个节点的优先级
        node_priorities = [
            (node, self.priority(node, context, snapshot))
            for node in nodes
        ]
        
        # 按优先级降序，相同时按 node_id 升序
        node_priorities.sort(key=lambda x: (-x[1], x[0].id))
        
        return [node for node, _ in node_priorities]
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.get_name(),
            "version": self.get_version(),
            "node_weight_factor": self.node_weight_factor,
            "latency_penalty_factor": self.latency_penalty_factor,
            "skill_weight_factor": self.skill_weight_factor,
            "consider_skill": self.consider_skill,
        }
