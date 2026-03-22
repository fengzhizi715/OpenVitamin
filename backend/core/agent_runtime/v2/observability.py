"""
Agent V2 可观测性：性能指标收集与结构化日志接入

- 结构化日志：使用平台统一 log_structured（backend/log）
- 性能指标：单次 run 的 plan 创建耗时、步骤耗时、replan 次数等
- Execution Kernel 指标：成功率、回退率、执行引擎切换等
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime
import threading

from log import log_structured


# ---------- 性能指标 ----------

@dataclass
class AgentV2Metrics:
    """单次 Agent V2 运行的性能指标"""
    agent_id: str = ""
    session_id: str = ""
    plan_id: str = ""
    plan_creation_ms: Optional[float] = None
    total_run_ms: Optional[float] = None
    step_count: int = 0
    replan_count: int = 0
    step_durations_ms: Dict[str, float] = field(default_factory=dict)
    final_status: str = ""
    
    # Execution Kernel 相关指标
    execution_engine: str = ""  # "kernel" | "plan_based"
    kernel_fallback: bool = False  # Kernel 失败回退到 PlanBasedExecutor
    kernel_instance_id: str = ""  # Kernel 实例 ID（用于追踪）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "plan_id": self.plan_id,
            "plan_creation_ms": self.plan_creation_ms,
            "total_run_ms": self.total_run_ms,
            "step_count": self.step_count,
            "replan_count": self.replan_count,
            "step_durations_ms": dict(self.step_durations_ms),
            "final_status": self.final_status,
            "execution_engine": self.execution_engine,
            "kernel_fallback": self.kernel_fallback,
            "kernel_instance_id": self.kernel_instance_id,
        }

    def log_summary(self) -> None:
        """将本次运行指标以结构化日志输出"""
        log_structured(
            "Metrics",
            "run_summary",
            level="info",
            **self.to_dict(),
        )


# ---------- Execution Kernel 聚合指标 ----------

class ExecutionKernelStats:
    """
    Execution Kernel 聚合统计（内存级，定期刷入日志）
    
    指标：
    - 计划成功率（plan success rate）
    - 步骤失败率
    - RePlan 触发率
    - 平均耗时（p50 / p95）
    - 回退率（Kernel -> PlanBasedExecutor fallback）
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._reset()
        return cls._instance
    
    def _reset(self):
        """重置统计"""
        self._total_runs = 0
        self._kernel_runs = 0
        self._plan_based_runs = 0
        self._kernel_success = 0
        self._kernel_failed = 0
        self._kernel_fallbacks = 0
        self._total_replans = 0
        self._total_steps = 0
        self._failed_steps = 0
        self._run_durations_ms: list = []
        self._last_flush = datetime.utcnow()
    
    def record_run(
        self,
        engine: str,
        success: bool,
        fallback: bool = False,
        replan_count: int = 0,
        step_count: int = 0,
        failed_steps: int = 0,
        duration_ms: float = 0,
    ):
        """记录一次执行"""
        self._total_runs += 1
        
        if engine == "kernel":
            self._kernel_runs += 1
            if success:
                self._kernel_success += 1
            else:
                self._kernel_failed += 1
            if fallback:
                self._kernel_fallbacks += 1
        else:
            self._plan_based_runs += 1
        
        self._total_replans += replan_count
        self._total_steps += step_count
        self._failed_steps += failed_steps
        
        if duration_ms > 0:
            self._run_durations_ms.append(duration_ms)
        
        # 每 100 次运行刷新一次日志
        if self._total_runs % 100 == 0:
            self.flush()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取当前统计"""
        durations = sorted(self._run_durations_ms) if self._run_durations_ms else []
        count = len(durations)
        
        def percentile(p: float) -> Optional[float]:
            if not count:
                return None
            idx = int(count * p / 100)
            idx = min(idx, count - 1)
            return durations[idx]
        
        return {
            "total_runs": self._total_runs,
            "kernel_runs": self._kernel_runs,
            "plan_based_runs": self._plan_based_runs,
            "kernel_success_rate": (
                self._kernel_success / self._kernel_runs * 100
                if self._kernel_runs > 0 else 0
            ),
            "kernel_fallback_rate": (
                self._kernel_fallbacks / self._kernel_runs * 100
                if self._kernel_runs > 0 else 0
            ),
            "step_fail_rate": (
                self._failed_steps / self._total_steps * 100
                if self._total_steps > 0 else 0
            ),
            "replan_trigger_rate": (
                self._total_replans / self._total_runs
                if self._total_runs > 0 else 0
            ),
            "avg_duration_ms": sum(durations) / count if count > 0 else 0,
            "p50_duration_ms": percentile(50),
            "p95_duration_ms": percentile(95),
        }
    
    def flush(self):
        """刷新统计到日志"""
        stats = self.get_stats()
        stats["flush_time"] = datetime.utcnow().isoformat()
        log_structured("KernelStats", "aggregate", level="info", **stats)


def get_kernel_stats() -> ExecutionKernelStats:
    """获取全局统计实例"""
    return ExecutionKernelStats()
