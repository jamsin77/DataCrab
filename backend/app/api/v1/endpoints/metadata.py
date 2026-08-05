"""元数据管理API端点"""

import hashlib
import json
import math
from datetime import datetime
from uuid import UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from loguru import logger

from app.core.database import get_db
from app.models.datasource import DataSource, TableMetadata
from app.models.user import User
from app.api.deps import get_current_user
from app.services.connectors import get_connector

router = APIRouter()


def _sanitize(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _serialize_meta(meta: TableMetadata, ds_name: str = None) -> dict:
    return {
        "id": str(meta.id),
        "data_source_id": str(meta.data_source_id),
        "table_name": meta.table_name,
        "table_type": meta.table_type,
        "storage_format": meta.storage_format,
        "storage_location": meta.storage_location,
        "source_connector": meta.source_connector,
        "table_schema": _sanitize(meta.table_schema),
        "row_count": meta.row_count,
        "column_count": meta.column_count,
        "size_bytes": meta.size_bytes,
        "sample_data": _sanitize(meta.sample_data),
        "column_stats": _sanitize(meta.column_stats),
        "business_name": meta.business_name,
        "business_description": meta.business_description,
        "business_tags": meta.business_tags or [],
        "business_purpose": meta.business_purpose,
        "source_system": meta.source_system,
        "data_domain": meta.data_domain,
        "data_owner": meta.data_owner,
        "data_steward": meta.data_steward,
        "security_level": meta.security_level,
        "retention_policy": meta.retention_policy,
        "last_synced_at": meta.last_synced_at.isoformat() if meta.last_synced_at else None,
        "quality_score": meta.quality_score,
        "ai_enriched": meta.ai_enriched,
        "ai_enriched_at": meta.ai_enriched_at.isoformat() if meta.ai_enriched_at else None,
        "created_at": meta.created_at.isoformat() if meta.created_at else None,
        "updated_at": meta.updated_at.isoformat() if meta.updated_at else None,
        "data_source_name": ds_name,
    }


@router.get("")
async def list_metadata(
    data_source_id: Optional[UUID] = None,
    data_domain: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """元数据列表（支持筛选/搜索/分页）"""
    query = select(TableMetadata).where(TableMetadata.data_source_id.isnot(None))

    if data_source_id:
        query = query.where(TableMetadata.data_source_id == data_source_id)
    if data_domain:
        query = query.where(TableMetadata.data_domain == data_domain)
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(
            TableMetadata.table_name.ilike(pattern),
            TableMetadata.business_name.ilike(pattern),
            TableMetadata.business_description.ilike(pattern),
        ))

    query = query.order_by(TableMetadata.updated_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    metas = result.scalars().all()

    # 批量获取数据源名称
    ds_ids = list(set(m.data_source_id for m in metas))
    ds_names = {}
    if ds_ids:
        ds_result = await db.execute(
            select(DataSource.id, DataSource.name).where(DataSource.id.in_(ds_ids))
        )
        ds_names = {row[0]: row[1] for row in ds_result.fetchall()}

    # tag 过滤（JSON 不好做 SQL 过滤，在 Python 侧做）
    items = [_serialize_meta(m, ds_names.get(m.data_source_id)) for m in metas]
    if tag:
        items = [i for i in items if tag in (i.get("business_tags") or [])]

    return {"items": items, "total": len(items)}


@router.get("/stats")
async def metadata_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """元数据统计概览"""
    total = await db.scalar(select(func.count(TableMetadata.id)))
    ai_enriched = await db.scalar(select(func.count(TableMetadata.id)).where(TableMetadata.ai_enriched == True))

    domains_result = await db.execute(
        select(TableMetadata.data_domain, func.count(TableMetadata.id))
        .where(TableMetadata.data_domain.isnot(None))
        .group_by(TableMetadata.data_domain)
    )
    domains = {row[0]: row[1] for row in domains_result.fetchall()}

    formats_result = await db.execute(
        select(TableMetadata.storage_format, func.count(TableMetadata.id))
        .where(TableMetadata.storage_format.isnot(None))
        .group_by(TableMetadata.storage_format)
    )
    formats = {row[0]: row[1] for row in formats_result.fetchall()}

    return {
        "total": total,
        "ai_enriched": ai_enriched,
        "by_domain": domains,
        "by_format": formats,
    }


@router.get("/{table_metadata_id}")
async def get_metadata(
    table_metadata_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """元数据详情"""
    result = await db.execute(
        select(TableMetadata).where(TableMetadata.id == table_metadata_id)
    )
    meta = result.scalar_one_or_none()
    if not meta:
        raise HTTPException(status_code=404, detail="元数据不存在")
    ds_name = None
    if meta.data_source_id:
        ds_r = await db.execute(select(DataSource.name).where(DataSource.id == meta.data_source_id))
        row = ds_r.first()
        if row:
            ds_name = row[0]
    return _serialize_meta(meta, ds_name)


@router.put("/{table_metadata_id}")
async def update_metadata(
    table_metadata_id: UUID,
    updates: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """编辑元数据（主要编辑业务元数据）"""
    result = await db.execute(
        select(TableMetadata).where(TableMetadata.id == table_metadata_id)
    )
    meta = result.scalar_one_or_none()
    if not meta:
        raise HTTPException(status_code=404, detail="元数据不存在")

    editable_fields = [
        "business_name", "business_description", "business_tags", "business_purpose",
        "source_system", "data_domain", "data_owner", "data_steward",
        "security_level", "retention_policy",
    ]
    for field in editable_fields:
        if field in updates:
            setattr(meta, field, updates[field])

    await db.flush()
    await db.refresh(meta)
    return _serialize_meta(meta, None)


async def _do_ai_enrich(meta: TableMetadata, ds, db: AsyncSession) -> None:
    """AI增强核心逻辑（不查 DataSource，不重复 initialize，不 flush）"""
    from app.services.llm import llm_manager
    if not llm_manager._initialized:
        await llm_manager.initialize()

    schema_str = json.dumps(meta.table_schema or [], ensure_ascii=False, default=str)
    stats_str = json.dumps(meta.column_stats or {}, ensure_ascii=False, default=str)
    sample_str = json.dumps(meta.sample_data or [], ensure_ascii=False, default=str)

    prompt = f"""请分析以下数据集的技术信息和样本数据，推断业务元数据。

## 技术信息
- 数据源名称: {ds.name if ds else '未知'}
- 数据集名称: {meta.table_name}
- 存储格式: {meta.storage_format or '未知'}
- 字段结构: {schema_str}
- 行数: {meta.row_count}
- 字段统计: {stats_str}

## 样本数据（前5行）
{sample_str}

## 请输出 JSON 格式的业务元数据
{{
    "business_name": "数据集的业务名称",
    "business_description": "一段话描述这个数据集包含什么数据、有什么特征",
    "business_tags": ["标签1", "标签2", "标签3"],
    "business_purpose": "这个数据集可能的业务用途",
    "source_system": "可能产生该数据的业务系统",
    "data_domain": "数据域分类",
    "security_level": "public/internal/confidential/secret"
}}

只输出 JSON，不要任何解释。"""

    llm_result = await llm_manager.chat_with_messages(
        [
            {"role": "system", "content": "你是数据元数据分析专家。根据数据集的技术信息和样本数据，推断业务元数据。只输出JSON，不要任何解释。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
    )

    if not llm_result or not llm_result.strip():
        raise ValueError("AI返回空内容")

    llm_result = llm_result.strip()
    if llm_result.startswith("```"):
        lines = llm_result.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        llm_result = "\n".join(lines).strip()

    parsed = json.loads(llm_result)

    for key in ["business_name", "business_description", "business_tags", "business_purpose",
                 "source_system", "data_domain", "security_level"]:
        if key in parsed:
            setattr(meta, key, parsed[key])

    meta.ai_enriched = True
    meta.ai_enriched_at = datetime.utcnow()


@router.post("/{table_metadata_id}/ai-enrich")
async def ai_enrich_business_metadata(
    table_metadata_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI补充业务元数据"""
    result = await db.execute(
        select(TableMetadata).where(TableMetadata.id == table_metadata_id)
    )
    meta = result.scalar_one_or_none()
    if not meta:
        raise HTTPException(status_code=404, detail="元数据不存在")

    ds_result = await db.execute(
        select(DataSource).where(DataSource.id == meta.data_source_id)
    )
    ds = ds_result.scalar_one_or_none()

    try:
        await _do_ai_enrich(meta, ds, db)
        logger.info(f"AI enrich done: {meta.table_name}")
    except Exception as e:
        logger.error(f"AI enrich failed [{meta.table_name}]: {e}")
        raise HTTPException(status_code=500, detail=f"AI补充失败: {e}")

    await db.flush()
    await db.refresh(meta)
    return _serialize_meta(meta, ds.name if ds else None)


# ========== 数据源元数据同步 ==========

@router.post("/datasources/{datasource_id}/sync")
async def sync_datasource_metadata(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发数据源技术元数据同步"""
    result = await db.execute(
        select(DataSource).where(DataSource.id == datasource_id)
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")

    connector = get_connector(ds.type, ds.connection_config or {})
    synced_count = 0
    current_table_names = set()

    try:
        schema_list = await connector.get_schema()

        for table_info in schema_list:
            table_name = table_info.get("table_name", "")
            if not table_name:
                continue

            current_table_names.add(table_name)

            try:
                df_sample = await connector.get_table_data(table_name, page=1, page_size=5)
            except Exception as e:
                logger.warning(f"同步表 [{table_name}] 获取样本失败: {e}")
                df_sample = None

            try:
                stats = await connector.get_table_stats(table_name)
            except Exception as e:
                logger.warning(f"同步表 [{table_name}] 获取统计失败: {e}")
                stats = {}

            column_stats = {}
            table_schema_list = []
            if df_sample is not None and not df_sample.empty:
                for col in df_sample.columns:
                    cs = {
                        "dtype": str(df_sample[col].dtype),
                        "null_rate": round(float(df_sample[col].isna().mean()), 4),
                        "unique_count": int(df_sample[col].nunique()),
                    }
                    if str(df_sample[col].dtype) in ('int64', 'float64', 'Int64', 'Float64'):
                        try:
                            cs["min"] = float(df_sample[col].min())
                            cs["max"] = float(df_sample[col].max())
                        except Exception:
                            pass
                    column_stats[col] = cs
                    table_schema_list.append({
                        "name": str(col),
                        "dtype": str(df_sample[col].dtype),
                        "nullable": bool(df_sample[col].isna().any()),
                    })

            if ds.type == "excel":
                storage_location = table_info.get("file_path", ds.connection_config.get("file_path", ""))
                if table_info.get("sheet_name"):
                    storage_location += f" → Sheet: {table_info['sheet_name']}"
            elif ds.type == "csv":
                storage_location = ds.connection_config.get("file_path", "")
            elif ds.type in ("mysql", "postgres"):
                cfg = ds.connection_config
                storage_location = f"{cfg.get('host', '')}:{cfg.get('port', '')}/{cfg.get('database', '')}"
            else:
                storage_location = json.dumps(ds.connection_config, ensure_ascii=False)[:500]

            existing = await db.execute(
                select(TableMetadata).where(
                    TableMetadata.data_source_id == ds.id,
                    TableMetadata.table_name == table_name,
                )
            )
            meta = existing.scalar_one_or_none()

            tech_data = {
                "table_type": table_info.get("table_type", "table"),
                "storage_format": ds.type,
                "storage_location": storage_location,
                "source_connector": ds.type,
                "table_schema": table_schema_list,
                "row_count": stats.get("row_count", len(df_sample) if df_sample is not None else 0),
                "column_count": len(df_sample.columns) if df_sample is not None else 0,
                "size_bytes": stats.get("size_bytes"),
                "sample_data": json.loads(json.dumps(df_sample.fillna("").to_dict(orient="records"), default=str)) if df_sample is not None else [],
                "column_stats": column_stats,
                "last_synced_at": datetime.utcnow(),
                "data_updated_at": table_info.get("data_updated_at"),
                "schema_hash": hashlib.sha256(
                    json.dumps(table_schema_list, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()[:32],
            }

            try:
                if meta:
                    for k, v in tech_data.items():
                        setattr(meta, k, v)
                else:
                    meta = TableMetadata(
                        data_source_id=ds.id,
                        table_name=table_name,
                        **tech_data,
                    )
                    db.add(meta)
                synced_count += 1
            except Exception as e:
                logger.warning(f"同步表 [{table_name}] 写入失败: {e}")

        await db.flush()

        # 删除数据源中已不存在的表的元数据（即使 current_table_names 为空也执行——清理全部）
        stale_result = await db.execute(
            select(TableMetadata).where(
                TableMetadata.data_source_id == ds.id,
                ~TableMetadata.table_name.in_(current_table_names) if current_table_names else True,
            )
        )
        stale_metas = stale_result.scalars().all()
        for stale in stale_metas:
            await db.delete(stale)
        if stale_metas:
            logger.info(f"数据源 [{ds.name}] 清理过期元数据: {len(stale_metas)} 张表")
    finally:
        await connector.close()

    logger.info(f"数据源 [{ds.name}] 元数据同步完成: {synced_count} 张表, 清理 {len(stale_metas)} 张过期表")
    return {"synced": synced_count, "deleted_stale": len(stale_metas), "datasource": ds.name}


@router.get("/datasources/{datasource_id}")
async def get_datasource_metadata(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取数据源下所有表的元数据"""
    result = await db.execute(
        select(TableMetadata).where(TableMetadata.data_source_id == datasource_id)
        .order_by(TableMetadata.table_name)
    )
    metas = result.scalars().all()
    ds_name = None
    ds_r = await db.execute(select(DataSource.name).where(DataSource.id == datasource_id))
    row = ds_r.first()
    if row:
        ds_name = row[0]
    return {"items": [_serialize_meta(m, ds_name) for m in metas], "total": len(metas)}
