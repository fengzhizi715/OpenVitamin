"""
V2.8 Inference Gateway Layer - Inference Response Model

Unified inference response with usage tracking and metadata.
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, List


class TokenUsage(BaseModel):
    """Token usage statistics"""
    prompt_tokens: int = Field(default=0, description="Tokens in the prompt")
    completion_tokens: int = Field(default=0, description="Tokens in the completion")
    total_tokens: int = Field(default=0, description="Total tokens used")


class InferenceResponse(BaseModel):
    """
    Unified inference response model.
    
    Provides a consistent response format regardless of the underlying provider.
    
    Attributes:
        text: The generated text
        tokens: List of tokens (for streaming scenarios)
        usage: Token usage statistics
        latency_ms: Total latency in milliseconds
        provider: Provider name (e.g., 'ollama', 'openai')
        model: Actual model ID used
        model_alias: Original alias requested
        finish_reason: Why generation stopped
        metadata: Additional response metadata
    """
    text: str = Field(
        default="",
        description="Generated text"
    )
    tokens: List[str] = Field(
        default_factory=list,
        description="Token list (for streaming)"
    )
    usage: TokenUsage = Field(
        default_factory=TokenUsage,
        description="Token usage statistics"
    )
    latency_ms: float = Field(
        default=0.0,
        description="Total latency in milliseconds"
    )
    provider: str = Field(
        default="",
        description="Provider name (e.g., 'ollama', 'openai')"
    )
    model: str = Field(
        default="",
        description="Actual model used"
    )
    model_alias: str = Field(
        default="",
        description="Original alias requested"
    )
    finish_reason: str = Field(
        default="stop",
        description="Why generation stopped"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional response metadata"
    )

    @property
    def success(self) -> bool:
        """Check if the response was successful"""
        return bool(self.text) and self.finish_reason != "error"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "text": self.text,
            "tokens": self.tokens,
            "usage": self.usage.model_dump(),
            "latency_ms": self.latency_ms,
            "provider": self.provider,
            "model": self.model,
            "model_alias": self.model_alias,
            "finish_reason": self.finish_reason,
            "metadata": self.metadata,
        }
