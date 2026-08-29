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

logger.add("debug_sse.log", filter=lambda r: "[SSE]" in r.get("message", "") or "[SSE-DEBUG]" in r.get("message", "") or "[Inspector-DEBUG]" in r.get("message", "") or "[handoff检查]" in r.get("message", "") or "[platform_issue" in r.get("message", "") or "[match-detail]" in r.get("message", "") or "[match]" in r.get("message", "") or "[classify]" in r.get("message", "") or "[direct_execute]" in r.get("message", "") or "[route]" in r.get("message", ""), rotation="1 MB")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_skills)
        await conn.run_sync(_migrate_custom_extensions)
        await conn.run_sync(_migrate_builtin_flags)
        await conn.run_sync(_migrate_author_to_created_by)
        await conn.run_sync(_migrate_chat_metadata)
    logger.info("数据库表已创建")
    await _seed_skills_and_pipelines()
    await _load_custom_extensions()
    await _backfill_related_skill_ids()
    await _rebuild_match_index()
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



def _migrate_skills(connection):
    from sqlalchemy import text
    try:
        result = connection.execute(text("PRAGMA table_info(skills)"))
        columns = {row[1] for row in result.fetchall()}
        if "skill_path" not in columns:
            connection.execute(text("ALTER TABLE skills ADD COLUMN skill_path VARCHAR(500)"))
            logger.info("skills表已添加 skill_path 列")
        if "skill_type" not in columns:
            connection.execute(text("ALTER TABLE skills ADD COLUMN skill_type VARCHAR(20)"))
            # 从 tags 里的 skill_type:xxx 迁移数据
            connection.execute(text("UPDATE skills SET skill_type = 'processing'"))
            logger.info("skills表已添加 skill_type 列")
        # 从 tags 中删除 skill_type:xxx 标记
        connection.execute(text("UPDATE skills SET tags = '[]' WHERE tags IS NULL"))
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
    # pipelines: related_skill_ids 列迁移 + 回填
    try:
        result = connection.execute(text("PRAGMA table_info(pipelines)"))
        columns = {row[1] for row in result.fetchall()}
        if "related_skill_ids" not in columns:
            connection.execute(text("ALTER TABLE pipelines ADD COLUMN related_skill_ids JSON DEFAULT '[]'"))
            logger.info("pipelines表已添加 related_skill_ids 列")
        if "pipeline_type" not in columns:
            connection.execute(text("ALTER TABLE pipelines ADD COLUMN pipeline_type VARCHAR(20)"))
            # 内置流程设 system，其他从关联技能推断
            connection.execute(text("UPDATE pipelines SET pipeline_type = CASE WHEN is_builtin = 1 THEN 'system' ELSE 'processing' END"))
            logger.info("pipelines表已添加 pipeline_type 列")
    except Exception as e:
        logger.warning(f"pipelines表迁移跳过: {e}")
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

    # data_sources: is_virtual 列迁移（从 tech_metadata.source 回填）
    try:
        result = connection.execute(text("PRAGMA table_info(data_sources)"))
        columns = {row[1] for row in result.fetchall()}
        if "is_virtual" not in columns:
            connection.execute(text("ALTER TABLE data_sources ADD COLUMN is_virtual BOOLEAN DEFAULT 0"))
            logger.info("data_sources表已添加 is_virtual 列")
        # 从 tech_metadata 回填虚拟数据源标记
        connection.execute(text("UPDATE data_sources SET is_virtual = 1 WHERE tech_metadata LIKE '%chat_upload_virtual%'"))
    except Exception as e:
        logger.warning(f"data_sources表 is_virtual 迁移跳过: {e}")

    # user_llm_configs: flash_model/vision_model 列迁移（旧列 fast_model → flash_model）
    try:
        result = connection.execute(text("PRAGMA table_info(user_llm_configs)"))
        columns = {row[1] for row in result.fetchall()}
        if "flash_model" not in columns:
            connection.execute(text("ALTER TABLE user_llm_configs ADD COLUMN flash_model VARCHAR(100)"))
            logger.info("user_llm_configs表已添加 flash_model 列")
        if "vision_model" not in columns:
            connection.execute(text("ALTER TABLE user_llm_configs ADD COLUMN vision_model VARCHAR(100)"))
            logger.info("user_llm_configs表已添加 vision_model 列")
        # 旧列 fast_model 数据迁移到 flash_model
        if "fast_model" in columns:
            connection.execute(text("UPDATE user_llm_configs SET flash_model = fast_model WHERE flash_model IS NULL OR flash_model = ''"))
            logger.info("user_llm_configs表 flash_model 已从 fast_model 同步")
    except Exception as e:
        logger.warning(f"user_llm_configs表迁移跳过: {e}")

    try:
        result = connection.execute(text("PRAGMA table_info(llm_providers)"))
        columns = {row[1] for row in result.fetchall()}
        # flash_model / vision_model / embedding_model 列：无条件添加缺失列（新数据库无旧列也要加）
        if "flash_model" not in columns:
            connection.execute(text("ALTER TABLE llm_providers ADD COLUMN flash_model VARCHAR(100)"))
            # 旧列名数据迁移（default_flash_model → flash_model / fast_model → flash_model）
            if "default_flash_model" in columns:
                connection.execute(text("UPDATE llm_providers SET flash_model = default_flash_model WHERE flash_model IS NULL AND default_flash_model IS NOT NULL"))
                logger.info("llm_providers表 flash_model 列已从 default_flash_model 迁移")
            elif "fast_model" in columns:
                connection.execute(text("UPDATE llm_providers SET flash_model = fast_model WHERE flash_model IS NULL AND fast_model IS NOT NULL"))
                logger.info("llm_providers表 flash_model 列已从 fast_model 迁移")
            else:
                logger.info("llm_providers表已添加 flash_model 列")
        if "vision_model" not in columns:
            connection.execute(text("ALTER TABLE llm_providers ADD COLUMN vision_model VARCHAR(100)"))
            if "default_vision_model" in columns:
                connection.execute(text("UPDATE llm_providers SET vision_model = default_vision_model WHERE vision_model IS NULL AND default_vision_model IS NOT NULL"))
                logger.info("llm_providers表 vision_model 列已从 default_vision_model 迁移")
            else:
                logger.info("llm_providers表已添加 vision_model 列")
        if "embedding_model" not in columns:
            connection.execute(text("ALTER TABLE llm_providers ADD COLUMN embedding_model VARCHAR(100)"))
            if "default_embedding_model" in columns:
                connection.execute(text("UPDATE llm_providers SET embedding_model = default_embedding_model WHERE embedding_model IS NULL AND default_embedding_model IS NOT NULL"))
                logger.info("llm_providers表 embedding_model 列已从 default_embedding_model 迁移")
            else:
                logger.info("llm_providers表已添加 embedding_model 列")
    except Exception as e:
        logger.warning(f"llm_providers表迁移跳过: {e}")


def _migrate_author_to_created_by(connection):
    """skills/operators 表 author 列 → created_by 列（SQLite 不支持 rename，走 add+update）"""
    from sqlalchemy import text
    for table in ("skills", "operators"):
        try:
            result = connection.execute(text(f"PRAGMA table_info({table})"))
            columns = {row[1] for row in result.fetchall()}
            if "author" not in columns:
                continue  # 全新库，模型已定义 created_by，无需迁移
            if "created_by" not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN created_by VARCHAR(32)"))
            connection.execute(text(f"UPDATE {table} SET created_by = author WHERE created_by IS NULL"))
            connection.execute(text(f"ALTER TABLE {table} DROP COLUMN author"))
            logger.info(f"{table}表 author 列已迁移为 created_by")
        except Exception as e:
            logger.warning(f"{table}表 author→created_by 迁移跳过: {e}")

    # permission_requests 表（PermissionRequest 模型）— 由 Base.metadata.create_all 自动创建
    try:
        result = connection.execute(text("PRAGMA table_info(permission_requests)"))
        columns = {row[1] for row in result.fetchall()}
        if not columns:
            logger.info("permission_requests 表将由 create_all 自动创建")
    except Exception as e:
        logger.warning(f"permission_requests 表迁移跳过: {e}")


def _migrate_chat_metadata(connection):
    """chat_messages 表加 meta JSON 列；chat_sessions 表加 context JSON 列"""
    from sqlalchemy import text
    try:
        result = connection.execute(text("PRAGMA table_info(chat_messages)"))
        columns = {row[1] for row in result.fetchall()}
        if "meta" not in columns:
            connection.execute(text("ALTER TABLE chat_messages ADD COLUMN meta JSON"))
            logger.info("chat_messages表已添加 meta 列")
    except Exception as e:
        logger.warning(f"chat_messages表 metadata 迁移跳过: {e}")
    try:
        result = connection.execute(text("PRAGMA table_info(chat_sessions)"))
        columns = {row[1] for row in result.fetchall()}
        if "context" not in columns:
            connection.execute(text("ALTER TABLE chat_sessions ADD COLUMN context JSON"))
            logger.info("chat_sessions表已添加 context 列")
    except Exception as e:
        logger.warning(f"chat_sessions表 context 迁移跳过: {e}")


async def _backfill_related_skill_ids():
    """回填存量 pipeline 的 related_skill_ids（从 source_skill_id + skill_calls 合并）"""
    from app.models.pipeline import Pipeline
    from sqlalchemy import select
    async with async_session() as db:
        pipelines = (await db.execute(select(Pipeline))).scalars().all()
        changed = 0
        for p in pipelines:
            existing = p.related_skill_ids or []
            if existing:
                continue
            ids = set()
            if p.source_skill_id:
                ids.add(str(p.source_skill_id))
            for sc in (p.skill_calls or []):
                if isinstance(sc, dict) and sc.get("skill_id"):
                    ids.add(str(sc["skill_id"]))
            if ids:
                p.related_skill_ids = list(ids)
                changed += 1
        if changed:
            await db.commit()
            logger.info(f"回填 related_skill_ids: {changed} 条流程")


async def _rebuild_match_index():
    """启动时重建向量索引。从 UserLLMConfig 取用户配置，遍历主+fallback 试 embed。"""
    try:
        from app.services.match_service import rebuild_index
        from app.services.llm import set_user_llm_config, llm_manager
        from app.core.crypto import decrypt
        from app.models.custom_extension import UserLLMConfig, LLMProvider
        from sqlalchemy import select as sa_select

        # 从 UserLLMConfig 表收集所有可能的 embedding 配置（主 + fallback）
        configs = []
        async with async_session() as session:
            result = await session.execute(sa_select(UserLLMConfig))
            for rec in result.scalars().all():
                api_key = decrypt(rec.api_key_encrypted) if rec.api_key_encrypted else ""
                if not api_key:
                    continue
                # 主配置
                if rec.embedding_model:
                    configs.append({
                        "provider": rec.provider, "api_key": api_key,
                        "api_base": rec.api_base or "",
                        "embedding_model": rec.embedding_model,
                        "default_model": rec.model or "",
                        "flash_model": rec.flash_model or "",
                        "vision_model": rec.vision_model or "",
                        "fallback_models": [],
                    })
                # fallback 配置
                for fb in (rec.fallback_models or []):
                    fb_key = decrypt(fb["api_key_encrypted"]) if fb.get("api_key_encrypted") else ""
                    if not fb_key and fb.get("provider"):
                        pub = await session.execute(
                            sa_select(LLMProvider).where(
                                LLMProvider.provider_name == fb["provider"],
                                LLMProvider.is_active == True,
                            )
                        )
                        pub_rec = pub.scalar_one_or_none()
                        if pub_rec and pub_rec.api_key_encrypted:
                            fb_key = decrypt(pub_rec.api_key_encrypted)
                    if fb_key and fb.get("embedding_model"):
                        configs.append({
                            "provider": fb.get("provider", ""), "api_key": fb_key,
                            "api_base": fb.get("api_base", ""),
                            "embedding_model": fb.get("embedding_model", ""),
                            "default_model": fb.get("model", ""),
                            "flash_model": fb.get("flash_model", ""),
                            "vision_model": fb.get("vision_model", ""),
                            "fallback_models": [],
                        })

        # 逐个试 embed，找到能用的配置
        sys_cfg = None
        for cfg in configs:
            try:
                set_user_llm_config(cfg)
                await llm_manager.embed("__health_check__")
                sys_cfg = cfg
                break
            except Exception:
                continue

        if sys_cfg:
            logger.info(f"向量索引使用配置: provider={sys_cfg['provider']}, embedding={sys_cfg['embedding_model']}")
        else:
            logger.warning("未找到可用的向量模型配置，向量索引无法重建")

        async with async_session() as db:
            await rebuild_index(db)
    except Exception as e:
        logger.error(f"向量索引重建失败: {e}")


async def _seed_skills_and_pipelines():
    """启动时扫描技能文件夹同步 DB + 创建内置元数据同步流程和调度"""
    from pathlib import Path
    from sqlalchemy import select as sa_select
    from app.models.skill import Skill
    from app.models.pipeline import Pipeline
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
            result = await db.execute(sa_select(Skill))
            all_skills = result.scalars().all()
            existing_names = {s.name for s in all_skills}
            # 同步已有技能的 skill_type（从 SKILL.md 读取）+ 清理 tags 里的 skill_type:xxx
            for skill in all_skills:
                folder_name = Path(skill.skill_path).name if skill.skill_path else ""
                if not folder_name:
                    continue
                full_path = skill_base / folder_name
                if not full_path.is_dir() or not (full_path / "SKILL.md").exists():
                    continue
                info = get_skill_info_from_path(full_path)
                _st = info.get("skill_type") or "processing"
                if skill.skill_type != _st:
                    skill.skill_type = _st
                # 清理 tags 里的 skill_type:xxx
                if skill.tags:
                    _clean_tags = [t for t in skill.tags if not str(t).startswith("skill_type:")]
                    if len(_clean_tags) != len(skill.tags):
                        skill.tags = _clean_tags
            await db.flush()
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
                    logger.warning(f"跳过技能文件夹 {folder_name}：SKILL.md 无 front matter 或名称重复")
                    continue
                _seen_in_this_scan.add(skill_name)
                _skill_type = info.get("skill_type") or "processing"
                # tags 从 SKILL.md 读取，剔除 skill_type（存到 DB 列）
                _tags = info.get("tags") or []
                _tags = [t for t in _tags if not str(t).startswith("skill_type:")]
                skill = Skill(
                    name=skill_name,
                    display_name=info.get("display_name") or folder_name,
                    description=info.get("description") or "",
                    skill_path=folder_name,
                    tags=_tags,
                    skill_type=_skill_type,
                    visibility="public",
                )
                db.add(skill)
                logger.info(f"扫描到技能: {skill_name}")
            await db.flush()

        # 同步已有流程的 pipeline_type（从关联技能推断）
        all_pipes = (await db.execute(sa_select(Pipeline))).scalars().all()
        # 查所有技能的 skill_type（用于推断）
        all_skills_map = {}
        if all_pipes:
            _skills_result = await db.execute(sa_select(Skill.id, Skill.skill_type))
            all_skills_map = {str(r[0]): r[1] for r in _skills_result.fetchall()}
        for p in all_pipes:
            if p.is_builtin:
                if p.pipeline_type != "system":
                    p.pipeline_type = "system"
            elif not p.pipeline_type:
                # 从关联技能推断
                _related = p.related_skill_ids or []
                _inferred = "processing"
                for sid in _related:
                    _st = all_skills_map.get(str(sid))
                    if _st:
                        _inferred = _st
                        break
                p.pipeline_type = _inferred
        await db.flush()

        # 2. Seed 内置流程和调度（按 is_builtin 查重，用户删除后不复活）
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
                pipeline_type="system",
                visibility="public",
                is_active=True,
                is_builtin=True,
            )
            db.add(builtin_pipe)
            await db.flush()
            logger.info("创建内置流程: 元数据同步与AI增强")

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
            logger.info("创建内置调度: 元数据每日同步")

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
