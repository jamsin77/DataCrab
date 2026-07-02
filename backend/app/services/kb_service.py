"""文档知识库服务：解析 → 切片 → 嵌入 → ChromaDB 存取 → 检索"""

import os
import hashlib
from typing import List, Dict, Any, Optional

from loguru import logger

from app.services.llm import llm_manager

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KB_DOC_DIR = os.path.join(_BACKEND_DIR, "data", "kb_docs")
KB_CHROMA_DIR = os.path.join(_BACKEND_DIR, "data", "kb_chroma")
os.makedirs(KB_DOC_DIR, exist_ok=True)
os.makedirs(KB_CHROMA_DIR, exist_ok=True)

KB_COLLECTION = "datacrab_kb"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

_chroma_client = None
_chroma_collection = None


def _get_collection():
    global _chroma_client, _chroma_collection
    if _chroma_collection is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=KB_CHROMA_DIR)
        _chroma_collection = _chroma_client.get_or_create_collection(name=KB_COLLECTION)
    return _chroma_collection


# ---------- 文本抽取 ----------
def extract_text(file_path: str, file_type: str) -> str:
    ft = (file_type or "").lower().lstrip(".")
    if ft in ("txt", "md", "markdown", "csv", "json", "log", "py", "js", "ts", "html", "xml", "yml", "yaml"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if ft in ("xlsx", "xls"):
        import pandas as pd
        sheets = pd.read_excel(file_path, sheet_name=None)
        parts = []
        for name, df in sheets.items():
            parts.append(f"## Sheet: {name}\n" + df.to_string(index=False))
        return "\n\n".join(parts)
    if ft == "pdf":
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                return "\n\n".join((p.extract_text() or "") for p in pdf.pages)
        except ImportError:
            pass
        try:
            import fitz
            doc = fitz.open(file_path)
            return "\n\n".join(page.get_text() for page in doc)
        except ImportError:
            raise ValueError("PDF 解析需要安装 pdfplumber 或 PyMuPDF（fitz）")
    if ft == "docx":
        try:
            import docx
            d = docx.Document(file_path)
            return "\n".join(p.text for p in d.paragraphs)
        except ImportError:
            raise ValueError("DOCX 解析需要安装 python-docx")
    if ft == "doc":
        raise ValueError("旧版 .doc 暂不支持，请转换为 .docx 或 .txt")
    # 兜底：按文本读
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        raise ValueError(f"无法解析文件: {e}")


# ---------- 切片 ----------
def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Dict[str, Any]]:
    """按段落聚合切片，返回 [{content, char_start, char_end, location}]"""
    if not text or not text.strip():
        return []
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    chunks: List[Dict[str, Any]] = []
    buf = ""
    buf_start = 0
    idx = 0
    pos = 0
    for p in paragraphs:
        if not buf:
            buf_start = pos
        buf = (buf + "\n\n" + p) if buf else p
        while len(buf) >= size:
            cut = buf[:size]
            chunks.append({
                "content": cut,
                "char_start": buf_start,
                "char_end": buf_start + size,
                "location": f"片段 {idx + 1}",
            })
            idx += 1
            buf = buf[size - overlap:] if overlap < size else ""
            buf_start = buf_start + size - (overlap if overlap < size else 0)
        pos += len(p) + 2
    if buf.strip():
        chunks.append({
            "content": buf,
            "char_start": buf_start,
            "char_end": buf_start + len(buf),
            "location": f"片段 {idx + 1}",
        })
    return chunks


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ---------- 导入 ----------
async def ingest_document(doc_id: str, file_path: str, file_type: str, name: str, user_id: str) -> Dict[str, Any]:
    """解析、切片、嵌入并写入 Chroma 与 DB。返回 {chunk_count, error}"""
    from app.core.database import async_session
    from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
    from sqlalchemy import select, update

    try:
        text = extract_text(file_path, file_type)
    except Exception as e:
        async with async_session() as db:
            await db.execute(
                update(KnowledgeDocument).where(KnowledgeDocument.id == doc_id).values(status="failed", error=str(e))
            )
            await db.commit()
        return {"chunk_count": 0, "error": str(e)}

    chunks = chunk_text(text)
    if not chunks:
        async with async_session() as db:
            await db.execute(
                update(KnowledgeDocument).where(KnowledgeDocument.id == doc_id).values(status="failed", error="文档无有效文本")
            )
            await db.commit()
        return {"chunk_count": 0, "error": "文档无有效文本"}

    collection = _get_collection()
    chunk_rows = []
    ids, embeddings, documents, metadatas = [], [], [], []
    for i, ch in enumerate(chunks):
        try:
            emb = await llm_manager.embed(ch["content"])
        except Exception as e:
            logger.warning(f"嵌入失败 chunk {i}: {e}")
            continue
        cid = f"{doc_id}_{i}"
        ids.append(cid)
        embeddings.append(emb)
        documents.append(ch["content"])
        metadatas.append({
            "document_id": str(doc_id),
            "doc_name": name,
            "chunk_index": i,
            "location": ch["location"],
            "user_id": str(user_id),
        })
        chunk_rows.append({
            "document_id": doc_id,
            "chunk_index": i,
            "content": ch["content"],
            "location": ch["location"],
            "char_start": ch["char_start"],
            "char_end": ch["char_end"],
            "chroma_id": cid,
        })

    if ids:
        collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    async with async_session() as db:
        db.add_all([KnowledgeChunk(**r) for r in chunk_rows])
        await db.execute(
            update(KnowledgeDocument).where(KnowledgeDocument.id == doc_id).values(
                status="ready",
                chunk_count=len(chunk_rows),
                content_hash=_content_hash(text),
            )
        )
        await db.commit()
    return {"chunk_count": len(chunk_rows), "error": None}


# ---------- 检索（证据链） ----------
async def search(query: str, user_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
    if not query or not query.strip():
        return []
    q_emb = await llm_manager.embed(query)
    collection = _get_collection()
    try:
        res = collection.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            where={"user_id": str(user_id)},
        )
    except Exception as e:
        logger.warning(f"KB 检索失败: {e}")
        return []

    out = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for cid, doc, meta, dist in zip(ids, docs, metas, dists):
        out.append({
            "chroma_id": cid,
            "content": doc,
            "document_id": meta.get("document_id"),
            "doc_name": meta.get("doc_name"),
            "chunk_index": meta.get("chunk_index"),
            "location": meta.get("location"),
            "score": round(1 - float(dist), 4) if dist is not None else None,  # 距离越小越相似
        })
    return out


# ---------- 删除 ----------
async def delete_document(doc_id: str):
    from app.core.database import async_session
    from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
    from sqlalchemy import select, delete as sa_delete

    async with async_session() as db:
        result = await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return None
        file_path = doc.file_path
        await db.execute(sa_delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id))
        await db.delete(doc)
        await db.commit()

    # 删除 Chroma 中该文档的向量
    try:
        collection = _get_collection()
        collection.delete(where={"document_id": str(doc_id)})
    except Exception as e:
        logger.warning(f"删除 Chroma 向量失败: {e}")

    # 删除磁盘文件
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass
    return True
