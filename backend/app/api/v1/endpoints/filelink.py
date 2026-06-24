"""文件链接API端点"""

import os
from uuid import UUID
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.filelink import FileLink
from app.models.user import User
from app.schemas.filelink import (
    FileLinkCreate,
    FileLinkUpdate,
    FileLinkResponse,
    FileInfo,
    DirectoryListing,
    FileWriteRequest,
)
from app.api.deps import get_current_user

router = APIRouter()


def get_file_info(path: Path) -> FileInfo:
    """获取文件信息"""
    stat = path.stat()
    return FileInfo(
        name=path.name,
        path=str(path),
        is_file=path.is_file(),
        is_dir=path.is_dir(),
        size=stat.st_size if path.is_file() else None,
        modified_time=datetime.fromtimestamp(stat.st_mtime),
        extension=path.suffix if path.is_file() else None,
    )


from datetime import datetime


@router.post("", response_model=FileLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_file_link(
    request: FileLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建文件链接"""
    # 验证路径是否存在
    path = Path(request.path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"路径不存在: {request.path}"
        )
    
    # 自动检测类型
    link_type = "directory" if path.is_dir() else "file"
    
    # 收集元数据
    file_metadata = {}
    try:
        stat = path.stat()
        file_metadata["size"] = stat.st_size
        file_metadata["modified_time"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        file_metadata["exists"] = True
    except Exception as e:
        file_metadata["exists"] = False
        file_metadata["error"] = str(e)
    
    file_link = FileLink(
        name=request.name,
        path=request.path,
        description=request.description,
        link_type=link_type,
        is_public=request.is_public,
        allowed_extensions=request.allowed_extensions,
        file_metadata=file_metadata,
        created_by=current_user.id,
    )
    db.add(file_link)
    await db.flush()
    await db.refresh(file_link)
    return file_link


@router.get("", response_model=list[FileLinkResponse])
async def list_file_links(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取文件链接列表"""
    query = select(FileLink).where(FileLink.is_active == True)
    # 非超级用户只能看到自己创建的或公开的链接
    if not current_user.is_superuser:
        query = query.where(
            (FileLink.created_by == current_user.id) | (FileLink.is_public == True)
        )
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{link_id}", response_model=FileLinkResponse)
async def get_file_link(
    link_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取文件链接详情"""
    result = await db.execute(select(FileLink).where(FileLink.id == link_id))
    file_link = result.scalar_one_or_none()
    if not file_link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件链接不存在")
    
    # 权限检查
    if not file_link.is_public and file_link.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问此文件链接")
    
    return file_link


@router.put("/{link_id}", response_model=FileLinkResponse)
async def update_file_link(
    link_id: UUID,
    request: FileLinkUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新文件链接"""
    result = await db.execute(select(FileLink).where(FileLink.id == link_id))
    file_link = result.scalar_one_or_none()
    if not file_link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件链接不存在")
    
    # 权限检查
    if file_link.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改此文件链接")
    
    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(file_link, key, value)
    
    await db.flush()
    await db.refresh(file_link)
    return file_link


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_link(
    link_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除文件链接"""
    result = await db.execute(select(FileLink).where(FileLink.id == link_id))
    file_link = result.scalar_one_or_none()
    if not file_link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件链接不存在")
    
    # 权限检查
    if file_link.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除此文件链接")
    
    await db.delete(file_link)


@router.get("/{link_id}/browse", response_model=DirectoryListing)
async def browse_directory(
    link_id: UUID,
    subpath: str = Query("", description="子路径，相对于链接路径"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """浏览目录内容"""
    result = await db.execute(select(FileLink).where(FileLink.id == link_id))
    file_link = result.scalar_one_or_none()
    if not file_link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件链接不存在")
    
    # 权限检查
    if not file_link.is_public and file_link.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问此文件链接")
    
    # 构建完整路径
    base_path = Path(file_link.path)
    if subpath:
        full_path = (base_path / subpath).resolve()
        base_resolved = str(base_path.resolve())
        if not (str(full_path) == base_resolved or str(full_path).startswith(base_resolved + os.sep)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非法路径")
    else:
        full_path = base_path
    
    if not full_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="路径不存在")
    
    if full_path.is_file():
        # 如果是文件，返回文件信息
        return DirectoryListing(
            path=str(full_path),
            files=[get_file_info(full_path)],
            total=1,
        )
    
    # 列出目录内容
    files = []
    for item in full_path.iterdir():
        try:
            files.append(get_file_info(item))
        except Exception:
            pass  # 跳过无法访问的文件
    
    return DirectoryListing(
        path=str(full_path),
        files=sorted(files, key=lambda x: (not x.is_dir, x.name)),
        total=len(files),
    )


@router.get("/{link_id}/download")
async def download_file(
    link_id: UUID,
    subpath: str = Query("", description="文件子路径"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载文件"""
    result = await db.execute(select(FileLink).where(FileLink.id == link_id))
    file_link = result.scalar_one_or_none()
    if not file_link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件链接不存在")
    
    # 权限检查
    if not file_link.is_public and file_link.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问此文件链接")
    
    # 构建完整路径
    base_path = Path(file_link.path)
    if subpath:
        full_path = (base_path / subpath).resolve()
        base_resolved = str(base_path.resolve())
        if not (str(full_path) == base_resolved or str(full_path).startswith(base_resolved + os.sep)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非法路径")
    else:
        full_path = base_path
    
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    
    # 检查扩展名限制
    if file_link.allowed_extensions:
        ext = full_path.suffix.lower()
        if ext not in [e.lower() for e in file_link.allowed_extensions]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不允许下载此类型的文件")
    
    return FileResponse(
        path=str(full_path),
        filename=full_path.name,
    )


@router.post("/{link_id}/write")
async def write_file(
    link_id: UUID,
    request: FileWriteRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在文件链接目录中写入文件"""
    result = await db.execute(select(FileLink).where(FileLink.id == link_id))
    file_link = result.scalar_one_or_none()
    if not file_link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件链接不存在")

    if not file_link.is_public and file_link.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问此文件链接")

    if file_link.link_type != "directory":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能向目录类型的文件链接写入文件")

    base_path = Path(file_link.path).resolve()
    full_path = (base_path / request.subpath).resolve()

    if not str(full_path).startswith(str(base_path)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非法路径")

    full_path.parent.mkdir(parents=True, exist_ok=True)

    with open(full_path, "w", encoding=request.encoding) as f:
        f.write(request.content)

    file_size = full_path.stat().st_size
    return {
        "status": "success",
        "path": str(full_path),
        "size": file_size,
        "message": f"文件已保存: {request.subpath} ({file_size} 字节)",
    }


@router.get("/{link_id}/preview")
async def preview_file(
    link_id: UUID,
    subpath: str = Query("", description="文件子路径"),
    max_size: int = Query(10240, description="最大预览字节数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """预览文件内容（文本文件）"""
    result = await db.execute(select(FileLink).where(FileLink.id == link_id))
    file_link = result.scalar_one_or_none()
    if not file_link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件链接不存在")
    
    # 权限检查
    if not file_link.is_public and file_link.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问此文件链接")
    
    # 构建完整路径
    base_path = Path(file_link.path)
    if subpath:
        full_path = (base_path / subpath).resolve()
        if not str(full_path).startswith(str(base_path.resolve())):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非法路径")
    else:
        full_path = base_path
    
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    
    # 检查文件大小
    size = full_path.stat().st_size
    if size > max_size * 10:  # 允许10倍于预览大小的文件
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件太大，无法预览")
    
    # 尝试读取文本内容
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read(max_size)
        return {
            "path": str(full_path),
            "name": full_path.name,
            "size": size,
            "content": content,
            "truncated": size > max_size,
        }
    except UnicodeDecodeError:
        # 非文本文件
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非文本文件，无法预览")
