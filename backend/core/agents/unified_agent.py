from typing import AsyncIterator, Optional, Dict, Any
import time

from core.inference.stats.tracker import record_inference, estimate_tokens
from core.agents.base import ModelAgent
from core.types import ChatCompletionRequest
from core.models.selector import get_model_selector
from core.runtimes.factory import get_runtime_factory
from core.models.descriptor import ModelDescriptor
from core.runtime.queue.inference_queue import get_inference_queue_manager
from core.runtime.manager.model_instance_manager import get_model_instance_manager
from core.runtime.manager.runtime_metrics import get_runtime_metrics
from log import log_structured

class UnifiedModelAgent(ModelAgent):
    """
    统一模型代理
    不直接负责推理，而是根据请求调度到正确的 Runtime
    """
    def __init__(self):
        self.selector = get_model_selector()
        self.runtime_factory = get_runtime_factory()

    async def chat(self, req: ChatCompletionRequest) -> str:
        start_time = time.time()
        # 1. 解析模型
        descriptor = self.selector.resolve(
            model_id=req.model, 
            model_require=req.model_require if hasattr(req, "model_require") else None
        )
        
        instance_manager = get_model_instance_manager()
        queue_manager = get_inference_queue_manager()
        metrics = get_runtime_metrics()
        runtime_type = getattr(descriptor, "runtime", "") or "default"

        # 2) 获取实例（懒加载 + 单次加载锁）
        runtime = await instance_manager.get_instance(descriptor.id)
        queue = queue_manager.get_queue(descriptor.id, runtime_type)

        metrics.record_request(descriptor.id)
        log_structured("RuntimeStabilization", "inference_started", model_id=descriptor.id, runtime=runtime_type)

        # 3) 调用运行时（按模型并发限流）
        try:
            async with self.runtime_factory.model_usage(descriptor.id):
                text = await queue.run(runtime.chat(descriptor, req))
        except Exception:
            metrics.record_request_failed(descriptor.id)
            log_structured("RuntimeStabilization", "inference_error", level="error", model_id=descriptor.id, runtime=runtime_type)
            raise

        # Update system inference telemetry (t/s) for UI panels.
        latency_ms = (time.time() - start_time) * 1000
        metrics.record_latency(descriptor.id, latency_ms)
        record_inference(
            tokens=estimate_tokens(text),
            latency_ms=latency_ms,
            model=descriptor.id,
            provider=descriptor.provider,
        )
        metrics.record_tokens(descriptor.id, estimate_tokens(text))
        log_structured(
            "RuntimeStabilization",
            "inference_completed",
            model_id=descriptor.id,
            runtime=runtime_type,
            latency_ms=round(latency_ms, 2),
        )
        return text

    async def stream_chat(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        start_time = time.time()
        output_chars = 0
        # 1. 解析模型
        descriptor = self.selector.resolve(
            model_id=req.model, 
            model_require=req.model_require if hasattr(req, "model_require") else None
        )
        
        instance_manager = get_model_instance_manager()
        queue_manager = get_inference_queue_manager()
        metrics = get_runtime_metrics()
        runtime_type = getattr(descriptor, "runtime", "") or "default"

        runtime = await instance_manager.get_instance(descriptor.id)
        queue = queue_manager.get_queue(descriptor.id, runtime_type)

        metrics.record_request(descriptor.id)
        log_structured("RuntimeStabilization", "inference_started", model_id=descriptor.id, runtime=runtime_type)

        completed_normally = False
        try:
            async with self.runtime_factory.model_usage(descriptor.id):
                async def _stream():
                    async for token in runtime.stream_chat(descriptor, req):
                        if token:
                            nonlocal output_chars
                            output_chars += len(token)
                        yield token
                async for token in queue.run_stream(_stream()):
                    yield token
            completed_normally = True
        except Exception:
            metrics.record_request_failed(descriptor.id)
            log_structured("RuntimeStabilization", "inference_error", level="error", model_id=descriptor.id, runtime=runtime_type)
            raise
        finally:
            latency_ms = (time.time() - start_time) * 1000
            metrics.record_latency(descriptor.id, latency_ms)
            if output_chars > 0 and latency_ms > 0:
                tokens_est = max(1, output_chars // 4)
                record_inference(
                    tokens=tokens_est,
                    latency_ms=latency_ms,
                    model=descriptor.id,
                    provider=descriptor.provider,
                )
                metrics.record_tokens(descriptor.id, tokens_est)
            if completed_normally:
                log_structured(
                    "RuntimeStabilization",
                    "inference_completed",
                    model_id=descriptor.id,
                    runtime=runtime_type,
                    latency_ms=round(latency_ms, 2),
                    output_chars=output_chars,
                )

    def model_info(self) -> dict:
        """这个方法在 UnifiedAgent 中意义较小，因为它代理了所有模型"""
        return {
            "backend": "unified",
            "supports_stream": True,
            "supports_functions": True
        }
