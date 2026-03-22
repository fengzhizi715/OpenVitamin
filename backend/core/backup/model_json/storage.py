"""
model.json 备份：快照存储与索引写入。
写入流程：临时文件 -> fsync -> 原子重命名；索引为 JSONL 追加。
"""
import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from log import logger

from .sanitize import sanitize_model_id

_INDEX_APPEND_LOCK = threading.Lock()


def get_backup_root() -> Path:
    """备份根目录：model_json_backup_directory 或 backend/data/backups。"""
    from config.settings import settings
    raw = getattr(settings, "model_json_backup_directory", "") or ""
    if raw.strip():
        return Path(raw.strip()).expanduser().resolve()
    # 默认：backend/data/backups（storage.py 在 core/backup/model_json/，上溯到 backend）
    backend = Path(__file__).resolve().parents[3]
    return (backend / "data" / "backups").resolve()


def get_model_json_backup_base() -> Path:
    """model_json 备份根：<backup_root>/model_json。"""
    return get_backup_root() / "model_json"


def get_snapshots_dir(model_id: str) -> Path:
    """
    某模型的快照目录：model_json/snapshots/<model_id_safe>_<id8>/。

    NOTE:
    sanitize_model_id() is not injective (e.g. "a/b" and "a_b" collide).
    Adding a stable short hash avoids directory collisions.
    """
    safe = sanitize_model_id(model_id)
    id8 = hashlib.sha256((model_id or "").encode("utf-8")).hexdigest()[:8]
    return get_model_json_backup_base() / "snapshots" / f"{safe}_{id8}"


def get_snapshots_dir_legacy(model_id: str) -> Path:
    """Legacy snapshot directory (pre-v2.9): model_json/snapshots/<model_id_safe>/."""
    safe = sanitize_model_id(model_id)
    return get_model_json_backup_base() / "snapshots" / safe


def iter_snapshots_dirs(model_id: str) -> List[Path]:
    """
    Candidate snapshot directories for a model.
    Order: new dir first, then legacy dir for backward compatibility.
    """
    dirs = [get_snapshots_dir(model_id)]
    legacy = get_snapshots_dir_legacy(model_id)
    if legacy not in dirs:
        dirs.append(legacy)
    return dirs


def get_index_path() -> Path:
    """索引/变更日志 JSONL 路径。"""
    return get_model_json_backup_base() / "index" / "model_backup_index.jsonl"


def get_manifests_dir() -> Path:
    """每日快照清单目录：model_json/manifests/。"""
    return get_model_json_backup_base() / "manifests"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _sha256_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash8(sha256_hex: str) -> str:
    return (sha256_hex or "")[:8]


def write_snapshot(
    model_id: str,
    content: bytes,
    *,
    backup_id: Optional[str] = None,
    timestamp_utc: Optional[datetime] = None,
) -> tuple[Path, str, str]:
    """
    将 content 写入快照文件，并返回 (快照路径, sha256, hash8)。
    命名：model_<model_id_safe>_<yyyyMMddTHHmmssZ>_<hash8>.json
    """
    now = timestamp_utc or datetime.now(timezone.utc)
    ts_str = now.strftime("%Y%m%dT%H%M%SZ")
    sha = _sha256_content(content)
    h8 = _hash8(sha)
    safe = sanitize_model_id(model_id)
    fname = f"model_{safe}_{ts_str}_{h8}.json"
    snap_dir = get_snapshots_dir(model_id)
    _ensure_dir(snap_dir)
    dest = snap_dir / fname
    # 临时文件 -> fsync -> 原子重命名（Path.write_bytes 无 fileno，需用 open 才能 fsync）
    tmp = snap_dir / f".{fname}.{uuid.uuid4().hex[:8]}"
    try:
        with open(tmp, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        raise
    return dest, sha, h8


def append_index_event(event: Dict[str, Any]) -> None:
    """向索引 JSONL 追加一条事件。"""
    index_path = get_index_path()
    _ensure_dir(index_path.parent)
    line = json.dumps(event, ensure_ascii=False) + "\n"
    # Prevent interleaving writes within the process; also best-effort file lock
    # to behave well under multiple workers.
    with _INDEX_APPEND_LOCK:
        with open(index_path, "a", encoding="utf-8") as f:
            try:
                import fcntl  # type: ignore
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                except Exception:
                    pass
            except Exception:
                pass
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
            try:
                import fcntl  # type: ignore
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            except Exception:
                pass


def read_snapshot_file(path: Path) -> bytes:
    """读取快照文件内容。"""
    return path.read_bytes()


def list_snapshot_files_for_model(model_id: str) -> List[Path]:
    """列出某模型快照目录下所有快照文件（按文件名排序，新在前）。"""
    files: List[Path] = []
    seen: set[str] = set()
    for snap_dir in iter_snapshots_dirs(model_id):
        if not snap_dir.exists():
            continue
        for p in snap_dir.iterdir():
            if not (p.is_file() and p.suffix == ".json" and not p.name.startswith(".")):
                continue
            sp = str(p.resolve())
            if sp in seen:
                continue
            seen.add(sp)
            files.append(p)
    files.sort(key=lambda p: p.name, reverse=True)
    return files


def resolve_snapshot_path(model_id: str, filename: str) -> Optional[Path]:
    """
    Resolve a snapshot file for a model, searching new and legacy directories.
    """
    if not model_id or not filename:
        return None
    for d in iter_snapshots_dirs(model_id):
        p = d / filename
        if p.exists() and p.is_file():
            return p
    return None


def parse_index_events(model_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """读取索引 JSONL，可选按 model_id 过滤，返回最近 limit 条（新在前）。"""
    index_path = get_index_path()
    if not index_path.exists():
        return []
    events = []
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if model_id and ev.get("model_id") != model_id:
                    continue
                events.append(ev)
            except Exception:
                continue
    events.reverse()
    return events[:limit]


def write_daily_manifest(date_yyyymmdd: str, backups: List[Dict[str, Any]]) -> Path:
    """
    写入每日快照清单到 manifests/daily_snapshot_<yyyyMMdd>.json。
    backups 每项建议含 model_id, backup_id, file, sha256, created_at。
    原子写入：先写临时文件再 rename，避免写入中断导致残缺文件。
    """
    _ensure_dir(get_manifests_dir())
    path = get_manifests_dir() / f"daily_snapshot_{date_yyyymmdd}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    now = datetime.now(timezone.utc)
    payload = {
        "date": date_yyyymmdd,
        "created_at": now.isoformat(),
        "backups": backups,
    }
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        raise
    return path


def list_daily_manifests() -> List[str]:
    """列出已有每日清单日期（yyyyMMdd），按日期倒序。"""
    manifests_dir = get_manifests_dir()
    if not manifests_dir.exists():
        return []
    out = []
    for p in manifests_dir.iterdir():
        if p.is_file() and p.suffix == ".json" and p.name.startswith("daily_snapshot_"):
            # daily_snapshot_20260312.json
            date_str = p.stem.replace("daily_snapshot_", "")
            if len(date_str) == 8 and date_str.isdigit():
                out.append(date_str)
    out.sort(reverse=True)
    return out


def read_daily_manifest(date_yyyymmdd: str) -> Optional[Dict[str, Any]]:
    """读取指定日期的每日清单。"""
    path = get_manifests_dir() / f"daily_snapshot_{date_yyyymmdd}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def snapshot_file_timestamp(path: Path) -> Optional[datetime]:
    """
    从快照文件名解析时间戳。文件名格式：model_<safe>_<yyyyMMddTHHmmssZ>_<hash8>.json
    返回 UTC datetime 或 None。
    """
    import re
    name = path.stem  # model_local_xxx_20260312T021501Z_abc
    m = re.search(r"(\d{8}T\d{6}Z)", name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
