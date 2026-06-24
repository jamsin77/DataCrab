"""工作流 API 端点"""

import json
import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from loguru import logger

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.workflow import Workflow, WorkflowExecution
from app.models.skill import Skill
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowRunRequest,
    WorkflowValidationResult,
    WorkflowExecutionResponse,
)
from app.services.workflow_builder import validate_dag, skill_to_workflow
from app.services.workflow_executor import LocalWorkflowExecutor

router = APIRouter()


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(
    category: Optional[str] = None,
    engine: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Workflow).where(Workflow.is_active == True)
    if category:
        q = q.where(Workflow.category == category)
    if engine:
        q = q.where(Workflow.engine == engine)
    if search:
        q = q.where(Workflow.name.ilike(f"%{search}%"))
    q = q.order_by(Workflow.updated_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/engines")
async def list_engines():
    return [
        {"id": "local", "name": "本地执行", "description": "直接在后端进程中执行，无需额外部署"},
        {"id": "prefect", "name": "Prefect", "description": "生产级工作流引擎，支持重试/并发/调度"},
    ]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return wf


@router.post("", response_model=WorkflowResponse)
async def create_workflow(
    req: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wf = Workflow(
        name=req.name,
        display_name=req.display_name,
        description=req.description,
        engine=req.engine,
        nodes=[n.model_dump() for n in req.nodes],
        edges=[e.model_dump() for e in req.edges],
        parameters=req.parameters,
        tags=req.tags,
        category=req.category,
        visibility=req.visibility,
        created_by=current_user.id,
    )
    db.add(wf)
    await db.flush()
    await db.refresh(wf)
    return wf


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID,
    req: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")

    update_data = req.model_dump(exclude_unset=True)
    if "nodes" in update_data and update_data["nodes"] is not None:
        update_data["nodes"] = [n.model_dump() if hasattr(n, "model_dump") else n for n in update_data["nodes"]]
    if "edges" in update_data and update_data["edges"] is not None:
        update_data["edges"] = [e.model_dump() if hasattr(e, "model_dump") else e for e in update_data["edges"]]

    for key, val in update_data.items():
        if val is not None:
            setattr(wf, key, val)

    wf.version = (wf.version or 1) + 1
    await db.flush()
    await db.refresh(wf)
    return wf


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    wf.is_active = False
    await db.flush()
    return {"success": True}


@router.post("/from-skill/{skill_id}", response_model=WorkflowResponse)
async def create_workflow_from_skill(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await db.execute(select(Skill).where(Skill.id == skill_id))
        skill = result.scalar_one_or_none()
        if not skill:
            raise HTTPException(status_code=404, detail="技能不存在")

        from app.services.skill_parser import read_skill_script
        from app.api.v1.endpoints.skill import _get_skill_folder, _extract_argparse_params, _extract_function_params

        folder = _get_skill_folder(skill_id)
        script_content = read_skill_script(folder, "main.py") or ""

        import ast as _ast
        script_params = []
        try:
            tree = _ast.parse(script_content)
            has_argparse = False
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        if alias.name == "argparse":
                            has_argparse = True
                elif isinstance(node, _ast.ImportFrom):
                    if node.module == "argparse":
                        has_argparse = True

            if has_argparse:
                script_params = _extract_argparse_params(script_content, tree)
            else:
                script_params = _extract_function_params(tree)
        except Exception:
            pass

        wf_def = skill_to_workflow(
            skill_id=str(skill_id),
            skill_name=skill.name or "",
            skill_display_name=skill.display_name,
            skill_description=skill.description,
            script_content=script_content,
            skill_params=[p.model_dump() if hasattr(p, "model_dump") else p for p in script_params],
        )

        wf = Workflow(
            name=wf_def["name"],
            display_name=wf_def["display_name"],
            description=wf_def["description"],
            engine=wf_def["engine"],
            nodes=wf_def["nodes"],
            edges=wf_def["edges"],
            parameters=wf_def["parameters"],
            source_skill_id=skill_id,
            category=skill.category,
            tags=skill.tags,
            created_by=current_user.id,
        )
        db.add(wf)
        await db.flush()
        await db.refresh(wf)
        return wf
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workflow_id}/validate", response_model=WorkflowValidationResult)
async def validate_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")

    valid, errors, warnings = validate_dag(wf.nodes or [], wf.edges or [])
    return WorkflowValidationResult(valid=valid, errors=errors, warnings=warnings)


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: UUID,
    req: Optional[WorkflowRunRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")

    inputs = req.inputs if req else {}

    executor = LocalWorkflowExecutor(db)
    exec_result = await executor.execute(
        workflow_id=workflow_id,
        nodes=wf.nodes or [],
        edges=wf.edges or [],
        inputs=inputs,
    )
    return exec_result


@router.post("/{workflow_id}/run-stream")
async def run_workflow_stream(
    workflow_id: UUID,
    req: Optional[WorkflowRunRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from fastapi.responses import StreamingResponse

    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")

    inputs = req.inputs if req else {}
    event_queue = []

    async def callback(event_type: str, data: dict):
        event_queue.append((event_type, data))

    async def event_stream():
        import asyncio

        executor = LocalWorkflowExecutor(db)

        task = asyncio.create_task(
            executor.execute(
                workflow_id=workflow_id,
                nodes=wf.nodes or [],
                edges=wf.edges or [],
                inputs=inputs,
                callback=callback,
            )
        )

        sent = 0
        while not task.done() or sent < len(event_queue):
            while sent < len(event_queue):
                evt_type, evt_data = event_queue[sent]
                yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False, default=str)}\n\n"
                sent += 1
            await asyncio.sleep(0.05)

        while sent < len(event_queue):
            evt_type, evt_data = event_queue[sent]
            yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False, default=str)}\n\n"
            sent += 1

        try:
            task.result()
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{workflow_id}/executions", response_model=list[WorkflowExecutionResponse])
async def list_executions(
    workflow_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(WorkflowExecution)
        .where(WorkflowExecution.workflow_id == workflow_id)
        .order_by(WorkflowExecution.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/executions/{execution_id}", response_model=WorkflowExecutionResponse)
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
    )
    exe = result.scalar_one_or_none()
    if not exe:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return exe


@router.post("/{workflow_id}/clone", response_model=WorkflowResponse)
async def clone_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")

    clone = Workflow(
        name=wf.name + "_copy",
        display_name=(wf.display_name or "") + " (副本)",
        description=wf.description,
        engine=wf.engine,
        nodes=wf.nodes,
        edges=wf.edges,
        parameters=wf.parameters,
        tags=wf.tags,
        category=wf.category,
        visibility=wf.visibility,
        created_by=current_user.id,
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)
    return clone
