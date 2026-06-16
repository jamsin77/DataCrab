"""技能管理API端点 - 遵循 Agent Skills 开放标准"""

import io
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


def _get_skill_storage() -> Path:
    path = Path(settings.SKILL_STORAGE_PATH)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_skill_folder(skill_id: UUID) -> Path:
    return _get_skill_storage() / str(skill_id)


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

    await db.delete(skill)
    await db.flush()


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
    inferred_table = parsed.get("table_name") or request.table_name
    datasource_id = request.datasource_id

    if not datasource_id and parsed.get("datasource_name"):
        from sqlalchemy import select as sa_select
        from app.models.datasource import Datasource
        ds_result = await db.execute(
            sa_select(Datasource).where(Datasource.name == parsed["datasource_name"])
        )
        ds = ds_result.scalar_one_or_none()
        if ds:
            datasource_id = str(ds.id)

    exec_result = run_skill_script(
        skill_path=folder,
        script_name=request.script_name,
        parameters=parameters,
        input_data=None,
        datasource_id=datasource_id,
        table_name=inferred_table,
    )

    skill.usage_count = (skill.usage_count or 0) + 1
    await db.flush()

    return SkillRunResponse(**exec_result)


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
        display_name=front_matter.get("name", name),
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
                "输出完整的 SKILL.md 内容，不要用代码块包裹。"
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
                "输出完整的 SKILL.md 内容，不要用代码块包裹。"
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
        if not isinstance(node, _ast.FunctionDef):
            continue
        for stmt in _ast.walk(node):
            if not isinstance(stmt, _ast.Call):
                continue
            if not isinstance(stmt.func, _ast.Attribute):
                continue
            if stmt.func.attr != "add_argument":
                continue
            if not stmt.args:
                continue
            arg_name = ""
            if isinstance(stmt.args[0], _ast.Constant):
                arg_name = stmt.args[0].value
            if not arg_name or not arg_name.startswith("--"):
                continue

            clean_name = arg_name.lstrip("-").replace("-", "_")
            kw_dict = {}
            for kw in stmt.keywords:
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


import re