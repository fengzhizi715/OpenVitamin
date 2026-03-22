"""
model.json 备份：解析 model_id 对应的 model.json 文件路径。
通过扫描本地模型目录查找包含该 model_id 的 model.json。
"""
import json
from pathlib import Path
from typing import Optional


def get_models_directory() -> Path:
    """获取本地模型根目录（与 LocalScanner 一致）。"""
    from core.system.settings_store import get_system_settings_store
    from config.settings import settings
    store = get_system_settings_store()
    configured = store.get_setting("dataDirectory") or getattr(settings, "local_model_directory", "")
    if not configured:
        configured = "~/.local-ai/models/"
    return Path(configured).expanduser().resolve()


def resolve_model_json_path(model_id: str) -> Optional[Path]:
    """
    解析 model_id 对应的 model.json 绝对路径。
    仅支持本地模型（local:*）；扫描 models_dir 下 llm/embedding/vlm/asr/perception 及根目录子目录。
    返回 None 表示未找到。
    """
    if not model_id or not isinstance(model_id, str):
        return None
    model_id = model_id.strip()
    models_dir = get_models_directory()
    if not models_dir.exists() or not models_dir.is_dir():
        return None

    # 与 LocalScanner 一致的扫描顺序
    subdirs = ["llm", "embedding", "vlm", "asr", "perception"]
    for sub_name in subdirs:
        sub_dir = models_dir / sub_name
        if not sub_dir.exists() or not sub_dir.is_dir():
            continue
        for item in sub_dir.iterdir():
            if not item.is_dir():
                continue
            manifest_path = item / "model.json"
            if not manifest_path.exists():
                continue
            if _manifest_matches_model_id(manifest_path, model_id):
                return manifest_path.resolve()

    for item in models_dir.iterdir():
        if not item.is_dir() or item.name in subdirs:
            continue
        manifest_path = item / "model.json"
        if not manifest_path.exists():
            continue
        if _manifest_matches_model_id(manifest_path, model_id):
            return manifest_path.resolve()

    return None


def _manifest_matches_model_id(manifest_path: Path, model_id: str) -> bool:
    """读取 model.json 判断其 model_id 是否与目标一致（支持 local: 前缀）。"""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        mid = (data.get("model_id") or "").strip()
        if not mid:
            return False
        # 与 LocalScanner 一致：id 为 local:{model_id}
        canonical = f"local:{mid}"
        return canonical == model_id or mid == model_id
    except Exception:
        return False
