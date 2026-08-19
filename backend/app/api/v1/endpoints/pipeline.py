"""流程管理API端点"""

import json
import re
import asyncio
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.permission_service import assert_resource_access
from app.models.pipeline import Pipeline, PipelineExecution
from app.models.skill import Skill
from app.schemas.pipeline import (
    PipelineCreate,
    PipelineUpdate,
    PipelineResponse,
    PipelineRunRequest,
    PipelineFromSkillRequest,
    PipelineExecutionResponse,
    PipelineDebugChatRequest,
)
from app.services.pipeline_builder import build_pipeline_from_skill
from app.services.pipeline_executor import execute_pipeline, execute_pipeline_stream
from app.services.llm import llm_manager, init_user_llm_context

router = APIRouter()


def _build_response(p: Pipeline) -> PipelineResponse:
    return PipelineResponse(
        id=p.id,
        name=p.name,
        display_name=p.display_name,
        description=p.description,
        main_code=p.main_code,
        entry_function=p.entry_function or "main",
        parameters=p.parameters or [],
        skill_calls=p.skill_calls or [],
        source_skill_id=p.source_skill_id,
        version=p.version or 1,
        tags=p.tags,
        category=p.category,
        visibility=p.visibility,
        is_active=p.is_active,
        is_builtin=getattr(p, "is_builtin", False) or False,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=list[PipelineResponse])
async def list_pipelines(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Pipeline).where(Pipeline.is_active == True)
    if category:
        query = query.where(Pipeline.category == category)
    if search:
        query = query.where(
            (Pipeline.name.ilike(f"%{search}%")) |
            (Pipeline.display_name.ilike(f"%{search}%"))
        )
    query = query.order_by(Pipeline.updated_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return [_build_response(p) for p in result.scalars().all()]


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="流程不存在")
    await assert_resource_access(db, current_user, "pipeline", p, "view")
    return _build_response(p)


@router.post("", response_model=PipelineResponse, status_code=201)
async def create_pipeline(
    req: PipelineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pipeline = Pipeline(
        id=uuid4(),
        name=req.name,
        display_name=req.display_name or req.name,
        description=req.description,
        main_code=req.main_code,
        entry_function=req.entry_function or "main",
        parameters=req.parameters or [],
        skill_calls=[c.model_dump() for c in (req.skill_calls or [])],
        tags=req.tags or [],
        category=req.category,
        visibility=req.visibility or "private",
        created_by=current_user.id,
    )
    db.add(pipeline)
    await db.flush()
    await db.refresh(pipeline)
    return _build_response(pipeline)


@router.put("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    pipeline_id: UUID,
    req: PipelineUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="流程不存在")
    await assert_resource_access(db, current_user, "pipeline", p, "manage")

    update_data = req.model_dump(exclude_unset=True)
    if "skill_calls" in update_data and update_data["skill_calls"] is not None:
        update_data["skill_calls"] = [
            c.model_dump() if hasattr(c, 'model_dump') else c
            for c in update_data["skill_calls"]
        ]
    for key, value in update_data.items():
        setattr(p, key, value)

    p.version = (p.version or 1) + 1
    await db.flush()
    await db.refresh(p)
    return _build_response(p)


@router.delete("/{pipeline_id}")
async def delete_pipeline(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="流程不存在")
    await assert_resource_access(db, current_user, "pipeline", p, "manage")
    if getattr(p, "is_builtin", False):
        raise HTTPException(status_code=403, detail="内置流程不可删除")
    p.is_active = False
    await db.flush()
    return {"ok": True}


def _read_last_success_params(skill_path_str: str):
    """从 experience.json positive 读最近成功执行参数"""
    try:
        from app.services import experience as _exp
        from pathlib import Path
        _positive = _exp.read_positive(Path(skill_path_str))
        for entry in reversed(_positive or []):
            _p = entry.get("parameters") or {}
            if _p:
                return _p
    except Exception:
        pass
    return None


@router.post("/from-skill/{skill_id}", response_model=PipelineResponse, status_code=201)
async def create_pipeline_from_skill(
    skill_id: UUID,
    req: Optional[PipelineFromSkillRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    await assert_resource_access(db, current_user, "skill", skill, "view")

    logger.info(f"从 Skill 生成 Pipeline: {skill.name} ({skill_id})")

    from app.services.skill_parser import read_skill_md
    from pathlib import Path
    import re as _re
    skill_md = read_skill_md(Path(skill.skill_path)) or ""
    func_desc = ""
    func_match = _re.search(r'##\s*📋?\s*功能说明\s*\n(.*?)(?=\n##\s|\Z)', skill_md, _re.DOTALL)
    if func_match:
        func_desc = func_match.group(1).strip()[:1000]
    if not func_desc:
        func_desc = skill.description or ""

    fixed_params = _read_last_success_params(skill.skill_path)
    if not fixed_params:
        raise HTTPException(status_code=400, detail="该技能尚未有成功执行记录，请先在调试页面成功执行一次后再转流程")

    try:
        built = await build_pipeline_from_skill(
            skill_path_str=skill.skill_path,
            skill_id=str(skill_id),
            skill_name=skill.name,
            skill_display_name=skill.display_name or skill.name,
            fixed_parameters=fixed_params,
        )
    except Exception as e:
        logger.error(f"Pipeline 生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"流程生成失败: {e}")

    display_name = (req.display_name if req else None) or f"{skill.display_name or skill.name} - 流程"

    # 查重：当前用户已为该技能转过的同名流程
    pl_name = f"pl_{skill.name}"
    mode = (req.mode if req else "skip") or "skip"
    existing = (await db.execute(
        select(Pipeline).where(Pipeline.name == pl_name, Pipeline.created_by == current_user.id)
    )).scalar_one_or_none()
    if existing and mode == "skip":
        # 默认 mode=skip：返回 existing 提示，前端弹窗选覆盖/另存为
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"流程 '{pl_name}' 已存在",
                "existing_pipeline_id": str(existing.id),
                "existing_display_name": existing.display_name or existing.name,
            },
        )
    if mode == "rename":
        new_disp = (req.new_name if req else None) or display_name
        display_name = new_disp
        import uuid as _uuid
        pl_name = f"pl_{skill.name}_{_uuid.uuid4().hex[:6]}"
        existing = None

    try:
        built = await build_pipeline_from_skill(
            skill_path_str=skill.skill_path,
            skill_id=str(skill_id),
            skill_name=skill.name,
            skill_display_name=skill.display_name or skill.name,
            fixed_parameters=fixed_params,
        )
    except Exception as e:
        logger.error(f"Pipeline 生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"流程生成失败: {e}")

    if existing and mode == "overwrite":
        existing.main_code = built["main_code"]
        existing.entry_function = built.get("entry_function", "main")
        existing.parameters = built.get("parameters", [])
        existing.skill_calls = built.get("skill_calls", [])
        existing.description = func_desc
        existing.display_name = display_name
        existing.source_skill_id = skill_id
        await db.flush()
        await db.refresh(existing)
        logger.info(f"流程已覆盖更新: {existing.display_name} ({existing.id})")
        return _build_response(existing)

    pipeline = Pipeline(
        id=uuid4(),
        name=pl_name,
        display_name=display_name,
        description=func_desc,
        main_code=built["main_code"],
        entry_function=built.get("entry_function", "main"),
        parameters=built.get("parameters", []),
        skill_calls=built.get("skill_calls", []),
        source_skill_id=skill_id,
        tags=skill.tags or [],
        category=skill.category,
        created_by=current_user.id,
    )
    db.add(pipeline)
    await db.flush()
    await db.refresh(pipeline)
    logger.info(f"流程已生成: {pipeline.display_name} ({pipeline.id})")
    return _build_response(pipeline)


@router.post("/from-skill-stream/{skill_id}")
async def create_pipeline_from_skill_stream(
    skill_id: UUID,
    req: Optional[PipelineFromSkillRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式转流程，推送转换进度（无 LLM，毫秒级机械转换）。

    转流程 = 把调试好的 skill 脚本原样转为 pipeline main_code，
    不重新生成代码，保留调试成果。
    """
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    await assert_resource_access(db, current_user, "skill", skill, "view")

    from app.services.skill_parser import read_skill_md
    from pathlib import Path

    async def event_stream():
        import json as json_mod
        try:
            yield f"data: {json_mod.dumps({'type': 'status', 'message': '正在读取调试好的脚本...'}, ensure_ascii=False)}\n\n"

            fixed_params = _read_last_success_params(skill.skill_path)
            if not fixed_params:
                yield f"data: {json_mod.dumps({'type': 'error', 'message': '该技能尚未有成功执行记录，请先在调试页面成功执行一次后再转流程'}, ensure_ascii=False)}\n\n"
                return

            skill_path = Path(skill.skill_path)
            skill_md = read_skill_md(skill_path) or ""
            func_desc = ""
            func_match = re.search(r'##\s*📋?\s*功能说明\s*\n(.*?)(?=\n##\s|\Z)', skill_md, re.DOTALL)
            if func_match:
                func_desc = func_match.group(1).strip()[:1000]
            if not func_desc:
                func_desc = skill.description or ""

            yield f"data: {json_mod.dumps({'type': 'status', 'message': '正在根据参数生成流程名称和描述...'}, ensure_ascii=False)}\n\n"

            display_name = ""
            description = ""
            try:
                from app.services.llm import llm_manager, init_user_llm_context
                await init_user_llm_context(current_user.id)
                await llm_manager.initialize()

                params_text = json_mod.dumps(fixed_params, ensure_ascii=False, indent=2)
                prompt = (
                    f"根据以下信息生成数据处理流程的显示名和描述。\n\n"
                    f"技能名称：{skill.display_name or skill.name}\n"
                    f"技能功能：{func_desc[:500]}\n"
                    f"固化参数：\n{params_text}\n\n"
                    f"请生成：\n"
                    f"1. display_name：简洁的流程名（不超过20字），反映实际数据处理过程\n"
                    f"2. description：流程描述（不超过100字），说明处理什么数据、怎么处理\n\n"
                    f'只输出 JSON，格式：{{"display_name": "...", "description": "..."}}'
                )

                response = await llm_manager.chat_with_messages(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=300,
                )

                text = response.strip()
                if "```json" in text:
                    text = text[text.index("```json") + 7:text.rindex("```")].strip()
                elif "```" in text:
                    text = text[text.index("```") + 3:text.rindex("```")].strip()
                result = json_mod.loads(text)
                display_name = result.get("display_name", "")
                description = result.get("description", "")
            except Exception as e:
                logger.warning(f"LLM 生成流程名称失败: {e}")

            if not display_name:
                display_name = (req.display_name if req else None) or f"{skill.display_name or skill.name} - 流程"
            if not description:
                description = func_desc

            # 查重：当前用户是否已为该技能转过流程（name=f"pl_{skill.name}"）
            pl_name = f"pl_{skill.name}"
            mode = (req.mode if req else "skip") or "skip"
            existing_q = select(Pipeline).where(
                Pipeline.name == pl_name,
                Pipeline.created_by == current_user.id,
            )
            existing = (await db.execute(existing_q)).scalar_one_or_none()

            if existing and mode == "skip":
                # 让前端弹窗选择覆盖/另存为
                yield f"data: {json_mod.dumps({'type': 'existing', 'pipeline_id': str(existing.id), 'existing_name': existing.name, 'existing_display_name': existing.display_name or existing.name}, ensure_ascii=False)}\n\n"
                return

            if mode == "rename":
                # 另存为：用用户填的新 display_name 生成新 name
                new_disp = (req.new_name if req else None) or display_name
                display_name = new_disp
                # name 加短随机后缀避免重复
                import uuid as _uuid
                pl_name = f"pl_{skill.name}_{_uuid.uuid4().hex[:6]}"
                existing = None  # 新建

            yield f"data: {json_mod.dumps({'type': 'status', 'message': '正在转换脚本并创建流程...'}, ensure_ascii=False)}\n\n"

            built = await build_pipeline_from_skill(
                skill_path_str=skill.skill_path,
                skill_id=str(skill_id),
                skill_name=skill.name,
                skill_display_name=skill.display_name or skill.name,
                fixed_parameters=fixed_params,
            )

            if existing and mode == "overwrite":
                # 覆盖现有流程：更新 main_code/参数/skill_calls/描述，保留 id
                existing.main_code = built["main_code"]
                existing.entry_function = built.get("entry_function", "main")
                existing.parameters = built.get("parameters", [])
                existing.skill_calls = built.get("skill_calls", [])
                existing.description = description
                existing.display_name = display_name
                existing.source_skill_id = skill_id
                await db.flush()
                await db.refresh(existing)
                logger.info(f"流程已覆盖更新: {existing.display_name} ({existing.id})")
                yield f"data: {json_mod.dumps({'type': 'done', 'pipeline_name': display_name, 'mode': 'overwrite'}, ensure_ascii=False)}\n\n"
                return

            pipeline = Pipeline(
                id=uuid4(),
                name=pl_name,
                display_name=display_name,
                description=description,
                main_code=built["main_code"],
                entry_function=built.get("entry_function", "main"),
                parameters=built.get("parameters", []),
                skill_calls=built.get("skill_calls", []),
                source_skill_id=skill_id,
                tags=skill.tags or [],
                category=skill.category,
                created_by=current_user.id,
            )
            db.add(pipeline)
            await db.flush()
            await db.refresh(pipeline)
            logger.info(f"流程已机械转换生成: {pipeline.display_name} ({pipeline.id})")

            yield f"data: {json_mod.dumps({'type': 'done', 'pipeline_name': display_name, 'mode': mode}, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json_mod.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/{pipeline_id}/run", response_model=PipelineExecutionResponse)
async def run_pipeline(
    pipeline_id: UUID,
    req: Optional[PipelineRunRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="流程不存在")
    await assert_resource_access(db, current_user, "pipeline", p, "use")

    execution = await execute_pipeline(
        p, (req.inputs if req else None) or {}, db, current_user.id
    )
    return PipelineExecutionResponse(
        id=execution.id,
        pipeline_id=execution.pipeline_id,
        status=execution.status,
        inputs=execution.inputs,
        outputs=execution.outputs,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        duration_ms=execution.duration_ms,
        error_message=execution.error_message,
        logs=execution.logs,
        created_at=execution.created_at,
    )


@router.post("/{pipeline_id}/run-stream")
async def run_pipeline_stream(
    pipeline_id: UUID,
    req: Optional[PipelineRunRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="流程不存在")
    await assert_resource_access(db, current_user, "pipeline", p, "use")

    async def event_stream():
        async for event in execute_pipeline_stream(
            p, (req.inputs if req else None) or {}, db, current_user.id
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{pipeline_id}/debug-chat")
async def debug_pipeline_chat(
    pipeline_id: UUID,
    req: PipelineDebugChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流程 AI 调试助手（多智能体架构：DataProcessor + DataInspector）"""
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="流程不存在")
    await assert_resource_access(db, current_user, "pipeline", p, "use")

    ctx = req.context or {}
    last_result = ctx.get("last_result", "")
    last_error = ctx.get("last_error", "")

    history = []
    for h in (req.history or [])[-10:]:
        history.append({"role": h.get("role", "user"), "content": h.get("content", "")})

    user_msg = req.message
    if last_result or last_error:
        user_msg += "\n\n[当前调试上下文]"
        if last_result:
            user_msg += f"\n上次执行结果: {last_result}"
        if last_error:
            user_msg += f"\n上次错误: {last_error[:500]}"

    from app.services.task_runner import prepare_pipeline_debug_runtime
    from app.services.multi_agent import stream_agent_events_sse
    runtime, message, context = await prepare_pipeline_debug_runtime(
        db, pipeline_id, current_user.id,
        history=history, user_message=user_msg, user_context=ctx,
    )
    if not runtime:
        raise HTTPException(status_code=404, detail="流程不存在")

    return StreamingResponse(
        stream_agent_events_sse(runtime, message, context, user_id=current_user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/{pipeline_id}/executions", response_model=list[PipelineExecutionResponse])
async def list_executions(
    pipeline_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="流程不存在")
    await assert_resource_access(db, current_user, "pipeline", p, "view")

    result = await db.execute(
        select(PipelineExecution)
        .where(PipelineExecution.pipeline_id == pipeline_id)
        .order_by(PipelineExecution.created_at.desc())
        .limit(limit)
    )
    executions = result.scalars().all()
    return [
        PipelineExecutionResponse(
            id=e.id,
            pipeline_id=e.pipeline_id,
            status=e.status,
            inputs=e.inputs,
            outputs=e.outputs,
            started_at=e.started_at,
            finished_at=e.finished_at,
            duration_ms=e.duration_ms,
            error_message=e.error_message,
            logs=e.logs,
            created_at=e.created_at,
        )
        for e in executions
    ]


@router.get("/executions/{execution_id}", response_model=PipelineExecutionResponse)
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PipelineExecution).where(PipelineExecution.id == execution_id)
    )
    e = result.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return PipelineExecutionResponse(
        id=e.id,
        pipeline_id=e.pipeline_id,
        status=e.status,
        inputs=e.inputs,
        outputs=e.outputs,
        started_at=e.started_at,
        finished_at=e.finished_at,
        duration_ms=e.duration_ms,
        error_message=e.error_message,
        logs=e.logs,
        created_at=e.created_at,
    )


@router.post("/{pipeline_id}/clone", response_model=PipelineResponse, status_code=201)
async def clone_pipeline(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="流程不存在")
    await assert_resource_access(db, current_user, "pipeline", original, "view")

    clone = Pipeline(
        id=uuid4(),
        name=f"{original.name}_clone",
        display_name=f"{original.display_name} (副本)",
        description=original.description,
        main_code=original.main_code,
        entry_function=original.entry_function,
        parameters=original.parameters,
        skill_calls=original.skill_calls,
        source_skill_id=original.source_skill_id,
        version=1,
        tags=original.tags,
        category=original.category,
        created_by=current_user.id,
        visibility="private",
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)
    return _build_response(clone)


@router.post("/import", response_model=PipelineResponse, status_code=201)
async def import_pipeline(
    req: PipelineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导入流程 JSON（与导出格式一致），创建新流程。

    前端读取 .json 文件后以 PipelineCreate 结构 POST 到此端点。
    name 冲突时自动加 _imported 后缀。
    """
    name = (req.name or "imported_pipeline").strip()
    existing = await db.execute(select(Pipeline).where(Pipeline.name == name, Pipeline.is_active == True))
    if existing.scalar_one_or_none():
        name = f"{name}_imported"

    pipeline = Pipeline(
        id=uuid4(),
        name=name,
        display_name=req.display_name or name,
        description=req.description,
        main_code=req.main_code or "",
        entry_function=req.entry_function or "main",
        parameters=req.parameters or [],
        skill_calls=[c.model_dump() for c in (req.skill_calls or [])],
        tags=req.tags or [],
        category=req.category,
        visibility=req.visibility or "private",
        created_by=current_user.id,
    )
    db.add(pipeline)
    await db.flush()
    await db.refresh(pipeline)
    logger.info(f"流程已导入: {pipeline.display_name} ({pipeline.id})")
    return _build_response(pipeline)


