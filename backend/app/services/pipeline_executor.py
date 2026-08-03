"""Pipeline Executor - 复用 skill_runner 子进程沙箱执行流程主函数"""

import asyncio
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import Pipeline, PipelineExecution


def _to_uuid(value: Optional[str]) -> Optional[UUID]:
    """将字符串 user_id 转为 UUID（PipelineExecution.created_by 是 UUID 列）。"""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


async def _execute_builtin_pipeline(
    pipeline: Pipeline,
    inputs: Dict[str, Any],
    db: AsyncSession,
    user_id: Optional[str] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """内置流程分发器：根据 main_code 标识符调用对应处理函数"""
    handlers = {
        "metadata_sync_enrich": _builtin_metadata_sync_enrich,
    }
    handler = handlers.get(pipeline.main_code)
    if not handler:
        return {"success": False, "error": f"未知内置流程: {pipeline.main_code}", "stdout": ""}
    return await handler(inputs, db, user_id, progress_callback)


async def _builtin_metadata_sync_enrich(
    inputs: Dict[str, Any],
    db: AsyncSession,
    user_id: Optional[str] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """内置流程：同步所有数据源元数据 + AI业务增强"""
    from sqlalchemy import select
    from app.models.datasource import DataSource, TableMetadata

    async def _report(msg):
        log_lines.append(msg)
        if progress_callback:
            try:
                await progress_callback("\n".join(log_lines))
            except Exception:
                pass

    # 获取用户有权限的数据源（与 list_datasources 端点逻辑一致）
    from app.services.permission_service import get_accessible_resource_ids
    if user_id:
        try:
            uid = UUID(str(user_id))
            shared_ids = await get_accessible_resource_ids(db, uid, "datasource")
            result = await db.execute(
                select(DataSource).where(
                    DataSource.is_active == True,
                    or_(
                        DataSource.created_by == uid,
                        DataSource.id.in_(shared_ids) if shared_ids else False,
                    ),
                )
            )
        except (ValueError, AttributeError):
            result = await db.execute(select(DataSource).where(DataSource.is_active == True))
    else:
        result = await db.execute(select(DataSource).where(DataSource.is_active == True))
    datasources = result.scalars().all()

    total_synced = 0
    total_enriched = 0
    errors = []
    log_lines = []

    await _report(f"开始处理 {len(datasources)} 个数据源...")

    for ds in datasources:
        await _report(f"\n--- 数据源: {ds.name} ({ds.type}) ---")
        try:
            # 同步技术元数据
            from app.api.v1.endpoints.metadata import sync_datasource_metadata
            from fastapi import HTTPException
            try:
                sync_result = await sync_datasource_metadata(ds.id, db, None)
                synced = sync_result.get("synced", 0)
                total_synced += synced
                await _report(f"  同步完成: {synced} 张表")
                await db.flush()
            except HTTPException as he:
                errors.append(f"同步失败 {ds.name}: {he.detail}")
                await _report(f"  同步失败: {he.detail}")
                continue

            # AI 增强每张表（schema 未变且已增强的跳过，并发增强）
            tables_result = await db.execute(
                select(TableMetadata).where(TableMetadata.data_source_id == ds.id)
            )
            tables = tables_result.scalars().all()
            from app.api.v1.endpoints.metadata import _do_ai_enrich

            # 筛选需要增强的表
            to_enrich = []
            skipped = 0
            for table in tables:
                if table.ai_enriched and table.schema_hash:
                    skipped += 1
                else:
                    to_enrich.append(table)

            if skipped:
                await _report(f"  跳过 {skipped} 张表（schema 未变更）")

            # 并发增强（限并发 5）
            BATCH = 5
            for batch_start in range(0, len(to_enrich), BATCH):
                batch = to_enrich[batch_start:batch_start + BATCH]
                results = await asyncio.gather(
                    *[_do_ai_enrich(t, ds, db) for t in batch],
                    return_exceptions=True,
                )
                for t, r in zip(batch, results):
                    if isinstance(r, Exception):
                        errors.append(f"AI增强失败 {t.table_name}: {r}")
                    else:
                        total_enriched += 1
                await db.flush()
                done = min(batch_start + BATCH, len(to_enrich))
                await _report(f"  AI增强进度: {done}/{len(to_enrich)}")

            await _report(f"  AI增强完成: {len(tables)} 张表（跳过 {skipped} 张未变更）")
        except Exception as e:
            errors.append(f"数据源 {ds.name} 处理异常: {e}")
            await _report(f"  异常: {e}")

    summary = f"同步 {total_synced} 张表，AI增强 {total_enriched} 张表"
    if errors:
        summary += f"，{len(errors)} 个错误"
    await _report(f"\n汇总: {summary}")

    return {
        "success": True,
        "result": {"synced": total_synced, "enriched": total_enriched, "errors": errors},
        "stdout": "\n".join(log_lines),
    }


async def execute_pipeline(
    pipeline: Pipeline,
    inputs: Dict[str, Any],
    db: AsyncSession,
    user_id: Optional[str] = None,
    progress_callback=None,
) -> PipelineExecution:
    """同步执行流程（子进程沙箱，复用 skill_runner 执行框架）"""
    execution = PipelineExecution(
        pipeline_id=pipeline.id,
        status="running",
        inputs=inputs,
        started_at=datetime.utcnow(),
        created_by=_to_uuid(user_id),
    )
    db.add(execution)
    await db.flush()

    try:
        if pipeline.is_builtin:
            result = await _execute_builtin_pipeline(pipeline, inputs, db, user_id, progress_callback)
        else:
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
        created_by=_to_uuid(user_id),
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
