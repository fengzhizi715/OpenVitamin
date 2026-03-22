"""
Graph Definition Models (Frozen, Immutable)
纯数据定义，不包含可执行函数
"""

from enum import Enum
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from pydantic import BaseModel, Field
import hashlib
import json

if TYPE_CHECKING:
    from typing import ForwardRef


class NodeType(str, Enum):
    """节点类型"""
    TOOL = "tool"
    LLM = "llm"  # Workflow Control Plane: LLM 节点，走 InferenceClient
    CONDITION = "condition"
    SCRIPT = "script"
    REPLAN = "replan"  # Phase B: 动态重规划节点
    LOOP = "loop"  # Phase C: 循环节点


class EdgeTrigger(str, Enum):
    """边触发条件"""
    SUCCESS = "success"
    FAILURE = "failure"
    ALWAYS = "always"
    # Phase C: 条件分支触发
    CONDITION_TRUE = "condition_true"
    CONDITION_FALSE = "condition_false"
    # Phase C: 循环控制触发
    LOOP_CONTINUE = "loop_continue"
    LOOP_EXIT = "loop_exit"


class RetryPolicy(BaseModel):
    """重试策略"""
    max_retries: int = Field(default=3, ge=0, description="最大重试次数")
    backoff_seconds: float = Field(default=1.0, ge=0, description="退避时间（秒）")
    backoff_multiplier: float = Field(default=2.0, ge=1.0, description="退避乘数")
    max_backoff_seconds: float = Field(default=60.0, ge=1.0, description="最大退避时间")
    
    def calculate_backoff(self, retry_count: int) -> float:
        """计算第 N 次重试的退避时间"""
        backoff = self.backoff_seconds * (self.backoff_multiplier ** retry_count)
        return min(backoff, self.max_backoff_seconds)


class LoopConfig(BaseModel):
    """Phase C: 循环节点配置"""
    max_iterations: int = Field(default=100, ge=1, description="最大迭代次数")
    timeout_seconds: float = Field(default=300.0, ge=1.0, description="循环总超时时间")
    condition_expression: Optional[str] = Field(default=None, description="循环条件表达式")
    audit_log: bool = Field(default=True, description="是否记录循环审计日志")


class NodeDefinition(BaseModel):
    """节点定义（不可变）"""
    id: str = Field(..., description="节点唯一标识")
    type: NodeType = Field(default=NodeType.TOOL, description="节点类型")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="输入 Schema")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="输出 Schema")
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy, description="重试策略")
    timeout_seconds: float = Field(default=300.0, ge=1.0, description="超时时间（秒）")
    cacheable: bool = Field(default=False, description="是否可缓存")
    config: Dict[str, Any] = Field(default_factory=dict, description="节点配置")
    # Phase C: 循环节点专用配置
    loop_config: Optional[LoopConfig] = Field(default=None, description="循环配置（仅 LOOP 类型有效）")
    
    class Config:
        frozen = True
    
    def cache_key(self, input_data: Dict[str, Any]) -> str:
        """生成缓存键"""
        data = {"node_id": self.id, "input": input_data}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class EdgeDefinition(BaseModel):
    """边定义（不可变）"""
    from_node: str = Field(..., description="源节点 ID")
    to_node: str = Field(..., description="目标节点 ID")
    on: EdgeTrigger = Field(default=EdgeTrigger.SUCCESS, description="触发条件")
    condition: Optional[str] = Field(default=None, description="条件表达式")
    
    class Config:
        frozen = True


class SubgraphDefinition(BaseModel):
    """子图定义（用于 Composite 步骤）"""
    id: str = Field(..., description="子图唯一标识")
    graph: "GraphDefinition" = Field(..., description="子图定义")
    parent_node_id: str = Field(..., description="父图中对应节点的 ID")
    
    class Config:
        frozen = True


class GraphDefinition(BaseModel):
    """图定义（不可变，纯数据）"""
    id: str = Field(..., description="图定义唯一标识")
    version: str = Field(default="1.0.0", description="版本号")
    nodes: List[NodeDefinition] = Field(default_factory=list, description="节点列表")
    edges: List[EdgeDefinition] = Field(default_factory=list, description="边列表")
    # Phase A: 支持嵌套子图
    subgraphs: List[SubgraphDefinition] = Field(default_factory=list, description="子图列表")
    parent_graph_id: Optional[str] = Field(default=None, description="父图 ID（用于子图）")
    # Phase B: 支持动态图扩展
    metadata: Dict[str, Any] = Field(default_factory=dict, description="图元数据")
    disabled_nodes: List[str] = Field(default_factory=list, description="已禁用节点 ID 列表")
    
    class Config:
        frozen = True
    
    def get_node(self, node_id: str) -> Optional[NodeDefinition]:
        """获取节点定义"""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None
    
    def get_entry_nodes(self) -> List[str]:
        """获取入口节点（没有入边的节点）"""
        target_nodes = {edge.to_node for edge in self.edges}
        entry_nodes = [node.id for node in self.nodes if node.id not in target_nodes]
        return entry_nodes
    
    def get_outgoing_edges(self, node_id: str) -> List[EdgeDefinition]:
        """获取节点的出边"""
        return [edge for edge in self.edges if edge.from_node == node_id]
    
    def get_incoming_edges(self, node_id: str) -> List[EdgeDefinition]:
        """获取节点的入边"""
        return [edge for edge in self.edges if edge.to_node == node_id]
    
    def get_dependencies(self, node_id: str) -> List[str]:
        """获取节点的依赖节点 ID 列表"""
        incoming = self.get_incoming_edges(node_id)
        # 只考虑 success 触发的边作为依赖
        return [edge.from_node for edge in incoming if edge.on == EdgeTrigger.SUCCESS]
    
    def validate(self) -> List[str]:
        """验证图定义，返回错误列表"""
        errors = []
        
        # 检查节点 ID 唯一性
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            errors.append("Duplicate node IDs found")
        
        # 检查边引用的节点是否存在
        node_id_set = set(node_ids)
        for edge in self.edges:
            if edge.from_node not in node_id_set:
                errors.append(f"Edge references non-existent from_node: {edge.from_node}")
            if edge.to_node not in node_id_set:
                errors.append(f"Edge references non-existent to_node: {edge.to_node}")
        
        # 检查是否有入口节点
        if not self.get_entry_nodes():
            errors.append("No entry nodes found (possible cycle)")
        
        # 检查循环依赖（简单检查）
        visited = set()
        rec_stack = set()
        
        def has_cycle(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            for edge in self.get_outgoing_edges(node_id):
                if edge.to_node not in visited:
                    if has_cycle(edge.to_node):
                        return True
                elif edge.to_node in rec_stack:
                    return True
            rec_stack.remove(node_id)
            return False
        
        for node_id in node_ids:
            if node_id not in visited:
                if has_cycle(node_id):
                    errors.append("Cycle detected in graph")
                    break
        
        return errors
    
    def is_node_disabled(self, node_id: str) -> bool:
        """检查节点是否被禁用"""
        return node_id in self.disabled_nodes
    
    def get_enabled_nodes(self) -> List[NodeDefinition]:
        """获取所有启用的节点"""
        return [node for node in self.nodes if not self.is_node_disabled(node.id)]
    
    def get_enabled_edges(self) -> List[EdgeDefinition]:
        """获取所有启用的边（连接未被禁用的节点）"""
        disabled_set = set(self.disabled_nodes)
        return [
            edge for edge in self.edges 
            if edge.from_node not in disabled_set and edge.to_node not in disabled_set
        ]
