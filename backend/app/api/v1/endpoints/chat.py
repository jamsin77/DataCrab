"""对话API端点"""

import asyncio
import json
import os
from collections import OrderedDict
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from loguru import logger

_active_stream_events: dict[str, asyncio.Event] = {}

from app.core.database import get_db
from app.models.chat import ChatSession, ChatMessage
from app.models.user import User
from app.models.filelink import FileLink
from app.models.datasource import DataSource
from app.schemas.chat import (
    ChatSessionCreate,
    ChatSessionUpdate,
    ChatSessionResponse,
    ChatMessageCreate,
    ChatMessageResponse,
)
from app.api.deps import get_current_user
from app.services.llm import llm_manager
from app.services.agent_config import agent_config
from app.services.agent_utils import estimate_tokens, build_identifier_hint

router = APIRouter()

# 加载助理人格文件
_persona_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_persona_path = os.path.join(_persona_dir, "services", "soul.md")
try:
    with open(_persona_path, "r", encoding="utf-8") as _f:
        ASSISTANT_PERSONA = _f.read().strip()
except FileNotFoundError:
        ASSISTANT_PERSONA = ""


@router.get("/agent/config")
async def get_agent_config():
    """获取Agent配置信息"""
    from app.services.agent_config import agent_config
    return agent_config.to_dict()


# 聊天附件上传
_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data", "uploads",
)
_MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB
_ALLOWED_EXCEL_EXTS = {".xlsx", ".xls"}
_VIRTUAL_DS_NAME = "聊天上传数据"  # 所有聊天上传的 Excel 归一到此虚拟数据源
_VIRTUAL_DS_SOURCE_TAG = "chat_upload_virtual"  # tech_metadata.source 标记


@router.post("/upload")
async def upload_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传 Excel 附件 → 归入「聊天上传数据」虚拟数据源 → 返回元信息。

    限制：仅 .xlsx/.xls，单文件 ≤ 5MB。
    设计：所有上传文件归一到同一个虚拟数据源（mode=files）。
          同名文件上传加时间戳后缀（不覆盖），路径互不相同 → 保留多版本。
          ExcelConnector._resolve_table_name 用最长前缀匹配把 table_name 解析为 (file_path, sheet_name)。
    """
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.datasource import DataSource

    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")
    filename = os.path.basename(file.filename)  # 防路径穿越
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_EXCEL_EXTS:
        raise HTTPException(status_code=400, detail=f"仅支持 Excel 文件 (.xlsx/.xls)，当前后缀: {ext or '无'}")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过 5MB 限制（当前 {len(content)/1024/1024:.1f}MB)")
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    # 同名文件加时间戳后缀，保留多版本不覆盖
    # 销售数据.xlsx → 销售数据_20260817_152630.xlsx → 表名前缀 销售数据_20260817_152630
    base = os.path.splitext(filename)[0]
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    saved_filename = f"{base}_{ts}{ext}"
    user_dir = os.path.join(_UPLOAD_DIR, str(current_user.id))
    os.makedirs(user_dir, exist_ok=True)
    file_path = os.path.join(user_dir, saved_filename)
    with open(file_path, "wb") as f:
        f.write(content)

    # 解析 Excel sheet 名 + 首个 sheet 的列名
    try:
        import pandas as pd
        xls = pd.ExcelFile(file_path)
        sheet_names = list(xls.sheet_names)
        first_df = pd.read_excel(file_path, sheet_name=sheet_names[0], nrows=5)
        columns = [str(c) for c in first_df.columns]
    except Exception as e:
        logger.warning(f"Excel 解析失败 [{filename}]: {e}")
        raise HTTPException(status_code=400, detail=f"Excel 解析失败: {e}")

    table_name_prefix = os.path.splitext(saved_filename)[0]  # 表名前缀 = basename without extension

    # 查找或创建虚拟数据源
    result = await db.execute(
        select(DataSource).where(
            DataSource.name == _VIRTUAL_DS_NAME,
            DataSource.created_by == current_user.id,
            DataSource.is_active == True,
        )
    )
    datasource = result.scalars().first()

    file_meta = {
        "original_filename": filename,
        "saved_filename": saved_filename,
        "file_path": file_path,
        "size_bytes": len(content),
        "sheets": sheet_names,
        "columns": columns,
        "table_name_prefix": table_name_prefix,
        "uploaded_at": ts,
    }

    if datasource is None:
        # 首次上传：创建虚拟数据源
        datasource = DataSource(
            name=_VIRTUAL_DS_NAME,
            type="excel",
            connection_config={"mode": "files", "file_paths": [file_path]},
            tech_metadata={
                "source": _VIRTUAL_DS_SOURCE_TAG,
                "files": [file_meta],
            },
            is_virtual=True,
            created_by=current_user.id,
        )
        db.add(datasource)
        await db.flush()

        # 自动创建 FileLink，授权沙箱访问上传目录
        from app.api.v1.endpoints.datasource import _auto_create_file_link
        await _auto_create_file_link(db, datasource, current_user.id)
    else:
        # 已有虚拟数据源：追加新文件路径（路径不同=新版本）
        cfg = dict(datasource.connection_config or {})
        cfg.setdefault("mode", "files")
        file_paths = list(cfg.get("file_paths", []))
        file_paths.append(file_path)  # 时间戳不同路径必不同
        cfg["file_paths"] = file_paths
        datasource.connection_config = cfg
        flag_modified(datasource, "connection_config")

        tech = dict(datasource.tech_metadata or {})
        files_meta = list(tech.get("files", []))
        files_meta.append(file_meta)
        tech["files"] = files_meta
        datasource.tech_metadata = tech
        flag_modified(datasource, "tech_metadata")
        await db.flush()

    await db.commit()

    logger.info(f"聊天附件上传成功: {filename} -> {saved_filename} (虚拟数据源 {datasource.id}, prefix={table_name_prefix}, sheets={sheet_names})")

    return {
        "datasource_id": str(datasource.id),
        "name": _VIRTUAL_DS_NAME,
        "filename": filename,
        "table_name_prefix": table_name_prefix,
        "size_bytes": len(content),
        "sheets": sheet_names,
        "columns": columns,
    }


def _match_datasource_names(sources, user_message: str):
    """从用户消息中匹配数据源名称，返回匹配到的数据源列表。

    匹配规则（从严不扩大范围）：
    1. 数据源名完整出现在用户消息中（精确匹配）
    2. 英文名按 _/- 拆分后所有关键词都出现（全匹配）
    不做宽松兜底（如 2 字组合），避免"数据"等常见词误匹配所有数据源。
    """
    if not user_message:
        return []
    msg_lower = user_message.lower()
    matched = []
    for ds in sources:
        ds_name_lower = ds.name.lower()
        if ds_name_lower in msg_lower:
            matched.append(ds)
            continue
        name_keywords = ds_name_lower.replace('_', ' ').replace('-', ' ').split()
        if name_keywords and all(kw in msg_lower for kw in name_keywords):
            matched.append(ds)
            continue
    return matched


async def build_datasource_context(
    db: AsyncSession,
    user_id: UUID,
    user_message: str = "",
) -> tuple:
    result = await db.execute(
        select(DataSource).where(
            DataSource.is_active == True,
            DataSource.created_by == user_id,
        )
    )
    sources = result.scalars().all()

    if not sources:
        return '\n## 可用数据源\n当前没有配置任何数据源。建议用户先在【数据源管理】页面添加数据源。\n', "", []

    matched_sources = _match_datasource_names(sources, user_message)

    # 匹配到多个时，取消息中最后提到的数据源（"最近一次提到的才是分析的"）
    if len(matched_sources) > 1:
        def _last_pos(ds):
            return user_message.lower().rfind(ds.name.lower())
        matched_sources.sort(key=_last_pos, reverse=True)
        matched_sources = [matched_sources[0]]

    # 未匹配到：只列名不预览，提示 Agent 问用户要分析哪个数据源
    if not matched_sources:
        lines = ["\n## 可用数据源"]
        lines.append(f"用户已配置 {len(sources)} 个数据源：")
        for ds in sources:
            lines.append(f"- {ds.name}（类型: {ds.type}, ID: {ds.id}）")
        lines.append("")
        lines.append("> 用户消息未明确提到任何数据源名。请先确认用户要分析哪个数据源，再调用工具查询，不要自行猜测。")
        return "\n".join(lines), "", []

    # 匹配到：展示详情 + 预览数据
    display_sources = matched_sources
    lines = ["\n## 可用数据源（工具的知识库）"]
    lines.append(f"以下 {len(display_sources)} 个数据源已配置，可供用户分析：\n")

    for ds in display_sources:
        cfg = ds.connection_config or {}
        lines.append(f"### {ds.name}（类型: {ds.type}, ID: {ds.id}）")
        if ds.type in ("mysql", "postgres"):
            lines.append(f"- 主机: {cfg.get('host', 'N/A')}:{cfg.get('port', 'N/A')}")
            lines.append(f"- 数据库: {cfg.get('database', 'N/A')}")
        elif ds.type == "csv":
            lines.append(f"- 文件路径: {cfg.get('file_path', 'N/A')}")
        elif ds.type == "excel":
            lines.append(f"- 文件路径: {cfg.get('file_path', 'N/A')}")
            lines.append(f"- 工作表: {cfg.get('sheet_name', 'N/A')}")
        elif ds.type in ("obs", "s3"):
            lines.append(f"- Endpoint: {cfg.get('endpoint', 'N/A')}")
            lines.append(f"- Bucket: {cfg.get('bucket', 'N/A')}")
            lines.append(f"- 基础路径: {cfg.get('base_path', '/')}")
        elif ds.type == "hadoop":
            lines.append(f"- 地址: {cfg.get('host', 'N/A')}:{cfg.get('port', 'N/A')}")
            lines.append(f"- 基础路径: {cfg.get('base_path', '/')}")

        if ds.table_metadata:
            table_names = [t.table_name for t in ds.table_metadata if t.table_name]
            if table_names:
                lines.append(f"- 包含的表/文件: {', '.join(table_names[:10])}")
                if len(table_names) > 10:
                    lines.append(f"  ...还有 {len(table_names) - 10} 个")

        lines.append("")

    # 预览作为一次性 user message 注入（不进 system prompt），保持 system 字节稳定命中 prefix cache
    data_previews, matched_names = await _query_datasource_previews(display_sources, user_message)

    return "\n".join(lines), data_previews, matched_names


async def _build_selected_datasource_context(ds, table_name: str, user_message: str) -> tuple:
    """用户从 data_suggestion 选择了数据源+表，只构建数据源和表名上下文（不预查数据）。
    返回 (datasource_context, data_preview)——data_preview 固定为空，Agent 用工具自行查询。"""
    lines = ["\n## 用户选择的数据源"]
    lines.append(f"数据源名: {ds.name}")
    lines.append(f"数据源 ID: {ds.id}")
    lines.append(f"数据源类型: {ds.type}")
    if table_name:
        lines.append(f"用户选择的表: {table_name}")
    lines.append("")
    lines.append("> 请用 query_table_data / get_table_schema / execute_sql 等工具按 datasource_id 查询此数据源的数据。")
    return "\n".join(lines), ""


async def _query_datasource_previews(sources, user_message: str):
    """查询数据源的实际数据预览。sources 已由 _match_datasource_names 过滤。
    返回 (preview_text, matched_names)"""
    from app.services.connectors import get_connector
    if not sources or not user_message:
        return "", []

    msg_lower = user_message.lower()
    previews = []

    import re
    all_keywords = ["全部", "所有", "所有数据", "全部数据", "all", "完整", "整个"]
    want_all = any(kw in msg_lower for kw in all_keywords)
    page_match = re.search(r'第\s*(\d+)\s*页|page\s*(\d+)', msg_lower)
    next_match = re.search(r'下\s*一\s*页|下一页|next\s*page|更多', msg_lower)

    page = 1
    if page_match:
        page = int(page_match.group(1) or page_match.group(2))
    elif next_match:
        page = 2

    page_size = 100 if want_all else 20

    for ds in sources:

        # 全局预览上限：多个数据源预览总和不超过 8000 字
        if sum(len(p) for p in previews) >= 8000:
            previews.append("> [更多数据源未预览，请单独查询]")
            break

        try:
            connector = get_connector(ds.type, ds.connection_config or {})
            schema = await connector.get_schema()

            if not schema:
                await connector.close()
                continue

            first_table = schema[0].get("table_name", "")
            if not first_table:
                await connector.close()
                continue

            total_rows = 0
            try:
                stats = await connector.get_table_stats(first_table)
                total_rows = stats.get("row_count", 0)
            except Exception:
                pass

            logger.info(f"查询数据源 [{ds.name}] 表 {first_table} page={page} size={page_size}")

            df = await connector.get_table_data(first_table, page=page, page_size=page_size)
            await connector.close()

            if df.empty:
                continue

            row_count = len(df)
            col_count = len(df.columns)
            total_pages = (total_rows + page_size - 1) // page_size if total_rows > 0 else 0

            preview_text = f"\n### 【实时数据】{ds.name} - {first_table}\n"
            preview_text += f"总行数: {total_rows}, 总列数: {col_count}, 当前第 {page} 页"
            if total_pages > 0:
                preview_text += f", 共 {total_pages} 页"
                preview_text += "\n> 提示: 如需翻页请说\"显示第2页\"，想看更多请说\"显示所有数据\"；如需排序、筛选、统计等操作请直接告诉我"
            preview_text += f"\n\n显示 {row_count} 行:\n\n"

            headers = list(df.columns)
            preview_text += "| " + " | ".join(str(h)[:15] for h in headers) + " |\n"
            preview_text += "| " + " | ".join("---" for _ in headers) + " |\n"

            for _, row in df.iterrows():
                vals = [str(v)[:30] if v is not None and str(v) != "nan" else "" for v in row]
                preview_text += "| " + " | ".join(vals) + " |\n"

            previews.append(_cap_preview(preview_text, note="数据较多，已截断预览；如需完整数据请明确说明"))
            logger.info(f"数据源 [{ds.name}] 已查询: {row_count}/{total_rows}行 x {col_count}列")

        except Exception as e:
            logger.warning(f"查询数据源 [{ds.name}] 数据失败: {e}")
            continue

    if previews:
        matched_names = [ds.name for ds in sources]
        return "\n## 实时数据查询结果\n以下是从数据源中查询到的真实数据，请基于这些数据回答用户问题：\n" + "\n".join(previews), matched_names
    return "", []


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建对话会话"""
    session = ChatSession(
        user_id=current_user.id,
        title=request.title or "新会话",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取会话列表"""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取会话详情"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return session


@router.put("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: UUID,
    request: ChatSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新会话"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    session.title = request.title
    await db.flush()
    await db.refresh(session)
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除会话"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    # 显式删除关联消息（SQLite 默认不启用外键级联）
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    await db.delete(session)
    # 清理内存中的历史摘要缓存
    _sid = str(session_id)
    _HISTORY_SUMMARIES.pop(_sid, None)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def list_messages(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取消息列表"""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或无权访问")
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return result.scalars().all()


@router.patch("/messages/{message_id}/metadata")
async def update_message_metadata(
    message_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新消息的 metadata 字段（前端流式结束后持久化临时字段：model/reasoning/executingMsgs/suggestion 等）"""
    result = await db.execute(
        select(ChatMessage).join(ChatSession, ChatMessage.session_id == ChatSession.id).where(
            ChatMessage.id == message_id,
            ChatSession.user_id == current_user.id,
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在或无权访问")
    msg.meta = body
    await db.commit()
    return {"success": True}


@router.delete("/sessions/{session_id}/messages", status_code=status.HTTP_204_NO_CONTENT)
async def clear_messages(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清空会话的所有消息（保留会话本身）"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    await db.execute(
        delete(ChatMessage).where(ChatMessage.session_id == session_id)
    )


# ==================== 上下文压缩 ====================
# 会话历史压缩缓存：session_id -> (摘要文本, 已摘要覆盖到的最后一条消息id)
# OrderedDict LRU：限制 100 个会话，防止长期运行内存泄漏
_HISTORY_SUMMARIES: OrderedDict = OrderedDict()
_HISTORY_SUMMARIES_MAX = 100
HISTORY_CHAR_BUDGET = 6000   # 历史原文总 token 估算超过此值则触发压缩
HISTORY_KEEP_RECENT = 6      # 压缩时保留最近 N 条原文
PREVIEW_CHAR_LIMIT = 5000    # 单个数据源预览的字符上限



async def _compress_history(history_messages: list, session_id: str) -> list:
    """历史消息分层压缩：总量超预算时，旧消息摘要 + 最近若干条原文。

    改进（L）：标识符机械抽取——压缩时提取表名/数据源ID/UUID，保留在摘要中。
    改进（M）：使用 CJK 感知的 token 估算替代字符数。
    改进（本轮）：摘要角色统一为 user（与 compact_messages 一致）；LRU 限制防泄漏；
                  旧消息截断 500→1000 保留更多上下文。
    """
    if not history_messages:
        return []
    total = sum(estimate_tokens(m.content or "") for m in history_messages)
    if total <= HISTORY_CHAR_BUDGET or len(history_messages) <= HISTORY_KEEP_RECENT:
        return [{"role": m.role, "content": m.content} for m in history_messages]

    keep = history_messages[-HISTORY_KEEP_RECENT:]
    older = history_messages[:-HISTORY_KEEP_RECENT]
    last_older_id = str(older[-1].id) if older else ""

    cached = _HISTORY_SUMMARIES.get(session_id)
    summary = None
    if cached and cached[1] == last_older_id:
        summary = cached[0]
        _HISTORY_SUMMARIES.move_to_end(session_id)
    else:
        try:
            older_text = "\n".join(f"[{m.role}] {(m.content or '')[:1000]}" for m in older)
            id_hint = build_identifier_hint(older_text)
            summary = await llm_manager.chat_with_messages(
                [
                    {"role": "system", "content": "你是对话摘要助手。把多轮对话压缩成简洁中文要点摘要，保留关键数据、结论和上下文，不要寒暄，限300字以内。" + id_hint},
                    {"role": "user", "content": older_text[:8000]},
                ],
                temperature=0.2,
                max_tokens=400,
            )
            _HISTORY_SUMMARIES[session_id] = (summary, last_older_id)
            while len(_HISTORY_SUMMARIES) > _HISTORY_SUMMARIES_MAX:
                _HISTORY_SUMMARIES.popitem(last=False)
        except Exception as e:
            logger.warning(f"历史摘要生成失败，降级为仅保留近期: {e}")
            summary = None

    compressed: list = []
    if summary:
        summary_text = f"## 先前对话摘要\n{summary}"
        if keep and keep[0].role == "user":
            compressed.append({"role": "user", "content": summary_text + "\n\n" + (keep[0].content or "")})
            compressed.extend({"role": m.role, "content": m.content} for m in keep[1:])
        else:
            compressed.append({"role": "user", "content": summary_text})
            compressed.extend({"role": m.role, "content": m.content} for m in keep)
    else:
        compressed.extend({"role": m.role, "content": m.content} for m in keep)
    return compressed


def _cap_preview(text: str, limit: int = PREVIEW_CHAR_LIMIT, note: str = "") -> str:
    """截断过长的数据预览，避免撑爆上下文"""
    if text and len(text) > limit:
        return text[:limit] + (f"\n\n> {note}" if note else "")
    return text


@router.post("/stream")
async def stream_response(
    request: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式响应 - 支持多智能体路由"""

    async def generate():
        session_id = str(request.session_id)
        cancel_event = asyncio.Event()
        _active_stream_events[session_id] = cancel_event
        full_response = ""

        try:
            # 加载会话上下文（源/目标数据源和表，跨消息持久化）
            _sess_result = await db.execute(
                select(ChatSession).where(ChatSession.id == request.session_id, ChatSession.user_id == current_user.id)
            )
            _session_obj = _sess_result.scalar_one_or_none()
            _session_ctx = _session_obj.context if _session_obj and _session_obj.context else {}

            user_message = ChatMessage(
                session_id=request.session_id,
                role="user",
                content=request.content,
            )
            db.add(user_message)
            await db.flush()

            # 刷新会话 updated_at，使会话列表按最近活跃排序
            from sqlalchemy import update as sa_update
            await db.execute(
                sa_update(ChatSession).where(ChatSession.id == request.session_id)
                .values(updated_at=datetime.utcnow())
            )
            await db.flush()

            # 设置当前用户的 LLM 配置（API Key 按用户隔离，contextvars 请求级生效）
            from app.services.llm import init_user_llm_context, llm_manager
            await init_user_llm_context(current_user.id)

            await llm_manager.initialize()

            history_result = await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == request.session_id,
                    ChatMessage.id != user_message.id,
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(20)
            )
            history_messages = list(history_result.scalars().all())
            history_messages.reverse()

            # 优先处理附件：用户上传了数据文件 → 直接用虚拟数据源，不推断
            # 无附件时才走文本推断（build_datasource_context）
            # 用户从 data_suggestion 选择了数据 → 直接用选中的数据源，跳过名称匹配和表匹配
            datasource_context = ""
            data_preview = ""
            matched_names = []
            _user_msg = request.content
            _attachment_matched = False

            # 如果前端没传 selected_datasource_id，但会话上下文有源数据 → 从 context 恢复
            # 是否跳过数据表匹配由 classify_message 的 keep_data 决定（line 812 处统一判断）
            if not request.selected_datasource_id and _session_ctx.get("source_datasource_id"):
                from app.models.datasource import DataSource as _DS
                _ctx_src = await db.execute(select(_DS).where(_DS.id == UUID(_session_ctx["source_datasource_id"]), _DS.is_active == True))
                _ctx_ds = _ctx_src.scalars().first()
                if _ctx_ds:
                    _can_use_ctx = (
                        _ctx_ds.created_by == current_user.id
                        or current_user.is_superuser
                    )
                    if _can_use_ctx:
                        datasource_context, data_preview = await _build_selected_datasource_context(
                            _ctx_ds, _session_ctx.get("source_table_name"), request.content
                        )
                        matched_names = [_ctx_ds.name]
                        _attachment_matched = True

            if request.selected_datasource_id:
                # 用户选择了数据，直接用选中的数据源构建上下文
                from app.services.permission_service import check_permission
                from app.models.datasource import DataSource as _DS
                sel_result = await db.execute(
                    select(_DS).where(
                        _DS.id == UUID(request.selected_datasource_id),
                        _DS.is_active == True,
                    )
                )
                sel_ds = sel_result.scalars().first()
                if sel_ds:
                    # 检查权限
                    _can_use = (
                        sel_ds.created_by == current_user.id
                        or current_user.is_superuser
                        or await check_permission(db, current_user.id, "datasource", sel_ds.id, "use",
                            is_owner=(sel_ds.created_by == current_user.id), is_superuser=current_user.is_superuser)
                    )
                    if _can_use:
                        datasource_context, data_preview = await _build_selected_datasource_context(
                            sel_ds, request.selected_table_name, request.content
                        )
                        matched_names = [sel_ds.name]
                        _attachment_matched = True
                        # 存源数据到会话上下文
                        _session_ctx["source_datasource_id"] = str(sel_ds.id)
                        _session_ctx["source_datasource_name"] = sel_ds.name
                        _session_ctx["source_table_name"] = request.selected_table_name
                        # 跳过表匹配（用户已选）
                        if "tables" not in (request.skip_steps or []):
                            request.skip_steps = (request.skip_steps or []) + ["tables"]

            if request.attachments and not _attachment_matched:
                from app.models.datasource import DataSource as _DS
                att_result = await db.execute(
                    select(_DS).where(
                        _DS.name == _VIRTUAL_DS_NAME,
                        _DS.created_by == current_user.id,
                        _DS.is_active == True,
                    )
                )
                virtual_ds = att_result.scalars().first()
                if virtual_ds:
                    _tech = virtual_ds.tech_metadata or {}
                    _all_files = _tech.get("files", [])
                    _att_files = [f for f in _all_files if f.get("original_filename") in request.attachments]
                    if _att_files:
                        att_lines = [
                            f"【本次对话附件】用户上传了以下文件到「{_VIRTUAL_DS_NAME}」数据源，请用以下工具按 datasource_id 查询：",
                            f"数据源名: {_VIRTUAL_DS_NAME}",
                            f"datasource_id: {virtual_ds.id}",
                            f"数据源类型: excel（文件型，非 DB）",
                            "",
                            "可用工具：",
                            "- query_table_data: 分页拉数据（page/page_size，默认100行）",
                            "- get_table_schema: 查看表结构",
                            "- execute_sql: 用 DuckDB 在内存跑 SQL（支持 SELECT/WHERE/GROUP BY/JOIN，"
                            "  统计/聚合优先用此工具，比翻页拉数据再算高效）",
                            "",
                            "本次上传文件：",
                        ]
                        for _f in _att_files:
                            _prefix = _f.get("table_name_prefix", "")
                            _sheets = _f.get("sheets") or []
                            att_lines.append(f"- 文件: {_f.get('original_filename', '')}")
                            att_lines.append(f"  表名前缀: {_prefix}")
                            if _sheets:
                                att_lines.append(f"  工作表(sheets): {', '.join(_sheets)}")
                                att_lines.append(f"  完整表名: {_prefix}_{_sheets[0]}（其余工作表类似，前缀_工作表名）")
                                _example_tbl = f'{_prefix}_{_sheets[0]}'
                                att_lines.append(f"  SQL 示例: execute_sql(datasource_id=\"{virtual_ds.id}\", sql=\"SELECT COUNT(*) FROM \\\"{_example_tbl}\\\"\")")
                        att_lines.append("如未指定具体工作表，默认查询第一个工作表。")
                        _user_msg = "\n".join(att_lines) + f"\n\n---\n\n{request.content}"
                        matched_names = [_VIRTUAL_DS_NAME]
                        _attachment_matched = True

            # 无附件或附件未匹配到文件时，才推断数据源
            if not _attachment_matched:
                datasource_context, data_preview, matched_names = await build_datasource_context(
                    db, current_user.id, request.content
                )
                _user_msg = f"{data_preview}\n\n---\n\n{request.content}" if data_preview else request.content

            # 提交用户消息，释放 SQLite 写锁（避免流式期间 database is locked）
            if _session_obj:
                _session_obj.context = dict(_session_ctx)
            await db.commit()

            # ===== 一次 LLM 调用判断消息类型 + 技能/流程/数据匹配 =====
            from app.services.chat_router import classify_message
            from app.services.llm import llm_manager
            from app.core.database import async_session as _new_session
            yield f"data: {json.dumps({'type': 'executing', 'message': '正在理解您的需求...'}, ensure_ascii=False)}\n\n"
            _msg_type, _keep_data, _classify_events = await classify_message(request.content, _session_ctx)
            for _ev in _classify_events:
                if _ev.get("type") in ("model", "thinking"):
                    yield f"data: {json.dumps(_ev, ensure_ascii=False)}\n\n"
            _type_label = {"analysis": "数据分析", "processing": "数据处理", "chat": "智能对话"}.get(_msg_type, _msg_type)
            yield f"data: {json.dumps({'type': 'executing', 'message': f'已识别：{_type_label}，正在为您准备...'}, ensure_ascii=False)}\n\n"
            logger.info(f"[match] session={session_id} msg_type={_msg_type} keep_data={_keep_data} skip={request.skip_match} content={request.content[:50]!r}")
            # LLM 判定继续用当前已选数据 → 跳过数据表匹配；判定换数据 → 清除 context 旧数据
            if _keep_data and "tables" not in (request.skip_steps or []):
                request.skip_steps = (request.skip_steps or []) + ["tables"]
            if not _keep_data and not request.selected_datasource_id:
                _session_ctx.pop("source_datasource_id", None)
                _session_ctx.pop("source_datasource_name", None)
                _session_ctx.pop("source_table_name", None)
                _session_ctx.pop("target_datasource_id", None)
                _session_ctx.pop("target_datasource_name", None)
                _session_ctx.pop("target_table_name", None)
                if _session_obj:
                    _session_obj.context = dict(_session_ctx)
            if not request.skip_match and _msg_type != "chat":
                from app.services.match_service import (
                    llm_match_tables, llm_match_skills, llm_match_pipelines, llm_match_target_tables,
                )
                from app.models.datasource import DataSource, TableMetadata
                from app.models.skill import Skill
                from app.models.pipeline import Pipeline
                from app.services.permission_service import check_permission
                from app.core.database import async_session as _new_session

                _skip_steps = request.skip_steps or []

                _match_error = None
                try:
                    # Step 0: 匹配数据表（LLM 判断）
                    if "tables" not in _skip_steps:
                        _ds_names = [ds.name for ds in (await db.execute(select(DataSource))).scalars().all() if ds.name and ds.name in request.content]
                        _ds_hint = f"正在{'、'.join(_ds_names)}中查找相关数据表..." if _ds_names else "正在为您查找相关数据表..."
                        yield f"data: {json.dumps({'type': 'executing', 'message': _ds_hint}, ensure_ascii=False)}\n\n"
                        if cancel_event.is_set():
                            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                            return
                        table_matches, _table_events = await llm_match_tables(request.content, db)
                        for _ev in _table_events:
                            if _ev.get("type") in ("model", "thinking"):
                                yield f"data: {json.dumps(_ev, ensure_ascii=False)}\n\n"
                        logger.info(f"[match] tables: {len(table_matches)} matched")
                        if table_matches:
                            _names = [m.get('table_name','') for _,_,m in table_matches[:3]]
                            _hint = '找到 {} 个相关数据表: {}'.format(len(table_matches), ', '.join(_names))
                            yield f"data: {json.dumps({'type': 'executing', 'message': _hint}, ensure_ascii=False)}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'executing', 'message': '未找到直接匹配的数据表'}, ensure_ascii=False)}\n\n"
                        table_results = []
                        for tid, score, meta in table_matches:
                            ds_id = meta.get("data_source_id", "")
                            table_name = meta.get("table_name", "")
                            if not ds_id or not table_name:
                                continue
                            try:
                                ds_result = await db.execute(select(DataSource).where(DataSource.id == UUID(ds_id)))
                            except (ValueError, Exception):
                                continue
                            ds = ds_result.scalar_one_or_none()
                            if not ds:
                                continue
                            can_use = (
                                ds.created_by == current_user.id
                                or current_user.is_superuser
                                or await check_permission(db, current_user.id, "datasource", ds.id, "use", is_owner=(ds.created_by == current_user.id), is_superuser=current_user.is_superuser)
                            )
                            owner_name = None
                            owner_email = None
                            if not can_use and ds.created_by:
                                u_result = await db.execute(select(User).where(User.id == ds.created_by))
                                u = u_result.scalar_one_or_none()
                                if u:
                                    owner_name = u.display_name or u.username
                                    owner_email = u.email
                            table_results.append({
                                "type": "table",
                                "datasource_id": str(ds.id),
                                "datasource_name": ds.name,
                                "table_name": table_name,
                                "row_count": meta.get("row_count"),
                                "column_count": meta.get("column_count"),
                                "similarity": score,
                                "can_use": can_use,
                                "owner_name": owner_name,
                                "owner_email": owner_email,
                            })
                        if table_results:
                            async with _new_session() as save_session:
                                save_session.add(ChatMessage(
                                    session_id=request.session_id, role="assistant",
                                    content="检测到数据已存在，请选择操作。",
                                ))
                                await save_session.commit()
                            yield f"data: {json.dumps({'type': 'data_suggestion', 'matches': table_results}, ensure_ascii=False, default=str)}\n\n"
                            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                            return

                    # Step 0.5: 目标表匹配（仅 processing 类，源数据已确定）
                    _src_ds_id = request.selected_datasource_id or _session_ctx.get("source_datasource_id")
                    if _msg_type == "processing" and "target" not in _skip_steps and _src_ds_id:
                        # 如果 context 已有目标信息 → 跳过
                        if _session_ctx.get("target_datasource_id"):
                            _skip_steps.append("target")
                        else:
                            yield f"data: {json.dumps({'type': 'executing', 'message': '正在检查目标数据源...'}, ensure_ascii=False)}\n\n"
                            if cancel_event.is_set():
                                yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                                return
                            target_matches, target_ds_names, _target_events = await llm_match_target_tables(
                                request.content, db, source_datasource_id=_src_ds_id
                            )
                            for _ev in _target_events:
                                if _ev.get("type") in ("model", "thinking"):
                                    yield f"data: {json.dumps(_ev, ensure_ascii=False)}\n\n"

                            if not target_ds_names:
                                # 用户没提到目标数据源 → 提醒
                                _hint = "请指定目标数据源（结果要写入哪个数据源），例如：导入到「证件OCR识别」数据源"
                                yield f"data: {json.dumps({'type': 'content', 'content': _hint}, ensure_ascii=False)}\n\n"
                                async with _new_session() as save_session:
                                    save_session.add(ChatMessage(
                                        session_id=request.session_id, role="assistant",
                                        content=_hint,
                                    ))
                                    await save_session.commit()
                                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                                return

                            if target_matches:
                                # 目标表已存在 → 提示已处理过 + 存 context
                                logger.info(f"[match] target tables: {len(target_matches)} matched (已处理过)")
                                target_results = []
                                for tid, score, meta in target_matches:
                                    _ds_id = meta.get("data_source_id", "")
                                    _tname = meta.get("table_name", "")
                                    if not _ds_id or not _tname:
                                        continue
                                    try:
                                        _ds_result = await db.execute(select(DataSource).where(DataSource.id == UUID(_ds_id)))
                                    except (ValueError, Exception):
                                        continue
                                    _ds = _ds_result.scalar_one_or_none()
                                    if not _ds:
                                        continue
                                    _can_use = (
                                        _ds.created_by == current_user.id
                                        or current_user.is_superuser
                                        or await check_permission(db, current_user.id, "datasource", _ds.id, "use",
                                            is_owner=(_ds.created_by == current_user.id), is_superuser=current_user.is_superuser)
                                    )
                                    target_results.append({
                                        "type": "target_table",
                                        "datasource_id": str(_ds.id),
                                        "datasource_name": _ds.name,
                                        "table_name": _tname,
                                        "row_count": meta.get("row_count"),
                                        "column_count": meta.get("column_count"),
                                        "similarity": score,
                                        "can_use": _can_use,
                                    })
                                if target_results:
                                    # 存目标数据到会话上下文
                                    _session_ctx["target_datasource_id"] = target_results[0]["datasource_id"]
                                    _session_ctx["target_datasource_name"] = target_results[0]["datasource_name"]
                                    _session_ctx["target_table_name"] = target_results[0]["table_name"]
                                    async with _new_session() as save_session:
                                        save_session.add(ChatMessage(
                                            session_id=request.session_id, role="assistant",
                                            content="检测到目标表已存在，可能已处理过，请选择操作。",
                                            meta={"suggestion": {"type": "target_suggestion", "matches": target_results}},
                                        ))
                                        # 同步存 context 到 session
                                        _sess = await save_session.get(ChatSession, request.session_id)
                                        if _sess:
                                            _sess.context = dict(_session_ctx)
                                        await save_session.commit()
                                    yield f"data: {json.dumps({'type': 'target_suggestion', 'matches': target_results}, ensure_ascii=False, default=str)}\n\n"
                                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                                    return

                            yield f"data: {json.dumps({'type': 'executing', 'message': '目标表不存在，将创建新表'}, ensure_ascii=False)}\n\n"

                    # Step 1: 匹配流程（LLM 判断）
                    if "pipelines" not in _skip_steps:
                        yield f"data: {json.dumps({'type': 'executing', 'message': '正在查找匹配的处理流程...'}, ensure_ascii=False)}\n\n"
                        if cancel_event.is_set():
                            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                            return
                        pipe_matches, _pipe_events = await llm_match_pipelines(request.content, db, _msg_type)
                        for _ev in _pipe_events:
                            if _ev.get("type") in ("model", "thinking"):
                                yield f"data: {json.dumps(_ev, ensure_ascii=False)}\n\n"
                        logger.info(f"[match] pipelines: {len(pipe_matches)} matched")
                        if pipe_matches:
                            yield f"data: {json.dumps({'type': 'executing', 'message': f'找到 {len(pipe_matches)} 个匹配的流程'}, ensure_ascii=False)}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'executing', 'message': '未找到匹配的流程'}, ensure_ascii=False)}\n\n"
                        pipe_results = []
                        for pid, score in pipe_matches:
                            try:
                                p_result = await db.execute(select(Pipeline).where(Pipeline.id == UUID(pid), Pipeline.is_active == True))
                            except (ValueError, Exception):
                                continue
                            p = p_result.scalar_one_or_none()
                            if not p:
                                continue
                            can_use = (
                                p.created_by == current_user.id
                                or p.visibility == "public"
                                or current_user.is_superuser
                                or await check_permission(db, current_user.id, "pipeline", p.id, "use", is_owner=(p.created_by == current_user.id), is_superuser=current_user.is_superuser)
                            )
                            owner_name = None
                            owner_email = None
                            if not can_use and p.created_by:
                                u_result = await db.execute(select(User).where(User.id == p.created_by))
                                u = u_result.scalar_one_or_none()
                                if u:
                                    owner_name = u.display_name or u.username
                                    owner_email = u.email
                            pipe_results.append({
                                "type": "pipeline",
                                "id": str(p.id),
                                "name": p.display_name or p.name,
                                "description": p.description or "",
                                "similarity": score,
                                "can_use": can_use,
                                "owner_name": owner_name,
                                "owner_email": owner_email,
                            })
                        if pipe_results:
                            async with _new_session() as save_session:
                                save_session.add(ChatMessage(
                                    session_id=request.session_id, role="assistant",
                                    content="检测到匹配的流程，请选择操作。",
                                ))
                                await save_session.commit()
                            yield f"data: {json.dumps({'type': 'skill_suggestion', 'matches': pipe_results}, ensure_ascii=False, default=str)}\n\n"
                            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                            return

                    # Step 2: 匹配技能（LLM 判断）
                    if "skills" not in _skip_steps:
                        yield f"data: {json.dumps({'type': 'executing', 'message': '正在查找匹配的技能...'}, ensure_ascii=False)}\n\n"
                        if cancel_event.is_set():
                            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                            return
                        skill_matches, _skill_events = await llm_match_skills(request.content, db, _msg_type)
                        for _ev in _skill_events:
                            if _ev.get("type") in ("model", "thinking"):
                                yield f"data: {json.dumps(_ev, ensure_ascii=False)}\n\n"
                        logger.info(f"[match] skills: {len(skill_matches)} matched")
                        if skill_matches:
                            yield f"data: {json.dumps({'type': 'executing', 'message': f'找到 {len(skill_matches)} 个匹配的技能'}, ensure_ascii=False)}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'executing', 'message': '未找到匹配的技能'}, ensure_ascii=False)}\n\n"
                        skill_results = []
                        for sid, score in skill_matches:
                            try:
                                s_result = await db.execute(select(Skill).where(Skill.id == UUID(sid)))
                            except (ValueError, Exception):
                                continue
                            s = s_result.scalar_one_or_none()
                            if not s:
                                continue
                            can_use = (
                                s.created_by == current_user.id
                                or s.visibility == "public"
                                or current_user.is_superuser
                                or await check_permission(db, current_user.id, "skill", s.id, "use", is_owner=(s.created_by == current_user.id), is_superuser=current_user.is_superuser)
                            )
                            owner_name = None
                            owner_email = None
                            if not can_use and s.created_by:
                                u_result = await db.execute(select(User).where(User.id == s.created_by))
                                u = u_result.scalar_one_or_none()
                                if u:
                                    owner_name = u.display_name or u.username
                                    owner_email = u.email
                            skill_results.append({
                                "type": "skill",
                                "id": str(s.id),
                                "name": s.display_name or s.name,
                                "description": s.description or "",
                                "similarity": score,
                                "can_use": can_use,
                                "owner_name": owner_name,
                                "owner_email": owner_email,
                            })
                        if skill_results:
                            async with _new_session() as save_session:
                                save_session.add(ChatMessage(
                                    session_id=request.session_id, role="assistant",
                                    content="检测到匹配的技能，请选择操作。",
                                ))
                                await save_session.commit()
                            yield f"data: {json.dumps({'type': 'skill_suggestion', 'matches': skill_results}, ensure_ascii=False, default=str)}\n\n"
                            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                            return

                    # Step 3: 无匹配 → 提示一下，继续走 Agent
                    _no_match_hint = "未找到匹配的流程或技能，正在直接为您处理。\n\n"
                    yield f"data: {json.dumps({'type': 'content', 'content': _no_match_hint}, ensure_ascii=False)}\n\n"
                    full_response += _no_match_hint
                except Exception as e:
                    _err = f"⚠️ 匹配检测出错：{e}\n\n"
                    logger.error(f"[match] 匹配出错，停止处理: {e}")
                    yield f"data: {json.dumps({'type': 'content', 'content': _err}, ensure_ascii=False)}\n\n"
                    full_response += _err
                    async with _new_session() as save_session:
                        save_session.add(ChatMessage(
                            session_id=request.session_id, role="assistant",
                            content=full_response,
                        ))
                        await save_session.commit()
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                    return

            # 路由：用 classify_message 的结果，不再重复调 LLM
            from app.services.multi_agent import ensure_agent_runtime, AgentMessage, HandoffReason

            _agent_name = "data_analyst" if _msg_type == "analysis" else "data_processor"
            logger.info(f"[route] session={session_id} msg_type={_msg_type} agent={_agent_name}")

            # 注入已知的数据上下文到 user message（避免 Agent 重复推断）
            _ctx_lines = []
            if _session_ctx.get("source_datasource_name"):
                _ctx_lines.append(f"源数据源: {_session_ctx['source_datasource_name']}")
            if _session_ctx.get("source_table_name"):
                _ctx_lines.append(f"源表: {_session_ctx['source_table_name']}")
            if _session_ctx.get("target_datasource_name"):
                _ctx_lines.append(f"目标数据源: {_session_ctx['target_datasource_name']}")
            if _session_ctx.get("target_table_name"):
                _ctx_lines.append(f"目标表: {_session_ctx['target_table_name']}")
            if _ctx_lines:
                _user_msg = f"【已确定的数据上下文】\n" + "\n".join(_ctx_lines) + f"\n\n---\n\n{_user_msg}"

            runtime = ensure_agent_runtime()

            trace_id = str(uuid4())
            compressed_history = await _compress_history(history_messages, session_id)
            context = {
                "db": db,
                "user_id": current_user.id,
                "datasource_context": datasource_context,
                "persona": ASSISTANT_PERSONA,
                "session_id": session_id,
                "history": compressed_history,
                "has_preinjected_data": bool(data_preview),
                "session_ctx": _session_ctx,
            }

            message = AgentMessage(
                from_agent="user",
                to_agent=_agent_name,
                reason=HandoffReason.DELEGATE,
                payload={"user_message": _user_msg, "content": _user_msg},
                context=context,
                trace_id=trace_id,
            )

            agen = runtime.run(_agent_name, message, context).__aiter__()
            while True:
                if cancel_event.is_set():
                    # 保存已收到的部分内容，避免刷新后回复丢失
                    from app.core.database import async_session as _new_session
                    async with _new_session() as save_session:
                        partial = full_response or ""
                        if partial:
                            partial += "\n\n*[已停止]*"
                        else:
                            partial = "*[已停止]*"
                        save_session.add(ChatMessage(
                            session_id=request.session_id, role="assistant",
                            content=partial,
                        ))
                        await save_session.commit()
                    yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                    return

                # SSE 保活：20 秒无事件则发 ping，防止 network error
                fut = asyncio.ensure_future(agen.__anext__())
                done, pending = await asyncio.wait({fut}, timeout=20)
                if not done:
                    yield f"data: {json.dumps({'type': 'ping'}, ensure_ascii=False)}\n\n"
                    done, pending = await asyncio.wait({fut}, timeout=120)
                    if not done:
                        fut.cancel()
                        yield f"data: {json.dumps({'type': 'error', 'content': '等待 Agent 响应超时'}, ensure_ascii=False)}\n\n"
                        return
                try:
                    event = fut.result()
                except StopAsyncIteration:
                    break
                except Exception as e:
                    logger.error(f"Agent 执行异常: {e}", exc_info=True)
                    yield f"data: {json.dumps({'type': 'error', 'content': f'响应出错: {e}'}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                    return

                if event.get("type") == "agent_switch":
                    yield f"data: {json.dumps({'type': 'agent_switch', 'agent': event['agent'], 'display_name': event.get('display_name',''), 'reason': event['reason'], 'reason_display': event.get('reason_display','')}, ensure_ascii=False)}\n\n"
                elif event.get("type") == "content":
                    content = event.get("content", "")
                    full_response += content
                    yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
                elif event.get("type") == "tool_result":
                    yield f"data: {json.dumps({'type': 'tool_result', 'content': event.get('content', '')[:2000]}, ensure_ascii=False)}\n\n"
                elif event.get("type") == "done":
                    result = event.get("result") or {}
                    _done_content = result.get("content", "") if isinstance(result, dict) else ""
                    if _done_content and _done_content.strip() not in full_response.strip():
                        full_response += _done_content
                        yield f"data: {json.dumps({'type': 'content', 'content': _done_content}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                else:
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

            # 用新 session 保存 AI 消息（避免长流式期间锁住 DB）
            from app.core.database import async_session as _new_session
            async with _new_session() as save_session:
                ai_message = ChatMessage(
                    session_id=request.session_id,
                    role="assistant",
                    content=full_response,
                )
                save_session.add(ai_message)
                await save_session.commit()

            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            # 保存已收到的部分内容，避免刷新后回复丢失
            from app.core.database import async_session as _new_session
            async with _new_session() as save_session:
                partial = full_response or ""
                if partial:
                    partial += "\n\n*[已停止]*"
                else:
                    partial = "*[已停止]*"
                save_session.add(ChatMessage(
                    session_id=request.session_id, role="assistant",
                    content=partial,
                ))
                await save_session.commit()
            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            import traceback as _tb
            err_detail = f"{e}\n\n{ _tb.format_exc()}"
            logger.error(f"流式响应失败: {err_detail}")
            # 保存已收到的部分内容 + 错误信息，避免前端刷新 DB 后回复消失
            from app.core.database import async_session as _new_session
            async with _new_session() as save_session:
                partial = full_response or ""
                if partial:
                    partial += "\n\n"
                partial += f"❌ 响应出错: {e}"
                ai_message = ChatMessage(
                    session_id=request.session_id,
                    role="assistant",
                    content=partial,
                )
                save_session.add(ai_message)
                await save_session.commit()
            yield f"data: {json.dumps({'type': 'error', 'content': err_detail}, ensure_ascii=False)}\n\n"
        finally:
            _active_stream_events.pop(session_id, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/stop")
async def stop_generation(session_id: str = Query(..., description="要停止的会话ID")):
    event = _active_stream_events.get(session_id)
    if event:
        event.set()
        return {"message": "已停止生成"}
    return {"message": "没有活跃的生成任务"}


# ===== 自然语言数据处理 =====
