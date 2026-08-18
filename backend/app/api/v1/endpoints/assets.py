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


SUPPORTED_TYPES = ["skills", "operators", "pipelines", "llm_config", "custom_extensions", "rules", "schedules"]


class ExportRequest(BaseModel):
    types: List[str] = SUPPORTED_TYPES


@router.get("/counts")
async def asset_counts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """各资产数量统计（导出页显示用）"""
    from sqlalchemy import select, func
    from app.models.skill import Skill
    from app.models.operator import Operator
    from app.models.pipeline import Pipeline
    from app.models.custom_extension import LLMProvider, CustomConnector
    from app.models.schedule import Schedule
    from pathlib import Path

    counts = {}
    counts["skills"] = (await db.execute(select(func.count()).select_from(Skill))).scalar() or 0
    counts["operators"] = (await db.execute(select(func.count()).select_from(Operator))).scalar() or 0
    counts["pipelines"] = (await db.execute(select(func.count()).select_from(Pipeline))).scalar() or 0
    counts["llm_config"] = (await db.execute(select(func.count()).select_from(LLMProvider).where(LLMProvider.is_active == True))).scalar() or 0
    counts["custom_extensions"] = (await db.execute(select(func.count()).select_from(CustomConnector).where(CustomConnector.is_active == True))).scalar() or 0
    rules_dir = Path(settings.SKILL_STORAGE_PATH).parent / "rules"
    counts["rules"] = sum(1 for n in ("data_standards", "data_quality", "data_security") if (rules_dir / f"{n}.md").exists())
    counts["schedules"] = (await db.execute(select(func.count()).select_from(Schedule).where(Schedule.created_by == current_user.id))).scalar() or 0
    return counts


@router.post("/export")
async def export_assets(
    req: ExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出选中资产为 zip。API Key 不导出。调度只导出当前用户创建的。"""
    zip_bytes = await build_export_zip(req.types, db, current_user.id)
    ts = __import__("datetime").datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"datacrab_assets_{ts}.zip"
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
    overwrite: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导入 zip 资产。types 是逗号分隔的资产类型，可选择只导入部分。"""
    zip_bytes = await file.read()
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="请上传 .zip 文件")
    type_list = [t.strip() for t in types.split(",") if t.strip()]
    try:
        result = await import_from_zip(zip_bytes, type_list, db, current_user.id, overwrite)
    except (zipfile.BadZipFile, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"无效的 zip 文件: {e}")
    await db.commit()
    return result
