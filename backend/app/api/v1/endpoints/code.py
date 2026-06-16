"""组合流程管理API端点"""

from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.code import ComposedCode
from app.models.user import User
from app.schemas.code import (
    ComposedCodeCreate,
    ComposedCodeGenerateRequest,
    ComposedCodeResponse,
    CodeExecuteRequest,
    CodeExecuteResponse,
)
from app.api.deps import get_current_user

router = APIRouter()


@router.post("", response_model=ComposedCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_code(
    request: ComposedCodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建流程"""
    code = ComposedCode(
        name=request.name,
        nl_description=request.nl_description,
        steps=request.steps,
        tags=request.tags,
        category=request.category,
        visibility=request.visibility,
        created_by=current_user.id,
    )
    db.add(code)
    await db.flush()
    await db.refresh(code)
    return code


@router.post("/generate", response_model=ComposedCodeResponse)
async def generate_code(
    request: ComposedCodeGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从自然语言生成流程"""
    # TODO: 调用NL处理和代码生成服务
    code = ComposedCode(
        name="生成的流程",
        nl_description=request.nl_description,
        steps=[],
        created_by=current_user.id,
    )
    db.add(code)
    await db.flush()
    await db.refresh(code)
    return code


@router.get("", response_model=list[ComposedCodeResponse])
async def list_codes(
    category: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取流程列表"""
    query = select(ComposedCode)
    if category:
        query = query.where(ComposedCode.category == category)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{code_id}", response_model=ComposedCodeResponse)
async def get_code(
    code_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取流程详情"""
    result = await db.execute(select(ComposedCode).where(ComposedCode.id == code_id))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="流程不存在")
    return code


@router.put("/{code_id}", response_model=ComposedCodeResponse)
async def update_code(
    code_id: UUID,
    request: ComposedCodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新流程"""
    result = await db.execute(select(ComposedCode).where(ComposedCode.id == code_id))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="流程不存在")

    code.name = request.name
    code.nl_description = request.nl_description
    if request.steps:
        code.steps = request.steps
    code.version += 1

    await db.flush()
    await db.refresh(code)
    return code


@router.delete("/{code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_code(
    code_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除流程"""
    result = await db.execute(select(ComposedCode).where(ComposedCode.id == code_id))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="流程不存在")
    await db.delete(code)


@router.post("/{code_id}/execute", response_model=CodeExecuteResponse)
async def execute_code(
    code_id: UUID,
    request: CodeExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行流程"""
    result = await db.execute(select(ComposedCode).where(ComposedCode.id == code_id))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="流程不存在")

    # TODO: 实际流程执行逻辑
    code.execution_count += 1
    await db.flush()

    return CodeExecuteResponse(
        code_id=code.id,
        status="success",
        results={"message": "流程执行完成"},
    )
