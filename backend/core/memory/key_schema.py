from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


@dataclass(frozen=True)
class KeySpec:
    key: str
    value_kind: str  # "enum" | "iana_tz" | "lang" | "string"
    description: str
    enum: Optional[list[str]] = None


# 你建议的“规范化 key 命名”：用域前缀，便于确定性合并/冲突
KEY_SPECS: dict[str, KeySpec] = {
    # preference
    "preference.language": KeySpec(
        key="preference.language",
        value_kind="lang",
        description="用户偏好语言（ISO 639-1，如 zh/en/ja）",
    ),
    "preference.timezone": KeySpec(
        key="preference.timezone",
        value_kind="iana_tz",
        description="用户时区（IANA TZ，如 Asia/Shanghai）",
    ),
    # profile
    "profile.role": KeySpec(
        key="profile.role",
        value_kind="string",
        description="用户角色/职业（短字符串）",
    ),
    # project
    "project.name": KeySpec(
        key="project.name",
        value_kind="string",
        description="用户长期项目名称（短字符串）",
    ),
}


def allowed_keys_markdown() -> str:
    lines = ["允许的 key 列表（必须严格使用以下之一）："]
    for k, spec in KEY_SPECS.items():
        lines.append(f"- {k}: {spec.description}")
    return "\n".join(lines)


def normalize_key(key: str) -> Optional[str]:
    if not key:
        return None
    k = key.strip()
    # 允许用户写成 preference_language 等，尽量归一化成 preference.language
    k = k.replace("_", ".")
    k = re.sub(r"\.+", ".", k)
    k = k.lower()
    return k


def normalize_value(key: str, value: str) -> Optional[str]:
    if not value:
        return None
    v = " ".join(value.strip().split())
    spec = KEY_SPECS.get(key)
    if not spec:
        return v

    if spec.value_kind == "string":
        # 控制长度，避免把大段文本当 value
        return v[:128]

    if spec.value_kind == "lang":
        vv = v.lower()
        # 允许 zh / zh-cn / en-us 这种，统一成前两位
        m = re.match(r"^[a-z]{2}(-[a-z]{2})?$", vv)
        if not m:
            return None
        return vv[:2]

    if spec.value_kind == "iana_tz":
        if ZoneInfo is None:
            return v
        try:
            ZoneInfo(v)
            return v
        except Exception:
            return None

    if spec.value_kind == "enum" and spec.enum:
        vv = v.lower()
        for opt in spec.enum:
            if vv == opt.lower():
                return opt
        return None

    return v


def validate_key(key: str) -> bool:
    return key in KEY_SPECS

