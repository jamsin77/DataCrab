"""Notebook API端点"""

from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.notebook import Notebook, NotebookVersion
from app.models.user import User
from app.schemas.notebook import (
    NotebookCreate,
    NotebookUpdate,
    NotebookResponse,
    CellExecuteRequest,
    CellExecuteResponse,
    VariableInfo,
    NotebookVersionResponse,
)
from app.api.deps import get_current_user

router = APIRouter()


@router.post("", response_model=NotebookResponse, status_code=status.HTTP_201_CREATED)
async def create_notebook(
    request: NotebookCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建Notebook"""
    notebook = Notebook(
        user_id=current_user.id,
        name=request.name,
        kernel=request.kernel,
        cells=[],
    )
    db.add(notebook)
    await db.flush()
    await db.refresh(notebook)
    return notebook


@router.get("", response_model=list[NotebookResponse])
async def list_notebooks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取Notebook列表"""
    result = await db.execute(
        select(Notebook)
        .where(Notebook.user_id == current_user.id)
        .order_by(Notebook.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{notebook_id}", response_model=NotebookResponse)
async def get_notebook(
    notebook_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取Notebook详情"""
    result = await db.execute(
        select(Notebook).where(
            Notebook.id == notebook_id,
            Notebook.user_id == current_user.id,
        )
    )
    notebook = result.scalar_one_or_none()
    if not notebook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook不存在")
    return notebook


@router.put("/{notebook_id}", response_model=NotebookResponse)
async def update_notebook(
    notebook_id: UUID,
    request: NotebookUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存Notebook"""
    result = await db.execute(
        select(Notebook).where(
            Notebook.id == notebook_id,
            Notebook.user_id == current_user.id,
        )
    )
    notebook = result.scalar_one_or_none()
    if not notebook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook不存在")

    update_data = request.model_dump(exclude_unset=True)
    if "cells" in update_data:
        update_data["cells"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in update_data["cells"]]

    for key, value in update_data.items():
        setattr(notebook, key, value)

    # 创建版本记录
    version = NotebookVersion(
        notebook_id=notebook.id,
        version=notebook.version,
        cells=notebook.cells,
    )
    db.add(version)
    notebook.version += 1

    await db.flush()
    await db.refresh(notebook)
    return notebook


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notebook(
    notebook_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除Notebook"""
    result = await db.execute(
        select(Notebook).where(
            Notebook.id == notebook_id,
            Notebook.user_id == current_user.id,
        )
    )
    notebook = result.scalar_one_or_none()
    if not notebook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook不存在")
    await db.delete(notebook)


@router.post("/{notebook_id}/execute", response_model=CellExecuteResponse)
async def execute_cell(
    notebook_id: UUID,
    request: CellExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行单元格"""
    # TODO: 实际代码执行逻辑
    return CellExecuteResponse(
        cell_id=request.cell_id,
        output={"type": "text", "content": "执行结果示例"},
        execution_time=100,
    )


@router.post("/{notebook_id}/kernel/restart")
async def restart_kernel(
    notebook_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重启内核"""
    # TODO: 实际内核重启逻辑
    return {"message": "内核已重启"}


@router.get("/{notebook_id}/variables", response_model=list[VariableInfo])
async def get_variables(
    notebook_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取变量列表"""
    # TODO: 实际变量获取逻辑
    return []


@router.get("/{notebook_id}/versions", response_model=list[NotebookVersionResponse])
async def get_versions(
    notebook_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取版本历史"""
    result = await db.execute(
        select(NotebookVersion)
        .where(NotebookVersion.notebook_id == notebook_id)
        .order_by(NotebookVersion.version.desc())
    )
    return result.scalars().all()
