"""智能体API端点"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.models.user import User
from app.api.deps import get_current_user
from app.services.multi_agent import (
    AgentRuntime, AgentMessage, HandoffReason, agent_registry
)
from app.services.data_processor_agent import DataProcessorAgent
from app.services.data_inspector_agent import DataInspectorAgent
from app.services.inspector_tools import inspector_tools
from app.schemas.agent import AgentRunRequest, InspectRequest, EtlInspectRequest, AgentInfo, AgentEventResponse

router = APIRouter()

_runtime: Optional[AgentRuntime] = None


def _get_runtime(db, user_id) -> AgentRuntime:
    global _runtime
    if _runtime is None:
        from app.services.multi_agent import ensure_agent_runtime
        _runtime = ensure_agent_runtime()
    return _runtime


@router.get("", response_model=list[AgentInfo])
async def list_agents():
    from app.services.multi_agent import ensure_agent_runtime
    ensure_agent_runtime()
    return agent_registry.list_agents()


@router.post("/{agent_name}/run")
async def run_agent(
    agent_name: str,
    request: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    runtime = _get_runtime(db, current_user.id)
    agent = agent_registry.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"智能体 '{agent_name}' 不存在")

    trace_id = str(uuid.uuid4())
    context = {
        "db": db,
        "user_id": current_user.id,
        "session_id": request.session_id,
        "datasource_context": "",
        "persona": "",
    }

    if request.datasource_id:
        context["current_datasource_id"] = request.datasource_id
    if request.table_name:
        context["current_table_name"] = request.table_name

    message = AgentMessage(
        from_agent="user",
        to_agent=agent_name,
        reason=HandoffReason.DELEGATE,
        payload={"user_message": request.message, "content": request.message},
        context=context,
        trace_id=trace_id,
    )

    async def generate():
        try:
            async for event in runtime.run(agent_name, message, context):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"智能体运行失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/inspect")
async def inspect_data(
    request: InspectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = {}
    all_issues = []

    try:
        profile = await inspector_tools.profile_data(request.datasource_id, request.table_name, db)
        results["profile"] = profile
    except Exception as e:
        logger.error(f"profile_data 失败: {e}")
        results["profile"] = {"error": str(e)}

    dimensions = request.check_dimensions or ["standards", "quality", "security"]

    if "standards" in dimensions:
        try:
            std_result = await inspector_tools.check_data_standards(
                request.datasource_id, request.table_name, db
            )
            results["standards"] = std_result
            all_issues.extend(std_result.get("issues", []))
        except Exception as e:
            logger.error(f"check_data_standards 失败: {e}")
            results["standards"] = {"error": str(e)}

    if "quality" in dimensions:
        try:
            quality_result = await inspector_tools.check_data_quality(
                request.datasource_id, request.table_name, db
            )
            results["quality"] = quality_result
            all_issues.extend(quality_result.get("issues", []))
        except Exception as e:
            logger.error(f"check_data_quality 失败: {e}")
            results["quality"] = {"error": str(e)}

    if "security" in dimensions:
        try:
            security_result = await inspector_tools.check_data_security(
                request.datasource_id, request.table_name, db
            )
            results["security"] = security_result
            all_issues.extend(security_result.get("issues", []))
        except Exception as e:
            logger.error(f"check_data_security 失败: {e}")
            results["security"] = {"error": str(e)}

    severity_order = {"fatal": 0, "critical": 1, "error": 2, "warning": 3, "info": 4}
    max_severity = "info"
    if all_issues:
        severities = [i.get("severity", "info") for i in all_issues]
        max_severity = min(severities, key=lambda s: severity_order.get(s, 3))

    results["summary"] = {
        "total_issues": len(all_issues),
        "max_severity": max_severity,
        "passed": len(all_issues) == 0,
    }

    return results


@router.post("/inspect-etl")
async def inspect_etl_quality(
    request: EtlInspectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ETL 过程质量对数检查（数据量波动 / 记录数·金额对数 / 检索不超总量）"""
    try:
        result = await inspector_tools.check_etl_quality(
            request.source_datasource_id,
            request.source_table,
            request.target_datasource_id,
            request.target_table,
            db,
            request.amount_column,
        )
        return result
    except Exception as e:
        logger.error(f"inspect_etl_quality 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events/{trace_id}", response_model=list[AgentEventResponse])
async def get_agent_events(
    trace_id: str,
    current_user: User = Depends(get_current_user),
):
    runtime = _get_runtime(None, None)
    events = runtime.event_store.get_trace(trace_id)
    return [
        AgentEventResponse(
            id=e.id,
            trace_id=e.trace_id,
            agent_name=e.agent_name,
            event_type=e.event_type,
            timestamp=e.timestamp.isoformat(),
            payload=e.payload,
        )
        for e in events
    ]


@router.get("/lineage/{datasource_id}/{table_name}", response_model=list[AgentEventResponse])
async def get_data_lineage(
    datasource_id: str,
    table_name: str,
    current_user: User = Depends(get_current_user),
):
    runtime = _get_runtime(None, None)
    events = runtime.event_store.get_lineage(datasource_id, table_name)
    return [
        AgentEventResponse(
            id=e.id,
            trace_id=e.trace_id,
            agent_name=e.agent_name,
            event_type=e.event_type,
            timestamp=e.timestamp.isoformat(),
            payload=e.payload,
        )
        for e in events
    ]
