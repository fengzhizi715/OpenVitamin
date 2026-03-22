"""
V2.8 Inference Gateway Layer - ASR Response Model
"""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ASRResponse(BaseModel):
    """
    Unified ASR response.

    Attributes:
        text: Full transcription text
        language: Detected language
        segments: Optional timestamp segments
        provider: Provider name
        model: Actual model id used
        model_alias: Original alias requested
        metadata: Additional response metadata
    """

    text: str = Field(default="", description="Transcription text")
    language: str = Field(default="unknown", description="Detected language")
    segments: List[Dict[str, Any]] = Field(default_factory=list, description="Timestamp segments")
    provider: str = Field(default="", description="Provider name")
    model: str = Field(default="", description="Actual model used")
    model_alias: str = Field(default="", description="Original alias requested")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @property
    def success(self) -> bool:
        return bool(self.text.strip())

