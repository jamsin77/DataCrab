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
    """SSE 流式生成流程，推送推理过程"""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")

    from app.services.llm import llm_manager
    from app.services.pipeline_builder import (
        build_pipeline_from_skill, PIPELINE_BUILDER_SYSTEM_PROMPT,
    )
    from app.services.skill_parser import read_skill_md, read_skill_script, list_skill_scripts
    from pathlib import Path
    import asyncio

    await init_user_llm_context(current_user.id)
    await llm_manager.initialize()

    skill_path = Path(skill.skill_path)
    skill_md = read_skill_md(skill_path) or ""
    scripts = {}
    for script_info in list_skill_scripts(skill_path):
        name = script_info["name"] if isinstance(script_info, dict) else script_info
        content = script_info.get("content") if isinstance(script_info, dict) else read_skill_script(skill_path, script_info)
        scripts[name] = content

    # 从 SKILL.md 提取功能说明，作为流程备注
    import re as _re
    func_desc = ""
    func_match = _re.search(r'##\s*📋?\s*功能说明\s*\n(.*?)(?=\n##\s|\Z)', skill_md, _re.DOTALL)
    if func_match:
        func_desc = func_match.group(1).strip()[:1000]
    if not func_desc:
        func_desc = skill.description or ""

    scripts_text = ""
    for name, content in scripts.items():
        scripts_text += f"\n### scripts/{name}\n```python\n{content}\n```\n"

    user_prompt = (
        f"请根据以下 Skill 信息生成一个完整的 Python 流程主函数。\n\n"
        f"## Skill 信息\n- 名称: {skill.name}\n- 显示名称: {skill.display_name or skill.name}\n\n"
        f"## SKILL.md 内容\n{skill_md[:3000]}\n\n"
        f"## 脚本内容\n{scripts_text[:8000]}\n\n"
        f"请生成完整的 Python 主函数文件。"
    )

    messages = [
        {"role": "system", "content": PIPELINE_BUILDER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    async def event_stream():
        import json as json_mod
        try:
            yield f"data: {json_mod.dumps({'type': 'status', 'message': '正在分析 Skill 结构...'}, ensure_ascii=False)}\n\n"

            full_content = ""
            async for chunk in llm_manager.chat_stream_with_thinking(messages, temperature=0.2, context="流程生成"):
                event = {"type": chunk["type"], "content": chunk["content"]}
                yield f"data: {json_mod.dumps(event, ensure_ascii=False)}\n\n"
                if chunk["type"] == "content":
                    full_content += chunk["content"]

            yield f"data: {json_mod.dumps({'type': 'status', 'message': '正在解析代码并创建流程...'}, ensure_ascii=False)}\n\n"

            built = await build_pipeline_from_skill(
                skill_path_str=skill.skill_path,
                skill_id=str(skill_id),
                skill_name=skill.name,
                skill_display_name=skill.display_name or skill.name,
            )
            # 覆盖为流式获取的代码（更完整）
            if full_content.strip():
                from app.services.pipeline_builder import _extract_python_code
                built["main_code"] = _extract_python_code(full_content)

            display_name = (req.display_name if req else None) or f"{skill.display_name or skill.name} - 流程"

            pipeline = Pipeline(
                id=uuid4(),
                name=f"pl_{skill.name}",
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
            logger.info(f"流程已流式生成: {pipeline.display_name} ({pipeline.id})")

            yield f"data: {json_mod.dumps({'type': 'done', 'pipeline_name': display_name}, ensure_ascii=False)}\n\n"

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

    await init_user_llm_context(current_user.id)
    await llm_manager.initialize()

    main_code = p.main_code or ""
    entry_function = p.entry_function or "main"
    display_name = p.display_name or p.name

    ctx = req.context or {}
    last_result = ctx.get("last_result", "")
    last_error = ctx.get("last_error", "")

    from app.services.multi_agent import AgentRuntime, AgentMessage, HandoffReason, agent_registry
    from app.services.data_processor_agent import DataProcessorAgent
    from app.services.data_inspector_agent import DataInspectorAgent

    if not agent_registry.get("data_processor"):
        agent_registry.register(DataProcessorAgent())
    if not agent_registry.get("data_inspector"):
        agent_registry.register(DataInspectorAgent())

    runtime = AgentRuntime(agent_registry, llm_manager)

    history = []
    for h in (req.history or [])[-10:]:
        history.append({"role": h.get("role", "user"), "content": h.get("content", "")[:500]})

    user_msg = req.message
    if last_result or last_error:
        user_msg += "\n\n[当前调试上下文]"
        if last_result:
            user_msg += f"\n上次执行结果: {last_result}"
        if last_error:
            user_msg += f"\n上次错误: {last_error[:500]}"

    context = {
        "debug_mode": True,
        "debug_type": "pipeline",
        "db": db,
        "user_id": current_user.id,
        "history": history,
        "debug_pipeline_id": pipeline_id,
        "debug_script_name": entry_function,
        "debug_script_content": main_code,
        "debug_function_name": entry_function,
        "debug_last_success_params": None,
        "debug_lessons": "",
        "debug_user_context": ctx,
        "debug_max_rounds": 7,"debug_max_inspections": 7,
    }

    message = AgentMessage(
        from_agent="user",
        to_agent="data_processor",
        reason=HandoffReason.DELEGATE,
        payload={"user_message": user_msg},
        context=context,
    )

    async def generate():
        import asyncio
        from app.services.llm import init_user_llm_context
        await init_user_llm_context(current_user.id)

        runtime_gen = runtime.run("data_processor", message, context)

        _inspector_active = False
        _inspector_summary = ""
        _inspector_content_sent = False
        try:
            while True:
                try:
                    event = await asyncio.wait_for(runtime_gen.__anext__(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping'}, ensure_ascii=False)}\n\n"
                    continue
                except StopAsyncIteration:
                    break

                t = event.get("type")
                if t == "agent_switch":
                    agent = event.get("agent")
                    _inspector_active = (agent == "data_inspector")
                    if agent == "data_inspector":
                        evt = {"type": "inspecting", "message": "执行成功，DataInspector 正在检查数据质量..."}
                    elif agent == "data_processor":
                        _retry_round = context.get("debug_inspection_round", 0) + 1
                        evt = {"type": "retry", "round": _retry_round, "message": f"DataInspector 发现问题，第 {_retry_round} 轮修复..."}
                    else:
                        evt = None
                    if evt:
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                elif t == "done":
                    if _inspector_active and _inspector_summary and not _inspector_content_sent:
                        yield f"data: {json.dumps({'type': 'content', 'content': _inspector_summary}, ensure_ascii=False)}\n\n"
                    _inspector_active = False
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                elif _inspector_active and t == "warning_confirmation":
                    _inspector_summary = event.get("summary", "")
                elif _inspector_active and t == "content":
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    _inspector_content_sent = True
                elif _inspector_active and t == "fatal":
                    _inspector_summary = event.get("summary", "") or "发现致命问题，已停止处理"
                elif _inspector_active and t == "tool_result":
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                else:
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流程调试对话失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


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


@router.post("/export-seed")
async def export_seed(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出所有流程到 seed 文件（data/seed/pipelines.json），供新机器安装时自动加载"""
    from pathlib import Path as _Path
    from app.core.config import settings as _settings
    result = await db.execute(select(Pipeline))
    pipelines = result.scalars().all()
    seen = set()
    data = []
    for p in pipelines:
        if p.name in seen:
            continue
        seen.add(p.name)
        data.append({
            "name": p.name,
            "display_name": p.display_name or p.name,
            "description": p.description or "",
            "main_code": p.main_code or "",
            "entry_function": p.entry_function or "main",
            "parameters": p.parameters or [],
            "skill_calls": p.skill_calls or [],
            "tags": p.tags or [],
            "category": p.category or "seed",
            "visibility": p.visibility or "public",
        })
    seed_dir = _Path(_settings.SKILL_STORAGE_PATH).parent / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_file = seed_dir / "pipelines.json"
    seed_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"exported": len(data), "path": str(seed_file)}
