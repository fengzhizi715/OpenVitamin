"""
数据库连接与 Session 管理
优化并发控制：
1. WAL 模式支持更好的并发读写
2. 忙时重试机制
3. 超时控制
4. 线程安全配置
"""
from pathlib import Path
from typing import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.exc import OperationalError

from config.settings import settings
from log import logger

Base = declarative_base()
metadata = MetaData()


def get_db_path() -> Path:
    """获取数据库路径"""
    if settings.db_path:
        return Path(settings.db_path)
    root = Path(__file__).resolve().parents[3]
    return root / "backend" / "data" / "platform.db"


def create_engine_instance():
    """创建数据库引擎（优化并发配置）"""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{db_path}"
    
    # SQLite 并发优化配置
    engine = create_engine(
        db_url,
        connect_args={
            "check_same_thread": False,  # 允许多线程访问
            "timeout": 30.0,  # 锁等待超时（秒）
        },
        echo=False,
        pool_pre_ping=True,  # 连接前健康检查
        pool_recycle=3600,  # 1 小时回收连接
        max_overflow=10,  # 允许额外连接数
        pool_size=5,  # 基础连接池大小
    )
    
    # 启用 WAL 模式以提升并发性能
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA busy_timeout=30000"))  # 30 秒忙等待
            conn.execute(text("PRAGMA cache_size=-64000"))  # 64MB 缓存
            conn.commit()
        logger.info("[Data] SQLite concurrency optimizations enabled (WAL mode)")
    except Exception as e:
        logger.warning(f"[Data] Failed to enable WAL mode: {e}")
    
    return engine


_engine = create_engine_instance()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=_engine,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话（依赖注入）。用法：FastAPI Depends(get_db)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session(retry_count: int = 3, retry_delay: float = 0.1) -> Iterator[Session]:
    """
    获取数据库会话（非 FastAPI，带重试机制）
    
    Args:
        retry_count: 重试次数（遇到 OperationalError 时）
        retry_delay: 重试延迟（秒）
    
    Usage:
        with db_session() as db:
            # 执行数据库操作
            pass
    """
    # 注意：@contextmanager 只能 yield 一次。旧实现的 while-retry 会在 commit 失败后再次 yield，
    # 导致 "generator didn't stop"。这里改为单次事务，依赖 SQLite busy_timeout/WAL 处理锁等待。
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except OperationalError as e:
        logger.error(f"[Data] Database operational error: {e}")
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"[Data] Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """初始化数据库（创建所有已注册的 ORM 表）"""
    Base.metadata.create_all(bind=_engine)
    logger.info("[Data] Database tables created")


def get_engine():
    """获取引擎（用于 Alembic、迁移脚本等）"""
    return _engine
