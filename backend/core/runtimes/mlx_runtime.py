"""
MLX 运行时：基于 mlx-lm 的 Apple Silicon 本地 LLM 推理。
仅支持 LLM 文本对话；模型路径为目录（含 config.json、权重等）。
"""
import anyio
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from log import logger
from core.runtimes.base import ModelRuntime
from core.types import ChatCompletionRequest, Message as LLMMessage
from core.models.descriptor import ModelDescriptor
from core.utils.async_rwlock import AsyncRWLock

try:
    from mlx_lm import load, generate, stream_generate
    from mlx_lm.sample_utils import make_sampler
    _MLX_AVAILABLE = True
except ImportError:
    load = generate = stream_generate = make_sampler = None
    _MLX_AVAILABLE = False
    logger.warning("mlx-lm not installed. MLXRuntime will be unavailable.")

_MLX_CACHE: Dict[str, Tuple[Any, Any]] = {}  # path -> (model, tokenizer)
_MODEL_LOCKS: Dict[str, AsyncRWLock] = {}
_FALLBACK_LOCK = AsyncRWLock()


def _get_model_lock(model_path: str) -> AsyncRWLock:
    lock = _MODEL_LOCKS.get(model_path)
    if lock is None:
        lock = AsyncRWLock()
        _MODEL_LOCKS[model_path] = lock
    return lock


def _messages_to_mlx_messages(messages: List[LLMMessage]) -> List[Dict[str, str]]:
    """将网关 Message 列表转为 mlx_lm 使用的 [{"role":..., "content": str}]。"""
    out: List[Dict[str, str]] = []
    for msg in messages:
        role = msg.role if msg.role in ("user", "assistant", "system") else "user"
        if isinstance(msg.content, str):
            text = msg.content
        elif isinstance(msg.content, list):
            parts = []
            for item in msg.content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text"):
                        parts.append(item["text"])
                elif getattr(item, "type", None) == "text":
                    parts.append(getattr(item, "text", "") or "")
            text = "\n".join(parts) if parts else ""
        else:
            text = str(msg.content) if msg.content else ""
        out.append({"role": role, "content": text})
    return out


class MLXRuntime(ModelRuntime):
    """
    基于 mlx-lm 的 LLM 运行时，适用于 Apple Silicon。
    模型路径为目录（metadata.path 由 LocalScanner 解析为绝对路径）。
    """

    def _get_model_and_tokenizer(self, descriptor: ModelDescriptor) -> Tuple[Any, Any]:
        if not _MLX_AVAILABLE:
            raise ImportError(
                "mlx-lm is not installed. Install with: pip install mlx mlx-lm "
                "(typically on macOS with Apple Silicon)."
            )
        model_path = descriptor.metadata.get("path")
        if not model_path:
            raise ValueError(f"Model path missing in metadata for {descriptor.id}")

        if model_path not in _MLX_CACHE:
            logger.info("[MLXRuntime] Loading model from %s", model_path)
            model, tokenizer = load(model_path)
            _MLX_CACHE[model_path] = (model, tokenizer)
        return _MLX_CACHE[model_path]

    async def load(self, descriptor: ModelDescriptor) -> bool:
        try:
            await anyio.to_thread.run_sync(self._get_model_and_tokenizer, descriptor)
            return True
        except Exception as e:
            logger.error("[MLXRuntime] Load failed: %s", e)
            return False

    async def unload(self, descriptor: ModelDescriptor) -> bool:
        model_path = descriptor.metadata.get("path")
        if model_path and model_path in _MLX_CACHE:
            logger.info("[MLXRuntime] Unloading model %s", model_path)
            del _MLX_CACHE[model_path]
            if model_path in _MODEL_LOCKS:
                del _MODEL_LOCKS[model_path]
            return True
        return False

    async def is_loaded(self, descriptor: ModelDescriptor) -> bool:
        model_path = descriptor.metadata.get("path")
        return bool(model_path and model_path in _MLX_CACHE)

    async def chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> str:
        model, tokenizer = self._get_model_and_tokenizer(descriptor)
        model_path = descriptor.metadata.get("path")
        lock = _get_model_lock(model_path) if model_path else _FALLBACK_LOCK

        max_tokens = req.max_tokens if (req.max_tokens is not None and req.max_tokens > 0) else 2048
        temperature = req.temperature if req.temperature is not None else 0.7
        top_p = getattr(req, "top_p", None) or 1.0

        mlx_messages = _messages_to_mlx_messages(req.messages)
        try:
            prompt = tokenizer.apply_chat_template(
                mlx_messages,
                add_generation_prompt=True,
                tokenize=False,
            )
        except Exception as e:
            logger.warning("[MLXRuntime] apply_chat_template failed, using plain concat: %s", e)
            prompt = ""
            for m in mlx_messages:
                prompt += f"{m['role']}: {m['content']}\n"
            prompt += "assistant:\n"

        def _generate() -> str:
            sampler = make_sampler(temp=temperature, top_p=top_p)
            result = generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                sampler=sampler,
            )
            return result if isinstance(result, str) else getattr(result, "text", str(result))

        async with lock.read_lock():
            return await anyio.to_thread.run_sync(_generate)

    async def stream_chat(
        self, descriptor: ModelDescriptor, req: ChatCompletionRequest
    ) -> AsyncIterator[str]:
        model, tokenizer = self._get_model_and_tokenizer(descriptor)
        model_path = descriptor.metadata.get("path")
        lock = _get_model_lock(model_path) if model_path else _FALLBACK_LOCK

        max_tokens = req.max_tokens if (req.max_tokens is not None and req.max_tokens > 0) else 2048
        temperature = req.temperature if req.temperature is not None else 0.7
        top_p = getattr(req, "top_p", None) or 1.0

        mlx_messages = _messages_to_mlx_messages(req.messages)
        try:
            prompt = tokenizer.apply_chat_template(
                mlx_messages,
                add_generation_prompt=True,
                tokenize=False,
            )
        except Exception as e:
            logger.warning("[MLXRuntime] apply_chat_template failed, using plain concat: %s", e)
            prompt = ""
            for m in mlx_messages:
                prompt += f"{m['role']}: {m['content']}\n"
            prompt += "assistant:\n"

        def _stream_gen() -> Any:
            sampler = make_sampler(temp=temperature, top_p=top_p)
            gen = stream_generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                sampler=sampler,
            )
            for chunk in gen:
                if getattr(chunk, "text", None):
                    yield chunk.text

        async with lock.read_lock():
            sync_gen = _stream_gen()

            def _get_next() -> Optional[str]:
                try:
                    return next(sync_gen)
                except StopIteration:
                    return None

            while True:
                token = await anyio.to_thread.run_sync(_get_next)
                if token is None:
                    break
                yield token
