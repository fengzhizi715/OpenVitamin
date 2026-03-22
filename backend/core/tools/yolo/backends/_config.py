"""
YOLO 模型路径与配置

配置来源优先级：
1. yolo_model_path（显式配置，文件不存在时抛错）
2. perception 目录下的 model.json（与 LocalScanner 对齐）
3. 默认路径 + 目录扫描
"""

import json
from pathlib import Path
from typing import Any, Dict

from config.settings import settings


def _get_models_dir() -> Path:
    """与 LocalScanner 一致：优先 dataDirectory，否则 local_model_directory"""
    try:
        from core.system.settings_store import get_system_settings_store
        store = get_system_settings_store()
        configured = store.get_setting("dataDirectory")
        if configured:
            return Path(configured).expanduser().resolve()
    except Exception:
        pass
    return Path(settings.local_model_directory).expanduser().resolve()


def _resolve_device(device: str) -> str:
    """支持 auto：自动选择 cuda > mps > cpu"""
    if device and device.lower() != "auto":
        return device.lower()
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _get_yolo_model_path_from_store() -> str | None:
    """从 UI 配置（SystemSettingsStore）读取模型路径，优先于 env"""
    try:
        from core.system.settings_store import get_system_settings_store
        store = get_system_settings_store()
        v = store.get_setting("yoloModelPath") or store.get_setting("yolo_model_path")
        return (v or "").strip() or None
    except Exception:
        return None


def _get_model_path_and_manifest_device_for(
    subdirs: list[str],
    default_filename: str,
    preferred: list[str],
) -> tuple[str, str | None]:
    """
    获取 YOLO 模型路径及 model.json 中的 device。
    返回 (model_path, manifest_device | None)
    配置优先级：UI 配置 > 环境变量/settings > model.json > 默认
    """
    # 1. 显式配置（UI 或 env）：存在则用，不存在则抛错（不静默回退）
    explicit_path = _get_yolo_model_path_from_store() or (
        (settings.yolo_model_path or "").strip() or None
    )
    if explicit_path:
        p = Path(explicit_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(
                f"YOLO 模型路径已配置但文件不存在: {p}。"
                f"请检查 YOLO_MODEL_PATH 或 yolo_model_path 配置。"
            )
        return str(p), None

    models_dir = _get_models_dir()
    perception_dir = models_dir / "perception"

    # 2. 尝试从 perception 子目录读取 model.json（与平台模型配置对齐）
    for sub in subdirs:
        candidate_dir = perception_dir / sub
        manifest_path = candidate_dir / "model.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                rel_path = manifest.get("path", default_filename)
                full_path = (candidate_dir / rel_path).resolve()
                if full_path.exists():
                    dev = manifest.get("metadata", {}).get("device")
                    return str(full_path), dev
            except (json.JSONDecodeError, OSError):
                pass

    # 3. 默认路径
    default_dir = subdirs[0]
    default = models_dir / "perception" / default_dir / default_filename
    if default.exists():
        return str(default), None

    # 4. 扫描默认目录
    scan_dir = models_dir / "perception" / default_dir
    if scan_dir.is_dir():
        for name in preferred:
            p = scan_dir / name
            if p.exists():
                return str(p.resolve()), None
        for f in sorted(scan_dir.glob("*.pt")):
            return str(f.resolve()), None

    return str(default), None


def _get_yolo_device_from_store() -> str | None:
    """从 UI 配置读取 device"""
    try:
        from core.system.settings_store import get_system_settings_store
        store = get_system_settings_store()
        return store.get_setting("yoloDevice") or store.get_setting("yolo_device")
    except Exception:
        return None


def get_yolov8_config() -> Dict[str, Any]:
    """获取 TorchPerceptionRuntime 所需配置"""
    model_path, manifest_device = _get_model_path_and_manifest_device_for(
        subdirs=["YOLOv8", "yolov8", "YOLO"],
        default_filename="yolov8s.pt",
        preferred=["yolov8s.pt", "yolov8n.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt"],
    )
    raw_device = (
        manifest_device
        or _get_yolo_device_from_store()
        or getattr(settings, "yolo_device", "mps")
        or "mps"
    )
    device = _resolve_device(raw_device)

    return {
        "model_id": "yolov8s",
        "runtime": "torch",
        "task": "object_detection",
        "model_path": model_path,
        "device": device,
        "confidence_threshold": 0.25,
    }


def get_yolov11_config() -> Dict[str, Any]:
    """获取 TorchPerceptionRuntime 所需配置"""
    model_path, manifest_device = _get_model_path_and_manifest_device_for(
        subdirs=["YOLO11", "yolo11"],
        default_filename="yolo11s.pt",
        preferred=["yolo11s.pt", "yolo11n.pt", "yolo11m.pt", "yolo11l.pt", "yolo11x.pt"],
    )
    raw_device = (
        manifest_device
        or _get_yolo_device_from_store()
        or getattr(settings, "yolo_device", "mps")
        or "mps"
    )
    device = _resolve_device(raw_device)

    return {
        "model_id": "yolo11s",
        "runtime": "torch",
        "task": "object_detection",
        "model_path": model_path,
        "device": device,
        "confidence_threshold": 0.25,
    }


def get_yolov26_config() -> Dict[str, Any]:
    """获取 TorchPerceptionRuntime 所需配置"""
    model_path, manifest_device = _get_model_path_and_manifest_device_for(
        subdirs=["YOLO26", "yolo26"],
        default_filename="yolo26s.pt",
        preferred=["yolo26s.pt", "yolo26n.pt", "yolo26m.pt", "yolo26l.pt", "yolo26x.pt"],
    )
    raw_device = (
        manifest_device
        or _get_yolo_device_from_store()
        or getattr(settings, "yolo_device", "mps")
        or "mps"
    )
    device = _resolve_device(raw_device)

    return {
        "model_id": "yolo26s",
        "runtime": "torch",
        "task": "object_detection",
        "model_path": model_path,
        "device": device,
        "confidence_threshold": 0.25,
    }


def get_fastsam_config() -> Dict[str, Any]:
    """获取 FastSAM 实例分割模型配置（TorchPerceptionRuntime）"""
    model_path, manifest_device = _get_model_path_and_manifest_device_for(
        subdirs=[
            "cv_fastsam_image-instance-segmentation_sa1b",
            "FastSAM",
            "fastsam",
        ],
        default_filename="FastSAM-s.pt",
        preferred=["FastSAM-s.pt", "FastSAM-x.pt"],
    )
    raw_device = (
        manifest_device
        or _get_yolo_device_from_store()
        or getattr(settings, "yolo_device", "mps")
        or "mps"
    )
    device = _resolve_device(raw_device)
    return {
        "model_id": "cv_fastsam_image-instance-segmentation_sa1b",
        "runtime": "torch",
        "task": "instance_segmentation",
        "model_path": model_path,
        "device": device,
        "confidence_threshold": 0.4,
    }
