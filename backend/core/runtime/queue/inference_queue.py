"""
V2.9 Runtime Stabilization Layer - Inference queue.

Per-model concurrency limit via asyncio.Semaphore.
"""
import asyncio
import threading
from typing import Dict, TypeVar, AsyncIterator, Optional
from log import logger

from core.runtime.config import get_max_concurrency

T = TypeVar("T")


class InferenceQueue:
    """
    Limits concurrent inference for one model.
    Uses a semaphore; run(coro) runs the coroutine under the semaphore.
    """

    def __init__(self, model_id: str, max_concurrency: int):
        self.model_id = model_id
        self._max_concurrency = max(1, max_concurrency)
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._in_flight = 0
        self._waiting = 0
        self._lock = asyncio.Lock()

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    def try_update_max_concurrency(self, new_max: int) -> bool:
        """
        Best-effort update of max_concurrency for this queue.

        Safety:
        - Only updates when idle (no waiting + no in-flight), so we don't change
          semaphore behavior mid-run.
        - Returns False if queue is busy or new_max is invalid/same.
        """
        new_max = max(1, int(new_max))
        if new_max == self._max_concurrency:
            return False
        # Best-effort check (not atomic); good enough to avoid surprising changes.
        if self._in_flight != 0 or self._waiting != 0:
            return False
        self._max_concurrency = new_max
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        return True

    async def _inc_usage(self) -> None:
        async with self._lock:
            self._in_flight += 1
            self._notify_queue_size()

    async def _dec_usage(self) -> None:
        async with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._notify_queue_size()

    def _notify_queue_size(self) -> None:
        try:
            from core.runtime.manager.runtime_metrics import get_runtime_metrics
            get_runtime_metrics().set_queue_size(self.model_id, self._waiting + self._in_flight)
        except Exception:
            pass

    def current_usage(self) -> int:
        """Best-effort: in-flight count (waiting not tracked atomically)."""
        return self._in_flight

    async def run(self, coro):
        """
        Run coroutine with concurrency limit.
        Returns the result of the coroutine.
        """
        acquired = False
        async with self._lock:
            self._waiting += 1
            self._notify_queue_size()
        try:
            async with self._semaphore:
                async with self._lock:
                    acquired = True
                    self._waiting = max(0, self._waiting - 1)
                await self._inc_usage()
                try:
                    return await coro
                finally:
                    await self._dec_usage()
        finally:
            # If we were cancelled/failed before acquiring the semaphore,
            # decrement waiting here; otherwise waiting was already decremented.
            if not acquired:
                async with self._lock:
                    self._waiting = max(0, self._waiting - 1)
                    self._notify_queue_size()

    async def run_stream(self, agen: AsyncIterator[T]) -> AsyncIterator[T]:
        """
        Run async generator under the semaphore.
        Semaphore is held for the entire consumption of the stream.
        """
        acquired = False
        async with self._lock:
            self._waiting += 1
            self._notify_queue_size()
        try:
            async with self._semaphore:
                async with self._lock:
                    acquired = True
                    self._waiting = max(0, self._waiting - 1)
                await self._inc_usage()
                try:
                    async for item in agen:
                        yield item
                finally:
                    await self._dec_usage()
        finally:
            if not acquired:
                async with self._lock:
                    self._waiting = max(0, self._waiting - 1)
                    self._notify_queue_size()


class InferenceQueueManager:
    """
    Per-model inference queues.
    Creates one InferenceQueue per model_id with max_concurrency from config (by runtime_type).
    """

    def __init__(self):
        self._queues: Dict[str, InferenceQueue] = {}
        self._lock = threading.Lock()

    def get_queue(self, model_id: str, runtime_type: str) -> InferenceQueue:
        """Get or create queue for model_id; concurrency from model metadata > settings > MODEL_RUNTIME_CONFIG."""
        with self._lock:
            max_concurrency = get_max_concurrency(runtime_type, model_id=model_id)
            if model_id in self._queues:
                q = self._queues[model_id]
                if q.try_update_max_concurrency(max_concurrency):
                    logger.info(
                        "[RuntimeStabilization] Updated queue max_concurrency model_id=%s runtime=%s max_concurrency=%s",
                        model_id,
                        runtime_type,
                        max_concurrency,
                    )
                return q
            q = InferenceQueue(model_id=model_id, max_concurrency=max_concurrency)
            self._queues[model_id] = q
            return q

    def list_queues(self) -> Dict[str, InferenceQueue]:
        with self._lock:
            return dict(self._queues)


# Singleton (thread-safe for first access)
_queue_manager: Optional[InferenceQueueManager] = None
_queue_manager_lock = threading.Lock()


def get_inference_queue_manager() -> InferenceQueueManager:
    global _queue_manager
    with _queue_manager_lock:
        if _queue_manager is None:
            _queue_manager = InferenceQueueManager()
        return _queue_manager
