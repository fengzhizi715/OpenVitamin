"""
V2.8 Inference Gateway Layer

Unified inference API for Agent/Skill → Model decoupling.

This module provides a clean abstraction layer between:
- Skills/Agents (callers)
- Model Runtimes (providers)

Key Benefits:
- Model aliasing (e.g., "reasoning-model" → "deepseek-r1")
- Provider abstraction
- Centralized routing
- Backward compatibility (direct model_id passthrough)

Usage:
    from core.inference import InferenceClient
    
    client = InferenceClient()
    
    # Non-streaming
    response = await client.generate(
        model="reasoning-model",
        prompt="Hello"
    )
    print(response.text)
    
    # Streaming
    async for token in client.stream(model="fast-model", prompt="Hello"):
        print(token, end="", flush=True)

Architecture:
    InferenceClient
        ↓
    InferenceGateway
        ↓
    ModelRouter → ProviderRuntimeAdapter
        ↓
    RuntimeFactory → Model Runtime
"""

from core.inference.models.inference_request import InferenceRequest
from core.inference.models.inference_response import InferenceResponse, TokenUsage
from core.inference.models.embedding_request import EmbeddingRequest
from core.inference.models.embedding_response import EmbeddingResponse
from core.inference.models.asr_request import ASRRequest
from core.inference.models.asr_response import ASRResponse
from core.inference.client.inference_client import InferenceClient, get_inference_client
from core.inference.gateway.inference_gateway import InferenceGateway, get_inference_gateway
from core.inference.router.model_router import ModelRouter, RoutingResult
from core.inference.registry.model_registry import (
    InferenceModelRegistry,
    ModelAlias,
    get_inference_model_registry,
)
from core.inference.streaming.token_stream import TokenStream, collect_stream
from core.inference.providers.provider_runtime_adapter import (
    RuntimeCapabilities,
    RUNTIME_STREAM_SUPPORT,
)

__all__ = [
    # Client (primary entry point)
    "InferenceClient",
    "get_inference_client",
    # Models
    "InferenceRequest",
    "InferenceResponse",
    "TokenUsage",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "ASRRequest",
    "ASRResponse",
    # Gateway
    "InferenceGateway",
    "get_inference_gateway",
    # Router
    "ModelRouter",
    "RoutingResult",
    # Registry
    "InferenceModelRegistry",
    "ModelAlias",
    "get_inference_model_registry",
    # Streaming
    "TokenStream",
    "collect_stream",
    # Capabilities
    "RuntimeCapabilities",
    "RUNTIME_STREAM_SUPPORT",
]
