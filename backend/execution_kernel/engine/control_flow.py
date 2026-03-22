"""
Phase C: Control Flow Execution
条件分支与循环控制流执行逻辑
"""

import asyncio
import logging
import ast
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from pydantic import BaseModel, Field

from execution_kernel.models.graph_definition import (
    NodeDefinition, NodeType, EdgeTrigger, LoopConfig
)

logger = logging.getLogger(__name__)


class LoopAuditLog(BaseModel):
    """Phase C: 循环审计日志条目"""
    iteration: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    condition_result: Optional[bool] = None
    error: Optional[str] = None


class LoopState(BaseModel):
    """Phase C: 循环执行状态"""
    iteration_count: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    audit_logs: List[LoopAuditLog] = Field(default_factory=list)
    exited: bool = False
    exit_reason: Optional[str] = None  # "condition_false", "max_iterations", "timeout", "error"


async def execute_condition_node(
    node_def: NodeDefinition,
    input_data: Dict[str, Any],
    context: "GraphContext",
) -> Dict[str, Any]:
    """
    Phase C: 执行条件节点
    
    根据 config.condition_expression 或 config.condition_fn 评估条件
    返回 {"condition_result": True/False} 用于边路由
    """
    config = node_def.config or {}
    
    # 1. 获取条件表达式
    condition_expr = config.get("condition_expression")
    condition_fn = config.get("condition_fn")  # 预留：函数引用
    
    result = False
    passthrough_input = dict(input_data or {})
    
    if condition_expr:
        # 简单表达式评估：支持变量引用
        # 例如: "${input.value} > 10" 或 "${context.loop_count} < 5"
        try:
            result = _evaluate_condition(condition_expr, input_data, context)
        except Exception as e:
            logger.error(f"Condition evaluation error: {e}")
            return {
                **passthrough_input,
                "condition_result": False,
                "error": f"Condition evaluation failed: {e}",
                "condition_expression": condition_expr,
            }
    elif condition_fn and hasattr(context, 'evaluators'):
        # 使用外部评估器
        evaluator = context.evaluators.get(condition_fn)
        if evaluator:
            result = await evaluator(input_data, context)
    else:
        # 默认：检查 input_data 中的 condition_result 字段
        result = input_data.get("condition_result", False)
    
    return {
        **passthrough_input,
        "condition_result": result,
        "condition_expression": condition_expr,
    }


def _evaluate_condition(
    expr: str,
    input_data: Dict[str, Any],
    context: "GraphContext",
) -> bool:
    """
    评估条件表达式
    
    支持：
    - ${input.key} 访问输入数据
    - ${context.key} 访问上下文
    - 比较运算符: ==, !=, <, >, <=, >=
    - 逻辑运算符: and, or, not
    """
    # 简单的变量替换
    import re
    
    def replace_var(match):
        raw = match.group(0)
        try:
            value = context.resolve(raw)
            return repr(value)
        except Exception:
            var_path = match.group(1).strip()
            parts = var_path.split(".")

            if parts[0] == "input" and len(parts) > 1:
                value = input_data
                for part in parts[1:]:
                    value = value.get(part) if isinstance(value, dict) else None
                return repr(value)
            elif parts[0] == "context" and len(parts) > 1:
                value = context.variables if hasattr(context, 'variables') else {}
                for part in parts[1:]:
                    value = value.get(part) if isinstance(value, dict) else None
                return repr(value)
            return raw
    
    # 替换 ${...} 变量
    processed_expr = re.sub(r'\$\{([^}]+)\}', replace_var, expr)
    
    # 安全评估（仅允许比较和逻辑运算），避免使用 eval
    try:
        node = ast.parse(processed_expr, mode="eval")
        return bool(_safe_eval_ast(node.body))
    except Exception as e:
        logger.error(f"Expression evaluation failed: {processed_expr}, error: {e}")
        return False


def _safe_eval_ast(node: ast.AST) -> Any:
    """受限 AST 求值器：仅支持布尔/比较/常量。"""
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        if node.id == "None":
            return None
        raise ValueError(f"Unsupported name: {node.id}")

    if isinstance(node, ast.UnaryOp):
        val = _safe_eval_ast(node.operand)
        if isinstance(node.op, ast.Not):
            return not bool(val)
        raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")

    if isinstance(node, ast.BoolOp):
        values = [_safe_eval_ast(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(bool(v) for v in values)
        if isinstance(node.op, ast.Or):
            return any(bool(v) for v in values)
        raise ValueError(f"Unsupported bool operator: {type(node.op).__name__}")

    if isinstance(node, ast.Compare):
        left = _safe_eval_ast(node.left)
        for op, comp in zip(node.ops, node.comparators):
            right = _safe_eval_ast(comp)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.In):
                ok = left in right
            elif isinstance(op, ast.NotIn):
                ok = left not in right
            elif isinstance(op, ast.Is):
                ok = left is right
            elif isinstance(op, ast.IsNot):
                ok = left is not right
            else:
                raise ValueError(f"Unsupported compare operator: {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True

    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


async def execute_loop_node(
    node_def: NodeDefinition,
    input_data: Dict[str, Any],
    context: "GraphContext",
    iteration_callback: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    Phase C: 执行循环节点
    
    循环节点是一个"虚拟"节点，实际循环体是连接到它的子图。
    循环节点负责：
    1. 维护迭代计数
    2. 评估循环条件
    3. 触发循环体执行
    4. 记录审计日志
    5. 安全退出（最大迭代、超时）
    
    Returns:
        {"loop_completed": True, "iterations": N, "exit_reason": "..."}
    """
    config = node_def.loop_config or LoopConfig()
    loop_state = LoopState()
    
    # 从 context 恢复之前的循环状态（支持恢复）
    if hasattr(context, 'loop_states') and node_def.id in context.loop_states:
        loop_state = context.loop_states[node_def.id]
    
    max_iterations = config.max_iterations
    timeout_seconds = config.timeout_seconds
    condition_expr = config.condition_expression or input_data.get("loop_condition")
    
    start_time = datetime.utcnow()
    
    while True:
        # 1. 检查最大迭代次数
        if loop_state.iteration_count >= max_iterations:
            loop_state.exited = True
            loop_state.exit_reason = "max_iterations"
            logger.warning(
                f"Loop {node_def.id} reached max iterations ({max_iterations})"
            )
            break
        
        # 2. 检查超时
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        if elapsed >= timeout_seconds:
            loop_state.exited = True
            loop_state.exit_reason = "timeout"
            logger.warning(
                f"Loop {node_def.id} timeout after {elapsed}s"
            )
            break
        
        # 3. 评估循环条件
        if condition_expr:
            condition_result = _evaluate_condition(condition_expr, input_data, context)
            if not condition_result:
                loop_state.exited = True
                loop_state.exit_reason = "condition_false"
                logger.info(f"Loop {node_def.id} exit: condition false")
                break
        
        # 4. 开始新迭代
        loop_state.iteration_count += 1
        iteration = loop_state.iteration_count
        
        audit_entry = LoopAuditLog(
            iteration=iteration,
            started_at=datetime.utcnow(),
        )
        
        try:
            # 5. 触发迭代回调（由 Scheduler 执行实际循环体）
            if iteration_callback:
                iteration_result = await iteration_callback(
                    node_def=node_def,
                    iteration=iteration,
                    input_data=input_data,
                )
                audit_entry.condition_result = iteration_result.get("condition_result")
            
            audit_entry.finished_at = datetime.utcnow()
            
        except Exception as e:
            audit_entry.error = str(e)
            audit_entry.finished_at = datetime.utcnow()
            loop_state.exit_reason = "error"
            logger.error(f"Loop {node_def.id} iteration {iteration} failed: {e}")
            # 根据配置决定是否继续或退出（LoopConfig 无 exit_on_error 时默认 True）
            if getattr(config, "exit_on_error", True):
                break
        
        if config.audit_log:
            loop_state.audit_logs.append(audit_entry)
    
    # 保存循环状态到 context
    if hasattr(context, 'loop_states'):
        context.loop_states[node_def.id] = loop_state
    
    return {
        "loop_completed": loop_state.exited,
        "iterations": loop_state.iteration_count,
        "exit_reason": loop_state.exit_reason,
        "audit_logs": [
            {
                "iteration": log.iteration,
                "started_at": log.started_at.isoformat(),
                "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                "condition_result": log.condition_result,
                "error": log.error,
            }
            for log in loop_state.audit_logs
        ] if config.audit_log else [],
    }
