"""
V2.8 Inference Gateway Layer - Embedding Request Model

Dedicated request model for embedding inference (non-chat).
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, model_validator


class EmbeddingRequest(BaseModel):
    """
    Unified embedding request.

    Attributes:
        model_alias: Model alias or direct model_id for an embedding-capable model
        input: One string or a list of strings to embed
        metadata: Additional metadata for logging/tracing
    """

    model_alias: str = Field(..., description="Model alias or direct model_id")
    input: Union[str, List[str]] = Field(..., description="Input text(s) to embed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Observability metadata")

    @model_validator(mode="after")
    def validate_input(self):
        if isinstance(self.input, str):
            if not self.input.strip():
                raise ValueError("input must be non-empty")
        else:
            if not self.input:
                raise ValueError("input list must be non-empty")
            if any((not isinstance(x, str) or not x.strip()) for x in self.input):
                raise ValueError("all input items must be non-empty strings")
        return self

    class Config:
        extra = "forbid"

