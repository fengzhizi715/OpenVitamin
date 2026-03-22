"""
VLM API 端点
提供 image + text → text 的多模态推理服务
"""

import json
import base64
import time
from pathlib import Path
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, UploadFile, Form, File, Request, Response
from pydantic import BaseModel, Field
from log import logger
from config.settings import settings

from core.models.descriptor import ModelDescriptor
from core.runtimes.vlm_runtime import VLMRuntime
from core.models.registry import get_model_registry
from core.runtimes.factory import get_runtime_factory
from core.conversation.history_store import HistoryStore, HistoryStoreConfig
from core.runtime.queue.inference_queue import get_inference_queue_manager
from core.runtime.manager.runtime_metrics import get_runtime_metrics
from core.inference.stats.tracker import record_inference, estimate_tokens
from core.system.runtime_settings import get_auto_unload_local_model_on_switch
from log import log_structured

router = APIRouter()

# Use consistent DB path with other session APIs
_db_path = (
    Path(__file__).resolve().parents[1] / "data" / "platform.db"
    if not settings.db_path
    else Path(settings.db_path)
)
_history_store = HistoryStore(
    HistoryStoreConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
        vector_enabled=bool(settings.memory_vector_enabled),
    )
)


def _get_user_id(req: Request) -> str:
    uid = (req.headers.get("X-User-Id") or "").strip()
    return uid or "default"


def _get_or_create_session_id(*, store: HistoryStore, req: Request, user_id: str, title_hint: str, model_id: str) -> str:
    sid = (req.headers.get("X-Session-Id") or "").strip()
    if sid and store.session_exists(user_id=user_id, session_id=sid):
        return sid
    title = (title_hint or "").strip()
    if not title:
        title = "New Chat"
    else:
        title = title[:50]
    return store.create_session(user_id=user_id, title=title, last_model=model_id)


async def _maybe_unload_previous_model(*, store: HistoryStore, user_id: str, session_id: str, current_model_id: str) -> None:
    try:
        session = store.get_session(user_id=user_id, session_id=session_id)
        last_model = (session or {}).get("last_model")
        if not last_model or last_model == current_model_id:
            return
        from core.models.registry import get_model_registry
        from core.runtimes.factory import get_runtime_factory

        reg = get_model_registry()
        prev_desc = reg.get_model(last_model)
        if not prev_desc or getattr(prev_desc, "provider", None) != "local":
            return
        await get_runtime_factory().unload_model(prev_desc.id)
        logger.info("[VLM API] Unloaded previous model %s before switching to %s", last_model, current_model_id)
    except Exception as e:
        logger.warning("[VLM API] Failed to unload previous model: %s", e)


def _sniff_mime(b: bytes, fallback: str = "image/jpeg") -> str:
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if b.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if b.startswith(b"RIFF") and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return fallback


class VLMGenerateRequest(BaseModel):
    """
    VLM 生成请求模型
    """
    model: str = Field(..., description="VLM 模型 ID")
    prompt: str = Field(..., description="文本提示词", min_length=1)
    system_prompt: Optional[str] = Field(
        default=None,
        description="可选的系统提示词（用于约束模型行为，例如要求必须基于图像回答）",
        max_length=4096,
    )
    temperature: Optional[float] = Field(default=0.7, ge=0, le=2, description="采样温度")
    max_tokens: Optional[int] = Field(default=512, ge=1, le=8192, description="最大生成 token 数")


class VLMGenerateResponse(BaseModel):
    """
    VLM 生成响应模型
    """
    model: str = Field(..., description="使用的模型 ID")
    text: str = Field(..., description="生成的文本结果")
    usage: Optional[dict] = Field(default=None, description="使用统计信息")


@router.post("/v1/vlm/generate", response_model=VLMGenerateResponse)
async def vlm_generate(
    request: Request,
    response: Response,
    request_json: str = Form(..., alias="request", description="JSON string of VLMGenerateRequest"),
    image: UploadFile = File(..., description="输入图像文件"),
):
    """
    VLM 多模态推理接口
    
    Args:
        request: VLM 生成请求参数
        image: 上传的图像文件
        
    Returns:
        VLMGenerateResponse: 包含生成文本的响应
        
    Raises:
        HTTPException: 当模型不存在、不是 VLM 模型或推理失败时
        
    设计说明：
    1. 使用 Form + File 分离 JSON 参数和二进制图像数据
    2. 不复用 OpenAI ChatCompletion 协议，采用专为 VLM 设计的简洁接口
    3. 从 ModelRegistry 获取模型信息，通过 RuntimeFactory 获取对应运行时
    4. 调用 VLMRuntime.infer() 执行推理
    5. 不处理鉴权、streaming、模型自动选择（由上层处理）
    """

    # NOTE: FastAPI will inject Request/Response by type, but our parameter names conflict with "request" form field.
    # We therefore retrieve them via dependency injection by name: FastAPI still supports this as long as the types match.
    store = _history_store
    
    logger.info("[VLM API] /v1/vlm/generate request received filename=%r content_type=%r", image.filename, image.content_type)

    # 0. 解析表单中的 JSON 请求参数
    try:
        req_obj = VLMGenerateRequest(**json.loads(request_json))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request JSON: {e}")
    logger.info(
        "[VLM API] parsed request model=%s prompt_len=%s temperature=%s max_tokens=%s",
        req_obj.model, len(req_obj.prompt or ""), req_obj.temperature, req_obj.max_tokens,
    )

    # 1. 验证模型是否存在且为 VLM 类型
    model_registry = get_model_registry()
    # Some registries expose get_model(); keep a small compatibility shim here.
    model_descriptor = None
    if hasattr(model_registry, "get_model"):
        model_descriptor = model_registry.get_model(req_obj.model)
    elif hasattr(model_registry, "get"):
        model_descriptor = model_registry.get(req_obj.model)
    
    if not model_descriptor:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{req_obj.model}' not found"
        )
    
    # 2. 验证模型类型（应为 VLM 或包含 vision 能力）
    # 这里可以根据你的模型描述符结构调整验证逻辑
    if not _is_vlm_model(model_descriptor):
        raise HTTPException(
            status_code=400,
            detail=f"Model '{req_obj.model}' is not a VLM model"
        )
    
    # 3. 获取对应的 VLM Runtime（使用单例工厂以复用 VLM runtime 缓存）
    runtime_factory = get_runtime_factory()
    await runtime_factory.auto_release_unused_local_runtimes(
        keep_model_ids={req_obj.model},
        reason="vlm_api",
    )
    try:
        vlm_runtime = await _get_vlm_runtime(model_descriptor, runtime_factory)
    except Exception as e:
        logger.error(f"[VLM API] Failed to get VLM runtime for model {req_obj.model}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize VLM runtime: {str(e)}"
        )
    
    # 4. 读取并验证图像数据
    try:
        image_content = await image.read()
        if not image_content:
            raise HTTPException(
                status_code=400,
                detail="Empty image file provided"
            )
    except Exception as e:
        logger.error(f"[VLM API] Failed to read image file: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image file: {str(e)}"
        )
    logger.info("[VLM API] image bytes read size=%s", len(image_content))
    
    # Session persistence (so /chat sessions won't lose VLM turns)
    # Session persistence (so /chat sessions won't lose VLM turns)
    user_id = "default"
    session_id = None
    try:
        if isinstance(request, Request):
            user_id = _get_user_id(request)
            session_id = _get_or_create_session_id(
                store=store,
                req=request,
                user_id=user_id,
                title_hint=req_obj.prompt,
                model_id=req_obj.model,
            )
            if isinstance(response, Response):
                response.headers["X-Session-Id"] = session_id
            if session_id and get_auto_unload_local_model_on_switch():
                await _maybe_unload_previous_model(
                    store=store,
                    user_id=user_id,
                    session_id=session_id,
                    current_model_id=req_obj.model,
                )
    except Exception as e:
        logger.warning(f"[VLM API] Failed to get/create session: {e}")
    logger.info("[VLM API] session resolved user_id=%s session_id=%s", user_id, session_id)

    # Build attachment meta for UI (store only meta, keep message content pure text for LLM chat maintainability)
    mime = _sniff_mime(image_content, fallback=(image.content_type or "image/jpeg"))
    data_url = f"data:{mime};base64,{base64.b64encode(image_content).decode('utf-8')}"
    attachments_meta = [{"type": "image", "url": data_url, "name": image.filename or "image"}]

    # Persist user message
    if session_id:
        try:
            store.append_message(
                session_id=session_id,
                role="user",
                content=req_obj.prompt,
                meta={"attachments": attachments_meta, "vlm": True},
            )
            store.touch_session(user_id=user_id, session_id=session_id, last_model=req_obj.model)
        except Exception as e:
            logger.warning(f"[VLM API] Failed to persist user message: {e}")

    # 5. 执行推理
    try:
        async with runtime_factory.model_usage(req_obj.model):
            # 确保运行时已初始化
            if not vlm_runtime.is_loaded:
                logger.info("[VLM API] initializing VLM runtime model=%s runtime=%s", req_obj.model, getattr(model_descriptor, "runtime", None))
                await vlm_runtime.initialize()
            else:
                logger.info("[VLM API] runtime cache hit model=%s", req_obj.model)
            
            # 执行多模态推理
            logger.info("[VLM API] infer start model=%s", req_obj.model)
            default_system_prompt = (
            "你是一个视觉语言助手。图像已经直接输入到你的视觉编码器中，你可以完全看到图像内容。\n"
            "用户消息中的图像是你当前可以直接观察和理解的视觉输入，不是外部附件或链接。\n"
            "请直接描述和分析图像内容，回答用户的问题。\n"
            "绝对不要说\"我无法查看图像\"、\"无法查看附件\"、\"无法访问外部链接\"等话术。\n"
            "如果图像内容不清晰或难以识别，请描述你能看到的细节，并说明需要用户补充哪些信息。"
            )
            # Runtime Stabilization: per-model concurrency limit + basic metrics.
            queue_manager = get_inference_queue_manager()
            metrics = get_runtime_metrics()
            runtime_type = str(getattr(model_descriptor, "runtime", "") or "default")
            queue = queue_manager.get_queue(req_obj.model, runtime_type)

            start_infer = time.time()
            metrics.record_request(req_obj.model)
            log_structured("RuntimeStabilization", "inference_started", model_id=req_obj.model, runtime=runtime_type)

            result_text = await queue.run(vlm_runtime.infer(
                image=image_content,  # 传递 bytes 数据
                prompt=req_obj.prompt,
                system_prompt=(req_obj.system_prompt or default_system_prompt),
                temperature=req_obj.temperature,
                max_tokens=req_obj.max_tokens
            ))
            latency_ms = (time.time() - start_infer) * 1000
            metrics.record_latency(req_obj.model, latency_ms)
            tokens_est = estimate_tokens(result_text or "")
            metrics.record_tokens(req_obj.model, tokens_est)
            record_inference(tokens=tokens_est, latency_ms=latency_ms, model=req_obj.model, provider=getattr(model_descriptor, "provider", ""))
            log_structured(
                "RuntimeStabilization",
                "inference_completed",
                model_id=req_obj.model,
                runtime=runtime_type,
                latency_ms=round(latency_ms, 2),
                tokens=tokens_est,
            )
        logger.info("[VLM API] infer done model=%s output_len=%s", req_obj.model, len(result_text or ""))
        
        logger.info(f"[VLM API] Generated text for model {req_obj.model}, prompt length: {len(req_obj.prompt)}")
        
    except Exception as e:
        try:
            get_runtime_metrics().record_request_failed(req_obj.model)
            log_structured("RuntimeStabilization", "inference_error", level="error", model_id=req_obj.model, error=str(e)[:300])
        except Exception:
            pass
        logger.error(f"[VLM API] Inference failed for model {req_obj.model}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Inference failed: {str(e)}"
        )

    # Persist assistant message
    if session_id:
        try:
            store.append_message(
                session_id=session_id,
                role="assistant",
                content=result_text,
                model=req_obj.model,
                meta={"vlm": True},
            )
            store.touch_session(user_id=user_id, session_id=session_id, last_model=req_obj.model)
        except Exception as e:
            logger.warning(f"[VLM API] Failed to persist assistant message: {e}")
    
    # 6. 返回结果
    return VLMGenerateResponse(
        model=req_obj.model,
        text=result_text,
        usage={
            "prompt_tokens": len(req_obj.prompt.split()),  # 简单估算
            "completion_tokens": len(result_text.split()),
        }
    )


def _is_vlm_model(model_descriptor: ModelDescriptor) -> bool:
    """
    判断模型是否为 VLM 模型
    
    Args:
        model_descriptor: 模型描述符
        
    Returns:
        bool: 是否为 VLM 模型
        
    设计说明：
    根据你的模型管理系统调整此判断逻辑
    可能的判断依据：
    - model_type 字段包含 "vlm" 或 "vision"
    - capabilities 字段包含 "image_to_text"
    - model_name 包含视觉相关关键词
    """
    # Long-term maintainability: prefer explicit modality/type fields; avoid name-based heuristics.
    mt = str(getattr(model_descriptor, "model_type", "") or "").lower().strip()
    if mt:
        return any(x in mt for x in ("vlm", "vision", "multimodal"))

    # Optional: explicit metadata.modality (if your descriptor stores it there)
    md = getattr(model_descriptor, "metadata", None) or {}
    modality = str(md.get("modality") or "").lower().strip()
    if modality:
        return modality in {"vlm", "vision", "multimodal"}

    # Optional: capabilities list (if present)
    capabilities = getattr(model_descriptor, "capabilities", None)
    if isinstance(capabilities, (list, tuple)):
        caps = {str(c).lower().strip() for c in capabilities}
        if {"vision", "image_to_text", "image"} & caps:
            return True

    # Strict default: do NOT guess by model name (prevents accidental misrouting).
    return False


async def _get_vlm_runtime(model_descriptor: ModelDescriptor, factory: Any) -> VLMRuntime:
    """
    获取 VLM 运行时实例
    
    Args:
        model_descriptor: 模型描述符
        factory: 运行时工厂
        
    Returns:
        VLMRuntime: VLM 运行时实例
    """
    # 使用工厂基于 ModelDescriptor 创建 VLM 运行时
    return factory.create_vlm_runtime(model_descriptor)


# 使用示例（仅供说明）：
"""
curl -X POST "http://localhost:8000/api/v1/vlm/generate" \\
  -H "Content-Type: multipart/form-data" \\
  -F "request={\"model\": \"qwen3-vl-8b\", \"prompt\": \"Describe this image in detail.\", \"temperature\": 0.7}" \\
  -F "image=@/path/to/image.jpg"

响应示例：
{
  "model": "qwen3-vl-8b",
  "text": "This image shows a beautiful landscape with mountains and a lake...",
  "usage": {
    "prompt_tokens": 6,
    "completion_tokens": 45
  }
}
"""
