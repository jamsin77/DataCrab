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
    """获取数据源列表"""
    shared_ids = await get_accessible_resource_ids(db, current_user.id, "datasource")
    query = select(DataSource).where(
        DataSource.is_active == True,
        or_(
            DataSource.created_by == current_user.id,
            DataSource.id.in_(shared_ids) if shared_ids else False,
        ),
    )
    if datasource_type:
        query = query.where(DataSource.type == datasource_type)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


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


@router.get("/internal/datasources/{datasource_id}/tables/{table_name}/data")
async def internal_get_table_data(
    datasource_id: UUID,
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """内部查询端点（无认证，仅供技能执行器子进程本机调用）"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        df = await connector.get_table_data(table_name, page=page, page_size=page_size)
        stats = await connector.get_table_stats(table_name)
        await connector.close()
        columns = [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]
        rows = df.fillna("").to_dict(orient="records")
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif not isinstance(v, (str, int, float, bool, type(None))):
                    r[k] = str(v)
        return {"columns": columns, "rows": rows, "total": stats.get("row_count", len(rows))}
    except Exception as e:
        logger.error(f"内部查询异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/internal/datasources/{datasource_id}/schema")
async def internal_get_schema(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """内部获取表结构（无认证，仅供技能执行器子进程本机调用）"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        schema = await connector.get_schema()
        await connector.close()
        return {"tables": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/internal/datasources")
async def internal_list_datasources(db: AsyncSession = Depends(get_db)):
    """内部列出数据源（无认证，仅供技能执行器子进程本机调用）"""
    result = await db.execute(select(DataSource).where(DataSource.is_active == True))
    return [{"id": str(s.id), "name": s.name, "type": s.type} for s in result.scalars().all()]


@router.post("/internal/datasources/{datasource_id}/tables/{table_name}/data")
async def internal_write_table_data(
    datasource_id: UUID,
    table_name: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """内部写入端点（无认证，仅供技能执行器子进程本机调用）"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        from app.services.connectors import ConnectorManager
        mgr = ConnectorManager(db)
        kwargs = {}
        if body.get("if_table_exists") and body["if_table_exists"] != "fail":
            kwargs["if_table_exists"] = body["if_table_exists"]
        if body.get("table_remark"):
            kwargs["table_remark"] = body["table_remark"]
        if body.get("column_remarks"):
            kwargs["column_remarks"] = body["column_remarks"]
        result = await mgr.write_table(
            str(datasource_id),
            table_name,
            body.get("records", []),
            **kwargs,
        )
        # 写入成功后更新 TableMetadata.data_updated_at，使浏览树显示最新修改时间
        if isinstance(result, dict) and result.get("success", True):
            from datetime import datetime as _dt
            meta_result = await db.execute(
                select(TableMetadata).where(
                    TableMetadata.data_source_id == datasource_id,
                    TableMetadata.table_name == table_name,
                )
            )
            meta = meta_result.scalar_one_or_none()
            if meta:
                meta.data_updated_at = _dt.utcnow()
            else:
                meta = TableMetadata(
                    data_source_id=datasource_id,
                    table_name=table_name,
                    data_updated_at=_dt.utcnow(),
                )
                db.add(meta)
            await db.flush()
        return result
    except Exception as e:
        logger.error(f"内部写入异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/internal/llm/chat")
async def internal_llm_chat(body: dict):
    """内部 LLM 对话端点（无认证，仅供技能执行器子进程本机调用）。
    通过 user_id 加载用户级 LLM 配置（含私有 API Key），确保技能脚本中的
    llm_chat() 使用用户自己的模型和额度。"""
    from app.services.llm import llm_manager, init_user_llm_context, reset_user_llm_config
    user_id = body.get("user_id")
    try:
        if user_id:
            await init_user_llm_context(user_id)
        await llm_manager.initialize()
        messages = []
        system_prompt = body.get("system_prompt")
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": body.get("prompt", "")})
        result = await llm_manager.chat_with_messages(
            messages,
            temperature=body.get("temperature", 0.7),
            max_tokens=int(body.get("max_tokens", 2000)),
        )
        return {"content": result}
    except Exception as e:
        logger.error(f"内部 LLM 对话异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        reset_user_llm_config()


@router.post("/internal/llm/vision")
async def internal_llm_vision(body: dict, db: AsyncSession = Depends(get_db)):
    """内部 LLM 视觉端点（无认证，仅供技能执行器子进程本机调用）。
    读取图片 → base64 编码 → 发送给视觉大模型 → 返回文本。"""
    import base64
    from pathlib import Path
    from app.models.filelink import FileLink
    from app.services.llm import llm_manager, init_user_llm_context, reset_user_llm_config, get_user_llm_config, _PROVIDER_VISION_MODELS

    user_id = body.get("user_id")
    user_id = UUID(str(user_id)) if user_id else None
    image_path = body.get("image_path", "")
    prompt = body.get("prompt", "")
    if not image_path or not prompt:
        raise HTTPException(status_code=400, detail="image_path 和 prompt 必填")

    allowed_dirs = await _collect_allowed_dirs(db, user_id)
    validated = _validate_file_path(image_path, allowed_dirs)
    p = Path(validated)
    if not p.exists():
        raise HTTPException(status_code=404, detail="图片文件不存在")

    ext = p.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tiff"):
        raise HTTPException(status_code=400, detail=f"不支持的图片格式: {ext}")

    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".bmp": "image/bmp", ".webp": "image/webp", ".gif": "image/gif", ".tiff": "image/tiff"}
    mime = mime_map.get(ext, "image/jpeg")

    try:
        # 图片压缩：缩到最大宽度 1024px，OCR 不需要原始分辨率，省 60-70% token
        raw_bytes = p.read_bytes()
        try:
            import io as _io
            from PIL import Image as _PILImage
            img = _PILImage.open(_io.BytesIO(raw_bytes))
            if img.width > 1024 or img.height > 1024:
                ratio = min(1024 / img.width, 1024 / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, _PILImage.LANCZOS)
            buf = _io.BytesIO()
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=85)
            image_data = base64.b64encode(buf.getvalue()).decode("utf-8")
            mime = "image/jpeg"
        except Exception:
            image_data = base64.b64encode(raw_bytes).decode("utf-8")
        if user_id:
            await init_user_llm_context(user_id)
        await llm_manager.initialize()

        # 视觉模型：读用户配置的 vision_model
        _user_cfg = get_user_llm_config()
        if not _user_cfg:
            raise HTTPException(status_code=400, detail="未配置 LLM Provider，请在配置页面设置")
        _vision_model = llm_manager._eff_vision_model(_user_cfg.get("provider", ""))
        if not _vision_model:
            raise HTTPException(status_code=400, detail="当前 Provider 未配置视觉模型，请在配置页面设置")

        system_prompt = body.get("system_prompt")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}},
                {"type": "text", "text": prompt},
            ],
        })

        _client = llm_manager._client_for(_user_cfg)
        resp = await _client.chat.completions.create(
            model=_vision_model,
            messages=messages,
            temperature=body.get("temperature", 0.3),
            max_tokens=int(body.get("max_tokens", 2000)),
        )
        result_text = resp.choices[0].message.content
        return {"content": result_text}
    except Exception as e:
        logger.error(f"内部 LLM 视觉异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        reset_user_llm_config()


# ==================== 内部视频处理端点 ====================

@router.post("/internal/video/info")
async def internal_video_info(body: dict, db: AsyncSession = Depends(get_db)):
    """内部视频信息提取端点（无认证，仅供技能执行器子进程本机调用）。
    提取视频元数据：时长、分辨率、帧率、编码等。"""
    from pathlib import Path
    from app.services.video_utils import probe_video, is_video_file

    user_id = body.get("user_id")
    user_id = UUID(str(user_id)) if user_id else None
    video_path = body.get("video_path", "")
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path 必填")

    allowed_dirs = await _collect_allowed_dirs(db, user_id)
    validated = _validate_file_path(video_path, allowed_dirs)
    p = Path(validated)
    if not p.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    if not is_video_file(str(p)):
        raise HTTPException(status_code=400, detail=f"不支持的视频格式: {p.suffix}")

    try:
        result = probe_video(str(p))
        result["video_path"] = str(p)
        return result
    except Exception as e:
        logger.error(f"内部视频信息提取异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/internal/video/keyframes")
async def internal_video_keyframes(body: dict, db: AsyncSession = Depends(get_db)):
    """内部视频关键帧抽取端点（无认证，仅供技能执行器子进程本机调用）。
    抽取关键帧为 JPEG 图片，返回帧列表（含时间戳和图片路径）。"""
    from pathlib import Path
    from app.services.video_utils import extract_keyframes, is_video_file

    user_id = body.get("user_id")
    user_id = UUID(str(user_id)) if user_id else None
    video_path = body.get("video_path", "")
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path 必填")

    max_frames = int(body.get("max_frames", 8))
    output_dir = body.get("output_dir")
    method = body.get("method", "auto")

    allowed_dirs = await _collect_allowed_dirs(db, user_id)
    validated = _validate_file_path(video_path, allowed_dirs)
    p = Path(validated)
    if not p.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    if not is_video_file(str(p)):
        raise HTTPException(status_code=400, detail=f"不支持的视频格式: {p.suffix}")

    # output_dir 须在授权目录内（如果指定了）
    if output_dir:
        _validate_file_path(output_dir, allowed_dirs)

    try:
        frames = extract_keyframes(
            str(p),
            max_frames=max_frames,
            output_dir=output_dir,
            method=method,
        )
        return {"success": True, "frames": frames, "count": len(frames)}
    except Exception as e:
        logger.error(f"内部视频关键帧抽取异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/internal/datasources/{datasource_id}/sql")
async def internal_execute_sql(
    datasource_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """内部 SQL 执行端点（无认证，仅供技能执行器子进程本机调用）。
    支持 DB 型连接器的原生 SQL，文件型连接器返回不支持错误。"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        await connector.connect()
        df = await connector.execute_query(body.get("sql", ""))
        await connector.close()
        if df is None or df.empty:
            return {"columns": list(df.columns) if df is not None else [], "rows": [], "row_count": 0}
        limit = int(body.get("limit", 10000))
        if len(df) > limit:
            df = df.head(limit)
        columns = list(df.columns)
        rows = df.fillna("").to_dict(orient="records")
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif not isinstance(v, (str, int, float, bool, type(None))):
                    r[k] = str(v)
        return {"columns": columns, "rows": rows, "row_count": len(rows)}
    except Exception as e:
        logger.error(f"内部 SQL 执行异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/internal/datasources/{datasource_id}/tables")
async def internal_list_tables(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """内部列出表列表端点（无认证，仅供技能执行器子进程本机调用）"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        schema = await connector.get_schema()
        await connector.close()
        return {"tables": [t.get("table_name", str(t)) if isinstance(t, dict) else str(t) for t in schema]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/internal/datasources/{datasource_id}/tables/{table_name}/chunks")
async def internal_iter_table_data(
    datasource_id: UUID,
    table_name: str,
    chunk_size: int = Query(10000, ge=1, le=100000),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """内部分块读取端点（无认证，仅供技能执行器子进程本机调用）。
    返回指定 chunk 的数据，技能沙箱通过翻页实现迭代。"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        df = await connector.get_table_data(table_name, page=page, page_size=chunk_size)
        stats = await connector.get_table_stats(table_name)
        await connector.close()
        total = stats.get("row_count", len(df))
        columns = list(df.columns)
        rows = df.fillna("").to_dict(orient="records")
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif not isinstance(v, (str, int, float, bool, type(None))):
                    r[k] = str(v)
        return {
            "columns": columns,
            "rows": rows,
            "chunk_size": chunk_size,
            "page": page,
            "total": total,
            "total_pages": (total + chunk_size - 1) // chunk_size if chunk_size > 0 else 1,
            "has_next": page * chunk_size < total,
        }
    except Exception as e:
        logger.error(f"内部分块读取异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 内部文件 I/O 端点 ====================

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


@router.get("/internal/file-links")
async def internal_list_file_links(
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """内部文件链接列表端点（无认证，仅供技能执行器子进程本机调用）"""
    from app.models.filelink import FileLink
    _uid = UUID(str(user_id)) if user_id else None
    result = await db.execute(
        select(FileLink).where(FileLink.is_active == True, FileLink.created_by == _uid)
    )
    return [
        {"id": str(f.id), "name": f.name, "path": f.path, "link_type": f.link_type}
        for f in result.scalars().all()
    ]


@router.post("/internal/files/read")
async def internal_read_file(body: dict, db: AsyncSession = Depends(get_db)):
    """内部文件读取端点（无认证，仅供技能执行器子进程本机调用）。
    自动检测格式：txt/md/log/py/json/csv/xlsx → 对应解析"""
    from pathlib import Path
    from app.models.filelink import FileLink

    user_id = body.get("user_id")
    user_id = UUID(str(user_id)) if user_id else None
    file_path = body.get("path", "")

    allowed_dirs = await _collect_allowed_dirs(db, user_id)
    validated = _validate_file_path(file_path, allowed_dirs)
    p = Path(validated)
    if not p.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = p.suffix.lower()
    try:
        if ext in (".txt", ".md", ".log", ".py", ".js", ".ts", ".html", ".xml", ".yml", ".yaml", ".sql", ".csv"):
            if ext == ".csv":
                import pandas as _pd
                df = _pd.read_csv(p)
                return {"format": "csv", "columns": list(df.columns), "rows": df.fillna("").to_dict(orient="records")}
            return {"format": "text", "content": p.read_text(encoding="utf-8")}
        elif ext == ".json":
            return {"format": "json", "content": json.loads(p.read_text(encoding="utf-8"))}
        elif ext in (".xlsx", ".xls"):
            import pandas as _pd
            df = _pd.read_excel(p)
            return {"format": "csv", "columns": list(df.columns), "rows": df.fillna("").to_dict(orient="records")}
        elif ext == ".parquet":
            import pandas as _pd
            df = _pd.read_parquet(p)
            return {"format": "csv", "columns": list(df.columns), "rows": df.fillna("").to_dict(orient="records")}
        elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tiff", ".tif"):
            # 图片/二进制 fail-fast：绝不返回 UTF-8 乱码（会掩盖错误信号，诱导 LLM 把乱码当数据传给 llm_vision）
            raise HTTPException(status_code=400, detail=f"read_file 不支持读取图片文件({ext})。请直接将图片路径传给 llm_vision(image_path, prompt) 进行 OCR/识别。")
        elif ext in (".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"):
            raise HTTPException(status_code=400, detail=f"read_file 不支持读取视频文件({ext})。请使用 extract_video_info(video_path) 提取视频信息，或 extract_keyframes(video_path) 抽取关键帧。")
        else:
            return {"format": "text", "content": p.read_text(encoding="utf-8", errors="replace")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {e}")


@router.post("/internal/files/write")
async def internal_write_file(body: dict, db: AsyncSession = Depends(get_db)):
    """内部文件写入端点（无认证，仅供技能执行器子进程本机调用）。
    自动检测格式：txt/json/csv → 对应序列化"""
    from pathlib import Path
    from app.models.filelink import FileLink
    import json as _json

    user_id = body.get("user_id")
    user_id = UUID(str(user_id)) if user_id else None
    file_path = body.get("path", "")
    data = body.get("data")
    fmt = body.get("format")

    allowed_dirs = await _collect_allowed_dirs(db, user_id)
    validated = _validate_file_path(file_path, allowed_dirs)
    p = Path(validated)
    p.parent.mkdir(parents=True, exist_ok=True)

    ext = p.suffix.lower()
    try:
        if ext == ".json" or fmt == "json":
            p.write_text(_json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        elif ext == ".csv" or fmt == "csv":
            import pandas as _pd
            if isinstance(data, list) and data and isinstance(data[0], dict):
                _pd.DataFrame(data).to_csv(p, index=False, encoding="utf-8-sig")
            else:
                p.write_text(str(data), encoding="utf-8")
        else:
            # 默认文本写入
            if isinstance(data, (dict, list)):
                p.write_text(_json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            else:
                p.write_text(str(data), encoding="utf-8")
        return {"success": True, "path": str(p), "size": p.stat().st_size}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入文件失败: {e}")
