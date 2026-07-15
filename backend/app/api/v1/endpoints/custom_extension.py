"""扩展 API — 数据源连接器 + LLM Provider 管理"""

from uuid import UUID
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from loguru import logger

from app.core.database import get_db
from app.models.custom_extension import CustomConnector, LLMProvider
from app.models.user import User
from app.api.deps import get_current_user
from app.services.permission_service import get_accessible_resource_ids, check_permission

router = APIRouter()


# ========== 数据源连接器 ==========

class ConnectorCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    code: str
    config_template: Optional[list] = []
    is_public: Optional[bool] = False


class ConnectorUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    config_template: Optional[list] = None
    is_public: Optional[bool] = None


@router.get("/connectors/custom")
async def list_custom_connectors(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户可见的连接器（自己的 + 公共的 + RBAC 共享的）"""
    shared_ids = await get_accessible_resource_ids(db, current_user.id, "connector")
    query = select(CustomConnector).where(CustomConnector.is_active == True)
    if not current_user.is_superuser:
        conds = [CustomConnector.created_by == current_user.id, CustomConnector.is_public == True]
        if shared_ids:
            conds.append(CustomConnector.id.in_(shared_ids))
        query = query.where(or_(*conds))
    query = query.order_by(CustomConnector.is_public.desc(), CustomConnector.created_at, CustomConnector.name)
    items = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "display_name": c.display_name or c.name,
            "description": c.description or "",
            "config_template": c.config_template or [],
            "code": c.code or "",
            "is_public": bool(c.is_public),
            "created_by": str(c.created_by) if c.created_by else None,
            "is_owner": c.created_by == current_user.id,
            "can_edit": c.created_by == current_user.id or current_user.is_superuser,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in items
    ]


@router.post("/connectors/custom")
async def create_custom_connector(
    payload: ConnectorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新增连接器：验证代码 → 存 DB → 注册到内存（默认私有）"""
    name = payload.name.strip().lower()
    if not name or not payload.code:
        raise HTTPException(status_code=400, detail="name 和 code 必填")

    existing = await db.execute(
        select(CustomConnector).where(
            or_(CustomConnector.name == name, CustomConnector.display_name == payload.display_name),
            CustomConnector.is_active == True,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="已存在同名或同显示名称的连接器，请编辑已有连接器而非新建")

    from app.services.connectors import register_custom_connector
    try:
        register_custom_connector(name, payload.code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"代码验证失败: {e}")

    record = CustomConnector(
        name=name,
        display_name=payload.display_name or name,
        description=payload.description or "",
        code=payload.code,
        config_template=payload.config_template or [],
        is_public=payload.is_public or False,
        created_by=current_user.id,
    )
    db.add(record)
    await db.commit()
    return {"ok": True, "id": str(record.id), "message": f"连接器 '{name}' 已创建"}


@router.put("/connectors/custom/{connector_id}")
async def update_custom_connector(
    connector_id: UUID,
    payload: ConnectorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改连接器：仅所有者或超级管理员可改"""
    result = await db.execute(select(CustomConnector).where(CustomConnector.id == connector_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="连接器不存在")
    if record.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="无权修改此连接器")

    from app.services.connectors import register_custom_connector
    new_code = payload.code if payload.code is not None else record.code
    if payload.code is not None:
        try:
            register_custom_connector(record.name, new_code)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"代码验证失败: {e}")

    if payload.display_name is not None:
        record.display_name = payload.display_name
    if payload.description is not None:
        record.description = payload.description
    if payload.code is not None:
        record.code = new_code
    if payload.config_template is not None:
        record.config_template = payload.config_template
    if payload.is_public is not None:
        record.is_public = payload.is_public
    await db.commit()
    return {"ok": True, "message": f"连接器 '{record.name}' 已更新"}


@router.delete("/connectors/custom/{connector_id}")
async def delete_custom_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除连接器（软删除 + 从内存注册表移除）；仅所有者或超级管理员可删"""
    result = await db.execute(select(CustomConnector).where(CustomConnector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="连接器不存在")
    if connector.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="无权删除此连接器")

    # 限制：已有数据源使用的连接器不能删除，避免数据源孤立
    from app.models.datasource import DataSource
    ds_count = await db.scalar(
        select(func.count(DataSource.id)).where(
            DataSource.type == connector.name,
            DataSource.is_active == True,
        )
    )
    if ds_count and ds_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该连接器已被 {ds_count} 个数据源使用，无法删除。请先删除或迁移相关数据源。",
        )

    from app.services.connectors import _connector_registry, _sync_supported_types
    _connector_registry.pop(connector.name, None)
    _sync_supported_types()

    connector.is_active = False
    await db.commit()
    return {"ok": True}


# ========== LLM Provider ==========

@router.get("/providers")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户可见的 Provider（自己的 + 公共的 + RBAC 共享的）"""
    shared_ids = await get_accessible_resource_ids(db, current_user.id, "llmprovider")
    query = select(LLMProvider).where(LLMProvider.is_active == True)
    if not current_user.is_superuser:
        conds = [LLMProvider.created_by == current_user.id, LLMProvider.is_public == True]
        if shared_ids:
            conds.append(LLMProvider.id.in_(shared_ids))
        query = query.where(or_(*conds))
    query = query.order_by(LLMProvider.is_public.desc(), LLMProvider.created_at, LLMProvider.provider_name)
    items = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(p.id),
            "provider_name": p.provider_name,
            "display_name": p.display_name or p.provider_name,
            "description": p.description or "",
            "api_base": p.api_base or "",
            "models": p.models or [],
            "fast_model": p.fast_model or "",
            "is_public": bool(p.is_public),
            "is_owner": p.created_by == current_user.id,
            "can_edit": p.created_by == current_user.id or current_user.is_superuser,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in items
    ]


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除 Provider（仅所有者或超级管理员可删）"""
    result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    if provider.created_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="无权删除此 Provider")

    from app.services.llm import _custom_adapter_cache, _provider_registry
    _custom_adapter_cache.pop(provider.provider_name, None)
    _provider_registry.pop(provider.provider_name, None)

    provider.is_active = False
    await db.commit()
    return {"ok": True}
