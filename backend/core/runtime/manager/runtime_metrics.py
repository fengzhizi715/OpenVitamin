"""
V2.9 Runtime Stabilization Layer - Runtime metrics.

Thread-safe aggregation: requests, latency, queue_size, tokens_generated.
"""
import threading
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class ModelMetrics:
    """Per-model metrics snapshot."""
    model_id: str
    requests: int = 0
    requests_failed: int = 0
    total_latency_ms: float = 0.0
    tokens_generated: int = 0
    queue_size: int = 0  # current waiting + in-flight (best-effort)

    @property
    def avg_latency_ms(self) -> float:
        if self.requests <= 0:
            return 0.0
        return self.total_latency_ms / self.requests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "requests": self.requests,
            "requests_failed": self.requests_failed,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "tokens_generated": self.tokens_generated,
            "queue_size": self.queue_size,
        }


class RuntimeMetrics:
    """
    Thread-safe runtime metrics.
    Records requests, latency, tokens; supports optional queue_size updates.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._by_model: Dict[str, ModelMetrics] = {}
        self._queue_sizes: Dict[str, int] = {}  # model_id -> current queue size (set by queue)

    def record_request(self, model_id: str) -> None:
        """Increment request count for model."""
        if not model_id:
            return
        with self._lock:
            m = self._by_model.setdefault(model_id, ModelMetrics(model_id=model_id))
            m.requests += 1
            m.queue_size = self._queue_sizes.get(model_id, 0)

    def record_request_failed(self, model_id: str) -> None:
        """Increment failed request count for model."""
        if not model_id:
            return
        with self._lock:
            m = self._by_model.setdefault(model_id, ModelMetrics(model_id=model_id))
            m.requests_failed += 1
            m.queue_size = self._queue_sizes.get(model_id, 0)

    def record_latency(self, model_id: str, latency_ms: float) -> None:
        """Record inference latency for model."""
        if not model_id or latency_ms < 0:
            return
        with self._lock:
            m = self._by_model.setdefault(model_id, ModelMetrics(model_id=model_id))
            m.total_latency_ms += latency_ms
            m.queue_size = self._queue_sizes.get(model_id, 0)

    def record_tokens(self, model_id: str, tokens: int) -> None:
        """Record tokens generated for model."""
        if not model_id or tokens < 0:
            return
        with self._lock:
            m = self._by_model.setdefault(model_id, ModelMetrics(model_id=model_id))
            m.tokens_generated += tokens
            m.queue_size = self._queue_sizes.get(model_id, 0)

    def set_queue_size(self, model_id: str, size: int) -> None:
        """Update current queue size for model (called by InferenceQueue)."""
        if not model_id:
            return
        with self._lock:
            self._queue_sizes[model_id] = max(0, size)
            if model_id in self._by_model:
                self._by_model[model_id].queue_size = self._queue_sizes[model_id]

    def get_metrics(self) -> Dict[str, Any]:
        """Return full metrics: global summary + per-model."""
        with self._lock:
            models = {}
            total_requests = 0
            total_failed = 0
            total_latency_ms = 0.0
            total_tokens = 0
            for mid, m in list(self._by_model.items()):
                m.queue_size = self._queue_sizes.get(mid, 0)
                models[mid] = m.to_dict()
                total_requests += m.requests
                total_failed += m.requests_failed
                total_latency_ms += m.total_latency_ms
                total_tokens += m.tokens_generated
            return {
                "summary": {
                    "total_requests": total_requests,
                    "total_requests_failed": total_failed,
                    "total_latency_ms": round(total_latency_ms, 2),
                    "total_tokens_generated": total_tokens,
                    "models_count": len(models),
                },
                "by_model": models,
            }

    def get_model_metrics(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Return metrics for one model."""
        with self._lock:
            m = self._by_model.get(model_id)
            if not m:
                return None
            m.queue_size = self._queue_sizes.get(model_id, 0)
            return m.to_dict()


# Singleton for process-wide metrics
_metrics: Optional[RuntimeMetrics] = None
_metrics_lock = threading.Lock()


def get_runtime_metrics() -> RuntimeMetrics:
    global _metrics
    with _metrics_lock:
        if _metrics is None:
            _metrics = RuntimeMetrics()
        return _metrics
