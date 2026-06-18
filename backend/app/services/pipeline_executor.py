"""Pipeline Executor - 编译并直接运行 Python 主函数"""

import asyncio
import io
import sys
import contextlib
import builtins
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
    """同步执行流程主函数"""
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
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            result = await _run_main_code(pipeline.main_code, pipeline.entry_function or "main", inputs)

        execution.status = "success"
        execution.outputs = _safe_serialize(result)
        execution.logs = stdout_capture.getvalue()
        if stderr_capture.getvalue():
            execution.logs = (execution.logs or "") + "\n[stderr]\n" + stderr_capture.getvalue()
    except Exception as e:
        execution.status = "failed"
        execution.error_message = str(e)
        logger.error(f"Pipeline 执行失败 [{pipeline.id}]: {e}")
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
    """SSE 流式执行流程主函数"""
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
    yield {"type": "status", "status": "running", "message": "正在编译主函数..."}

    try:
        stdout_capture = io.StringIO()

        with contextlib.redirect_stdout(stdout_capture):
            yield {"type": "status", "status": "running", "message": "正在执行..."}
            result = await _run_main_code(pipeline.main_code, pipeline.entry_function or "main", inputs)

        execution.status = "success"
        execution.outputs = _safe_serialize(result)
        execution.logs = stdout_capture.getvalue()

        yield {
            "type": "done",
            "status": "success",
            "outputs": execution.outputs,
            "logs": execution.logs,
        }
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


async def _run_main_code(code: str, entry: str, inputs: Dict[str, Any]) -> Any:
    """编译并运行主函数代码"""
    module_code = compile(code, "<pipeline>", "exec")
    namespace: Dict[str, Any] = {
        "__name__": "__pipeline__",
        "__builtins__": builtins,
    }
    exec(module_code, namespace)

    func = namespace.get(entry)
    if not callable(func):
        raise ValueError(f"入口函数 '{entry}' 不可调用")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(**inputs))


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
