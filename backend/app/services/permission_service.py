"""权限管理服务"""

import uuid
from datetime import datetime
from typing import Optional, List, Set
from sqlalchemy import select, or_, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.user import User, Role, Permission, user_roles


RESOURCE_TYPES = {"datasource", "operator", "skill", "metadata", "filelink", "pipeline", "schedule", "connector", "llmprovider"}
PERMISSION_LEVELS = {"view", "use", "manage"}
LEVEL_HIERARCHY = {"view": 1, "use": 2, "manage": 3}


def _level_value(level: str) -> int:
    return LEVEL_HIERARCHY.get(level, 0)


async def grant_permission(
    db: AsyncSession,
    resource_type: str,
    resource_id: uuid.UUID,
    granted_by: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
    role_id: Optional[uuid.UUID] = None,
    permission_level: str = "view",
) -> Permission:
    if resource_type not in RESOURCE_TYPES:
        raise ValueError(f"不支持的资源类型: {resource_type}")
    if permission_level not in PERMISSION_LEVELS:
        raise ValueError(f"不支持的权限级别: {permission_level}")
    if not user_id and not role_id:
        raise ValueError("必须指定 user_id 或 role_id")

    existing_q = select(Permission).where(
        Permission.resource_type == resource_type,
        Permission.resource_id == resource_id,
        Permission.permission_level == permission_level,
    )
    if user_id:
        existing_q = existing_q.where(Permission.user_id == user_id)
    else:
        existing_q = existing_q.where(Permission.role_id == role_id)

    existing = (await db.execute(existing_q)).scalar_one_or_none()
    if existing:
        existing.permission_level = permission_level
        await db.flush()
        return existing

    perm = Permission(
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        role_id=role_id,
        permission_level=permission_level,
    )
    db.add(perm)
    await db.flush()
    logger.info(f"授权: {resource_type}/{resource_id} -> user={user_id} role={role_id} level={permission_level} by={granted_by}")
    return perm


async def revoke_permission(
    db: AsyncSession,
    resource_type: str,
    resource_id: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
    role_id: Optional[uuid.UUID] = None,
    permission_level: Optional[str] = None,
):
    conditions = [
        Permission.resource_type == resource_type,
        Permission.resource_id == resource_id,
    ]
    if user_id:
        conditions.append(Permission.user_id == user_id)
    if role_id:
        conditions.append(Permission.role_id == role_id)
    if permission_level:
        conditions.append(Permission.permission_level == permission_level)

    await db.execute(delete(Permission).where(and_(*conditions)))
    await db.flush()


async def get_user_role_ids(db: AsyncSession, user_id: uuid.UUID) -> List[uuid.UUID]:
    result = await db.execute(
        select(user_roles.c.role_id).where(user_roles.c.user_id == user_id)
    )
    return [row[0] for row in result.fetchall()]


async def get_accessible_resource_ids(
    db: AsyncSession,
    user_id: uuid.UUID,
    resource_type: str,
    min_level: str = "view",
) -> Set[uuid.UUID]:
    """获取用户可访问的资源ID集合（不含自己创建的）"""
    role_ids = await get_user_role_ids(db, user_id)
    min_val = _level_value(min_level)

    conditions = [
        Permission.resource_type == resource_type,
        or_(Permission.user_id == user_id, Permission.role_id.in_(role_ids) if role_ids else False),
    ]

    result = await db.execute(select(Permission).where(and_(*conditions)))
    perms = result.scalars().all()

    accessible = set()
    for p in perms:
        if _level_value(p.permission_level) >= min_val:
            accessible.add(p.resource_id)
    return accessible


async def check_permission(
    db: AsyncSession,
    user_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    required_level: str = "view",
    is_owner: bool = False,
    is_superuser: bool = False,
) -> bool:
    """检查用户是否有权限访问某资源"""
    if is_superuser:
        return True
    if is_owner:
        return True

    role_ids = await get_user_role_ids(db, user_id)
    min_val = _level_value(required_level)

    conditions = [
        Permission.resource_type == resource_type,
        Permission.resource_id == resource_id,
        or_(Permission.user_id == user_id, Permission.role_id.in_(role_ids) if role_ids else False),
    ]

    result = await db.execute(select(Permission).where(and_(*conditions)))
    perms = result.scalars().all()

    for p in perms:
        if _level_value(p.permission_level) >= min_val:
            return True
    return False


async def list_resource_permissions(
    db: AsyncSession,
    resource_type: str,
    resource_id: uuid.UUID,
) -> List[dict]:
    """列出某资源的所有授权"""
    result = await db.execute(
        select(Permission).where(
            Permission.resource_type == resource_type,
            Permission.resource_id == resource_id,
        )
    )
    perms = result.scalars().all()

    out = []
    for p in perms:
        item = {
            "id": str(p.id),
            "resource_type": p.resource_type,
            "resource_id": str(p.resource_id),
            "permission_level": p.permission_level,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        if p.user_id:
            user_result = await db.execute(select(User).where(User.id == p.user_id))
            user = user_result.scalar_one_or_none()
            item["user_id"] = str(p.user_id)
            item["user_name"] = user.display_name or user.username if user else None
        if p.role_id:
            role_result = await db.execute(select(Role).where(Role.id == p.role_id))
            role = role_result.scalar_one_or_none()
            item["role_id"] = str(p.role_id)
            item["role_name"] = role.display_name or role.name if role else None
        out.append(item)
    return out


async def list_user_permissions(db: AsyncSession, user_id: uuid.UUID) -> List[dict]:
    """列出用户被授予的所有权限"""
    role_ids = await get_user_role_ids(db, user_id)

    conditions = [or_(
        Permission.user_id == user_id,
        Permission.role_id.in_(role_ids) if role_ids else False,
    )]

    result = await db.execute(select(Permission).where(and_(*conditions)))
    perms = result.scalars().all()

    out = []
    for p in perms:
        out.append({
            "id": str(p.id),
            "resource_type": p.resource_type,
            "resource_id": str(p.resource_id),
            "permission_level": p.permission_level,
            "granted_via": "user" if p.user_id == user_id else "role",
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return out


async def copy_permissions(
    db: AsyncSession,
    source_user_id: uuid.UUID,
    target_user_id: Optional[uuid.UUID] = None,
    target_role_id: Optional[uuid.UUID] = None,
    granted_by: uuid.UUID = None,
) -> int:
    """复制用户的权限给另一个用户或角色"""
    source_perms = await list_user_permissions(db, source_user_id)

    count = 0
    for p in source_perms:
        await grant_permission(
            db,
            resource_type=p["resource_type"],
            resource_id=uuid.UUID(p["resource_id"]),
            granted_by=granted_by,
            user_id=target_user_id,
            role_id=target_role_id,
            permission_level=p["permission_level"],
        )
        count += 1

    logger.info(f"复制权限: {source_user_id} -> user={target_user_id} role={target_role_id}, 共{count}条")
    return count


async def get_all_users(db: AsyncSession) -> List[dict]:
    result = await db.execute(select(User).where(User.is_active == True).order_by(User.username))
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "display_name": u.display_name or u.username,
            "email": u.email,
            "is_superuser": u.is_superuser,
        }
        for u in users
    ]


async def get_all_roles(db: AsyncSession) -> List[dict]:
    result = await db.execute(select(Role).order_by(Role.name))
    roles = result.scalars().all()
    out = []
    for r in roles:
        member_count_result = await db.execute(
            select(user_roles.c.user_id).where(user_roles.c.role_id == r.id)
        )
        member_count = len(member_count_result.fetchall())
        out.append({
            "id": str(r.id),
            "name": r.name,
            "display_name": r.display_name or r.name,
            "description": r.description,
            "member_count": member_count,
        })
    return out


async def create_role(
    db: AsyncSession,
    name: str,
    display_name: str = None,
    description: str = None,
) -> Role:
    role = Role(
        name=name,
        display_name=display_name,
        description=description,
        permissions={},
    )
    db.add(role)
    await db.flush()
    return role


async def assign_role_to_user(db: AsyncSession, role_id: uuid.UUID, user_id: uuid.UUID):
    await db.execute(
        user_roles.insert().values(user_id=user_id, role_id=role_id)
    )
    await db.flush()


async def remove_role_from_user(db: AsyncSession, role_id: uuid.UUID, user_id: uuid.UUID):
    await db.execute(
        user_roles.delete().where(
            and_(user_roles.c.user_id == user_id, user_roles.c.role_id == role_id)
        )
    )
    await db.flush()


async def get_role_members(db: AsyncSession, role_id: uuid.UUID) -> List[dict]:
    result = await db.execute(
        select(User).join(user_roles, user_roles.c.user_id == User.id).where(
            user_roles.c.role_id == role_id
        )
    )
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "display_name": u.display_name or u.username,
        }
        for u in users
    ]


# 资源类型 → 公开字段名（visibility / is_public）；None 表示无公开豁免
_PUBLIC_FIELD = {
    "skill": "visibility",
    "operator": "visibility",
    "pipeline": "visibility",
    "datasource": None,  # 数据源无公开字段，靠显式授权
    "schedule": None,
    "connector": "is_public",
    "llmprovider": "is_public",
}


async def assert_resource_access(
    db: AsyncSession,
    user,
    resource_type: str,
    resource,
    required_level: str = "view",
):
    """统一权限断言。owner/superuser 直通；公开资源放行 view/use；否则查 Permission 表。
    不通过抛 HTTPException(403)。manage 级仅 owner/superuser 或显式授权 manage。
    """
    from fastapi import HTTPException

    if user is None or getattr(user, "is_superuser", False):
        return
    owner_id = getattr(resource, "created_by", None)
    if owner_id == user.id:
        return

    # 公开资源放行 view/use（manage 仍需授权）
    public_field = _PUBLIC_FIELD.get(resource_type)
    if public_field and required_level in ("view", "use"):
        if getattr(resource, public_field, None) in (True, "public"):
            return

    has_perm = await check_permission(
        db, user.id, resource_type, resource.id, required_level, is_owner=False
    )
    if not has_perm:
        raise HTTPException(
            status_code=403,
            detail=f"无权{required_level}此{resource_type}（id={resource.id}）",
        )
