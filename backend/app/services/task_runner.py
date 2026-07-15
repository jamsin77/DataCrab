"""调度任务后台执行器 - 根据 task_type 分派到 skill/operator/pipeline 执行器"""

import asyncio
import inspect
import io
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.models.schedule import Schedule, TaskExecution
from app.models.operator import Operator
from app.models.skill import Skill
from app.services.sandbox_ns import build_operator_namespace


async def execute_task(
    execution_id: UUID,
    task_type: str,
    task_target_id: UUID,
    task_params: Optional[Dict[str, Any]] = None,
    user_id: Optional[UUID] = None,
    timeout: int = 3600,
) -> None:
    """后台执行调度任务，更新 TaskExecution 与 Schedule 记录。

    由 schedule.py 的 trigger_schedule 通过 BackgroundTasks 调用，
    在独立 db session 中运行，不依赖请求上下文。
    """
    async with async_session() as db:
        result = await db.execute(
            select(TaskExecution).where(TaskExecution.id == execution_id)
        )
        execution = result.scalar_one_or_none()
        if not execution:
            logger.error(f"任务执行记录不存在: {execution_id}")
            return

        execution.status = "running"
        execution.started_at = datetime.utcnow()
        await db.flush()

        start_time = time.time()
        success = False
        result_data: Optional[Dict[str, Any]] = None
        error_msg: Optional[str] = None
        logs: Optional[str] = None

        try:
            if task_type == "skill":
                success, result_data, error_msg, logs = await _run_skill(
                    db, task_target_id, task_params or {}, user_id, timeout
                )
            elif task_type == "operator":
                success, result_data, error_msg, logs = await _run_operator(
                    db, task_target_id, task_params or {}, user_id
                )
            elif task_type == "pipeline":
                success, result_data, error_msg, logs = await _run_pipeline(
                    db, task_target_id, task_params or {}, user_id
                )
            else:
                raise ValueError(f"不支持的任务类型: {task_type}")
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logs = traceback.format_exc()
            logger.error(f"调度任务执行异常 [{execution_id}]: {e}")

        execution.status = "success" if success else "failed"
        execution.finished_at = datetime.utcnow()
        execution.duration = int(time.time() - start_time)
        execution.result = result_data if isinstance(result_data, dict) else None
        execution.error_message = error_msg
        execution.logs = logs
        execution.exit_code = 0 if success else 1

        sched_result = await db.execute(
            select(Schedule).where(Schedule.id == execution.schedule_id)
        )
        schedule = sched_result.scalar_one_or_none()
        if schedule:
            schedule.last_run_at = execution.finished_at
            schedule.last_run_status = execution.status
            _reschedule_next_run(schedule)

        await db.commit()
        logger.info(
            f"调度任务完成 [{execution_id}] task_type={task_type} status={execution.status} duration={execution.duration}s"
        )


def _reschedule_next_run(schedule: Schedule) -> None:
    """根据调度类型重新计算下次执行时间"""
    if schedule.schedule_type == "cron" and schedule.cron_expression:
        from croniter import croniter
        cron = croniter(schedule.cron_expression, datetime.utcnow())
        schedule.next_run_at = cron.get_next(datetime)
    elif schedule.schedule_type == "interval" and schedule.interval_seconds:
        schedule.next_run_at = datetime.utcnow() + timedelta(
            seconds=schedule.interval_seconds
        )


async def _run_skill(
    db, skill_id: UUID, params: Dict[str, Any], user_id: Optional[UUID], timeout: int
) -> Tuple[bool, Optional[Dict], Optional[str], Optional[str]]:
    """执行技能脚本（同步沙箱，放线程池）"""
    from app.services.skill_runner import run_skill_script

    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        return False, None, "技能不存在", None

    folder = Path(settings.SKILL_STORAGE_PATH) / str(skill_id)
    script_name = params.get("script_name", "main.py")
    parameters = params.get("parameters", {})
    input_data = params.get("input_data")
    datasource_id = params.get("datasource_id")
    table_name = params.get("table_name")

    exec_result = await asyncio.to_thread(
        run_skill_script,
        skill_path=folder,
        script_name=script_name,
        parameters=parameters,
        input_data=input_data,
        datasource_id=datasource_id,
        table_name=table_name,
        timeout=timeout,
        user_id=str(user_id) if user_id else None,
    )

    skill.usage_count = (skill.usage_count or 0) + 1
    await db.flush()

    success = exec_result.get("success", False)
    return success, exec_result, exec_result.get("error"), exec_result.get("stdout")


async def _run_operator(
    db, operator_id: UUID, params: Dict[str, Any], user_id: Optional[UUID]
) -> Tuple[bool, Optional[Dict], Optional[str], Optional[str]]:
    """执行算子脚本（exec + func call）"""
    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        return False, None, "算子不存在", None
    if not operator.script_content:
        return False, None, "该算子没有可执行的脚本", None

    captured_output = io.StringIO()

    def _exec_sync() -> Any:
        local_ns = {
            "__builtins__": __builtins__,
            "print": lambda *a, **kw: print(*a, file=captured_output, **kw),
        }
        local_ns.update(build_operator_namespace(user_id))
        exec(operator.script_content, local_ns)
        func = local_ns.get(operator.function_name or "")
        if not func:
            available = [k for k in local_ns if callable(local_ns[k]) and not k.startswith("_")]
            raise ValueError(
                f"脚本中未找到函数: {operator.function_name}，可用函数: {available}"
            )
        return func

    try:
        func = await asyncio.to_thread(_exec_sync)
        is_async = inspect.iscoroutinefunction(func)
        if is_async:
            result_value = await func(**params)
        else:
            result_value = await asyncio.to_thread(func, **params)

        if hasattr(result_value, "to_dict"):
            result_value = result_value.to_dict(orient="records")

        return True, {"result": result_value}, None, captured_output.getvalue() or None
    except Exception as e:
        return (
            False,
            None,
            f"{type(e).__name__}: {e}",
            captured_output.getvalue() or None,
        )


async def _run_pipeline(
    db, pipeline_id: UUID, params: Dict[str, Any], user_id: Optional[UUID]
) -> Tuple[bool, Optional[Dict], Optional[str], Optional[str]]:
    """执行流程主函数"""
    from app.models.pipeline import Pipeline
    from app.services.pipeline_executor import execute_pipeline

    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        return False, None, "流程不存在", None

    inputs = params.get("inputs", params)
    execution = await execute_pipeline(pipeline, inputs, db, str(user_id) if user_id else None)

    success = execution.status == "success"
    error_msg = execution.error_message if not success else None
    logs = execution.logs
    result_data = {
        "pipeline_execution_id": str(execution.id),
        "status": execution.status,
        "outputs": execution.outputs,
    }
    return success, result_data, error_msg, logs


# ===== 定时调度扫描器 =====

_scheduler_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None
SCAN_INTERVAL = 30  # 扫描间隔（秒）


async def start_scheduler(scan_interval: int = SCAN_INTERVAL):
    """启动定时调度扫描器（由 main.py lifespan 调用）"""
    global _scheduler_task, _stop_event
    _stop_event = asyncio.Event()
    _scheduler_task = asyncio.create_task(_scheduler_loop(scan_interval))
    logger.info(f"定时调度扫描器已启动，扫描间隔 {scan_interval}s")


async def stop_scheduler():
    """停止定时调度扫描器（由 main.py lifespan shutdown 调用）"""
    global _scheduler_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _scheduler_task:
        try:
            await asyncio.wait_for(_scheduler_task, timeout=10)
        except asyncio.TimeoutError:
            _scheduler_task.cancel()
            try:
                await _scheduler_task
            except asyncio.CancelledError:
                pass
    logger.info("定时调度扫描器已停止")


async def _scheduler_loop(scan_interval: int):
    """扫描循环：周期检查到期调度并触发执行"""
    while _stop_event and not _stop_event.is_set():
        try:
            await _scan_and_trigger()
        except Exception as e:
            logger.error(f"调度扫描异常: {e}")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=scan_interval)
        except asyncio.TimeoutError:
            pass


async def _scan_and_trigger():
    """扫描所有 next_run_at 到期的 active 调度"""
    now = datetime.utcnow()
    async with async_session() as db:
        result = await db.execute(
            select(Schedule.id, Schedule.name).where(
                Schedule.status == "active",
                Schedule.next_run_at != None,
                Schedule.next_run_at <= now,
            )
        )
        due = result.all()

    if not due:
        return

    for schedule_id, schedule_name in due:
        try:
            await _trigger_scheduled(schedule_id, schedule_name)
        except Exception as e:
            logger.error(f"触发调度 {schedule_name}({schedule_id}) 失败: {e}")


async def _trigger_scheduled(schedule_id: UUID, schedule_name: str):
    """触发单个到期调度：并发检查 → 创建执行记录 → 重算 next_run_at → 后台执行"""
    from sqlalchemy import func

    async with async_session() as db:
        # 重新查 schedule（确认仍 active 且仍到期）
        result = await db.execute(
            select(Schedule).where(Schedule.id == schedule_id)
        )
        sched = result.scalar_one_or_none()
        if not sched or sched.status != "active":
            return
        if not sched.next_run_at or sched.next_run_at > datetime.utcnow():
            return

        # 并发数检查
        running_result = await db.execute(
            select(func.count(TaskExecution.id)).where(
                TaskExecution.schedule_id == schedule_id,
                TaskExecution.status.in_(["pending", "running"]),
            )
        )
        running_count = running_result.scalar() or 0
        if running_count >= (sched.concurrent_runs or 1):
            logger.debug(
                f"调度 {schedule_name} 并发已满 ({running_count}/{sched.concurrent_runs})，跳过"
            )
            return

        # 创建执行记录
        execution = TaskExecution(
            schedule_id=sched.id,
            task_type=sched.task_type,
            task_target_id=sched.task_target_id,
            status="pending",
            trigger_type="schedule",
            triggered_by=sched.created_by,
        )
        db.add(execution)

        # 重算 next_run_at（防止下一轮扫描重复触发）
        _reschedule_next_run(sched)

        await db.commit()
        await db.refresh(execution)

        # 捕获执行所需参数（session 关闭后 detached）
        task_type = sched.task_type
        task_target_id = sched.task_target_id
        task_params = sched.task_params
        user_id = sched.created_by
        timeout = sched.timeout or 3600
        execution_id = execution.id

    # 后台执行（独立 db session）
    asyncio.create_task(
        execute_task(
            execution_id=execution_id,
            task_type=task_type,
            task_target_id=task_target_id,
            task_params=task_params,
            user_id=user_id,
            timeout=timeout,
        )
    )
    logger.info(f"定时触发: {schedule_name} -> execution {execution_id}")
