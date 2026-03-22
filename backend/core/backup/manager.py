"""
备份管理器

负责：
- 管理备份策略
- 执行自动备份
- 管理备份历史
- 执行保留策略
"""
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from log import logger

from .models import (
    BackupConfig,
    BackupFrequency,
    BackupMetadata,
    BackupResult,
    BackupStatus,
    BackupType,
    RestoreResult,
)
from .strategy import BackupStrategy
from .sqlite_strategy import SQLiteBackupStrategy


class BackupManager:
    """备份管理器"""

    def __init__(
        self,
        strategy: BackupStrategy,
        config: BackupConfig,
        metadata_db_path: Optional[Path] = None,
    ):
        """
        初始化备份管理器

        Args:
            strategy: 备份策略实例
            config: 备份配置
            metadata_db_path: 备份元数据数据库路径（可选，默认使用备份目录）
        """
        self.strategy = strategy
        self.config = config
        self._lock = threading.Lock()  # 线程安全锁

        # 确定备份目录
        backup_dir = Path(self.config.backup_directory).expanduser().resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        self.backup_directory = backup_dir

        # 确定元数据数据库路径
        if metadata_db_path:
            self.metadata_db_path = Path(metadata_db_path).resolve()
        else:
            self.metadata_db_path = self.backup_directory / "backup_metadata.db"

        # 初始化元数据数据库
        self._init_metadata_db()

        # 从备份历史中加载最后一次自动备份时间
        self._last_auto_backup_time: Optional[datetime] = self._load_last_auto_backup_time()

    def _init_metadata_db(self) -> None:
        """初始化备份元数据数据库"""
        try:
            self.metadata_db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self.metadata_db_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS backup_metadata (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        path TEXT NOT NULL,
                        error_message TEXT
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_backup_metadata_created_at 
                    ON backup_metadata(created_at DESC);
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_backup_metadata_status 
                    ON backup_metadata(status);
                    """
                )
                conn.commit()
        except Exception as e:
            logger.error(
                f"[BackupManager] Failed to initialize metadata database: {str(e)}",
                exc_info=True,
            )
            raise

    def _load_last_auto_backup_time(self) -> Optional[datetime]:
        """从备份历史中加载最后一次成功的自动备份时间"""
        try:
            auto_backups = self.list_backups(status=BackupStatus.SUCCESS)
            # 过滤出自动备份
            auto_backups = [b for b in auto_backups if b.type == BackupType.AUTO]
            if auto_backups:
                # 按创建时间降序排列，取第一个
                auto_backups.sort(key=lambda x: x.created_at, reverse=True)
                return auto_backups[0].created_at
        except Exception as e:
            logger.warning(
                f"[BackupManager] Failed to load last auto backup time: {e}"
            )
        return None

    def create_backup(self, backup_type: BackupType = BackupType.MANUAL) -> BackupResult:
        """
        创建备份

        Args:
            backup_type: 备份类型（自动/手动）

        Returns:
            BackupResult: 备份结果
        """
        # 线程安全：确保同一时间只有一个备份操作
        with self._lock:
            try:
                # 生成备份文件名（带时间戳）
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f"backup_{timestamp}.db"
                backup_path = self.backup_directory / backup_filename

                # 执行备份
                logger.info(
                    f"[BackupManager] Creating {backup_type.value} backup: {backup_path}"
                )
                result = self.strategy.backup(backup_path)

                # 记录备份元数据
                if result.success:
                    metadata = BackupMetadata(
                        id=result.backup_id or str(int(time.time())),
                        created_at=datetime.now(),
                        size=result.size or 0,
                        type=backup_type,
                        status=BackupStatus.SUCCESS,
                        path=backup_path,
                    )
                    self._save_metadata(metadata)

                    # 如果是自动备份，更新最后备份时间
                    if backup_type == BackupType.AUTO:
                        self._last_auto_backup_time = datetime.now()

                    # 执行保留策略清理
                    self._apply_retention_policy()
                else:
                    # 记录失败的备份
                    metadata = BackupMetadata(
                        id=str(int(time.time())),
                        created_at=datetime.now(),
                        size=0,
                        type=backup_type,
                        status=BackupStatus.FAILED,
                        path=backup_path,
                        error_message=result.error_message,
                    )
                    self._save_metadata(metadata)

                return result

            except Exception as e:
                error_msg = f"Failed to create backup: {str(e)}"
                logger.error(f"[BackupManager] {error_msg}", exc_info=True)
                return BackupResult(success=False, error_message=error_msg)

    def restore_backup(self, backup_id: str) -> RestoreResult:
        """
        恢复备份

        Args:
            backup_id: 备份 ID

        Returns:
            RestoreResult: 恢复结果
        """
        # 线程安全：确保同一时间只有一个恢复操作
        with self._lock:
            try:
                # 查找备份元数据
                metadata = self._get_metadata(backup_id)
                if not metadata:
                    error_msg = f"Backup not found: {backup_id}"
                    logger.error(f"[BackupManager] {error_msg}")
                    return RestoreResult(
                        success=False,
                        status=RestoreStatus.VALIDATION_FAILED,
                        error_message=error_msg,
                    )

                # 验证备份文件存在
                if not metadata.path.exists():
                    error_msg = f"Backup file not found: {metadata.path}"
                    logger.error(f"[BackupManager] {error_msg}")
                    return RestoreResult(
                        success=False,
                        status=RestoreStatus.VALIDATION_FAILED,
                        error_message=error_msg,
                    )

                # 执行恢复
                logger.info(
                    f"[BackupManager] Restoring backup: {backup_id} from {metadata.path}"
                )
                result = self.strategy.restore(metadata.path)

                if result.success:
                    logger.info(f"[BackupManager] Backup restored successfully: {backup_id}")
                else:
                    logger.error(
                        f"[BackupManager] Backup restore failed: {backup_id}, "
                        f"error: {result.error_message}"
                    )

                return result

            except Exception as e:
                error_msg = f"Failed to restore backup: {str(e)}"
                logger.error(f"[BackupManager] {error_msg}", exc_info=True)
                return RestoreResult(
                    success=False,
                    status=RestoreStatus.FAILED,
                    error_message=error_msg,
                )

    def list_backups(
        self,
        status: Optional[BackupStatus] = None,
        limit: Optional[int] = None,
    ) -> List[BackupMetadata]:
        """
        列出备份历史

        Args:
            status: 过滤状态（可选）
            limit: 限制返回数量（可选）

        Returns:
            List[BackupMetadata]: 备份元数据列表
        """
        try:
            with sqlite3.connect(str(self.metadata_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                query = "SELECT * FROM backup_metadata"
                params = []

                if status:
                    query += " WHERE status = ?"
                    params.append(status.value)

                query += " ORDER BY created_at DESC"

                if limit:
                    query += " LIMIT ?"
                    params.append(limit)

                cursor = conn.execute(query, params)
                rows = cursor.fetchall()

                backups = []
                for row in rows:
                    try:
                        backup = BackupMetadata(
                            id=row["id"],
                            created_at=datetime.fromisoformat(row["created_at"]),
                            size=row["size"],
                            type=BackupType(row["type"]),
                            status=BackupStatus(row["status"]),
                            path=Path(row["path"]),
                            error_message=row["error_message"],
                        )
                        backups.append(backup)
                    except Exception as e:
                        logger.warning(
                            f"[BackupManager] Failed to parse backup metadata row: {e}"
                        )

                return backups

        except Exception as e:
            logger.error(
                f"[BackupManager] Failed to list backups: {str(e)}", exc_info=True
            )
            return []

    def delete_backup(self, backup_id: str) -> bool:
        """
        删除备份

        Args:
            backup_id: 备份 ID

        Returns:
            bool: 是否删除成功
        """
        try:
            # 查找备份元数据
            metadata = self._get_metadata(backup_id)
            if not metadata:
                logger.warning(f"[BackupManager] Backup not found: {backup_id}")
                return False

            # 删除备份文件
            if metadata.path.exists():
                try:
                    metadata.path.unlink()
                    logger.info(f"[BackupManager] Backup file deleted: {metadata.path}")
                except Exception as e:
                    logger.error(
                        f"[BackupManager] Failed to delete backup file {metadata.path}: {str(e)}",
                        exc_info=True,
                    )
                    return False

            # 删除元数据记录
            with sqlite3.connect(str(self.metadata_db_path)) as conn:
                conn.execute("DELETE FROM backup_metadata WHERE id = ?", (backup_id,))
                conn.commit()

            logger.info(f"[BackupManager] Backup deleted: {backup_id}")
            return True

        except Exception as e:
            logger.error(
                f"[BackupManager] Failed to delete backup: {str(e)}", exc_info=True
            )
            return False

    def check_and_perform_auto_backup(self) -> Optional[BackupResult]:
        """
        检查并执行自动备份（如果需要）

        根据配置的频率判断是否需要执行自动备份。

        Returns:
            Optional[BackupResult]: 如果执行了备份则返回结果，否则返回 None
        """
        if not self.config.enabled:
            return None

        if self.config.frequency == BackupFrequency.MANUAL:
            return None

        # 检查是否需要执行自动备份
        if self.config.frequency == BackupFrequency.ON_START:
            # 启动时备份：如果从未备份过或上次备份不是今天，则执行备份
            if (
                self._last_auto_backup_time is None
                or self._last_auto_backup_time.date() < datetime.now().date()
            ):
                logger.info("[BackupManager] Performing on-start backup")
                return self.create_backup(BackupType.AUTO)

        elif self.config.frequency == BackupFrequency.DAILY:
            # 每日备份：如果从未备份过或上次备份不是今天，则执行备份
            if (
                self._last_auto_backup_time is None
                or self._last_auto_backup_time.date() < datetime.now().date()
            ):
                logger.info("[BackupManager] Performing daily backup")
                return self.create_backup(BackupType.AUTO)

        elif self.config.frequency == BackupFrequency.WEEKLY:
            # 每周备份：如果从未备份过或上次备份超过7天，则执行备份
            if (
                self._last_auto_backup_time is None
                or (datetime.now() - self._last_auto_backup_time).days >= 7
            ):
                logger.info("[BackupManager] Performing weekly backup")
                return self.create_backup(BackupType.AUTO)

        return None

    def _save_metadata(self, metadata: BackupMetadata) -> None:
        """保存备份元数据"""
        try:
            with sqlite3.connect(str(self.metadata_db_path)) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO backup_metadata 
                    (id, created_at, size, type, status, path, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metadata.id,
                        metadata.created_at.isoformat(),
                        metadata.size,
                        metadata.type.value,
                        metadata.status.value,
                        str(metadata.path),
                        metadata.error_message,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(
                f"[BackupManager] Failed to save backup metadata: {str(e)}",
                exc_info=True,
            )

    def _get_metadata(self, backup_id: str) -> Optional[BackupMetadata]:
        """获取备份元数据"""
        try:
            with sqlite3.connect(str(self.metadata_db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM backup_metadata WHERE id = ?", (backup_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return None

                return BackupMetadata(
                    id=row["id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    size=row["size"],
                    type=BackupType(row["type"]),
                    status=BackupStatus(row["status"]),
                    path=Path(row["path"]),
                    error_message=row["error_message"],
                )
        except Exception as e:
            logger.error(
                f"[BackupManager] Failed to get backup metadata: {str(e)}",
                exc_info=True,
            )
            return None

    def update_backup_directory(self, new_directory: str) -> None:
        """
        更新备份目录（配置更改时调用）

        Args:
            new_directory: 新的备份目录路径
        """
        new_backup_dir = Path(new_directory).expanduser().resolve()
        new_backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 如果备份目录改变，需要迁移元数据数据库
        if new_backup_dir != self.backup_directory:
            old_metadata_path = self.metadata_db_path
            new_metadata_path = new_backup_dir / "backup_metadata.db"
            
            # 如果旧元数据数据库存在，尝试复制
            if old_metadata_path.exists() and not new_metadata_path.exists():
                try:
                    import shutil
                    shutil.copy2(old_metadata_path, new_metadata_path)
                    logger.info(
                        f"[BackupManager] Migrated metadata database: "
                        f"{old_metadata_path} -> {new_metadata_path}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[BackupManager] Failed to migrate metadata database: {e}"
                    )
            
            self.backup_directory = new_backup_dir
            self.metadata_db_path = new_metadata_path
            # 确保新元数据数据库已初始化
            self._init_metadata_db()
        
        # 更新配置
        self.config.backup_directory = new_directory

    def _apply_retention_policy(self) -> None:
        """应用保留策略：只保留最近 N 个成功备份"""
        try:
            # 获取所有成功的备份，按创建时间降序排列
            successful_backups = self.list_backups(status=BackupStatus.SUCCESS)

            # 如果备份数量超过保留数量，删除多余的备份
            if len(successful_backups) > self.config.retention_count:
                backups_to_delete = successful_backups[self.config.retention_count :]
                logger.info(
                    f"[BackupManager] Applying retention policy: "
                    f"keeping {self.config.retention_count} backups, "
                    f"deleting {len(backups_to_delete)} old backups"
                )

                for backup in backups_to_delete:
                    self.delete_backup(backup.id)

        except Exception as e:
            logger.error(
                f"[BackupManager] Failed to apply retention policy: {str(e)}",
                exc_info=True,
            )

    @staticmethod
    def create_default_manager(
        database_path: Path,
        config: Optional[BackupConfig] = None,
    ) -> "BackupManager":
        """
        创建默认的备份管理器（SQLite）

        这是一个便捷方法，用于快速创建 SQLite 备份管理器。

        Args:
            database_path: SQLite 数据库文件路径
            config: 备份配置（可选，默认使用 BackupConfig 默认值）

        Returns:
            BackupManager: 备份管理器实例
        """
        if config is None:
            config = BackupConfig()

        strategy = SQLiteBackupStrategy(database_path)
        return BackupManager(strategy=strategy, config=config)
