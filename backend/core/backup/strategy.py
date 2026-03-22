"""
备份策略接口

所有备份策略必须实现此接口，以支持不同数据库类型的备份。
"""
from abc import ABC, abstractmethod
from pathlib import Path

from .models import BackupResult, RestoreResult


class BackupStrategy(ABC):
    """备份策略接口"""

    @abstractmethod
    def backup(self, backup_path: Path) -> BackupResult:
        """
        执行备份

        Args:
            backup_path: 备份文件保存路径

        Returns:
            BackupResult: 备份结果
        """
        pass

    @abstractmethod
    def restore(self, backup_path: Path) -> RestoreResult:
        """
        恢复备份

        Args:
            backup_path: 备份文件路径

        Returns:
            RestoreResult: 恢复结果
        """
        pass

    @abstractmethod
    def validate_backup(self, backup_path: Path) -> bool:
        """
        验证备份文件是否有效

        Args:
            backup_path: 备份文件路径

        Returns:
            bool: 备份文件是否有效
        """
        pass

    @abstractmethod
    def get_database_path(self) -> Path:
        """
        获取当前数据库路径

        Returns:
            Path: 数据库文件路径
        """
        pass
