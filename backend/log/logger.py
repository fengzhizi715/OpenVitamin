"""
平台统一日志：控制台 + 文件轮转 + 结构化日志

- 标准 logger：支持控制台与按天轮转文件（保留 30 天）
- log_structured：单行 JSON 结构化日志，全平台可用，便于解析与检索
"""
import datetime
import json
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any


def _default_log_dir() -> Path:
    """日志目录：项目根目录/logs（backend/log/logger.py -> backend -> 项目根）"""
    this_file = Path(__file__).resolve()
    backend_dir = this_file.parent.parent  # backend
    root_dir = backend_dir.parent          # 项目根目录
    return root_dir / "logs"


def setup_logger(
    name: str = "ai_platform",
    log_dir: Path | str | None = None,
    file_basename: str = "app.log",
    backup_count: int = 30,
) -> logging.Logger:
    """
    创建并配置根 logger。

    - 控制台：INFO 及以上
    - 文件：按天轮转，保留 backup_count 天
    """
    log_dir = Path(log_dir) if log_dir else _default_log_dir()
    log_dir = log_dir.resolve()
    log_file = log_dir / file_basename
    log_file = log_file.resolve()

    if not log_dir.exists():
        os.makedirs(log_dir, exist_ok=True)

    log = logging.getLogger(name)
    log.setLevel(logging.DEBUG)

    if log.handlers:
        log.handlers.clear()

    formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    log.addHandler(console)

    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        atTime=datetime.time(0, 0, 0),
    )
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)

    log.propagate = False
    return log


# 全局 logger 实例
logger = setup_logger()


def log_structured(
    component: str,
    event: str,
    level: str = "info",
    **kwargs: Any,
) -> None:
    """
    输出结构化日志，全平台可用。

    格式：单行 JSON，包含 component / event 及传入键值对，便于日志聚合与检索。
    敏感或过长字段应在调用方截断后再传入。
    """
    payload = {"component": component, "event": event, **kwargs}
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        line = json.dumps({"component": component, "event": event, "log_error": "serialization_failed"})
    log_fn = getattr(logger, level, logger.info)
    log_fn(line)
