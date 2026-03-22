"""
V2.8 Inference Gateway Layer - Inference Request Model

Unified inference request - simpler than ChatCompletionRequest.
Designed for Skill/Agent → Gateway communication.
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any

from core.types import Message


class InferenceRequest(BaseModel):
    """
    Unified inference request model.
    
    Simpler than ChatCompletionRequest, designed for the Inference Gateway.
    Uses model_alias instead of model_id to support routing.
    
    Attributes:
        model_alias: Model alias (e.g., 'reasoning-model', 'fast-model') or direct model_id
        messages: Full message list (message-first, supports multimodal content parts)
        prompt: The input prompt/text (legacy convenience; converted to messages)
        system_prompt: Optional system prompt (only valid with prompt, not with messages)
        temperature: Sampling temperature (0-2)
        max_tokens: Maximum tokens to generate
        stream: Whether to stream the response
        stop: Stop sequences
        metadata: Additional metadata for logging/tracing
    """
    model_alias: str = Field(
        ...,
        description="Model alias (e.g., 'reasoning-model', 'fast-model') or direct model_id"
    )
    messages: Optional[List[Message]] = Field(
        default=None,
        description="Full message list (preferred). Supports multimodal content parts (text + image_url)."
    )
    prompt: Optional[str] = Field(
        default=None,
        description="Legacy convenience prompt; converted to messages if messages is not provided."
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="Optional system prompt (only valid with prompt, not with messages)"
    )
    temperature: float = Field(
        default=0.7,
        ge=0,
        le=2,
        description="Sampling temperature"
    )
    max_tokens: int = Field(
        default=2048,
        ge=1,
        le=8192,
        description="Maximum tokens to generate"
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream the response"
    )
    stop: Optional[List[str]] = Field(
        default=None,
        description="Stop sequences"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for logging/tracing"
    )

    @model_validator(mode="after")
    def validate_input_mode(self):
        """
        Deterministic input contract:
        - Prefer messages (message-first).
        - Forbid mixing messages with prompt/system_prompt to avoid implicit merging.
        """
        has_messages = isinstance(self.messages, list) and len(self.messages) > 0
        has_prompt = isinstance(self.prompt, str) and self.prompt.strip() != ""
        has_system = isinstance(self.system_prompt, str) and self.system_prompt.strip() != ""

        if has_messages and (has_prompt or has_system):
            raise ValueError("Provide either messages OR prompt/system_prompt, not both.")
        if not has_messages and not has_prompt:
            raise ValueError("Either 'messages' or non-empty 'prompt' must be provided.")
        if has_system and not has_prompt:
            raise ValueError("'system_prompt' is only valid when 'prompt' is provided.")
        return self

    class Config:
        extra = "forbid"  # Strict validation
