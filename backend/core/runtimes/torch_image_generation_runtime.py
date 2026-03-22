"""
Torch-based local image generation runtime.

Current status:
- legacy compatibility path for image_generation + torch manifests
- new Diffusers-native manifests should prefer DiffusersImageGenerationRuntime

Implementation note:
- This runtime still uses diffusers AutoPipelineForText2Image with trust_remote_code.
- It is kept for backward compatibility with earlier local image-generation manifests.
"""

import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import anyio

from log import logger
from core.runtimes.image_generation_runtime import ImageGenerationRuntime
from core.runtimes.image_generation_types import ImageGenerationRequest, ImageGenerationResponse

try:
    import torch
except ImportError:
    torch = None

try:
    from diffusers import AutoPipelineForText2Image
except ImportError:
    AutoPipelineForText2Image = None


def _resolve_device(device: str) -> str:
    if not torch:
        return "cpu"
    if (device or "auto").lower() != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _resolve_dtype(dtype_name: Optional[str]) -> Any:
    if not torch:
        return None
    mapping = {
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    return mapping.get((dtype_name or "").lower(), torch.float16)


class TorchImageGenerationRuntime(ImageGenerationRuntime):
    def __init__(self, model_id: str, model_dir: Path, metadata: Optional[Dict[str, Any]] = None):
        self._model_id = model_id
        self._model_dir = Path(model_dir)
        self._metadata = metadata or {}
        self._pipeline = None
        self._device = _resolve_device(str(self._metadata.get("device") or "auto"))
        self._dtype = _resolve_dtype(self._metadata.get("torch_dtype"))

    @property
    def model_info(self) -> Dict[str, Any]:
        return {
            "model_id": self._model_id,
            "runtime": "torch",
            "pipeline": self._metadata.get("pipeline"),
            "device": self._device,
        }

    def _load_sync(self) -> bool:
        if self._pipeline is not None:
            return True
        if AutoPipelineForText2Image is None:
            raise ImportError(
                "diffusers is not installed. Install it with: pip install diffusers"
            )
        if torch is None:
            raise ImportError("torch is not installed.")
        if not self._model_dir.is_dir():
            raise ValueError(f"Image generation model dir not found: {self._model_dir}")

        trust_remote_code = bool(
            self._metadata.get("allow_remote_code", True)
            or self._metadata.get("allow_remote", False)
        )
        kwargs: Dict[str, Any] = {
            "trust_remote_code": trust_remote_code,
        }
        if self._dtype is not None:
            kwargs["torch_dtype"] = self._dtype
        variant = self._metadata.get("variant")
        if variant:
            kwargs["variant"] = variant

        logger.info("[TorchImageGenerationRuntime] Loading model from %s", self._model_dir)
        pipeline = AutoPipelineForText2Image.from_pretrained(str(self._model_dir), **kwargs)
        if hasattr(pipeline, "set_progress_bar_config"):
            pipeline.set_progress_bar_config(disable=True)
        pipeline = pipeline.to(self._device)
        self._pipeline = pipeline
        return True

    async def load(self) -> bool:
        return await anyio.to_thread.run_sync(self._load_sync)

    def _unload_sync(self) -> bool:
        if self._pipeline is None:
            return False
        self._pipeline = None
        if torch is not None:
            try:
                if self._device == "cuda":
                    torch.cuda.empty_cache()
                elif self._device == "mps":
                    torch.mps.empty_cache()
            except Exception:
                pass
        return True

    async def unload(self) -> bool:
        return await anyio.to_thread.run_sync(self._unload_sync)

    async def is_loaded(self) -> bool:
        return self._pipeline is not None

    def _get_dimensions(self, req: ImageGenerationRequest) -> Tuple[int, int]:
        width = req.width or int(self._metadata.get("default_width") or 1024)
        height = req.height or int(self._metadata.get("default_height") or 1024)
        max_width = int(self._metadata.get("max_width") or width)
        max_height = int(self._metadata.get("max_height") or height)
        return min(width, max_width), min(height, max_height)

    def _build_generator(self, seed: Optional[int]) -> Tuple[Optional[Any], Optional[int]]:
        if seed is None or torch is None:
            return None, seed
        generator_device = "cpu" if self._device == "mps" else self._device
        generator = torch.Generator(device=generator_device)
        generator.manual_seed(seed)
        return generator, seed

    def _generate_sync(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        if self._pipeline is None:
            self._load_sync()

        width, height = self._get_dimensions(req)
        steps = req.num_inference_steps or int(self._metadata.get("default_num_inference_steps") or 28)
        guidance = (
            req.guidance_scale
            if req.guidance_scale is not None
            else float(self._metadata.get("default_guidance_scale") or 4.0)
        )
        negative_prompt_supported = bool(self._metadata.get("negative_prompt_supported", True))
        generator, used_seed = self._build_generator(req.seed)

        kwargs: Dict[str, Any] = {
            "prompt": req.prompt,
            "width": width,
            "height": height,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
        }
        if generator is not None:
            kwargs["generator"] = generator
        if negative_prompt_supported and req.negative_prompt:
            kwargs["negative_prompt"] = req.negative_prompt

        start = time.perf_counter()
        result = self._pipeline(**kwargs)
        latency_ms = int((time.perf_counter() - start) * 1000)
        if not getattr(result, "images", None):
            raise RuntimeError("Image generation pipeline returned no images")
        image = result.images[0]
        return ImageGenerationResponse.from_pil_image(
            model=self._model_id,
            image=image,
            seed=used_seed,
            latency_ms=latency_ms,
            image_format=req.image_format,
            metadata={
                "pipeline": self._metadata.get("pipeline"),
                "device": self._device,
                "num_inference_steps": steps,
                "guidance_scale": guidance,
            },
        )

    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        return await anyio.to_thread.run_sync(self._generate_sync, req)
