"""权限管理API端点"""

import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services import permission_service as ps

router = APIRouter()


class GrantPermissionRequest(BaseModel):
    resource_type: str = Field(..., description="资源类型: datasource/operator/skill/metadata等")
    resource_id: str = Field(..., description="资源UUID")
    user_id: Optional[str] = Field(None, description="被授权用户ID")
    role_id: Optional[str] = Field(None, description="被授权角色ID")
    permission_level: str = Field("view", description="权限级别: view/use/manage")


class RevokePermissionRequest(BaseModel):
    resource_type: str
    resource_id: str
    user_id: Optional[str] = None
    role_id: Optional[str] = None
    permission_level: Optional[str] = None


class CopyPermissionRequest(BaseModel):
    source_user_id: str = Field(..., description="源用户ID")
    target_user_id: Optional[str] = Field(None, description="目标用户ID")
    target_role_id: Optional[str] = Field(None, description="目标角色ID")


class CreateRoleRequest(BaseModel):
    name: str = Field(..., max_length=50)
    display_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class AssignRoleRequest(BaseModel):
    user_id: str


@router.post("/grant")
async def grant_permission(
    req: GrantPermissionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """授权资源访问权限"""
    try:
        perm = await ps.grant_permission(
            db,
            resource_type=req.resource_type,
            resource_id=uuid.UUID(req.resource_id),
            granted_by=current_user.id,
            user_id=uuid.UUID(req.user_id) if req.user_id else None,
            role_id=uuid.UUID(req.role_id) if req.role_id else None,
            permission_level=req.permission_level,
        )
        await db.commit()
        return {"success": True, "id": str(perm.id), "message": "授权成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"授权失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/revoke")
async def revoke_permission(
    req: RevokePermissionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤销资源访问权限"""
    try:
        await ps.revoke_permission(
            db,
            resource_type=req.resource_type,
            resource_id=uuid.UUID(req.resource_id),
            user_id=uuid.UUID(req.user_id) if req.user_id else None,
            role_id=uuid.UUID(req.role_id) if req.role_id else None,
            permission_level=req.permission_level,
        )
        await db.commit()
        return {"success": True, "message": "已撤销权限"}
    except Exception as e:
        logger.error(f"撤销权限失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resource/{resource_type}/{resource_id}")
async def list_resource_permissions(
    resource_type: str,
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出某资源的所有授权"""
    perms = await ps.list_resource_permissions(db, resource_type, uuid.UUID(resource_id))
    return perms


@router.get("/my-permissions")
async def list_my_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户的所有被授予权限"""
    return await ps.list_user_permissions(db, current_user.id)


@router.get("/user/{user_id}")
async def list_user_permissions(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出指定用户的所有权限（需要超管权限）"""
    if not current_user.is_superuser and str(current_user.id) != user_id:
        raise HTTPException(status_code=403, detail="无权查看其他用户的权限")
    return await ps.list_user_permissions(db, uuid.UUID(user_id))


@router.post("/copy")
async def copy_permissions(
    req: CopyPermissionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """复制用户权限给另一个用户或角色"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有管理员可以复制权限")

    if not req.target_user_id and not req.target_role_id:
        raise HTTPException(status_code=400, detail="必须指定目标用户或角色")

    try:
        count = await ps.copy_permissions(
            db,
            source_user_id=uuid.UUID(req.source_user_id),
            target_user_id=uuid.UUID(req.target_user_id) if req.target_user_id else None,
            target_role_id=uuid.UUID(req.target_role_id) if req.target_role_id else None,
            granted_by=current_user.id,
        )
        await db.commit()
        return {"success": True, "copied_count": count, "message": f"已复制{count}条权限"}
    except Exception as e:
        logger.error(f"复制权限失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check/{resource_type}/{resource_id}")
async def check_permission(
    resource_type: str,
    resource_id: str,
    level: str = "view",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检查当前用户对某资源的权限"""
    has_perm = await ps.check_permission(
        db,
        user_id=current_user.id,
        resource_type=resource_type,
        resource_id=uuid.UUID(resource_id),
        required_level=level,
        is_superuser=current_user.is_superuser,
    )
    return {"has_permission": has_perm, "level": level}


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有用户（用于授权选择）"""
    return await ps.get_all_users(db)


@router.get("/roles")
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有角色"""
    return await ps.get_all_roles(db)


@router.post("/roles")
async def create_role(
    req: CreateRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建角色"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有管理员可以创建角色")
    try:
        role = await ps.create_role(db, name=req.name, display_name=req.display_name, description=req.description)
        await db.commit()
        return {
            "id": str(role.id),
            "name": role.name,
            "display_name": role.display_name,
            "description": role.description,
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"创建角色失败: {str(e)}")


@router.get("/roles/{role_id}/members")
async def get_role_members(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取角色成员列表"""
    return await ps.get_role_members(db, uuid.UUID(role_id))


@router.post("/roles/{role_id}/members")
async def assign_role_member(
    role_id: str,
    req: AssignRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """给角色添加成员"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有管理员可以分配角色")
    try:
        await ps.assign_role_to_user(db, uuid.UUID(role_id), uuid.UUID(req.user_id))
        await db.commit()
        return {"success": True, "message": "已添加成员"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/roles/{role_id}/members/{user_id}")
async def remove_role_member(
    role_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从角色移除成员"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有管理员可以移除角色成员")
    await ps.remove_role_from_user(db, uuid.UUID(role_id), uuid.UUID(user_id))
    await db.commit()
    return {"success": True, "message": "已移除成员"}
