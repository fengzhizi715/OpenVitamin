"""
数据库备份系统

可扩展的备份架构，支持：
- SQLite 文件快照备份（当前）
- PostgreSQL 逻辑备份（未来）
- MySQL 逻辑备份（未来）
- 云存储备份（未来）
"""

from .models import (
    BackupConfig,
    BackupFrequency,
    BackupMode,
    BackupMetadata,
    BackupResult,
    BackupStatus,
    BackupType,
    DatabaseType,
    RestoreResult,
    RestoreStatus,
)
from .manager import BackupManager
from .strategy import BackupStrategy
from .sqlite_strategy import SQLiteBackupStrategy

__all__ = [
    "BackupConfig",
    "BackupFrequency",
    "BackupManager",
    "BackupMetadata",
    "BackupMode",
    "BackupResult",
    "BackupStatus",
    "BackupStrategy",
    "BackupType",
    "DatabaseType",
    "RestoreResult",
    "RestoreStatus",
    "SQLiteBackupStrategy",
]
