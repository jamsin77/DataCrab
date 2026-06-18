"""调度管理API端点"""

from uuid import UUID
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from croniter import croniter

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

router = APIRouter()


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
            croniter(request.cron_expression)
        except:
            raise HTTPException(status_code=400, detail="无效的Cron表达式")
    
    # 计算下次执行时间
    next_run_at = None
    if request.schedule_type == "cron":
        cron = croniter(request.cron_expression, datetime.utcnow())
        next_run_at = cron.get_next(datetime)
    elif request.schedule_type == "interval":
        next_run_at = datetime.utcnow() + timedelta(seconds=request.interval_seconds or 3600)
    
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
    
    # 如果更新了Cron表达式，重新计算下次执行时间
    if "cron_expression" in update_data and schedule.schedule_type == "cron":
        try:
            cron = croniter(update_data["cron_expression"], datetime.utcnow())
            schedule.next_run_at = cron.get_next(datetime)
        except:
            raise HTTPException(status_code=400, detail="无效的Cron表达式")
    
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
        cron = croniter(schedule.cron_expression, datetime.utcnow())
        schedule.next_run_at = cron.get_next(datetime)
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
    
    # TODO: 在后台执行任务
    # background_tasks.add_task(execute_task, execution.id, schedule, request.task_params)
    
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
    """验证Cron表达式"""
    try:
        cron = croniter(request.cron_expression, datetime.utcnow())
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
    # 总调度数
    total_result = await db.execute(select(Schedule))
    total = len(total_result.scalars().all())
    
    # 各状态数量
    active_result = await db.execute(select(Schedule).where(Schedule.status == "active"))
    active = len(active_result.scalars().all())
    
    paused_result = await db.execute(select(Schedule).where(Schedule.status == "paused"))
    paused = len(paused_result.scalars().all())
    
    # 今日执行数
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_result = await db.execute(
        select(TaskExecution).where(TaskExecution.created_at >= today)
    )
    today_executions = len(today_result.scalars().all())
    
    # 成功/失败数
    success_result = await db.execute(
        select(TaskExecution).where(
            and_(TaskExecution.created_at >= today, TaskExecution.status == "success")
        )
    )
    success = len(success_result.scalars().all())
    
    failed_result = await db.execute(
        select(TaskExecution).where(
            and_(TaskExecution.created_at >= today, TaskExecution.status == "failed")
        )
    )
    failed = len(failed_result.scalars().all())
    
    return {
        "total_schedules": total,
        "active": active,
        "paused": paused,
        "today_executions": today_executions,
        "success": success,
        "failed": failed,
    }
