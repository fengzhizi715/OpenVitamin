"""
Quota Manager

资源配额管理，限制工作流的执行次数和资源使用。
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading

from log import logger


@dataclass
class QuotaConfig:
    """配额配置"""
    max_executions_per_hour: Optional[int] = None
    max_executions_per_day: Optional[int] = None
    max_concurrent: Optional[int] = None
    max_duration_seconds: Optional[int] = None
    max_tokens_per_execution: Optional[int] = None


@dataclass
class QuotaUsage:
    """配额使用情况"""
    executions_last_hour: int = 0
    executions_last_day: int = 0
    concurrent_executions: int = 0
    total_tokens_consumed: int = 0


class QuotaManager:
    """
    配额管理器
    
    管理工作流的资源配额，防止资源滥用。
    """
    
    def __init__(self):
        # 配额配置
        self._configs: Dict[str, QuotaConfig] = {}
        
        # 执行记录 (workflow_id -> list of execution timestamps)
        self._execution_history: Dict[str, list] = {}
        
        # 当前并发执行数
        self._concurrent_counts: Dict[str, int] = {}
        
        # Token 消耗统计
        self._token_consumption: Dict[str, int] = {}
        
        # 锁
        self._lock = threading.Lock()
    
    def set_quota(self, workflow_id: str, config: QuotaConfig) -> None:
        """设置工作流配额"""
        with self._lock:
            self._configs[workflow_id] = config
        logger.info(f"[QuotaManager] Set quota for workflow {workflow_id}: {config}")
    
    def get_quota(self, workflow_id: str) -> Optional[QuotaConfig]:
        """获取工作流配额"""
        return self._configs.get(workflow_id)
    
    def check_quota(
        self,
        workflow_id: str,
        estimated_tokens: Optional[int] = None
    ) -> tuple[bool, Optional[str]]:
        """
        检查配额
        
        Returns:
            (是否允许, 拒绝原因)
        """
        config = self._configs.get(workflow_id)
        if not config:
            # 没有配额限制
            return True, None
        
        with self._lock:
            # 清理过期记录
            self._cleanup_history(workflow_id)
            
            history = self._execution_history.get(workflow_id, [])
            concurrent = self._concurrent_counts.get(workflow_id, 0)
            
            # 检查每小时限制
            if config.max_executions_per_hour is not None:
                hour_ago = datetime.utcnow() - timedelta(hours=1)
                executions_last_hour = sum(
                    1 for ts in history if ts > hour_ago
                )
                if executions_last_hour >= config.max_executions_per_hour:
                    return False, f"Hourly quota exceeded ({config.max_executions_per_hour}/hour)"
            
            # 检查每天限制
            if config.max_executions_per_day is not None:
                day_ago = datetime.utcnow() - timedelta(days=1)
                executions_last_day = sum(
                    1 for ts in history if ts > day_ago
                )
                if executions_last_day >= config.max_executions_per_day:
                    return False, f"Daily quota exceeded ({config.max_executions_per_day}/day)"
            
            # 检查并发限制
            if config.max_concurrent is not None:
                if concurrent >= config.max_concurrent:
                    return False, f"Concurrent quota exceeded ({config.max_concurrent})"
            
            # 检查 Token 限制
            if estimated_tokens and config.max_tokens_per_execution is not None:
                if estimated_tokens > config.max_tokens_per_execution:
                    return False, f"Token quota exceeded ({config.max_tokens_per_execution} max)"
        
        return True, None
    
    def record_execution_start(self, workflow_id: str) -> None:
        """记录执行开始"""
        with self._lock:
            now = datetime.utcnow()
            
            # 添加到历史记录
            if workflow_id not in self._execution_history:
                self._execution_history[workflow_id] = []
            self._execution_history[workflow_id].append(now)
            
            # 增加并发计数
            self._concurrent_counts[workflow_id] = (
                self._concurrent_counts.get(workflow_id, 0) + 1
            )
        
        logger.debug(f"[QuotaManager] Recorded execution start for {workflow_id}")
    
    def record_execution_end(
        self,
        workflow_id: str,
        tokens_consumed: int = 0
    ) -> None:
        """记录执行结束"""
        with self._lock:
            # 减少并发计数
            current = self._concurrent_counts.get(workflow_id, 0)
            if current > 0:
                self._concurrent_counts[workflow_id] = current - 1
            
            # 记录 Token 消耗
            if tokens_consumed > 0:
                self._token_consumption[workflow_id] = (
                    self._token_consumption.get(workflow_id, 0) + tokens_consumed
                )
        
        logger.debug(
            f"[QuotaManager] Recorded execution end for {workflow_id}, "
            f"tokens: {tokens_consumed}"
        )
    
    def get_usage(self, workflow_id: str) -> QuotaUsage:
        """获取配额使用情况"""
        with self._lock:
            self._cleanup_history(workflow_id)
            
            history = self._execution_history.get(workflow_id, [])
            now = datetime.utcnow()
            
            hour_ago = now - timedelta(hours=1)
            day_ago = now - timedelta(days=1)
            
            return QuotaUsage(
                executions_last_hour=sum(1 for ts in history if ts > hour_ago),
                executions_last_day=sum(1 for ts in history if ts > day_ago),
                concurrent_executions=self._concurrent_counts.get(workflow_id, 0),
                total_tokens_consumed=self._token_consumption.get(workflow_id, 0)
            )
    
    def get_quota_status(self, workflow_id: str) -> Dict[str, Any]:
        """获取配额状态"""
        config = self._configs.get(workflow_id)
        usage = self.get_usage(workflow_id)
        
        status = {
            "workflow_id": workflow_id,
            "has_quota": config is not None,
            "usage": {
                "executions_last_hour": usage.executions_last_hour,
                "executions_last_day": usage.executions_last_day,
                "concurrent_executions": usage.concurrent_executions,
                "total_tokens_consumed": usage.total_tokens_consumed
            }
        }
        
        if config:
            status["limits"] = {
                "max_executions_per_hour": config.max_executions_per_hour,
                "max_executions_per_day": config.max_executions_per_day,
                "max_concurrent": config.max_concurrent,
                "max_duration_seconds": config.max_duration_seconds,
                "max_tokens_per_execution": config.max_tokens_per_execution
            }
            
            # 计算剩余配额
            status["remaining"] = {
                "executions_per_hour": (
                    config.max_executions_per_hour - usage.executions_last_hour
                    if config.max_executions_per_hour else None
                ),
                "executions_per_day": (
                    config.max_executions_per_day - usage.executions_last_day
                    if config.max_executions_per_day else None
                ),
                "concurrent": (
                    config.max_concurrent - usage.concurrent_executions
                    if config.max_concurrent else None
                )
            }
        
        return status
    
    def _cleanup_history(self, workflow_id: str) -> None:
        """清理过期历史记录"""
        if workflow_id not in self._execution_history:
            return
        
        # 保留最近 7 天的记录
        cutoff = datetime.utcnow() - timedelta(days=7)
        self._execution_history[workflow_id] = [
            ts for ts in self._execution_history[workflow_id]
            if ts > cutoff
        ]
    
    def reset_quota(self, workflow_id: str) -> None:
        """重置配额统计"""
        with self._lock:
            self._execution_history.pop(workflow_id, None)
            self._concurrent_counts.pop(workflow_id, None)
            self._token_consumption.pop(workflow_id, None)
        
        logger.info(f"[QuotaManager] Reset quota for workflow {workflow_id}")
