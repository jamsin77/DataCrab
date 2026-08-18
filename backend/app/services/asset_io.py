"""资产导出/导入服务 — 技能/算子/流程/LLM配置/连接器/规则 一键迁移。

设计原则：
- API Key / 密码 一律不导出（导入后用户手动填）
- 按 name 去重（已存在的跳过，不覆盖）
- 流程的 skill_calls 用 skill_name 引用（跨机器稳定），导入时反查 skill_id
- 技能是文件夹形式，直接打包；其他资产序列化为 JSON
"""
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


# ============ 导出 ============

async def export_skills_to_zip(zf: zipfile.ZipFile, db: AsyncSession) -> int:
    """导出技能：data/skills/ 文件夹整体打包"""
    skill_base = Path(settings.SKILL_STORAGE_PATH)
    if not skill_base.is_dir():
        return 0
    count = 0
    for skill_dir in sorted(skill_base.iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        for fpath in skill_dir.rglob("*"):
            if fpath.is_file():
                arcname = f"skills/{skill_dir.name}/{fpath.relative_to(skill_dir)}"
                zf.write(str(fpath), arcname)
        count += 1
    return count


async def export_operators(zf: zipfile.ZipFile, db: AsyncSession) -> int:
    """导出算子：DB → operators.json（含 script_content）"""
    from app.models.operator import Operator
    result = await db.execute(select(Operator))
    ops = result.scalars().all()
    data = []
    for op in ops:
        data.append({
            "name": op.name,
            "display_name": op.display_name or op.name,
            "description": op.description or "",
            "category": op.category or "general",
            "inputs": op.inputs or [],
            "outputs": op.outputs or [],
            "parameters": op.parameters or [],
            "execution_config": op.execution_config or {},
            "script_content": op.script_content or "",
            "script_filename": op.script_filename or "",
            "function_name": op.function_name or "",
            "tags": op.tags or [],
        })
    zf.writestr("operators.json", json.dumps(data, ensure_ascii=False, indent=2))
    return len(data)


async def export_pipelines(zf: zipfile.ZipFile, db: AsyncSession) -> int:
    """导出流程：DB → pipelines.json（skill_calls 的 skill_id 换成 skill_name）"""
    from app.models.pipeline import Pipeline
    from app.models.skill import Skill
    # 构建 skill_id → skill_name 映射
    skills = (await db.execute(select(Skill))).scalars().all()
    id2name = {str(s.id): s.name for s in skills}

    result = await db.execute(select(Pipeline))
    pipes = result.scalars().all()
    data = []
    for p in pipes:
        skill_calls = []
        for c in (p.skill_calls or []):
            if isinstance(c, dict):
                skill_id = c.get("skill_id", "")
                skill_name = id2name.get(skill_id, id2name.get(str(skill_id), ""))
                new_c = {k: v for k, v in c.items() if k != "skill_id"}
                new_c["skill_name"] = skill_name
                skill_calls.append(new_c)
        data.append({
            "name": p.name,
            "display_name": p.display_name or p.name,
            "description": p.description or "",
            "main_code": p.main_code or "",
            "entry_function": p.entry_function or "main",
            "parameters": p.parameters or [],
            "skill_calls": skill_calls,
            "tags": p.tags or [],
            "category": p.category or "seed",
            "visibility": p.visibility or "public",
        })
    zf.writestr("pipelines.json", json.dumps(data, ensure_ascii=False, indent=2))
    return len(data)


async def export_llm_config(zf: zipfile.ZipFile, db: AsyncSession) -> int:
    """导出 LLM Provider：DB → llm_config.json（不含 api_key）"""
    from app.models.custom_extension import LLMProvider, UserLLMConfig
    providers = (await db.execute(select(LLMProvider).where(LLMProvider.is_active == True))).scalars().all()
    data = []
    for p in providers:
        data.append({
            "provider_name": p.provider_name,
            "display_name": p.display_name or "",
            "description": p.description or "",
            "api_base": p.api_base or "",
            "models": p.models or [],
            "default_model": p.default_model or "",
            "flash_model": p.flash_model or "",
            "vision_model": p.vision_model or "",
            "embedding_model": p.embedding_model or "",
            "code": p.code or "",
            "is_public": p.is_public,
        })
    zf.writestr("llm_config.json", json.dumps(data, ensure_ascii=False, indent=2))
    return len(data)


async def export_custom_extensions(zf: zipfile.ZipFile, db: AsyncSession) -> int:
    """导出自定义连接器：DB → custom_extensions.json（不含连接密码）"""
    from app.models.custom_extension import CustomConnector
    connectors = (await db.execute(select(CustomConnector).where(CustomConnector.is_active == True))).scalars().all()
    data = []
    for c in connectors:
        data.append({
            "name": c.name,
            "display_name": c.display_name or "",
            "description": c.description or "",
            "code": c.code or "",
            "config_template": c.config_template or [],
            "is_public": c.is_public,
        })
    zf.writestr("custom_extensions.json", json.dumps(data, ensure_ascii=False, indent=2))
    return len(data)


async def export_rules(zf: zipfile.ZipFile, db: AsyncSession) -> int:
    """导出数据标准/质量/安全规则（MD 文件）"""
    rules_dir = Path(settings.SKILL_STORAGE_PATH).parent / "rules"
    data = {}
    for name in ("data_standards", "data_quality", "data_security"):
        fpath = rules_dir / f"{name}.md"
        if fpath.exists():
            data[name] = fpath.read_text(encoding="utf-8")
    if data:
        zf.writestr("rules.json", json.dumps(data, ensure_ascii=False, indent=2))
    return len(data)


async def export_schedules(zf: zipfile.ZipFile, db: AsyncSession, user_id) -> int:
    """导出调度：当前用户创建的调度 → schedules.json（task_target_id 换成 task_target_name 跨机器稳定）"""
    from app.models.schedule import Schedule
    from app.models.pipeline import Pipeline
    from app.models.operator import Operator
    from app.models.skill import Skill

    # 构建 (task_type, task_target_id) → name 映射
    pipelines = (await db.execute(select(Pipeline))).scalars().all()
    operators = (await db.execute(select(Operator))).scalars().all()
    skills = (await db.execute(select(Skill))).scalars().all()
    id2name: Dict = {}
    for p in pipelines:
        id2name[("pipeline", str(p.id))] = p.name
    for o in operators:
        id2name[("operator", str(o.id))] = o.name
    for s in skills:
        id2name[("skill", str(s.id))] = s.name

    # 只导出当前用户创建的调度（内置调度 created_by 为空，不导出）
    q = select(Schedule)
    if user_id is not None:
        q = q.where(Schedule.created_by == user_id)
    schedules = (await db.execute(q)).scalars().all()
    data = []
    for sch in schedules:
        target_name = id2name.get((sch.task_type, str(sch.task_target_id)), "")
        data.append({
            "name": sch.name,
            "description": sch.description or "",
            "task_type": sch.task_type,
            "task_target_name": target_name,
            "task_params": sch.task_params or {},
            "schedule_type": sch.schedule_type,
            "cron_expression": sch.cron_expression,
            "timezone": sch.timezone or "UTC",
            "interval_seconds": sch.interval_seconds,
            "event_config": sch.event_config or {},
            "max_retries": sch.max_retries if sch.max_retries is not None else 3,
            "retry_interval": sch.retry_interval if sch.retry_interval is not None else 60,
            "timeout": sch.timeout if sch.timeout is not None else 3600,
            "concurrent_runs": sch.concurrent_runs if sch.concurrent_runs is not None else 1,
            "run_mode": sch.run_mode or "normal",
            "status": sch.status or "active",
            "is_builtin": bool(sch.is_builtin),
        })
    zf.writestr("schedules.json", json.dumps(data, ensure_ascii=False, indent=2))
    return len(data)


async def build_export_zip(types: List[str], db: AsyncSession, user_id=None) -> bytes:
    """构建导出 zip，返回字节流。types 指定要导出的资产类型。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "exported_at": datetime.utcnow().isoformat(),
            "datacrab_version": settings.APP_VERSION,
            "types": types,
            "counts": {},
        }
        t0 = datetime.utcnow()
        if "skills" in types:
            manifest["counts"]["skills"] = await export_skills_to_zip(zf, db)
        if "operators" in types:
            manifest["counts"]["operators"] = await export_operators(zf, db)
        if "pipelines" in types:
            manifest["counts"]["pipelines"] = await export_pipelines(zf, db)
        if "llm_config" in types:
            manifest["counts"]["llm_config"] = await export_llm_config(zf, db)
        if "custom_extensions" in types:
            manifest["counts"]["custom_extensions"] = await export_custom_extensions(zf, db)
        if "rules" in types:
            manifest["counts"]["rules"] = await export_rules(zf, db)
        if "schedules" in types:
            manifest["counts"]["schedules"] = await export_schedules(zf, db, user_id)
        manifest["elapsed_ms"] = round((datetime.utcnow() - t0).total_seconds() * 1000, 2)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


# ============ 导入 ============

async def import_skills(zf: zipfile.ZipFile, db: AsyncSession, overwrite: bool = False) -> Dict:
    """导入技能：解压到 data/skills/，启动时自动 seed"""
    skill_base = Path(settings.SKILL_STORAGE_PATH)
    skill_base.mkdir(parents=True, exist_ok=True)
    imported, skipped = 0, 0
    skill_folders = set()
    for name in zf.namelist():
        if not name.startswith("skills/") or name.endswith("/"):
            continue
        parts = name.split("/")
        if len(parts) < 3:
            continue
        folder_name = parts[1]
        skill_folders.add(folder_name)
    for folder_name in skill_folders:
        target = skill_base / folder_name
        if target.exists() and not overwrite:
            skipped += 1
            continue
        target.mkdir(parents=True, exist_ok=True)
        prefix = f"skills/{folder_name}/"
        for name in zf.namelist():
            if name.startswith(prefix) and not name.endswith("/"):
                rel = name[len(prefix):]
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
        imported += 1
    return {"imported": imported, "skipped": skipped}


async def import_operators(data: List[Dict], db: AsyncSession, overwrite: bool = False) -> Dict:
    """导入算子：JSON → DB（按 name 去重）"""
    from app.models.operator import Operator
    existing = (await db.execute(select(Operator.name))).scalars().all()
    existing_names = set(existing)
    imported, skipped = 0, 0
    for op in data:
        name = op.get("name", "")
        if not name or name in existing_names:
            skipped += 1
            continue
        operator = Operator(
            name=name,
            display_name=op.get("display_name") or name,
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
        existing_names.add(name)
        imported += 1
    await db.flush()
    return {"imported": imported, "skipped": skipped}


async def import_pipelines(data: List[Dict], db: AsyncSession, user_id, overwrite: bool = False) -> Dict:
    """导入流程：JSON → DB（skill_calls 的 skill_name 反查 skill_id）"""
    from app.models.pipeline import Pipeline
    from app.models.skill import Skill
    from uuid import uuid4
    skills = (await db.execute(select(Skill))).scalars().all()
    name2id = {s.name: str(s.id) for s in skills}
    existing = (await db.execute(select(Pipeline.name).where(Pipeline.is_active == True))).scalars().all()
    existing_names = set(existing)
    imported, skipped = 0, 0
    for p in data:
        name = p.get("name", "")
        if not name or name in existing_names:
            skipped += 1
            continue
        skill_calls = []
        for c in (p.get("skill_calls") or []):
            skill_name = c.pop("skill_name", "")
            skill_id = name2id.get(skill_name, "")
            if skill_id:
                c["skill_id"] = skill_id
            skill_calls.append(c)
        pipeline = Pipeline(
            id=uuid4(),
            name=name,
            display_name=p.get("display_name") or name,
            description=p.get("description") or "",
            main_code=p.get("main_code") or "",
            entry_function=p.get("entry_function") or "main",
            parameters=p.get("parameters") or [],
            skill_calls=skill_calls,
            tags=p.get("tags") or [],
            category=p.get("category") or "seed",
            visibility=p.get("visibility") or "public",
            created_by=user_id,
        )
        db.add(pipeline)
        existing_names.add(name)
        imported += 1
    await db.flush()
    return {"imported": imported, "skipped": skipped}


async def import_llm_config(data: List[Dict], db: AsyncSession, user_id, overwrite: bool = False) -> Dict:
    """导入 LLM Provider：JSON → DB（不含 api_key，按 provider_name 去重）"""
    from app.models.custom_extension import LLMProvider
    existing = (await db.execute(select(LLMProvider.provider_name))).scalars().all()
    existing_names = set(existing)
    imported, skipped = 0, 0
    for p in data:
        name = p.get("provider_name", "")
        if not name or name in existing_names:
            skipped += 1
            continue
        provider = LLMProvider(
            provider_name=name,
            display_name=p.get("display_name") or "",
            description=p.get("description") or "",
            api_base=p.get("api_base") or "",
            models=p.get("models") or [],
            default_model=p.get("default_model") or "",
            flash_model=p.get("flash_model") or "",
            vision_model=p.get("vision_model") or "",
            embedding_model=p.get("embedding_model") or "",
            code=p.get("code") or "",
            is_public=p.get("is_public", False),
            api_key_encrypted=None,
            created_by=user_id,
        )
        db.add(provider)
        existing_names.add(name)
        imported += 1
    await db.flush()
    return {"imported": imported, "skipped": skipped}


async def import_custom_extensions(data: List[Dict], db: AsyncSession, user_id, overwrite: bool = False) -> Dict:
    """导入自定义连接器：JSON → DB（按 name 去重）"""
    from app.models.custom_extension import CustomConnector
    existing = (await db.execute(select(CustomConnector.name))).scalars().all()
    existing_names = set(existing)
    imported, skipped = 0, 0
    for c in data:
        name = c.get("name", "")
        if not name or name in existing_names:
            skipped += 1
            continue
        connector = CustomConnector(
            name=name,
            display_name=c.get("display_name") or "",
            description=c.get("description") or "",
            code=c.get("code") or "",
            config_template=c.get("config_template") or [],
            is_public=c.get("is_public", False),
            created_by=user_id,
        )
        db.add(connector)
        existing_names.add(name)
        imported += 1
    await db.flush()
    return {"imported": imported, "skipped": skipped}


async def import_rules(data: Dict, db: AsyncSession) -> Dict:
    """导入数据规则：JSON → MD 文件"""
    rules_dir = Path(settings.SKILL_STORAGE_PATH).parent / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    imported = 0
    for name, content in data.items():
        fpath = rules_dir / f"{name}.md"
        fpath.write_text(content, encoding="utf-8")
        imported += 1
    return {"imported": imported, "skipped": 0}


async def import_schedules(data: List[Dict], db: AsyncSession, user_id, overwrite: bool = False) -> Dict:
    """导入调度：JSON → DB（task_target_name 反查 task_target_id，按 name 去重）
    放在最后导入：依赖 skills/operators/pipelines 已先导入。
    """
    from app.models.schedule import Schedule
    from app.models.pipeline import Pipeline
    from app.models.operator import Operator
    from app.models.skill import Skill
    from uuid import uuid4

    # 构建 name → id 映射（按 task_type 分表）
    pipelines = (await db.execute(select(Pipeline))).scalars().all()
    operators = (await db.execute(select(Operator))).scalars().all()
    skills = (await db.execute(select(Skill))).scalars().all()
    name2id = {
        "pipeline": {p.name: str(p.id) for p in pipelines},
        "operator": {o.name: str(o.id) for o in operators},
        "skill": {s.name: str(s.id) for s in skills},
    }

    existing = (await db.execute(select(Schedule.name).where(Schedule.created_by == user_id))).scalars().all()
    existing_names = set(existing)
    imported, skipped, unresolved = 0, 0, 0
    for sch in data:
        name = sch.get("name", "")
        if not name or name in existing_names:
            skipped += 1
            continue
        task_type = sch.get("task_type", "")
        task_target_name = sch.get("task_target_name", "")
        task_target_id = name2id.get(task_type, {}).get(task_target_name)
        if not task_target_id:
            # 目标资产未导入或不存在，跳过该调度
            unresolved += 1
            skipped += 1
            continue
        schedule = Schedule(
            id=uuid4(),
            name=name,
            description=sch.get("description") or "",
            task_type=task_type,
            task_target_id=task_target_id,
            task_params=sch.get("task_params") or {},
            schedule_type=sch.get("schedule_type") or "manual",
            cron_expression=sch.get("cron_expression"),
            timezone=sch.get("timezone") or "UTC",
            interval_seconds=sch.get("interval_seconds"),
            event_config=sch.get("event_config") or {},
            max_retries=sch.get("max_retries", 3),
            retry_interval=sch.get("retry_interval", 60),
            timeout=sch.get("timeout", 3600),
            concurrent_runs=sch.get("concurrent_runs", 1),
            run_mode=sch.get("run_mode", "normal"),
            status=sch.get("status", "active"),
            is_builtin=sch.get("is_builtin", False),
            created_by=user_id,
        )
        db.add(schedule)
        existing_names.add(name)
        imported += 1
    await db.flush()
    return {"imported": imported, "skipped": skipped, "unresolved": unresolved}


async def read_zip_manifest(zip_bytes: bytes) -> Dict:
    """读取 zip 里的 manifest.json（导入前预览用）"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        try:
            return json.loads(zf.read("manifest.json"))
        except KeyError:
            return {}


async def import_from_zip(zip_bytes: bytes, types: List[str], db: AsyncSession, user_id, overwrite: bool = False) -> Dict:
    """从 zip 导入资产。types 指定导入哪些类型。"""
    result = {}
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    try:
        if "skills" in types:
            result["skills"] = await import_skills(zf, db, overwrite)
        if "operators" in types and "operators.json" in zf.namelist():
            data = json.loads(zf.read("operators.json"))
            result["operators"] = await import_operators(data, db, overwrite)
        if "pipelines" in types and "pipelines.json" in zf.namelist():
            data = json.loads(zf.read("pipelines.json"))
            result["pipelines"] = await import_pipelines(data, db, user_id, overwrite)
        if "llm_config" in types and "llm_config.json" in zf.namelist():
            data = json.loads(zf.read("llm_config.json"))
            result["llm_config"] = await import_llm_config(data, db, user_id, overwrite)
        if "custom_extensions" in types and "custom_extensions.json" in zf.namelist():
            data = json.loads(zf.read("custom_extensions.json"))
            result["custom_extensions"] = await import_custom_extensions(data, db, user_id, overwrite)
        if "rules" in types and "rules.json" in zf.namelist():
            data = json.loads(zf.read("rules.json"))
            result["rules"] = await import_rules(data, db)
        if "schedules" in types and "schedules.json" in zf.namelist():
            data = json.loads(zf.read("schedules.json"))
            result["schedules"] = await import_schedules(data, db, user_id, overwrite)
    finally:
        zf.close()
    return result
