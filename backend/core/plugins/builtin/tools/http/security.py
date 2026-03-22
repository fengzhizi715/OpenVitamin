from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple
from urllib.parse import urlparse

from config.settings import settings
from core.tools.context import ToolContext


def _parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def _host_allowed(host: str, patterns: Iterable[str]) -> bool:
    host_l = host.lower()
    for pat in patterns:
        p = pat.strip().lower()
        if not p:
            continue
        if p == host_l:
            return True
        if p.startswith("*.") and host_l.endswith(p[1:]):
            return True
    return False


def check_http_permission_and_url(url: str, ctx: ToolContext) -> Tuple[bool, Optional[str]]:
    """
    Enforce Local-first defaults for HTTP tools.
    Allowed if:
    - ctx.permissions["net.http"] is True, OR settings.tool_net_http_enabled is True
    And (if allowlist non-empty) host matches allowlist.
    """
    # 1) Permission gate (default deny unless explicitly enabled)
    permitted = bool((ctx.permissions or {}).get("net.http")) or bool(settings.tool_net_http_enabled)
    if not permitted:
        return False, "Permission denied: net.http is disabled (enable via ToolContext.permissions['net.http']=true or settings.tool_net_http_enabled=true)"

    # 2) URL validation
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return False, "Invalid URL scheme (must be http or https)"

    host = parsed.hostname
    if not host:
        return False, "Invalid URL (missing hostname)"

    allowed_hosts = _parse_csv(getattr(settings, "tool_net_http_allowed_hosts", "") or "")
    if allowed_hosts:
        if not _host_allowed(host, allowed_hosts):
            return False, f"Host not allowed by allowlist: {host}"

    return True, None

