"""
Agent V2 数据结构定义
可扩展的执行内核数据结构
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============== Execution Mode ==============
class ExecutionMode(str, Enum):
    """Agent 执行模式"""
    LEGACY = "legacy"
    PLAN_BASED = "plan_based"


# ============== Plan & Step ==============
class StepType(str, Enum):
    """步骤类型"""
    ATOMIC = "atomic"
    COMPOSITE = "composite"
    REPLAN = "replan"  # V2.2: 动态重规划步骤
    CONDITION = "condition"  # Phase C: 条件分支步骤
    LOOP = "loop"  # Phase C: 循环步骤


class ExecutorType(str, Enum):
    """执行器类型"""
    LLM = "llm"
    SKILL = "skill"
    TOOLCHAIN = "toolchain"
    INTERNAL = "internal"


class StepStatus(str, Enum):
    """步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Step(BaseModel):
    """
    执行步骤
    
    - atomic: 原子步骤，直接执行
    - composite: 组合步骤，内部包含 sub_plan（递归执行）
    - replan: 动态重规划步骤，触发新的 Plan 生成（V2.2）
    """
    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    type: StepType = StepType.ATOMIC
    executor: ExecutorType = ExecutorType.LLM
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    sub_plan: Optional["Plan"] = None
    status: StepStatus = StepStatus.PENDING
    error: Optional[str] = None
    # V2.2: 动态重规划相关字段
    replan_instruction: Optional[str] = None  # 重规划指令
    on_failure_replan: Optional[str] = None  # 失败时重规划指令

    class Config:
        arbitrary_types_allowed = True


class Plan(BaseModel):
    """
    执行计划
    
    包含目标、上下文、步骤列表和成功/失败策略
    V2.2 支持嵌套 Plan（通过 parent_plan_id）
    """
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:8]}")
    goal: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)
    steps: List[Step] = Field(default_factory=list)
    success_criteria: Optional[str] = None
    failure_strategy: Optional[str] = None
    # V2.2: Plan 血缘关系
    parent_plan_id: Optional[str] = None  # 父 Plan ID

    class Config:
        arbitrary_types_allowed = True


# ============== State ==============
class AgentState(BaseModel):
    """
    Agent 状态管理
    
    - persistent_state: 持久化状态（跨会话保存）
    - runtime_state: 运行时状态（当前会话内有效）
    """
    agent_id: str
    persistent_state: Dict[str, Any] = Field(default_factory=dict)
    runtime_state: Dict[str, Any] = Field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """获取状态值（优先 runtime，再 persistent）"""
        return self.runtime_state.get(key) or self.persistent_state.get(key, default)

    def set_runtime(self, key: str, value: Any) -> None:
        """设置运行时状态"""
        self.runtime_state[key] = value

    def set_persistent(self, key: str, value: Any) -> None:
        """设置持久化状态"""
        self.persistent_state[key] = value

    def get_persistent(self, key: str, default: Any = None) -> Any:
        """获取持久化状态"""
        return self.persistent_state.get(key, default)


# ============== Execution Trace ==============
class StepLog(BaseModel):
    """步骤执行日志（支持层级）"""
    step_id: str
    parent_step_id: Optional[str] = None  # 父步骤 ID，支持层级追踪
    depth: int = 0                         # 递归深度，0 表示顶层
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_type: str  # start, output, error, complete, skill_call
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[float] = None   # 步骤耗时（仅 complete/error 时有值）
    tool_id: Optional[str] = None          # 技能/工具 ID（兼容前端）


class ExecutionTrace(BaseModel):
    """执行追踪（V2.2 支持 Plan 栈管理，Phase A 支持嵌套子图层级）"""
    plan_id: str
    step_logs: List[StepLog] = Field(default_factory=list)
    final_status: str = "pending"  # pending, running, completed, failed
    # V2.2: Plan 栈管理，支持嵌套 Plan 执行
    plan_stack: List[str] = Field(default_factory=list)  # Plan ID 栈
    root_plan_id: Optional[str] = None  # 根 Plan ID
    # Phase A: 子图层级追踪
    subgraph_traces: Dict[str, "ExecutionTrace"] = Field(default_factory=dict)  # subgraph_id -> ExecutionTrace
    parent_trace_id: Optional[str] = None  # 父 Trace ID

    def push_plan(self, plan_id: str) -> None:
        """将 Plan ID 入栈"""
        self.plan_stack.append(plan_id)

    def pop_plan(self) -> Optional[str]:
        """将 Plan ID 出栈"""
        return self.plan_stack.pop() if self.plan_stack else None

    def current_plan_id(self) -> Optional[str]:
        """获取当前 Plan ID（栈顶）"""
        return self.plan_stack[-1] if self.plan_stack else None

    def add_log(self, log: StepLog) -> None:
        """添加日志"""
        self.step_logs.append(log)

    def add_subgraph_trace(self, subgraph_id: str, trace: "ExecutionTrace") -> None:
        """Phase A: 添加子图执行追踪"""
        self.subgraph_traces[subgraph_id] = trace
        trace.parent_trace_id = self.plan_id

    def get_subgraph_trace(self, subgraph_id: str) -> Optional["ExecutionTrace"]:
        """Phase A: 获取子图执行追踪"""
        return self.subgraph_traces.get(subgraph_id)

    def get_all_logs_with_hierarchy(self) -> List[StepLog]:
        """
        Phase A: 获取所有日志（包含子图），按层级展开。
        
        注意：此方法返回新的 StepLog 对象，避免原地修改导致的幂等性问题。
        多次调用结果一致，不会累计 depth。
        """
        return self._collect_logs_recursive(parent_step_id=None, base_depth=0)
    
    def _collect_logs_recursive(self, parent_step_id: Optional[str], base_depth: int) -> List[StepLog]:
        """
        递归收集日志，创建新的 StepLog 对象以避免原地修改。
        
        Args:
            parent_step_id: 父步骤 ID
            base_depth: 基础深度（用于计算当前层级）
        
        Returns:
            新的 StepLog 列表（不影响原始对象）
        """
        from copy import copy
        
        all_logs = []
        
        # 复制主图日志，设置正确的层级信息
        for log in self.step_logs:
            new_log = copy(log)
            new_log.parent_step_id = parent_step_id if parent_step_id is not None else log.parent_step_id
            new_log.depth = base_depth + log.depth
            all_logs.append(new_log)
        
        # 递归处理子图
        for subgraph_id, subgraph_trace in self.subgraph_traces.items():
            # 子图的日志深度 +1，parent_step_id 为 subgraph_id
            subgraph_logs = subgraph_trace._collect_logs_recursive(
                parent_step_id=subgraph_id,
                base_depth=base_depth + 1
            )
            all_logs.extend(subgraph_logs)
        
        # 按时间戳排序
        all_logs.sort(key=lambda x: x.timestamp)
        return all_logs

    def mark_running(self) -> None:
        """标记为运行中"""
        self.final_status = "running"

    def mark_completed(self) -> None:
        """标记为完成"""
        self.final_status = "completed"

    def mark_failed(self) -> None:
        """标记为失败"""
        self.final_status = "failed"


# ============== Helper Functions ==============
def create_atomic_step(
    executor: ExecutorType,
    inputs: Dict[str, Any],
    step_id: Optional[str] = None
) -> Step:
    """创建原子步骤的便捷函数"""
    return Step(
        step_id=step_id or f"step_{uuid.uuid4().hex[:8]}",
        type=StepType.ATOMIC,
        executor=executor,
        inputs=inputs,
    )


def create_composite_step(
    sub_plan: Plan,
    step_id: Optional[str] = None
) -> Step:
    """创建组合步骤的便捷函数"""
    return Step(
        step_id=step_id or f"step_{uuid.uuid4().hex[:8]}",
        type=StepType.COMPOSITE,
        executor=ExecutorType.INTERNAL,
        sub_plan=sub_plan,
    )


def create_simple_plan(
    goal: str,
    steps: List[Step],
    context: Optional[Dict[str, Any]] = None
) -> Plan:
    """创建简单计划的便捷函数"""
    return Plan(
        goal=goal,
        steps=steps,
        context=context or {},
    )


def create_replan_step(
    replan_instruction: str,
    executor: ExecutorType = ExecutorType.LLM,
    step_id: Optional[str] = None
) -> Step:
    """创建重规划步骤的便捷函数（V2.2）"""
    return Step(
        step_id=step_id or f"step_{uuid.uuid4().hex[:8]}",
        type=StepType.REPLAN,
        executor=executor,
        inputs={},
        replan_instruction=replan_instruction,
    )


