"""
SQLite 备份策略实现

使用文件级快照方式备份 SQLite 数据库。
"""
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from log import logger

from .models import BackupResult, RestoreResult, RestoreStatus
from .strategy import BackupStrategy


class SQLiteBackupStrategy(BackupStrategy):
    """SQLite 文件快照备份策略"""

    def __init__(self, database_path: Path):
        """
        初始化 SQLite 备份策略

        Args:
            database_path: SQLite 数据库文件路径
        """
        self.database_path = Path(database_path).resolve()
        if not self.database_path.exists():
            raise FileNotFoundError(f"Database file not found: {self.database_path}")

    def get_database_path(self) -> Path:
        """获取数据库路径"""
        return self.database_path

    def backup(self, backup_path: Path) -> BackupResult:
        """
        执行 SQLite 文件快照备份

        备份流程：
        1. 确保数据库连接安全（WAL checkpoint）
        2. 创建备份目录
        3. 复制数据库文件
        4. 验证备份文件

        Args:
            backup_path: 备份文件保存路径

        Returns:
            BackupResult: 备份结果
        """
        start_time = time.time()

        try:
            # 确保备份目录存在
            backup_path.parent.mkdir(parents=True, exist_ok=True)

            # 1. 执行 WAL checkpoint，确保数据库处于一致状态
            # 这会将 WAL 文件中的更改合并到主数据库文件
            self._checkpoint_wal()

            # 2. 复制数据库文件
            logger.info(f"[Backup] Starting SQLite backup: {self.database_path} -> {backup_path}")
            shutil.copy2(self.database_path, backup_path)

            # 3. 验证备份文件
            if not self.validate_backup(backup_path):
                backup_path.unlink(missing_ok=True)
                error_msg = "Backup file validation failed"
                logger.error(f"[Backup] {error_msg}")
                return BackupResult(
                    success=False,
                    error_message=error_msg,
                    duration_seconds=time.time() - start_time,
                )

            # 4. 获取备份文件大小
            backup_size = backup_path.stat().st_size

            duration = time.time() - start_time
            backup_id = str(uuid.uuid4())

            logger.info(
                f"[Backup] SQLite backup completed successfully: {backup_path} "
                f"({backup_size / (1024 * 1024):.2f} MB, {duration:.2f}s)"
            )

            return BackupResult(
                success=True,
                backup_id=backup_id,
                backup_path=backup_path,
                size=backup_size,
                duration_seconds=duration,
            )

        except Exception as e:
            error_msg = f"Backup failed: {str(e)}"
            logger.error(f"[Backup] {error_msg}", exc_info=True)
            # 清理可能创建的不完整备份文件
            backup_path.unlink(missing_ok=True)
            return BackupResult(
                success=False,
                error_message=error_msg,
                duration_seconds=time.time() - start_time,
            )

    def restore(self, backup_path: Path) -> RestoreResult:
        """
        恢复 SQLite 备份

        恢复流程：
        1. 验证备份文件存在且有效
        2. 创建当前数据库的临时备份（防止恢复失败）
        3. 替换数据库文件
        4. 验证恢复后的数据库

        Args:
            backup_path: 备份文件路径

        Returns:
            RestoreResult: 恢复结果
        """
        start_time = time.time()
        temp_backup_path: Optional[Path] = None

        try:
            # 1. 验证备份文件
            if not backup_path.exists():
                error_msg = f"Backup file not found: {backup_path}"
                logger.error(f"[Restore] {error_msg}")
                return RestoreResult(
                    success=False,
                    status=RestoreStatus.VALIDATION_FAILED,
                    error_message=error_msg,
                    duration_seconds=time.time() - start_time,
                )

            if not self.validate_backup(backup_path):
                error_msg = "Backup file validation failed"
                logger.error(f"[Restore] {error_msg}")
                return RestoreResult(
                    success=False,
                    status=RestoreStatus.VALIDATION_FAILED,
                    error_message=error_msg,
                    duration_seconds=time.time() - start_time,
                )

            # 2. 创建当前数据库的临时备份（防止恢复失败）
            temp_backup_path = self.database_path.with_suffix(
                f".restore_backup.{int(time.time())}.db"
            )
            try:
                if self.database_path.exists():
                    logger.info(
                        f"[Restore] Creating temporary backup of current database: {temp_backup_path}"
                    )
                    shutil.copy2(self.database_path, temp_backup_path)
            except Exception as e:
                error_msg = f"Failed to create temporary backup: {str(e)}"
                logger.error(f"[Restore] {error_msg}", exc_info=True)
                return RestoreResult(
                    success=False,
                    status=RestoreStatus.FAILED,
                    error_message=error_msg,
                    duration_seconds=time.time() - start_time,
                )

            # 3. 关闭所有数据库连接（通过 checkpoint）
            self._checkpoint_wal()

            # 4. 替换数据库文件
            logger.info(
                f"[Restore] Restoring database: {backup_path} -> {self.database_path}"
            )
            shutil.copy2(backup_path, self.database_path)

            # 5. 验证恢复后的数据库
            if not self.validate_backup(self.database_path):
                # 恢复失败，尝试恢复临时备份
                error_msg = "Restored database validation failed"
                logger.error(f"[Restore] {error_msg}")
                if temp_backup_path and temp_backup_path.exists():
                    logger.info(
                        f"[Restore] Attempting to restore from temporary backup: {temp_backup_path}"
                    )
                    try:
                        shutil.copy2(temp_backup_path, self.database_path)
                        logger.info("[Restore] Temporary backup restored successfully")
                    except Exception as restore_error:
                        logger.error(
                            f"[Restore] Failed to restore from temporary backup: {restore_error}",
                            exc_info=True,
                        )
                return RestoreResult(
                    success=False,
                    status=RestoreStatus.FAILED,
                    error_message=error_msg,
                    duration_seconds=time.time() - start_time,
                )

            # 6. 清理临时备份（恢复成功）
            if temp_backup_path and temp_backup_path.exists():
                temp_backup_path.unlink(missing_ok=True)

            duration = time.time() - start_time
            logger.info(
                f"[Restore] Database restored successfully from: {backup_path} ({duration:.2f}s)"
            )

            return RestoreResult(
                success=True,
                status=RestoreStatus.SUCCESS,
                duration_seconds=duration,
            )

        except Exception as e:
            error_msg = f"Restore failed: {str(e)}"
            logger.error(f"[Restore] {error_msg}", exc_info=True)

            # 尝试恢复临时备份
            if temp_backup_path and temp_backup_path.exists():
                try:
                    logger.info(
                        f"[Restore] Attempting to restore from temporary backup: {temp_backup_path}"
                    )
                    shutil.copy2(temp_backup_path, self.database_path)
                    logger.info("[Restore] Temporary backup restored successfully")
                except Exception as restore_error:
                    logger.error(
                        f"[Restore] Failed to restore from temporary backup: {restore_error}",
                        exc_info=True,
                    )

            return RestoreResult(
                success=False,
                status=RestoreStatus.FAILED,
                error_message=error_msg,
                duration_seconds=time.time() - start_time,
            )

    def validate_backup(self, backup_path: Path) -> bool:
        """
        验证备份文件是否有效

        通过尝试打开数据库并执行简单查询来验证。

        Args:
            backup_path: 备份文件路径

        Returns:
            bool: 备份文件是否有效
        """
        if not backup_path.exists():
            return False

        try:
            # 尝试打开数据库并执行简单查询
            conn = sqlite3.connect(str(backup_path))
            try:
                cursor = conn.cursor()
                # 执行简单查询验证数据库完整性
                cursor.execute("SELECT 1")
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                if result and result[0] == "ok":
                    return True
                logger.warning(
                    f"[Backup] Integrity check failed for {backup_path}: {result}"
                )
                return False
            finally:
                conn.close()
        except Exception as e:
            logger.error(
                f"[Backup] Failed to validate backup file {backup_path}: {str(e)}",
                exc_info=True,
            )
            return False

    def _checkpoint_wal(self) -> None:
        """
        执行 WAL checkpoint，确保数据库处于一致状态

        这会将 WAL (Write-Ahead Logging) 文件中的更改合并到主数据库文件，
        确保备份时数据库处于一致状态。
        """
        try:
            conn = sqlite3.connect(str(self.database_path))
            try:
                # 执行 checkpoint，将 WAL 文件中的更改合并到主数据库
                conn.execute("PRAGMA wal_checkpoint(FULL)")
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(
                f"[Backup] WAL checkpoint failed (may not be using WAL mode): {str(e)}"
            )
            # WAL checkpoint 失败不影响备份（可能数据库未使用 WAL 模式）
