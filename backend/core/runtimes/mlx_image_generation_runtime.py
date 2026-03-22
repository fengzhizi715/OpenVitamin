"""
MLX + MFLUX local image generation runtime.

Current target:
- image_generation + mlx + qwen-image
"""

import importlib
import gc
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import anyio

from log import logger
from core.runtimes.image_generation_runtime import ImageGenerationRuntime
from core.runtimes.image_generation_types import ImageGenerationRequest, ImageGenerationResponse


def _parse_quantization_bits(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    text = str(value).lower().strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


class _CancelGenerationCallback:
    def __init__(self, cancel_event: threading.Event, stop_exc_cls: Any, progress_callback: Any = None):
        self._cancel_event = cancel_event
        self._stop_exc_cls = stop_exc_cls
        self._progress_callback = progress_callback

    def call_in_loop(self, t, seed, prompt, latents, config, time_steps):
        if self._cancel_event.is_set():
            raise self._stop_exc_cls(f"Image generation cancelled at step {t + 1}/{config.num_inference_steps}")
        if self._progress_callback is not None:
            try:
                anyio.from_thread.run(self._progress_callback, int(t + 1), int(config.num_inference_steps))
            except Exception:
                pass


class MLXImageGenerationRuntime(ImageGenerationRuntime):
    def __init__(self, model_id: str, model_dir: Path, metadata: Optional[Dict[str, Any]] = None):
        self._model_id = model_id
        self._model_dir = Path(model_dir)
        self._metadata = metadata or {}
        self._model = None
        self._pipeline = str(self._metadata.get("pipeline") or "").lower().strip()
        self._quantize = _parse_quantization_bits(self._metadata.get("quantization"))
        self._qwen_image_cls = None
        self._model_config_cls = None
        self._generation_lock = threading.Lock()
        self._cancel_event: Optional[threading.Event] = None

    @property
    def model_info(self) -> Dict[str, Any]:
        return {
            "model_id": self._model_id,
            "runtime": "mlx",
            "pipeline": self._pipeline,
            "quantize": self._quantize,
        }

    def _load_sync(self) -> bool:
        if self._model is not None:
            return True
        if self._pipeline != "qwen-image":
            raise ValueError(
                f"Unsupported MLX image pipeline '{self._pipeline}' for model {self._model_id}"
            )
        if not self._model_dir.is_dir():
            raise ValueError(f"MLX image generation model dir not found: {self._model_dir}")

        try:
            model_config_mod = importlib.import_module("mflux.models.common.config")
            qwen_mod = importlib.import_module("mflux.models.qwen.variants.txt2img.qwen_image")
        except ImportError as e:
            raise ImportError(
                "mflux is not installed. Install it with: pip install mflux"
            ) from e

        model_config_cls = getattr(model_config_mod, "ModelConfig", None)
        qwen_image_cls = getattr(qwen_mod, "QwenImage", None)
        if model_config_cls is None or qwen_image_cls is None:
            raise RuntimeError("mflux Qwen Image runtime classes not found")

        logger.info(
            "[MLXImageGenerationRuntime] load_start model=%s pipeline=%s model_dir=%s quantize=%s",
            self._model_id,
            self._pipeline,
            self._model_dir,
            self._quantize,
        )
        load_started_at = time.perf_counter()
        self._model_config_cls = model_config_cls
        self._qwen_image_cls = qwen_image_cls
        self._model = qwen_image_cls(
            quantize=self._quantize,
            model_path=str(self._model_dir),
            model_config=model_config_cls.qwen_image(),
        )
        logger.info(
            "[MLXImageGenerationRuntime] load_done model=%s latency_ms=%s",
            self._model_id,
            int((time.perf_counter() - load_started_at) * 1000),
        )
        return True

    async def load(self) -> bool:
        return await anyio.to_thread.run_sync(self._load_sync)

    def _unload_sync(self) -> bool:
        if self._model is None:
            return False
        model = self._model
        self._model = None
        self._qwen_image_cls = None
        self._model_config_cls = None
        self._cancel_event = None
        try:
            del model
        except Exception:
            pass
        gc.collect()
        try:
            mlx_core = importlib.import_module("mlx.core")
            clear_cache = getattr(mlx_core, "clear_cache", None)
            if callable(clear_cache):
                clear_cache()
            metal = getattr(mlx_core, "metal", None)
            if metal is not None:
                metal_clear_cache = getattr(metal, "clear_cache", None)
                if callable(metal_clear_cache):
                    metal_clear_cache()
        except Exception:
            # Best-effort cleanup only; runtime unload should not fail because
            # cache cleanup support differs by MLX version/platform.
            pass
        return True

    async def unload(self) -> bool:
        return await anyio.to_thread.run_sync(self._unload_sync)

    async def is_loaded(self) -> bool:
        return self._model is not None

    def _generate_sync(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        with self._generation_lock:
            if self._model is None:
                self._load_sync()

            width = req.width or int(self._metadata.get("default_width") or 1024)
            height = req.height or int(self._metadata.get("default_height") or 1024)
            steps = req.num_inference_steps or int(self._metadata.get("default_num_inference_steps") or 28)
            guidance = (
                req.guidance_scale
                if req.guidance_scale is not None
                else float(self._metadata.get("default_guidance_scale") or 4.0)
            )
            seed = req.seed if req.seed is not None else int(time.time() * 1000) % (2**31 - 1)
            scheduler = str(self._metadata.get("scheduler") or "linear")
            negative_prompt_supported = bool(self._metadata.get("negative_prompt_supported", True))

            logger.info(
                "[MLXImageGenerationRuntime] generate_start model=%s width=%s height=%s steps=%s guidance=%s seed=%s scheduler=%s",
                self._model_id,
                width,
                height,
                steps,
                guidance,
                seed,
                scheduler,
            )
            self._cancel_event = threading.Event()

            cancel_callback = None
            start = time.perf_counter()
            try:
                stop_exc_cls = importlib.import_module("mflux.utils.exceptions").StopImageGenerationException
                cancel_callback = _CancelGenerationCallback(
                    self._cancel_event,
                    stop_exc_cls,
                    progress_callback=req.progress_callback,
                )
                self._model.callbacks.register(cancel_callback)

                logger.info("[MLXImageGenerationRuntime] phase=model_generate_enter model=%s", self._model_id)
                generated = self._model.generate_image(
                    seed=seed,
                    prompt=req.prompt,
                    negative_prompt=req.negative_prompt if negative_prompt_supported else None,
                    num_inference_steps=steps,
                    width=width,
                    height=height,
                    guidance=guidance,
                    scheduler=scheduler,
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                logger.info(
                    "[MLXImageGenerationRuntime] phase=model_generate_done model=%s latency_ms=%s",
                    self._model_id,
                    latency_ms,
                )
                logger.info(
                    "[MLXImageGenerationRuntime] encode_response_start model=%s format=%s",
                    self._model_id,
                    req.image_format,
                )
                response = ImageGenerationResponse.from_pil_image(
                    model=self._model_id,
                    image=generated.image,
                    seed=seed,
                    latency_ms=latency_ms,
                    image_format=req.image_format,
                    metadata={
                        "pipeline": self._pipeline,
                        "scheduler": scheduler,
                        "num_inference_steps": steps,
                        "guidance_scale": guidance,
                        "quantization": self._quantize,
                    },
                )
                logger.info(
                    "[MLXImageGenerationRuntime] generate_done model=%s latency_ms=%s width=%s height=%s",
                    self._model_id,
                    latency_ms,
                    width,
                    height,
                )
                return response
            finally:
                if cancel_callback is not None:
                    callbacks = getattr(self._model, "callbacks", None)
                    if callbacks and cancel_callback in callbacks.in_loop:
                        callbacks.in_loop.remove(cancel_callback)
                self._cancel_event = None

    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        return await anyio.to_thread.run_sync(self._generate_sync, req)

    async def cancel(self) -> bool:
        if self._cancel_event is None:
            return False
        self._cancel_event.set()
        logger.info("[MLXImageGenerationRuntime] cancel_requested model=%s", self._model_id)
        return True
