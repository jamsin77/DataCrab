"""调度任务后台执行器 - 根据 task_type 分派到 skill/operator/pipeline 执行器"""

import asyncio
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.models.schedule import Schedule, TaskExecution
from app.models.operator import Operator
from app.models.skill import Skill
from app.services.permission_service import check_permission


async def _commit_with_retry(db, max_attempts: int = 3, base_delay: float = 0.5) -> bool:
    """SQLite commit 重试（处理 database is locked）。
    失败后 rollback 再重试，避免 PendingRollbackError 连锁。
    返回 True 表示成功，False 表示最终失败（调用方负责降级处理）。"""
    for attempt in range(max_attempts):
        try:
            await db.commit()
            return True
        except Exception as e:
            try:
                await db.rollback()
            except Exception:
                pass
            if attempt < max_attempts - 1:
                logger.warning(f"commit 失败（第{attempt+1}次），{base_delay * (attempt + 1):.1f}s 后重试: {e}")
                await asyncio.sleep(base_delay * (attempt + 1))
            else:
                logger.error(f"commit 最终失败（{max_attempts}次）: {e}")
                return False
    return False


async def execute_task(
    execution_id: UUID,
    task_type: str,
    task_target_id: UUID,
    task_params: Optional[Dict[str, Any]] = None,
    user_id: Optional[UUID] = None,
    timeout: int = 3600,
    run_mode: str = "normal",
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
        if execution.status == "running":
            logger.warning(f"执行记录已在运行中，跳过重复执行: {execution_id}")
            return
        execution.status = "running"
        execution.started_at = datetime.utcnow()
        execution.logs = "正在执行..."  # 占位日志，让前端详情能看到执行中状态
        if not await _commit_with_retry(db):
            logger.error(f"设置执行记录 running 状态失败: {execution_id}")
            return  # commit 失败无法继续，避免后续操作卡死

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
                if run_mode == "auto_fix":
                    success, result_data, error_msg, logs = await _run_pipeline_auto_fix(
                        db, task_target_id, task_params or {}, user_id,
                        execution_id=execution_id, timeout=timeout,
                    )
                else:
                    success, result_data, error_msg, logs = await _run_pipeline(
                        db, task_target_id, task_params or {}, user_id,
                        execution_id=execution_id,
                    )
            else:
                raise ValueError(f"不支持的任务类型: {task_type}")
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logs = traceback.format_exc()
            logger.error(f"调度任务执行异常 [{execution_id}]: {e}")
            # 子任务崩溃可能留下未提交的脏事务，回滚后重新加载执行记录，
            # 确保状态能正确写入 failed 而非永远卡在 pending
            try:
                await db.rollback()
            except Exception:
                pass
            result = await db.execute(
                select(TaskExecution).where(TaskExecution.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            if not execution:
                return

        # 更新执行记录最终状态（带重试，处理 SQLite database is locked + PendingRollbackError 连锁）
        for _final_attempt in range(3):
            try:
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

                if await _commit_with_retry(db):
                    break
                # commit 重试耗尽 → rollback 后重新加载对象再试
                if _final_attempt < 2:
                    logger.warning(f"更新执行记录状态失败（第{_final_attempt+1}次），重新加载后重试")
                    result = await db.execute(
                        select(TaskExecution).where(TaskExecution.id == execution_id)
                    )
                    execution = result.scalar_one_or_none()
                    if not execution:
                        return
            except Exception as final_err:
                logger.warning(f"更新执行记录状态异常（第{_final_attempt+1}次）: {final_err}")
                try:
                    await db.rollback()
                except Exception:
                    pass
                if _final_attempt < 2:
                    await asyncio.sleep(0.5 * (_final_attempt + 1))
                    result = await db.execute(
                        select(TaskExecution).where(TaskExecution.id == execution_id)
                    )
                    execution = result.scalar_one_or_none()
                    if not execution:
                        return
                else:
                    logger.error(f"更新执行记录状态最终失败: {final_err}")
        logger.info(
            f"调度任务完成 [{execution_id}] task_type={task_type} status={execution.status} duration={execution.duration}s"
        )


def compute_next_cron_run(cron_expression: str, tz_name: str = "UTC") -> datetime:
    """计算 cron 表达式下次执行时间（按指定时区解释），返回 UTC naive datetime。

    cron 表达式按 ``tz_name`` 的本地墙钟时间解释，结果转换为 UTC 存储，
    与扫描器 ``datetime.utcnow()`` 比较保持一致。支持 ``;`` 分隔多个表达式。
    无效时区直接抛错（全球系统不做隐式回退）。
    """
    from croniter import croniter

    exprs = [e.strip() for e in cron_expression.split(";") if e.strip()]
    if not exprs:
        raise ValueError("Cron表达式为空")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        raise ValueError(f"无效的时区: {tz_name}")
    now_local = datetime.now(tz).replace(tzinfo=None)
    next_times: list[datetime] = []
    for expr in exprs:
        try:
            next_times.append(croniter(expr, now_local).get_next(datetime))
        except Exception:
            raise ValueError(f"无效的Cron表达式: {expr}")
    next_local = min(next_times)
    return next_local.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def _reschedule_next_run(schedule: Schedule) -> None:
    """根据调度类型重新计算下次执行时间（cron 按时区解释，返回 UTC）"""
    if schedule.schedule_type == "cron" and schedule.cron_expression:
        schedule.next_run_at = compute_next_cron_run(
            schedule.cron_expression, schedule.timezone or "UTC"
        )
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

    # 权限软校验：非 owner 需 use 级授权（防调度迁移后越权）
    if user_id and skill.created_by != user_id:
        from app.models.user import User
        u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if u and not u.is_superuser:
            has_perm = await check_permission(db, user_id, "skill", skill_id, "use", is_owner=False)
            if not has_perm and skill.visibility != "public":
                return False, None, f"用户无权执行技能 {skill.name}", None

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
    """执行算子脚本（通过 skill_runner 沙箱执行，和技能/流程统一）"""
    from app.services.skill_runner import run_skill_script_by_content_async

    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    operator = result.scalar_one_or_none()
    if not operator:
        return False, None, "算子不存在", None
    if not operator.script_content:
        return False, None, "该算子没有可执行的脚本", None

    # 权限软校验：非 owner 需 use 级授权
    if user_id and operator.created_by != user_id:
        from app.models.user import User
        u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if u and not u.is_superuser:
            has_perm = await check_permission(db, user_id, "operator", operator_id, "use", is_owner=False)
            if not has_perm and operator.visibility != "public":
                return False, None, f"用户无权执行算子 {operator.name}", None

    try:
        exec_result = await run_skill_script_by_content_async(
            script_content=operator.script_content,
            parameters=params,
            user_id=str(user_id) if user_id else None,
            entry_function=operator.function_name,
            timeout=600,
        )
        success = exec_result.get("success", False)
        result_data = {"result": exec_result.get("result")} if success else None
        error_msg = exec_result.get("error") if not success else None
        stdout = exec_result.get("stdout") or None
        return success, result_data, error_msg, stdout
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}", None


async def _run_pipeline(
    db, pipeline_id: UUID, params: Dict[str, Any], user_id: Optional[UUID],
    execution_id: Optional[UUID] = None,
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

    # 权限软校验：非 owner 需 use 级授权
    if user_id and pipeline.created_by != user_id:
        from app.models.user import User
        u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if u and not u.is_superuser:
            has_perm = await check_permission(db, user_id, "pipeline", pipeline_id, "use", is_owner=False)
            if not has_perm and pipeline.visibility != "public":
                return False, None, f"用户无权执行流程 {pipeline.name}", None

    inputs = params.get("inputs", params)

    # 内置流程：实时进度回调，更新 TaskExecution.logs
    progress_cb = None
    if pipeline.is_builtin and execution_id:
        from app.models.schedule import TaskExecution as TE
        async def _progress(logs_text):
            try:
                ex = (await db.execute(select(TE).where(TE.id == execution_id))).scalar_one_or_none()
                if ex:
                    ex.logs = logs_text
                    await db.commit()
            except Exception:
                pass
        progress_cb = _progress

    execution = await execute_pipeline(pipeline, inputs, db, str(user_id) if user_id else None, progress_callback=progress_cb)

    success = execution.status == "success"
    error_msg = execution.error_message if not success else None
    logs = execution.logs
    result_data = {
        "pipeline_execution_id": str(execution.id),
        "status": execution.status,
        "outputs": execution.outputs,
    }
    return success, result_data, error_msg, logs


async def prepare_pipeline_debug_runtime(
    db, pipeline_id: UUID, user_id: Optional[UUID],
    history: list = None, user_message: str = "执行流程并检查结果",
    user_context: dict = None, last_success_params=None,
):
    """构建流程调试/自修复的 AgentRuntime 上下文（调试端点 + 调度自修复共享）。

    返回 (runtime, message, context)；流程不存在返回 (None, None, None)。
    """
    from app.models.pipeline import Pipeline
    from app.services.multi_agent import ensure_agent_runtime, build_debug_context, build_debug_message
    from app.services import experience as _exp

    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.is_active == True)
    )
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        return None, None, None

    if user_id:
        from app.services.llm import init_user_llm_context
        await init_user_llm_context(user_id)
    from app.services.llm import llm_manager
    await llm_manager.initialize()

    runtime = ensure_agent_runtime()

    _pipe_exp_dir = _exp.pipeline_experience_dir(pipeline_id)
    _pipe_lessons = _exp.read_lessons(_pipe_exp_dir) or ""
    entry_function = pipeline.entry_function or "main"

    context = build_debug_context(
        db=db,
        user_id=user_id,
        target_type="pipeline",
        history=history,
        script_name=entry_function,
        script_content=pipeline.main_code or "",
        function_name=entry_function,
        lessons=_pipe_lessons,
        user_context=user_context,
        last_success_params=last_success_params,
        debug_pipeline_id=pipeline_id,
        debug_folder=_pipe_exp_dir,
    )

    message = build_debug_message(user_message, context)
    return runtime, message, context


async def _run_pipeline_auto_fix(
    db, pipeline_id: UUID, params: Dict[str, Any], user_id: Optional[UUID],
    execution_id: UUID = None, timeout: int = 600,
) -> Tuple[bool, Optional[Dict], Optional[str], Optional[str]]:
    """自修复模式执行流程：走 DataProcessor + DataInspector AgentRuntime。

    与调试页面 debug-chat 相同的流程（共享 prepare_pipeline_debug_runtime），
    区别在于：增量写入日志（前端可看进度）+ 超时保护 + 收集结果而非流式推送。
    """
    runtime, message, context = await prepare_pipeline_debug_runtime(
        db, pipeline_id, user_id
    )
    if not runtime:
        return False, None, "流程不存在", None

    logs_lines = []
    _content_buf = []  # 累加 content token，避免一字一行
    final_success = False
    final_content = ""
    _start = time.time()
    _deadline = _start + timeout
    _event_count = 0

    async def _flush_logs():
        """增量写入日志，让前端详情能看到执行进度。"""
        if not execution_id:
            return
        try:
            async with async_session() as _db2:
                _r = await _db2.execute(
                    select(TaskExecution).where(TaskExecution.id == execution_id)
                )
                _ex = _r.scalar_one_or_none()
                if _ex:
                    all_lines = list(logs_lines)
                    if _content_buf:
                        all_lines.append("".join(_content_buf))
                    _ex.logs = "\n".join(all_lines)
                    await _db2.commit()
        except Exception:
            pass

    def _flush_content():
        """把累加的 content token 作为一个整行写入 logs_lines。"""
        if _content_buf:
            logs_lines.append("".join(_content_buf))
            _content_buf.clear()

    try:
        async for event in runtime.run("data_processor", message, context):
            if time.time() > _deadline:
                _flush_content()
                logs_lines.append(f"[超时] 自修复执行超过 {timeout}s，终止")
                break
            t = event.get("type")
            if t == "content":
                _content_buf.append(event.get("content", ""))
            else:
                _flush_content()
            if t == "round":
                _round = event.get("round", 1)
                _label = "执行尝试" if _round == 1 else "修改尝试"
                logs_lines.append(f"─── 第 {_round} 次{_label} ───")
            elif t == "run_result":
                r = event.get("result", {})
                if r.get("success"):
                    logs_lines.append("✅ 脚本执行成功")
                    final_success = True
                else:
                    logs_lines.append(f"❌ 脚本执行失败: {(r.get('error') or '')[:200]}")
            elif t == "done":
                r = event.get("result", {})
                final_content = r.get("content", "")
                if r.get("success"):
                    final_success = True
            elif t == "give_up":
                logs_lines.append(f"[放弃] {event.get('reason', '')}")
            elif t == "fatal":
                logs_lines.append(f"[致命错误] {event.get('summary', '')}")
            # 每 5 条事件增量写入一次日志（含 content 累加内容）
            _event_count += 1
            if _event_count % 5 == 0:
                await _flush_logs()
    except Exception as e:
        _flush_content()
        logger.error(f"auto_fix 执行异常 [{pipeline_id}]: {e}")
        await _flush_logs()
        return False, None, f"自修复执行异常: {e}", "\n".join(logs_lines)

    _flush_content()
    await _flush_logs()

    logs = "\n".join(logs_lines) or final_content or "自修复执行完成"
    if final_success:
        return True, {"mode": "auto_fix", "summary": final_content[:500]}, None, logs
    else:
        return False, {"mode": "auto_fix", "summary": final_content[:500]}, final_content[:500] or "自修复未能成功", logs


# ===== 定时调度扫描器 =====

_scheduler_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None
_running_tasks: set = set()  # 持有后台执行任务引用，防止 GC 回收（asyncio 文档要求）
SCAN_INTERVAL = 30  # 扫描间隔（秒）


async def start_scheduler(scan_interval: int = SCAN_INTERVAL):
    """启动定时调度扫描器（由 main.py lifespan 调用）"""
    global _scheduler_task, _stop_event
    _stop_event = asyncio.Event()
    await _recover_stuck_executions()
    await _recover_orphaned_executions(threshold_seconds=0)
    await _recompute_stale_next_runs()
    _scheduler_task = asyncio.create_task(_scheduler_loop(scan_interval))
    logger.info(f"定时调度扫描器已启动，扫描间隔 {scan_interval}s")


async def _recover_stuck_executions():
    """启动时将残留的 running 执行标记为失败。

    进程重启会导致 asyncio.create_task 的后台任务丢失。running 执行 definite
    已死，标记 failed；pending 执行留给 _recover_orphaned_executions 回收重试。
    """
    async with async_session() as db:
        result = await db.execute(
            select(TaskExecution).where(
                TaskExecution.status == "running"
            )
        )
        stuck = result.scalars().all()
        for ex in stuck:
            ex.status = "failed"
            ex.error_message = "服务重启，任务中断"
            ex.finished_at = datetime.utcnow()
        if stuck:
            await db.commit()
            logger.warning(f"启动时恢复 {len(stuck)} 个中断的执行记录（标记为失败）")


async def _recover_orphaned_executions(threshold_seconds: int = 60):
    """回收被重启/崩溃遗留的 pending 执行（无 started_at 且创建超过阈值秒数）。

    dev 模式 ``--reload`` 或进程崩溃会杀死 BackgroundTask / asyncio.create_task，
    导致手动触发的执行永远卡在 pending。调度器每轮扫描时回收这些孤儿执行。
    启动时 threshold_seconds=0 立即回收；扫描循环用 60s 与 BackgroundTask 共存。
    """
    threshold = datetime.utcnow() - timedelta(seconds=threshold_seconds)
    async with async_session() as db:
        result = await db.execute(
            select(TaskExecution).where(
                TaskExecution.status == "pending",
                TaskExecution.started_at == None,
                TaskExecution.created_at <= threshold,
            )
        )
        orphans = result.scalars().all()
        if not orphans:
            return

        sched_ids = {ex.schedule_id for ex in orphans if ex.schedule_id}
        scheds: dict = {}
        if sched_ids:
            sched_result = await db.execute(
                select(Schedule).where(Schedule.id.in_(sched_ids))
            )
            for s in sched_result.scalars().all():
                scheds[s.id] = s

        to_run = []
        for ex in orphans:
            sched = scheds.get(ex.schedule_id)
            to_run.append((
                ex.id,
                ex.task_type,
                ex.task_target_id,
                sched.task_params if sched else None,
                (sched.created_by if sched else None) or ex.triggered_by,
                (sched.timeout or 3600) if sched else 3600,
                (sched.run_mode or "normal") if sched else "normal",
            ))

    for exec_id, ttype, target, params, uid, timeout, run_mode in to_run:
        task = asyncio.create_task(
            execute_task(
                execution_id=exec_id,
                task_type=ttype,
                task_target_id=target,
                task_params=params,
                user_id=uid,
                timeout=timeout,
                run_mode=run_mode,
            )
        )
        _running_tasks.add(task)
        task.add_done_callback(_running_tasks.discard)
        logger.info(f"回收孤儿执行: {exec_id}")


async def _recompute_stale_next_runs():
    """启动时用时区感知逻辑重算所有 active cron 调度的 next_run_at。

    修正历史版本用 datetime.utcnow() 误算 cron 下次执行时间导致的偏移
    （用户按本地时间设的 9:42 被当 UTC，实际延迟 8 小时才触发）。
    """
    async with async_session() as db:
        result = await db.execute(
            select(Schedule).where(
                Schedule.status == "active",
                Schedule.schedule_type == "cron",
                Schedule.cron_expression != None,
            )
        )
        schedules = result.scalars().all()
        fixed = 0
        for sched in schedules:
            try:
                sched.next_run_at = compute_next_cron_run(
                    sched.cron_expression, sched.timezone or "UTC"
                )
                fixed += 1
            except Exception as e:
                logger.warning(f"重算调度 {sched.name} next_run_at 失败: {e}")
        if fixed:
            await db.commit()
            logger.info(f"启动时重算 {fixed} 个调度的下次执行时间（时区感知）")


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
    _perm_escalation_counter = 0
    while _stop_event and not _stop_event.is_set():
        try:
            await _scan_and_trigger()
            await _recover_orphaned_executions()
            _perm_escalation_counter += 1
            if _perm_escalation_counter >= 6:
                _perm_escalation_counter = 0
                await _escalate_stale_permission_requests()
        except Exception as e:
            logger.error(f"调度扫描异常: {e}")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=scan_interval)
        except asyncio.TimeoutError:
            pass


async def _escalate_stale_permission_requests():
    """超时权限申请升级：pending 且 created_at < now()-3天 → escalated=True"""
    try:
        from app.models.user import PermissionRequest
        from datetime import timedelta
        now = datetime.utcnow()
        cutoff = now - timedelta(days=3)
        async with async_session() as db:
            result = await db.execute(
                select(PermissionRequest).where(
                    PermissionRequest.status == "pending",
                    PermissionRequest.escalated == False,
                    PermissionRequest.created_at < cutoff,
                )
            )
            stale = result.scalars().all()
            for pr in stale:
                pr.escalated = True
                pr.escalated_at = now
                logger.info(f"权限申请超时升级: {pr.id} ({pr.resource_type}/{pr.resource_id})")
            if stale:
                await db.commit()
    except Exception as e:
        logger.warning(f"权限申请超时升级失败: {e}")


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

        if not await _commit_with_retry(db):
            # commit 失败（database is locked），放弃本次触发
            # next_run_at 未更新，下一轮扫描（30s 后）会重新尝试
            logger.error(f"调度 {schedule_name} 创建执行记录 commit 失败，放弃本次触发（下一轮扫描会重试）")
            return
        await db.refresh(execution)

        # 捕获执行所需参数（session 关闭后 detached）
        task_type = sched.task_type
        task_target_id = sched.task_target_id
        task_params = sched.task_params
        user_id = sched.created_by
        timeout = sched.timeout or 3600
        run_mode = sched.run_mode or "normal"
        execution_id = execution.id

    # 后台执行（独立 db session）—— 必须持有引用，否则 task 会被 GC 回收导致永不执行
    task = asyncio.create_task(
        execute_task(
            execution_id=execution_id,
            task_type=task_type,
            task_target_id=task_target_id,
            task_params=task_params,
            user_id=user_id,
            timeout=timeout,
            run_mode=run_mode,
        )
    )
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    logger.info(f"定时触发: {schedule_name} -> execution {execution_id}")
