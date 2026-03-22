"""
系统全局设置存储（ORM 版本）
"""
import json
from typing import Any, Dict, Optional

from sqlalchemy.dialects.sqlite import insert

from core.data.base import db_session
from core.data.models.system import SystemSetting
from log import logger


class SystemSettingsStore:
    """系统全局设置存储（使用 SQLAlchemy ORM）"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        """获取设置值"""
        try:
            with db_session() as db:
                setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
                if setting:
                    return json.loads(setting.value_json)
        except Exception as e:
            logger.error(f"[SystemSettingsStore] get_setting failed: {e}")
        return default

    def set_setting(self, key: str, value: Any) -> None:
        """设置值（UPSERT）"""
        try:
            val_json = json.dumps(value)
            with db_session() as db:
                stmt = insert(SystemSetting).values(
                    key=key,
                    value_json=val_json,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["key"],
                    set_={
                        "value_json": stmt.excluded.value_json,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
                db.execute(stmt)
        except Exception as e:
            logger.error(f"[SystemSettingsStore] set_setting failed: {e}")

    def get_all_settings(self) -> Dict[str, Any]:
        """获取所有设置"""
        settings = {}
        try:
            with db_session() as db:
                rows = db.query(SystemSetting).all()
                for row in rows:
                    settings[row.key] = json.loads(row.value_json)
        except Exception as e:
            logger.error(f"[SystemSettingsStore] get_all_settings failed: {e}")
        return settings


_store: Optional[SystemSettingsStore] = None


def get_system_settings_store() -> SystemSettingsStore:
    """获取系统设置存储单例"""
    global _store
    if _store is None:
        _store = SystemSettingsStore()
    return _store
