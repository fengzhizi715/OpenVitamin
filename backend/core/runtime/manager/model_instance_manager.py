"""
V2.9 Runtime Stabilization Layer - Model instance manager.

Unified model instance management: lazy load, cache, unload.
Thread/async safe: one load per model_id via asyncio.Lock.
"""
import asyncio
import threading
from typing import Dict, List, Any, Optional

from log import log_structured
from core.models.registry import get_model_registry
from core.models.descriptor import ModelDescriptor
from core.runtimes.factory import get_runtime_factory


class ModelInstanceManager:
    """
    Unified model instance management.
    - Lazy load: first inference loads the model.
    - Cache: model_id → runtime instance (via factory's existing caches).
    - Single load per model_id: asyncio.Lock prevents concurrent load of same model.
    """

    def __init__(self):
        self._factory = get_runtime_factory()
        self._registry = get_model_registry()
        self._load_locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()
        self._logged_loaded: set = set()  # model_ids we already logged model_loaded for

    async def _get_load_lock(self, model_id: str) -> asyncio.Lock:
        async with self._locks_lock:
            if model_id not in self._load_locks:
                self._load_locks[model_id] = asyncio.Lock()
            return self._load_locks[model_id]

    def _get_descriptor(self, model_id: str) -> ModelDescriptor:
        desc = self._registry.get_model(model_id)
        if not desc:
            raise ValueError(f"Model not found: {model_id}")
        return desc

    def _get_or_create_runtime(self, descriptor: ModelDescriptor) -> Any:
        """
        Get or create runtime for descriptor. Uses factory's existing caches.
        Caller must hold the per-model load lock.
        """
        model_type = (getattr(descriptor, "model_type", "") or "llm").lower()
        model_id = descriptor.id
        runtime_type = (getattr(descriptor, "runtime", "") or "").lower()

        if model_type == "embedding":
            return self._factory.create_runtime(descriptor)
        if model_type in ("vlm", "vision", "multimodal"):
            # For torch-based VLMs, use TorchModelRuntime which provides chat/stream_chat
            if runtime_type == "torch":
                return self._factory.get_runtime("torch")
            # For other VLM runtimes (llama.cpp, mlx), use the VLM runtime directly
            return self._factory.create_vlm_runtime(descriptor)
        if model_type == "asr":
            return self._factory.create_asr_runtime(descriptor)
        if model_type == "perception":
            return self._factory.create_perception_runtime(descriptor)
        if model_type == "image_generation":
            return self._factory.create_image_generation_runtime(descriptor)
        # LLM and default
        return self._factory.get_runtime(descriptor.runtime)

    async def _ensure_loaded(self, runtime: Any, descriptor: ModelDescriptor) -> bool:
        """
        Best-effort "ensure loaded" under the per-model load lock.

        Design goal:
        - Avoid concurrent weight loads for the same model_id.
        - Keep behavior deterministic: if runtime can't report load state, we don't guess.
        """
        is_loaded_fn = getattr(runtime, "is_loaded", None)
        load_fn = getattr(runtime, "load", None)

        # If runtime can't tell load state, don't claim it's loaded.
        if not callable(is_loaded_fn):
            return False

        try:
            try:
                loaded = is_loaded_fn(descriptor)
            except TypeError:
                loaded = is_loaded_fn()
            if hasattr(loaded, "__await__"):
                loaded = await loaded
            loaded = bool(loaded)
        except Exception:
            return False

        if loaded:
            return True

        if not callable(load_fn):
            return False

        try:
            try:
                res = load_fn(descriptor)
            except TypeError:
                res = load_fn()
            if hasattr(res, "__await__"):
                res = await res
            return bool(res)
        except Exception:
            return False

    async def get_instance(self, model_id: str) -> Any:
        """
        Get runtime instance for model_id. Loads on first use (lazy).
        Same model_id returns same instance (cached in factory).
        """
        descriptor = self._get_descriptor(model_id)
        lock = await self._get_load_lock(model_id)
        async with lock:
            try:
                runtime = self._get_or_create_runtime(descriptor)
                loaded = await self._ensure_loaded(runtime, descriptor)
                if model_id not in self._logged_loaded:
                    self._logged_loaded.add(model_id)
                    log_structured(
                        "RuntimeStabilization",
                        "model_loaded",
                        model_id=model_id,
                        runtime=getattr(descriptor, "runtime", ""),
                        loaded=loaded,
                    )
                return runtime
            except Exception as e:
                log_structured(
                    "RuntimeStabilization",
                    "inference_error",
                    level="error",
                    model_id=model_id,
                    error=str(e)[:500],
                )
                raise

    async def load_instance(self, model_id: str) -> Any:
        """
        Explicitly load and return the runtime instance.
        Same as get_instance (lazy load is the default).
        """
        return await self.get_instance(model_id)

    async def unload_instance(self, model_id: str) -> bool:
        """Unload model and clear from factory caches."""
        try:
            ok = await self._factory.unload_model(model_id)
            if ok:
                self._logged_loaded.discard(model_id)
                log_structured(
                    "RuntimeStabilization",
                    "model_unloaded",
                    model_id=model_id,
                )
            return ok
        except Exception as e:
            log_structured(
                "RuntimeStabilization",
                "inference_error",
                level="error",
                model_id=model_id,
                error=str(e)[:500],
            )
            return False

    def list_instances(self) -> List[str]:
        """Return list of model_ids that have loaded runtimes (best-effort)."""
        return list(self._factory._runtime_ids())


# Singleton (thread-safe for first access)
_instance_manager: Optional[ModelInstanceManager] = None
_instance_manager_lock = threading.Lock()


def get_model_instance_manager() -> ModelInstanceManager:
    global _instance_manager
    with _instance_manager_lock:
        if _instance_manager is None:
            _instance_manager = ModelInstanceManager()
        return _instance_manager
