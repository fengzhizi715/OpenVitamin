"""
V2.9 Runtime Stabilization Layer - Runtime configuration.

Per-runtime-type concurrency and behavior.
Precedence: model metadata (model.json) > settings overrides > MODEL_RUNTIME_CONFIG.
"""
import json
from typing import Dict, Any, Optional

from log import logger

# Default key for runtimes not explicitly listed
DEFAULT_KEY = "default"

# Per-runtime-type config: max_concurrency limits parallel inference per model.
# Lower values reduce OOM risk (llama.cpp/torch); higher values allow more throughput (ollama/remote).
MODEL_RUNTIME_CONFIG: Dict[str, Dict[str, Any]] = {
    DEFAULT_KEY: {
        "max_concurrency": 1,
    },
    "llama.cpp": {
        "max_concurrency": 1,
    },
    "torch": {
        "max_concurrency": 2,
    },
    "ollama": {
        "max_concurrency": 4,
    },
    "openai": {
        "max_concurrency": 8,
    },
    "lmstudio": {
        "max_concurrency": 4,
    },
    "mlx": {
        "max_concurrency": 1,
    },
    "gemini": {
        "max_concurrency": 8,
    },
    "deepseek": {
        "max_concurrency": 8,
    },
    "kimi": {
        "max_concurrency": 8,
    },
}


def _settings_overrides() -> Dict[str, int]:
    """Parse runtime_max_concurrency_overrides from settings. Returns empty dict on parse error."""
    try:
        from config.settings import settings
        raw = getattr(settings, "runtime_max_concurrency_overrides", "") or ""
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        out: Dict[str, int] = {}
        for k, v in data.items():
            key = str(k).strip().lower()
            # Be strict but ergonomic: accept numeric strings too.
            if isinstance(v, (int, float)) and int(v) >= 1:
                out[key] = max(1, int(v))
                continue
            if isinstance(v, str) and v.strip().isdigit():
                out[key] = max(1, int(v.strip()))
        return out
    except Exception:
        try:
            # Best-effort warning (do not raise from settings parsing).
            from config.settings import settings
            raw = getattr(settings, "runtime_max_concurrency_overrides", "") or ""
            if raw.strip():
                logger.warning(
                    "[RuntimeStabilization] Failed to parse settings.runtime_max_concurrency_overrides; expected JSON object. raw=%r",
                    raw[:500],
                )
        except Exception:
            pass
        return {}


def get_max_concurrency(runtime_type: str, model_id: Optional[str] = None) -> int:
    """
    Return max_concurrency for the given runtime type (and optionally model).

    Precedence (User-in-Control + 确定性):
    1. model.json metadata: metadata.max_concurrency for this model_id
    2. settings: runtime_max_concurrency_overrides[runtime_type]
    3. MODEL_RUNTIME_CONFIG[runtime_type]
    """
    rt = (runtime_type or "").strip().lower()
    if not rt:
        rt = DEFAULT_KEY

    # 1) Model-level: model.json metadata
    if model_id:
        try:
            from core.models.registry import get_model_registry
            reg = get_model_registry()
            desc = reg.get_model(model_id)
            if desc and isinstance(getattr(desc, "metadata", None), dict):
                v = desc.metadata.get("max_concurrency")
                if v is not None:
                    return max(1, int(v))
                # Help users avoid silent misconfiguration while keeping determinism:
                # do NOT interpret camelCase automatically, but warn if present.
                if "maxConcurrency" in desc.metadata:
                    logger.warning(
                        "[RuntimeStabilization] model metadata uses 'maxConcurrency' but only 'max_concurrency' is supported. model_id=%s",
                        model_id,
                    )
        except Exception:
            pass

    # 2) Settings overrides (per runtime type)
    overrides = _settings_overrides()
    if rt in overrides:
        return overrides[rt]

    # 3) Code default
    cfg = MODEL_RUNTIME_CONFIG.get(rt) or MODEL_RUNTIME_CONFIG.get(DEFAULT_KEY) or {}
    return max(1, int(cfg.get("max_concurrency", 1)))
