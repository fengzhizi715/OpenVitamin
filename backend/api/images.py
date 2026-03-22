"""
Image generation API.

Supports:
- synchronous generation
- async job mode with polling
"""

import asyncio
import base64
import binascii
import gc
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from log import logger
from config.settings import settings
from core.data.base import SessionLocal
from core.data.models.image_generation import ImageGenerationJobORM, ImageGenerationWarmupORM
from core.models.descriptor import ModelDescriptor
from core.models.registry import get_model_registry
from core.runtime.queue import get_inference_queue_manager
from core.runtimes.factory import get_runtime_factory
from core.runtimes.image_generation_types import (
    ImageGenerationJobResponse,
    ImageGenerationJobListResponse,
    ImageGenerationJobStatus,
    ImageGenerationRequest as RuntimeImageGenerationRequest,
    ImageGenerationResponse,
    ImageGenerationWarmupResponse,
)

router = APIRouter()


class ImageGenerateRequest(BaseModel):
    model: str = Field(..., description="image_generation 模型 ID")
    prompt: str = Field(..., min_length=1, description="正向提示词")
    negative_prompt: str | None = Field(default=None, description="负向提示词")
    width: int | None = Field(default=None, ge=64, le=4096)
    height: int | None = Field(default=None, ge=64, le=4096)
    num_inference_steps: int | None = Field(default=None, ge=1, le=200)
    guidance_scale: float | None = Field(default=None, ge=0, le=50)
    seed: int | None = Field(default=None, ge=0)
    image_format: str = Field(default="PNG", description="输出格式，如 PNG/JPEG")


class ImageWarmupRequest(BaseModel):
    model: str = Field(..., description="image_generation 模型 ID")
    prompt: str = Field(default="warmup image", min_length=1, description="warmup 用提示词")
    width: int = Field(default=256, ge=64, le=1024)
    height: int = Field(default=256, ge=64, le=1024)
    num_inference_steps: int = Field(default=1, ge=1, le=8)
    guidance_scale: float = Field(default=1.0, ge=0, le=20)
    seed: int = Field(default=42, ge=0)


@dataclass
class _ImageGenerationJob:
    job_id: str
    request: ImageGenerateRequest
    status: ImageGenerationJobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    phase: Optional[str] = None
    queue_position: Optional[int] = None
    error: Optional[str] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    progress: Optional[float] = None
    result: Optional[ImageGenerationResponse] = None
    cancelled: bool = False
    task: Optional[asyncio.Task] = field(default=None, repr=False)


_IMAGE_JOBS: Dict[str, _ImageGenerationJob] = {}
_IMAGE_JOBS_LOCK = asyncio.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GENERATED_IMAGES_DIR = (_PROJECT_ROOT / "backend" / "data" / "generated_images").resolve()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _clone_request(request: ImageGenerateRequest) -> ImageGenerateRequest:
    return ImageGenerateRequest.model_validate(request.model_dump())


def _is_mps_oom_error(exc: Exception) -> bool:
    text = str(exc or "")
    lowered = text.lower()
    return "mps backend out of memory" in lowered or (
        "out of memory" in lowered and "mps" in lowered
    )


async def _force_release_other_image_generation_runtimes(
    factory,
    *,
    keep_model_id: Optional[str] = None,
    reason: str = "",
) -> int:
    keep = {keep_model_id} if keep_model_id else set()
    released = await factory.unload_other_image_generation_runtimes(keep_model_ids=keep)
    gc.collect()
    try:
        import torch  # type: ignore

        if hasattr(torch, "mps"):
            torch.mps.empty_cache()
    except Exception:
        pass
    if released > 0:
        logger.info(
            "[ImageGenerateAPI] released_other_image_runtimes released=%s keep=%s reason=%s",
            released,
            keep_model_id or "-",
            reason or "n/a",
        )
    return released


def _db_upsert_job(job: _ImageGenerationJob) -> None:
    db: Session = SessionLocal()
    try:
        row = db.get(ImageGenerationJobORM, job.job_id)
        payload = {
            "job_id": job.job_id,
            "model": job.request.model,
            "prompt": job.request.prompt,
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "phase": job.phase,
            "error": job.error,
            "request_json": {
                **job.request.model_dump(mode="json"),
                "__queue_position": job.queue_position,
                "__current_step": job.current_step,
                "__total_steps": job.total_steps,
                "__progress": job.progress,
            },
            "result_json": job.result.model_dump(mode="json") if job.result else None,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }
        if row is None:
            row = ImageGenerationJobORM(**payload)
            db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        db.commit()
    finally:
        db.close()


def _db_delete_job(job_id: str) -> None:
    db: Session = SessionLocal()
    try:
        row = db.get(ImageGenerationJobORM, job_id)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def _db_mark_warmups_not_latest(model: str) -> None:
    db: Session = SessionLocal()
    try:
        db.query(ImageGenerationWarmupORM).filter(
            ImageGenerationWarmupORM.model == model,
            ImageGenerationWarmupORM.latest.is_(True),
        ).update({"latest": False}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _db_create_warmup(
    *,
    warmup_id: str,
    model: str,
    prompt: str,
    request_json: dict,
    started_at: datetime,
    finished_at: datetime,
    elapsed_ms: int,
    output_path: Optional[str],
    width: Optional[int],
    height: Optional[int],
    result_json: Optional[dict],
    status: str = "succeeded",
    error: Optional[str] = None,
) -> None:
    db: Session = SessionLocal()
    try:
        db.query(ImageGenerationWarmupORM).filter(
            ImageGenerationWarmupORM.model == model,
            ImageGenerationWarmupORM.latest.is_(True),
        ).update({"latest": False}, synchronize_session=False)
        row = ImageGenerationWarmupORM(
            warmup_id=warmup_id,
            model=model,
            prompt=prompt,
            status=status,
            elapsed_ms=elapsed_ms,
            output_path=output_path,
            width=width,
            height=height,
            error=error,
            request_json=request_json,
            result_json=result_json,
            latest=True,
            created_at=started_at,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _db_get_latest_warmup(model: Optional[str] = None) -> Optional[ImageGenerationWarmupORM]:
    db: Session = SessionLocal()
    try:
        query = db.query(ImageGenerationWarmupORM)
        if model:
            query = query.filter(ImageGenerationWarmupORM.model == model)
        row = query.order_by(ImageGenerationWarmupORM.created_at.desc()).first()
        if row is None:
            return None
        db.expunge(row)
        return row
    finally:
        db.close()


def _orm_to_job_response(row: ImageGenerationJobORM, *, include_base64: bool = True) -> ImageGenerationJobResponse:
    result = None
    if row.result_json:
        payload = dict(row.result_json)
        if not include_base64:
            payload["image_base64"] = ""
        result = ImageGenerationResponse.model_validate(payload)
    return ImageGenerationJobResponse(
        job_id=row.job_id,
        status=ImageGenerationJobStatus(row.status),
        model=row.model,
        prompt=row.prompt,
        phase=row.phase,
        error=row.error,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        queue_position=(row.request_json or {}).get("__queue_position"),
        current_step=(row.request_json or {}).get("__current_step"),
        total_steps=(row.request_json or {}).get("__total_steps"),
        progress=(row.request_json or {}).get("__progress"),
        result=result,
    )


def _orm_to_warmup_response(row: ImageGenerationWarmupORM) -> ImageGenerationWarmupResponse:
    return ImageGenerationWarmupResponse(
        warmup_id=row.warmup_id,
        model=row.model,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        elapsed_ms=row.elapsed_ms,
        output_path=row.output_path,
        width=row.width,
        height=row.height,
        error=row.error,
    )


def _image_extension_from_mime(mime_type: str) -> str:
    lower = (mime_type or "").lower()
    if lower == "image/jpeg":
        return "jpg"
    if lower == "image/webp":
        return "webp"
    return "png"


def _persist_image_result(response: ImageGenerationResponse, job_id: Optional[str]) -> ImageGenerationResponse:
    _GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = job_id or f"img_{int(_utcnow().timestamp())}"
    ext = _image_extension_from_mime(response.mime_type)
    output_path = (_GENERATED_IMAGES_DIR / f"{stem}.{ext}").resolve()
    try:
        output_path.write_bytes(base64.b64decode(response.image_base64))
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist generated image: {e}") from e

    response.output_path = str(output_path)
    if job_id:
        response.download_url = f"/api/v1/images/jobs/{job_id}/file"
        try:
            from PIL import Image
            import io

            thumb_path = (_GENERATED_IMAGES_DIR / f"{stem}_thumb.{ext}").resolve()
            with Image.open(io.BytesIO(base64.b64decode(response.image_base64))) as image:
                image.thumbnail((256, 256))
                image.save(thumb_path, format=(response.mime_type.split("/")[-1] or "png").upper())
            response.thumbnail_path = str(thumb_path)
            response.thumbnail_url = f"/api/v1/images/jobs/{job_id}/thumbnail"
        except Exception as e:
            logger.warning("[ImageGenerateAPI] thumbnail_generation_failed job_id=%s err=%s", job_id, e)
    return response


def _ensure_thumbnail_for_payload(job_id: str, payload: dict) -> Optional[str]:
    thumbnail_path = payload.get("thumbnail_path")
    if thumbnail_path and Path(thumbnail_path).resolve().is_file():
        return thumbnail_path

    output_path = payload.get("output_path")
    mime_type = payload.get("mime_type") or "image/png"
    if not output_path:
        return None

    source = Path(output_path).resolve()
    if not source.is_file():
        return None

    try:
        from PIL import Image

        ext = _image_extension_from_mime(mime_type)
        thumb_path = (_GENERATED_IMAGES_DIR / f"{job_id}_thumb.{ext}").resolve()
        with Image.open(source) as image:
            image.thumbnail((256, 256))
            image.save(thumb_path, format=(mime_type.split("/")[-1] or "png").upper())
        payload["thumbnail_path"] = str(thumb_path)
        payload["thumbnail_url"] = f"/api/v1/images/jobs/{job_id}/thumbnail"
        return str(thumb_path)
    except Exception as e:
        logger.warning("[ImageGenerateAPI] lazy_thumbnail_generation_failed job_id=%s err=%s", job_id, e)
        return None


async def _get_job(job_id: str) -> Optional[_ImageGenerationJob]:
    async with _IMAGE_JOBS_LOCK:
        return _IMAGE_JOBS.get(job_id)


async def _save_job(job: _ImageGenerationJob) -> None:
    async with _IMAGE_JOBS_LOCK:
        _IMAGE_JOBS[job.job_id] = job
    await asyncio.to_thread(_db_upsert_job, job)


async def _patch_job(job_id: str, **updates) -> Optional[_ImageGenerationJob]:
    async with _IMAGE_JOBS_LOCK:
        job = _IMAGE_JOBS.get(job_id)
        if not job:
            return None
        for key, value in updates.items():
            setattr(job, key, value)
    await asyncio.to_thread(_db_upsert_job, job)
    return job


def _job_to_response(job: _ImageGenerationJob, *, include_base64: bool = True) -> ImageGenerationJobResponse:
    result = job.result
    if result is not None and not include_base64:
        payload = result.model_copy(deep=True)
        payload.image_base64 = ""
        result = payload
    return ImageGenerationJobResponse(
        job_id=job.job_id,
        status=job.status,
        model=job.request.model,
        prompt=job.request.prompt,
        phase=job.phase,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        queue_position=job.queue_position,
        current_step=job.current_step,
        total_steps=job.total_steps,
        progress=job.progress,
        result=result,
    )


async def _get_pending_count_for_model(model_id: str) -> int:
    async with _IMAGE_JOBS_LOCK:
        return sum(
            1
            for job in _IMAGE_JOBS.values()
            if job.request.model == model_id and job.status in {ImageGenerationJobStatus.QUEUED, ImageGenerationJobStatus.RUNNING}
        )


async def _get_queued_count_for_model(model_id: str) -> int:
    async with _IMAGE_JOBS_LOCK:
        return sum(
            1
            for job in _IMAGE_JOBS.values()
            if job.request.model == model_id and job.status == ImageGenerationJobStatus.QUEUED
        )


async def _recompute_queue_positions(model_id: str) -> None:
    async with _IMAGE_JOBS_LOCK:
        queued = [
            job for job in _IMAGE_JOBS.values()
            if job.request.model == model_id and job.status == ImageGenerationJobStatus.QUEUED
        ]
        queued.sort(key=lambda item: item.created_at)
        updates = []
        for idx, job in enumerate(queued, start=1):
            if job.queue_position != idx:
                job.queue_position = idx
                updates.append(job)
    for job in updates:
        await asyncio.to_thread(_db_upsert_job, job)


def _row_to_response(
    row: ImageGenerationJobORM,
    *,
    include_result: bool,
    include_base64: bool = True,
) -> ImageGenerationJobResponse:
    payload = _orm_to_job_response(row, include_base64=include_base64)
    if not include_result:
        payload.result = None
    return payload


def _validate_descriptor(request: ImageGenerateRequest) -> ModelDescriptor:
    registry = get_model_registry()
    descriptor = registry.get_model(request.model)
    if not descriptor:
        raise HTTPException(status_code=404, detail=f"Model not found: {request.model}")

    model_type = (getattr(descriptor, "model_type", "") or "").lower()
    if model_type != "image_generation":
        raise HTTPException(
            status_code=400,
            detail=f"Model {request.model} is not an image_generation model (model_type={descriptor.model_type})",
        )

    capabilities = {str(c).lower().strip() for c in (descriptor.capabilities or [])}
    if "text_to_image" not in capabilities:
        raise HTTPException(
            status_code=400,
            detail=f"Model {request.model} does not declare capability text_to_image",
        )

    return descriptor


def _build_runtime_request(
    request: ImageGenerateRequest,
    *,
    progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
) -> RuntimeImageGenerationRequest:
    return RuntimeImageGenerationRequest(
        prompt=request.prompt,
        negative_prompt=request.negative_prompt,
        width=request.width,
        height=request.height,
        num_inference_steps=request.num_inference_steps,
        guidance_scale=request.guidance_scale,
        seed=request.seed,
        image_format=request.image_format,
        progress_callback=progress_callback,
    )


async def _run_generation(
    request: ImageGenerateRequest,
    descriptor: ModelDescriptor,
    *,
    job_id: Optional[str] = None,
) -> ImageGenerationResponse:
    factory = get_runtime_factory()
    queue = get_inference_queue_manager().get_queue(descriptor.id, descriptor.runtime)

    if job_id:
        await _patch_job(job_id, status=ImageGenerationJobStatus.QUEUED, phase="queued")
        await _recompute_queue_positions(descriptor.id)

    await factory.auto_release_unused_local_runtimes(
        keep_model_ids={descriptor.id},
        reason="image_generate_api",
    )

    logger.info(
        "[ImageGenerateAPI] request_start model=%s job_id=%s width=%s height=%s steps=%s guidance=%s seed=%s",
        descriptor.id,
        job_id or "-",
        request.width,
        request.height,
        request.num_inference_steps,
        request.guidance_scale,
        request.seed,
    )

    async def _run_under_queue() -> ImageGenerationResponse:
        # Image generation models have much larger unified-memory footprints than
        # chat runtimes. Before switching to a different image model, proactively
        # unload other cached image-generation runtimes to avoid MPS OOM on load.
        await _force_release_other_image_generation_runtimes(
            factory,
            keep_model_id=descriptor.id,
            reason="before_image_runtime_load",
        )
        runtime = factory.create_image_generation_runtime(descriptor)
        async with factory.model_usage(descriptor.id):
            async def _progress_callback(current_step: int, total_steps: int) -> None:
                if not job_id:
                    return
                progress = round((current_step / total_steps) * 100, 2) if total_steps > 0 else None
                await _patch_job(
                    job_id,
                    current_step=current_step,
                    total_steps=total_steps,
                    progress=progress,
                    phase="generating",
                )

            if job_id:
                await _patch_job(
                    job_id,
                    status=ImageGenerationJobStatus.RUNNING,
                    phase="preparing_runtime",
                    started_at=_utcnow(),
                    queue_position=None,
                )
                await _recompute_queue_positions(descriptor.id)
            if job_id:
                await _patch_job(job_id, phase="loading_runtime")
            try:
                if not await runtime.is_loaded():
                    logger.info("[ImageGenerateAPI] runtime_load_start model=%s job_id=%s", descriptor.id, job_id or "-")
                    await runtime.load()
                    logger.info("[ImageGenerateAPI] runtime_load_done model=%s job_id=%s", descriptor.id, job_id or "-")

                if job_id:
                    await _patch_job(job_id, phase="generating")
                response = await runtime.generate(_build_runtime_request(request, progress_callback=_progress_callback))
            except Exception as exc:
                if not _is_mps_oom_error(exc):
                    raise
                logger.warning(
                    "[ImageGenerateAPI] mps_oom_retry model=%s job_id=%s err=%s",
                    descriptor.id,
                    job_id or "-",
                    exc,
                )
                await factory.unload_image_generation_runtime(descriptor.id)
                await _force_release_other_image_generation_runtimes(
                    factory,
                    reason="mps_oom_retry",
                )
                runtime = factory.create_image_generation_runtime(descriptor)
                if job_id:
                    await _patch_job(job_id, phase="loading_runtime")
                logger.info("[ImageGenerateAPI] runtime_load_retry_start model=%s job_id=%s", descriptor.id, job_id or "-")
                await runtime.load()
                logger.info("[ImageGenerateAPI] runtime_load_retry_done model=%s job_id=%s", descriptor.id, job_id or "-")
                if job_id:
                    await _patch_job(job_id, phase="generating")
                response = await runtime.generate(_build_runtime_request(request, progress_callback=_progress_callback))

            response = _persist_image_result(response, job_id)
            logger.info(
                "[ImageGenerateAPI] request_done model=%s job_id=%s latency_ms=%s output=%sx%s",
                descriptor.id,
                job_id or "-",
                response.latency_ms,
                response.width,
                response.height,
            )
            return response

    return await queue.run(_run_under_queue())


async def _run_generation_job(job_id: str) -> None:
    job = await _get_job(job_id)
    if not job:
        return

    descriptor = _validate_descriptor(job.request)
    try:
        if job.cancelled:
            await _patch_job(
                job_id,
                status=ImageGenerationJobStatus.CANCELLED,
                phase="cancelled",
                finished_at=_utcnow(),
                error="Image generation job cancelled before start",
            )
            return
        response = await _run_generation(job.request, descriptor, job_id=job_id)
        job = await _get_job(job_id)
        if job and job.cancelled:
            await _patch_job(
                job_id,
                status=ImageGenerationJobStatus.CANCELLED,
                phase="cancelled",
                finished_at=_utcnow(),
                result=response,
                error="Image generation job cancelled",
            )
            return
        await _patch_job(
            job_id,
            status=ImageGenerationJobStatus.SUCCEEDED,
            phase="completed",
            finished_at=_utcnow(),
            current_step=job.request.num_inference_steps,
            total_steps=job.request.num_inference_steps,
            progress=100.0,
            result=response,
        )
    except asyncio.CancelledError:
        logger.info("[ImageGenerateAPI] job_cancelled job_id=%s", job_id)
        await _patch_job(
            job_id,
            status=ImageGenerationJobStatus.CANCELLED,
            phase="cancelled",
            finished_at=_utcnow(),
            error="Image generation job cancelled",
        )
    except HTTPException as e:
        logger.warning("[ImageGenerateAPI] job_failed job_id=%s status=%s detail=%s", job_id, e.status_code, e.detail)
        await _patch_job(
            job_id,
            status=ImageGenerationJobStatus.FAILED,
            phase="failed",
            finished_at=_utcnow(),
            error=str(e.detail),
        )
    except Exception as e:
        current = await _get_job(job_id)
        if current and current.cancelled:
            logger.info("[ImageGenerateAPI] job_cancelled_after_runtime_signal job_id=%s", job_id)
            await _patch_job(
                job_id,
                status=ImageGenerationJobStatus.CANCELLED,
                phase="cancelled",
                finished_at=_utcnow(),
                error="Image generation job cancelled",
            )
            return
        logger.exception("[ImageGenerateAPI] job_failed job_id=%s", job_id)
        await _patch_job(
            job_id,
            status=ImageGenerationJobStatus.FAILED,
            phase="failed",
            finished_at=_utcnow(),
            error=str(e),
        )
    finally:
        await _recompute_queue_positions(descriptor.id)


@router.post(
    "/api/v1/images/generate",
    response_model=ImageGenerationResponse | ImageGenerationJobResponse,
)
async def generate_image(
    request: ImageGenerateRequest,
    wait: bool = Query(default=True, description="true=同步等待结果；false=创建异步任务并返回 job"),
):
    descriptor = _validate_descriptor(request)

    if wait:
        try:
            return await _run_generation(request, descriptor)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Image generation failed for model=%s", descriptor.id)
            raise HTTPException(status_code=500, detail=str(e))

    pending_limit = max(1, int(getattr(settings, "image_generation_max_pending_jobs_per_model", 4)))
    pending_count = await _get_pending_count_for_model(descriptor.id)
    if pending_count >= pending_limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"IMAGE_GENERATION_QUEUE_FULL: model={descriptor.id} "
                f"pending={pending_count} limit={pending_limit}"
            ),
        )

    job_id = str(uuid4())
    queued_count = await _get_queued_count_for_model(descriptor.id)
    job = _ImageGenerationJob(
        job_id=job_id,
        request=_clone_request(request),
        status=ImageGenerationJobStatus.QUEUED,
        created_at=_utcnow(),
        phase="queued",
        queue_position=queued_count + 1,
    )
    await _save_job(job)
    task = asyncio.create_task(_run_generation_job(job_id))
    await _patch_job(job_id, task=task)
    logger.info("[ImageGenerateAPI] job_created job_id=%s model=%s", job_id, descriptor.id)
    saved = await _get_job(job_id)
    return _job_to_response(saved)


@router.get("/api/v1/images/jobs/{job_id}", response_model=ImageGenerationJobResponse)
async def get_image_generation_job(job_id: str):
    job = await _get_job(job_id)
    if job:
        return _job_to_response(job, include_base64=False)
    db: Session = SessionLocal()
    try:
        row = db.get(ImageGenerationJobORM, job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Image generation job not found: {job_id}")
        return _orm_to_job_response(row, include_base64=False)
    finally:
        db.close()


@router.get("/api/v1/images/jobs", response_model=ImageGenerationJobListResponse)
async def list_image_generation_jobs(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    model: str | None = Query(default=None),
    q: str | None = Query(default=None, description="search prompt"),
    sort: str = Query(default="created_at_desc", description="created_at_desc|created_at_asc"),
    include_result: bool = Query(default=False),
):
    normalized_status = (status or "").strip().lower()
    normalized_model = (model or "").strip()
    normalized_q = (q or "").strip()
    normalized_sort = (sort or "created_at_desc").strip().lower()
    db: Session = SessionLocal()
    try:
        query = db.query(ImageGenerationJobORM)
        if normalized_status:
            query = query.filter(ImageGenerationJobORM.status == normalized_status)
        if normalized_model:
            query = query.filter(ImageGenerationJobORM.model == normalized_model)
        if normalized_q:
            query = query.filter(ImageGenerationJobORM.prompt.ilike(f"%{normalized_q}%"))
        if normalized_sort == "created_at_asc":
            order_by = ImageGenerationJobORM.created_at.asc()
        else:
            order_by = ImageGenerationJobORM.created_at.desc()
        total = query.count()
        rows = query.order_by(order_by).offset(offset).limit(limit).all()
        items = [_row_to_response(row, include_result=include_result, include_base64=False) for row in rows]
        return ImageGenerationJobListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            has_next=(offset + len(items)) < total,
        )
    finally:
        db.close()


@router.delete("/api/v1/images/jobs/{job_id}")
async def delete_image_generation_job(job_id: str):
    async with _IMAGE_JOBS_LOCK:
        job = _IMAGE_JOBS.get(job_id)
        model_id = job.request.model if job else None
        if job and job.status in {ImageGenerationJobStatus.QUEUED, ImageGenerationJobStatus.RUNNING}:
            raise HTTPException(status_code=409, detail="Cannot delete a running image generation job")
        removed = _IMAGE_JOBS.pop(job_id, None)

    db: Session = SessionLocal()
    try:
        row = db.get(ImageGenerationJobORM, job_id)
        if removed is None and row is None:
            raise HTTPException(status_code=404, detail=f"Image generation job not found: {job_id}")
        if row is not None and row.status in {ImageGenerationJobStatus.QUEUED.value, ImageGenerationJobStatus.RUNNING.value}:
            raise HTTPException(status_code=409, detail="Cannot delete a running image generation job")
    finally:
        db.close()

    output_path = removed.result.output_path if removed and removed.result else (row.result_json or {}).get("output_path") if row and row.result_json else None
    thumbnail_path = removed.result.thumbnail_path if removed and removed.result else (row.result_json or {}).get("thumbnail_path") if row and row.result_json else None
    for candidate_path, label in ((output_path, "image"), (thumbnail_path, "thumbnail")):
        if not candidate_path:
            continue
        try:
            path_obj = Path(candidate_path).resolve()
            if path_obj.is_file():
                path_obj.unlink()
        except Exception:
            logger.warning(
                "[ImageGenerateAPI] Failed to delete generated %s for job_id=%s path=%s",
                label,
                job_id,
                candidate_path,
            )

    await asyncio.to_thread(_db_delete_job, job_id)
    if model_id:
        await _recompute_queue_positions(model_id)
    logger.info("[ImageGenerateAPI] job_deleted job_id=%s", job_id)
    return {"ok": True, "job_id": job_id}


@router.post("/api/v1/images/jobs/{job_id}/cancel", response_model=ImageGenerationJobResponse)
async def cancel_image_generation_job(job_id: str):
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Image generation job not found: {job_id}")
    if job.status in {ImageGenerationJobStatus.SUCCEEDED, ImageGenerationJobStatus.FAILED, ImageGenerationJobStatus.CANCELLED}:
        return _job_to_response(job)

    descriptor = _validate_descriptor(job.request)
    runtime = get_runtime_factory().create_image_generation_runtime(descriptor)
    cancelled_runtime = False
    cancel_fn = getattr(runtime, "cancel", None)
    if callable(cancel_fn):
        cancelled_runtime = bool(await cancel_fn())

    await _patch_job(job_id, cancelled=True, phase="cancel_requested")
    if job.status == ImageGenerationJobStatus.QUEUED and job.task and not job.task.done():
        job.task.cancel()
        await _recompute_queue_positions(descriptor.id)

    logger.info(
        "[ImageGenerateAPI] job_cancel_requested job_id=%s model=%s runtime_cancelled=%s",
        job_id,
        descriptor.id,
        cancelled_runtime,
    )
    saved = await _get_job(job_id)
    return _job_to_response(saved)


@router.get("/api/v1/images/jobs/{job_id}/file")
async def download_image_generation_job_file(job_id: str):
    job = await _get_job(job_id)
    output_path_str = job.result.output_path if job and job.result else None
    mime_type = job.result.mime_type if job and job.result else None
    if not output_path_str:
        db: Session = SessionLocal()
        try:
            row = db.get(ImageGenerationJobORM, job_id)
            if not row or not row.result_json:
                raise HTTPException(status_code=404, detail=f"Generated image file not found for job: {job_id}")
            output_path_str = row.result_json.get("output_path")
            mime_type = row.result_json.get("mime_type") or mime_type
        finally:
            db.close()
    if not output_path_str:
        raise HTTPException(status_code=404, detail=f"Generated image file not found for job: {job_id}")

    output_path = Path(output_path_str).resolve()
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail=f"Generated image file not found: {output_path}")

    return FileResponse(str(output_path), media_type=mime_type or "image/png", filename=output_path.name)


@router.get("/api/v1/images/jobs/{job_id}/thumbnail")
async def download_image_generation_job_thumbnail(job_id: str):
    job = await _get_job(job_id)
    thumb_path = job.result.thumbnail_path if job and job.result else None
    mime_type = job.result.mime_type if job and job.result else None
    if not thumb_path and job and job.result:
        payload = job.result.model_dump(mode="json")
        thumb_path = _ensure_thumbnail_for_payload(job_id, payload)
        if thumb_path:
            updated_result = ImageGenerationResponse.model_validate(payload)
            await _patch_job(job_id, result=updated_result)
            mime_type = updated_result.mime_type or mime_type
    if not thumb_path:
        db: Session = SessionLocal()
        try:
            row = db.get(ImageGenerationJobORM, job_id)
            if not row or not row.result_json:
                raise HTTPException(status_code=404, detail=f"Generated thumbnail not found for job: {job_id}")
            payload = dict(row.result_json)
            thumb_path = _ensure_thumbnail_for_payload(job_id, payload)
            mime_type = payload.get("mime_type") or mime_type
            if thumb_path and payload != row.result_json:
                row.result_json = payload
                db.commit()
        finally:
            db.close()
    if not thumb_path:
        raise HTTPException(status_code=404, detail=f"Generated thumbnail not found for job: {job_id}")

    path = Path(thumb_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Generated thumbnail file not found: {path}")
    return FileResponse(str(path), media_type=mime_type or "image/png", filename=path.name)


@router.get("/api/v1/images/warmup/latest", response_model=ImageGenerationWarmupResponse)
async def get_latest_image_generation_warmup(model: str | None = Query(default=None)):
    row = await asyncio.to_thread(_db_get_latest_warmup, model.strip() if model else None)
    if row is None:
        raise HTTPException(status_code=404, detail="No warmup record found")
    return _orm_to_warmup_response(row)


@router.post("/api/v1/images/warmup")
async def warmup_image_generation_runtime(request: ImageWarmupRequest):
    image_request = ImageGenerateRequest(
        model=request.model,
        prompt=request.prompt,
        width=request.width,
        height=request.height,
        num_inference_steps=request.num_inference_steps,
        guidance_scale=request.guidance_scale,
        seed=request.seed,
        image_format="PNG",
    )
    descriptor = _validate_descriptor(image_request)
    started_at = time_started = _utcnow()
    warmup_id = str(uuid4())
    try:
        response = await _run_generation(image_request, descriptor, job_id=None)
        elapsed_ms = int((_utcnow() - time_started).total_seconds() * 1000)
        finished_at = _utcnow()
        await asyncio.to_thread(
            _db_create_warmup,
            warmup_id=warmup_id,
            model=descriptor.id,
            prompt=request.prompt,
            request_json=request.model_dump(mode="json"),
            started_at=started_at,
            finished_at=finished_at,
            elapsed_ms=elapsed_ms,
            output_path=response.output_path,
            width=response.width,
            height=response.height,
            result_json=response.model_dump(mode="json"),
        )
    except Exception as e:
        finished_at = _utcnow()
        elapsed_ms = int((finished_at - time_started).total_seconds() * 1000)
        await asyncio.to_thread(
            _db_create_warmup,
            warmup_id=warmup_id,
            model=descriptor.id,
            prompt=request.prompt,
            request_json=request.model_dump(mode="json"),
            started_at=started_at,
            finished_at=finished_at,
            elapsed_ms=elapsed_ms,
            output_path=None,
            width=request.width,
            height=request.height,
            result_json=None,
            status="failed",
            error=str(e),
        )
        raise
    logger.info(
        "[ImageGenerateAPI] warmup_done model=%s elapsed_ms=%s output=%sx%s",
        descriptor.id,
        elapsed_ms,
        response.width,
        response.height,
    )
    return {
        "ok": True,
        "warmup_id": warmup_id,
        "model": descriptor.id,
        "started_at": started_at,
        "elapsed_ms": elapsed_ms,
        "output_path": response.output_path,
        "width": response.width,
        "height": response.height,
    }
