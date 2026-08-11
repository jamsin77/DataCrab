"""文档知识库API端点"""

import os
from uuid import UUID, uuid4
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.services import kb_service

router = APIRouter()


def _doc_to_dict(doc: KnowledgeDocument) -> dict:
    return {
        "id": str(doc.id),
        "name": doc.name,
        "file_type": doc.file_type,
        "size_bytes": doc.size_bytes,
        "chunk_count": doc.chunk_count,
        "status": doc.status,
        "error": doc.error,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("/documents")
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的知识库文档"""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.created_by == current_user.id)
        .order_by(KnowledgeDocument.created_at.desc())
    )
    return [_doc_to_dict(d) for d in result.scalars().all()]


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传文档到知识库（自动解析、切片、嵌入）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")
    file_type = os.path.splitext(file.filename)[1].lower().lstrip(".")
    supported = {"txt", "md", "markdown", "csv", "json", "log", "py", "js", "ts", "html", "xml", "yml", "yaml", "xlsx", "xls", "pdf", "docx"}
    if file_type not in supported:
        raise HTTPException(status_code=400, detail=f"暂不支持该格式: .{file_type}")

    doc_id = uuid4()
    doc_dir = os.path.join(kb_service.KB_DOC_DIR, str(doc_id))
    os.makedirs(doc_dir, exist_ok=True)
    file_path = os.path.join(doc_dir, file.filename)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    doc = KnowledgeDocument(
        id=doc_id,
        name=file.filename,
        file_type=file_type,
        file_path=file_path,
        size_bytes=len(content),
        status="processing",
        created_by=current_user.id,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    # 提交后异步/同步导入（此处同步执行以简化）
    await db.commit()

    from app.services.llm import init_user_llm_context
    await init_user_llm_context(current_user.id)
    result = await kb_service.ingest_document(
        str(doc_id), file_path, file_type, file.filename, str(current_user.id)
    )
    if result.get("error"):
        logger.warning(f"文档导入失败 {file.filename}: {result['error']}")

    # 重新读取最新状态
    fresh = await db.get(KnowledgeDocument, doc_id)
    return _doc_to_dict(fresh)


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除文档及其切片与向量"""
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.created_by == current_user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    await db.commit()  # 释放后再调 service（service 内自建 session）
    await kb_service.delete_document(str(doc_id))
    return {"ok": True}


@router.get("/documents/{doc_id}/chunks")
async def list_chunks(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查看文档切片（证据链详情）"""
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.created_by == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="文档不存在")
    result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == doc_id)
        .order_by(KnowledgeChunk.chunk_index)
    )
    return [
        {
            "id": str(c.id),
            "chunk_index": c.chunk_index,
            "content": c.content,
            "location": c.location,
            "char_start": c.char_start,
            "char_end": c.char_end,
        }
        for c in result.scalars().all()
    ]


@router.post("/search")
async def search_documents(
    body: dict,
    current_user: User = Depends(get_current_user),
):
    """语义检索知识库（返回带证据链的切片）"""
    query = (body or {}).get("query", "").strip()
    top_k = (body or {}).get("top_k", 5) or 5
    if not query:
        raise HTTPException(status_code=400, detail="请输入检索内容")
    from app.services.llm import init_user_llm_context
    await init_user_llm_context(current_user.id)
    results = await kb_service.search(query, str(current_user.id), top_k=max(1, min(int(top_k), 20)))
    return {"query": query, "results": results}
