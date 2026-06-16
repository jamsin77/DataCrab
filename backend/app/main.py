"""DataCrab 数据智能应用 - 主入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from app.core.database import engine, Base
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_skills)
    logger.info("数据库表已创建")
    yield
    logger.info("应用关闭")


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


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="DataCrab 数据智能应用 API",
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
    )
