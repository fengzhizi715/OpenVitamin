"""
TorchVLMRuntime: 基于 PyTorch + HuggingFace Transformers 的 VLM 运行时

- 根据 manifest 的 architecture 自动选择 ModelAdapter（internvl / qwen-vl）
- 对外接口与 VLMRuntime 完全一致，支持 infer() 与 generate()
- 与 llama.cpp 行为对齐
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Union, Optional, Dict, Any

try:
    from PIL import Image
except ImportError:
    Image = None

from core.runtimes.vlm_runtime import VLMRuntime
from core.utils.async_rwlock import AsyncRWLock
from core.runtimes.vlm_types import VLMRequest, VLMResponse, VLMGenerationConfig
from .model_adapter import ModelAdapter
from .internvl_adapter import InternVLAdapter
from .qwen_vl_adapter import QwenVLAdapter

_ADAPTER_REGISTRY: Dict[str, type] = {
    "internvl": InternVLAdapter,
    "internvl2": InternVLAdapter,
    "internvl3": InternVLAdapter,
    "qwen-vl": QwenVLAdapter,
    "qwen2-vl": QwenVLAdapter,
    "qwen3-vl": QwenVLAdapter,
    "qwen3.5": QwenVLAdapter,
    "qwen3_5": QwenVLAdapter,
}


class TorchVLMRuntime(VLMRuntime):
    """
    Torch VLM Runtime

    根据 model.json 的 architecture 选择 Adapter，不感知具体模型结构。
    """

    def __init__(self, model_dir: Union[str, Path], manifest: Optional[Dict[str, Any]] = None):
        self._model_dir = Path(model_dir)
        self._manifest = manifest or self._load_manifest()
        self._adapter: Optional[ModelAdapter] = None
        self._lock = AsyncRWLock()

    def _load_manifest(self) -> Dict[str, Any]:
        p = self._model_dir / "model.json"
        if not p.exists():
            raise FileNotFoundError(f"model.json not found in {self._model_dir}")
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def _get_adapter(self) -> ModelAdapter:
        metadata = self._manifest.get("metadata") or {}
        arch = (self._manifest.get("architecture") or metadata.get("architecture") or "").lower().replace("_", "-")
        if not arch:
            # 兜底：从 HuggingFace config.json 推断（如 qwen3_5 / qwen3_vl / internvl3）
            try:
                cfg_path = self._model_dir / "config.json"
                if cfg_path.exists():
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    mt = str(cfg.get("model_type") or "").lower()
                    if mt:
                        arch = mt.replace("_", "-")
            except Exception:
                pass
        if not arch:
            raise ValueError("manifest.architecture required for torch runtime")
        cls = _ADAPTER_REGISTRY.get(arch)
        if not cls:
            # 尝试前缀匹配
            for k, v in _ADAPTER_REGISTRY.items():
                if arch.startswith(k) or k in arch:
                    cls = v
                    break
        if not cls:
            raise ValueError(f"Unsupported architecture: {arch}. Supported: {list(_ADAPTER_REGISTRY.keys())}")
        return cls()

    async def initialize(self, model_path: Union[str, Path] = None, **kwargs) -> None:
        """加载模型（通过 Adapter）"""
        if self._adapter is not None and self._adapter.is_loaded:
            return

        async with self._lock.write_lock():
            if self._adapter is not None and self._adapter.is_loaded:
                return

            model_dir = Path(model_path) if model_path else self._model_dir
            metadata = self._manifest.get("metadata") or {}
            options = {
                "model_name": str(model_dir),
                "torch_dtype": self._manifest.get("torch_dtype", metadata.get("torch_dtype", "float16")),
                "device": self._manifest.get("device", metadata.get("device", "auto")),
                "architecture": self._manifest.get("architecture", metadata.get("architecture", "")),
                **(self._manifest.get("vision") or {}),
            }
            # 可选：从 model.json 根级或 image_preprocess 读取图像约束（仅 Torch VLM 使用）
            img_pre = self._manifest.get("image_preprocess") or {}
            md_img_pre = metadata.get("image_preprocess") if isinstance(metadata, dict) else {}
            if "max_image_side" in self._manifest:
                options["max_image_side"] = self._manifest.get("max_image_side")
            if "max_image_pixels" in self._manifest:
                options["max_image_pixels"] = self._manifest.get("max_image_pixels")
            if isinstance(img_pre, dict):
                if "max_image_side" in img_pre:
                    options["max_image_side"] = img_pre.get("max_image_side")
                if "max_image_pixels" in img_pre:
                    options["max_image_pixels"] = img_pre.get("max_image_pixels")
            # 兼容放在 metadata 下（优先级更高，便于按模型单独调优）
            if isinstance(md_img_pre, dict):
                if "max_image_side" in md_img_pre:
                    options["max_image_side"] = md_img_pre.get("max_image_side")
                if "max_image_pixels" in md_img_pre:
                    options["max_image_pixels"] = md_img_pre.get("max_image_pixels")
            if isinstance(metadata, dict):
                if "max_image_side" in metadata:
                    options["max_image_side"] = metadata.get("max_image_side")
                if "max_image_pixels" in metadata:
                    options["max_image_pixels"] = metadata.get("max_image_pixels")
            options.update(kwargs)

            adapter = self._get_adapter()
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: adapter.load(model_dir, options))
            self._adapter = adapter

    async def infer(
        self,
        image: Union["Image.Image", bytes],
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        执行单次多模态推理（兼容现有 VLMRuntime 接口）

        将 image + prompt 转为 VLMRequest，调用 generate。
        """
        messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": _image_to_data_url(image)}}, {"type": "text", "text": prompt}]}]
        system = (kwargs.get("system_prompt") or "").strip()
        if system:
            messages.insert(0, {"role": "system", "content": system})

        top_p = kwargs.get("top_p")
        req = VLMRequest(
            messages=messages,
            images=None,
            generation_config=VLMGenerationConfig(
                max_tokens=max_tokens if (max_tokens is not None and max_tokens > 0) else 2048,
                temperature=temperature if temperature is not None else 0.7,
                top_p=top_p if top_p is not None else 1.0,
                stop=kwargs.get("stop"),
            ),
        )
        resp = await self.generate(req)
        if resp.choices:
            msg = resp.choices[0].get("message", {})
            return msg.get("content", "")
        return ""

    async def generate(self, req: VLMRequest) -> VLMResponse:
        """
        执行生成，与 llama.cpp 行为对齐
        """
        async with self._lock.read_lock():
            if self._adapter is None or not self._adapter.is_loaded:
                raise RuntimeError("Model not initialized. Call initialize() first.")
            cfg = req.generation_config or VLMGenerationConfig()
            messages = req.messages
            images = req.images

            def _run():
                return self._adapter.generate(
                    messages=messages,
                    images=images,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    top_p=cfg.top_p,
                    stop=cfg.stop,
                )

            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(None, _run)

            # 构建与 llama.cpp 一致的 VLMResponse
            return VLMResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
                object="chat.completion",
                created=int(time.time()),
                model=self._manifest.get("model_name", "torch-vlm"),
                choices=[{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                usage=None,
            )

    async def unload(self) -> None:
        async with self._lock.write_lock():
            if self._adapter:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._adapter.unload)
                self._adapter = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        try:
            import gc
            gc.collect()
        except Exception:
            pass

    @property
    def is_loaded(self) -> bool:
        return self._adapter is not None and self._adapter.is_loaded

    @property
    def model_info(self) -> Dict[str, Any]:
        return {
            "runtime": "torch",
            "modality": "vlm",
            "model_dir": str(self._model_dir),
            "architecture": self._manifest.get("architecture", "unknown"),
            "model_name": self._manifest.get("model_name", ""),
        }

    def health(self) -> Dict[str, Any]:
        if self._adapter:
            return self._adapter.health()
        return {"status": "not_loaded"}


def _image_to_data_url(image: Union["Image.Image", bytes]) -> str:
    import base64
    from io import BytesIO

    def _sniff_mime(b: bytes) -> str:
        if b.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if b.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if b.startswith(b"RIFF") and b[8:12] == b"WEBP":
            return "image/webp"
        return "image/png"

    if isinstance(image, bytes):
        mime = _sniff_mime(image)
        b64 = base64.b64encode(image).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    if Image and isinstance(image, Image.Image):
        buf = BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    raise ValueError("image must be PIL.Image or bytes")
