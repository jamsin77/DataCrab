"""DataCrab 数据工程智能体 - 主入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from app.core.database import engine, Base, async_session
from app.api.v1.router import api_router
from app.services.task_runner import start_scheduler, stop_scheduler
from app.core.version import get_version

# 启动时动态生成版本号（格式: YYYY.MM.DD.提交次数）
settings.APP_VERSION = get_version()

logger.add("debug_sse.log", filter=lambda r: "[SSE]" in r.get("message", "") or "[SSE-DEBUG]" in r.get("message", "") or "[Inspector-DEBUG]" in r.get("message", "") or "[handoff检查]" in r.get("message", "") or "[platform_issue" in r.get("message", ""), rotation="1 MB")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_skills)
        await conn.run_sync(_migrate_custom_extensions)
        await conn.run_sync(_migrate_builtin_flags)
    logger.info("数据库表已创建")
    await _seed_skills_and_pipelines()
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


def _migrate_builtin_flags(connection):
    from sqlalchemy import text
    for table in ("pipelines", "schedules"):
        try:
            result = connection.execute(text(f"PRAGMA table_info({table})"))
            columns = {row[1] for row in result.fetchall()}
            if "is_builtin" not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN is_builtin BOOLEAN DEFAULT 0"))
                logger.info(f"{table}表已添加 is_builtin 列")
        except Exception as e:
            logger.warning(f"{table}表迁移跳过: {e}")
    try:
        result = connection.execute(text("PRAGMA table_info(schedules)"))
        columns = {row[1] for row in result.fetchall()}
        if "run_mode" not in columns:
            connection.execute(text("ALTER TABLE schedules ADD COLUMN run_mode VARCHAR(20) DEFAULT 'normal'"))
            logger.info("schedules表已添加 run_mode 列")
    except Exception as e:
        logger.warning(f"schedules表 run_mode 迁移跳过: {e}")
    try:
        result = connection.execute(text("PRAGMA table_info(table_metadata)"))
        columns = {row[1] for row in result.fetchall()}
        if "schema_hash" not in columns:
            connection.execute(text("ALTER TABLE table_metadata ADD COLUMN schema_hash VARCHAR(64)"))
            logger.info("table_metadata表已添加 schema_hash 列")
        if "data_updated_at" not in columns:
            connection.execute(text("ALTER TABLE table_metadata ADD COLUMN data_updated_at DATETIME"))
            logger.info("table_metadata表已添加 data_updated_at 列")
    except Exception as e:
        logger.warning(f"table_metadata表迁移跳过: {e}")

    # user_llm_configs / llm_providers 加 vision_model / default_vision_model / default_embedding_model 列
    try:
        result = connection.execute(text("PRAGMA table_info(user_llm_configs)"))
        columns = {row[1] for row in result.fetchall()}
        if "vision_model" not in columns:
            connection.execute(text("ALTER TABLE user_llm_configs ADD COLUMN vision_model VARCHAR(100)"))
            logger.info("user_llm_configs表已添加 vision_model 列")
    except Exception as e:
        logger.warning(f"user_llm_configs表迁移跳过: {e}")

    try:
        result = connection.execute(text("PRAGMA table_info(llm_providers)"))
        columns = {row[1] for row in result.fetchall()}
        if "default_vision_model" not in columns:
            connection.execute(text("ALTER TABLE llm_providers ADD COLUMN default_vision_model VARCHAR(100)"))
            logger.info("llm_providers表已添加 default_vision_model 列")
        if "default_embedding_model" not in columns:
            connection.execute(text("ALTER TABLE llm_providers ADD COLUMN default_embedding_model VARCHAR(100)"))
            logger.info("llm_providers表已添加 default_embedding_model 列")
    except Exception as e:
        logger.warning(f"llm_providers表迁移跳过: {e}")


async def _seed_skills_and_pipelines():
    """首次启动时自动 seed 技能（从文件夹扫描）、流程和算子（从 seed JSON）"""
    from pathlib import Path
    from sqlalchemy import select as sa_select, func
    from app.models.skill import Skill
    from app.models.pipeline import Pipeline
    from app.models.operator import Operator
    from app.services.skill_parser import get_skill_info_from_path

    async with async_session() as db:
        # 1. Seed skills：扫描技能文件夹，DB 中不存在的自动创建记录
        skill_base = Path(settings.SKILL_STORAGE_PATH)
        if skill_base.is_dir():
            # 预修复：技能文件夹重命名后 DB 中 skill_path 可能指向旧路径，
            # 按技能名在磁盘上重新查找新文件夹并更新 skill_path（统一为相对文件夹名）
            _all_skills = (await db.execute(sa_select(Skill))).scalars().all()
            for skill in _all_skills:
                sp = skill.skill_path or ""
                folder = Path(sp).name if sp else ""
                full_path = skill_base / folder if folder else None
                if full_path and full_path.is_dir() and (full_path / "SKILL.md").exists():
                    if sp != folder:  # 绝对路径 → 统一为相对文件夹名
                        skill.skill_path = folder
                        logger.info(f"统一技能路径: {skill.name} -> {folder}")
                    continue
                # 路径无效，用技能名在磁盘上找新文件夹
                for candidate in sorted(skill_base.iterdir()):
                    if not candidate.is_dir() or not (candidate / "SKILL.md").exists():
                        continue
                    info = get_skill_info_from_path(candidate)
                    if info.get("name") == skill.name:
                        skill.skill_path = candidate.name
                        logger.info(f"修复技能路径: {skill.name} -> {candidate.name}")
                        break
            await db.flush()

            existing_names = set()
            result = await db.execute(sa_select(Skill.name))
            existing_names = {r[0] for r in result.fetchall()}
            # 用 skill_path 中的文件夹名去重，避免同一文件夹创建多条记录
            result = await db.execute(sa_select(Skill.skill_path))
            existing_folders = {Path(r[0]).name for r in result.fetchall() if r[0]}
            _seen_in_this_scan = set()
            for skill_folder in sorted(skill_base.iterdir()):
                if not skill_folder.is_dir() or not (skill_folder / "SKILL.md").exists():
                    continue
                folder_name = skill_folder.name
                if folder_name in existing_folders:
                    continue
                info = get_skill_info_from_path(skill_folder)
                skill_name = info.get("name") or ""
                # SKILL.md 无 front matter 时 name 为空，跳过（避免用 UUID 创建无效记录）
                if not skill_name or skill_name in existing_names or skill_name in _seen_in_this_scan:
                    logger.warning(f"跳过 seed 技能文件夹 {folder_name}：SKILL.md 无 front matter 或名称重复")
                    continue
                _seen_in_this_scan.add(skill_name)
                _skill_type = info.get("skill_type") or "processing"
                skill = Skill(
                    name=skill_name,
                    display_name=info.get("display_name") or folder_name,
                    description=info.get("description") or "",
                    skill_path=folder_name,
                    category="seed",
                    tags=["seed", f"skill_type:{_skill_type}"],
                    visibility="public",
                )
                db.add(skill)
                logger.info(f"Seed 技能: {skill_name}")
            await db.flush()

        seed_dir = Path(settings.SKILL_STORAGE_PATH).parent / "seed"

        # 2. Seed pipelines：表为空时从 seed JSON 加载
        count_result = await db.execute(sa_select(func.count()).select_from(Pipeline))
        if count_result.scalar() == 0:
            seed_file = seed_dir / "pipelines.json"
            if seed_file.exists():
                import json
                pipelines = json.loads(seed_file.read_text(encoding="utf-8"))
                for p in pipelines:
                    pipe = Pipeline(
                        name=p["name"],
                        display_name=p.get("display_name") or p["name"],
                        description=p.get("description") or "",
                        main_code=p.get("main_code") or "",
                        entry_function=p.get("entry_function") or "main",
                        parameters=p.get("parameters") or [],
                        skill_calls=p.get("skill_calls") or [],
                        tags=p.get("tags") or [],
                        category=p.get("category") or "seed",
                        visibility="public",
                        is_active=True,
                    )
                    db.add(pipe)
                logger.info(f"Seed 流程: {len(pipelines)} 个")

        # 3. Seed operators：表为空时从 seed JSON 加载
        count_result = await db.execute(sa_select(func.count()).select_from(Operator))
        if count_result.scalar() == 0:
            seed_file = seed_dir / "operators.json"
            if seed_file.exists():
                import json
                operators = json.loads(seed_file.read_text(encoding="utf-8"))
                for op in operators:
                    operator = Operator(
                        name=op["name"],
                        display_name=op.get("display_name") or op["name"],
                        description=op.get("description") or "",
                        category=op.get("category") or "general",
                        inputs=op.get("inputs") or [],
                        outputs=op.get("outputs") or [],
                        parameters=op.get("parameters") or [],
                        execution_config=op.get("execution_config") or {},
                        script_content=op.get("script_content") or "",
                        script_filename=op.get("script_filename") or "",
                        function_name=op.get("function_name") or "",
                        tags=op.get("tags") or [],
                        visibility="public",
                    )
                    db.add(operator)
                logger.info(f"Seed 算子: {len(operators)} 个")

        # 4. Seed 内置流程和调度（按 is_builtin 查重，用户删除后不复活）
        from app.models.schedule import Schedule

        builtin_pipe = (await db.execute(
            sa_select(Pipeline).where(Pipeline.is_builtin == True)
        )).scalar_one_or_none()
        if not builtin_pipe:
            builtin_pipe = Pipeline(
                name="metadata-sync-enrich",
                display_name="元数据同步与AI增强",
                description="自动同步所有有权限数据源的元数据并进行AI业务增强",
                main_code="metadata_sync_enrich",
                entry_function="main",
                parameters=[],
                skill_calls=[],
                tags=["system", "builtin"],
                category="system",
                visibility="public",
                is_active=True,
                is_builtin=True,
            )
            db.add(builtin_pipe)
            await db.flush()
            logger.info("Seed 内置流程: 元数据同步与AI增强")

        builtin_sched = (await db.execute(
            sa_select(Schedule).where(Schedule.is_builtin == True)
        )).scalar_one_or_none()
        if not builtin_sched:
            cron_expr = "0 0 * * *"
            next_run = None
            try:
                from croniter import croniter
                from datetime import datetime as _dt
                next_run = croniter(cron_expr, _dt.utcnow()).get_next(_dt)
            except Exception:
                pass
            builtin_sched = Schedule(
                name="metadata-daily-sync",
                description="每天0点同步元数据并AI增强（内置，不可删除）",
                task_type="pipeline",
                task_target_id=builtin_pipe.id,
                schedule_type="cron",
                cron_expression=cron_expr,
                timezone="Asia/Shanghai",
                status="active",
                is_builtin=True,
                run_mode="normal",
                next_run_at=next_run,
            )
            db.add(builtin_sched)
            logger.info("Seed 内置调度: 元数据每日同步")

        await db.commit()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="DataCrab 数据工程智能体 API",
    lifespan=lifespan,
)

# CORS中间件
_cors_origins = settings.CORS_ORIGINS
_allow_credentials = "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
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
