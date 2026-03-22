"""
Alembic 迁移环境配置。

使用 core.data.base 的 engine 与 metadata，与 ORM 迁移计划 ADR 一致。
运行方式：在 backend 目录下执行 `alembic -c alembic.ini ...`（prepend_sys_path = . 已确保可导入 config、core）。
"""
from logging.config import fileConfig

from alembic import context

# 使用 core.data.base 的引擎与元数据（唯一数据源，避免重复配置）
from core.data.base import Base, get_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 供 autogenerate 使用：扫描 Base 下所有已注册的 ORM 模型
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline 模式：仅生成 SQL，不连接数据库。URL 与 base 一致。"""
    url = str(get_engine().url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online 模式：使用 core.data.base 的 engine 执行迁移。"""
    connectable = get_engine()

    with connectable.connect() as connection:
        # 加载 sqlite-vec 扩展（如果可用），避免 autogenerate 时检查虚拟表报错
        try:
            import sqlite_vec  # type: ignore
            # 使用原始连接加载扩展
            raw_conn = connection.connection.dbapi_connection
            raw_conn.enable_load_extension(True)
            try:
                sqlite_vec.load(raw_conn)  # type: ignore
            finally:
                raw_conn.enable_load_extension(False)
        except Exception:
            pass  # sqlite-vec 不可用时忽略

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
