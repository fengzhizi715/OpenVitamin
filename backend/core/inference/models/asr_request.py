"""
V2.8 Inference Gateway Layer - ASR Request Model

Dedicated request model for ASR transcription (non-chat).
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator


class ASRRequest(BaseModel):
    """
    Unified ASR transcription request.

    Attributes:
        model_alias: Model alias or direct model_id for an ASR model
        audio: Audio input (workspace-relative path, or data:audio/... base64 URL)
        workspace: Required when audio is a relative path (used to resolve safely)
        options: Optional ASR runtime options (language, beam_size, vad_filter, etc.)
        metadata: Additional metadata for logging/tracing
    """

    model_alias: str = Field(..., description="Model alias or direct model_id")
    audio: str = Field(..., description="Audio input: workspace-relative path or data:audio/... base64 URL")
    workspace: Optional[str] = Field(default=None, description="Workspace path used to resolve relative audio paths")
    options: Dict[str, Any] = Field(default_factory=dict, description="ASR options")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Observability metadata")

    @model_validator(mode="after")
    def validate_audio(self):
        if not isinstance(self.audio, str) or not self.audio.strip():
            raise ValueError("audio must be a non-empty string")
        if not self.audio.startswith("data:"):
            # Path mode: require workspace for determinism/safety on relative paths.
            # Absolute paths are only allowed when workspace is provided (runtime will validate).
            if self.workspace is None or not str(self.workspace).strip():
                raise ValueError("workspace is required when audio is a file path")
        return self

    class Config:
        extra = "forbid"

