from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import psutil
import time
import os
import json
import aiofiles
from pathlib import Path
from log import logger, log_structured

import subprocess
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict

from config.settings import settings
from core.system.settings_store import get_system_settings_store

router = APIRouter(prefix="/api/system", tags=["system"])

ALLOWED_SYSTEM_CONFIG_KEYS = {
    "offlineMode",
    "theme",
    "modelLoader",
    "contextWindow",
    "gpuLayers",
    "dataDirectory",
    "language",
    "yoloModelPath",
    "yoloDevice",
    "yoloDefaultBackend",
    "imageGenerationDefaultModelId",
    "asrModelId",
    "asrDevice",
    "autoUnloadLocalModelOnSwitch",
    "runtimeAutoReleaseEnabled",
    "runtimeMaxCachedLocalRuntimes",
    "runtimeMaxCachedLocalLlmRuntimes",
    "runtimeMaxCachedLocalVlmRuntimes",
    "runtimeMaxCachedLocalImageGenerationRuntimes",
    "runtimeReleaseIdleTtlSeconds",
    "runtimeReleaseMinIntervalSeconds",
}


class SystemConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offlineMode: Optional[bool] = None
    theme: Optional[Literal["light", "dark"]] = None
    modelLoader: Optional[Literal["llama.cpp", "ollama"]] = None
    contextWindow: Optional[int] = Field(default=None, ge=256, le=262144)
    gpuLayers: Optional[int] = Field(default=None, ge=0, le=256)
    dataDirectory: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    language: Optional[Literal["zh", "en"]] = None

    yoloModelPath: Optional[str] = Field(default=None, max_length=4096)
    yoloDevice: Optional[Literal["auto", "cpu", "cuda", "mps"]] = None
    yoloDefaultBackend: Optional[Literal["yolov8", "yolov11", "yolov26", "onnx"]] = None
    imageGenerationDefaultModelId: Optional[str] = Field(default=None, max_length=512)

    asrModelId: Optional[str] = Field(default=None, min_length=1, max_length=512)
    asrDevice: Optional[Literal["auto", "cpu", "cuda", "mps"]] = None

    autoUnloadLocalModelOnSwitch: Optional[bool] = None
    runtimeAutoReleaseEnabled: Optional[bool] = None
    runtimeMaxCachedLocalRuntimes: Optional[int] = Field(default=None, ge=1, le=16)
    runtimeMaxCachedLocalLlmRuntimes: Optional[int] = Field(default=None, ge=1, le=16)
    runtimeMaxCachedLocalVlmRuntimes: Optional[int] = Field(default=None, ge=1, le=16)
    runtimeMaxCachedLocalImageGenerationRuntimes: Optional[int] = Field(default=None, ge=1, le=16)
    runtimeReleaseIdleTtlSeconds: Optional[int] = Field(default=None, ge=30, le=86400)
    runtimeReleaseMinIntervalSeconds: Optional[int] = Field(default=None, ge=1, le=3600)


def _validate_system_config_payload(config_data: dict) -> dict:
    if not isinstance(config_data, dict):
        raise HTTPException(status_code=400, detail="config payload must be a JSON object")

    unsupported = sorted(set(config_data.keys()) - ALLOWED_SYSTEM_CONFIG_KEYS)
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "unsupported system config keys",
                "unsupported_keys": unsupported,
                "allowed_keys": sorted(ALLOWED_SYSTEM_CONFIG_KEYS),
            },
        )

    try:
        validated = SystemConfigUpdate.model_validate(config_data)
    except Exception as e:
        if hasattr(e, "errors"):
            raise HTTPException(status_code=400, detail={"message": "invalid system config payload", "errors": e.errors()})
        raise HTTPException(status_code=400, detail=str(e))

    return validated.model_dump(exclude_none=True)

@router.get("/config")
async def get_config():
    """获取系统配置"""
    store = get_system_settings_store()
    db_settings = store.get_all_settings()
    
    # 优先从数据库读取用户设置的目录，否则使用配置文件默认值
    local_model_dir = db_settings.get("dataDirectory") or settings.local_model_directory
    
    return {
        "ollama_base_url": settings.ollama_base_url,
        "app_name": settings.app_name,
        "version": settings.version,
        "local_model_directory": local_model_dir,
        "settings": db_settings
    }

@router.post("/config")
async def update_config(config_data: dict):
    """更新系统配置"""
    config_data = _validate_system_config_payload(config_data)
    store = get_system_settings_store()
    for key, value in config_data.items():
        store.set_setting(key, value)
    return {"success": True}

@router.post("/engine/reload")
async def reload_engine():
    """重载推理引擎"""
    logger.info("[System] Reloading inference engine...")
    # 这里可以添加实际的重载逻辑，比如重启 Ollama 服务或重置 llama.cpp 实例
    await asyncio.sleep(1.5)
    return {"success": True}

@router.get("/browse-directory")
async def browse_directory():
    """打开本地目录选择器 (目前仅支持 MacOS)"""
    import platform
    import subprocess
    
    system = platform.system()
    try:
        if system == "Darwin":
            # MacOS osascript to pick a folder and return POSIX path
            cmd = 'osascript -e "POSIX path of (choose folder with prompt \\"Select Local Model Directory:\\")"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {"path": stdout.decode().strip()}
        elif system == "Windows":
            # Windows powershell snippet for folder picker
            cmd = 'powershell.exe -NoProfile -Command "& { $app = New-Object -ComObject Shell.Application; $folder = $app.BrowseForFolder(0, \'Select Local Model Directory\', 0); if ($folder) { $folder.Self.Path } }"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {"path": stdout.decode().strip()}
    except Exception as e:
        logger.error(f"[System] Browse directory failed: {e}")
        
    return {"path": None}

# 获取启动时间
BOOT_TIME = time.time()

def get_node_version():
    """获取 Node.js 版本"""
    try:
        result = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return "N/A"

def get_gpu_metrics():
    """获取真实的 GPU 指标"""
    gpu_metrics = {
        "gpu_usage": 0,
        "vram_used": 0,
        "vram_total": 0,
        "cuda_version": "N/A"
    }
    
    # 1. 尝试 NVIDIA GPU (pynvml)
    try:
        import pynvml
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        if device_count > 0:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0) # 默认取第一个 GPU
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            cuda_ver = pynvml.nvmlSystemGetCudaDriverVersion()
            
            gpu_metrics["gpu_usage"] = util.gpu
            gpu_metrics["vram_used"] = round(info.used / (1024**3), 1)
            gpu_metrics["vram_total"] = round(info.total / (1024**3), 1)
            gpu_metrics["cuda_version"] = f"{cuda_ver // 1000}.{(cuda_ver % 1000) // 10}"
            pynvml.nvmlShutdown()
            return gpu_metrics
    except:
        pass

    # 2. 尝试 MacOS Apple Silicon (MPS / Unified Memory)
    if os.uname().sysname == 'Darwin':
        try:
            # 对于 Mac，VRAM 即统一内存
            mem = psutil.virtual_memory()
            gpu_metrics["vram_total"] = round(mem.total / (1024**3), 1)
            # 估算 GPU 占用的内存 (Mac 没有直接 API 拿 GPU 瞬时占用，通常取当前活跃内存的一个比例)
            gpu_metrics["vram_used"] = round(mem.used / (1024**3), 1)
            gpu_metrics["cuda_version"] = "MPS (Metal)"
            
            # 获取 GPU 使用率 (通过 ioreg 尝试，可能较慢)
            cmd = "ioreg -l | grep \"PerformanceStatistics\" | grep \"Device Utilization\" | head -n 1"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=1)
            if res.stdout:
                # 解析示例: "Device Utilization %"=15
                import re
                match = re.search(r"\"Device Utilization %\"=(\d+)", res.stdout)
                if match:
                    gpu_metrics["gpu_usage"] = int(match.group(1))
            return gpu_metrics
        except:
            pass

    return gpu_metrics

@router.get("/runtime-metrics")
async def get_runtime_metrics_api():
    """V2.9 运行时稳定层指标：按模型的请求数、延迟、队列、tokens"""
    from core.runtime import get_runtime_metrics
    return get_runtime_metrics().get_metrics()


@router.get("/metrics")
async def get_metrics():
    """获取硬件指标"""
    from core.inference.stats.tracker import get_inference_stats
    
    cpu_usage = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    
    gpu_info = get_gpu_metrics()
    uptime_seconds = int(time.time() - BOOT_TIME)
    
    # Get inference speed from stats tracker
    inference_stats = get_inference_stats().get_stats()
    inference_speed = inference_stats.get("inference_speed")  # tokens/s or None
    
    return {
        "cpu_load": cpu_usage,
        "ram_used": round(memory.used / (1024**3), 1),
        "ram_total": round(memory.total / (1024**3), 1),
        "gpu_usage": gpu_info["gpu_usage"],
        "vram_used": gpu_info["vram_used"],
        "vram_total": gpu_info["vram_total"],
        "inference_speed": inference_speed,  # tokens/s or null
        "uptime": format_uptime(uptime_seconds),
        "node_version": get_node_version(),
        "cuda_version": gpu_info["cuda_version"],
        "active_workers": psutil.cpu_count(logical=False) or 4
    }

def format_uptime(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"

@router.get("/logs/stream")
async def stream_logs(request: Request):
    """实时流式推送日志"""
    # 使用与 logger.py 相同的路径计算方式（基于 __file__ 的相对路径）
    # backend/api/system.py -> backend/api -> backend -> 项目根目录
    # 先 resolve __file__ 确保是绝对路径，然后计算相对路径
    backend_api_file = Path(__file__).resolve()  # 先转换为绝对路径
    backend_api_dir = backend_api_file.parent  # backend/api
    root_dir = backend_api_dir.parent.parent  # 项目根目录 (backend/api -> backend -> 项目根目录)
    log_file = root_dir / "logs" / "app.log"  # 已经是绝对路径
    
    async def log_generator():
        # 确保日志目录存在（log_file 已经是绝对路径）
        log_file_abs = log_file.resolve()  # 再次确保是绝对路径
        log_file_abs.parent.mkdir(parents=True, exist_ok=True)
        
        if not log_file_abs.exists():
            # 如果日志文件不存在，创建一个空文件并发送提示
            log_file_abs.touch()
            yield f"data: {json.dumps({'timestamp': '', 'level': 'INFO', 'tag': 'System', 'message': 'Log file created. Waiting for logs...'})}\n\n"
            await asyncio.sleep(0.1)

        # 先读取最后 50 行
        async with aiofiles.open(log_file_abs, mode='r', encoding='utf-8') as f:
            lines = await f.readlines()
            # 只处理最后 50 行，跳过空行和 Traceback 行
            for line in lines[-50:]:
                line = line.strip()
                if not line or line.startswith("Traceback") or line.startswith("File \""):
                    continue
                entry = parse_log_line(line)
                if entry:
                    yield f"data: {json.dumps(entry)}\n\n"

        # 持续监控新日志
        # 使用轮询方式监控文件变化，因为 aiofiles.readline() 在文件末尾不会阻塞
        last_size = log_file_abs.stat().st_size if log_file_abs.exists() else 0
        
        while True:
            if await request.is_disconnected():
                break
            
            try:
                current_size = log_file_abs.stat().st_size
                
                # 如果文件大小增加，读取新内容
                if current_size > last_size:
                    async with aiofiles.open(log_file_abs, mode='r', encoding='utf-8') as f:
                        await f.seek(last_size)
                        new_lines = await f.readlines()
                        for line in new_lines:
                            line = line.strip()
                            # 跳过空行和 Traceback 行
                            if not line or line.startswith("Traceback") or line.startswith("File \""):
                                continue
                            entry = parse_log_line(line)
                            if entry:
                                yield f"data: {json.dumps(entry)}\n\n"
                        last_size = current_size
                
                await asyncio.sleep(0.5)  # 轮询间隔
            except Exception as e:
                logger.error(f"Error reading log file: {e}")
                await asyncio.sleep(1)

    return StreamingResponse(log_generator(), media_type="text/event-stream")

def parse_log_line(line: str) -> dict:
    """
    解析日志行
    格式: [%(asctime)s] %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] - %(message)s
    示例: [2026-01-13 12:12:30] INFO [ai_platform] [chat.py:111] - Some message
    """
    try:
        if not line.strip() or " - " not in line:
            return None
            
        parts = line.split(" - ", 1)
        header = parts[0].strip()
        message = parts[1].strip()
        
        # 解析 header: [2026-01-13 12:12:30] INFO [ai_platform] [chat.py:111]
        if not header.startswith("[") or "]" not in header:
            return None
            
        # 提取时间戳 [2026-01-13 12:12:30]
        time_end = header.find("]")
        if time_end == -1:
            return None
        time_str = header[1:time_end]  # "2026-01-13 12:12:30"
        
        # 提取剩余部分: " INFO [ai_platform] [chat.py:111]"
        remaining = header[time_end + 1:].strip()
        if not remaining:
            return None
        
        # 提取级别 (第一个单词)
        parts_remaining = remaining.split(" ", 1)
        level = parts_remaining[0] if parts_remaining else "INFO"
        
        # 提取 tag (第一个 [xxx] 中的内容)
        tag = "System"
        if len(parts_remaining) > 1:
            tag_part = parts_remaining[1]
            tag_start = tag_part.find("[")
            if tag_start != -1:
                tag_end = tag_part.find("]", tag_start + 1)
                if tag_end != -1:
                    tag = tag_part[tag_start + 1:tag_end]

        return {
            "timestamp": time_str,  # 完整的时间戳 "2026-01-13 12:12:30"
            "level": "ERRR" if level == "ERROR" else level,
            "tag": tag,
            "message": message
        }
    except Exception as e:
        logger.debug(f"Failed to parse log line: {e}, line: {line[:100]}")
        return None


# ========== Execution Kernel 管理 API ==========

@router.get("/kernel/stats")
async def get_kernel_stats():
    """
    获取 Execution Kernel 聚合统计指标
    
    指标包括：
    - total_runs: 总执行次数
    - kernel_runs: Kernel 执行次数
    - plan_based_runs: PlanBasedExecutor 执行次数
    - kernel_success_rate: Kernel 成功率 (%)
    - kernel_fallback_rate: Kernel 回退率 (%)
    - step_fail_rate: 步骤失败率 (%)
    - replan_trigger_rate: RePlan 触发率
    - avg_duration_ms: 平均耗时
    - p50_duration_ms: P50 耗时
    - p95_duration_ms: P95 耗时
    """
    from core.agent_runtime.v2.observability import get_kernel_stats
    return get_kernel_stats().get_stats()


@router.get("/kernel/status")
async def get_kernel_status():
    """
    获取 Execution Kernel 当前状态
    
    返回：
    - enabled: 全局是否启用
    - can_toggle: 是否可以运行时切换
    """
    from core.agent_runtime.v2.runtime import USE_EXECUTION_KERNEL
    return {
        "enabled": USE_EXECUTION_KERNEL,
        "can_toggle": True,
        "description": "Execution Kernel is a DAG-based execution engine. Set USE_EXECUTION_KERNEL in runtime.py or use agent-level override."
    }


@router.post("/kernel/toggle")
async def toggle_kernel(data: dict):
    """
    运行时切换 Execution Kernel 开关
    
    请求体：
    - enabled: true/false
    
    注意：此操作仅影响当前运行实例，重启后恢复为代码中定义的默认值。
    """
    from core.agent_runtime.v2.runtime import USE_EXECUTION_KERNEL
    import core.agent_runtime.v2.runtime as runtime_module
    
    enabled = data.get("enabled", None)
    if enabled is None:
        return {"success": False, "error": "Missing 'enabled' field"}
    
    # 运行时修改模块级变量
    runtime_module.USE_EXECUTION_KERNEL = bool(enabled)
    
    log_structured("System", "kernel_toggled", enabled=bool(enabled), previous=USE_EXECUTION_KERNEL)
    logger.info(f"[System] Execution Kernel toggled to: {enabled}")
    
    return {
        "success": True,
        "enabled": bool(enabled),
        "note": "Runtime toggle. Will reset to default on restart."
    }


@router.post("/kernel/stats/reset")
async def reset_kernel_stats():
    """重置 Kernel 统计指标"""
    from core.agent_runtime.v2.observability import get_kernel_stats
    stats = get_kernel_stats()
    stats._reset()
    log_structured("System", "kernel_stats_reset")
    return {"success": True, "message": "Kernel stats reset"}


# ========== V2.7: Optimization Layer API ==========

@router.get("/kernel/optimization")
async def get_optimization_status():
    """
    V2.7: 获取 Optimization Layer 状态
    
    返回：
    - enabled: 是否启用优化
    - scheduler_policy: 调度策略信息（名称、版本）
    - snapshot: 快照信息（版本、节点数、Skill 数）
    - config: 完整配置
    """
    from core.agent_runtime.v2.runtime import get_kernel_adapter
    
    adapter = get_kernel_adapter()
    if adapter is None:
        return {
            "enabled": False,
            "error": "Kernel adapter not initialized",
        }
    if not adapter._initialized:
        await adapter.initialize()
    return adapter.get_optimization_status()


@router.post("/kernel/optimization/rebuild-snapshot")
async def rebuild_optimization_snapshot(data: dict = None):
    """
    V2.7: 重新构建 OptimizationSnapshot
    
    请求体（可选）：
    - instance_ids: 指定收集的实例 ID 列表
    - limit_instances: 最大实例数量限制（默认 100）
    
    返回：
    - version: 新快照版本
    - node_count: 节点统计数
    - skill_count: Skill 统计数
    """
    from core.agent_runtime.v2.runtime import get_kernel_adapter
    
    adapter = get_kernel_adapter()
    if adapter is None:
        return {"success": False, "error": "Kernel adapter not initialized"}
    if not adapter._initialized:
        await adapter.initialize()
    
    data = data or {}
    instance_ids = data.get("instance_ids")
    limit_instances = data.get("limit_instances", 100)
    
    try:
        snapshot = await adapter.rebuild_optimization_snapshot(
            instance_ids=instance_ids,
            limit_instances=limit_instances,
        )
        
        log_structured("System", "optimization_snapshot_rebuilt", 
                      version=snapshot.version,
                      node_count=len(snapshot.node_weights))
        
        return {
            "success": True,
            "version": snapshot.version,
            "node_count": len(snapshot.node_weights),
            "skill_count": len(snapshot.skill_weights),
        }
    except Exception as e:
        logger.error(f"[System] Failed to rebuild optimization snapshot: {e}")
        return {"success": False, "error": str(e)}


@router.post("/kernel/optimization/config")
async def set_optimization_config(data: dict):
    """
    V2.7: 更新 Optimization 配置
    
    请求体：
    - enabled: 是否启用优化
    - scheduler_policy: 策略名称（"default" 或 "learned"）
    - policy_params: 策略参数（仅 learned 策略有效）
      - node_weight_factor: 节点权重乘数
      - latency_penalty_factor: 延迟惩罚乘数
      - skill_weight_factor: Skill 权重乘数
      - consider_skill: 是否考虑 Skill 权重
    """
    from core.agent_runtime.v2.runtime import get_kernel_adapter
    from execution_kernel.optimization import OptimizationConfig
    
    adapter = get_kernel_adapter()
    if adapter is None:
        return {"success": False, "error": "Kernel adapter not initialized"}
    if not adapter._initialized:
        await adapter.initialize()
    
    try:
        config = OptimizationConfig(
            enabled=data.get("enabled", False),
            scheduler_policy=data.get("scheduler_policy", "default"),
            policy_params=data.get("policy_params", {}),
            auto_build_snapshot=data.get("auto_build_snapshot", True),
            collect_statistics=data.get("collect_statistics", True),
        )
        
        adapter.set_optimization_config(config)
        
        # 每次更新配置都重新初始化策略，确保关闭优化时切回 DefaultPolicy
        await adapter._initialize_optimization()
        
        log_structured("System", "optimization_config_updated",
                      enabled=config.enabled,
                      policy=config.scheduler_policy)
        
        return {
            "success": True,
            "config": config.to_dict(),
        }
    except Exception as e:
        logger.error(f"[System] Failed to update optimization config: {e}")
        return {"success": False, "error": str(e)}


@router.get("/kernel/optimization/impact-report")
async def get_optimization_impact_report():
    """
    V2.7: 获取优化效果报告
    
    对比当前快照与空快照（或指定版本）的差异，计算优化效果：
    - 成功率提升百分比
    - 延迟降低百分比
    - 节点/Skill 数量变化
    """
    from core.agent_runtime.v2.runtime import get_kernel_adapter
    from execution_kernel.optimization.snapshot import OptimizationSnapshot
    from execution_kernel.analytics.metrics import compute_optimization_impact
    
    adapter = get_kernel_adapter()
    if adapter is None:
        return {"error": "Kernel adapter not initialized"}
    
    if not adapter._initialized:
        await adapter.initialize()
    
    current_snapshot = adapter._optimization_snapshot
    if current_snapshot is None:
        return {"error": "No optimization snapshot available"}
    
    # 使用空快照作为基准对比
    baseline_snapshot = OptimizationSnapshot.empty()
    baseline_empty = True

    # 计算优化效果
    impact = compute_optimization_impact(baseline_snapshot, current_snapshot)

    log_structured("System", "optimization_impact_report",
                  improvement_pct=impact["improvement_pct"],
                  latency_reduction=impact["latency_reduction_pct"])

    return {
        "impact": impact,
        "baseline_empty": baseline_empty,
        "note": "空快照表示无历史数据基准，当前数值为相对「无优化」的差异；success_rate_before=0 仅表示基准无数据。",
        "current_policy": adapter._scheduler_policy.get_name() if adapter._scheduler_policy else None,
        "optimization_enabled": adapter._optimization_config.enabled if adapter._optimization_config else False,
    }
