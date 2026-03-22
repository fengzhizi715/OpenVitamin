from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List


class WorkspacePathError(ValueError):
    pass


def resolve_in_workspace(
    *,
    workspace: str,
    path: str,
    allowed_absolute_roots: Optional[List[str]] = None,
) -> Path:
    """
    Resolve `path` under `workspace` and ensure it cannot escape.

    - `workspace` may be relative or absolute.
    - `path` is treated as relative to workspace by default.
    - If `path` is absolute and `allowed_absolute_roots` is set, path is allowed
      only when it lies under one of those roots (e.g. user home); otherwise
      absolute paths are rejected.
    """
    if path is None or not path.strip():
        raise WorkspacePathError("path is required")

    p = Path(path)
    if p.is_absolute():
        if allowed_absolute_roots:
            target_abs = p.expanduser().resolve()
            for root_str in allowed_absolute_roots:
                root_abs = Path(root_str).expanduser().resolve()
                try:
                    common = Path(os.path.commonpath([str(root_abs), str(target_abs)]))
                    if common == root_abs:
                        return target_abs
                except (ValueError, OSError):
                    continue
        raise WorkspacePathError("absolute paths are not allowed (or path is outside allowed roots)")

    workspace_abs = Path(workspace or ".").expanduser().resolve()
    target_abs = (workspace_abs / p).resolve()

    try:
        common = Path(os.path.commonpath([str(workspace_abs), str(target_abs)]))
    except Exception as e:
        raise WorkspacePathError(f"invalid path: {e}") from e

    if common != workspace_abs:
        raise WorkspacePathError("access denied: outside workspace")

    return target_abs

