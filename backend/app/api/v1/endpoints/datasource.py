"""数据源管理API端点"""

import json
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional, Any


def _normalize_ts(ts: Any) -> Optional[datetime]:
    """归一化时间戳为 aware UTC datetime，消除 aware/naive 混合导致的比较错误。

    返回 aware UTC，isoformat() 带 +00:00，前端 new Date 才能正确转本地时区显示。
    - aware datetime → 转 UTC
    - naive datetime → 假定已是 UTC，补 tzinfo=UTC
    - 其他类型 → None
    """
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)

from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.services.permission_service import get_accessible_resource_ids, check_permission

from app.core.database import get_db
from app.models.datasource import DataSource, TableMetadata
from app.models.user import User
from app.schemas.datasource import (
    DataSourceCreate,
    DataSourceUpdate,
    DataSourceResponse,
    ConnectionTestResult,
    TreeNode,
    TableDataResponse,
    TableStatsResponse,
    QualityAnalysisResponse,
    _SENSITIVE_KEYS,
)
from app.api.deps import get_current_user

router = APIRouter()


def _get_connector(*args, **kwargs):
    from app.services.connectors import get_connector as _gc
    return _gc(*args, **kwargs)


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_datasource(
    request: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建数据源"""
    datasource = DataSource(
        name=request.name,
        type=request.type,
        connection_config=request.connection_config,
        business_metadata=request.business_metadata,
        security_level=request.security_level,
        created_by=current_user.id,
    )
    db.add(datasource)
    await db.flush()
    await db.refresh(datasource)

    # 自动为文件型数据源创建 FileLink（授权目录），使沙箱 read_file/llm_vision 可访问
    await _auto_create_file_link(db, datasource, current_user.id)

    return datasource


async def _auto_create_file_link(db: AsyncSession, datasource: DataSource, user_id):
    """文件型数据源自动创建 FileLink，授权沙箱访问其目录"""
    from pathlib import Path
    from app.models.filelink import FileLink

    cfg = datasource.connection_config or {}
    file_path = cfg.get("file_path") or cfg.get("path") or cfg.get("folder_path") or cfg.get("directory") or ""
    if not file_path:
        return

    p = Path(file_path)
    # 文件 → 授权父目录；目录 → 授权自身
    dir_path = str(p.parent) if p.is_file() or "." in p.name else str(p)

    # 检查是否已有同路径的 FileLink
    result = await db.execute(
        select(FileLink).where(
            FileLink.path == dir_path,
            FileLink.created_by == user_id,
            FileLink.is_active == True,
        )
    )
    if result.scalars().first():
        return

    link = FileLink(
        name=f"[自动] {datasource.name}",
        path=dir_path,
        description=f"数据源 {datasource.name} 自动授权目录",
        link_type="directory",
        created_by=user_id,
    )
    db.add(link)
    await db.flush()
    logger.info(f"自动创建 FileLink: {dir_path} (数据源: {datasource.name})")


@router.get("", response_model=list[DataSourceResponse])
async def list_datasources(
    datasource_type: Optional[str] = Query(None, alias="type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取数据源列表（虚拟数据源「聊天上传数据」始终排第一位）"""
    shared_ids = await get_accessible_resource_ids(db, current_user.id, "datasource")
    query = select(DataSource).where(
        DataSource.is_active == True,
        or_(
            DataSource.created_by == current_user.id,
            DataSource.id.in_(shared_ids) if shared_ids else False,
        ),
    )
    if datasource_type:
        query = query.where(or_(DataSource.type == datasource_type, DataSource.is_virtual == True))
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    all_ds = list(result.scalars().all())
    # 虚拟数据源排第一，其余按 created_at desc
    all_ds.sort(key=lambda ds: (0 if getattr(ds, "is_virtual", False) else 1,
                                -(ds.created_at.timestamp() if ds.created_at else 0)))
    return all_ds


def _reject_virtual(datasource, action: str):
    """虚拟数据源受保护，禁止修改/删除/测试/同步"""
    if getattr(datasource, "is_virtual", False):
        raise HTTPException(
            status_code=status_code.HTTP_403_FORBIDDEN,
            detail=f"虚拟数据源「{datasource.name}」受保护，不可{action}",
        )


@router.get("/{datasource_id}", response_model=DataSourceResponse)
async def get_datasource(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取数据源详情"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")
    is_owner = datasource.created_by == current_user.id
    if not is_owner and not current_user.is_superuser:
        has_perm = await check_permission(db, current_user.id, "datasource", datasource_id, "view", is_owner=False)
        if not has_perm:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问此数据源")
    return datasource


@router.put("/{datasource_id}", response_model=DataSourceResponse)
async def update_datasource(
    datasource_id: UUID,
    request: DataSourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新数据源"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    _reject_virtual(datasource, "修改")

    update_data = request.model_dump(exclude_unset=True)

    if "connection_config" in update_data and update_data["connection_config"] is not None:
        new_config = update_data["connection_config"]
        old_config = datasource.connection_config or {}
        merged = {}
        for k, v in new_config.items():
            if k.lower() in _SENSITIVE_KEYS and v == "***":
                merged[k] = old_config.get(k, v)
            else:
                merged[k] = v
        for k, v in old_config.items():
            if k not in merged:
                merged[k] = v
        update_data["connection_config"] = merged

    for key, value in update_data.items():
        setattr(datasource, key, value)

    await db.flush()
    await db.refresh(datasource)

    # 修改时也自动创建 FileLink（授权目录）
    await _auto_create_file_link(db, datasource, current_user.id)

    return datasource


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_datasource(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除数据源"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")
    _reject_virtual(datasource, "删除")
    datasource.is_active = False
    await db.flush()


@router.post("/{datasource_id}/test", response_model=ConnectionTestResult)
async def test_connection(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """测试数据源连接"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    _reject_virtual(datasource, "测试")

    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        success = await connector.test_connection()
        await connector.close()
        if success:
            return ConnectionTestResult(success=True, message="连接测试成功")
        else:
            return ConnectionTestResult(success=False, message="连接测试失败")
    except ValueError as e:
        return ConnectionTestResult(success=False, message=str(e))
    except Exception as e:
        logger.error(f"测试连接异常: {e}")
        return ConnectionTestResult(success=False, message=f"连接测试异常: {str(e)}")


@router.get("/{datasource_id}/tree", response_model=list[TreeNode])
async def get_datasource_tree(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取数据源树形结构（表按最后更新时间降序，最新的在前）"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        schema = await connector.get_schema()
        await connector.close()

        # 关联 TableMetadata 获取最后更新时间，按更新时间降序排序（最新的在前）
        table_names = [item.get("table_name", "") for item in schema if item.get("table_name")]
        meta_map: dict = {}
        if table_names:
            meta_result = await db.execute(
                select(TableMetadata.table_name, TableMetadata.data_updated_at, TableMetadata.created_at).where(
                    TableMetadata.data_source_id == datasource_id,
                    TableMetadata.table_name.in_(table_names),
                )
            )
            meta_map = {
                row[0]: {"data_updated_at": row[1], "created_at": row[2]}
                for row in meta_result.all()
            }

        nodes_with_ts = []
        for item in schema:
            table_name = item.get("table_name", "")
            table_type = item.get("table_type", "")
            meta_info = meta_map.get(table_name, {})
            # 优先使用连接器返回的实时 data_updated_at（反映外部修改，如用户手动加列），
            # 其次用 DB TableMetadata.data_updated_at（DataCrab 写入时更新），最后用 created_at
            live_ts = item.get("data_updated_at")
            db_ts = meta_info.get("data_updated_at") or meta_info.get("created_at")
            # 归一化为 naive UTC，避免 aware/naive 混合比较报错
            ts = _normalize_ts(live_ts) or _normalize_ts(db_ts)
            meta = dict(item)
            if ts:
                meta["data_updated_at"] = ts.isoformat()
            node = TreeNode(
                id=f"{datasource_id}:{table_name}",
                label=table_name,
                type=table_type,
                metadata=meta,
            )
            nodes_with_ts.append((node, ts))

        # 有更新时间的在前（按时间降序），无更新时间的排后（保持原顺序）
        _EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
        nodes_with_ts.sort(key=lambda x: x[1] or _EPOCH, reverse=True)

        return [n for n, _ in nodes_with_ts]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"获取数据源树异常: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{datasource_id}/tables/{table_name}/data", response_model=TableDataResponse)
async def get_table_data(
    datasource_id: UUID,
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取表数据"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        df = await connector.get_table_data(table_name, page=page, page_size=page_size)

        total_count = len(df)
        try:
            stats = await connector.get_table_stats(table_name)
            total_count = stats.get("row_count", total_count)
        except Exception:
            pass

        await connector.close()

        columns = [{"name": col, "type": str(df[col].dtype)} for col in df.columns]
        rows = df.fillna("").to_dict(orient="records")

        return TableDataResponse(
            columns=columns,
            rows=rows,
            total=total_count,
            page=page,
            page_size=page_size,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"获取表数据异常: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{datasource_id}/tables/{table_name}/stats", response_model=TableStatsResponse)
async def get_table_stats(
    datasource_id: UUID,
    table_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取表统计信息"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        stats = await connector.get_table_stats(table_name)
        await connector.close()

        return TableStatsResponse(
            row_count=stats.get("row_count", 0),
            column_count=stats.get("column_count", 0),
            size_bytes=stats.get("size_bytes", 0),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"获取表统计异常: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{datasource_id}/tables/{table_name}/quality", response_model=QualityAnalysisResponse)
async def get_table_quality(
    datasource_id: UUID,
    table_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取数据质量分析"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        df = await connector.get_table_data(table_name, page=1, page_size=10000)
        await connector.close()

        if df.empty:
            return QualityAnalysisResponse(completeness=1.0, consistency=1.0, issues=[], suggestions=[])

        total_cells = df.size
        null_cells = int(df.isnull().sum().sum())
        completeness = 1.0 - (null_cells / total_cells) if total_cells > 0 else 1.0

        issues = []
        suggestions = []

        for col in df.columns:
            null_count = int(df[col].isnull().sum())
            if null_count > 0:
                null_pct = null_count / len(df) * 100
                issues.append({
                    "column": col,
                    "issue": "缺失值",
                    "count": null_count,
                    "percentage": round(null_pct, 2),
                })
                suggestions.append({
                    "column": col,
                    "suggestion": f"建议填充或删除{col}列的缺失值（{round(null_pct, 1)}%缺失）",
                })

            if df[col].dtype in ("int64", "float64"):
                q1 = df[col].quantile(0.25)
                q3 = df[col].quantile(0.75)
                iqr = q3 - q1
                outliers = df[(df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)]
                if len(outliers) > 0:
                    issues.append({
                        "column": col,
                        "issue": "异常值",
                        "count": len(outliers),
                        "percentage": round(len(outliers) / len(df) * 100, 2),
                    })

        return QualityAnalysisResponse(
            completeness=round(completeness, 4),
            consistency=1.0,
            issues=issues,
            suggestions=suggestions,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"获取数据质量分析异常: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ==================== 沙箱工具辅助函数（供 tool_registry handler 调用）====================

def _validate_file_path(path: str, allowed_dirs: list) -> str:
    """验证文件路径在授权目录范围内，返回 resolved 路径或抛异常"""
    from pathlib import Path
    resolved = Path(path).resolve()
    for allowed in allowed_dirs:
        allowed_resolved = Path(allowed).resolve()
        if str(resolved).startswith(str(allowed_resolved)):
            return str(resolved)
    raise HTTPException(status_code=403, detail=f"路径不在授权目录范围内: {path}")


async def _collect_allowed_dirs(db: AsyncSession, user_id) -> list[str]:
    """收集授权目录：文件链接 + 文件型数据源目录（用户建数据源即授权）"""
    from pathlib import Path
    allowed = []

    # 1. 文件链接
    from app.models.filelink import FileLink
    result = await db.execute(
        select(FileLink).where(FileLink.is_active == True, FileLink.created_by == user_id)
    )
    for f in result.scalars().all():
        if f.link_type == "directory":
            allowed.append(f.path)
        else:
            allowed.append(str(Path(f.path).parent))

    # 2. 文件型数据源自动授权
    result = await db.execute(
        select(DataSource).where(DataSource.is_active == True, DataSource.created_by == user_id)
    )
    _FILE_DS_TYPES = {"csv", "excel", "generic_file"}
    for ds in result.scalars().all():
        if ds.type not in _FILE_DS_TYPES:
            continue
        cfg = ds.connection_config or {}
        for key in ("path", "folder_path", "file_path", "directory"):
            p = cfg.get(key)
            if p:
                allowed.append(str(Path(p).parent if Path(p).suffix else p))
        for p in cfg.get("file_paths", []):
            if p:
                allowed.append(str(Path(p).parent))

    return allowed


# ==================== 内部统一工具执行端点 ====================

@router.post("/internal/execute-tool")
async def internal_execute_tool(body: dict, db: AsyncSession = Depends(get_db)):
    """内部统一工具执行端点（无认证，仅供技能/算子沙箱子进程本机调用）。
    
    接收 {tool_name, args, user_id}，调用 tool_registry handler 统一分发。
    所有沙箱工具调用都通过此端点，替代之前分散的 /internal/* 端点。
    直接调 handler（不经 execute_tool），跳过 LRU 缓存和截断（脚本需要完整数据）。
    """
    from app.services.tool_registry import _REGISTRY, _ensure_registered
    from app.core.database import async_session as _tool_session
    from uuid import UUID as _UUID

    tool_name = body.get("tool_name")
    args = body.get("args", {})
    user_id = body.get("user_id")

    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name 必填")

    _ensure_registered()
    td = _REGISTRY.get(tool_name)
    if not td:
        raise HTTPException(status_code=400, detail=f"未知工具: {tool_name}")

    _uid = None
    if user_id:
        try:
            _uid = _UUID(str(user_id))
        except (ValueError, TypeError):
            pass

    _ctx = {"_sandbox_call": True}
    try:
        async with _tool_session() as tool_db:
            result_str = await td.handler(args, tool_db, _uid, _ctx)
            await tool_db.commit()
    except Exception as e:
        logger.error(f"internal_execute_tool({tool_name}) 异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    try:
        return json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return {"result": result_str}
