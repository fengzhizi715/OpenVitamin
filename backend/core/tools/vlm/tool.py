"""
vlm.generate: VLM 图文生成 Tool

输入：image（base64 data URL 或 workspace 相对路径）、prompt、model_id（必填）
输出：text
"""

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError
from log import logger


def _decode_data_url(image: str) -> bytes:
    m = re.match(r"^data:image/[a-zA-Z0-9+.-]+;base64,(.+)$", image, re.DOTALL)
    if not m:
        raise ValueError("invalid data URL")
    try:
        return base64.b64decode(m.group(1))
    except Exception as e:
        raise ValueError(f"base64 decode failed: {e}") from e


def _load_image_bytes(image: str, workspace: str) -> bytes:
    if not image or not isinstance(image, str):
        raise ValueError("image is required")
    image = image.strip()

    # base64 data URL
    if image.startswith("data:image/"):
        return _decode_data_url(image)

    # file path (relative to workspace)
    allowed_roots = ["/"]
    try:
        from config.settings import settings
        raw = getattr(settings, "file_read_allowed_roots", None) or ""
        roots = [r.strip() for r in str(raw).split(",") if r.strip()]
        if roots:
            allowed_roots = roots
    except Exception:
        pass

    try:
        resolved = resolve_in_workspace(
            workspace=workspace or ".",
            path=image,
            allowed_absolute_roots=allowed_roots,
        )
        if not resolved.is_file():
            raise ValueError(f"file not found: {resolved}")
        return resolved.read_bytes()
    except WorkspacePathError as e:
        raise ValueError(str(e)) from e


def _is_vlm_model(model_descriptor: Any) -> bool:
    mt = str(getattr(model_descriptor, "model_type", "") or "").lower().strip()
    if mt:
        return any(x in mt for x in ("vlm", "vision", "multimodal"))
    md = getattr(model_descriptor, "metadata", None) or {}
    modality = str(md.get("modality") or "").lower().strip()
    if modality:
        return modality in {"vlm", "vision", "multimodal"}
    capabilities = getattr(model_descriptor, "capabilities", None)
    if isinstance(capabilities, (list, tuple)):
        caps = {str(c).lower().strip() for c in capabilities}
        if {"vision", "image_to_text", "image"} & caps:
            return True
    return False


class VLMGenerateTool(Tool):
    @property
    def name(self) -> str:
        return "vlm.generate"

    @property
    def description(self) -> str:
        return (
            "Generate text from image + prompt using a VLM model. "
            "Input: image (data URL or workspace file path), prompt, model_id. "
            "Output: text."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_id": {"type": "string", "description": "VLM model id to use"},
                "image": {
                    "type": "string",
                    "description": "Image input: base64 data URL or file path relative to workspace",
                },
                "prompt": {"type": "string", "description": "User prompt for VLM"},
                "system_prompt": {"type": "string", "description": "Optional system prompt"},
                "temperature": {"type": "number", "default": 0.7},
                "max_tokens": {"type": "integer", "default": 1024},
                "top_p": {"type": "number", "default": 1.0},
            },
            "required": ["model_id", "image", "prompt"],
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "text": {"type": "string"},
            },
        }

    @property
    def required_permissions(self) -> List[str]:
        return ["file.read"]

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            model_id = (input_data.get("model_id") or "").strip()
            prompt = (input_data.get("prompt") or "").strip()
            image_raw = input_data.get("image")
            if not model_id:
                raise ValueError("model_id is required")
            if not prompt:
                raise ValueError("prompt is required")

            image_bytes = _load_image_bytes(image_raw, ctx.workspace or ".")

            from core.models.registry import get_model_registry
            from core.runtimes.factory import get_runtime_factory

            reg = get_model_registry()
            desc = reg.get_model(model_id)
            if not desc:
                raise ValueError(f"model not found: {model_id}")
            if not _is_vlm_model(desc):
                raise ValueError(f"model is not VLM: {model_id}")

            factory = get_runtime_factory()
            vlm = factory.create_vlm_runtime(desc)
            async with factory.model_usage(model_id):
                if not vlm.is_loaded:
                    await vlm.initialize()

                text = await vlm.infer(
                    image=image_bytes,
                    prompt=prompt,
                    temperature=input_data.get("temperature", 0.7),
                    max_tokens=input_data.get("max_tokens", 1024),
                    top_p=input_data.get("top_p", 1.0),
                    system_prompt=input_data.get("system_prompt"),
                )
            return ToolResult(success=True, data={"model_id": model_id, "text": text})
        except Exception as e:
            logger.exception(f"[vlm.generate] Failed: {e}")
            return ToolResult(success=False, data=None, error=str(e))
