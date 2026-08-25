"""权限管理API端点"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from loguru import logger

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, PermissionRequest
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


# ===== 权限申请流程 =====

class PermissionRequestCreate(BaseModel):
    resource_type: str = Field(..., description="资源类型")
    resource_id: str = Field(..., description="资源UUID")
    requested_level: str = Field("use", description="申请的权限级别")
    reason: Optional[str] = Field(None, description="申请理由")


class PermissionRequestResponse(BaseModel):
    id: str
    resource_type: str
    resource_id: str
    requester_id: str
    requested_level: str
    reason: Optional[str] = None
    status: str
    reviewer_id: Optional[str] = None
    review_note: Optional[str] = None
    escalated: bool = False
    created_at: Optional[str] = None
    reviewed_at: Optional[str] = None


async def _get_resource_owner_id(db: AsyncSession, resource_type: str, resource_id: uuid.UUID) -> Optional[uuid.UUID]:
    """查询资源的 created_by"""
    if resource_type == "skill":
        from app.models.skill import Skill
        r = await db.execute(select(Skill).where(Skill.id == resource_id))
        s = r.scalar_one_or_none()
        return s.created_by if s else None
    elif resource_type == "pipeline":
        from app.models.pipeline import Pipeline
        r = await db.execute(select(Pipeline).where(Pipeline.id == resource_id))
        p = r.scalar_one_or_none()
        return p.created_by if p else None
    elif resource_type == "operator":
        from app.models.operator import Operator
        r = await db.execute(select(Operator).where(Operator.id == resource_id))
        o = r.scalar_one_or_none()
        return o.created_by if o else None
    elif resource_type == "datasource":
        from app.models.datasource import DataSource
        r = await db.execute(select(DataSource).where(DataSource.id == resource_id))
        d = r.scalar_one_or_none()
        return d.created_by if d else None
    return None


@router.post("/request", response_model=PermissionRequestResponse)
async def create_permission_request(
    req: PermissionRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交权限申请"""
    existing = await db.execute(
        select(PermissionRequest).where(
            and_(
                PermissionRequest.resource_type == req.resource_type,
                PermissionRequest.resource_id == uuid.UUID(req.resource_id),
                PermissionRequest.requester_id == current_user.id,
                PermissionRequest.status == "pending",
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="已有一份待审批的申请，请等待资源所有者处理")

    has_perm = await ps.check_permission(
        db, current_user.id, req.resource_type, uuid.UUID(req.resource_id), req.requested_level,
        is_superuser=current_user.is_superuser,
    )
    if has_perm:
        raise HTTPException(status_code=400, detail="您已拥有该权限，无需申请")

    pr = PermissionRequest(
        resource_type=req.resource_type,
        resource_id=uuid.UUID(req.resource_id),
        requester_id=current_user.id,
        requested_level=req.requested_level,
        reason=req.reason,
        status="pending",
    )
    db.add(pr)
    await db.flush()
    await db.refresh(pr)
    await db.commit()
    return PermissionRequestResponse(
        id=str(pr.id), resource_type=pr.resource_type, resource_id=str(pr.resource_id),
        requester_id=str(pr.requester_id), requested_level=pr.requested_level,
        reason=pr.reason, status=pr.status, escalated=pr.escalated,
        created_at=pr.created_at.isoformat() if pr.created_at else None,
    )


@router.get("/requests/my", response_model=List[PermissionRequestResponse])
async def list_my_requests(
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """我发起的权限申请"""
    q = select(PermissionRequest).where(PermissionRequest.requester_id == current_user.id)
    if status_filter:
        q = q.where(PermissionRequest.status == status_filter)
    q = q.order_by(PermissionRequest.created_at.desc())
    result = await db.execute(q)
    return [PermissionRequestResponse(
        id=str(pr.id), resource_type=pr.resource_type, resource_id=str(pr.resource_id),
        requester_id=str(pr.requester_id), requested_level=pr.requested_level,
        reason=pr.reason, status=pr.status,
        reviewer_id=str(pr.reviewer_id) if pr.reviewer_id else None,
        review_note=pr.review_note, escalated=pr.escalated,
        created_at=pr.created_at.isoformat() if pr.created_at else None,
        reviewed_at=pr.reviewed_at.isoformat() if pr.reviewed_at else None,
    ) for pr in result.scalars().all()]


@router.get("/requests/incoming", response_model=List[PermissionRequestResponse])
async def list_incoming_requests(
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """别人对我的资源的申请"""
    q = select(PermissionRequest).where(PermissionRequest.status == "pending")
    result = await db.execute(q)
    all_pending = result.scalars().all()
    mine = []
    for pr in all_pending:
        owner_id = await _get_resource_owner_id(db, pr.resource_type, pr.resource_id)
        if owner_id == current_user.id or current_user.is_superuser:
            if status_filter and pr.status != status_filter:
                continue
            mine.append(PermissionRequestResponse(
                id=str(pr.id), resource_type=pr.resource_type, resource_id=str(pr.resource_id),
                requester_id=str(pr.requester_id), requested_level=pr.requested_level,
                reason=pr.reason, status=pr.status,
                reviewer_id=str(pr.reviewer_id) if pr.reviewer_id else None,
                review_note=pr.review_note, escalated=pr.escalated,
                created_at=pr.created_at.isoformat() if pr.created_at else None,
                reviewed_at=pr.reviewed_at.isoformat() if pr.reviewed_at else None,
            ))
    return mine


@router.post("/requests/{request_id}/approve")
async def approve_request(
    request_id: str,
    review_note: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批准权限申请（资源所有者或超管）"""
    result = await db.execute(select(PermissionRequest).where(PermissionRequest.id == uuid.UUID(request_id)))
    pr = result.scalar_one_or_none()
    if not pr:
        raise HTTPException(status_code=404, detail="申请不存在")
    if pr.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理")

    owner_id = await _get_resource_owner_id(db, pr.resource_type, pr.resource_id)
    if owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有资源所有者或管理员可以审批")

    await ps.grant_permission(
        db, pr.resource_type, pr.resource_id, current_user.id,
        user_id=pr.requester_id, permission_level=pr.requested_level,
    )
    pr.status = "approved"
    pr.reviewer_id = current_user.id
    pr.review_note = review_note
    pr.reviewed_at = datetime.utcnow()
    await db.flush()
    await db.commit()
    return {"success": True, "message": "已批准权限申请"}


@router.post("/requests/{request_id}/reject")
async def reject_request(
    request_id: str,
    review_note: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """驳回权限申请（资源所有者或超管）"""
    result = await db.execute(select(PermissionRequest).where(PermissionRequest.id == uuid.UUID(request_id)))
    pr = result.scalar_one_or_none()
    if not pr:
        raise HTTPException(status_code=404, detail="申请不存在")
    if pr.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理")

    owner_id = await _get_resource_owner_id(db, pr.resource_type, pr.resource_id)
    if owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有资源所有者或管理员可以审批")

    pr.status = "rejected"
    pr.reviewer_id = current_user.id
    pr.review_note = review_note
    pr.reviewed_at = datetime.utcnow()
    await db.flush()
    await db.commit()
    return {"success": True, "message": "已驳回权限申请"}
