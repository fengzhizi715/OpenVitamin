"""
Skill v2 Execution Contract.

定义统一的执行接口，确保：
- 所有 Skill 执行必须通过统一入口
- 不能直接调用 Skill 内部函数
- 必须记录 trace_id
- 自动捕获异常和填充 metrics
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional


@dataclass
class SkillExecutionRequest:
    """
    Skill 执行请求
    
    要求：
    - skill_id 必填
    - version 可选（不指定则使用 latest）
    - trace_id 必填（用于追踪）
    - caller_id 必填（用于审计）
    - input 必须符合 input_schema
    """
    skill_id: str
    input: Dict[str, Any]
    
    version: Optional[str] = None
    trace_id: str = ""
    caller_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> Optional[str]:
        """验证请求，返回错误信息或 None"""
        if not self.skill_id:
            return "skill_id is required"
        if self.input is None:
            return "input is required"
        if not isinstance(self.input, dict):
            return "input must be an object"
        return None


@dataclass
class SkillExecutionResponse:
    """
    Skill 执行响应
    
    状态：
    - success: 执行成功
    - error: 执行失败
    - timeout: 执行超时
    """
    status: Literal["success", "error", "timeout"]
    output: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    # 元信息（可选，用于返回）
    skill_id: str = ""
    version: str = ""
    trace_id: str = ""
    
    @classmethod
    def success(cls, output: Dict[str, Any], **kwargs) -> "SkillExecutionResponse":
        return cls(
            status="success",
            output=output,
            error=None,
            metrics=kwargs.pop("metrics", {}),
            skill_id=kwargs.pop("skill_id", ""),
            version=kwargs.pop("version", ""),
            trace_id=kwargs.pop("trace_id", "")
        )
    
    @classmethod
    def error(cls, error_code: str, error_message: str, **kwargs) -> "SkillExecutionResponse":
        return cls(
            status="error",
            output=None,
            error={
                "code": error_code,
                "message": error_message
            },
            metrics=kwargs.pop("metrics", {}),
            skill_id=kwargs.pop("skill_id", ""),
            version=kwargs.pop("version", ""),
            trace_id=kwargs.pop("trace_id", "")
        )
    
    @classmethod
    def timeout(cls, timeout_ms: int, **kwargs) -> "SkillExecutionResponse":
        return cls(
            status="timeout",
            output=None,
            error={
                "code": "TIMEOUT",
                "message": f"Execution timed out after {timeout_ms}ms"
            },
            metrics=kwargs.pop("metrics", {}),
            skill_id=kwargs.pop("skill_id", ""),
            version=kwargs.pop("version", ""),
            trace_id=kwargs.pop("trace_id", "")
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "metrics": self.metrics,
            "skill_id": self.skill_id,
            "version": self.version,
            "trace_id": self.trace_id,
        }


@dataclass
class ExecutionMetrics:
    """执行指标"""
    start_time: float = field(default_factory=time.perf_counter)
    end_time: Optional[float] = None
    latency_ms: float = 0.0
    
    # Token 使用（为未来 LLM 集成预留）
    token_usage: Dict[str, int] = field(default_factory=dict)  # input/output/total
    
    # 资源使用
    memory_usage_mb: float = 0.0
    cpu_time_ms: float = 0.0
    
    # 业务指标
    llm_calls: int = 0
    tool_calls: int = 0
    api_calls: int = 0
    
    # 成本估算（为未来计费功能预留）
    cost_usd: float = 0.0
    
    def finalize(self):
        """完成指标收集"""
        self.end_time = time.perf_counter()
        self.latency_ms = (self.end_time - self.start_time) * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "latency_ms": round(self.latency_ms, 2),
            "token_usage": self.token_usage,
            "memory_usage_mb": round(self.memory_usage_mb, 2),
            "cpu_time_ms": round(self.cpu_time_ms, 2),
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "api_calls": self.api_calls,
            "cost_usd": round(self.cost_usd, 4),
        }
