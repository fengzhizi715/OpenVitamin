"""
V2.8 Inference Gateway Layer - Inference Gateway

Central inference routing hub.
Coordinates ModelRouter and ProviderRuntimeAdapter.
"""
from typing import AsyncIterator, Optional

from log import logger

from core.inference.router.model_router import ModelRouter, RoutingResult
from core.inference.providers.provider_runtime_adapter import ProviderRuntimeAdapter
from core.inference.models.inference_request import InferenceRequest
from core.inference.models.inference_response import InferenceResponse
from core.inference.models.embedding_request import EmbeddingRequest
from core.inference.models.embedding_response import EmbeddingResponse
from core.inference.models.asr_request import ASRRequest
from core.inference.models.asr_response import ASRResponse


class InferenceGateway:
    """
    Central inference routing hub.
    
    Coordinates:
    1. Model alias resolution (ModelRouter)
    2. Provider dispatch (ProviderRuntimeAdapter)
    
    Does NOT:
    - Know about specific models
    - Handle business logic
    - Manage state
    
    Usage:
        gateway = InferenceGateway()
        response = await gateway.generate(request)
    """
    
    def __init__(self):
        self.router = ModelRouter()
        self.adapter = ProviderRuntimeAdapter()

    @staticmethod
    def _validate_messages(request: InferenceRequest) -> None:
        """
        Deterministic guards for message-first requests.

        - Do not reorder messages (User-in-Control).
        - Validate common provider constraints early.
        - Prevent obvious prompt bloat (e.g., huge data URLs) from crashing runtimes.
        """
        messages = getattr(request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return

        # Basic prompt bloat guard: prevent pathological payloads from crashing runtimes.
        total_text_chars = 0
        total_image_url_chars = 0

        # Many chat templates require system messages to be at the beginning.
        saw_non_system = False
        for m in messages:
            role = getattr(m, "role", None) if not isinstance(m, dict) else m.get("role")
            if role == "system":
                if saw_non_system:
                    raise ValueError("System message must be at the beginning.")
            else:
                saw_non_system = True

            content = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
            if isinstance(content, str):
                total_text_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    item_type = getattr(item, "type", None) if not isinstance(item, dict) else item.get("type")
                    if item_type != "image_url":
                        if item_type == "text":
                            text = getattr(item, "text", None) if not isinstance(item, dict) else item.get("text")
                            if isinstance(text, str):
                                total_text_chars += len(text)
                        continue
                    image_url = getattr(item, "image_url", None) if not isinstance(item, dict) else item.get("image_url")
                    url = (image_url or {}).get("url", "") if isinstance(image_url, dict) else ""
                    if isinstance(url, str):
                        total_image_url_chars += len(url)
                    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
                        raise ValueError("image_url must be a data URL (data:image/...) in this deployment.")
                    if isinstance(url, str) and url.startswith("data:image/") and len(url) > 2_000_000:
                        raise ValueError("image_url data URL is too large; provide a workspace file reference instead.")

        if total_text_chars > 200_000:
            raise ValueError("messages text content too large; reduce context or chunk the request.")
        if total_image_url_chars > 6_000_000:
            raise ValueError("messages image content too large; reduce image size or number of images.")
    
    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """
        Execute non-streaming inference.
        
        Args:
            request: InferenceRequest with model_alias and prompt
            
        Returns:
            InferenceResponse with generated text
        """
        self._validate_messages(request)
        # 1. Route alias to provider + model_id
        routing = self.router.resolve(request.model_alias)
        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[InferenceGateway] Routing alias=%s -> %s/%s via=%s session_id=%s trace_id=%s agent_id=%s",
            request.model_alias,
            routing.provider,
            routing.model_id,
            routing.resolved_via,
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )
        
        # 2. Execute via adapter
        if routing.resolved_via == "direct":
            # Passthrough: use model_alias as model_id directly
            return await self.adapter.generate(
                "auto",
                request.model_alias,
                request
            )
        
        return await self.adapter.generate(
            routing.provider,
            routing.model_id,
            request
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        routing = self.router.resolve(request.model_alias)
        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[InferenceGateway] Embed routing alias=%s -> %s/%s via=%s session_id=%s trace_id=%s agent_id=%s",
            request.model_alias,
            routing.provider,
            routing.model_id,
            routing.resolved_via,
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )
        if routing.resolved_via == "direct":
            return await self.adapter.embed("auto", request.model_alias, request)
        return await self.adapter.embed(routing.provider, routing.model_id, request)

    async def transcribe(self, request: ASRRequest) -> ASRResponse:
        routing = self.router.resolve(request.model_alias)
        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[InferenceGateway] ASR routing alias=%s -> %s/%s via=%s session_id=%s trace_id=%s agent_id=%s",
            request.model_alias,
            routing.provider,
            routing.model_id,
            routing.resolved_via,
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )
        if routing.resolved_via == "direct":
            return await self.adapter.transcribe("auto", request.model_alias, request)
        return await self.adapter.transcribe(routing.provider, routing.model_id, request)
    
    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """
        Execute streaming inference.
        
        Args:
            request: InferenceRequest with model_alias and prompt
            
        Yields:
            Token strings
        """
        self._validate_messages(request)
        # 1. Route alias to provider + model_id
        routing = self.router.resolve(request.model_alias)
        
        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[InferenceGateway] Stream routing alias=%s -> %s/%s via=%s session_id=%s trace_id=%s agent_id=%s",
            request.model_alias,
            routing.provider,
            routing.model_id,
            routing.resolved_via,
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )
        
        # 2. Stream via adapter
        if routing.resolved_via == "direct":
            async for token in self.adapter.stream(
                "auto",
                request.model_alias,
                request
            ):
                yield token
            return
        
        async for token in self.adapter.stream(
            routing.provider,
            routing.model_id,
            request
        ):
            yield token
    
    def get_routing_info(self, model_alias: str) -> RoutingResult:
        """
        Get routing information without executing inference.
        
        Args:
            model_alias: The alias to resolve
            
        Returns:
            RoutingResult with resolution details
        """
        return self.router.resolve(model_alias)
    
    def list_available_models(self) -> list:
        """List all available model aliases"""
        return self.router.list_available_models()


# Singleton
_gateway = None


def get_inference_gateway() -> InferenceGateway:
    """Get the global InferenceGateway singleton"""
    global _gateway
    if _gateway is None:
        _gateway = InferenceGateway()
    return _gateway
