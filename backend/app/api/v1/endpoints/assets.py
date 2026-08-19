"""资产导出/导入端点 — 一键迁移技能/算子/流程/LLM配置/连接器/规则。

API Key / 密码 不导出，导入后用户手动填。
"""
import json
import zipfile
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_current_user
from app.models.user import User
from app.services.asset_io import build_export_zip, import_from_zip, read_zip_manifest

router = APIRouter()


SUPPORTED_TYPES = ["skills", "operators", "pipelines", "llm_config", "custom_extensions", "schedules"]


class ExportRequest(BaseModel):
    types: List[str] = SUPPORTED_TYPES


@router.get("/counts")
async def asset_counts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """各资产数量统计（导出页显示用）——只统计当前用户 manage 的资产"""
    from sqlalchemy import select, func
    from app.models.skill import Skill
    from app.models.operator import Operator
    from app.models.pipeline import Pipeline
    from app.models.custom_extension import LLMProvider, CustomConnector
    from app.models.schedule import Schedule

    uid = current_user.id
    counts = {}
    counts["skills"] = (await db.execute(select(func.count()).select_from(Skill).where(Skill.created_by == uid))).scalar() or 0
    counts["operators"] = (await db.execute(select(func.count()).select_from(Operator).where(Operator.created_by == uid))).scalar() or 0
    counts["pipelines"] = (await db.execute(select(func.count()).select_from(Pipeline).where(Pipeline.created_by == uid, Pipeline.is_builtin == False, Pipeline.is_active == True))).scalar() or 0
    counts["llm_config"] = (await db.execute(select(func.count()).select_from(LLMProvider).where(LLMProvider.created_by == uid, LLMProvider.is_active == True))).scalar() or 0
    counts["custom_extensions"] = (await db.execute(select(func.count()).select_from(CustomConnector).where(CustomConnector.created_by == uid, CustomConnector.is_active == True))).scalar() or 0
    counts["schedules"] = (await db.execute(select(func.count()).select_from(Schedule).where(Schedule.created_by == uid))).scalar() or 0
    return counts


@router.post("/export")
async def export_assets(
    req: ExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出选中资产为 zip。API Key 不导出。调度只导出当前用户创建的。"""
    zip_bytes = await build_export_zip(req.types, db, current_user.id)
    ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"datacrab_{ts}.zip"
    return StreamingResponse(
        __import__("io").BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传 zip 后预览：显示 manifest（各类型数量），不执行导入。"""
    zip_bytes = await file.read()
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="请上传 .zip 文件")
    try:
        manifest = await read_zip_manifest(zip_bytes)
    except (zipfile.BadZipFile, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"无效的 zip 文件: {e}")
    if not manifest:
        raise HTTPException(status_code=422, detail="zip 中缺少 manifest.json，可能不是 DataCrab 导出的资产包")
    return manifest


@router.post("/import")
async def import_assets(
    file: UploadFile = File(...),
    types: str = Form(...),
    overwrite_types: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导入 zip 资产。types 是逗号分隔的资产类型，overwrite_types 是逗号分隔的要覆盖的类型（空=全部跳过）。"""
    import logging
    logger = logging.getLogger(__name__)
    zip_bytes = await file.read()
    logger.info(f"[资产导入] file={file.filename} size={len(zip_bytes)} types={types} overwrite_types={overwrite_types}")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="请上传 .zip 文件")
    type_list = [t.strip() for t in types.split(",") if t.strip()]
    overwrite_set = set(t.strip() for t in overwrite_types.split(",") if t.strip())
    try:
        result = await import_from_zip(zip_bytes, type_list, db, current_user.id, overwrite_set)
    except (zipfile.BadZipFile, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"无效的 zip 文件: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[资产导入] 导入失败 file={file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")
    await db.commit()
    return result
