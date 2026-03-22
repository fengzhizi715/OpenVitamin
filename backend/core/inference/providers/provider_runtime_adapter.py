"""
V2.8 Inference Gateway Layer - Provider Runtime Adapter

Adapts existing runtimes to InferenceGateway interface.
Wraps RuntimeFactory and ModelRegistry without modification.
"""
from typing import AsyncIterator, Optional, Dict, List
import asyncio
import time
from dataclasses import dataclass

from log import logger, log_structured
from core.runtimes.factory import get_runtime_factory
from core.models.registry import get_model_registry
from core.types import ChatCompletionRequest, Message
from core.runtimes.base import EmbeddingRuntime

from core.inference.models.inference_request import InferenceRequest
from core.inference.models.inference_response import InferenceResponse, TokenUsage
from core.inference.models.embedding_request import EmbeddingRequest
from core.inference.models.embedding_response import EmbeddingResponse
from core.inference.models.asr_request import ASRRequest
from core.inference.models.asr_response import ASRResponse
from core.inference.stats.tracker import record_inference, estimate_tokens

from core.runtime import (
    get_model_instance_manager,
    get_inference_queue_manager,
    get_runtime_metrics,
)


@dataclass
class RuntimeCapabilities:
    """Describes a runtime's capabilities"""
    runtime_name: str
    supports_streaming: bool
    streaming_type: str  # "native", "fake", "none"
    description: str


# Stream support matrix for different runtimes
# "native" = true token-by-token streaming
# "fake" = yields all content at once (no real streaming)
# "none" = streaming not supported
RUNTIME_STREAM_SUPPORT: Dict[str, RuntimeCapabilities] = {
    # Registry/runtime identifiers used in this codebase
    "llama.cpp": RuntimeCapabilities(
        runtime_name="llama.cpp",
        supports_streaming=True,
        streaming_type="native",
        description="llama.cpp GGUF models - full streaming support",
    ),
    "torch": RuntimeCapabilities(
        runtime_name="torch",
        supports_streaming=True,
        streaming_type="fake",
        description="Torch models - fake streaming (yields all at once)",
    ),
    "gemini": RuntimeCapabilities(
        runtime_name="gemini",
        supports_streaming=True,
        streaming_type="native",
        description="OpenAI-compatible APIs - full streaming support",
    ),
    "deepseek": RuntimeCapabilities(
        runtime_name="deepseek",
        supports_streaming=True,
        streaming_type="native",
        description="OpenAI-compatible APIs - full streaming support",
    ),
    "kimi": RuntimeCapabilities(
        runtime_name="kimi",
        supports_streaming=True,
        streaming_type="native",
        description="OpenAI-compatible APIs - full streaming support",
    ),
    "lmstudio": RuntimeCapabilities(
        runtime_name="lmstudio",
        supports_streaming=True,
        streaming_type="native",
        description="OpenAI-compatible APIs - full streaming support",
    ),
    "llama_cpp": RuntimeCapabilities(
        runtime_name="llama_cpp",
        supports_streaming=True,
        streaming_type="native",
        description="llama.cpp GGUF models - full streaming support"
    ),
    "mlx": RuntimeCapabilities(
        runtime_name="mlx",
        supports_streaming=True,
        streaming_type="native",
        description="Apple MLX models - full streaming support"
    ),
    "openai": RuntimeCapabilities(
        runtime_name="openai",
        supports_streaming=True,
        streaming_type="native",
        description="OpenAI-compatible APIs - full streaming support"
    ),
    "ollama": RuntimeCapabilities(
        runtime_name="ollama",
        supports_streaming=True,
        streaming_type="native",
        description="Ollama server - full streaming support"
    ),
    "torch_vlm": RuntimeCapabilities(
        runtime_name="torch_vlm",
        supports_streaming=True,
        streaming_type="fake",
        description="Torch VLM models - fake streaming (yields all at once)"
    ),
    "llama_vlm": RuntimeCapabilities(
        runtime_name="llama_vlm",
        supports_streaming=False,
        streaming_type="none",
        description="LlamaCpp VLM - streaming not implemented"
    ),
}


class ProviderRuntimeAdapter:
    """
    Adapts existing runtimes to InferenceGateway interface.
    
    Bridges the new InferenceRequest/Response models with the
    existing RuntimeFactory and ModelRegistry.
    
    Does NOT modify existing runtimes - only wraps them.
    
    Usage:
        adapter = ProviderRuntimeAdapter()
        response = await adapter.generate("ollama", "qwen2", request)
    """
    
    def __init__(self):
        self.runtime_factory = get_runtime_factory()
        self.model_registry = get_model_registry()

    @staticmethod
    def _request_has_image(messages: list) -> bool:
        try:
            for m in messages or []:
                content = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
                if not isinstance(content, list):
                    continue
                for item in content:
                    item_type = getattr(item, "type", None) if not isinstance(item, dict) else item.get("type")
                    if item_type == "image_url":
                        return True
        except Exception:
            return False
        return False

    @staticmethod
    def _validate_multimodal_support(descriptor, messages: list) -> None:
        """
        Deterministic multimodal policy:
        - If request includes images, the target model must advertise vision capability.
        - Do not silently drop images or convert modalities.
        """
        if not ProviderRuntimeAdapter._request_has_image(messages):
            return

        model_type = (getattr(descriptor, "model_type", "") or "").lower()
        caps = getattr(descriptor, "capabilities", None) or []
        caps_l = {str(c).lower() for c in caps if isinstance(c, str)}

        supports = (
            model_type in {"vlm", "vision", "multimodal"}
            or "vision" in caps_l
            or "multimodal" in caps_l
            or "vlm" in caps_l
        )
        if not supports:
            raise ValueError(
                f"Model '{getattr(descriptor, 'id', '')}' does not support image inputs. "
                "Use a VLM/vision model or remove image_url content parts."
            )
    
    async def generate(
        self,
        provider: str,
        model_id: str,
        request: InferenceRequest
    ) -> InferenceResponse:
        """
        Execute non-streaming inference via existing runtime system.
        
        Args:
            provider: Provider name (used for logging/fallback)
            model_id: Concrete model ID to use
            request: The inference request
            
        Returns:
            InferenceResponse with generated text
        """
        start_time = time.time()
        
        # Build ChatCompletionRequest for existing system
        messages = self._build_messages(request)
        
        cc_request = ChatCompletionRequest(
            model=model_id,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
            stop=request.stop
        )
        
        # Get descriptor and runtime
        descriptor = self._find_model(model_id, provider)
        
        if not descriptor:
            raise ValueError(f"Model not found: {model_id} (provider: {provider})")

        # Explicit multimodal compatibility check (no silent degradation).
        self._validate_multimodal_support(descriptor, messages)

        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[ProviderRuntimeAdapter] generate provider=%s model=%s runtime=%s session_id=%s trace_id=%s agent_id=%s",
            getattr(descriptor, "provider", provider),
            getattr(descriptor, "id", model_id),
            getattr(descriptor, "runtime", ""),
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )

        instance_manager = get_model_instance_manager()
        queue_manager = get_inference_queue_manager()
        metrics = get_runtime_metrics()
        model_id_key = descriptor.id
        runtime_type = getattr(descriptor, "runtime", "") or "default"

        runtime = await instance_manager.get_instance(model_id_key)
        queue = queue_manager.get_queue(model_id_key, runtime_type)

        log_structured(
            "RuntimeStabilization",
            "inference_started",
            model_id=model_id_key,
            runtime=runtime_type,
        )
        metrics.record_request(model_id_key)

        try:
            text = await queue.run(runtime.chat(descriptor, cc_request))
        except Exception as e:
            metrics.record_request_failed(model_id_key)
            log_structured(
                "RuntimeStabilization",
                "inference_error",
                level="error",
                model_id=model_id_key,
                error=str(e)[:500],
            )
            logger.error(
                "[ProviderRuntimeAdapter] Inference failed provider=%s model_id=%s runtime=%s error=%s",
                provider,
                model_id,
                getattr(descriptor, "runtime", ""),
                str(e)[:300],
            )
            raise RuntimeError(f"Inference failed for {descriptor.id}: {e}") from e

        latency_ms = (time.time() - start_time) * 1000
        metrics.record_latency(model_id_key, latency_ms)
        estimated_tokens = estimate_tokens(text)
        metrics.record_tokens(model_id_key, estimated_tokens)
        record_inference(
            tokens=estimated_tokens,
            latency_ms=latency_ms,
            model=descriptor.id,
            provider=descriptor.provider
        )
        log_structured(
            "RuntimeStabilization",
            "inference_completed",
            model_id=model_id_key,
            latency_ms=round(latency_ms, 2),
            tokens=estimated_tokens,
        )
        
        return InferenceResponse(
            text=text,
            usage=TokenUsage(),  # Existing runtimes don't return usage
            latency_ms=latency_ms,
            provider=descriptor.provider,
            model=descriptor.id,
            model_alias=request.model_alias
        )
    
    async def stream(
        self,
        provider: str,
        model_id: str,
        request: InferenceRequest
    ) -> AsyncIterator[str]:
        """
        Execute streaming inference via existing runtime system.
        
        Args:
            provider: Provider name (used for logging/fallback)
            model_id: Concrete model ID to use
            request: The inference request
            
        Yields:
            Token strings
        """
        start_time = time.time()
        # NOTE: Many runtimes yield "text deltas"/chunks, not actual model tokens.
        # For system-level t/s telemetry we estimate tokens from output length
        # to avoid reporting "chunks/s" as "tokens/s".
        output_chars = 0
        
        messages = self._build_messages(request)
        
        cc_request = ChatCompletionRequest(
            model=model_id,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True,
            stop=request.stop
        )
        
        descriptor = self._find_model(model_id, provider)
        
        if not descriptor:
            raise ValueError(f"Model not found: {model_id}")

        # Explicit multimodal compatibility check (no silent degradation).
        self._validate_multimodal_support(descriptor, messages)

        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[ProviderRuntimeAdapter] stream provider=%s model=%s runtime=%s session_id=%s trace_id=%s agent_id=%s",
            getattr(descriptor, "provider", provider),
            getattr(descriptor, "id", model_id),
            getattr(descriptor, "runtime", ""),
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )

        instance_manager = get_model_instance_manager()
        queue_manager = get_inference_queue_manager()
        metrics = get_runtime_metrics()
        model_id_key = descriptor.id
        runtime_type = getattr(descriptor, "runtime", "") or "default"

        runtime = await instance_manager.get_instance(model_id_key)
        queue = queue_manager.get_queue(model_id_key, runtime_type)

        log_structured(
            "RuntimeStabilization",
            "inference_started",
            model_id=model_id_key,
            runtime=runtime_type,
        )
        metrics.record_request(model_id_key)

        completed_normally = False
        try:
            async def _stream():
                async for token in runtime.stream_chat(descriptor, cc_request):
                    if token:
                        nonlocal output_chars
                        output_chars += len(token)
                    yield token

            async for token in queue.run_stream(_stream()):
                yield token
            completed_normally = True
        except Exception as e:
            metrics.record_request_failed(model_id_key)
            log_structured(
                "RuntimeStabilization",
                "inference_error",
                level="error",
                model_id=model_id_key,
                error=str(e)[:500],
            )
            raise
        finally:
            latency_ms = (time.time() - start_time) * 1000
            metrics.record_latency(model_id_key, latency_ms)
            if output_chars > 0:
                tokens_est = max(1, output_chars // 4)
                metrics.record_tokens(model_id_key, tokens_est)
                record_inference(
                    tokens=tokens_est,
                    latency_ms=latency_ms,
                    model=descriptor.id,
                    provider=descriptor.provider
                )
            if completed_normally:
                log_structured(
                    "RuntimeStabilization",
                    "inference_completed",
                    model_id=model_id_key,
                    latency_ms=round(latency_ms, 2),
                    output_chars=output_chars,
                )

    async def embed(self, provider: str, model_id: str, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        Execute embedding inference via existing embedding runtime system.
        """
        descriptor = self._find_model(model_id, provider)
        if not descriptor:
            raise ValueError(f"Embedding model not found: {model_id} (provider: {provider})")

        model_type = (getattr(descriptor, "model_type", "") or "").lower()
        caps = getattr(descriptor, "capabilities", None) or []
        caps_l = {str(c).lower() for c in caps if isinstance(c, str)}
        if model_type != "embedding" and "embedding" not in caps_l:
            raise ValueError(f"Model {descriptor.id} is not an embedding model (model_type={model_type})")

        instance_manager = get_model_instance_manager()
        queue_manager = get_inference_queue_manager()
        metrics = get_runtime_metrics()
        model_id_key = descriptor.id
        runtime_type = getattr(descriptor, "runtime", "") or "default"

        rt = await instance_manager.get_instance(model_id_key)
        if not isinstance(rt, EmbeddingRuntime):
            raise ValueError(f"Embedding runtime not available for model {descriptor.id} (runtime={descriptor.runtime})")

        queue = queue_manager.get_queue(model_id_key, runtime_type)
        texts = [request.input] if isinstance(request.input, str) else list(request.input)
        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[ProviderRuntimeAdapter] embed provider=%s model=%s runtime=%s batch=%s session_id=%s trace_id=%s agent_id=%s",
            getattr(descriptor, "provider", provider),
            getattr(descriptor, "id", model_id),
            getattr(descriptor, "runtime", ""),
            len(texts),
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )

        metrics.record_request(model_id_key)
        start_embed = time.time()
        try:
            loop = asyncio.get_running_loop()
            async def _embed_coro():
                return await loop.run_in_executor(None, lambda: rt.embed(texts))
            embeddings = await queue.run(_embed_coro())
        except Exception as e:
            metrics.record_request_failed(model_id_key)
            raise
        latency_ms = (time.time() - start_embed) * 1000
        metrics.record_latency(model_id_key, latency_ms)

        return EmbeddingResponse(
            embeddings=embeddings,
            provider=getattr(descriptor, "provider", ""),
            model=getattr(descriptor, "id", model_id),
            model_alias=request.model_alias,
        )

    async def transcribe(self, provider: str, model_id: str, request: ASRRequest) -> ASRResponse:
        """
        Execute ASR transcription via existing ASR runtime system.
        """
        import base64
        import os
        import tempfile
        from pathlib import Path
        from core.tools.sandbox import resolve_in_workspace, WorkspacePathError

        descriptor = self._find_model(model_id, provider)
        if not descriptor:
            raise ValueError(f"ASR model not found: {model_id} (provider: {provider})")

        model_type = (getattr(descriptor, "model_type", "") or "").lower()
        if model_type != "asr":
            raise ValueError(f"Model {descriptor.id} is not an ASR model (model_type={model_type})")

        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[ProviderRuntimeAdapter] transcribe provider=%s model=%s runtime=%s session_id=%s trace_id=%s agent_id=%s",
            getattr(descriptor, "provider", provider),
            getattr(descriptor, "id", model_id),
            getattr(descriptor, "runtime", ""),
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )

        instance_manager = get_model_instance_manager()
        queue_manager = get_inference_queue_manager()
        metrics = get_runtime_metrics()
        model_id_key = descriptor.id
        runtime_type = getattr(descriptor, "runtime", "") or "default"

        runtime = await instance_manager.get_instance(model_id_key)
        queue = queue_manager.get_queue(model_id_key, runtime_type)
        metrics.record_request(model_id_key)
        start_transcribe = time.time()

        audio = request.audio.strip()
        tmp_path = None
        try:
            if audio.startswith("http://") or audio.startswith("https://"):
                raise ValueError("audio must be a workspace file reference or data: URL (http(s) not allowed)")

            if audio.startswith("data:"):
                # data:audio/...;base64,<payload>
                if "," not in audio:
                    raise ValueError("Invalid audio data URL")
                header, b64 = audio.split(",", 1)
                if "base64" not in header:
                    raise ValueError("Only base64 data URLs are supported for audio")
                raw = base64.b64decode(b64)
                if len(raw) > 20 * 1024 * 1024:
                    raise ValueError("Audio payload too large")

                suffix = ".webm"
                h = header.lower()
                if "wav" in h:
                    suffix = ".wav"
                elif "mpeg" in h or "mp3" in h:
                    suffix = ".mp3"
                elif "mp4" in h or "m4a" in h:
                    suffix = ".m4a"
                elif "ogg" in h:
                    suffix = ".ogg"

                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                    f.write(raw)
                    tmp_path = f.name
                audio_path = tmp_path
            else:
                ws = str(request.workspace or "").strip()
                if not ws:
                    raise ValueError("workspace is required for audio path inputs")

                # Resolve safely inside workspace. Absolute paths are allowed only if under workspace root.
                try:
                    resolved = resolve_in_workspace(workspace=ws, path=audio, allowed_absolute_roots=[ws])
                except WorkspacePathError as e:
                    raise ValueError(str(e)) from e
                if not resolved.exists() or not resolved.is_file():
                    raise FileNotFoundError(f"Audio file not found: {audio}")
                audio_path = str(Path(resolved).resolve())

            async def _transcribe_coro():
                return await runtime.transcribe(audio_path, options=request.options or {})
            try:
                result = await queue.run(_transcribe_coro())
            except Exception:
                metrics.record_request_failed(model_id_key)
                raise
            latency_ms = (time.time() - start_transcribe) * 1000
            metrics.record_latency(model_id_key, latency_ms)
            return ASRResponse(
                text=str(result.get("text", "") or ""),
                language=str(result.get("language", "unknown") or "unknown"),
                segments=result.get("segments") or [],
                provider=getattr(descriptor, "provider", ""),
                model=getattr(descriptor, "id", model_id),
                model_alias=request.model_alias,
            )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
    
    def _build_messages(self, request: InferenceRequest) -> list:
        """
        Build message list from InferenceRequest (message-first).

        Contract:
        - If request.messages is provided: use it as-is (supports multimodal content items).
        - Else: build minimal system+user from prompt/system_prompt.
        """
        if isinstance(getattr(request, "messages", None), list) and request.messages:
            # Pydantic already validated Message schema, keep exact ordering for determinism.
            return list(request.messages)

        messages = []
        if request.system_prompt:
            messages.append(Message(role="system", content=request.system_prompt))
        messages.append(Message(role="user", content=request.prompt or ""))
        return messages
    
    def _find_model(self, model_id: str, provider: str):
        """
        Find model descriptor by ID or provider_model_id.
        
        Args:
            model_id: Model ID to find
            provider: Provider hint (for logging)
            
        Returns:
            ModelDescriptor or None
        """
        # Try exact ID match first
        descriptor = self.model_registry.get_model(model_id)
        if descriptor:
            return descriptor
        
        # Try provider_model_id match
        for m in self.model_registry.list_models():
            if m.provider_model_id == model_id:
                return m
        
        logger.debug(
            f"[ProviderRuntimeAdapter] Model '{model_id}' not found "
            f"in registry (provider: {provider})"
        )
        return None
    
    def list_available_models(self) -> list:
        """List all models available in the registry"""
        return self.model_registry.list_models()
    
    def get_runtime_capabilities(self, runtime_name: str) -> RuntimeCapabilities:
        """
        Get capabilities for a specific runtime.
        
        Args:
            runtime_name: Runtime identifier (e.g., "llama_cpp", "openai")
            
        Returns:
            RuntimeCapabilities for the runtime
        """
        # Normalize common runtime naming differences
        rt = (runtime_name or "").strip()
        normalize = {
            "llama.cpp": "llama.cpp",
            "llama_cpp": "llama.cpp",
            "torch_vlm": "torch",
            "torch_model_runtime": "torch",
        }
        rt = normalize.get(rt, rt)
        return RUNTIME_STREAM_SUPPORT.get(
            rt,
            RuntimeCapabilities(
                runtime_name=rt or runtime_name,
                supports_streaming=True,  # Assume streaming works
                streaming_type="native",
                description=f"Unknown runtime: {rt or runtime_name}"
            )
        )
    
    def get_model_capabilities(self, model_id: str) -> RuntimeCapabilities:
        """
        Get streaming capabilities for a specific model.
        
        Args:
            model_id: Model ID to check
            
        Returns:
            RuntimeCapabilities for the model's runtime
        """
        descriptor = self._find_model(model_id, "")
        if not descriptor:
            return RuntimeCapabilities(
                runtime_name="unknown",
                supports_streaming=False,
                streaming_type="none",
                description=f"Model not found: {model_id}"
            )
        
        return self.get_runtime_capabilities(descriptor.runtime)
    
    def list_streaming_support(self) -> Dict[str, RuntimeCapabilities]:
        """
        List streaming support for all known runtimes.
        
        Returns:
            Dict mapping runtime names to their capabilities
        """
        return dict(RUNTIME_STREAM_SUPPORT)
