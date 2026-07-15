"""数据源管理API端点"""

from uuid import UUID
from typing import Optional

from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.services.permission_service import get_accessible_resource_ids, check_permission

from app.core.database import get_db
from app.models.datasource import DataSource
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
    return datasource


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
    """获取数据源树形结构"""
    result = await db.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据源不存在")

    try:
        connector = _get_connector(datasource.type, datasource.connection_config or {})
        schema = await connector.get_schema()
        await connector.close()

        tree_nodes = []
        for item in schema:
            table_name = item.get("table_name", "")
            table_type = item.get("table_type", "")
            node = TreeNode(
                id=f"{datasource_id}:{table_name}",
                label=table_name,
                type=table_type,
                metadata=item,
            )
            tree_nodes.append(node)

        return tree_nodes
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
        return await mgr.write_table(
            str(datasource_id),
            table_name,
            body.get("records", []),
            **kwargs,
        )
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
