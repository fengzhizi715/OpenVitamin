"""
image.* tools: image generation control-plane tools for agents and skills.

These tools call the platform's internal image-generation API/service path instead
of touching runtimes directly, so model selection and execution stay gateway-centric.
"""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from api.images import (
    ImageGenerateRequest,
    cancel_image_generation_job,
    generate_image,
    get_image_generation_job,
)
from core.models.registry import get_model_registry
from core.system.settings_store import get_system_settings_store
from config.settings import settings
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from log import logger


def _strip_base64_from_job_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, dict) and "image_base64" in result:
        result = {**result, "image_base64": ""}
        payload = {**payload, "result": result}
    return payload


def _strip_base64_from_sync_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "image_base64" in payload:
        payload = {**payload, "image_base64": ""}
    return payload


def _list_image_generation_models() -> List[Dict[str, Any]]:
    registry = get_model_registry()
    result: List[Dict[str, Any]] = []
    for descriptor in registry.list_models():
        if (getattr(descriptor, "model_type", "") or "").lower() != "image_generation":
            continue
        metadata = descriptor.metadata or {}
        result.append(
            {
                "model_id": descriptor.id,
                "name": descriptor.name,
                "runtime": descriptor.runtime,
                "pipeline": metadata.get("pipeline"),
                "pipeline_class": metadata.get("pipeline_class"),
                "device": metadata.get("device") or descriptor.device,
                "default_width": metadata.get("default_width"),
                "default_height": metadata.get("default_height"),
                "default_num_inference_steps": metadata.get("default_num_inference_steps"),
                "default_guidance_scale": metadata.get("default_guidance_scale"),
                "negative_prompt_supported": metadata.get("negative_prompt_supported"),
            }
        )
    result.sort(key=lambda item: item["model_id"])
    return result


def _select_default_image_generation_model_id(requested_model_id: Optional[str] = None) -> Optional[str]:
    models = _list_image_generation_models()
    if not models:
        return None

    def _match_model(candidate_id: Optional[str]) -> Optional[str]:
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            return None
        requested = candidate_id.strip().lower()
        for item in models:
            model_id = str(item.get("model_id") or "")
            name = str(item.get("name") or "")
            if model_id.lower() == requested or name.lower() == requested:
                return model_id
        return None

    explicit_match = _match_model(requested_model_id)
    if explicit_match:
        return explicit_match

    configured_default = (
        get_system_settings_store().get_setting("imageGenerationDefaultModelId")
        or getattr(settings, "image_generation_default_model_id", "")
    )
    configured_match = _match_model(configured_default)
    if configured_match:
        return configured_match

    # Prefer local image_generation models first.
    models_sorted = sorted(
        models,
        key=lambda item: (
            0 if str(item.get("model_id") or "").startswith("local:") else 1,
            str(item.get("name") or ""),
            str(item.get("model_id") or ""),
        ),
    )
    return str(models_sorted[0].get("model_id") or "") or None


class ImageListModelsTool(Tool):
    @property
    def name(self) -> str:
        return "image.list_models"

    @property
    def description(self) -> str:
        return "List available image_generation models and their default parameters."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "models": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "model_id": {"type": "string"},
                            "name": {"type": "string"},
                            "runtime": {"type": "string"},
                            "pipeline": {"type": ["string", "null"]},
                            "pipeline_class": {"type": ["string", "null"]},
                            "device": {"type": ["string", "null"]},
                            "default_width": {"type": ["integer", "null"]},
                            "default_height": {"type": ["integer", "null"]},
                            "default_num_inference_steps": {"type": ["integer", "null"]},
                            "default_guidance_scale": {"type": ["number", "null"]},
                            "negative_prompt_supported": {"type": ["boolean", "null"]},
                        },
                        "required": ["model_id", "name", "runtime"],
                    },
                }
            },
            "required": ["models"],
        }

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "image.list_models",
            "icon": "image",
            "category": "image",
            "permissions_hint": [],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, data={"models": _list_image_generation_models()})


class ImageGenerateTool(Tool):
    @property
    def name(self) -> str:
        return "image.generate"

    @property
    def description(self) -> str:
        return (
            "Generate an image using an image_generation model. "
            "model_id is optional; if omitted, the tool selects a default available image_generation model. "
            "Supports synchronous mode (wait=true) and async job mode (wait=false)."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_id": {"type": "string", "description": "image_generation model id to use"},
                "prompt": {"type": "string", "description": "Text prompt for generation"},
                "negative_prompt": {"type": "string"},
                "width": {"type": "integer", "minimum": 64, "maximum": 4096},
                "height": {"type": "integer", "minimum": 64, "maximum": 4096},
                "num_inference_steps": {"type": "integer", "minimum": 1, "maximum": 200},
                "guidance_scale": {"type": "number", "minimum": 0, "maximum": 50},
                "seed": {"type": "integer", "minimum": 0},
                "image_format": {"type": "string"},
                "wait": {"type": "boolean", "default": True},
                "include_base64": {"type": "boolean", "default": False},
            },
            "required": ["prompt"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "model_id": {"type": "string"},
                "status": {"type": ["string", "null"]},
                "phase": {"type": ["string", "null"]},
                "job_id": {"type": ["string", "null"]},
                "result": {"type": ["object", "null"]},
            },
            "required": ["mode", "model_id"],
        }

    @property
    def required_permissions(self) -> List[str]:
        return ["image.generate"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "image.generate",
            "icon": "image",
            "category": "image",
            "permissions_hint": [{"key": "image.generate", "label": "Generate images with local image models."}],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            selected_model_id = _select_default_image_generation_model_id(input_data.get("model_id"))
            if not selected_model_id:
                return ToolResult(success=False, data=None, error="No available image_generation model found.")

            request = ImageGenerateRequest(
                model=selected_model_id,
                prompt=input_data["prompt"],
                negative_prompt=input_data.get("negative_prompt"),
                width=input_data.get("width"),
                height=input_data.get("height"),
                num_inference_steps=input_data.get("num_inference_steps"),
                guidance_scale=input_data.get("guidance_scale"),
                seed=input_data.get("seed"),
                image_format=input_data.get("image_format") or "PNG",
            )
            wait = bool(input_data.get("wait", False))
            include_base64 = bool(input_data.get("include_base64", False))

            raw = await generate_image(request=request, wait=wait)
            payload = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else dict(raw)
            if not include_base64:
                if wait:
                    payload = _strip_base64_from_sync_payload(payload)
                else:
                    payload = _strip_base64_from_job_payload(payload)

            if wait:
                data = {
                    "mode": "sync",
                    "model_id": request.model,
                    "status": "succeeded",
                    "phase": "completed",
                    "job_id": None,
                    "result": payload,
                }
            else:
                data = {
                    "mode": "async",
                    "model_id": request.model,
                    "status": payload.get("status"),
                    "phase": payload.get("phase"),
                    "job_id": payload.get("job_id"),
                    "result": payload.get("result"),
                }
            return ToolResult(success=True, data=data)
        except HTTPException as e:
            return ToolResult(success=False, data=None, error=str(e.detail))
        except Exception as e:
            logger.exception("[image.generate] Failed: %s", e)
            return ToolResult(success=False, data=None, error=str(e))


class ImageGetJobTool(Tool):
    @property
    def name(self) -> str:
        return "image.get_job"

    @property
    def description(self) -> str:
        return "Get image generation job status and result metadata by job_id."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "include_base64": {"type": "boolean", "default": False},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "status": {"type": "string"},
                "phase": {"type": ["string", "null"]},
                "result": {"type": ["object", "null"]},
            },
            "required": ["job_id", "status"],
        }

    @property
    def required_permissions(self) -> List[str]:
        return ["image.generate"]

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            job = await get_image_generation_job(input_data["job_id"])
            payload = job.model_dump(mode="json")
            if not bool(input_data.get("include_base64", False)):
                payload = _strip_base64_from_job_payload(payload)
            return ToolResult(success=True, data=payload)
        except HTTPException as e:
            return ToolResult(success=False, data=None, error=str(e.detail))
        except Exception as e:
            logger.exception("[image.get_job] Failed: %s", e)
            return ToolResult(success=False, data=None, error=str(e))


class ImageCancelJobTool(Tool):
    @property
    def name(self) -> str:
        return "image.cancel_job"

    @property
    def description(self) -> str:
        return "Cancel an image generation job by job_id."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "status": {"type": "string"},
                "phase": {"type": ["string", "null"]},
            },
            "required": ["job_id", "status"],
        }

    @property
    def required_permissions(self) -> List[str]:
        return ["image.generate"]

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            job = await cancel_image_generation_job(input_data["job_id"])
            payload = _strip_base64_from_job_payload(job.model_dump(mode="json"))
            return ToolResult(success=True, data=payload)
        except HTTPException as e:
            return ToolResult(success=False, data=None, error=str(e.detail))
        except Exception as e:
            logger.exception("[image.cancel_job] Failed: %s", e)
            return ToolResult(success=False, data=None, error=str(e))
