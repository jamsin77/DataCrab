"""Pipeline Executor - 复用 skill_runner 子进程沙箱执行流程主函数"""

import asyncio
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import Pipeline, PipelineExecution


async def execute_pipeline(
    pipeline: Pipeline,
    inputs: Dict[str, Any],
    db: AsyncSession,
    user_id: Optional[str] = None,
) -> PipelineExecution:
    """同步执行流程（子进程沙箱，复用 skill_runner 执行框架）"""
    execution = PipelineExecution(
        pipeline_id=pipeline.id,
        status="running",
        inputs=inputs,
        started_at=datetime.utcnow(),
        created_by=user_id,
    )
    db.add(execution)
    await db.flush()

    try:
        from app.services.skill_runner import run_skill_script_by_content

        result = await asyncio.to_thread(
            run_skill_script_by_content,
            script_content=pipeline.main_code,
            parameters=inputs,
            user_id=str(user_id) if user_id else None,
            entry_function=pipeline.entry_function,
        )

        if result.get("success"):
            execution.status = "success"
            execution.outputs = _safe_serialize(result.get("result"))
            execution.logs = result.get("stdout", "")
        else:
            execution.status = "failed"
            execution.error_message = result.get("error") or "执行失败"
            execution.logs = result.get("stdout", "")
            logger.error(f"Pipeline 执行失败 [{pipeline.id}]: {execution.error_message}")
    except Exception as e:
        execution.status = "failed"
        execution.error_message = str(e)
        logger.error(f"Pipeline 执行异常 [{pipeline.id}]: {e}")
    finally:
        execution.finished_at = datetime.utcnow()
        if execution.started_at:
            execution.duration_ms = int(
                (execution.finished_at - execution.started_at).total_seconds() * 1000
            )
        await db.flush()

    return execution


async def execute_pipeline_stream(
    pipeline: Pipeline,
    inputs: Dict[str, Any],
    db: AsyncSession,
    user_id: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """SSE 流式执行流程（子进程沙箱，逐行推送 stdout 进度）"""
    execution = PipelineExecution(
        pipeline_id=pipeline.id,
        status="running",
        inputs=inputs,
        started_at=datetime.utcnow(),
        created_by=user_id,
    )
    db.add(execution)
    await db.flush()

    yield {"type": "status", "status": "running", "message": "流程开始执行..."}

    from app.services.skill_runner import run_skill_script_streaming_by_content

    _q: asyncio.Queue = asyncio.Queue()

    def _sync_gen():
        try:
            for item in run_skill_script_streaming_by_content(
                script_content=pipeline.main_code,
                parameters=inputs,
                user_id=str(user_id) if user_id else None,
                entry_function=pipeline.entry_function,
            ):
                _q.put_nowait(item)
        except Exception as e:
            _q.put_nowait({"type": "result", "result": {
                "success": False, "error": str(e), "stdout": "", "execution_time_ms": 0,
            }})
        _q.put_nowait(None)

    loop = asyncio.get_event_loop()
    task = loop.run_in_executor(None, _sync_gen)

    final_result = None
    try:
        while True:
            try:
                item = await asyncio.wait_for(_q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield {"type": "ping"}
                continue
            if item is None:
                break
            if item["type"] == "progress":
                yield {"type": "progress", "message": item["message"]}
            elif item["type"] == "result":
                final_result = item["result"]

        if final_result and final_result.get("success"):
            execution.status = "success"
            execution.outputs = _safe_serialize(final_result.get("result"))
            execution.logs = final_result.get("stdout", "")
            yield {
                "type": "done",
                "status": "success",
                "outputs": execution.outputs,
                "logs": execution.logs,
            }
        else:
            execution.status = "failed"
            execution.error_message = (final_result or {}).get("error", "执行失败")
            execution.logs = (final_result or {}).get("stdout", "")
            yield {"type": "error", "status": "failed", "message": execution.error_message}
    except Exception as e:
        execution.status = "failed"
        execution.error_message = str(e)
        yield {"type": "error", "status": "failed", "message": str(e)}
    finally:
        execution.finished_at = datetime.utcnow()
        if execution.started_at:
            execution.duration_ms = int(
                (execution.finished_at - execution.started_at).total_seconds() * 1000
            )
        await db.flush()
        await task


def _safe_serialize(obj: Any) -> Any:
    """安全序列化结果"""
    if obj is None:
        return None
    try:
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return {"columns": list(obj.columns), "rows": obj.head(100).to_dict(orient="records"), "total_rows": len(obj)}
        if isinstance(obj, pd.Series):
            return obj.to_dict()
    except ImportError:
        pass
    try:
        import json
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
