"""
V2.8 Inference Gateway Layer - Inference Client

Primary entry point for Skills and Agents to make inference calls.
Provides a simple, clean API that hides the complexity of routing and providers.
"""
from typing import AsyncIterator, Optional

from core.inference.gateway.inference_gateway import (
    InferenceGateway,
    get_inference_gateway,
)
from core.inference.models.inference_request import InferenceRequest
from core.inference.models.inference_response import InferenceResponse
from core.inference.models.embedding_request import EmbeddingRequest
from core.inference.models.embedding_response import EmbeddingResponse
from core.inference.models.asr_request import ASRRequest
from core.inference.models.asr_response import ASRResponse


class InferenceClient:
    """
    Unified inference client for Skills and Agents.
    
    This is the PRIMARY entry point for all inference calls.
    Skills and Agents should use this client instead of
    directly calling RuntimeFactory or ModelRegistry.
    
    Usage:
        client = InferenceClient()
        
        # Non-streaming
        response = await client.generate(
            model="reasoning-model",
            prompt="Explain quantum entanglement",
            temperature=0.2
        )
        print(response.text)
        
        # Streaming
        async for token in client.stream(
            model="fast-model",
            prompt="Hello"
        ):
            print(token, end="", flush=True)
        
        # With system prompt
        response = await client.generate(
            model="assistant",
            prompt="What is 2+2?",
            system_prompt="You are a helpful math tutor."
        )
    
    Architecture:
        InferenceClient
            ↓
        InferenceGateway
            ↓
        ModelRouter → ProviderRuntimeAdapter
            ↓
        RuntimeFactory → Model Runtime
    """
    
    def __init__(self, gateway: Optional[InferenceGateway] = None):
        """
        Initialize the client.
        
        Args:
            gateway: Optional InferenceGateway instance (for testing)
        """
        self._gateway = gateway or get_inference_gateway()
    
    async def generate(
        self,
        model: str,
        prompt: Optional[str] = None,
        messages: Optional[list] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[list] = None,
        metadata: Optional[dict] = None
    ) -> InferenceResponse:
        """
        Execute non-streaming inference.
        
        Args:
            model: Model alias or direct model_id
            prompt: The input prompt/text
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            metadata: Additional metadata for logging
            
        Returns:
            InferenceResponse with generated text
        """
        request = InferenceRequest(
            model_alias=model,
            messages=messages,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            stop=stop,
            metadata=metadata or {},
        )
        return await self._gateway.generate(request)
    
    async def stream(
        self,
        model: str,
        prompt: Optional[str] = None,
        messages: Optional[list] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[list] = None
    ) -> AsyncIterator[str]:
        """
        Execute streaming inference.
        
        Args:
            model: Model alias or direct model_id
            prompt: The input prompt/text
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            
        Yields:
            Token strings
        """
        request = InferenceRequest(
            model_alias=model,
            messages=messages,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stop=stop,
        )
        async for token in self._gateway.stream(request):
            yield token

    async def embed(
        self,
        model: str,
        input_text,
        metadata: Optional[dict] = None,
    ) -> EmbeddingResponse:
        req = EmbeddingRequest(
            model_alias=model,
            input=input_text,
            metadata=metadata or {},
        )
        return await self._gateway.embed(req)

    async def transcribe(
        self,
        model: str,
        audio: str,
        *,
        workspace: Optional[str] = None,
        options: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> ASRResponse:
        req = ASRRequest(
            model_alias=model,
            audio=audio,
            workspace=workspace,
            options=options or {},
            metadata=metadata or {},
        )
        return await self._gateway.transcribe(req)
    
    def get_routing_info(self, model: str):
        """
        Get routing information for a model alias.
        
        Args:
            model: Model alias to resolve
            
        Returns:
            RoutingResult with resolution details
        """
        return self._gateway.get_routing_info(model)
    
    def list_available_models(self) -> list:
        """
        List all available model aliases.
        
        Returns:
            List of alias names
        """
        return self._gateway.list_available_models()
    
    def get_streaming_capabilities(self, model: str):
        """
        Get streaming capabilities for a model.
        
        Args:
            model: Model alias or model_id
            
        Returns:
            RuntimeCapabilities describing streaming support
        """
        from core.inference.providers.provider_runtime_adapter import ProviderRuntimeAdapter
        adapter = ProviderRuntimeAdapter()
        return adapter.get_model_capabilities(model)
    
    def refresh_registry(self) -> int:
        """
        Refresh the model registry to pick up new models.
        
        Call this when models are added/removed dynamically.
        
        Returns:
            Number of new aliases added
        """
        from core.inference.registry.model_registry import get_inference_model_registry
        registry = get_inference_model_registry()
        return registry.refresh()
    
    # ==================== Migration Helpers ====================
    # These methods help migrate from legacy code patterns
    
    @classmethod
    def from_executor_llm_call(cls, model_id: str, messages: list, temperature: float = 0.7) -> "InferenceClient":
        """
        Migration helper: Create client configured like AgentExecutor.llm_call.
        
        DEPRECATED: Use InferenceClient().generate() directly.
        
        This helper exists to ease migration from:
            executor = AgentExecutor()
            result = await executor.llm_call(model_id, messages, temperature)
        
        To:
            client = InferenceClient()
            result = await client.generate(model=model_id, prompt=..., temperature=temperature)
        
        Args:
            model_id: Model ID (will be used as alias)
            messages: List of Message objects (only last user message used)
            temperature: Sampling temperature
            
        Returns:
            InferenceClient instance (for chaining)
        """
        import warnings
        warnings.warn(
            "from_executor_llm_call is deprecated. Use InferenceClient().generate() directly.",
            DeprecationWarning,
            stacklevel=2
        )
        return cls()
    
    async def legacy_llm_call(self, model_id: str, messages: list, temperature: float = 0.7) -> str:
        """
        Migration helper: Mimic AgentExecutor.llm_call behavior.
        
        DEPRECATED: Use generate() instead.
        
        This method provides backward-compatible behavior for code
        migrating from AgentExecutor.llm_call().
        
        Args:
            model_id: Model ID
            messages: List of Message objects
            temperature: Sampling temperature
            
        Returns:
            Generated text string (not InferenceResponse)
        """
        import warnings
        warnings.warn(
            "legacy_llm_call is deprecated. Use generate() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        # Extract prompt from messages
        prompt = ""
        system_prompt = None
        
        for msg in messages:
            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                if msg.role == "system":
                    system_prompt = msg.content
                elif msg.role == "user":
                    prompt = msg.content
            elif isinstance(msg, dict):
                if msg.get("role") == "system":
                    system_prompt = msg.get("content")
                elif msg.get("role") == "user":
                    prompt = msg.get("content", "")
        
        response = await self.generate(
            model=model_id,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature
        )
        return response.text


def get_inference_client() -> InferenceClient:
    """
    Get an InferenceClient instance.
    
    Returns:
        InferenceClient instance
    """
    return InferenceClient()
