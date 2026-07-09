"""扩展 API — 数据源连接器 + LLM Provider 管理"""

from uuid import UUID
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.core.database import get_db
from app.models.custom_extension import CustomConnector, LLMProvider
from app.models.user import User
from app.api.deps import get_current_user

router = APIRouter()


# ========== 数据源连接器 ==========

@router.get("/connectors/custom")
async def list_custom_connectors(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有连接器"""
    result = await db.execute(
        select(CustomConnector).where(CustomConnector.is_active == True).order_by(CustomConnector.created_at.desc())
    )
    items = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "display_name": c.display_name or c.name,
            "description": c.description or "",
            "config_template": c.config_template or [],
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in items
    ]


@router.delete("/connectors/custom/{connector_id}")
async def delete_custom_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除连接器"""
    result = await db.execute(select(CustomConnector).where(CustomConnector.id == connector_id))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="连接器不存在")

    from app.services.connectors import _custom_connector_cache
    _custom_connector_cache.pop(connector.name, None)

    connector.is_active = False
    await db.flush()
    return {"ok": True}


# ========== LLM Provider ==========

@router.get("/providers")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有 Provider"""
    result = await db.execute(
        select(LLMProvider).where(LLMProvider.is_active == True).order_by(LLMProvider.created_at, LLMProvider.provider_name)
    )
    items = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "provider_name": p.provider_name,
            "display_name": p.display_name or p.provider_name,
            "description": p.description or "",
            "api_base": p.api_base or "",
            "models": p.models or [],
            "fast_model": p.fast_model or "",
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
    """删除 Provider"""
    result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    from app.services.llm import _custom_adapter_cache, _provider_registry
    _custom_adapter_cache.pop(provider.provider_name, None)
    _provider_registry.pop(provider.provider_name, None)

    provider.is_active = False
    await db.commit()
    return {"ok": True}
