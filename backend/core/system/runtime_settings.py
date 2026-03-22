"""
运行时相关配置：优先从 SystemSettingsStore（前端可配）读取，否则回退到 config.settings。
key 与前端约定为 camelCase。
"""
from config.settings import settings
from core.system.settings_store import get_system_settings_store


def _get_bool(key: str, fallback: bool) -> bool:
    v = get_system_settings_store().get_setting(key)
    if v is None:
        return fallback
    return bool(v)


def _get_int(key: str, fallback: int, min_val: int, max_val: int) -> int:
    v = get_system_settings_store().get_setting(key)
    if v is None:
        return fallback
    try:
        n = int(v)
        return max(min_val, min(max_val, n))
    except (TypeError, ValueError):
        return fallback


def get_auto_unload_local_model_on_switch() -> bool:
    return _get_bool("autoUnloadLocalModelOnSwitch", getattr(settings, "auto_unload_local_model_on_switch", False))


def get_runtime_auto_release_enabled() -> bool:
    return _get_bool("runtimeAutoReleaseEnabled", getattr(settings, "runtime_auto_release_enabled", True))


def get_runtime_max_cached_local_runtimes(model_type: str | None = None) -> int:
    fallback = getattr(settings, "runtime_max_cached_local_runtimes", 1)
    if not model_type:
        return _get_int("runtimeMaxCachedLocalRuntimes", fallback, 1, 16)

    normalized = str(model_type).lower()
    if normalized in {"vision", "multimodal"}:
        normalized = "vlm"

    specific_keys = {
        "llm": (
            "runtimeMaxCachedLocalLlmRuntimes",
            getattr(settings, "runtime_max_cached_local_llm_runtimes", fallback),
        ),
        "vlm": (
            "runtimeMaxCachedLocalVlmRuntimes",
            getattr(settings, "runtime_max_cached_local_vlm_runtimes", fallback),
        ),
        "image_generation": (
            "runtimeMaxCachedLocalImageGenerationRuntimes",
            getattr(settings, "runtime_max_cached_local_image_generation_runtimes", fallback),
        ),
    }
    key_and_fallback = specific_keys.get(normalized)
    if not key_and_fallback:
        return _get_int("runtimeMaxCachedLocalRuntimes", fallback, 1, 16)
    key, typed_fallback = key_and_fallback
    return _get_int(key, typed_fallback, 1, 16)


def get_runtime_release_idle_ttl_seconds() -> int:
    fallback = getattr(settings, "runtime_release_idle_ttl_seconds", 300)
    return _get_int("runtimeReleaseIdleTtlSeconds", fallback, 30, 86400)


def get_runtime_release_min_interval_seconds() -> int:
    fallback = getattr(settings, "runtime_release_min_interval_seconds", 5)
    return _get_int("runtimeReleaseMinIntervalSeconds", fallback, 1, 3600)
