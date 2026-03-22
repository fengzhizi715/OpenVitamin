# 数据库备份系统

可扩展的数据库备份架构，支持多种数据库类型和备份模式。

## 架构设计

### 1. 策略模式（Strategy Pattern）

所有备份操作通过 `BackupStrategy` 接口实现，支持：
- **SQLiteBackupStrategy**: SQLite 文件快照备份（当前实现）
- **PostgreSQLBackupStrategy**: PostgreSQL 逻辑备份（未来扩展）
- **MySQLBackupStrategy**: MySQL 逻辑备份（未来扩展）
- **CloudBackupStrategy**: 云存储备份（未来扩展）

### 2. 核心组件

- **BackupStrategy**: 备份策略接口
- **BackupManager**: 备份管理器（管理策略、自动备份、历史记录）
- **BackupConfig**: 备份配置
- **BackupMetadata**: 备份元数据
- **BackupResult / RestoreResult**: 操作结果

## 使用示例

### 基本使用

```python
from pathlib import Path
from core.backup import (
    BackupManager,
    BackupConfig,
    BackupFrequency,
    BackupType,
    SQLiteBackupStrategy,
)

# 1. 创建备份配置
config = BackupConfig(
    enabled=True,
    frequency=BackupFrequency.DAILY,
    retention_count=10,
    backup_directory="~/.local-ai/backups/",
)

# 2. 创建备份策略
database_path = Path("/path/to/platform.db")
strategy = SQLiteBackupStrategy(database_path)

# 3. 创建备份管理器
manager = BackupManager(strategy=strategy, config=config)

# 4. 手动创建备份
result = manager.create_backup(BackupType.MANUAL)
if result.success:
    print(f"Backup created: {result.backup_path}")

# 5. 列出备份历史
backups = manager.list_backups()
for backup in backups:
    print(f"{backup.id}: {backup.created_at} - {backup.size_mb} MB")

# 6. 恢复备份
restore_result = manager.restore_backup(backup_id="backup-id")
if restore_result.success:
    print("Backup restored successfully")

# 7. 删除备份
manager.delete_backup(backup_id="backup-id")
```

### 便捷方法

```python
from core.backup import BackupManager

# 使用默认配置创建 SQLite 备份管理器
database_path = Path("/path/to/platform.db")
manager = BackupManager.create_default_manager(database_path)
```

### 自动备份

```python
# 在应用启动时检查并执行自动备份
result = manager.check_and_perform_auto_backup()
if result:
    print(f"Auto backup created: {result.backup_path}")
```

## 扩展指南

### 实现新的备份策略

1. 继承 `BackupStrategy` 接口
2. 实现 `backup()`, `restore()`, `validate_backup()`, `get_database_path()` 方法
3. 在 `BackupManager` 中使用新策略

示例（PostgreSQL 逻辑备份）：

```python
from core.backup.strategy import BackupStrategy
from core.backup.models import BackupResult, RestoreResult

class PostgreSQLBackupStrategy(BackupStrategy):
    def backup(self, backup_path: Path) -> BackupResult:
        # 使用 pg_dump 执行逻辑备份
        # ...
        pass
    
    def restore(self, backup_path: Path) -> RestoreResult:
        # 使用 psql 执行恢复
        # ...
        pass
    
    def validate_backup(self, backup_path: Path) -> bool:
        # 验证备份文件
        # ...
        pass
    
    def get_database_path(self) -> Path:
        # 返回数据库连接信息（PostgreSQL 使用连接字符串）
        # ...
        pass
```

## 线程安全

所有备份和恢复操作都通过 `threading.Lock` 保证线程安全，确保同一时间只有一个备份/恢复操作在执行。

## 错误处理

所有操作都返回结构化的结果对象（`BackupResult` / `RestoreResult`），包含：
- `success`: 操作是否成功
- `error_message`: 错误信息（如果失败）
- `duration_seconds`: 操作耗时
- 其他相关信息

## 保留策略

备份管理器自动执行保留策略：
- 只保留最近 N 个成功备份（由 `retention_count` 配置）
- 自动删除超出保留数量的旧备份
- 备份和元数据同步删除

## 备份元数据

备份元数据存储在独立的 SQLite 数据库中（`backup_metadata.db`），包含：
- 备份 ID
- 创建时间
- 文件大小
- 备份类型（自动/手动）
- 备份状态（成功/失败）
- 文件路径
- 错误信息（如果失败）
