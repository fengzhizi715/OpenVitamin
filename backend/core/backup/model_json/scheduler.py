"""
model.json 定时全量快照（阶段 2）。
在配置的 UTC 时间（如 02:00）执行 run_daily_snapshot，写入当日 manifest。
run_daily_snapshot 为同步阻塞，放至 executor 避免阻塞事件循环。
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from log import logger


def _parse_time(s: str) -> Optional[tuple[int, int, int]]:
    """解析 "02:00" 或 "02:00:00" 为 (h, m, s)。"""
    s = (s or "").strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1]), 0
        except ValueError:
            return None
    if len(parts) == 3:
        try:
            return int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            return None
    return None


def _next_run_at(now: datetime, hour: int, minute: int, second: int) -> datetime:
    """下次运行时间：今日或明日该时刻（UTC）。"""
    target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


async def run_daily_snapshot_loop() -> None:
    """
    后台循环：在 settings 配置的 UTC 时间执行每日全量快照。
    若未启用或时间格式无效，则直接退出。
    """
    from config.settings import settings
    enabled = getattr(settings, "model_json_backup_daily_enabled", False)
    time_str = getattr(settings, "model_json_backup_daily_time", "02:00") or "02:00"
    if not enabled:
        logger.info("[ModelJsonBackup] Daily snapshot disabled, scheduler not started")
        return
    parsed = _parse_time(time_str)
    if not parsed:
        logger.warning("[ModelJsonBackup] Invalid model_json_backup_daily_time=%r, scheduler not started", time_str)
        return
    h, m, s = parsed
    from .service import run_daily_snapshot
    logger.info("[ModelJsonBackup] Daily snapshot scheduler started (UTC %02d:%02d:%02d)", h, m, s)
    loop = asyncio.get_event_loop()
    while True:
        now = datetime.now(timezone.utc)
        next_at = _next_run_at(now, h, m, s)
        delay = (next_at - now).total_seconds()
        logger.debug("[ModelJsonBackup] Next daily snapshot at %s (in %.0fs)", next_at.isoformat(), delay)
        await asyncio.sleep(delay)
        try:
            result = await loop.run_in_executor(None, run_daily_snapshot)
            logger.info(
                "[ModelJsonBackup] Daily snapshot completed: success_count=%s, failed=%s, manifest=%s",
                result.get("success_count"),
                len(result.get("failed") or []),
                result.get("daily_manifest_date"),
            )
        except Exception as e:
            logger.exception("[ModelJsonBackup] Daily snapshot failed: %s", e)
