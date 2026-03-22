"""
Image generation request / response types.
"""

import base64
from io import BytesIO
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="正向提示词")
    negative_prompt: Optional[str] = Field(default=None, description="负向提示词")
    width: Optional[int] = Field(default=None, ge=64, le=4096)
    height: Optional[int] = Field(default=None, ge=64, le=4096)
    num_inference_steps: Optional[int] = Field(default=None, ge=1, le=200)
    guidance_scale: Optional[float] = Field(default=None, ge=0, le=50)
    seed: Optional[int] = Field(default=None, ge=0)
    image_format: str = Field(default="PNG", description="输出图像格式")
    progress_callback: Optional[Any] = Field(default=None, exclude=True)

    model_config = {
        "arbitrary_types_allowed": True,
    }


class ImageGenerationResponse(BaseModel):
    model: str
    mime_type: str = "image/png"
    width: int
    height: int
    seed: Optional[int] = None
    latency_ms: Optional[int] = None
    image_base64: str
    output_path: Optional[str] = None
    download_url: Optional[str] = None
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def from_pil_image(
        *,
        model: str,
        image: Any,
        seed: Optional[int],
        latency_ms: Optional[int],
        image_format: str = "PNG",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ImageGenerationResponse":
        buffer = BytesIO()
        fmt = (image_format or "PNG").upper()
        image.save(buffer, format=fmt)
        mime_type = f"image/{fmt.lower()}"
        return ImageGenerationResponse(
            model=model,
            mime_type=mime_type,
            width=int(getattr(image, "width", 0) or 0),
            height=int(getattr(image, "height", 0) or 0),
            seed=seed,
            latency_ms=latency_ms,
            image_base64=base64.b64encode(buffer.getvalue()).decode("utf-8"),
            metadata=metadata or {},
        )


class ImageGenerationJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImageGenerationJobResponse(BaseModel):
    job_id: str
    status: ImageGenerationJobStatus
    model: str
    prompt: str
    phase: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    queue_position: Optional[int] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    progress: Optional[float] = None
    result: Optional[ImageGenerationResponse] = None


class ImageGenerationJobListResponse(BaseModel):
    items: list[ImageGenerationJobResponse]
    total: int
    limit: int
    offset: int
    has_next: bool


class ImageGenerationWarmupResponse(BaseModel):
    warmup_id: str
    model: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    elapsed_ms: Optional[int] = None
    output_path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    error: Optional[str] = None
