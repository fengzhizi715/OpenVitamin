"""
V2.9 Runtime Stabilization Layer 单元测试示例。

运行方式（在 backend 目录下）：
  pytest tests/test_runtime_stabilization.py -v
"""
import asyncio
import pytest

from core.runtime.config import get_max_concurrency, DEFAULT_KEY
from core.runtime.manager.runtime_metrics import RuntimeMetrics


class TestRuntimeConfig:
    """Runtime config (max_concurrency)."""

    def test_get_max_concurrency_default(self):
        assert get_max_concurrency("") >= 1
        assert get_max_concurrency("unknown_runtime") >= 1

    def test_get_max_concurrency_llama_cpp(self):
        assert get_max_concurrency("llama.cpp") == 1

    def test_get_max_concurrency_ollama(self):
        assert get_max_concurrency("ollama") == 4

    def test_get_max_concurrency_torch(self):
        assert get_max_concurrency("torch") == 2


class TestRuntimeMetrics:
    """RuntimeMetrics: record and get_metrics."""

    def test_record_and_get_metrics(self):
        m = RuntimeMetrics()
        m.record_request("model-a")
        m.record_request("model-a")
        m.record_latency("model-a", 100.0)
        m.record_latency("model-a", 200.0)
        m.record_tokens("model-a", 50)
        m.record_request_failed("model-b")
        out = m.get_metrics()
        assert "summary" in out
        assert out["summary"]["total_requests"] == 2
        assert out["summary"]["total_requests_failed"] == 1
        assert out["summary"]["total_tokens_generated"] == 50
        assert "model-a" in out["by_model"]
        assert out["by_model"]["model-a"]["requests"] == 2
        assert out["by_model"]["model-a"]["avg_latency_ms"] == 150.0
        assert out["by_model"]["model-a"]["tokens_generated"] == 50

    def test_get_model_metrics_missing(self):
        m = RuntimeMetrics()
        assert m.get_model_metrics("nonexistent") is None

    def test_get_model_metrics_exists(self):
        m = RuntimeMetrics()
        m.record_request("m1")
        m.record_latency("m1", 50.0)
        one = m.get_model_metrics("m1")
        assert one is not None
        assert one["model_id"] == "m1"
        assert one["requests"] == 1
        assert one["avg_latency_ms"] == 50.0


@pytest.mark.asyncio
class TestInferenceQueue:
    """InferenceQueue: semaphore limits concurrency."""

    async def test_run_returns_result(self):
        from core.runtime.queue.inference_queue import InferenceQueue
        q = InferenceQueue(model_id="test-model", max_concurrency=2)

        async def coro():
            return 42
        result = await q.run(coro())
        assert result == 42

    async def test_run_limits_concurrency(self):
        from core.runtime.queue.inference_queue import InferenceQueue
        max_c = 1
        q = InferenceQueue(model_id="test-model", max_concurrency=max_c)
        in_flight = 0
        max_seen = 0

        async def slow_coro():
            nonlocal in_flight, max_seen
            in_flight += 1
            max_seen = max(max_seen, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return 1

        # Run 3 concurrently; with max_concurrency=1 only one should run at a time
        tasks = [q.run(slow_coro()) for _ in range(3)]
        results = await asyncio.gather(*tasks)
        assert sum(results) == 3
        assert max_seen == 1

    async def test_run_stream_yields_all(self):
        from core.runtime.queue.inference_queue import InferenceQueue
        q = InferenceQueue(model_id="stream-model", max_concurrency=1)

        async def agen():
            for i in range(3):
                yield i

        collected = []
        async for x in q.run_stream(agen()):
            collected.append(x)
        assert collected == [0, 1, 2]


class TestInferenceQueueManager:
    """InferenceQueueManager: get_queue per model."""

    def test_get_queue_same_model_same_queue(self):
        from core.runtime.queue.inference_queue import InferenceQueueManager
        mgr = InferenceQueueManager()
        q1 = mgr.get_queue("model-1", "llama.cpp")
        q2 = mgr.get_queue("model-1", "llama.cpp")
        assert q1 is q2
        assert q1.model_id == "model-1"
        assert q1.max_concurrency == 1

    def test_get_queue_different_runtime_concurrency(self):
        from core.runtime.queue.inference_queue import InferenceQueueManager
        mgr = InferenceQueueManager()
        q_ollama = mgr.get_queue("ollama-model", "ollama")
        q_llama = mgr.get_queue("llama-model", "llama.cpp")
        assert q_ollama.max_concurrency == 4
        assert q_llama.max_concurrency == 1


class TestModelInstanceManagerImport:
    """ModelInstanceManager can be imported and get_instance is callable (no registry)."""

    def test_manager_import(self):
        from core.runtime import get_model_instance_manager
        mgr = get_model_instance_manager()
        assert mgr is not None
        assert callable(mgr.get_instance)
        assert callable(mgr.list_instances)


class TestRuntimeMetricsAPI:
    """Runtime metrics API: structure returned by get_metrics() is what the API exposes."""

    def test_runtime_metrics_structure(self):
        """Same structure as GET /api/system/runtime-metrics."""
        from core.runtime import get_runtime_metrics
        data = get_runtime_metrics().get_metrics()
        assert "summary" in data
        assert "by_model" in data
        assert "total_requests" in data["summary"]
        assert "total_requests_failed" in data["summary"]
        assert "total_latency_ms" in data["summary"]
        assert "total_tokens_generated" in data["summary"]
        assert "models_count" in data["summary"]
