"""DataCrab 数据工程智能体 - 主入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from app.core.database import engine, Base, async_session
from app.api.v1.router import api_router
from app.services.task_runner import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_skills)
        await conn.run_sync(_migrate_custom_extensions)
    logger.info("数据库表已创建")
    await _load_custom_extensions()
    await _init_llm_from_db()
    await start_scheduler()
    yield
    await stop_scheduler()
    logger.info("应用关闭")


async def _load_custom_extensions():
    """启动时从数据库加载连接器和 LLM Provider"""
    from sqlalchemy import select as sa_select
    from app.models.custom_extension import LLMProvider
    from app.services.connectors import load_connectors_from_db
    from app.services.llm import load_providers_from_db, register_custom_adapter, llm_manager
    from app.core.crypto import decrypt
    from app.core.config import settings

    # 加载所有 Provider（含 seed 预配置 + DB 中的）
    await load_providers_from_db()

    # 加载有适配器代码的 Provider
    async with async_session() as session:
        result = await session.execute(
            sa_select(LLMProvider).where(LLMProvider.is_active == True, LLMProvider.code != None)
        )
        for p in result.scalars().all():
            try:
                register_custom_adapter(p.provider_name, p.code)
            except Exception as e:
                logger.warning(f"加载 Provider 适配器 {p.provider_name} 失败: {e}")

    # 加载所有连接器（统一从 DB 装载，首次启动 seed 内置连接器）
    await load_connectors_from_db()


async def _init_llm_from_db():
    """从数据库读取解密后的 API Key，初始化 LLM 客户端"""
    from sqlalchemy import select as sa_select
    from app.models.custom_extension import LLMProvider
    from app.services.llm import llm_manager, _parse_fallback_models
    from app.core.crypto import decrypt
    from app.core.config import settings

    async with async_session() as session:
        # 读取主 Provider 的 API Key
        provider_name = settings.LLM_PROVIDER
        result = await session.execute(
            sa_select(LLMProvider).where(LLMProvider.provider_name == provider_name)
        )
        provider_record = result.scalar_one_or_none()
        api_key = ""
        if provider_record and provider_record.api_key_encrypted:
            api_key = decrypt(provider_record.api_key_encrypted)

        # 读取降级模型的 API Key
        fallback_models = _parse_fallback_models(settings.LLM_FALLBACK_MODELS)
        for f in fallback_models:
            fb_provider = f.get("provider", "")
            if fb_provider and not f.get("api_key"):
                fb_result = await session.execute(
                    sa_select(LLMProvider).where(LLMProvider.provider_name == fb_provider)
                )
                fb_record = fb_result.scalar_one_or_none()
                if fb_record and fb_record.api_key_encrypted:
                    f["api_key"] = decrypt(fb_record.api_key_encrypted)

    if api_key:
        try:
            await llm_manager.reinitialize(
                provider=provider_name,
                api_key=api_key,
                api_base=settings.OPENAI_API_BASE or "",
                model=settings.OPENAI_MODEL,
                embedding_model=settings.OPENAI_EMBEDDING_MODEL,
                fallback_models=fallback_models,
            )
            logger.info(f"LLM 客户端已从数据库初始化: provider={provider_name}")
        except Exception as e:
            logger.warning(f"LLM 客户端从数据库初始化失败: {e}")


def _migrate_skills(connection):
    from sqlalchemy import text
    try:
        result = connection.execute(text("PRAGMA table_info(skills)"))
        columns = {row[1] for row in result.fetchall()}
        if "skill_path" not in columns:
            connection.execute(text("ALTER TABLE skills ADD COLUMN skill_path VARCHAR(500)"))
            logger.info("skills表已添加 skill_path 列")
    except Exception as e:
        logger.warning(f"Skills表迁移跳过: {e}")


def _migrate_custom_extensions(connection):
    from sqlalchemy import text
    for table in ("custom_connectors", "llm_providers"):
        try:
            result = connection.execute(text(f"PRAGMA table_info({table})"))
            columns = {row[1] for row in result.fetchall()}
            if "is_public" not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN is_public BOOLEAN DEFAULT 0"))
                logger.info(f"{table}表已添加 is_public 列")
        except Exception as e:
            logger.warning(f"{table}表迁移跳过: {e}")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="DataCrab 数据工程智能体 API",
    lifespan=lifespan,
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        reload_excludes=["*.db", "*.db-journal", "*.db-wal", "*.log"],
    )
