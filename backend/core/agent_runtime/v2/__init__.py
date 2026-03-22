"""
Agent V2 执行内核
可扩展的 Plan-Based 执行架构
"""
from .models import (
    ExecutionMode,
    StepType,
    ExecutorType,
    StepStatus,
    Step,
    Plan,
    AgentState,
    StepLog,
    ExecutionTrace,
    create_atomic_step,
    create_composite_step,
    create_simple_plan,
)
from .executors import (
    BaseExecutor,
    LLMExecutor,
    SkillExecutor,
    ToolChainExecutor,
    InternalExecutor,
    ExecutorFactory,
)
from .planner import Planner, get_planner
from .executor_v2 import PlanBasedExecutor

__all__ = [
    # Models
    "ExecutionMode",
    "StepType",
    "ExecutorType", 
    "StepStatus",
    "Step",
    "Plan",
    "AgentState",
    "StepLog",
    "ExecutionTrace",
    "create_atomic_step",
    "create_composite_step",
    "create_simple_plan",
    # Executors
    "BaseExecutor",
    "LLMExecutor",
    "SkillExecutor",
    "ToolChainExecutor",
    "InternalExecutor",
    "ExecutorFactory",
    # Planner
    "Planner",
    "get_planner",
    # Runtime
    "PlanBasedExecutor",
    "AgentRuntime",
    "get_agent_runtime",
]


def __getattr__(name):
    # Lazy import runtime to avoid importing heavy optional deps during module import.
    if name in {"AgentRuntime", "get_agent_runtime"}:
        from .runtime import AgentRuntime, get_agent_runtime
        if name == "AgentRuntime":
            return AgentRuntime
        return get_agent_runtime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
