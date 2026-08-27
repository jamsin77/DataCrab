"""数据库连接和会话管理"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from typing import AsyncGenerator

from app.core.config import settings

# SQLite不支持pool_size参数，需要条件配置
_is_sqlite = "sqlite" in settings.DATABASE_URL

engine_kwargs = {"echo": False}
if _is_sqlite:
    # SQLite busy timeout：等待锁释放而非立即报错（60秒）
    # 30秒在 Pipeline 并发执行 + task_runner 调度扫描时仍会超时，提升到60秒
    engine_kwargs["connect_args"] = {"timeout": 120}
else:
    engine_kwargs["pool_size"] = settings.DATABASE_POOL_SIZE
    engine_kwargs["max_overflow"] = settings.DATABASE_MAX_OVERFLOW

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# SQLite 开启 WAL 模式：允许读写并发，避免流式响应持有 session 期间写操作 database is locked
if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=120000")
        cursor.close()

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """ORM基类"""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
