"""流程管理API端点"""

import json
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
from app.models.pipeline import Pipeline, PipelineExecution
from app.models.skill import Skill
from app.schemas.pipeline import (
    PipelineCreate,
    PipelineUpdate,
    PipelineResponse,
    PipelineRunRequest,
    PipelineFromSkillRequest,
    PipelineExecutionResponse,
)
from app.services.pipeline_builder import build_pipeline_from_skill
from app.services.pipeline_executor import execute_pipeline, execute_pipeline_stream

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
    p.is_active = False
    await db.flush()
    return {"ok": True}


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

    logger.info(f"从 Skill 生成 Pipeline: {skill.name} ({skill_id})")

    try:
        built = await build_pipeline_from_skill(
            skill_path_str=skill.skill_path,
            skill_id=str(skill_id),
            skill_name=skill.name,
            skill_display_name=skill.display_name or skill.name,
        )
    except Exception as e:
        logger.error(f"Pipeline 生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"流程生成失败: {e}")

    display_name = (req.display_name if req else None) or f"{skill.display_name or skill.name} - 流程"

    pipeline = Pipeline(
        id=uuid4(),
        name=f"pl_{skill.name}",
        display_name=display_name,
        description=skill.description,
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
    """SSE 流式生成流程"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")

    async def event_stream():
        yield f"data: {json.dumps({'type': 'status', 'message': '正在分析 Skill 结构...'}, ensure_ascii=False)}\n\n"

        built = {}
        try:
            built = await build_pipeline_from_skill(
                skill_path_str=skill.skill_path,
                skill_id=str(skill_id),
                skill_name=skill.name,
                skill_display_name=skill.display_name or skill.name,
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return

        yield f"data: {json.dumps({'type': 'status', 'message': '正在创建流程...'}, ensure_ascii=False)}\n\n"

        display_name = (req.display_name if req else None) or f"{skill.display_name or skill.name} - 流程"

        pipeline = Pipeline(
            id=uuid4(),
            name=f"pl_{skill.name}",
            display_name=display_name,
            description=skill.description,
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

        resp = _build_response(pipeline)
        resp_data = resp.model_dump(mode="json")
        yield f"data: {json.dumps({'type': 'created', 'pipeline': resp_data}, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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

    async def event_stream():
        async for event in execute_pipeline_stream(
            p, (req.inputs if req else None) or {}, db, current_user.id
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{pipeline_id}/executions", response_model=list[PipelineExecutionResponse])
async def list_executions(
    pipeline_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
