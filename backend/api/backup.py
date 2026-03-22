"""
数据库备份 API
"""
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import settings
from core.backup import (
    BackupConfig,
    BackupFrequency,
    BackupManager,
    BackupMode,
    BackupStatus,
    BackupType,
    DatabaseType,
)
from core.backup.models import BackupMetadata
from log import logger

router = APIRouter(prefix="/api/backup", tags=["backup"])

# 全局备份管理器实例
_backup_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    """获取备份管理器实例（单例）"""
    global _backup_manager
    if _backup_manager is None:
        # 获取数据库路径
        db_path = (
            Path(__file__).resolve().parents[1] / "data" / "platform.db"
            if not settings.db_path
            else Path(settings.db_path)
        )

        # 从系统设置加载备份配置
        from core.system.settings_store import get_system_settings_store
        store = get_system_settings_store()
        db_settings = store.get_all_settings()

        # 构建备份配置
        config = BackupConfig(
            enabled=db_settings.get("backupEnabled", False),
            frequency=BackupFrequency(
                db_settings.get("backupFrequency", BackupFrequency.MANUAL.value)
            ),
            retention_count=db_settings.get("backupRetentionCount", 10),
            backup_directory=db_settings.get(
                "backupDirectory", "~/.local-ai/backups/"
            ),
            backup_mode=BackupMode(
                db_settings.get("backupMode", BackupMode.LOCAL_SNAPSHOT.value)
            ),
            database_type=DatabaseType(
                db_settings.get("databaseType", DatabaseType.SQLITE.value)
            ),
        )

        # 创建备份管理器
        _backup_manager = BackupManager.create_default_manager(db_path, config)

        # 应用启动时检查并执行自动备份
        try:
            result = _backup_manager.check_and_perform_auto_backup()
            if result and result.success:
                logger.info(
                    f"[BackupAPI] Auto backup created on startup: {result.backup_path}"
                )
        except Exception as e:
            logger.warning(f"[BackupAPI] Auto backup check failed: {e}")

    return _backup_manager


class BackupConfigRequest(BaseModel):
    """备份配置请求"""
    enabled: bool
    frequency: str  # 'on_start' | 'daily' | 'weekly' | 'manual'
    retention_count: int
    backup_directory: str
    auto_delete: Optional[bool] = True  # 前端传递，但后端通过 retention_count 控制


class DatabaseStatusResponse(BaseModel):
    """数据库状态响应"""
    type: str
    path: str
    size: str  # 格式化的文件大小，如 "45.2 MB"
    size_bytes: int
    last_backup_time: Optional[str]  # ISO 格式时间戳
    backup_status: str  # 'enabled' | 'disabled'


@router.get("/status")
async def get_database_status():
    """获取数据库状态"""
    try:
        manager = get_backup_manager()
        db_path = manager.strategy.get_database_path()

        # 获取数据库文件大小
        size_bytes = db_path.stat().st_size if db_path.exists() else 0
        size_mb = round(size_bytes / (1024 * 1024), 2)
        size_str = f"{size_mb} MB"

        # 获取最后一次备份时间
        backups = manager.list_backups(status=BackupStatus.SUCCESS, limit=1)
        last_backup_time = (
            backups[0].created_at.isoformat() if backups else None
        )

        # 获取备份状态
        backup_status = "enabled" if manager.config.enabled else "disabled"

        return DatabaseStatusResponse(
            type="SQLite",  # 当前固定为 SQLite
            path=str(db_path),
            size=size_str,
            size_bytes=size_bytes,
            last_backup_time=last_backup_time,
            backup_status=backup_status,
        )
    except Exception as e:
        logger.error(f"[BackupAPI] Failed to get database status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_backup_config():
    """获取备份配置"""
    try:
        manager = get_backup_manager()
        config = manager.config

        return {
            "enabled": config.enabled,
            "frequency": config.frequency.value,
            "retention_count": config.retention_count,
            "backup_directory": config.backup_directory,
            "auto_delete": True,  # 始终为 True，通过 retention_count 控制
            "mode": config.backup_mode.value,
            "database_type": config.database_type.value,
        }
    except Exception as e:
        logger.error(f"[BackupAPI] Failed to get backup config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config")
async def update_backup_config(config_data: BackupConfigRequest):
    """更新备份配置"""
    try:
        manager = get_backup_manager()

        # 更新配置
        manager.config.enabled = config_data.enabled
        manager.config.frequency = BackupFrequency(config_data.frequency)
        manager.config.retention_count = config_data.retention_count
        
        # 如果备份目录改变，需要更新管理器
        if manager.config.backup_directory != config_data.backup_directory:
            manager.update_backup_directory(config_data.backup_directory)
        else:
            manager.config.backup_directory = config_data.backup_directory

        # 保存到系统设置
        from core.system.settings_store import get_system_settings_store
        store = get_system_settings_store()
        store.set_setting("backupEnabled", config_data.enabled)
        store.set_setting("backupFrequency", config_data.frequency)
        store.set_setting("backupRetentionCount", config_data.retention_count)
        store.set_setting("backupDirectory", config_data.backup_directory)

        logger.info(f"[BackupAPI] Backup config updated: {config_data.dict()}")

        return {"success": True}
    except Exception as e:
        logger.error(
            f"[BackupAPI] Failed to update backup config: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_backup():
    """手动创建备份"""
    try:
        manager = get_backup_manager()
        result = manager.create_backup(BackupType.MANUAL)

        if result.success:
            return {
                "success": True,
                "backup_id": result.backup_id,
                "backup_path": str(result.backup_path),
                "size": result.size,
                "size_mb": round(result.size / (1024 * 1024), 2) if result.size else None,
                "duration_seconds": result.duration_seconds,
            }
        else:
            raise HTTPException(
                status_code=500, detail=result.error_message or "Backup failed"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[BackupAPI] Failed to create backup: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restore/{backup_id}")
async def restore_backup(backup_id: str):
    """恢复备份"""
    try:
        manager = get_backup_manager()
        result = manager.restore_backup(backup_id)

        if result.success:
            return {
                "success": True,
                "status": result.status.value,
                "duration_seconds": result.duration_seconds,
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=result.error_message or "Restore failed",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[BackupAPI] Failed to restore backup {backup_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def list_backups():
    """列出备份历史"""
    try:
        manager = get_backup_manager()
        backups = manager.list_backups()

        return [
            {
                "id": backup.id,
                "date": backup.created_at.isoformat(),
                "size": f"{round(backup.size / (1024 * 1024), 2)} MB",
                "size_bytes": backup.size,
                "type": backup.type.value,
                "status": backup.status.value,
                "error_message": backup.error_message,
            }
            for backup in backups
        ]
    except Exception as e:
        logger.error(f"[BackupAPI] Failed to list backups: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{backup_id}")
async def delete_backup(backup_id: str):
    """删除备份"""
    try:
        manager = get_backup_manager()
        success = manager.delete_backup(backup_id)

        if success:
            return {"success": True}
        else:
            raise HTTPException(status_code=404, detail="Backup not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[BackupAPI] Failed to delete backup {backup_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/browse-directory")
async def browse_directory():
    """浏览备份目录（复用系统 API 的逻辑）"""
    import platform
    import subprocess
    import asyncio

    system = platform.system()
    try:
        if system == "Darwin":
            cmd = 'osascript -e "POSIX path of (choose folder with prompt \\"Select Backup Directory:\\")"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {"path": stdout.decode().strip()}
        elif system == "Windows":
            cmd = 'powershell.exe -NoProfile -Command "& { $app = New-Object -ComObject Shell.Application; $folder = $app.BrowseForFolder(0, \'Select Backup Directory\', 0); if ($folder) { $folder.Self.Path } }"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {"path": stdout.decode().strip()}
    except Exception as e:
        logger.error(f"[BackupAPI] Browse directory failed: {e}")

    return {"path": None}
