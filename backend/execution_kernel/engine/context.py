"""
Context Propagation
上下文传播模型，全局 context 只读，节点输出声明式存储
"""

from typing import Dict, Any, Optional
import re
import logging

from execution_kernel.models.graph_definition import GraphDefinition


logger = logging.getLogger(__name__)


class ContextResolutionError(Exception):
    """上下文解析异常"""
    pass


class GraphContext:
    """
    图执行上下文
    
    特性：
    - 全局 context 只读
    - node 输出声明式存储
    - 简单表达式解析
    
    表达式语法：
    - ${global.key} - 引用全局上下文
    - ${nodes.node_id.output.key} - 引用节点输出
    - ${input.key} - 引用当前节点输入
    """
    
    # 表达式模式：${...}
    EXPR_PATTERN = re.compile(r'\$\{([^}]+)\}')
    
    def __init__(
        self,
        global_data: Dict[str, Any],
        node_outputs: Dict[str, Dict[str, Any]] = None,
        current_node_input: Dict[str, Any] = None,
    ):
        self._global_data = dict(global_data)  # 只读副本
        self._node_outputs = dict(node_outputs or {})  # node_id -> output
        self._current_node_input = dict(current_node_input or {})
    
    @property
    def global_data(self) -> Dict[str, Any]:
        """全局数据（只读）"""
        return dict(self._global_data)
    
    @property
    def node_outputs(self) -> Dict[str, Dict[str, Any]]:
        """节点输出（只读）"""
        return {k: dict(v) for k, v in self._node_outputs.items()}
    
    def set_node_output(self, node_id: str, output: Dict[str, Any]):
        """
        设置节点输出（声明式存储）
        
        注意：只在节点执行完成后调用
        """
        self._node_outputs[node_id] = dict(output)
        logger.debug(f"Node output set: {node_id} -> {list(output.keys())}")
    
    def get_node_output(self, node_id: str) -> Optional[Dict[str, Any]]:
        """获取节点输出"""
        return self._node_outputs.get(node_id)
    
    def resolve(self, expression: str) -> Any:
        """
        解析表达式
        
        支持格式：
        - ${global.key}
        - ${nodes.node_id.output.key}
        - ${input.key}
        - 字面值（不包含 ${}）
        """
        if not expression:
            return expression
        
        # 检查是否是表达式
        if not self.EXPR_PATTERN.search(expression):
            return expression
        
        def replace_expr(match):
            expr = match.group(1).strip()
            try:
                return str(self._resolve_single(expr))
            except ContextResolutionError as e:
                logger.warning(f"Context resolution failed: {expr} -> {e}")
                return match.group(0)  # 保留原表达式
        
        result = self.EXPR_PATTERN.sub(replace_expr, expression)
        
        # 如果整个表达式就是一个 ${}，返回解析后的原始类型
        if self.EXPR_PATTERN.fullmatch(expression):
            expr = self.EXPR_PATTERN.search(expression).group(1).strip()
            return self._resolve_single(expr)
        
        return result
    
    def _resolve_single(self, expr: str) -> Any:
        """解析单个表达式"""
        parts = expr.split('.')
        
        if not parts:
            raise ContextResolutionError(f"Empty expression")
        
        root = parts[0]
        
        if root == "global":
            return self._resolve_global(parts[1:])
        
        elif root == "nodes":
            return self._resolve_node_output(parts[1:])
        
        elif root == "input":
            return self._resolve_input(parts[1:])

        elif root == "prev":
            return self._resolve_prev(parts[1:])
        
        else:
            raise ContextResolutionError(f"Unknown root: {root}")
    
    def _resolve_global(self, path: list) -> Any:
        """解析全局上下文引用"""
        current = self._global_data
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                raise ContextResolutionError(f"Global key not found: {'.'.join(path)}")
        return current
    
    def _resolve_node_output(self, path: list) -> Any:
        """解析节点输出引用"""
        if len(path) < 2:
            raise ContextResolutionError(f"Invalid node output reference: {path}")
        
        node_id = path[0]
        
        # 跳过 'output' 前缀如果存在
        output_path = path[1:]
        if output_path and output_path[0] == "output":
            output_path = output_path[1:]
        
        if not output_path:
            raise ContextResolutionError(f"Missing output key in reference: {path}")
        
        if node_id not in self._node_outputs:
            raise ContextResolutionError(f"Node output not found: {node_id}")
        
        current = self._node_outputs[node_id]
        for key in output_path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                raise ContextResolutionError(
                    f"Output key not found: {node_id}.{'.'.join(output_path)}"
                )
        return current
    
    def _resolve_input(self, path: list) -> Any:
        """
        解析输入引用（message-first 友好）：
        1) 当前节点输入
        2) workflow 全局 input_data
        3) 最近节点输出（仅当路径可解析）
        """
        if not path:
            return self._current_node_input

        found, value = self._try_resolve_path(self._current_node_input, path)
        if found:
            return value

        global_input = self._global_data.get("input_data")
        found, value = self._try_resolve_path(global_input, path)
        if found:
            return value

        for _, out in reversed(list(self._node_outputs.items())):
            found, value = self._try_resolve_path(out, path)
            if found:
                return value

        raise ContextResolutionError(f"Input key not found: {'.'.join(path)}")

    def _resolve_prev(self, path: list) -> Any:
        """
        解析最近上游输出引用：
        - ${prev} 返回最近节点完整输出
        - ${prev.key} 返回最近节点输出中的 key
        """
        if not self._node_outputs:
            raise ContextResolutionError("Previous node output not found")

        _, latest = next(reversed(self._node_outputs.items()))
        if not path:
            return latest

        found, value = self._try_resolve_path(latest, path)
        if found:
            return value
        raise ContextResolutionError(f"Previous output key not found: {'.'.join(path)}")

    @staticmethod
    def _try_resolve_path(data: Any, path: list) -> tuple[bool, Any]:
        current = data
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return False, None
        return True, current
    
    def resolve_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        递归解析字典中的所有表达式
        
        用于解析节点的输入数据
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.resolve(value)
            elif isinstance(value, dict):
                result[key] = self.resolve_dict(value)
            elif isinstance(value, list):
                result[key] = [self.resolve(item) if isinstance(item, str) else item for item in value]
            else:
                result[key] = value
        return result
    
    def copy_for_node(self, node_id: str, node_input: Dict[str, Any]) -> "GraphContext":
        """
        创建节点专用的上下文副本
        
        用于节点执行时
        """
        return GraphContext(
            global_data=self._global_data,
            node_outputs=self._node_outputs,
            current_node_input=node_input,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """导出为字典（用于持久化）"""
        return {
            "global_data": self._global_data,
            "node_outputs": self._node_outputs,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphContext":
        """从字典创建"""
        return cls(
            global_data=data.get("global_data", {}),
            node_outputs=data.get("node_outputs", {}),
        )
