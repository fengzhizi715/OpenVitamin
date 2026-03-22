"""
ASR API 端点
提供 麦克风/音频 → 文本 的语音识别服务
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from log import logger
from core.models.registry import get_model_registry
from core.inference import get_inference_client

router = APIRouter()


class ASRTranscribeResponse(BaseModel):
    """ASR 转录响应"""
    text: str = Field(..., description="完整转录文本")
    language: str = Field(..., description="检测到的语言代码")
    segments: list = Field(default_factory=list, description="时间轴分段")


@router.post("/api/asr/transcribe", response_model=ASRTranscribeResponse)
async def asr_transcribe(
    audio: UploadFile = File(..., description="音频文件 (wav/mp3/m4a)"),
    model_id: Optional[str] = Form(default="local:faster-whisper-small", description="ASR 模型 ID"),
):
    """
    将音频转录音频为文本。

    流程：麦克风录音 → 上传音频 → ASR 转录 → 返回文本
    返回的文本可直接作为聊天输入发送给 LLM。
    """
    reg = get_model_registry()
    client = get_inference_client()

    # 解析模型 ID（支持 "local:whisper-small" 或 "whisper-small"）
    resolved_id = model_id if model_id.startswith("local:") else f"local:{model_id}"
    descriptor = reg.get_model(resolved_id)

    if not descriptor:
        # 尝试不带 local 前缀
        descriptor = reg.get_model(model_id)
    if not descriptor:
        raise HTTPException(
            status_code=404,
            detail=f"ASR model not found: {model_id}. Ensure the ASR model is scanned (model_type=asr) and dataDirectory includes the asr/ directory.",
        )

    if getattr(descriptor, "model_type", "").lower() != "asr":
        raise HTTPException(
            status_code=400,
            detail=f"Model {model_id} is not an ASR model (model_type={getattr(descriptor, 'model_type', '')})",
        )

    # 读取音频数据
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # 保存为临时文件（faster-whisper 支持文件路径）
    import tempfile
    import os
    suffix = ".webm"  # 浏览器 MediaRecorder 默认输出 webm
    if audio.filename:
        ext = os.path.splitext(audio.filename)[1].lower()
        if ext in (".mp3", ".m4a", ".ogg", ".webm", ".wav"):
            suffix = ext
    elif audio.content_type:
        # 根据 Content-Type 推断
        if "webm" in audio.content_type:
            suffix = ".webm"
        elif "mp3" in audio.content_type or "mpeg" in audio.content_type:
            suffix = ".mp3"
        elif "wav" in audio.content_type:
            suffix = ".wav"

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            # Route through Inference Gateway for decoupling (local-first file reference).
            workspace = os.path.dirname(tmp_path)
            rel = os.path.basename(tmp_path)
            resp = await client.transcribe(
                model=descriptor.id,
                audio=rel,
                workspace=workspace,
                options={},
                metadata={"caller": "api.asr.transcribe"},
            )
            return ASRTranscribeResponse(
                text=resp.text or "",
                language=resp.language or "unknown",
                segments=resp.segments or [],
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logger.exception("ASR transcribe failed")
        raise HTTPException(status_code=500, detail=str(e))
