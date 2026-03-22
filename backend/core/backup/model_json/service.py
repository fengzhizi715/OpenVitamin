"""
model.json 备份服务：创建、列表、恢复、删除、保留策略。
"""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from log import logger

from .path_resolver import get_models_directory, resolve_model_json_path
from .storage import (
    append_index_event,
    get_snapshots_dir,
    resolve_snapshot_path,
    list_snapshot_files_for_model,
    list_daily_manifests,
    parse_index_events,
    read_daily_manifest,
    read_snapshot_file,
    snapshot_file_timestamp,
    write_daily_manifest,
    write_snapshot,
)


def _event_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _backup_id(ts: datetime, hash8: str) -> str:
    return f"bkp_{ts.strftime('%Y%m%d_%H%M%S')}_{hash8}"


def _validate_schema(data: Dict[str, Any]) -> bool:
    """简单 schema 校验：至少含 model_id。旧版备份可做兼容（见文档 §7）。"""
    return isinstance(data, dict) and isinstance(data.get("model_id"), str)


def create_backup(
    model_id: str,
    *,
    reason: Optional[str] = None,
    tags: Optional[List[str]] = None,
    source: str = "api",
    operator: str = "system",
) -> Dict[str, Any]:
    """
    为指定 model_id 创建一次快照备份（读取当前 model.json 写入备份目录并写索引）。
    返回 { success, backup_id, model_id, file, sha256, created_at } 或 { success: False, error }。
    """
    path = resolve_model_json_path(model_id)
    if not path or not path.exists():
        # 尝试用 registry 的 provider_model_id 再解析一次（兼容前端传参差异）
        try:
            from core.models.registry import get_model_registry
            reg = get_model_registry()
            desc = reg.get_model(model_id)
            if desc and getattr(desc, "provider", "") == "local" and getattr(desc, "provider_model_id", None):
                path = resolve_model_json_path(desc.provider_model_id)
        except Exception:
            pass
        if not path or not path.exists():
            models_dir = get_models_directory()
            err = (
                f"未找到本地模型对应的 model.json：{model_id}。"
                f" 请确认：1) 设置-通用-数据目录 是否包含该模型所在路径；"
                f" 2) 是否已在模型页执行「扫描模型」；"
                f" 3) 当前搜索目录：{models_dir}"
            )
            logger.warning("[ModelJsonBackup] %s", err)
            return {"success": False, "error": err}
    try:
        content = path.read_bytes()
    except Exception as e:
        logger.exception("[ModelJsonBackup] Failed to read model.json for %s", model_id)
        return {"success": False, "error": str(e)}
    ts = datetime.now(timezone.utc)
    try:
        dest_path, sha256, hash8 = write_snapshot(model_id, content, timestamp_utc=ts)
    except Exception as e:
        logger.exception("[ModelJsonBackup] Failed to write snapshot for %s", model_id)
        return {"success": False, "error": str(e)}
    backup_id = _backup_id(ts, hash8)
    event = {
        "event_id": _event_id(),
        "backup_id": backup_id,
        "model_id": model_id,
        "action": "create",
        "operator": operator,
        "source": source,
        "before_hash": None,
        "after_hash": sha256,
        "backup_file": dest_path.name,
        "timestamp_utc": ts.isoformat(),
        "reason": reason or "",
        "tags": tags or [],
    }
    try:
        append_index_event(event)
    except Exception as e:
        logger.warning("[ModelJsonBackup] Index append failed: %s", e)
    from .storage import get_model_json_backup_base, get_backup_root
    base = get_model_json_backup_base()
    try:
        storage_path = str(dest_path.relative_to(base))
    except ValueError:
        storage_path = str(dest_path)
    return {
        "success": True,
        "backup_id": backup_id,
        "model_id": model_id,
        "file": dest_path.name,
        "storage_path": storage_path,
        "backup_root": str(get_backup_root()),
        "sha256": sha256,
        "created_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def create_all_backups(
    *,
    reason: Optional[str] = None,
    source: str = "api",
) -> Dict[str, Any]:
    """
    为所有本地模型创建快照。返回 { success, total, success_count, created: [...], failed }。
    created 每项含 model_id, backup_id, file, sha256, created_at，用于写每日 manifest。
    """
    from core.models.registry import get_model_registry
    reg = get_model_registry()
    models = reg.list_models(provider="local")
    total = len(models)
    failed = []
    created = []
    for d in models:
        out = create_backup(d.id, reason=reason, source=source)
        if not out.get("success"):
            failed.append({"model_id": d.id, "error": out.get("error", "unknown")})
        else:
            created.append({
                "model_id": d.id,
                "backup_id": out.get("backup_id"),
                "file": out.get("file"),
                "sha256": out.get("sha256"),
                "created_at": out.get("created_at"),
            })
    return {
        "success": True,
        "total": total,
        "success_count": total - len(failed),
        "created": created,
        "failed": failed,
    }


def list_backups(model_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    查询备份记录（从索引 JSONL），按时间倒序，最多 limit 条。
    返回项含 backup_id, model_id, backup_file, timestamp_utc, action, reason 等。
    已被用户删除的 backup_id（索引中有 action=delete）不再出现在列表中。
    """
    events = parse_index_events(model_id=model_id, limit=limit * 2)
    deleted_ids: Set[str] = set()
    for ev in events:
        if ev.get("action") == "delete" and ev.get("backup_id"):
            deleted_ids.add(ev["backup_id"])
    result = []
    for ev in events:
        if ev.get("action") not in ("create", "restore") or not ev.get("backup_file"):
            continue
        if ev.get("backup_id") in deleted_ids:
            continue
        result.append({
            "backup_id": ev.get("backup_id"),
            "model_id": ev.get("model_id"),
            "file": ev.get("backup_file"),
            "sha256": ev.get("after_hash"),
            "timestamp_utc": ev.get("timestamp_utc"),
            "action": ev.get("action"),
            "reason": ev.get("reason"),
            "source": ev.get("source"),
        })
        if len(result) >= limit:
            break
    return result


def _find_snapshot_path_by_backup_id(backup_id: str) -> Optional[tuple[str, Path, Optional[str]]]:
    """
    通过 backup_id 在索引中查找对应的 model_id 与快照路径。
    返回 (model_id, path, expected_sha256_or_none) 或 None。expected_sha256 用于恢复前校验。
    """
    events = parse_index_events(model_id=None, limit=5000)
    for ev in events:
        if ev.get("backup_id") == backup_id and ev.get("backup_file") and ev.get("model_id"):
            path = resolve_snapshot_path(ev["model_id"], ev["backup_file"])
            if path is not None:
                return ev["model_id"], path, ev.get("after_hash")
    return None


def delete_backup(backup_id: str, *, source: str = "api", operator: str = "system") -> Dict[str, Any]:
    """
    删除指定 backup_id 对应的快照文件；索引为仅追加，追加一条 action=delete 事件用于审计。
    返回 { success, backup_id, deleted_file } 或 { success: False, error }。
    """
    found = _find_snapshot_path_by_backup_id(backup_id)
    if not found:
        return {"success": False, "error": f"backup not found: {backup_id}"}
    model_id, snapshot_path, _ = found
    try:
        snapshot_path.unlink()
    except Exception as e:
        logger.warning("[ModelJsonBackup] Failed to delete snapshot %s: %s", snapshot_path, e)
        return {"success": False, "error": str(e)}
    ts = datetime.now(timezone.utc)
    try:
        append_index_event({
            "event_id": _event_id(),
            "backup_id": backup_id,
            "model_id": model_id,
            "action": "delete",
            "operator": operator,
            "source": source,
            "backup_file": snapshot_path.name,
            "timestamp_utc": ts.isoformat(),
            "reason": "user delete",
        })
    except Exception as e:
        logger.warning("[ModelJsonBackup] Index append (delete) failed: %s", e)
    return {
        "success": True,
        "backup_id": backup_id,
        "deleted_file": snapshot_path.name,
    }


def restore_backup(
    backup_id: str,
    *,
    dry_run: bool = False,
    source: str = "api",
    operator: str = "system",
) -> Dict[str, Any]:
    """
    恢复指定备份。dry_run 时仅校验不写入。
    恢复前会先对当前 model.json 做一次保护性备份（见文档 §8.1）。
    返回 { success, model_id, restored_file, protected_backup_id? } 或 { success: False, error }。
    """
    found = _find_snapshot_path_by_backup_id(backup_id)
    if not found:
        return {"success": False, "error": f"backup not found: {backup_id}"}
    model_id, snapshot_path, expected_sha = found
    try:
        content = read_snapshot_file(snapshot_path)
    except Exception as e:
        return {"success": False, "error": f"read snapshot: {e}"}
    sha_stored = hashlib.sha256(content).hexdigest()
    if expected_sha and expected_sha != sha_stored:
        return {"success": False, "error": "snapshot hash mismatch (file may be corrupted)"}
    data = json.loads(content.decode("utf-8"))
    if not _validate_schema(data):
        return {"success": False, "error": "snapshot schema invalid or missing model_id"}
    target_path = resolve_model_json_path(model_id)
    if not target_path or not target_path.exists():
        return {"success": False, "error": f"target model.json not found for {model_id}"}
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "model_id": model_id,
            "restored_file": snapshot_path.name,
            "sha256": sha_stored,
        }
    # 写前备份当前版本（回滚保护，文档 §8.1）
    protect_id = None
    try:
        current_content = target_path.read_bytes()
        ts = datetime.now(timezone.utc)
        dest_path, sha_protect, h8 = write_snapshot(model_id, current_content, timestamp_utc=ts)
        protect_id = _backup_id(ts, h8)
        append_index_event({
            "event_id": _event_id(),
            "backup_id": protect_id,
            "model_id": model_id,
            "action": "create",
            "operator": operator,
            "source": source,
            "after_hash": sha_protect,
            "backup_file": dest_path.name,
            "timestamp_utc": ts.isoformat(),
            "reason": "pre-restore protection",
        })
    except Exception as e:
        logger.warning("[ModelJsonBackup] Pre-restore backup failed: %s", e)
    # 覆盖目标 model.json（原子写入：临时文件 -> fsync -> rename）
    tmp = target_path.with_suffix(".json.tmp." + hashlib.sha256(backup_id.encode()).hexdigest()[:8])
    try:
        with open(tmp, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(target_path)
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return {"success": False, "error": f"write target: {e}"}
    try:
        append_index_event({
            "event_id": _event_id(),
            "backup_id": backup_id,
            "model_id": model_id,
            "action": "restore",
            "operator": operator,
            "source": source,
            "backup_file": snapshot_path.name,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "reason": "",
        })
    except Exception as e:
        logger.warning("[ModelJsonBackup] Restore index append failed (restore already applied): %s", e)
    return {
        "success": True,
        "model_id": model_id,
        "restored_file": snapshot_path.name,
        "sha256": sha_stored,
        "protected_backup_id": protect_id,
    }


# 保留策略（文档 §6）：7d 全留，8-30d 每日 1 份，31-180d 每周 1 份，超过 180d 删除
RETENTION_DAYS_ALL = 7
RETENTION_DAYS_DAILY = 30
RETENTION_DAYS_WEEKLY = 180


def _model_ids_from_index(limit: int = 100000) -> Set[str]:
    """从索引中取有 backup_file 的 event 的 model_id 集合。保留策略用较大 limit 避免漏掉仅含旧备份的模型。"""
    events = parse_index_events(model_id=None, limit=limit)
    return {ev["model_id"] for ev in events if ev.get("model_id") and ev.get("backup_file")}


def _backup_id_from_snapshot_path(path: Path, model_id: str) -> Optional[str]:
    """从索引中根据 backup_file 名与 model_id 反查 backup_id。"""
    fname = path.name
    events = parse_index_events(model_id=model_id, limit=2000)
    for ev in events:
        if ev.get("backup_file") == fname and ev.get("backup_id"):
            return ev["backup_id"]
    return None


def retention_dry_run(model_id: Optional[str] = None) -> Dict[str, Any]:
    """
    保留策略 dry-run：返回将被删除的快照列表，不实际删除。
    策略：7d 内全留，8-30d 每日留 1 份，31-180d 每周留 1 份，超过 180d 删除。
    返回 { to_delete: [{ model_id, file, backup_id?, timestamp_utc }], policy }。
    """
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=RETENTION_DAYS_ALL)
    cutoff_30d = now - timedelta(days=RETENTION_DAYS_DAILY)
    cutoff_180d = now - timedelta(days=RETENTION_DAYS_WEEKLY)

    model_ids = list(_model_ids_from_index())
    if model_id:
        model_ids = [m for m in model_ids if m == model_id]
    to_delete: List[Dict[str, Any]] = []
    kept_count = 0

    for mid in model_ids:
        files = list_snapshot_files_for_model(mid)
        by_ts: List[Tuple[datetime, Path]] = []
        for p in files:
            ts = snapshot_file_timestamp(p)
            if ts is None:
                continue
            by_ts.append((ts, p))
        by_ts.sort(key=lambda x: x[0], reverse=True)  # 新在前

        within_7d: List[Tuple[datetime, Path]] = []
        day_8_30: Dict[str, Path] = {}  # date_str -> latest path that day
        week_31_180: Dict[Tuple[int, int], Path] = {}  # (year, isoweek) -> latest path

        for ts, p in by_ts:
            if ts >= cutoff_7d:
                within_7d.append((ts, p))
                kept_count += 1
                continue
            if ts >= cutoff_30d:
                day_key = ts.strftime("%Y-%m-%d")
                if day_key not in day_8_30:
                    day_8_30[day_key] = p
                    kept_count += 1
                else:
                    to_delete.append({"model_id": mid, "file": p.name, "timestamp_utc": ts.isoformat()})
                continue
            if ts >= cutoff_180d:
                y, w = ts.isocalendar()[0], ts.isocalendar()[1]
                wk = (y, w)
                if wk not in week_31_180:
                    week_31_180[wk] = p
                    kept_count += 1
                else:
                    to_delete.append({"model_id": mid, "file": p.name, "timestamp_utc": ts.isoformat()})
                continue
            to_delete.append({"model_id": mid, "file": p.name, "timestamp_utc": ts.isoformat()})

    for item in to_delete:
        p = resolve_snapshot_path(item["model_id"], item["file"])
        if p is None:
            continue
        bid = _backup_id_from_snapshot_path(p, item["model_id"])
        if bid:
            item["backup_id"] = bid

    return {
        "to_delete": to_delete,
        "to_delete_count": len(to_delete),
        "kept_count": kept_count,
        "policy": f"{RETENTION_DAYS_ALL}d_all, {RETENTION_DAYS_DAILY}d_daily, {RETENTION_DAYS_WEEKLY}d_weekly",
    }


def cleanup_retention(
    dry_run: bool = True,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    按保留策略清理快照文件（仅删快照，不删索引）。dry_run 时只返回报告不删除。
    """
    report = retention_dry_run(model_id=model_id)
    if dry_run:
        return {"dry_run": True, **report}
    deleted = 0
    errors = []
    for item in report["to_delete"]:
        mid = item["model_id"]
        fname = item["file"]
        path = resolve_snapshot_path(mid, fname)
        if not path:
            continue
        try:
            path.unlink()
            deleted += 1
        except Exception as e:
            errors.append({"model_id": mid, "file": fname, "error": str(e)})
    return {
        "dry_run": False,
        "deleted_count": deleted,
        "errors": errors,
        "to_delete_count": report["to_delete_count"],
    }


def run_daily_snapshot() -> Dict[str, Any]:
    """
    执行定时全量快照并写入当日 manifest（阶段 2）。
    返回 create_all 结果，并写入 manifests/daily_snapshot_<yyyyMMdd>.json。
    """
    result = create_all_backups(reason="daily_snapshot", source="scheduler")
    created = result.get("created") or []
    if created:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        write_daily_manifest(today, created)
        result["daily_manifest_date"] = today
    return result


def restore_batch(
    target_timestamp_utc: str,
    model_ids: Optional[List[str]] = None,
    dry_run: bool = False,
    source: str = "api",
) -> Dict[str, Any]:
    """
    批量回滚：将指定模型（或全部有备份的模型）恢复到目标时间点前最近一次备份。
    target_timestamp_utc 为 ISO 时间串（如 2026-03-12T00:00:00Z）。
    返回 { success, restored: [{ model_id, backup_id }], failed: [{ model_id, error }] }。
    """
    try:
        target = datetime.fromisoformat(target_timestamp_utc.replace("Z", "+00:00"))
    except Exception:
        return {"success": False, "error": "invalid target_timestamp_utc"}
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    events = parse_index_events(model_id=None, limit=10000)
    # 有 backup_file 的 create/restore 事件，且 timestamp_utc <= target，按 model_id 取最新
    by_model: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        if ev.get("action") not in ("create", "restore") or not ev.get("backup_file") or not ev.get("model_id"):
            continue
        try:
            ts = datetime.fromisoformat((ev.get("timestamp_utc") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if ts > target:
            continue
        mid = ev["model_id"]
        if model_ids and mid not in model_ids:
            continue
        if mid not in by_model or ts > datetime.fromisoformat((by_model[mid].get("timestamp_utc") or "").replace("Z", "+00:00")):
            by_model[mid] = ev
    restored = []
    failed = []
    for mid, ev in by_model.items():
        backup_id = ev.get("backup_id")
        if not backup_id:
            failed.append({"model_id": mid, "error": "no backup_id"})
            continue
        if dry_run:
            restored.append({"model_id": mid, "backup_id": backup_id, "dry_run": True})
            continue
        out = restore_backup(backup_id, dry_run=False, source=source)
        if out.get("success"):
            restored.append({"model_id": mid, "backup_id": backup_id})
        else:
            failed.append({"model_id": mid, "error": out.get("error", "unknown")})
    return {"success": True, "restored": restored, "failed": failed}
