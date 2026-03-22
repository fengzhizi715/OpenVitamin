"""
Concurrency Limiter

并发控制机制，限制同时执行的 Workflow 数量。
"""

import asyncio
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import threading

from log import logger


@dataclass
class ConcurrencySlot:
    """并发槽位"""
    execution_id: str
    workflow_id: str
    acquired_at: datetime = field(default_factory=datetime.utcnow)


class ConcurrencyLimiter:
    """
    并发限制器
    
    控制同时执行的 Workflow 数量，防止系统过载。
    """
    
    def __init__(
        self,
        global_limit: int = 10,
        per_workflow_limit: int = 3
    ):
        self.global_limit = global_limit
        self.per_workflow_limit = per_workflow_limit
        
        # 全局信号量
        self._global_semaphore = asyncio.Semaphore(global_limit)
        
        # 每个工作流的信号量
        self._workflow_semaphores: Dict[str, asyncio.Semaphore] = {}
        
        # 已占用的槽位
        self._slots: Dict[str, ConcurrencySlot] = {}
        self._slots_lock = threading.Lock()
        
        # 等待队列
        self._waiting_global: Set[str] = set()
        self._waiting_per_workflow: Dict[str, Set[str]] = {}
    
    async def acquire(
        self,
        execution_id: str,
        workflow_id: str,
        timeout: Optional[float] = None
    ) -> bool:
        """
        获取执行槽位
        
        Args:
            execution_id: 执行 ID
            workflow_id: 工作流 ID
            timeout: 超时时间（秒）
        
        Returns:
            是否成功获取
        """
        # 获取或创建工作流信号量
        if workflow_id not in self._workflow_semaphores:
            self._workflow_semaphores[workflow_id] = asyncio.Semaphore(
                self.per_workflow_limit
            )

        workflow_semaphore = self._workflow_semaphores[workflow_id]

        # 非阻塞快速路径：timeout=0 时直接尝试一次，不进入 wait_for（避免被立即 Timeout）。
        if timeout == 0:
            if self._global_semaphore._value <= 0 or workflow_semaphore._value <= 0:
                return False
            self._global_semaphore._value -= 1
            workflow_semaphore._value -= 1
            with self._slots_lock:
                self._slots[execution_id] = ConcurrencySlot(
                    execution_id=execution_id,
                    workflow_id=workflow_id,
                )
            logger.debug(
                f"[ConcurrencyLimiter] Acquired slot (non-blocking) for {execution_id} "
                f"(global: {self._global_semaphore._value}, "
                f"workflow {workflow_id}: {workflow_semaphore._value})"
            )
            return True
        
        try:
            # 添加到等待队列
            self._waiting_global.add(execution_id)
            if workflow_id not in self._waiting_per_workflow:
                self._waiting_per_workflow[workflow_id] = set()
            self._waiting_per_workflow[workflow_id].add(execution_id)
            
            # 尝试获取全局槽位
            acquired_global = await asyncio.wait_for(
                self._global_semaphore.acquire(),
                timeout=timeout
            )
            
            if not acquired_global:
                return False
            
            try:
                # 尝试获取工作流槽位
                acquired_workflow = await asyncio.wait_for(
                    workflow_semaphore.acquire(),
                    timeout=timeout
                )
                
                if not acquired_workflow:
                    self._global_semaphore.release()
                    return False
                
                # 记录槽位
                with self._slots_lock:
                    self._slots[execution_id] = ConcurrencySlot(
                        execution_id=execution_id,
                        workflow_id=workflow_id
                    )
                
                # 从等待队列移除
                self._waiting_global.discard(execution_id)
                self._waiting_per_workflow[workflow_id].discard(execution_id)
                
                logger.debug(
                    f"[ConcurrencyLimiter] Acquired slot for {execution_id} "
                    f"(global: {self._global_semaphore._value}, "
                    f"workflow {workflow_id}: {workflow_semaphore._value})"
                )
                return True
                
            except asyncio.TimeoutError:
                self._global_semaphore.release()
                return False
                
        except asyncio.TimeoutError:
            return False
        finally:
            # 确保从等待队列移除
            self._waiting_global.discard(execution_id)
            if workflow_id in self._waiting_per_workflow:
                self._waiting_per_workflow[workflow_id].discard(execution_id)
    
    def release(self, execution_id: str) -> bool:
        """
        释放执行槽位
        
        Args:
            execution_id: 执行 ID
        
        Returns:
            是否成功释放
        """
        with self._slots_lock:
            slot = self._slots.pop(execution_id, None)
        
        if not slot:
            return False
        
        # 释放工作流信号量
        workflow_semaphore = self._workflow_semaphores.get(slot.workflow_id)
        if workflow_semaphore:
            try:
                workflow_semaphore.release()
            except ValueError:
                # 信号量已经满了
                pass
        
        # 释放全局信号量
        try:
            self._global_semaphore.release()
        except ValueError:
            # 信号量已经满了
            pass
        
        logger.debug(
            f"[ConcurrencyLimiter] Released slot for {execution_id}"
        )
        return True
    
    def get_status(self) -> Dict[str, any]:
        """获取并发状态"""
        with self._slots_lock:
            active_count = len(self._slots)
            active_per_workflow: Dict[str, int] = {}
            for slot in self._slots.values():
                active_per_workflow[slot.workflow_id] = (
                    active_per_workflow.get(slot.workflow_id, 0) + 1
                )
        
        return {
            "global_limit": self.global_limit,
            "global_available": self._global_semaphore._value,
            "global_active": active_count,
            "global_waiting": len(self._waiting_global),
            "per_workflow_limit": self.per_workflow_limit,
            "per_workflow_active": active_per_workflow,
            "per_workflow_waiting": {
                wf_id: len(waiting)
                for wf_id, waiting in self._waiting_per_workflow.items()
            }
        }
    
    def is_acquired(self, execution_id: str) -> bool:
        """检查是否已获取槽位"""
        with self._slots_lock:
            return execution_id in self._slots
    
    def get_slot_info(self, execution_id: str) -> Optional[ConcurrencySlot]:
        """获取槽位信息"""
        with self._slots_lock:
            return self._slots.get(execution_id)
