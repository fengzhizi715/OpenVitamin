"""
备份系统数据模型
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class BackupFrequency(str, Enum):
    """备份频率"""
    ON_START = "on_start"  # 应用启动时
    DAILY = "daily"  # 每日
    WEEKLY = "weekly"  # 每周
    MANUAL = "manual"  # 仅手动


class BackupMode(str, Enum):
    """备份模式（扩展预留）"""
    LOCAL_SNAPSHOT = "local_snapshot"  # 本地文件快照（SQLite）
    LOGICAL_DUMP = "logical_dump"  # 逻辑备份（PostgreSQL/MySQL）
    CLOUD = "cloud"  # 云存储备份（S3/MinIO）


class DatabaseType(str, Enum):
    """数据库类型（扩展预留）"""
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


class BackupType(str, Enum):
    """备份类型"""
    AUTO = "auto"  # 自动备份
    MANUAL = "manual"  # 手动备份


class BackupStatus(str, Enum):
    """备份状态"""
    SUCCESS = "success"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"


class RestoreStatus(str, Enum):
    """恢复状态"""
    SUCCESS = "success"
    FAILED = "failed"
    VALIDATION_FAILED = "validation_failed"


@dataclass
class BackupConfig:
    """备份配置"""
    enabled: bool = False
    frequency: BackupFrequency = BackupFrequency.MANUAL
    retention_count: int = 10
    backup_directory: str = "~/.local-ai/backups/"
    backup_mode: BackupMode = BackupMode.LOCAL_SNAPSHOT
    database_type: DatabaseType = DatabaseType.SQLITE

    def __post_init__(self):
        """验证配置"""
        if self.retention_count < 1:
            raise ValueError("retention_count must be >= 1")
        if not self.backup_directory:
            raise ValueError("backup_directory cannot be empty")


@dataclass
class BackupMetadata:
    """备份元数据"""
    id: str
    created_at: datetime
    size: int  # 字节数
    type: BackupType
    status: BackupStatus
    path: Path
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "size": self.size,
            "size_mb": round(self.size / (1024 * 1024), 2),
            "type": self.type.value,
            "status": self.status.value,
            "path": str(self.path),
            "error_message": self.error_message,
        }


@dataclass
class BackupResult:
    """备份结果"""
    success: bool
    backup_id: Optional[str] = None
    backup_path: Optional[Path] = None
    size: Optional[int] = None
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "success": self.success,
            "backup_id": self.backup_id,
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "size": self.size,
            "size_mb": round(self.size / (1024 * 1024), 2) if self.size else None,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class RestoreResult:
    """恢复结果"""
    success: bool
    status: RestoreStatus
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = None
    backup_id: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "success": self.success,
            "status": self.status.value,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "backup_id": self.backup_id,
        }
