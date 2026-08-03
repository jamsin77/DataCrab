"""调度管理API端点"""

from uuid import UUID
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from croniter import croniter
from zoneinfo import ZoneInfo

from app.core.database import get_db
from app.models.schedule import Schedule, TaskExecution
from app.models.user import User
from app.models.operator import Operator
from app.models.skill import Skill
from app.schemas.schedule import (
    ScheduleCreate,
    ScheduleUpdate,
    ScheduleResponse,
    TaskExecutionCreate,
    TaskExecutionResponse,
    ManualTriggerRequest,
    CronValidateRequest,
    CronValidateResponse,
)
from app.api.deps import get_current_user
from app.services.task_runner import execute_task, compute_next_cron_run

router = APIRouter()


def _validate_cron_and_next_run(cron_expression: str, tz_name: str = "UTC") -> datetime:
    """验证 cron 表达式（支持 ; 分隔多个）并返回最近的下次执行时间（UTC，按指定时区解释）"""
    return compute_next_cron_run(cron_expression, tz_name)


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    request: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建调度"""
    # 验证任务目标是否存在
    if request.task_type == "operator":
        result = await db.execute(select(Operator).where(Operator.id == request.task_target_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="算子不存在")
    elif request.task_type == "skill":
        result = await db.execute(select(Skill).where(Skill.id == request.task_target_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="技能不存在")
    
    # 验证Cron表达式
    if request.schedule_type == "cron":
        if not request.cron_expression:
            raise HTTPException(status_code=400, detail="Cron调度需要提供cron_expression")
        try:
            next_run_at = _validate_cron_and_next_run(request.cron_expression, request.timezone)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif request.schedule_type == "interval":
        next_run_at = datetime.utcnow() + timedelta(seconds=request.interval_seconds or 3600)
    else:
        next_run_at = None
    
    schedule = Schedule(
        name=request.name,
        description=request.description,
        task_type=request.task_type,
        task_target_id=request.task_target_id,
        task_params=request.task_params,
        schedule_type=request.schedule_type,
        cron_expression=request.cron_expression,
        timezone=request.timezone,
        interval_seconds=request.interval_seconds,
        event_config=request.event_config,
        max_retries=request.max_retries,
        retry_interval=request.retry_interval,
        timeout=request.timeout,
        concurrent_runs=request.concurrent_runs,
        run_mode=request.run_mode,
        next_run_at=next_run_at,
        created_by=current_user.id,
    )
    db.add(schedule)
    await db.flush()
    await db.refresh(schedule)
    return schedule


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    status_filter: Optional[str] = Query(None, alias="status"),
    task_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取调度列表"""
    query = select(Schedule)
    if status_filter:
        query = query.where(Schedule.status == status_filter)
    if task_type:
        query = query.where(Schedule.task_type == task_type)
    query = query.order_by(Schedule.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取调度详情"""
    result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="调度不存在")
    return schedule


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: UUID,
    request: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新调度"""
    result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="调度不存在")

    update_data = request.model_dump(exclude_unset=True)

    # 内置调度保护：锁定 name/schedule_type/task_type/task_target_id，cron 最低每天一次
    if getattr(schedule, "is_builtin", False):
        for locked in ("name", "schedule_type", "task_type", "task_target_id"):
            update_data.pop(locked, None)
        if "cron_expression" in update_data:
            _expr = update_data["cron_expression"].strip()
            _parts = _expr.split()
            if len(_parts) == 5:
                _min, _hour, _dom, _mon, _dow = _parts
                _freq = (_min != "0" or _hour != "0" or _dom != "*" or _mon != "*" or _dow != "*")
                if _freq:
                    raise HTTPException(status_code=400, detail="内置调度不支持高于每天的频率，请使用每天或更低频率（如每周、每月）")
    
    # 如果更新了Cron表达式，重新计算下次执行时间
    if "cron_expression" in update_data and schedule.schedule_type == "cron":
        try:
            schedule.next_run_at = _validate_cron_and_next_run(
                update_data["cron_expression"],
                update_data.get("timezone") or schedule.timezone or "UTC",
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    for key, value in update_data.items():
        setattr(schedule, key, value)

    schedule.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除调度"""
    result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="调度不存在")
    if getattr(schedule, "is_builtin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="内置调度不可删除")
    await db.delete(schedule)


@router.post("/{schedule_id}/pause", response_model=ScheduleResponse)
async def pause_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """暂停调度"""
    result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="调度不存在")
    schedule.status = "paused"
    await db.flush()
    await db.refresh(schedule)
    return schedule


@router.post("/{schedule_id}/resume", response_model=ScheduleResponse)
async def resume_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复调度"""
    result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="调度不存在")
    schedule.status = "active"
    
    # 重新计算下次执行时间
    if schedule.schedule_type == "cron" and schedule.cron_expression:
        try:
            schedule.next_run_at = _validate_cron_and_next_run(schedule.cron_expression, schedule.timezone or "UTC")
        except ValueError:
            pass
    elif schedule.schedule_type == "interval" and schedule.interval_seconds:
        schedule.next_run_at = datetime.utcnow() + timedelta(seconds=schedule.interval_seconds)
    
    await db.flush()
    await db.refresh(schedule)
    return schedule


@router.post("/{schedule_id}/trigger", response_model=TaskExecutionResponse)
async def trigger_schedule(
    schedule_id: UUID,
    request: ManualTriggerRequest = ManualTriggerRequest(),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动触发调度"""
    result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="调度不存在")
    
    # 创建执行记录
    execution = TaskExecution(
        schedule_id=schedule_id,
        task_type=schedule.task_type,
        task_target_id=schedule.task_target_id,
        status="pending",
        trigger_type="manual",
        triggered_by=current_user.id,
    )
    db.add(execution)
    await db.flush()
    await db.refresh(execution)
    # 显式提交：BackgroundTasks 在 get_db 依赖 commit 之前运行，
    # 不提交则 execute_task 的独立 session 查不到执行记录，永远卡 pending
    await db.commit()

    background_tasks.add_task(
        execute_task,
        execution_id=execution.id,
        task_type=schedule.task_type,
        task_target_id=schedule.task_target_id,
        task_params=request.task_params or schedule.task_params,
        user_id=current_user.id,
        timeout=schedule.timeout or 3600,
        run_mode=schedule.run_mode or "normal",
    )
    
    return execution


@router.get("/{schedule_id}/executions", response_model=list[TaskExecutionResponse])
async def list_executions(
    schedule_id: UUID,
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取执行历史"""
    query = select(TaskExecution).where(TaskExecution.schedule_id == schedule_id)
    if status_filter:
        query = query.where(TaskExecution.status == status_filter)
    query = query.order_by(TaskExecution.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/executions/{execution_id}", response_model=TaskExecutionResponse)
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取执行详情"""
    result = await db.execute(select(TaskExecution).where(TaskExecution.id == execution_id))
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="执行记录不存在")
    return execution


@router.post("/validate-cron", response_model=CronValidateResponse)
async def validate_cron(
    request: CronValidateRequest,
    current_user: User = Depends(get_current_user),
):
    """验证Cron表达式（支持 ; 分隔多个），返回指定时区后续 5 次本地执行时间"""
    try:
        tz_name = request.timezone or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            return CronValidateResponse(valid=False, message=f"无效的时区: {tz_name}")
        exprs = [e.strip() for e in request.cron_expression.split(";") if e.strip()]
        if not exprs:
            return CronValidateResponse(valid=False, message="Cron表达式为空")
        now_local = datetime.now(tz).replace(tzinfo=None)
        for expr in exprs:
            croniter(expr, now_local)
        cron = croniter(exprs[0], now_local)
        next_runs = [cron.get_next(datetime) for _ in range(5)]
        return CronValidateResponse(valid=True, next_runs=next_runs)
    except Exception as e:
        return CronValidateResponse(valid=False, message=str(e))


@router.get("/stats/overview")
async def get_schedule_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取调度统计概览"""
    total_result = await db.execute(select(func.count(Schedule.id)))
    total = total_result.scalar() or 0
    
    active_result = await db.execute(select(func.count(Schedule.id)).where(Schedule.status == "active"))
    active = active_result.scalar() or 0
    
    paused_result = await db.execute(select(func.count(Schedule.id)).where(Schedule.status == "paused"))
    paused = paused_result.scalar() or 0
    
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_result = await db.execute(
        select(func.count(TaskExecution.id)).where(TaskExecution.created_at >= today)
    )
    today_executions = today_result.scalar() or 0
    
    success_result = await db.execute(
        select(func.count(TaskExecution.id)).where(
            and_(TaskExecution.created_at >= today, TaskExecution.status == "success")
        )
    )
    success = success_result.scalar() or 0
    
    failed_result = await db.execute(
        select(func.count(TaskExecution.id)).where(
            and_(TaskExecution.created_at >= today, TaskExecution.status == "failed")
        )
    )
    failed = failed_result.scalar() or 0
    
    return {
        "total_schedules": total,
        "active": active,
        "paused": paused,
        "today_executions": today_executions,
        "success": success,
        "failed": failed,
    }
