"""
本地 AI 推理平台 - FastAPI 主入口
"""
import sys
from pathlib import Path
from typing import Optional
import atexit
import signal
from datetime import datetime, timedelta, timezone

# 添加后端目录到 Python 路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# 尽早加载 .env：先加载 backend/.env，再加载项目根 .env，确保 TOOL_NET_WEB_ENABLED 等生效
try:
    from dotenv import load_dotenv
    load_dotenv(backend_dir / ".env")
    load_dotenv(backend_dir.parent / ".env")
except ImportError:
    pass

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
import asyncio

from log import logger
from config.settings import settings
from api.chat import router as chat_router
from api.memory import router as memory_router
from api.sessions import router as sessions_router
from api.system import router as system_router
from api.knowledge import router as knowledge_router
from api.rag_trace import router as rag_trace_router
from api.agents import router as agents_router, session_router as agent_sessions_router
from api.tools import router as tools_router
from api.skills import router as skills_router
from api.vlm import router as vlm_router
from api.asr import router as asr_router
from api.images import router as images_router
from api.backup import router as backup_router
from api.model_backups import router as model_backups_router
from api.events import router as events_router
from api.workflows import router as workflows_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.version}...")
    logger.info(f"Log files will be kept for 30 days in logs/ directory")
    _web_enabled = getattr(settings, "tool_net_web_enabled", True)
    logger.info(f"tool_net_web_enabled={_web_enabled} (web.search: True=real, False=disabled)")
    if not _web_enabled:
        logger.warning("Web search is DISABLED. Set TOOL_NET_WEB_ENABLED=true (or remove from .env) and restart for real search.")
    
    # 初始化数据库表（确保ORM表存在）
    try:
        from core.data.base import Base, get_engine
        from core.data.models import (
            SystemSetting,
            Model,
            ModelConfig,
            Agent,
            Skill,
            AgentSession,
            AgentTrace,
            ImageGenerationJobORM,
            ImageGenerationWarmupORM,
        )
        from sqlalchemy import text
        engine = get_engine()
        Base.metadata.create_all(engine)

        # Workflow schema 兼容迁移（SQLite）：为旧表补齐新增列
        with engine.connect() as conn:
            # workflow_executions 新增队列观测列
            cols = {
                str(row[1])
                for row in conn.execute(text("PRAGMA table_info(workflow_executions)")).fetchall()
            }
            if "queue_position" not in cols:
                conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN queue_position INTEGER"))
            if "queued_at" not in cols:
                conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN queued_at DATETIME"))
            if "wait_duration_ms" not in cols:
                conn.execute(text("ALTER TABLE workflow_executions ADD COLUMN wait_duration_ms INTEGER"))
            conn.commit()

        logger.info("Database tables initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}", exc_info=True)
        # 不阻止启动，但记录错误

    # 启动兜底：清理长时间卡在 running 的旧会话，避免异常退出后残留“假运行中”
    try:
        from core.data.base import db_session
        from core.data.models.session import AgentSession as AgentSessionORM

        stale_seconds = max(60, int(getattr(settings, "agent_stale_running_session_seconds", 1800)))
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        with db_session(retry_count=3, retry_delay=0.1) as db:
            stmt = (
                AgentSessionORM.__table__.update()
                .where(
                    AgentSessionORM.status == "running",
                    AgentSessionORM.updated_at < cutoff,
                )
                .values(
                    status="error",
                    error_message="Recovered on startup: stale running session",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = db.execute(stmt)
            recovered = int(getattr(result, "rowcount", 0) or 0)
        if recovered > 0:
            logger.warning(
                f"[Startup] Recovered {recovered} stale running agent session(s) "
                f"(threshold={stale_seconds}s)"
            )
        else:
            logger.info(f"[Startup] No stale running agent sessions (threshold={stale_seconds}s)")
    except Exception as e:
        logger.warning(f"[Startup] Failed to recover stale running sessions: {e}")

    # 启动兜底：将上次异常退出残留的图片任务状态回收，避免 UI 显示假 running/queued
    try:
        from core.data.base import db_session
        from core.data.models.image_generation import ImageGenerationJobORM

        with db_session(retry_count=3, retry_delay=0.1) as db:
            stmt = (
                ImageGenerationJobORM.__table__.update()
                .where(ImageGenerationJobORM.status.in_(["queued", "running"]))
                .values(
                    status="failed",
                    phase="recovered_on_startup",
                    error="Recovered on startup: stale queued/running image generation job",
                    finished_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = db.execute(stmt)
            recovered_image_jobs = int(getattr(result, "rowcount", 0) or 0)
        if recovered_image_jobs > 0:
            logger.warning(f"[Startup] Recovered {recovered_image_jobs} stale image generation job(s)")
        else:
            logger.info("[Startup] No stale image generation jobs")
    except Exception as e:
        logger.warning(f"[Startup] Failed to recover stale image generation jobs: {e}")

    # model.json 定时全量快照（阶段 2）：若启用则后台循环在配置的 UTC 时间执行
    if getattr(settings, "model_json_backup_daily_enabled", False):
        try:
            from core.backup.model_json.scheduler import run_daily_snapshot_loop
            asyncio.create_task(run_daily_snapshot_loop())
        except Exception as e:
            logger.warning(f"[Startup] Model.json daily snapshot scheduler not started: {e}")
    
    async def _shutdown_cleanup_async() -> int:
        """
        Cleanup loaded resources on graceful shutdown.

        IMPORTANT:
        - Run in the lifespan teardown (async) to avoid deadlocks.
        - Do NOT block inside signal handlers.
        """
        logger.info("[Shutdown] Performing cleanup of loaded models...")
        unloaded_count = 0
        try:
            # Import here to avoid circular imports
            from core.models.registry import get_model_registry
            from core.runtimes.factory import get_runtime_factory

            registry = get_model_registry()
            factory = get_runtime_factory()

            all_models = registry.list_models()
            for model_descriptor in all_models:
                try:
                    # Perception 模型由 unload_perception_runtimes 统一处理，跳过
                    if getattr(model_descriptor, "model_type", "").lower() == "perception":
                        continue
                    runtime = factory.get_runtime(model_descriptor.runtime)
                    if await runtime.is_loaded(model_descriptor):
                        logger.info(f"[Shutdown] Unloading model: {model_descriptor.id}")
                        ok = await runtime.unload(model_descriptor)
                        if ok:
                            unloaded_count += 1
                            logger.info(f"[Shutdown] Successfully unloaded: {model_descriptor.id}")
                        else:
                            logger.warning(f"[Shutdown] Failed to unload: {model_descriptor.id}")
                except Exception as e:
                    logger.error(f"[Shutdown] Error unloading {model_descriptor.id}: {e}")
                    continue

            # Also release cached embedding runtimes (best-effort)
            try:
                n_embed = factory.close_embedding_runtimes()
                if n_embed:
                    logger.info(f"[Shutdown] Closed {n_embed} embedding runtime(s)")
            except Exception as e:
                logger.warning(f"[Shutdown] Failed to close embedding runtimes: {e}")

            # Also unload cached VLM runtimes (best-effort)
            try:
                n_vlm = await factory.unload_vlm_runtimes()
                if n_vlm:
                    logger.info(f"[Shutdown] Unloaded {n_vlm} VLM runtime(s)")
            except Exception as e:
                logger.warning(f"[Shutdown] Failed to unload VLM runtimes: {e}")

            # Also unload cached ASR runtimes (best-effort)
            try:
                n_asr = await factory.unload_asr_runtimes()
                if n_asr:
                    logger.info(f"[Shutdown] Unloaded {n_asr} ASR runtime(s)")
            except Exception as e:
                logger.warning(f"[Shutdown] Failed to unload ASR runtimes: {e}")

            # Also unload cached perception runtimes (best-effort)
            try:
                n_perception = await factory.unload_perception_runtimes()
                if n_perception:
                    logger.info(f"[Shutdown] Unloaded {n_perception} perception runtime(s)")
            except Exception as e:
                logger.warning(f"[Shutdown] Failed to unload perception runtimes: {e}")
        except Exception as e:
            logger.error(f"[Shutdown] Cleanup failed: {e}")
        logger.info(f"[Shutdown] Cleanup complete. Unloaded {unloaded_count} models.")
        return unloaded_count

    # atexit 作为兜底：进程被正常退出且 lifespan teardown 未执行时尽量清理（不保证所有场景）
    def cleanup_handler_sync():
        try:
            asyncio.run(_shutdown_cleanup_async())
        except Exception as e:
            logger.error(f"[Shutdown] atexit cleanup failed: {e}")

    atexit.register(cleanup_handler_sync)

    # 注册 SIGINT/SIGTERM/SIGHUP：仅记录并委托给原处理器，避免在请求中直接抛 KeyboardInterrupt 导致 500
    _prev_signal_handlers = {}

    def _exit_request_handler(signum, frame):
        try:
            sig_name = signal.Signals(signum).name
        except Exception:
            sig_name = str(signum)
        logger.info(f"[Shutdown] Received signal {sig_name} ({signum}); delegating to previous signal handler.")

        prev = _prev_signal_handlers.get(signum)
        # 委托给 uvicorn/系统原 handler；不要在这里直接 raise KeyboardInterrupt
        if callable(prev):
            prev(signum, frame)
            return
        if prev == signal.SIG_IGN:
            return
        # SIG_DFL/未知：回退为中断异常（极少发生，保底行为）
        raise KeyboardInterrupt

    try:
        for _sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            _prev_signal_handlers[_sig] = signal.getsignal(_sig)
            signal.signal(_sig, _exit_request_handler)
    except Exception:
        # Windows/某些环境可能没有 SIGHUP
        pass
    
    # 扫描并注册模型
    from core.models.scanner.ollama import OllamaScanner
    from core.models.scanner.lmstudio import LMStudioScanner
    from core.models.scanner.local import LocalScanner
    from core.models.descriptor import ModelDescriptor
    from core.models.registry import get_model_registry
    from core.plugins.registry import get_plugin_registry
    
    registry = get_model_registry()
    plugin_registry = get_plugin_registry()
    
    # 初始化并加载内置插件
    try:
        from api.chat import memory_store
        await plugin_registry.load_builtin_plugins(
            logger=logger,
            memory=memory_store,
            model_registry=registry
        )
        logger.info(f"[Main] Loaded {len(plugin_registry.list())} plugins")
        
        # 注册内置 Tools
        from core.plugins.builtin.tools import bootstrap_tools
        bootstrap_tools()
        logger.info("[Main] Registered built-in tools")

        from core.skills.registry import SkillRegistry
        from core.skills.service import bootstrap_builtin_skills
        from core.skills.discovery import get_discovery_engine
        SkillRegistry.load()
        logger.info("[Main] Loaded Skill registry")
        n_builtin = bootstrap_builtin_skills()
        if n_builtin:
            logger.info(f"[Main] Registered {n_builtin} built-in skills from tools")
        # Skill 语义发现：绑定 Registry 并构建向量索引（供运行时 use_skill_discovery 使用）
        try:
            engine = get_discovery_engine()
            engine.bind_registry(SkillRegistry)
            n_indexed = engine.build_index()
            logger.info(f"[Main] Skill discovery index built ({n_indexed} skills)")
        except Exception as e:
            logger.warning(f"[Main] Skill discovery index build failed: {e}")
    except Exception as e:
        logger.error(f"Plugin initialization failed: {e}")

    try:
        ollama_scanner = OllamaScanner()
        await ollama_scanner.scan()
    except Exception as e:
        logger.error(f"Ollama scan failed: {e}")
        
    try:
        lmstudio_scanner = LMStudioScanner()
        await lmstudio_scanner.scan()
    except Exception as e:
        logger.debug(f"LM Studio scan failed: {e}")

    try:
        local_scanner = LocalScanner()
        await local_scanner.scan()
    except Exception as e:
        logger.error(f"Local model scan failed: {e}")
    
    try:
        yield
    finally:
        # graceful shutdown path
        await _shutdown_cleanup_async()

# 创建应用
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="本地 AI 推理网关",
    lifespan=lifespan
)

# 用户上下文中间件（必须在 CORS 之前）
from middleware.user_context import UserContextMiddleware
app.add_middleware(UserContextMiddleware)

# CORS 中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],  # 允许前端读取自定义会话 ID
)

# 包含路由
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(sessions_router)
app.include_router(system_router)
app.include_router(knowledge_router)
app.include_router(rag_trace_router)
app.include_router(agents_router)
app.include_router(agent_sessions_router)
app.include_router(tools_router)
app.include_router(skills_router)
app.include_router(vlm_router)
app.include_router(asr_router)
app.include_router(images_router)
app.include_router(backup_router)
app.include_router(model_backups_router)
app.include_router(events_router)
app.include_router(workflows_router)


@app.get("/")
async def root():
    """根端点"""
    return {
        "message": "Welcome to OpenVitamin大模型与智能体应用平台",
        "version": settings.version,
    }


@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": settings.version,
    }


class CreateModelRequest(BaseModel):
    id: str
    name: str
    provider: str
    provider_model_id: str
    runtime: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    description: Optional[str] = None

@app.post("/api/models")
async def register_model(req: CreateModelRequest):
    """手动注册模型（如云端 OpenAI, DeepSeek 等）"""
    from core.models.registry import get_model_registry
    from core.models.descriptor import ModelDescriptor
    
    reg = get_model_registry()
    
    descriptor = ModelDescriptor(
        id=req.id,
        name=req.name,
        provider=req.provider,
        provider_model_id=req.provider_model_id,
        runtime=req.runtime,
        base_url=req.base_url,
        metadata={"api_key": req.api_key} if req.api_key else {},
        description=req.description,
        source="Cloud API",
        family=req.provider
    )
    
    reg.upsert_model(descriptor)
    return {"success": True, "id": descriptor.id}

@app.get("/api/models")
async def list_models(model_type: str = None):
    """列出可用模型"""
    from core.agents.router import get_router
    from core.runtimes.factory import get_runtime_factory
    from core.models.registry import get_model_registry
    
    router = get_router()
    models = await router.list_models(model_type=model_type)
    factory = get_runtime_factory()
    reg = get_model_registry()
    
    # 注入实时状态
    for m in models:
        m["status"] = "detached"
        desc = reg.get_model(m["id"])
        if desc:
            model_type = getattr(desc, "model_type", "").lower()
            if model_type == "perception":
                if factory.is_perception_loaded(desc.id):
                    m["status"] = "active"
            elif model_type == "image_generation":
                if factory.is_image_generation_loaded(desc.id):
                    m["status"] = "active"
            else:
                runtime = factory.get_runtime(desc.runtime)
                if await runtime.is_loaded(desc):
                    m["status"] = "active"
                    # 如果是 llama.cpp 并且在缓存中，我们可以标记 device
                    if desc.runtime == "llama.cpp":
                        m["device"] = "GPU:0" # 暂时硬编码为 GPU:0，未来可从 runtime 获取
            
    return {
        "object": "list",
        "data": models,
    }


@app.post("/api/models/scan")
async def scan_models():
    """手动扫描模型，同步本地模型状态（移除磁盘上已不存在的本地模型）"""
    from core.models.scanner.ollama import OllamaScanner
    from core.models.scanner.lmstudio import LMStudioScanner
    from core.models.scanner.local import LocalScanner
    from core.models.registry import get_model_registry
    from core.runtimes.factory import get_runtime_factory
    
    results = {"ollama": 0, "lmstudio": 0, "local": 0, "removed": 0}
    
    try:
        ollama_scanner = OllamaScanner()
        models = await ollama_scanner.scan()
        results["ollama"] = len(models)
    except Exception as e:
        logger.error(f"Ollama scan failed: {e}")
        
    try:
        lmstudio_scanner = LMStudioScanner()
        models = await lmstudio_scanner.scan()
        results["lmstudio"] = len(models)
    except Exception as e:
        logger.debug(f"LM Studio scan failed: {e}")

    try:
        local_scanner = LocalScanner()
        models = await local_scanner.scan()
        results["local"] = len(models)
        
        # 同步本地模型：移除磁盘上已不存在的本地模型
        reg = get_model_registry()
        factory = get_runtime_factory()
        scanned_ids = {d.id for d in models}
        existing_local = reg.list_models(provider="local")
        for desc in existing_local:
            if desc.id not in scanned_ids:
                try:
                    model_type = getattr(desc, "model_type", "").lower()
                    if model_type == "perception":
                        factory.unload_perception_runtime(desc.id)
                    elif model_type == "image_generation":
                        await factory.unload_image_generation_runtime(desc.id)
                    else:
                        try:
                            runtime = factory.get_runtime(desc.runtime)
                            if await runtime.is_loaded(desc):
                                await runtime.unload(desc)
                        except Exception:
                            pass
                    reg.delete_model(desc.id)
                    results["removed"] += 1
                    logger.info(f"[Scan] Removed outdated local model: {desc.id}")
                except Exception as e:
                    logger.warning(f"[Scan] Failed to remove {desc.id}: {e}")
    except Exception as e:
        logger.error(f"Local model scan failed: {e}")
        
    return {"success": True, "results": results}


@app.post("/api/models/{model_id}/load")
async def load_model(model_id: str):
    """手动加载模型"""
    from core.models.registry import get_model_registry
    from core.runtimes.factory import get_runtime_factory
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": "Model not found"}, 404
        
    factory = get_runtime_factory()
    
    # Perception 模型：通过 Factory 创建并缓存 runtime
    model_type = getattr(desc, "model_type", "").lower()
    if model_type == "perception":
        try:
            factory.create_perception_runtime(desc)
            success = True
        except Exception as e:
            logger.exception("Failed to load perception model")
            return {"error": str(e)}, 500
    elif model_type == "image_generation":
        try:
            runtime = factory.create_image_generation_runtime(desc)
            success = await runtime.load()
        except Exception as e:
            logger.exception("Failed to load image generation model")
            return {"error": str(e)}, 500
    else:
        runtime = factory.get_runtime(desc.runtime)
        success = await runtime.load(desc)
    
    res = {"success": success, "status": "active" if success else "detached"}
    if success and desc.runtime == "llama.cpp":
        res["device"] = "GPU:0"
    
    return res


@app.post("/api/models/{model_id}/unload")
async def unload_model(model_id: str):
    """手动卸载模型"""
    from core.models.registry import get_model_registry
    from core.runtimes.factory import get_runtime_factory
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": "Model not found"}, 404
        
    factory = get_runtime_factory()
    success = await factory.unload_model(desc.id)
    return {"success": success, "status": "detached"}


@app.get("/api/models/{model_id}/safety_check")
async def model_safety_check(model_id: str):
    """检查模型加载的 VRAM 安全性"""
    from core.models.registry import get_model_registry
    from api.system import get_gpu_metrics
    import re
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": "Model not found"}, 404
        
    # 获取当前 GPU 状态
    gpu = get_gpu_metrics()
    vram_total = gpu["vram_total"]
    vram_used = gpu["vram_used"]
    vram_available = max(0, vram_total - vram_used)
    
    # 估算模型所需 VRAM
    # 基础: 模型文件大小
    size_gb = 0
    if desc.size:
        match = re.search(r"(\d+(\.\d+)?)\s*(GB|MB)", desc.size)
        if match:
            val = float(match.group(1))
            unit = match.group(3)
            size_gb = val if unit == "GB" else val / 1024
            
    # 上下文开销 (估算: 8k 约 0.5GB, 32k 约 2GB)
    ctx_kb = desc.context_length or 4096
    ctx_overhead_gb = (ctx_kb / 1024 / 8) * 0.5 
    
    estimated_total_gb = size_gb + ctx_overhead_gb
    
    # 安全检查
    is_safe = vram_available > estimated_total_gb
    
    # 如果是 Ollama，可能已经加载了，或者 Ollama 会自动调度
    if desc.provider == "ollama":
        # Ollama 比较智能，通常不需要严格限制，但给个提示
        return {
            "is_safe": True,
            "estimated_vram_gb": round(estimated_total_gb, 2),
            "available_vram_gb": round(vram_available, 2),
            "message": "Ollama handles memory management automatically.",
            "warning": None if vram_available > size_gb else "Ollama may use system RAM if VRAM is low."
        }
        
    warning = None
    if not is_safe:
        if vram_available + 2 > estimated_total_gb: # 差点点
            warning = f"VRAM is tight ({round(vram_available, 1)}GB available). The model might be slow or fail to load."
        else:
            warning = f"Insufficient VRAM! Estimated {round(estimated_total_gb, 1)}GB required, but only {round(vram_available, 1)}GB available."
            
    return {
        "is_safe": is_safe,
        "estimated_vram_gb": round(estimated_total_gb, 2),
        "available_vram_gb": round(vram_available, 2),
        "message": "Safe to load" if is_safe else "Low VRAM warning",
        "warning": warning
    }


@app.patch("/api/models/{model_id}")
async def update_model(model_id: str, data: dict):
    """更新模型元数据/配置"""
    from core.models.registry import get_model_registry
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": "Model not found"}, 404
        
    # 更新字段
    if "name" in data:
        desc.name = data["name"]
    if "provider_model_id" in data:
        desc.provider_model_id = data["provider_model_id"]
    if "context_length" in data:
        desc.context_length = data["context_length"]
    if "description" in data:
        desc.description = data["description"]
    if "base_url" in data:
        desc.base_url = data["base_url"]
    if "metadata" in data:
        desc.metadata.update(data["metadata"])
        
    reg.upsert_model(desc)
    return {"success": True, "data": desc.model_dump()}


@app.get("/api/models/{model_id}/chat-params")
async def get_model_chat_params(model_id: str):
    """获取模型的聊天参数"""
    from core.models.registry import get_model_registry
    reg = get_model_registry()
    params = reg.get_model_chat_params(model_id)
    return {"success": True, "data": params}


@app.post("/api/models/{model_id}/chat-params")
async def save_model_chat_params(model_id: str, data: dict):
    """保存模型的聊天参数"""
    from core.models.registry import get_model_registry
    logger.info(f"Updating chat parameters for model {model_id}: {data}")
    reg = get_model_registry()
    reg.save_model_chat_params(model_id, data)
    return {"success": True}


@app.get("/api/models/{model_id}/browse")
async def browse_model_dir(model_id: str, dir: str = ""):
    """列出目录内容，用于模型路径选择。dir 为空时使用模型所在目录。"""
    from core.models.registry import get_model_registry
    import os

    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc or desc.provider != "local":
        return {"error": "Model not found or not local"}, 404

    model_path_val = desc.metadata.get("model_path") or desc.metadata.get("path")
    if not model_path_val:
        return {"error": "Model path unknown"}, 404

    model_dir = os.path.dirname(model_path_val)
    browse_dir = os.path.normpath(os.path.join(model_dir, dir)) if dir else model_dir

    if not os.path.isdir(browse_dir):
        return {"error": "Directory not found", "path": browse_dir}, 404

    # 安全检查：仅允许模型目录及其父级（便于选择模型文件）
    model_dir_real = os.path.realpath(model_dir)
    browse_real = os.path.realpath(browse_dir)
    if not (browse_real.startswith(model_dir_real) or model_dir_real.startswith(browse_real)):
        return {"error": "Access denied"}, 403

    try:
        entries = sorted(os.listdir(browse_dir))
        dirs = []
        files = []
        for name in entries:
            if name.startswith("."):
                continue
            full = os.path.join(browse_dir, name)
            if os.path.isdir(full):
                dirs.append(name)
            else:
                files.append(name)
        parent_dir = os.path.dirname(browse_dir) if browse_dir != model_dir else None
        return {
            "path": browse_dir,
            "dirs": sorted(dirs),
            "files": sorted(files),
            "parent": parent_dir,
            "model_dir": model_dir,
        }
    except PermissionError:
        return {"error": "Permission denied"}, 403
    except Exception as e:
        logger.warning(f"Browse failed: {e}")
        return {"error": str(e)}, 500


@app.get("/api/models/{model_id}/manifest")
async def get_model_manifest(model_id: str):
    """获取模型清单配置"""
    from core.models.registry import get_model_registry
    import os
    import json
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": "Model not found"}, 404
    
    # 对于本地模型，尝试读取 model.json
    model_path_val = desc.metadata.get("model_path") or desc.metadata.get("path")
    if desc.provider == "local" and model_path_val:
        model_dir = os.path.dirname(model_path_val)
        manifest_path = os.path.join(model_dir, "model.json")
        
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                # 将相对 path 解析为绝对路径
                rel_path = manifest.get("path", "")
                if rel_path and not os.path.isabs(rel_path):
                    abs_path = os.path.normpath(os.path.join(model_dir, rel_path))
                    manifest = {**manifest, "path": abs_path}
                return manifest
            except Exception as e:
                logger.warning(f"Failed to read manifest for {model_id}: {e}")
    
    # 返回默认清单
    return {
        "model_id": desc.id,
        "name": desc.name,
        "model_type": getattr(desc, "model_type", None) or desc.metadata.get("modality", "llm"),
        "runtime": desc.runtime,
        "format": desc.metadata.get("format", "gguf"),
        "path": desc.metadata.get("model_path") or desc.metadata.get("path", ""),
        "capabilities": getattr(desc, "capabilities", None) or desc.metadata.get("capabilities", []),
        "quantization": desc.metadata.get("quantization", ""),
        "description": desc.description or "",
        "metadata": desc.metadata
    }


@app.put("/api/models/{model_id}/manifest")
async def update_model_manifest(model_id: str, data: dict):
    """更新模型清单配置"""
    from core.models.registry import get_model_registry
    import os
    import json
    
    reg = get_model_registry()
    desc = reg.get_model(model_id)
    if not desc:
        return {"error": "Model not found"}, 404
    
    # 对于本地模型，更新 model.json
    model_path_val = desc.metadata.get("model_path") or desc.metadata.get("path")
    if desc.provider == "local" and model_path_val:
        model_dir = os.path.dirname(model_path_val)
        manifest_path = os.path.join(model_dir, "model.json")
        
        try:
            # 保存前将绝对路径转为相对路径（model.json 约定使用相对路径）
            save_data = dict(data)
            path_val = save_data.get("path", "")
            if path_val and os.path.isabs(path_val):
                try:
                    rel = os.path.relpath(path_val, model_dir)
                    if not rel.startswith(".."):
                        save_data["path"] = rel
                except ValueError:
                    pass
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Updated manifest for {model_id} at {manifest_path}")
        except Exception as e:
            logger.error(f"Failed to write manifest for {model_id}: {e}")
            return {"error": f"Failed to save manifest: {str(e)}"}, 500
    
    return {"success": True}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
