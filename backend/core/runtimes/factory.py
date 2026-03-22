import asyncio
import time
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, Union
from core.runtimes.base import ModelRuntime, EmbeddingRuntime
from core.runtimes.ollama import OllamaRuntime
from core.runtimes.openai import OpenAIRuntime
from core.runtimes.llama_cpp import LlamaCppRuntime
from core.runtimes.mlx_runtime import MLXRuntime
from core.runtimes.torch_model_runtime import TorchModelRuntime
from core.runtimes.embedding_onnx import OnnxEmbeddingRuntime
from core.runtimes.vlm_runtime import VLMRuntime
from core.runtimes.image_generation_runtime import ImageGenerationRuntime
from core.models.descriptor import ModelDescriptor
from config.settings import settings
from log import logger

class RuntimeFactory:
    """
    运行时工厂
    根据 ModelDescriptor 的 runtime 字段和 model_type 提供对应的运行时实例
    """
    def __init__(self):
        self._runtimes: Dict[str, ModelRuntime] = {
            "ollama": OllamaRuntime(),
            "openai": OpenAIRuntime(),
            "gemini": OpenAIRuntime(), # Gemini 兼容 OpenAI 格式
            "deepseek": OpenAIRuntime(),
            "kimi": OpenAIRuntime(),
            "lmstudio": OpenAIRuntime(), # LM Studio 也是 OpenAI 兼容
            "llama.cpp": LlamaCppRuntime(),
            "mlx": MLXRuntime(),
            "torch": TorchModelRuntime(), # Torch VLM (InternVL, Qwen-VL)
        }
        # Embedding runtimes are created on-demand based on model metadata
        self._embedding_runtimes: Dict[str, EmbeddingRuntime] = {}

        # VLM runtimes: registry + cache (process-wide via get_runtime_factory singleton)
        self._vlm_builders: Dict[str, Callable[[ModelDescriptor], VLMRuntime]] = {}
        self._vlm_runtimes: Dict[str, VLMRuntime] = {}
        self._register_builtin_vlm_builders()

        # ASR runtimes: cache by model id
        self._asr_runtimes: Dict[str, Any] = {}

        # Perception runtimes: cache by model id (YOLO 等)
        self._perception_runtimes: Dict[str, Any] = {}
        # Image generation runtimes: cache by model id
        self._image_generation_runtimes: Dict[str, ImageGenerationRuntime] = {}
        self._image_generation_builders: Dict[str, Callable[[ModelDescriptor], ImageGenerationRuntime]] = {}
        self._register_builtin_image_generation_builders()
        # Runtime usage bookkeeping（通用、与具体 Agent 无关）
        self._runtime_last_used: Dict[str, float] = {}
        self._runtime_in_use: Dict[str, int] = {}
        # Track model_ids that have entered usage bookkeeping so we can consider
        # unloading LLM runtimes (llama.cpp/torch LLM/etc.) in the same policy.
        self._known_model_ids: Set[str] = set()
        self._usage_lock = threading.Lock()
        self._gc_lock = asyncio.Lock()
        self._last_auto_release_at: float = 0.0

    def _touch_runtime(self, model_id: str) -> None:
        if model_id:
            with self._usage_lock:
                self._runtime_last_used[model_id] = time.time()
                self._known_model_ids.add(model_id)

    def _inc_runtime_use(self, model_id: str) -> None:
        if not model_id:
            return
        with self._usage_lock:
            self._runtime_in_use[model_id] = self._runtime_in_use.get(model_id, 0) + 1
            self._runtime_last_used[model_id] = time.time()
            self._known_model_ids.add(model_id)

    def _dec_runtime_use(self, model_id: str) -> None:
        if not model_id:
            return
        with self._usage_lock:
            cur = self._runtime_in_use.get(model_id, 0) - 1
            if cur <= 0:
                self._runtime_in_use.pop(model_id, None)
            else:
                self._runtime_in_use[model_id] = cur
            self._runtime_last_used[model_id] = time.time()

    def _snapshot_usage(self) -> tuple[Dict[str, float], Dict[str, int]]:
        with self._usage_lock:
            return dict(self._runtime_last_used), dict(self._runtime_in_use)

    def _clear_usage_record(self, model_id: str) -> None:
        if not model_id:
            return
        with self._usage_lock:
            self._runtime_last_used.pop(model_id, None)
            self._runtime_in_use.pop(model_id, None)
            self._known_model_ids.discard(model_id)

    @asynccontextmanager
    async def model_usage(self, model_id: str):
        """
        标记模型运行时处于活跃使用中（用于资源回收时跳过 in-use 模型）。
        """
        self._inc_runtime_use(model_id)
        try:
            yield
        finally:
            self._dec_runtime_use(model_id)

    def _runtime_ids(self) -> Set[str]:
        ids: Set[str] = set()
        # Cached heavy runtimes
        ids.update(self._vlm_runtimes.keys())
        ids.update(self._asr_runtimes.keys())
        ids.update(self._perception_runtimes.keys())
        ids.update(self._image_generation_runtimes.keys())
        # Plus any model_ids that have entered usage bookkeeping (LLM, etc.)
        with self._usage_lock:
            ids.update(self._known_model_ids)
        return ids

    @staticmethod
    def _normalize_cache_bucket(model_type: str | None) -> str:
        normalized = (model_type or "").lower()
        if normalized in {"vision", "multimodal"}:
            return "vlm"
        return normalized or "unknown"

    def _is_mps_pressure_high(self) -> bool:
        try:
            import torch
            if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
                return False
            current = float(torch.mps.current_allocated_memory())
            rec_fn = getattr(torch.mps, "recommended_max_memory", None)
            recommended = float(rec_fn()) if callable(rec_fn) else 0.0
            if recommended <= 0:
                return False
            ratio = current / recommended
            return ratio >= float(getattr(settings, "runtime_mps_pressure_threshold", 0.85))
        except Exception:
            return False

    def _is_ram_pressure_high(self) -> bool:
        """
        Generic system memory pressure heuristic.
        This helps on macOS where llama.cpp allocations are not visible to torch.mps.
        """
        try:
            import psutil
            vm = psutil.virtual_memory()
            # vm.percent is [0..100]
            threshold = float(getattr(settings, "runtime_ram_pressure_threshold", 85.0))
            return float(vm.percent) >= threshold
        except Exception:
            return False

    async def _is_model_loaded(self, model_id: str) -> bool:
        """
        Best-effort check whether a model is currently loaded into memory.
        Keeps auto-release decisions predictable and avoids repeated unload attempts
        for models that were never loaded or already released.
        """
        from core.models.registry import get_model_registry

        reg = get_model_registry()
        desc = reg.get_model(model_id)
        if not desc:
            return False

        model_type = (getattr(desc, "model_type", "") or "").lower()
        if model_type in {"vlm", "vision", "multimodal"}:
            return model_id in self._vlm_runtimes
        if model_type == "asr":
            return model_id in self._asr_runtimes
        if model_type == "perception":
            return model_id in self._perception_runtimes
        if model_type == "image_generation":
            return model_id in self._image_generation_runtimes
        if model_type == "embedding":
            return model_id in self._embedding_runtimes

        runtime = self.get_runtime(desc.runtime)
        is_loaded_fn = getattr(runtime, "is_loaded", None)
        if callable(is_loaded_fn):
            try:
                res = is_loaded_fn(desc)
                if hasattr(res, "__await__"):
                    res = await res
                return bool(res)
            except Exception:
                # If runtime cannot report load state, fall back to attempting unload.
                return True
        # Unknown runtime state: assume loaded so unload_model can attempt cleanup.
        return True

    async def auto_release_unused_local_runtimes(
        self,
        keep_model_ids: Optional[Set[str]] = None,
        reason: str = "",
    ) -> Dict[str, int]:
        """
        通用自动回收策略（与业务无关）：
        - 超过缓存上限时回收最久未使用模型
        - MPS 高压力时积极回收
        - 跳过当前 keep 集合与 in-use 模型
        """
        from core.system.runtime_settings import (
            get_runtime_auto_release_enabled,
            get_runtime_release_idle_ttl_seconds,
            get_runtime_max_cached_local_runtimes,
            get_runtime_release_min_interval_seconds,
        )
        if not get_runtime_auto_release_enabled():
            logger.debug("[RuntimeFactory] auto_release disabled reason=%s", reason or "n/a")
            return {"released": 0}

        keep = {m for m in (keep_model_ids or set()) if m}
        now = time.time()
        ttl = get_runtime_release_idle_ttl_seconds()
        min_interval = get_runtime_release_min_interval_seconds()
        pressure_high = self._is_mps_pressure_high() or self._is_ram_pressure_high()

        if (not pressure_high) and (now - self._last_auto_release_at < min_interval):
            logger.debug(
                "[RuntimeFactory] auto_release skipped(min_interval) reason=%s keep=%s since_last=%.2fs min_interval=%ss pressure_high=%s",
                reason or "n/a",
                list(keep),
                (now - self._last_auto_release_at),
                min_interval,
                pressure_high,
            )
            return {"released": 0}

        async with self._gc_lock:
            # 双重检查，避免并发下重复回收抖动
            now = time.time()
            if (not pressure_high) and (now - self._last_auto_release_at < min_interval):
                logger.debug(
                    "[RuntimeFactory] auto_release skipped(min_interval,locked) reason=%s keep=%s since_last=%.2fs min_interval=%ss pressure_high=%s",
                    reason or "n/a",
                    list(keep),
                    (now - self._last_auto_release_at),
                    min_interval,
                    pressure_high,
                )
                return {"released": 0}

            from core.models.registry import get_model_registry

            last_used, in_use = self._snapshot_usage()
            candidates = []
            reg = get_model_registry()
            keep_counts: Dict[str, int] = {}
            for model_id in keep:
                desc = reg.get_model(model_id)
                if not desc or getattr(desc, "provider", None) != "local":
                    continue
                bucket = self._normalize_cache_bucket(getattr(desc, "model_type", ""))
                keep_counts[bucket] = keep_counts.get(bucket, 0) + 1
            for model_id in self._runtime_ids():
                if model_id in keep:
                    continue
                if in_use.get(model_id, 0) > 0:
                    continue
                desc = reg.get_model(model_id)
                if not desc:
                    # Stale record
                    self._clear_usage_record(model_id)
                    continue
                if getattr(desc, "provider", None) != "local":
                    # Only auto-release local models (remote providers are stateless here)
                    continue

                # Avoid repeated unload attempts on models that are not actually loaded.
                loaded = await self._is_model_loaded(model_id)
                if not loaded:
                    self._clear_usage_record(model_id)
                    continue

                last = last_used.get(model_id, 0.0)
                idle = now - last if last > 0 else ttl + 1
                bucket = self._normalize_cache_bucket(getattr(desc, "model_type", ""))
                candidates.append((model_id, idle, last, bucket))

            if not candidates:
                logger.debug(
                    "[RuntimeFactory] auto_release no_candidates reason=%s keep=%s pressure_high=%s",
                    reason or "n/a",
                    list(keep),
                    pressure_high,
                )
                return {"released": 0}

            # 排序：最久未使用优先
            candidates_by_bucket: Dict[str, list[tuple[str, float, float, str]]] = {}
            for item in candidates:
                candidates_by_bucket.setdefault(item[3], []).append(item)
            for items in candidates_by_bucket.values():
                items.sort(key=lambda x: x[2] if x[2] > 0 else -1)

            to_release: list[str] = []
            bucket_limits: Dict[str, int] = {}
            bucket_candidate_counts: Dict[str, int] = {}
            for bucket, items in candidates_by_bucket.items():
                limit = get_runtime_max_cached_local_runtimes(bucket)
                bucket_limits[bucket] = limit
                bucket_candidate_counts[bucket] = len(items)
                overflow = max(0, len(items) + keep_counts.get(bucket, 0) - limit)
                selected_in_bucket = 0
                for model_id, idle, _, _ in items:
                    if pressure_high:
                        # 高压力：每个桶至少释放 overflow+1 或空闲超过 ttl 的模型
                        if idle >= ttl or selected_in_bucket < overflow + 1:
                            to_release.append(model_id)
                            selected_in_bucket += 1
                    else:
                        if overflow <= 0:
                            break
                        if idle >= ttl or overflow > 0:
                            to_release.append(model_id)
                            selected_in_bucket += 1
                            overflow -= 1

            released = 0
            logger.debug(
                "[RuntimeFactory] auto_release select reason=%s keep=%s pressure_high=%s ttl=%ss bucket_limits=%s keep_counts=%s candidates=%s to_release=%s",
                reason or "n/a",
                list(keep),
                pressure_high,
                ttl,
                bucket_limits,
                keep_counts,
                bucket_candidate_counts,
                list(to_release),
            )
            for model_id in to_release:
                try:
                    ok = await self.unload_model(model_id)
                    if ok:
                        released += 1
                        self._clear_usage_record(model_id)
                except Exception:
                    continue

            self._last_auto_release_at = now
            if released > 0:
                logger.info(
                    "[RuntimeFactory] auto_release released=%s reason=%s keep=%s pressure_high=%s",
                    released,
                    reason or "n/a",
                    list(keep),
                    pressure_high,
                )
            else:
                logger.debug(
                    "[RuntimeFactory] auto_release released=0 reason=%s keep=%s pressure_high=%s",
                    reason or "n/a",
                    list(keep),
                    pressure_high,
                )
            return {"released": released}

    def _register_builtin_vlm_builders(self) -> None:
        """
        Register built-in VLM runtime builders.

        Design:
        - Keep VLM backend selection explicit and extensible.
        - Adding a second VLM backend should be a small, localized change (register a builder).
        """
        # llama.cpp VLM (GGUF with vision support)
        self.register_vlm_builder("llama.cpp", self._build_llama_cpp_vlm)
        # Torch VLM (PyTorch + Transformers: InternVL, Qwen-VL)
        self.register_vlm_builder("torch", self._build_torch_vlm)

    def _register_builtin_image_generation_builders(self) -> None:
        self.register_image_generation_builder("diffusers", self._build_diffusers_image_generation)
        self.register_image_generation_builder("torch", self._build_torch_image_generation)
        self.register_image_generation_builder("mlx", self._build_mlx_image_generation)

    def register_vlm_builder(self, runtime_type: str, builder: Callable[[ModelDescriptor], VLMRuntime]) -> None:
        self._vlm_builders[runtime_type] = builder

    def register_image_generation_builder(
        self,
        runtime_type: str,
        builder: Callable[[ModelDescriptor], ImageGenerationRuntime],
    ) -> None:
        self._image_generation_builders[runtime_type] = builder

    def _build_llama_cpp_vlm(self, model: ModelDescriptor) -> VLMRuntime:
        from core.runtimes.llama_vlm_runtime import LlamaCppVLMRuntime

        metadata = model.metadata or {}
        model_path = metadata.get("model_path") or metadata.get("path") or metadata.get("gguf_path")
        if not model_path:
            raise ValueError(
                f"VLM model '{model.id}' missing required metadata: model_path/gguf_path"
            )
        model_path = str(model_path)

        # VLM-specific (best-effort, backend dependent)
        mmproj_raw = (
            metadata.get("mmproj_path")
            or metadata.get("clip_model_path")
            or metadata.get("vision_proj_path")
            or metadata.get("mmproj")
        )
        mmproj_path = self._resolve_relative_path(mmproj_raw, model_path) if mmproj_raw else None
        vlm_family = metadata.get("vlm_family") or metadata.get("family")

        n_ctx = metadata.get("context_length", model.context_length)
        n_gpu_layers = metadata.get("n_gpu_layers", 0)
        verbose = bool(metadata.get("verbose", False))

        return LlamaCppVLMRuntime(
            model_path=model_path,
            mmproj_path=mmproj_path,
            vlm_family=vlm_family,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose,
        )

    def _build_torch_vlm(self, model: ModelDescriptor) -> VLMRuntime:
        from core.runtimes.torch import TorchVLMRuntime

        metadata = model.metadata or {}
        # model_path/model_dir 可能是相对路径（如 "."），优先基于 metadata.path（主权重绝对路径）解析
        raw_model_dir = metadata.get("model_dir")
        raw_model_path = metadata.get("model_path")
        raw_main_path = metadata.get("path")

        raw_path = raw_model_dir or raw_model_path or raw_main_path
        if not raw_path:
            raise ValueError(
                f"Torch VLM model '{model.id}' missing required metadata: model_path/path/model_dir"
            )

        model_dir = Path(raw_path)
        if not model_dir.is_absolute():
            base = Path(raw_main_path) if raw_main_path else None
            if base and base.is_absolute():
                base_dir = base.parent if base.suffix else base
                model_dir = (base_dir / model_dir).resolve()
            else:
                model_dir = model_dir.resolve()

        if model_dir.suffix in (".gguf", ".bin", ".safetensors"):
            model_dir = model_dir.parent
        if not model_dir.is_dir():
            raise ValueError(f"Torch VLM model dir not found: {model_dir}")

        return TorchVLMRuntime(model_dir=model_dir)

    def _resolve_image_generation_model_dir(self, model: ModelDescriptor) -> Path:
        metadata = model.metadata or {}
        raw_path = metadata.get("model_dir") or metadata.get("model_path") or metadata.get("path")
        if not raw_path:
            raise ValueError(
                f"Image generation model '{model.id}' missing required metadata: model_path/path/model_dir"
            )

        model_dir = Path(raw_path)
        if not model_dir.is_absolute():
            base = Path(metadata.get("path") or raw_path)
            base_dir = base.parent if base.suffix else base
            model_dir = (base_dir / model_dir).resolve()
        if model_dir.suffix in (".gguf", ".bin", ".safetensors", ".pth"):
            model_dir = model_dir.parent
        if not model_dir.is_dir():
            raise ValueError(f"Image generation model dir not found: {model_dir}")
        return model_dir

    def _build_diffusers_image_generation(self, model: ModelDescriptor) -> ImageGenerationRuntime:
        from core.runtimes.diffusers_image_generation_runtime import DiffusersImageGenerationRuntime

        model_dir = self._resolve_image_generation_model_dir(model)
        return DiffusersImageGenerationRuntime(
            model_id=model.id,
            model_dir=model_dir,
            metadata=model.metadata or {},
        )

    def _build_torch_image_generation(self, model: ModelDescriptor) -> ImageGenerationRuntime:
        from core.runtimes.torch_image_generation_runtime import TorchImageGenerationRuntime

        model_dir = self._resolve_image_generation_model_dir(model)

        return TorchImageGenerationRuntime(
            model_id=model.id,
            model_dir=model_dir,
            metadata=model.metadata or {},
        )

    def _build_mlx_image_generation(self, model: ModelDescriptor) -> ImageGenerationRuntime:
        from core.runtimes.mlx_image_generation_runtime import MLXImageGenerationRuntime

        model_dir = self._resolve_image_generation_model_dir(model)

        return MLXImageGenerationRuntime(
            model_id=model.id,
            model_dir=model_dir,
            metadata=model.metadata or {},
        )

    @staticmethod
    def _resolve_relative_path(path_val: str, base_path: str) -> str:
        """将相对路径解析为绝对路径，基准为 base_path 所在目录。"""
        p = Path(path_val)
        if p.is_absolute():
            return path_val
        base = Path(base_path)
        if base.is_file() or (base.exists() and base.suffix):
            base = base.parent
        return str((base / path_val).resolve())

    def get_runtime(self, runtime_type: str) -> ModelRuntime:
        """获取 LLM 运行时（向后兼容）"""
        runtime = self._runtimes.get(runtime_type)
        if not runtime:
            # 默认回退到 OpenAI 兼容，因为它是最通用的
            return self._runtimes["openai"]
        return runtime

    def create_runtime(self, model: ModelDescriptor) -> Union[ModelRuntime, EmbeddingRuntime, ImageGenerationRuntime]:
        """
        根据 ModelDescriptor 创建运行时实例
        
        如果 model_type == "embedding"，创建 EmbeddingRuntime
        否则创建 ModelRuntime
        """
        if model.model_type == "embedding":
            return self._get_embedding_runtime(model)
        if model.model_type == "image_generation":
            return self.create_image_generation_runtime(model)
        else:
            return self.get_runtime(model.runtime)

    def create_vlm_runtime(self, model: ModelDescriptor) -> VLMRuntime:
        """
        根据 ModelDescriptor 创建 VLM 运行时实例

        设计说明：
        - 与 create_runtime 类似，但专门用于 VLM（image+text→text）
        - 将 backend 特定配置聚合到 model.metadata 中，避免 API 层感知 n_ctx 等细节
        """
        runtime_type = model.runtime
        cache_key = model.id

        # Reuse cached instance (important for large VLMs)
        if cache_key in self._vlm_runtimes:
            self._touch_runtime(cache_key)
            return self._vlm_runtimes[cache_key]

        builder = self._vlm_builders.get(runtime_type)
        if not builder:
            raise ValueError(f"Unsupported VLM runtime type for VLM: {runtime_type}")

        rt = builder(model)
        self._vlm_runtimes[cache_key] = rt
        self._touch_runtime(cache_key)
        return rt

    async def unload_vlm_runtime(self, model_id: str) -> bool:
        """Unload a cached VLM runtime by model id."""
        rt = self._vlm_runtimes.pop(model_id, None)
        if not rt:
            return False
        try:
            await rt.unload()
        except Exception:
            pass
        self._clear_usage_record(model_id)
        return True

    async def unload_vlm_runtimes(self) -> int:
        """
        Best-effort unload of cached VLM runtimes (async).
        """
        n = 0
        for rt in list(self._vlm_runtimes.values()):
            try:
                await rt.unload()
                n += 1
            except Exception:
                n += 1
        self._vlm_runtimes.clear()
        return n

    def create_image_generation_runtime(self, model: ModelDescriptor) -> ImageGenerationRuntime:
        runtime_type = model.runtime
        cache_key = model.id

        if cache_key in self._image_generation_runtimes:
            self._touch_runtime(cache_key)
            return self._image_generation_runtimes[cache_key]

        builder = self._image_generation_builders.get(runtime_type)
        if not builder:
            raise ValueError(
                f"Unsupported image generation runtime type for model '{model.id}': {runtime_type}"
            )

        rt = builder(model)
        self._image_generation_runtimes[cache_key] = rt
        self._touch_runtime(cache_key)
        return rt

    async def unload_image_generation_runtime(self, model_id: str) -> bool:
        rt = self._image_generation_runtimes.pop(model_id, None)
        if not rt:
            return False
        try:
            await rt.unload()
        except Exception:
            pass
        self._clear_usage_record(model_id)
        return True

    async def unload_other_image_generation_runtimes(
        self,
        keep_model_ids: Optional[Set[str]] = None,
    ) -> int:
        keep = {m for m in (keep_model_ids or set()) if m}
        released = 0
        for model_id in list(self._image_generation_runtimes.keys()):
            if model_id in keep:
                continue
            if await self.unload_image_generation_runtime(model_id):
                released += 1
        return released

    def is_image_generation_loaded(self, model_id: str) -> bool:
        return model_id in self._image_generation_runtimes

    async def unload_model(self, model_id: str) -> bool:
        """
        Best-effort unload of a model by id.
        Handles VLM/LLM/ASR/Perception/Embedding runtimes.
        """
        from core.models.registry import get_model_registry

        reg = get_model_registry()
        desc = reg.get_model(model_id)
        if not desc:
            return False

        model_type = (getattr(desc, "model_type", "") or "").lower()

        if model_type == "perception":
            return self.unload_perception_runtime(desc.id)
        if model_type == "image_generation":
            return await self.unload_image_generation_runtime(desc.id)

        if model_type == "embedding":
            rt = self._embedding_runtimes.pop(desc.id, None)
            if not rt:
                return False
            close_fn = getattr(rt, "close", None)
            if callable(close_fn):
                close_fn()
            return True

        if model_type == "asr":
            rt = self._asr_runtimes.pop(desc.id, None)
            if not rt:
                return False
            unload_fn = getattr(rt, "unload", None)
            if callable(unload_fn):
                res = unload_fn()
                if hasattr(res, "__await__"):
                    await res
            self._clear_usage_record(desc.id)
            return True

        if model_type in {"vlm", "vision", "multimodal"}:
            return await self.unload_vlm_runtime(desc.id)

        # default: LLM runtime
        runtime = self.get_runtime(desc.runtime)
        unload_fn = getattr(runtime, "unload", None)
        if callable(unload_fn):
            res = unload_fn(desc)
            if hasattr(res, "__await__"):
                return await res
            return bool(res)
        return False

    def create_asr_runtime(self, model: ModelDescriptor) -> Any:
        """
        根据 ModelDescriptor 创建 ASR 运行时实例。
        用于 model_type == "asr" 的模型。
        """
        from core.runtimes.torch import TorchASRRuntime

        cache_key = model.id
        if cache_key in self._asr_runtimes:
            self._touch_runtime(cache_key)
            return self._asr_runtimes[cache_key]

        metadata = model.metadata or {}
        model_dir = metadata.get("model_path") or metadata.get("path") or metadata.get("model_dir")
        if not model_dir:
            raise ValueError(
                f"ASR model '{model.id}' missing required metadata: model_path/path/model_dir"
            )
        model_dir = Path(model_dir)
        if model_dir.suffix in (".gguf", ".bin", ".safetensors", ".pth"):
            model_dir = model_dir.parent
        if not model_dir.is_dir():
            raise ValueError(f"ASR model dir not found: {model_dir}")

        rt = TorchASRRuntime(model_dir=model_dir)
        self._asr_runtimes[cache_key] = rt
        self._touch_runtime(cache_key)
        return rt

    async def unload_asr_runtimes(self) -> int:
        """Best-effort unload of cached ASR runtimes (async)."""
        n = 0
        for model_id, rt in list(self._asr_runtimes.items()):
            try:
                await rt.unload()
                n += 1
            except Exception:
                n += 1
            self._clear_usage_record(model_id)
        self._asr_runtimes.clear()
        return n

    def create_perception_runtime(self, model: ModelDescriptor) -> Any:
        """
        根据 ModelDescriptor 创建 Perception 运行时实例。
        用于 model_type == "perception" 的模型（如 YOLO）。
        """
        from core.runtimes.perception import TorchPerceptionRuntime

        cache_key = model.id
        if cache_key in self._perception_runtimes:
            self._touch_runtime(cache_key)
            return self._perception_runtimes[cache_key]

        metadata = model.metadata or {}
        raw_path = metadata.get("model_path") or metadata.get("path") or metadata.get("model_dir")
        if not raw_path:
            raise ValueError(
                f"Perception model '{model.id}' missing required metadata: model_path/path/model_dir"
            )
        model_path = Path(raw_path)
        # .pt 等感知模型为单文件，保留路径；.gguf 等为目录时取 parent
        if model_path.suffix in (".gguf", ".bin", ".safetensors") and not model_path.is_dir():
            model_path = model_path.parent
        if not model_path.exists():
            raise ValueError(f"Perception model path not found: {model_path}")

        device = metadata.get("device") or "cpu"
        if device and device.lower() == "auto":
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"
            except ImportError:
                device = "cpu"

        model_config = {
            "model_id": model.provider_model_id,
            "runtime": "torch",
            "task": metadata.get("task", "object_detection"),
            "model_path": str(Path(model_path).resolve()),
            "device": device,
            "confidence_threshold": metadata.get("confidence_threshold", 0.25),
        }
        rt = TorchPerceptionRuntime(model_config)
        setattr(rt, "_descriptor_id", model.id)
        self._perception_runtimes[cache_key] = rt
        self._touch_runtime(cache_key)
        return rt

    def get_perception_runtime(self, model_id: str) -> Optional[Any]:
        """获取已缓存的 Perception runtime，若不存在返回 None"""
        return self._perception_runtimes.get(model_id)

    def get_active_perception_runtime(self) -> Optional[Any]:
        """获取任意已加载的 Perception runtime，供 YOLO Tool 使用"""
        if not self._perception_runtimes:
            return None
        # 返回最近一次使用的 runtime（尽量避免误选旧模型）
        items = list(self._perception_runtimes.items())
        items.sort(key=lambda kv: self._runtime_last_used.get(kv[0], 0.0), reverse=True)
        return items[0][1]

    def is_perception_loaded(self, model_id: str) -> bool:
        """检查指定 perception 模型是否已加载"""
        rt = self._perception_runtimes.get(model_id)
        return rt is not None and getattr(rt, "is_loaded", True)

    def unload_perception_runtime(self, model_id: str) -> bool:
        """卸载指定 perception 模型"""
        rt = self._perception_runtimes.pop(model_id, None)
        if rt is None:
            return False
        try:
            unload_fn = getattr(rt, "unload", None)
            if callable(unload_fn):
                unload_fn()
        except Exception:
            pass
        self._clear_usage_record(model_id)
        return True

    async def unload_perception_runtimes(self) -> int:
        """Best-effort unload of cached perception runtimes (async)."""
        n = 0
        for rt in list(self._perception_runtimes.values()):
            try:
                unload_fn = getattr(rt, "unload", None)
                if callable(unload_fn):
                    unload_fn()
                n += 1
            except Exception:
                n += 1
        self._perception_runtimes.clear()
        return n

    async def unload_image_generation_runtimes(self) -> int:
        n = 0
        for model_id, rt in list(self._image_generation_runtimes.items()):
            try:
                await rt.unload()
                n += 1
            except Exception:
                n += 1
            self._clear_usage_record(model_id)
        self._image_generation_runtimes.clear()
        return n

    def _get_embedding_runtime(self, model: ModelDescriptor) -> EmbeddingRuntime:
        """
        获取或创建 Embedding Runtime
        
        根据 runtime 类型和模型元数据创建对应的 embedding runtime
        """
        # 使用 model.id 作为缓存 key
        cache_key = model.id
        
        if cache_key in self._embedding_runtimes:
            return self._embedding_runtimes[cache_key]
        
        # 根据 runtime 类型创建对应的 embedding runtime
        # NOTE: 历史上 registry 里可能写成 "onnxruntime"（与 onnxruntime 包名一致），这里做兼容映射
        if model.runtime in {"onnx", "embedding_onnx", "onnxruntime"}:
            # 从 metadata 中获取配置
            metadata = model.metadata or {}
            
            # 必需的参数
            model_path = metadata.get("model_path") or metadata.get("path")
            tokenizer_name = metadata.get("tokenizer") or metadata.get("tokenizer_name")
            embedding_dim = metadata.get("embedding_dim", 768)
            
            if not model_path or not tokenizer_name:
                raise ValueError(
                    f"Embedding model '{model.id}' missing required metadata: "
                    f"model_path={model_path}, tokenizer={tokenizer_name}"
                )
            
            runtime = OnnxEmbeddingRuntime(
                model_path=model_path,
                tokenizer_name=tokenizer_name,
                embedding_dim=embedding_dim,
                max_tokens=metadata.get("max_tokens", 512),
                pooling=metadata.get("pooling", "mean"),
                normalize=metadata.get("normalize", True),
                providers=metadata.get("providers"),  # 可选，如 ["CUDAExecutionProvider", "CPUExecutionProvider"]
            )
            
            self._embedding_runtimes[cache_key] = runtime
            return runtime
        else:
            raise ValueError(f"Unsupported embedding runtime type: {model.runtime}")

    def close_embedding_runtimes(self) -> int:
        """
        Best-effort close of cached embedding runtimes.

        This is primarily useful for graceful shutdown / dev-server restarts where the process
        may otherwise retain ONNX sessions in memory until exit.
        """
        n = 0
        for rt in list(self._embedding_runtimes.values()):
            try:
                close_fn = getattr(rt, "close", None)
                if callable(close_fn):
                    close_fn()
                n += 1
            except Exception:
                # best-effort: ignore individual failures
                n += 1
        self._embedding_runtimes.clear()
        return n

# 单例
_factory = None

def get_runtime_factory() -> RuntimeFactory:
    global _factory
    if _factory is None:
        _factory = RuntimeFactory()
    return _factory
