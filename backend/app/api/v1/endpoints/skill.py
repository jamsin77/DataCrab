"""技能管理API端点 - 遵循 Agent Skills 开放标准"""

import io
import math
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from loguru import logger

from app.core.config import settings
from app.core.database import get_db
from app.models.skill import Skill
from app.models.operator import Operator
from app.models.user import User
from app.schemas.skill import (
    SkillCreate,
    SkillUpdate,
    SkillResponse,
    SkillDetailResponse,
    SkillSearchRequest,
    SkillRunRequest,
    SkillRunNLRequest,
    SkillRunResponse,
    SkillGenerateRequest,
    SkillCloneRequest,
    SkillDocUpdate,
    SkillScriptUpdate,
    SkillScriptInfo,
    SkillModifyRequest,
    SkillDebugChatRequest,
    SkillParamDef,
)
from app.services.skill_parser import (
    parse_skill_md,
    get_skill_info_from_path,
    read_skill_md,
    write_skill_md,
    read_skill_script,
    write_skill_script,
    list_skill_scripts,
    append_error_log,
    read_error_log,
    read_lessons,
    write_lessons,
)
from app.api.deps import get_current_user
from app.models.datasource import DataSource
from app.services.prompt_docs import SANDBOX_TOOLS_DOC

router = APIRouter()


async def _build_datasource_info(db: AsyncSession, user_id) -> str:
    """构建当前用户的数据源信息文本，用于注入到 Skill Creator 提示词"""
    from app.services.connectors import get_connector
    try:
        result = await db.execute(
            select(DataSource).where(DataSource.created_by == user_id, DataSource.is_active == True)
        )
        sources = result.scalars().all()
        if not sources:
            return "（用户暂无数据源）"
        lines = []
        for ds in sources:
            tables = []
            try:
                connector = get_connector(ds.type, ds.connection_config or {})
                schema = await connector.get_schema()
                tables = [s.get("table_name", "") for s in schema if s.get("table_name")]
                await connector.close()
            except Exception:
                pass
            tables_str = ", ".join(tables) if tables else "（无表）"
            lines.append(f"- \"{ds.name}\" ({ds.type}) 表: {tables_str}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"构建数据源信息失败: {e}")
        return "（无法获取数据源信息）"


def _sanitize_nans(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nans(v) for v in obj]
    return obj


def _get_skill_storage() -> Path:
    path = Path(settings.SKILL_STORAGE_PATH)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_skill_folder(skill_id: UUID) -> Path:
    return _get_skill_storage() / str(skill_id)


async def _sync_scripts_to_operators(
    skill: Skill,
    folder: Path,
    db: AsyncSession,
    current_user: User,
):
    from app.services.operator_parser import parse_python_script_multi, extract_script_name

    scripts_dir = folder / "scripts"
    if not scripts_dir.is_dir():
        return

    for script_file in sorted(scripts_dir.glob("*.py")):
        script_content = script_file.read_text(encoding="utf-8")
        script_content = script_content.strip()
        if script_content.startswith("```python"):
            lines = script_content.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            script_content = "\n".join(lines).strip()
        elif script_content.startswith("```"):
            lines = script_content.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            script_content = "\n".join(lines).strip()
        if not script_content.strip():
            continue

        try:
            parsed_list = parse_python_script_multi(script_content)
        except Exception:
            continue

        script_name = extract_script_name(script_file.name)

        for parsed in parsed_list:
            func_name = parsed.get("function_name")
            if not func_name:
                continue
            if func_name == "main":
                continue

            operator_name = f"{skill.name}-{script_name}-{func_name}"

            existing = await db.execute(
                select(Operator).where(Operator.name == operator_name)
            )
            existing_op = existing.scalar_one_or_none()

            op_data = dict(
                display_name=f"{skill.display_name or skill.name} - {func_name}",
                description=parsed.get("description") or skill.description or "",
                category=skill.category or "skill",
                inputs=parsed.get("inputs", [{"name": "data", "type": "DataFrame", "required": True}]),
                outputs=parsed.get("outputs", [{"name": "result", "type": "any"}]),
                parameters=parsed.get("parameters", []),
                execution_config={"type": "python_script", "source": "skill", "skill_id": str(skill.id)},
                script_content=script_content,
                script_filename=script_file.name,
                function_name=func_name,
                tags=(skill.tags or []) + ["from_skill"],
                visibility=skill.visibility or "public",
                author=current_user.id,
            )

            if existing_op:
                for k, v in op_data.items():
                    setattr(existing_op, k, v)
            else:
                operator = Operator(name=operator_name, **op_data)
                db.add(operator)

    await db.flush()


def _get_skill_relative_path(folder: Path) -> str:
    storage = _get_skill_storage()
    try:
        return str(folder.relative_to(storage))
    except ValueError:
        return str(folder)


def _build_detail(skill: Skill) -> SkillDetailResponse:
    folder = _get_skill_folder(skill.id)
    info = get_skill_info_from_path(folder)

    return SkillDetailResponse(
        id=skill.id,
        name=skill.name,
        display_name=skill.display_name or info.get("display_name"),
        description=skill.description or info.get("description"),
        skill_path=str(folder) if folder.exists() else None,
        tags=skill.tags,
        category=skill.category,
        version=skill.version,
        visibility=skill.visibility,
        usage_count=skill.usage_count,
        success_rate=skill.success_rate,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        skill_md=read_skill_md(folder),
        scripts=list_skill_scripts(folder),
        references=info.get("references", []),
        assets=info.get("assets", []),
    )


@router.get("", response_model=list[SkillDetailResponse])
async def list_skills(
    category: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.permission_service import get_accessible_resource_ids
    shared_ids = await get_accessible_resource_ids(db, current_user.id, "skill")
    query = select(Skill).where(
        or_(
            Skill.author == current_user.id,
            Skill.visibility == "public",
            Skill.id.in_(shared_ids) if shared_ids else False,
        )
    )
    if category:
        query = query.where(Skill.category == category)
    query = query.order_by(Skill.updated_at.desc())
    result = await db.execute(query)
    skills = result.scalars().all()
    return [_build_detail(s) for s in skills]


@router.get("/categories", response_model=list[str])
async def get_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Skill.category).distinct().where(Skill.category.isnot(None))
    )
    return [row[0] for row in result.all()]


@router.get("/{skill_id}", response_model=SkillDetailResponse)
async def get_skill(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return _build_detail(skill)


@router.post("", response_model=SkillDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: SkillCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    skill_id = uuid4()
    folder = _get_skill_folder(skill_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scripts").mkdir(exist_ok=True)
    (folder / "references").mkdir(exist_ok=True)
    (folder / "assets").mkdir(exist_ok=True)
    safe_name = request.name.replace("_", "-")
    (folder / "SKILL.md").write_text(
        f"---\nname: {safe_name}\ndescription: {request.description or ''}\n---\n\n# {request.display_name or safe_name}\n\n{request.description or ''}\n",
        encoding="utf-8",
    )

    skill = Skill(
        id=skill_id,
        name=safe_name,
        display_name=request.display_name or request.name,
        description=request.description,
        skill_path=str(folder),
        tags=request.tags,
        category=request.category,
        visibility=request.visibility or "public",
        author=current_user.id,
    )
    db.add(skill)
    await db.flush()
    await db.refresh(skill)
    await _sync_scripts_to_operators(skill, _get_skill_folder(skill_id), db, current_user)
    logger.info(f"技能已创建: {skill.name} ({skill.id})")
    return _build_detail(skill)


@router.put("/{skill_id}", response_model=SkillDetailResponse)
async def update_skill(
    skill_id: UUID,
    request: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    update_data = request.model_dump(exclude_unset=True)
    if "name" in update_data:
        update_data["name"] = update_data["name"].replace("_", "-")
        if "display_name" not in update_data and skill.display_name == skill.name:
            update_data["display_name"] = update_data["name"]
    for key, value in update_data.items():
        setattr(skill, key, value)

    await db.flush()
    await db.refresh(skill)
    return _build_detail(skill)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    if folder.exists():
        shutil.rmtree(folder)

    skill_name = skill.name
    prefix = f"{skill_name}-"
    ops = await db.execute(select(Operator).where(Operator.name.startswith(prefix)))
    for op in ops.scalars().all():
        cfg = op.execution_config or {}
        if cfg.get("source") == "skill" and cfg.get("skill_id") == str(skill_id):
            await db.delete(op)

    await db.delete(skill)
    await db.flush()
    logger.info(f"技能已删除: {skill_name} ({skill_id})，关联算子已清理")


@router.post("/upload", response_model=SkillDetailResponse, status_code=status.HTTP_201_CREATED)
async def upload_skill(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传 Skill 包（.zip 格式）"""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="只支持 .zip 格式的 Skill 包")

    skill_id = uuid4()
    folder = _get_skill_folder(skill_id)

    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            for member in zf.infolist():
                member_path = (folder / member.filename).resolve()
                if not str(member_path).startswith(str(folder.resolve())):
                    raise HTTPException(status_code=400, detail=f"非法文件路径: {member.filename}")
            zf.extractall(folder)

        skill_md_path = folder / "SKILL.md"
        if not skill_md_path.exists():
            shutil.rmtree(folder)
            raise HTTPException(status_code=400, detail="Skill 包中缺少 SKILL.md 文件")

        parsed = parse_skill_md(skill_md_path.read_text(encoding="utf-8"))
        name = parsed.get("name") or folder.name
        display_name = parsed.get("name") or name
        description = parsed.get("description") or ""

        scripts_dir = folder / "scripts"
        if not scripts_dir.is_dir():
            scripts_dir.mkdir(exist_ok=True)
        folder.joinpath("references").mkdir(exist_ok=True)
        folder.joinpath("assets").mkdir(exist_ok=True)

        skill = Skill(
            id=skill_id,
            name=name,
            display_name=display_name,
            description=description,
            skill_path=str(folder),
            tags=parsed.get("front_matter", {}).get("tags", []),
            category=parsed.get("front_matter", {}).get("category"),
            visibility="public",
            author=current_user.id,
        )
        db.add(skill)
        await db.flush()
        await db.refresh(skill)
        logger.info(f"Skill 包已上传: {name} ({skill.id})")
        return _build_detail(skill)
    except HTTPException:
        raise
    except Exception as e:
        if folder.exists():
            shutil.rmtree(folder)
        raise HTTPException(status_code=500, detail=f"Skill 包解析失败: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/{skill_id}/download")
async def download_skill(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载 Skill 包（.zip 格式）"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    if not folder.exists():
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(folder))

    zip_buffer.seek(0)
    filename = f"{skill.name}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{skill_id}/skill-md")
async def get_skill_md(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 SKILL.md 内容"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    content = read_skill_md(_get_skill_folder(skill_id))
    return {"skill_md": content or "", "parsed": parse_skill_md(content) if content else {}}


@router.put("/{skill_id}/skill-md", response_model=SkillDetailResponse)
async def update_skill_md(
    skill_id: UUID,
    request: SkillDocUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新 SKILL.md 内容"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    folder.mkdir(parents=True, exist_ok=True)
    write_skill_md(folder, request.content)

    parsed = parse_skill_md(request.content)
    if parsed.get("name"):
        skill.display_name = parsed["name"]
    if parsed.get("description"):
        skill.description = parsed["description"]

    await db.flush()
    await db.refresh(skill)
    return _build_detail(skill)


@router.get("/{skill_id}/scripts", response_model=list[SkillScriptInfo])
async def get_skill_scripts(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 Skill 的所有脚本"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    return list_skill_scripts(_get_skill_folder(skill_id))


@router.get("/{skill_id}/scripts/{script_name}")
async def get_skill_script(
    skill_id: UUID,
    script_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定脚本内容"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    content = read_skill_script(_get_skill_folder(skill_id), script_name)
    if content is None:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return {"name": script_name, "content": content}


@router.put("/{skill_id}/scripts/{script_name}")
async def update_skill_script(
    skill_id: UUID,
    script_name: str,
    request: SkillScriptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新或创建脚本"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    folder.mkdir(parents=True, exist_ok=True)
    write_skill_script(folder, script_name, request.content)
    await _sync_scripts_to_operators(skill, folder, db, current_user)
    return {"name": script_name, "ok": True}


@router.delete("/{skill_id}/scripts/{script_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill_script(
    skill_id: UUID,
    script_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除脚本"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    script_path = _get_skill_folder(skill_id) / "scripts" / script_name
    if script_path.exists():
        script_path.unlink()


@router.post("/{skill_id}/run", response_model=SkillRunResponse)
async def run_skill(
    skill_id: UUID,
    request: SkillRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行 Skill 脚本"""
    from app.services.skill_runner import run_skill_script
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)

    ds_name = None
    if request.datasource_id:
        from app.models.datasource import DataSource as DSModel
        ds_result = await db.execute(select(DSModel).where(DSModel.id == UUID(request.datasource_id)))
        ds_obj = ds_result.scalar_one_or_none()
        if ds_obj:
            ds_name = ds_obj.name

    import asyncio as _asyncio
    exec_result = await _asyncio.to_thread(
        run_skill_script,
        skill_path=folder,
        script_name=request.script_name,
        parameters=request.parameters,
        input_data=request.input_data,
        datasource_id=request.datasource_id,
        datasource_name=ds_name,
        table_name=request.table_name,
        user_id=str(current_user.id),
    )

    skill.usage_count = (skill.usage_count or 0) + 1
    await db.flush()

    return SkillRunResponse(**exec_result)


@router.post("/{skill_id}/run-stream")
async def run_skill_stream(
    skill_id: UUID,
    request: SkillRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.skill_runner import run_skill_script_async
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)

    ds_name = None
    if request.datasource_id:
        from app.models.datasource import DataSource as DSModel
        ds_result = await db.execute(select(DSModel).where(DSModel.id == UUID(request.datasource_id)))
        ds_obj = ds_result.scalar_one_or_none()
        if ds_obj:
            ds_name = ds_obj.name

    import asyncio
    import json as json_mod

    async def generate():
        try:
            yield f"data: {json_mod.dumps({'type': 'executing', 'message': '正在执行技能脚本...'}, ensure_ascii=False)}\n\n"

            exec_result = await run_skill_script_async(
                skill_path=folder,
                script_name=request.script_name,
                parameters=request.parameters,
                input_data=request.input_data,
                datasource_id=request.datasource_id,
                datasource_name=ds_name,
                table_name=request.table_name,
                user_id=str(current_user.id),
            )

            skill.usage_count = (skill.usage_count or 0) + 1
            await db.flush()

            from app.services.data_harness import collect_experience
            collect_experience(
                folder, source="run-stream",
                exec_result=exec_result,
                parameters=request.parameters,
                script_name=request.script_name,
            )

            # 执行成功后 → 触发 DataInspector 质量检查（报告型，不自动修复）
            _inner_r = exec_result.get("result") if isinstance(exec_result.get("result"), dict) else {}
            _exec_success = exec_result.get("success") and _inner_r.get("success") is not False
            if _exec_success:
                _target_ds_name = request.parameters.get("target_datasource_name") or request.parameters.get("source_datasource_name")
                _target_table = request.parameters.get("target_table_name") or request.parameters.get("source_table_name") or request.table_name
                if _target_ds_name and _target_table:
                    _target_ds_id = request.datasource_id
                    if request.parameters.get("target_datasource_name"):
                        from sqlalchemy import select as sa_select
                        from app.models.datasource import DataSource
                        _ds_r = await db.execute(sa_select(DataSource).where(DataSource.name == request.parameters["target_datasource_name"]))
                        _ds_obj = _ds_r.scalar_one_or_none()
                        if _ds_obj:
                            _target_ds_id = str(_ds_obj.id)
                    if _target_ds_id:
                        yield f"data: {json_mod.dumps({'type': 'inspecting', 'message': '执行成功，DataInspector 正在检查数据质量...'}, ensure_ascii=False)}\n\n"
                        try:
                            from app.services.data_inspector_agent import DataInspectorAgent
                            from app.services.multi_agent import AgentMessage, HandoffReason, agent_registry
                            if not agent_registry.get("data_inspector"):
                                agent_registry.register(DataInspectorAgent())
                            _inspector = agent_registry.get("data_inspector")
                            _inspect_msg = AgentMessage(
                                from_agent="runner",
                                to_agent="data_inspector",
                                reason=HandoffReason.INSPECT_RESULT,
                                payload={
                                    "datasource_id": str(_target_ds_id),
                                    "table_name": _target_table,
                                    "operation_description": "技能执行",
                                    "result_summary": str(_inner_r)[:500],
                                },
                            )
                            _inspect_ctx = {"db": db, "user_id": current_user.id}
                            _issues = []
                            _summary = ""
                            async for _evt in _inspector.run(_inspect_msg, _inspect_ctx):
                                _t = _evt.get("type")
                                if _t == "handoff":
                                    _payload = _evt.get("payload", {})
                                    _issues = _payload.get("issues", [])
                                    _summary = _payload.get("summary", "")
                                    break
                                elif _t == "done":
                                    _r = _evt.get("result", {})
                                    if _r.get("content"):
                                        _summary = _r["content"][:500]
                                    break
                                elif _t == "tool_result":
                                    pass
                                else:
                                    yield f"data: {json_mod.dumps(_evt, ensure_ascii=False, default=str)}\n\n"
                            _inspection = {"passed": len(_issues) == 0, "issues": _issues,
                                           "summary": _summary or f"检查完成：{len(_issues)} 个问题"}
                            yield f"data: {json_mod.dumps({'type': 'inspection_result', 'result': _sanitize_nans(_inspection)}, ensure_ascii=False, default=str)}\n\n"
                        except Exception as inspect_err:
                            logger.warning(f"数据质量检查失败: {inspect_err}")
                            yield f"data: {json_mod.dumps({'type': 'inspection_result', 'result': {'passed': True, 'error': str(inspect_err)[:200]}}, ensure_ascii=False)}\n\n"

            yield f"data: {json_mod.dumps({'type': 'done', 'result': _sanitize_nans(exec_result)}, ensure_ascii=False, default=str)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式执行技能失败: {e}")
            yield f"data: {json_mod.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/{skill_id}/params", response_model=list[SkillParamDef])
async def get_skill_params(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取技能的参数定义（从 SKILL.md 参数表 + 脚本 AST 提取）"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    params = []

    script_content = read_skill_script(folder, "main.py")
    if script_content is None:
        for f in sorted((folder / "scripts").glob("*.py")):
            script_content = f.read_text(encoding="utf-8")
            break

    if script_content:
        import ast as _ast
        try:
            tree = _ast.parse(script_content)

            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        if alias.name == "argparse":
                            params = _extract_argparse_params(script_content, tree)
                            break
                elif isinstance(node, _ast.ImportFrom):
                    if node.module == "argparse":
                        params = _extract_argparse_params(script_content, tree)

            if not params:
                params = _extract_function_params(tree)
        except SyntaxError:
            pass

    if not params:
        skill_md = read_skill_md(folder) or ""
        params = _extract_params_from_md(skill_md)

    return params


@router.post("/{skill_id}/run-nl")
async def run_skill_nl(
    skill_id: UUID,
    request: SkillRunNLRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自然语言调用技能 - LLM 从自然语言推断执行参数"""
    from app.services.skill_runner import run_skill_script
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)

    skill_md = read_skill_md(folder) or ""
    script_content = read_skill_script(folder, request.script_name)
    if script_content is None:
        raise HTTPException(status_code=400, detail=f"脚本 {request.script_name} 不存在")

    from app.services.llm import llm_manager
    await llm_manager.initialize()

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个技能参数解析器。根据技能的 SKILL.md 描述、脚本代码和用户的自然语言调用指令，"
                "推断出执行该技能所需的参数。\n\n"
                "## 严格要求\n"
                "1. **参数名必须与 SKILL.md 参数规范完全一致**，不得自创参数名或使用近义词\n"
                "2. **参数类型必须严格匹配**：string→字符串，int→整数，bool→true/false，"
                "dict→JSON对象(如 {\"key\":\"value\"})，list→JSON数组。dict 类型绝不能输出为数组\n"
                "3. **只输出 SKILL.md 中定义的参数**，不要添加定义之外的参数\n"
                "4. **不要输出以下系统自动注入的参数**：datasource_id、datasource_name、datasource、"
                "table_name、table_names、tables、table —— 这些由系统自动注入，重复传入会导致冲突\n"
                "5. **仔细区分数据源名和表名**：数据源名(DataSource)是连接名称，表名(Table)是数据源中的表；"
                "用户说\"从X数据源\"时X是数据源名，说\"把Y这张表\"时Y是表名，切勿混淆\n"
                "6. 对于 add_columns 等 dict 类型参数，格式为 {\"列名\": 值}，"
                "不要用 [{\"name\":..., \"value\":...}] 列表格式\n\n"
                "## 输出格式\n"
                "只输出一个 JSON 对象，不要输出任何解释。格式：\n"
                '{"parameters": {"参数名": 值, ...}, "table_name": "表名(如有)"}\n'
                "注意：table_name 仅在用户明确提到表名时输出，不要把数据源名放到 table_name 中。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"技能名称：{skill.display_name or skill.name}\n"
                f"技能描述：{skill.description or ''}\n\n"
                f"SKILL.md 内容：\n{skill_md[:2000]}\n\n"
                f"脚本代码（{request.script_name}）：\n{script_content[:3000]}\n\n"
                f"用户的自然语言调用指令：{request.query}\n\n"
                f"请严格按 SKILL.md 参数规范推断执行参数，只输出 JSON。"
            ),
        },
    ]

    try:
        nl_result = await llm_manager.chat_with_messages(messages, temperature=0.2, max_tokens=500)
    except Exception as e:
        logger.error(f"自然语言参数推断失败: {e}")
        raise HTTPException(status_code=500, detail=f"参数推断失败: {str(e)}")

    nl_result = nl_result.strip()
    if nl_result.startswith("```"):
        lines = nl_result.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        nl_result = "\n".join(lines).strip()

    import json
    try:
        parsed = json.loads(nl_result)
    except json.JSONDecodeError:
        logger.warning(f"LLM 返回非 JSON: {nl_result}")
        parsed = {"parameters": {}}

    parameters = parsed.get("parameters", {})
    for key in ["datasource_id", "datasource_name", "datasource", "table_name", "table_names", "tables", "table"]:
        parameters.pop(key, None)

    inferred_table = parsed.get("table_name") or request.table_name
    datasource_id = request.datasource_id
    ds_name = None

    if datasource_id:
        from app.models.datasource import DataSource as DSModel
        ds_obj_result = await db.execute(select(DSModel).where(DSModel.id == UUID(datasource_id)))
        ds_obj = ds_obj_result.scalar_one_or_none()
        if ds_obj:
            ds_name = ds_obj.name

    if not datasource_id and parsed.get("datasource_name"):
        from sqlalchemy import select as sa_select
        from app.models.datasource import DataSource
        ds_result = await db.execute(
            sa_select(DataSource).where(DataSource.name == parsed["datasource_name"])
        )
        ds = ds_result.scalar_one_or_none()
        if ds:
            datasource_id = str(ds.id)
            ds_name = ds.name

    import asyncio as _asyncio2
    exec_result = await _asyncio2.to_thread(
        run_skill_script,
        skill_path=folder,
        script_name=request.script_name,
        parameters=parameters,
        input_data=None,
        datasource_id=datasource_id,
        datasource_name=ds_name,
        table_name=inferred_table,
        user_id=str(current_user.id),
    )

    skill.usage_count = (skill.usage_count or 0) + 1
    await db.flush()

    return SkillRunResponse(**exec_result)


@router.post("/{skill_id}/run-nl-stream")
async def run_skill_nl_stream(
    skill_id: UUID,
    request: SkillRunNLRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.skill_runner import run_skill_script_async
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)

    skill_md = read_skill_md(folder) or ""
    script_content = read_skill_script(folder, request.script_name)
    if script_content is None:
        raise HTTPException(status_code=400, detail=f"脚本 {request.script_name} 不存在")

    from app.services.llm import llm_manager
    await llm_manager.initialize()

    import asyncio
    import json as json_mod
    import re as _re_nl

    # 提取参数规范（避免传完整 SKILL.md + 脚本导致推理链过长）
    params_section = ""
    params_match = _re_nl.search(r'(📋?\s*参数规范.*?)(?=\n##\s|###\s|##\s*📁|\Z)', skill_md, _re_nl.DOTALL)
    if not params_match:
        params_match = _re_nl.search(r'(\| 参数 \|.*?)(?=\n##\s|###\s|\Z)', skill_md, _re_nl.DOTALL)
    if params_match:
        params_section = params_match.group(1).strip()[:1500]

    messages = [
        {
            "role": "system",
            "content": (
                "你是技能参数解析器。根据参数规范和用户指令，推断执行参数。\n"
                "只输出 JSON，不要解释。\n\n"
                "规则：\n"
                "- 参数名必须与参数规范完全一致\n"
                "- 区分数据源名(DataSource)和表名(Table)\n"
                "- 不要输出 datasource/table_name 等系统注入参数\n\n"
                '输出格式：{"parameters": {"参数名": 值}}'
            ),
        },
        {
            "role": "user",
            "content": (
                f"技能：{skill.display_name or skill.name}\n"
                f"描述：{skill.description or ''}\n\n"
                f"参数规范：\n{params_section or '请参考脚本函数签名推断参数'}\n\n"
                f"用户指令：{request.query}\n\n"
                f"只输出 JSON。"
            ),
        },
    ]

    async def generate():
        full_content = ""
        try:
            async for chunk in llm_manager.chat_stream_with_thinking(messages, model=llm_manager.fast_model, temperature=0.2, max_tokens=2000):
                event = {"type": chunk["type"], "content": chunk["content"]}
                yield f"data: {json_mod.dumps(event, ensure_ascii=False)}\n\n"
                if chunk["type"] == "content":
                    full_content += chunk["content"]

            nl_result = full_content.strip()
            if nl_result.startswith("```"):
                lines = nl_result.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                nl_result = "\n".join(lines).strip()

            try:
                parsed = json_mod.loads(nl_result)
            except json_mod.JSONDecodeError:
                logger.warning(f"LLM 返回非 JSON: {nl_result}")
                parsed = {"parameters": {}}

            parameters = parsed.get("parameters", {})
            for key in ["datasource_id", "datasource_name", "datasource", "table_name", "table_names", "tables", "table"]:
                parameters.pop(key, None)

            inferred_table = parsed.get("table_name") or request.table_name
            datasource_id = request.datasource_id
            ds_name = None

            if datasource_id:
                from app.models.datasource import DataSource as DSModel
                ds_obj_result = await db.execute(select(DSModel).where(DSModel.id == UUID(datasource_id)))
                ds_obj = ds_obj_result.scalar_one_or_none()
                if ds_obj:
                    ds_name = ds_obj.name

            if not datasource_id and parsed.get("datasource_name"):
                from sqlalchemy import select as sa_select
                from app.models.datasource import DataSource
                ds_result = await db.execute(
                    sa_select(DataSource).where(DataSource.name == parsed["datasource_name"])
                )
                ds = ds_result.scalar_one_or_none()
                if ds:
                    datasource_id = str(ds.id)
                    ds_name = ds.name

            yield f"data: {json_mod.dumps({'type': 'inferred_params', 'parameters': parameters, 'table_name': inferred_table}, ensure_ascii=False)}\n\n"
            logger.info(f"NL推断参数: {json_mod.dumps(parameters, ensure_ascii=False)}")
            yield f"data: {json_mod.dumps({'type': 'executing', 'message': '参数推断完成，正在执行技能脚本...'}, ensure_ascii=False)}\n\n"

            exec_result = await run_skill_script_async(
                skill_path=folder,
                script_name=request.script_name,
                parameters=parameters,
                input_data=None,
                datasource_id=datasource_id,
                datasource_name=ds_name,
                table_name=inferred_table,
                user_id=str(current_user.id),
            )

            skill.usage_count = (skill.usage_count or 0) + 1
            try:
                await db.flush()
            except Exception as db_err:
                logger.warning(f"NL stream: db.flush failed: {db_err}")

            from app.services.data_harness import collect_experience
            collect_experience(
                folder, source="run-nl-stream",
                exec_result=exec_result,
                parameters=parameters,
                script_name=request.script_name,
            )

            # 执行成功后 → 触发 DataInspector 质量检查（报告型，不自动修复）
            _inner_r = exec_result.get("result") if isinstance(exec_result.get("result"), dict) else {}
            _exec_success = exec_result.get("success") and _inner_r.get("success") is not False
            if _exec_success:
                _target_ds_name = parameters.get("target_datasource_name") or parameters.get("source_datasource_name")
                _target_table = parameters.get("target_table_name") or parameters.get("source_table_name") or inferred_table
                if _target_ds_name and _target_table:
                    _target_ds_id = datasource_id
                    if parameters.get("target_datasource_name"):
                        from sqlalchemy import select as sa_select
                        from app.models.datasource import DataSource
                        _ds_r = await db.execute(sa_select(DataSource).where(DataSource.name == parameters["target_datasource_name"]))
                        _ds_obj = _ds_r.scalar_one_or_none()
                        if _ds_obj:
                            _target_ds_id = str(_ds_obj.id)
                    if _target_ds_id:
                        yield f"data: {json_mod.dumps({'type': 'inspecting', 'message': '执行成功，DataInspector 正在检查数据质量...'}, ensure_ascii=False)}\n\n"
                        try:
                            from app.services.data_inspector_agent import DataInspectorAgent
                            from app.services.multi_agent import AgentMessage, HandoffReason, agent_registry
                            if not agent_registry.get("data_inspector"):
                                agent_registry.register(DataInspectorAgent())
                            _inspector = agent_registry.get("data_inspector")
                            _inspect_msg = AgentMessage(
                                from_agent="runner",
                                to_agent="data_inspector",
                                reason=HandoffReason.INSPECT_RESULT,
                                payload={
                                    "datasource_id": str(_target_ds_id),
                                    "table_name": _target_table,
                                    "operation_description": "技能执行",
                                    "result_summary": str(_inner_r)[:500],
                                },
                            )
                            _inspect_ctx = {"db": db, "user_id": current_user.id}
                            _issues = []
                            _summary = ""
                            async for _evt in _inspector.run(_inspect_msg, _inspect_ctx):
                                _t = _evt.get("type")
                                if _t == "handoff":
                                    _payload = _evt.get("payload", {})
                                    _issues = _payload.get("issues", [])
                                    _summary = _payload.get("summary", "")
                                    break
                                elif _t == "done":
                                    _result = _evt.get("result", {})
                                    if _result.get("content"):
                                        _summary = _result["content"][:500]
                                    break
                                elif _t == "tool_result":
                                    pass
                                else:
                                    yield f"data: {json_mod.dumps(_evt, ensure_ascii=False, default=str)}\n\n"
                            _inspection = {"passed": len(_issues) == 0, "issues": _issues,
                                           "summary": _summary or f"检查完成：{len(_issues)} 个问题"}
                            yield f"data: {json_mod.dumps({'type': 'inspection_result', 'result': _sanitize_nans(_inspection)}, ensure_ascii=False, default=str)}\n\n"
                        except Exception as inspect_err:
                            logger.warning(f"数据质量检查失败: {inspect_err}")
                            yield f"data: {json_mod.dumps({'type': 'inspection_result', 'result': {'passed': True, 'error': str(inspect_err)[:200]}}, ensure_ascii=False)}\n\n"

            logger.info(f"NL stream: exec_result success={exec_result.get('success')}, error={str(exec_result.get('error',''))[:100]}")
            yield f"data: {json_mod.dumps({'type': 'done', 'result': _sanitize_nans(exec_result)}, ensure_ascii=False, default=str)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            import traceback as _tb
            logger.error(f"流式NL执行技能失败: {e}\n{_tb.format_exc()}")
            yield f"data: {json_mod.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/{skill_id}/debug-chat")
async def debug_skill_chat(
    skill_id: UUID,
    request: SkillDebugChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """技能 AI 调试助手（多智能体架构：DataProcessor + DataInspector）"""
    result_row = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result_row.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    skill_md = read_skill_md(folder) or ""
    script_content = read_skill_script(folder, request.script_name) or ""

    from app.services.llm import llm_manager
    await llm_manager.initialize()

    import json as json_mod

    # 数据源信息
    ds_name = None
    if request.datasource_id:
        from app.models.datasource import DataSource as DSModel
        ds_obj_result = await db.execute(select(DSModel).where(DSModel.id == UUID(request.datasource_id)))
        ds_obj = ds_obj_result.scalar_one_or_none()
        if ds_obj:
            ds_name = ds_obj.name

    # 提取参数规范
    import re as _re_extract
    params_section = ""
    params_match = _re_extract.search(r'(##\s*📋?\s*参数规范.*?)(?=\n##\s|###\s|##\s*📁|\Z)', skill_md, _re_extract.DOTALL)
    if params_match:
        params_section = params_match.group(1).strip()[:1500]

    skill_md_excerpt = skill_md[:1200]
    if params_match:
        skill_md_excerpt = skill_md.replace(params_match.group(0), "", 1)[:800]

    # 最近成功参数
    last_success_params = None
    try:
        from app.services import experience as _exp
        _positive = _exp.read_positive(folder)
        for entry in reversed(_positive or []):
            _p = entry.get("parameters") or {}
            _rs = entry.get("result_summary", "") or ""
            if _p and ("\x27success\x27: True" in _rs or "migrated_rows" in _rs):
                last_success_params = _p
                break
    except Exception:
        pass

    lessons = read_lessons(folder) or ""

    # 构建多智能体上下文
    from app.services.multi_agent import AgentRuntime, AgentMessage, HandoffReason, agent_registry
    from app.services.data_processor_agent import DataProcessorAgent
    from app.services.data_inspector_agent import DataInspectorAgent

    if not agent_registry.get("data_processor"):
        agent_registry.register(DataProcessorAgent())
    if not agent_registry.get("data_inspector"):
        agent_registry.register(DataInspectorAgent())

    runtime = AgentRuntime(agent_registry, llm_manager)

    history = []
    for msg in request.history[-10:]:
        history.append({"role": msg.get("role", "user"), "content": msg.get("content", "")[:500]})

    context = {
        "debug_mode": True,
        "db": db,
        "user_id": current_user.id,
        "history": history,
        "debug_folder": folder,
        "debug_script_name": request.script_name,
        "debug_script_content": script_content,
        "debug_skill_md": skill_md_excerpt,
        "debug_params_section": params_section,
        "debug_last_success_params": last_success_params,
        "debug_lessons": lessons,
        "debug_datasource_id": request.datasource_id,
        "debug_datasource_name": ds_name,
        "debug_table_name": request.table_name,
        "debug_user_context": request.context or {},
        "debug_max_rounds": 7,"debug_max_inspections": 7,
    }

    message = AgentMessage(
        from_agent="user",
        to_agent="data_processor",
        reason=HandoffReason.DELEGATE,
        payload={"user_message": request.message},
        context=context,
    )

    async def generate():
        import asyncio
        from app.services.llm import init_user_llm_context
        await init_user_llm_context(current_user.id)
        try:
            async for event in runtime.run("data_processor", message, context):
                t = event.get("type")
                if t == "agent_switch":
                    agent = event.get("agent")
                    if agent == "data_inspector":
                        evt = {"type": "inspecting", "message": "执行成功，DataInspector 正在检查数据质量..."}
                    elif agent == "data_processor":
                        evt = {"type": "retry", "round": 2, "message": "DataInspector 发现问题，开始修复..."}
                    else:
                        evt = None
                    if evt:
                        yield f"data: {json_mod.dumps(evt, ensure_ascii=False)}\n\n"
                elif t == "done":
                    pass
                else:
                    yield f"data: {json_mod.dumps(event, ensure_ascii=False, default=str)}\n\n"
            yield f"data: {json_mod.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"调试对话失败: {e}")
            yield f"data: {json_mod.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/{skill_id}/summarize-errors")
async def summarize_skill_errors(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分析技能的错误日志，用 LLM 总结经验并写入 SKILL.md"""
    result_row = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result_row.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    errors = read_error_log(folder)
    from app.services import experience as _exp
    positives = _exp.read_positive(folder)

    if not errors and not positives:
        return {"success": True, "message": "暂无错误/成功记录", "error_count": 0, "lessons": ""}

    from app.services.llm import llm_manager
    await llm_manager.initialize()

    import json as json_mod

    error_summary_lines = []
    for i, e in enumerate(errors[-30:], 1):
        error_summary_lines.append(
            f"{i}. [{e.get('timestamp','')[:10]}] {e.get('error_type','')}: "
            f"{e.get('error_message','')[:150]}"
        )
        if e.get("stdout_preview"):
            error_summary_lines.append(f"   输出预览: {e['stdout_preview'][:100]}")
        if e.get("parameters"):
            error_summary_lines.append(f"   参数: {json_mod.dumps(e['parameters'], ensure_ascii=False)[:100]}")

    pos_lines = []
    for i, p in enumerate(positives[-15:], 1):
        pos_lines.append(
            f"{i}. 参数: {json_mod.dumps(p.get('parameters', {}), ensure_ascii=False)[:120]}"
            f" → 结果摘要: {p.get('result_summary','')[:80]}"
        )

    existing_lessons = read_lessons(folder)
    lessons_context = f"\n\n已有的经验总结（在此基础上补充更新）：\n{existing_lessons}" if existing_lessons else ""

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "你是一个技能经验分析专家。分析技能执行中的【错误日志（反例）】和【成功记录（正例）】，"
                "总结出规律性的经验。要求：\n"
                "1. 反例：按错误类型分类，给出问题描述、根因、修复建议\n"
                "2. 正例：归纳成功模式与最佳实践（哪些参数组合/写法能稳定成功）\n"
                "3. 如果已有经验总结，在此基础上补充更新（保留仍有效条目，更新已有条目，添加新发现）\n"
                "4. 使用 Markdown 格式，用 ### 分类别，分别有「常见错误」和「成功模式」两节\n"
                "5. 只输出经验总结内容，不要前言结尾\n"
                "6. 简洁精炼，每个条目不超过3行"
            ),
        },
        {
            "role": "user",
            "content": (
                f"技能名称：{skill.display_name or skill.name}\n"
                f"技能描述：{skill.description or '无'}\n"
                f"【反例·错误记录】（最近{len(errors[-30:])}条，共{len(errors)}条）：\n\n"
                + "\n".join(error_summary_lines)
                + (f"\n\n【正例·成功记录】（最近{len(pos_lines)}条，共{len(positives)}条）：\n\n" + "\n".join(pos_lines) if pos_lines else "")
                + lessons_context
            ),
        },
    ]

    try:
        lessons_text = await llm_manager.chat_with_messages(
            prompt_messages, temperature=0.3, max_tokens=1500
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM总结失败: {str(e)}")

    write_lessons(folder, lessons_text.strip())

    return {
        "success": True,
        "message": f"已总结 {len(errors)} 条错误记录并更新 SKILL.md",
        "error_count": len(errors),
        "lessons": lessons_text.strip(),
    }


@router.get("/{skill_id}/experience")
async def get_skill_experience(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取技能的调试经验（归纳原因 + 历史错误记录 + 成功记录）"""
    result_row = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result_row.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    from app.services import experience
    folder = Path(settings.SKILL_STORAGE_PATH) / str(skill_id)
    data = experience.read_experience(folder)
    return {
        "lessons": data.get("lessons", ""),
        "negative": (data.get("negative") or [])[-20:],  # 最近20条错误
        "positive": (data.get("positive") or [])[-10:],  # 最近10条成功
        "stats": experience.experience_stats(folder),
    }


async def _collect_all_lessons(db: AsyncSession, user_id) -> str:
    """收集用户所有算子+技能的经验总结，用于注入新技能/算子生成（统一经验库）"""
    from app.services import experience
    return await experience.collect_all_lessons(db, user_id)


@router.post("/generate", response_model=SkillDetailResponse, status_code=status.HTTP_201_CREATED)
async def generate_skill_endpoint(
    request: SkillGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Skill Creator：根据自然语言描述生成完整 Skill 包"""
    from app.services.skill_creator import generate_skill, create_skill_on_disk
    try:
        ds_info = await _build_datasource_info(db, current_user.id)
        all_lessons = (await _collect_all_lessons(db, current_user.id))[:2000]
        generated = await generate_skill(request.prompt, datasource_info=ds_info, lessons=all_lessons)
    except Exception as e:
        logger.error(f"Skill Creator 生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"Skill 生成失败: {str(e)}")

    skill_md = generated.get("skill_md", "")
    scripts = generated.get("scripts", {})
    front_matter = generated.get("front_matter", {})

    if not skill_md:
        raise HTTPException(status_code=400, detail="Skill Creator 未生成有效的 SKILL.md")

    skill_id = uuid4()
    folder = _get_skill_folder(skill_id)

    try:
        create_skill_on_disk(folder, skill_md, scripts)
    except Exception as e:
        if folder.exists():
            shutil.rmtree(folder)
        raise HTTPException(status_code=500, detail=f"Skill 文件夹创建失败: {e}")

    name = front_matter.get("name", "")
    if not name or name in ("generate-skill", "generated-skill", "new-skill", "custom-skill", "skill-name"):
        words = re.sub(r'[^\w\u4e00-\u9fff]', ' ', request.prompt).split()
        keywords = [w.lower() for w in words[:4] if len(w) > 1]
        name = "-".join(keywords) if keywords else f"skill-{str(skill_id)[:8]}"
    name = name.replace("_", "-")
    skill = Skill(
        id=skill_id,
        name=name,
        display_name=name,
        description=front_matter.get("description", ""),
        skill_path=str(folder),
        tags=front_matter.get("tags", ["ai_generated"]),
        category=front_matter.get("category", "ai_generated"),
        visibility="private",
        author=current_user.id,
    )
    db.add(skill)
    await db.flush()
    await db.refresh(skill)
    await _sync_scripts_to_operators(skill, folder, db, current_user)
    logger.info(f"Skill Creator 已生成技能: {name} ({skill.id})")
    return _build_detail(skill)


@router.post("/generate-stream")
async def generate_skill_stream_endpoint(
    request: SkillGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Skill Creator 流式生成：SSE 实时推送生成过程"""
    from fastapi.responses import StreamingResponse
    from app.services.skill_creator import generate_skill_stream, create_skill_on_disk
    import json

    ds_info = await _build_datasource_info(db, current_user.id)
    all_lessons = (await _collect_all_lessons(db, current_user.id))[:2000]

    async def event_stream():
        parsed_data = None
        async for event in generate_skill_stream(request.prompt, datasource_info=ds_info, lessons=all_lessons):
            if event["type"] == "done":
                parsed_data = event["data"]
                yield f"data: {json.dumps({'type': 'done', 'message': '解析完成，正在创建技能...'}, ensure_ascii=False)}\n\n"
                break
            elif event["type"] == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': event['message']}, ensure_ascii=False)}\n\n"
                return
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        if not parsed_data:
            yield f"data: {json.dumps({'type': 'error', 'message': '生成失败'}, ensure_ascii=False)}\n\n"
            return

        skill_md = parsed_data.get("skill_md", "")
        scripts = parsed_data.get("scripts", {})
        front_matter = parsed_data.get("front_matter", {})

        if not skill_md:
            yield f"data: {json.dumps({'type': 'error', 'message': '未生成有效的 SKILL.md'}, ensure_ascii=False)}\n\n"
            return

        skill_id = uuid4()
        folder = _get_skill_folder(skill_id)

        try:
            create_skill_on_disk(folder, skill_md, scripts)
        except Exception as e:
            if folder.exists():
                shutil.rmtree(folder)
            yield f"data: {json.dumps({'type': 'error', 'message': f'文件夹创建失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        name = front_matter.get("name", "")
        if not name or name in ("generate-skill", "generated-skill", "new-skill", "custom-skill", "skill-name"):
            words = re.sub(r'[^\w\u4e00-\u9fff]', ' ', request.prompt).split()
            keywords = [w.lower() for w in words[:4] if len(w) > 1]
            name = "-".join(keywords) if keywords else f"skill-{str(skill_id)[:8]}"
        name = name.replace("_", "-")
        skill = Skill(
            id=skill_id,
            name=name,
            display_name=name,
            description=front_matter.get("description", ""),
            skill_path=str(folder),
            tags=front_matter.get("tags", ["ai_generated"]),
            category=front_matter.get("category", "ai_generated"),
            visibility="private",
            author=current_user.id,
        )
        db.add(skill)
        await db.flush()
        await db.refresh(skill)
        await _sync_scripts_to_operators(skill, folder, db, current_user)
        logger.info(f"Skill Creator 流式生成技能: {name} ({skill.id})")

        from app.schemas.skill import SkillDetailResponse
        detail = _build_detail(skill)
        resp_data = SkillDetailResponse.model_validate(detail).model_dump(mode="json")
        yield f"data: {json.dumps({'type': 'created', 'skill': resp_data}, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{skill_id}/clone", response_model=SkillDetailResponse, status_code=status.HTTP_201_CREATED)
async def clone_skill(
    skill_id: UUID,
    request: SkillCloneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    new_id = uuid4()
    new_folder = _get_skill_folder(new_id)
    old_folder = _get_skill_folder(skill_id)

    if old_folder.exists():
        shutil.copytree(old_folder, new_folder)

    clone = Skill(
        id=new_id,
        name=request.name,
        display_name=request.name,
        description=skill.description,
        skill_path=str(new_folder),
        tags=[*(skill.tags or [])],
        category=skill.category,
        visibility=skill.visibility,
        author=current_user.id,
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)
    await _sync_scripts_to_operators(clone, clone_folder, db, current_user)
    return _build_detail(clone)


@router.post("/{skill_id}/modify", response_model=SkillDetailResponse)
async def modify_skill(
    skill_id: UUID,
    request: SkillModifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    current_md = read_skill_md(folder) or ""

    if not current_md:
        raise HTTPException(status_code=400, detail="该技能没有 SKILL.md 内容")

    from app.services.llm import llm_manager
    await llm_manager.initialize()

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个 Skill 文档编辑器。根据用户的自然语言指令修改 SKILL.md 文件。\n"
                "SKILL.md 是 YAML front matter + Markdown 格式的技能描述文档。\n"
                "保持 YAML front matter 格式，只修改用户要求的部分。\n"
                "输出完整的 SKILL.md 内容，不要用代码块包裹。\n\n"
                "🚫 安全红线：Skill 只能处理用户的业务数据，不能修改 DataCrab 平台自身。\n"
                "如果用户要求修改 SKILL.md 使技能能够操作平台系统数据，请拒绝并说明原因。\n\n"
                "✅ 修改后必验证：修改 SKILL.md 后，请重新读取确认修改内容已正确反映。\n"
                "如果修改涉及脚本逻辑，建议在修改后执行技能验证效果。\n\n"
                "📂 输出默认同源：数据处理生成新文件时，如果未指定输出路径，默认保存到 DataSource（数据源）指定的文件路径下。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"以下是现有的 SKILL.md 内容：\n\n```markdown\n{current_md}\n```\n\n"
                f"请根据以下要求修改这个 SKILL.md：\n{request.instruction}\n\n"
                f"请输出修改后的完整 SKILL.md 内容。"
            ),
        },
    ]

    try:
        new_md = await llm_manager.chat_with_messages(messages, temperature=0.3, max_tokens=3000)
    except Exception as e:
        logger.error(f"LLM修改技能失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI修改失败: {str(e)}")

    new_md = new_md.strip()
    if new_md.startswith("```"):
        lines = new_md.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        new_md = "\n".join(lines).strip()

    write_skill_md(folder, new_md)

    parsed = parse_skill_md(new_md)
    if parsed.get("name"):
        skill.display_name = parsed["name"]
    if parsed.get("description"):
        skill.description = parsed["description"]

    await db.flush()
    await db.refresh(skill)
    await _sync_scripts_to_operators(skill, folder, db, current_user)
    logger.info(f"技能已通过AI修改: {skill.name} ({skill.id})")
    return _build_detail(skill)


@router.post("/{skill_id}/modify-stream")
async def modify_skill_stream(
    skill_id: UUID,
    request: SkillModifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)
    current_md = read_skill_md(folder) or ""

    if not current_md:
        raise HTTPException(status_code=400, detail="该技能没有 SKILL.md 内容")

    from app.services.llm import llm_manager
    await llm_manager.initialize()

    import asyncio
    import json as json_mod

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个 Skill 文档编辑器。根据用户的自然语言指令修改 SKILL.md 文件。\n"
                "SKILL.md 是 YAML front matter + Markdown 格式的技能描述文档。\n"
                "保持 YAML front matter 格式，只修改用户要求的部分。\n"
                "输出完整的 SKILL.md 内容，不要用代码块包裹。\n\n"
                "🚫 安全红线：Skill 只能处理用户的业务数据，不能修改 DataCrab 平台自身。\n"
                "如果用户要求修改 SKILL.md 使技能能够操作平台系统数据，请拒绝并说明原因。\n\n"
                "✅ 修改后必验证：修改 SKILL.md 后，请重新读取确认修改内容已正确反映。\n"
                "如果修改涉及脚本逻辑，建议在修改后执行技能验证效果。\n\n"
                "📂 输出默认同源：数据处理生成新文件时，如果未指定输出路径，默认保存到 DataSource（数据源）指定的文件路径下。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"以下是现有的 SKILL.md 内容：\n\n```markdown\n{current_md}\n```\n\n"
                f"请根据以下要求修改这个 SKILL.md：\n{request.instruction}\n\n"
                f"请输出修改后的完整 SKILL.md 内容。"
            ),
        },
    ]

    async def generate():
        full_content = ""
        try:
            async for chunk in llm_manager.chat_stream_with_thinking(messages, model=llm_manager.model, temperature=0.3, max_tokens=4000):
                event = {"type": chunk["type"], "content": chunk["content"]}
                yield f"data: {json_mod.dumps(event, ensure_ascii=False)}\n\n"
                if chunk["type"] == "content":
                    full_content += chunk["content"]

            new_md = full_content.strip()
            if new_md.startswith("```"):
                lines = new_md.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                new_md = "\n".join(lines).strip()

            write_skill_md(folder, new_md)

            parsed = parse_skill_md(new_md)
            if parsed.get("name"):
                skill.display_name = parsed["name"]
            if parsed.get("description"):
                skill.description = parsed["description"]

            await db.flush()
            await db.refresh(skill)
            await _sync_scripts_to_operators(skill, folder, db, current_user)
            logger.info(f"技能已通过AI流式修改: {skill.name} ({skill.id})")

            detail = _build_detail(skill)
            yield f"data: {json_mod.dumps({'type': 'done', 'skill': detail}, ensure_ascii=False, default=str)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式修改技能失败: {e}")
            yield f"data: {json_mod.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/search", response_model=list[SkillDetailResponse])
async def search_skills(
    request: SkillSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Skill)
    if request.category:
        query = query.where(Skill.category == request.category)
    query = query.limit(request.top_k)
    result = await db.execute(query)
    return [_build_detail(s) for s in result.scalars().all()]


def _extract_argparse_params(script_content: str, tree) -> list[SkillParamDef]:
    import ast as _ast
    params = []
    add_arg_pattern = re.compile(r'add_argument\(["\'](.+?)["\']')

    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        if not isinstance(node.func, _ast.Attribute):
            continue
        if node.func.attr != "add_argument":
            continue
        if not node.args:
            continue
        arg_name = ""
        if isinstance(node.args[0], _ast.Constant):
            arg_name = node.args[0].value
        if not arg_name or not arg_name.startswith("--"):
            continue

        clean_name = arg_name.lstrip("-").replace("-", "_")
        kw_dict = {}
        for kw in node.keywords:
            if isinstance(kw.arg, str) and isinstance(kw.value, _ast.Constant):
                kw_dict[kw.arg] = kw.value.value
            elif isinstance(kw.arg, str) and isinstance(kw.value, _ast.Name):
                kw_dict[kw.arg] = kw.value.id

        is_list = kw_dict.get("nargs") in ("+", "*")
        is_datasource = "datasource" in clean_name and "id" not in clean_name
        is_table = "table" in clean_name and "id" not in clean_name

        ptype = "str"
        if kw_dict.get("type") == "int" or kw_dict.get("type") == int:
            ptype = "int"
        elif kw_dict.get("type") == "float" or kw_dict.get("type") == float:
            ptype = "float"
        elif is_list:
            ptype = "list"

        help_text = kw_dict.get("help", "")
        if isinstance(help_text, str):
            help_text = help_text.strip()

        params.append(SkillParamDef(
            name=clean_name,
            display_name=help_text or clean_name,
            type=ptype,
            required=kw_dict.get("required", False) is True,
            default=kw_dict.get("default"),
            description=help_text,
            is_datasource=is_datasource,
            is_table=is_table,
            is_list=is_list,
        ))
    return params


_BUILTIN_SKILL_FUNCTIONS = frozenset({
    "query_table_data", "get_table_data", "get_table_schema",
    "get_datasource_id_by_name", "write_table_data",
})


def _extract_function_params(tree) -> list[SkillParamDef]:
    import ast as _ast

    def _calls_builtin(func_node: _ast.FunctionDef) -> bool:
        for child in _ast.walk(func_node):
            if isinstance(child, _ast.Call) and isinstance(child.func, _ast.Name):
                if child.func.id in _BUILTIN_SKILL_FUNCTIONS:
                    return True
        return False

    def _count_params(func_node: _ast.FunctionDef) -> int:
        return sum(
            1 for a in func_node.args.args
            if a.arg not in ("self", "cls", "df", "input_data", "data")
        )

    candidates: list[tuple[_ast.FunctionDef, bool, int]] = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        candidates.append((node, _calls_builtin(node), _count_params(node)))

    if not candidates:
        return []

    builtin = [c for c in candidates if c[1]]
    if builtin:
        best_node = max(builtin, key=lambda c: c[2])[0]
    else:
        best_node = max(candidates, key=lambda c: c[2])[0]

    params = []
    for arg in best_node.args.args:
        if arg.arg in ("self", "cls", "df", "input_data", "data", "inputs", "parameters", "context"):
            continue
        pname = arg.arg
        ptype = "str"
        if arg.annotation:
            ann_str = ""
            if isinstance(arg.annotation, _ast.Name):
                ann_str = arg.annotation.id
            elif isinstance(arg.annotation, _ast.Constant):
                ann_str = str(arg.annotation.value)
            elif isinstance(arg.annotation, _ast.Subscript):
                if isinstance(arg.annotation.value, _ast.Name):
                    ann_str = arg.annotation.value.id
                elif isinstance(arg.annotation.value, _ast.Attribute):
                    ann_str = arg.annotation.value.attr
            type_map = {"int": "int", "float": "float", "bool": "bool",
                        "List": "list", "Optional": "str", "Dict": "dict",
                        "str": "str"}
            ptype = type_map.get(ann_str, "str")

        is_datasource = "datasource" in pname and "id" not in pname
        is_table = "table" in pname and "id" not in pname
        is_list = ptype == "list"

        has_default = False
        default_val = None
        defaults_start = len(best_node.args.args) - len(best_node.args.defaults)
        arg_idx = best_node.args.args.index(arg)
        if arg_idx >= defaults_start:
            has_default = True
            dv = best_node.args.defaults[arg_idx - defaults_start]
            if isinstance(dv, _ast.Constant):
                default_val = dv.value
            elif isinstance(dv, _ast.NoneType):
                default_val = None

        example_val = None
        if not is_datasource and not is_table:
            if is_list or ptype == "list":
                _NAME_LIST_EXAMPLES = {
                    "columns": '["列名1", "列名2"]',
                    "on": '["连接键"]',
                    "table_names": '["表1", "表2"]',
                    "subset": '["列名1"]',
                }
                example_val = _NAME_LIST_EXAMPLES.get(pname, '["值1"]')
            elif ptype == "bool":
                example_val = "true"
            elif ptype == "int":
                example_val = "10"
            elif ptype == "float":
                example_val = "0.5"
            elif ptype == "dict":
                _NAME_DICT_EXAMPLES = {
                    "mapping": '{"旧名": "新名"}',
                    "functions": '{"列名": "sum"}',
                    "column_mapping": '{"源列": "目标列"}',
                    "column_transforms": '{"列名": {"type": "trim"}}',
                    "cleaning_options": '{"remove_empty": true, "deduplicate": true}',
                }
                example_val = _NAME_DICT_EXAMPLES.get(pname, '{"key": "value"}')
            else:
                _NAME_EXAMPLES = {
                    "column": '"列名"',
                    "condition": '"年龄 > 18"',
                    "query": '"搜索关键词"',
                    "name": '"名称"',
                    "value": '"值"',
                    "method": '"ffill"',
                    "how": '"inner"',
                    "group_column": '"分组列"',
                    "agg_column": '"聚合列"',
                    "agg_func": '"sum"',
                    "action": '"search"',
                    "sort_column": '"排序列"',
                    "filter_column": '"筛选列"',
                    "split_column": '"分割列"',
                    "primary_key": '"id"',
                    "output_dir": '"./output"',
                    "output_filename": '"result.xlsx"',
                    "era": '"唐"',
                    "location": '"北京"',
                    "level": '"一级"',
                    "relic_type": '"瓷器"',
                    "sources": '"wikipedia,baidu"',
                    "update_mode": '"append"',
                }
                example_val = _NAME_EXAMPLES.get(pname)

        params.append(SkillParamDef(
            name=pname,
            type=ptype,
            required=not has_default,
            default=default_val,
            example=example_val,
            is_datasource=is_datasource,
            is_table=is_table,
            is_list=is_list,
        ))
    return params


def _extract_params_from_md(skill_md: str) -> list[SkillParamDef]:
    import re as _re
    params = []
    in_param_table = False
    for line in skill_md.split("\n"):
        stripped = line.strip()
        if "参数" in stripped and ("说明" in stripped or "类型" in stripped or "描述" in stripped):
            in_param_table = True
            continue
        if in_param_table and stripped.startswith("|") and not stripped.startswith("|--") and not stripped.startswith("| ---"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if len(cells) >= 2 and cells[0] and not cells[0].startswith("-"):
                pname = cells[0].strip()
                if pname in ("参数", "Parameter", "---"):
                    continue
                is_ds = "datasource" in pname and "id" not in pname
                is_tbl = "table" in pname and "id" not in pname
                params.append(SkillParamDef(
                    name=pname,
                    type="str",
                    required="必选" in stripped or "必填" in stripped,
                    description=cells[1] if len(cells) > 1 else None,
                    is_datasource=is_ds,
                    is_table=is_tbl,
                ))
        elif in_param_table and not stripped.startswith("|"):
            in_param_table = False
    return params