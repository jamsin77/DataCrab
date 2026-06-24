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
from sqlalchemy import select
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
)
from app.services.skill_runner import run_skill_script
from app.services.skill_creator import generate_skill, create_skill_on_disk
from app.api.deps import get_current_user

router = APIRouter()


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
    from app.services.operator_parser import parse_python_script, extract_script_name

    scripts_dir = folder / "scripts"
    if not scripts_dir.is_dir():
        return

    for script_file in sorted(scripts_dir.glob("*.py")):
        script_content = script_file.read_text(encoding="utf-8")
        if not script_content.strip():
            continue

        try:
            parsed = parse_python_script(script_content)
        except Exception:
            continue

        func_name = parsed.get("function_name")
        if not func_name:
            continue

        script_name = extract_script_name(script_file.name)
        operator_name = f"{skill.name}-{script_name}"

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
    query = select(Skill)
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
    (folder / "SKILL.md").write_text(
        f"---\nname: {request.name}\ndescription: {request.description or ''}\n---\n\n# {request.display_name or request.name}\n\n{request.description or ''}\n",
        encoding="utf-8",
    )

    skill = Skill(
        id=skill_id,
        name=request.name,
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

    exec_result = run_skill_script(
        skill_path=folder,
        script_name=request.script_name,
        parameters=request.parameters,
        input_data=request.input_data,
        datasource_id=request.datasource_id,
        datasource_name=ds_name,
        table_name=request.table_name,
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

            exec_result = run_skill_script(
                skill_path=folder,
                script_name=request.script_name,
                parameters=request.parameters,
                input_data=request.input_data,
                datasource_id=request.datasource_id,
                datasource_name=ds_name,
                table_name=request.table_name,
            )

            skill.usage_count = (skill.usage_count or 0) + 1
            await db.flush()

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
                "推断出执行该技能所需的参数。\n"
                "只输出一个 JSON 对象，包含推断出的 parameters 字段，不要输出任何解释。\n"
                "如果用户提到了数据源或表名，也一并输出 datasource_name 和 table_name 字段。\n"
                "输出格式示例：\n"
                '{"parameters": {"column": "年代", "limit": 100}, "table_name": "文物数据"}'
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
                f"请推断执行参数，只输出 JSON。"
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

    exec_result = run_skill_script(
        skill_path=folder,
        script_name=request.script_name,
        parameters=parameters,
        input_data=None,
        datasource_id=datasource_id,
        datasource_name=ds_name,
        table_name=inferred_table,
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

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个技能参数解析器。根据技能的 SKILL.md 描述、脚本代码和用户的自然语言调用指令，"
                "推断出执行该技能所需的参数。\n"
                "只输出一个 JSON 对象，包含推断出的 parameters 字段，不要输出任何解释。\n"
                "如果用户提到了数据源或表名，也一并输出 datasource_name 和 table_name 字段。\n"
                "输出格式示例：\n"
                '{"parameters": {"column": "年代", "limit": 100}, "table_name": "文物数据"}'
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
                f"请推断执行参数，只输出 JSON。"
            ),
        },
    ]

    async def generate():
        full_content = ""
        try:
            async for chunk in llm_manager.chat_stream_with_thinking(messages, temperature=0.2):
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
            yield f"data: {json_mod.dumps({'type': 'executing', 'message': '参数推断完成，正在执行技能脚本...'}, ensure_ascii=False)}\n\n"

            exec_result = run_skill_script(
                skill_path=folder,
                script_name=request.script_name,
                parameters=parameters,
                input_data=None,
                datasource_id=datasource_id,
                datasource_name=ds_name,
                table_name=inferred_table,
            )

            skill.usage_count = (skill.usage_count or 0) + 1
            await db.flush()

            yield f"data: {json_mod.dumps({'type': 'done', 'result': _sanitize_nans(exec_result)}, ensure_ascii=False, default=str)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式NL执行技能失败: {e}")
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
    result_row = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result_row.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    folder = _get_skill_folder(skill_id)

    skill_md = read_skill_md(folder) or ""
    script_content = read_skill_script(folder, request.script_name) or ""

    from app.services.llm import llm_manager
    await llm_manager.initialize()

    import asyncio
    import json as json_mod

    ds_name = None
    if request.datasource_id:
        from app.models.datasource import DataSource as DSModel
        ds_obj_result = await db.execute(select(DSModel).where(DSModel.id == UUID(request.datasource_id)))
        ds_obj = ds_obj_result.scalar_one_or_none()
        if ds_obj:
            ds_name = ds_obj.name

    system_prompt = (
        "你是 DataCrab 平台的技能调试助手。你正在帮助用户调试和优化一个技能（Skill）。\n\n"
        "## 你的能力\n"
        "1. **修改脚本**：输出以下格式的标记来更新脚本：\n"
        "```json\n"
        '{"action": "modify_script", "script_name": "main.py"}\n'
        "```\n"
        "紧接着输出：\n"
        "```python\n"
        "# 完整的脚本内容\n"
        "```\n"
        "2. **执行技能**：输出 JSON `{\"action\": \"run\", \"parameters\": {...}}` 来触发执行\n"
        "3. **分析问题**：分析执行结果中的错误，给出建议\n"
        "4. **解释代码**：解释技能脚本的功能和逻辑\n\n"
        "## 当前技能信息\n"
        f"- 技能名称：{skill.display_name or skill.name}\n"
        f"- 技能描述：{skill.description or '无'}\n"
        f"- 数据源：{ds_name or request.datasource_id or '未选择'}\n"
        f"- 表名：{request.table_name or '未选择'}\n\n"
        f"## SKILL.md\n```\n{skill_md[:3000]}\n```\n\n"
        f"## 当前脚本（{request.script_name}）\n```python\n{script_content}\n```\n\n"
        "## 脚本运行环境（必须了解）\n"
        "脚本在沙箱中执行，系统会自动注入以下内置函数到全局作用域，脚本中**直接使用即可，无需 import**：\n"
        "- `query_table_data(datasource_id, table_name, limit=1000)` → 返回 {\"success\": bool, \"data\": [行dict], \"columns\": [列名], \"row_count\": int}\n"
        "- `get_table_data(datasource_id, table_name, limit=1000)` → 同 query_table_data\n"
        "- `get_table_schema(datasource_id, table_name)` → 返回表结构\n"
        "- `get_datasource_id_by_name(name)` → 按名称查找数据源ID\n"
        "- `write_table_data(datasource_id, table_name, records=...)` → 写入数据\n\n"
        "⚠️ **绝对禁止**在脚本中 `import datacrab` 或 `from datacrab import ...`，datacrab 包不存在！\n"
        "⚠️ **绝对禁止**在脚本中 `pip install datacrab`，datacrab 不是可安装的包！\n"
        "⚠️ `if __name__ == '__main__':` 块会被系统自动去掉，argparse 脚本的 main() 由系统调用\n\n"
        "## Action 输出格式\n"
        "- **run action**：单独一行 JSON，如 `{\"action\": \"run\", \"parameters\": {\"split_column\": \"批次\"}}`\n"
        "- **modify_script action**：先用 JSON 声明 action，紧接着用 ```python 代码块提供完整脚本\n"
        "- run 的 parameters 只需传业务参数，不要传 datasource_id/table_name（系统会自动注入）\n"
        "- 可以在同一回复中先 modify_script 再 run，系统会按顺序执行\n"
        "- modify_script 的代码块中必须是完整的脚本，不能只写修改的部分\n"
        "- 如果只是回答问题或分析，不需要输出任何 action\n\n"
        "## 🚫 安全红线\n"
        "- 技能只能处理用户的业务数据，绝不能修改 DataCrab 平台自身\n"
        "- 修改脚本时，确保脚本不会访问或修改平台的系统表和配置\n"
        "- 脚本中只能操作用户数据源的业务数据，不能操作平台系统数据\n\n"
        "## ✅ 技能属于用户内容，可以自由修改\n"
        "- 用户可以自由创建、修改、调试、删除自己的技能\n"
        "- 技能脚本可以使用内置工具函数访问用户数据\n\n"
        "## ✅ 修改后必验证\n"
        "- 输出 modify_script 后，必须紧接着在同一回复中输出 run action 来验证\n"
        "- 如果验证失败，分析错误并再次 modify_script + run\n"
        "- 只有验证通过才算修改完成\n\n"
        "## 📂 输出默认同源\n"
        "- 数据处理生成新文件时，如果用户未指定输出路径，默认保存到 DataSource（数据源）指定的文件路径下\n"
        "- 如果 DataSource 来自数据库，需要询问用户输出路径"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.history[-20:]:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": request.message})

    async def generate():
        full_content = ""
        try:
            async for chunk in llm_manager.chat_stream_with_thinking(messages, temperature=0.3):
                event = {"type": chunk["type"], "content": chunk["content"]}
                yield f"data: {json_mod.dumps(event, ensure_ascii=False)}\n\n"
                if chunk["type"] == "content":
                    full_content += chunk["content"]

            actions = []
            import re as _re
            for m in _re.finditer(r'\{\s*["\x27]action["\x27]\s*:\s*["\x27]modify_script["\x27]\s*,\s*["\x27]script_name["\x27]\s*:\s*["\x27]([^"\x27]*)["\x27]\s*\}', full_content):
                script_name = m.group(1) or request.script_name
                code_match = _re.search(r'```python\s*\n(.*?)```', full_content[m.end():], _re.DOTALL)
                if not code_match:
                    code_match = _re.search(r'```\s*\n(.*?)```', full_content[m.end():m.end()+50000], _re.DOTALL)
                if code_match:
                    actions.append({"action": "modify_script", "script_name": script_name, "content": code_match.group(1).strip()})

            for m in _re.finditer(r'\{\s*["\x27]action["\x27]\s*:\s*["\x27]run["\x27]\s*,\s*["\x27]parameters["\x27]\s*:\s*(\{[^}]*\})\s*\}', full_content):
                try:
                    params = json_mod.loads(m.group(1).replace("'", '"'))
                    actions.append({"action": "run", "parameters": params})
                except json_mod.JSONDecodeError:
                    pass

            for action in actions:
                if action.get("action") == "modify_script":
                    script_name = action.get("script_name", request.script_name)
                    new_content = action.get("content", "")
                    if new_content:
                        write_skill_script(folder, script_name, new_content)
                        yield f"data: {json_mod.dumps({'type': 'script_updated', 'script_name': script_name}, ensure_ascii=False)}\n\n"

                elif action.get("action") == "run":
                    parameters = action.get("parameters", {})
                    for key in ["datasource_id", "datasource_name"]:
                        parameters.pop(key, None)

                    yield f"data: {json_mod.dumps({'type': 'executing', 'message': '正在执行技能...'}, ensure_ascii=False)}\n\n"

                    exec_result = run_skill_script(
                        skill_path=folder,
                        script_name=request.script_name,
                        parameters=parameters,
                        input_data=None,
                        datasource_id=request.datasource_id,
                        datasource_name=ds_name,
                        table_name=request.table_name,
                    )

                    exec_result = _sanitize_nans(exec_result)
                    yield f"data: {json_mod.dumps({'type': 'run_result', 'result': exec_result}, ensure_ascii=False, default=str)}\n\n"

                    skill.usage_count = (skill.usage_count or 0) + 1
                    await db.flush()

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


@router.post("/generate", response_model=SkillDetailResponse, status_code=status.HTTP_201_CREATED)
async def generate_skill_endpoint(
    request: SkillGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Skill Creator：根据自然语言描述生成完整 Skill 包"""
    try:
        generated = await generate_skill(request.prompt)
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

    name = front_matter.get("name", "generated-skill")
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

    async def event_stream():
        parsed_data = None
        async for event in generate_skill_stream(request.prompt):
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

        name = front_matter.get("name", "generated-skill")
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
            async for chunk in llm_manager.chat_stream_with_thinking(messages, temperature=0.3):
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


def _extract_function_params(tree) -> list[SkillParamDef]:
    import ast as _ast
    params = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        for arg in node.args.args:
            if arg.arg in ("self", "cls", "df", "input_data", "data"):
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
                type_map = {"int": "int", "float": "float", "bool": "bool",
                            "List": "list", "Optional": "str", "Dict": "dict",
                            "str": "str"}
                ptype = type_map.get(ann_str, "str")

            is_datasource = "datasource" in pname and "id" not in pname
            is_table = "table" in pname and "id" not in pname
            is_list = ptype == "list"

            has_default = False
            default_val = None
            defaults_start = len(node.args.args) - len(node.args.defaults)
            arg_idx = node.args.args.index(arg)
            if arg_idx >= defaults_start:
                has_default = True
                dv = node.args.defaults[arg_idx - defaults_start]
                if isinstance(dv, _ast.Constant):
                    default_val = dv.value
                elif isinstance(dv, _ast.NoneType):
                    default_val = None

            params.append(SkillParamDef(
                name=pname,
                type=ptype,
                required=not has_default,
                default=default_val,
                is_datasource=is_datasource,
                is_table=is_table,
                is_list=is_list,
            ))
        break
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