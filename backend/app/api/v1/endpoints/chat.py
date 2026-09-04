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
from app.services.tool_registry import execute_tool, get_tool_schemas

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
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
    "data", "uploads",
)
_MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB
_ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tiff"}
_VIRTUAL_DS_NAME = "聊天上传数据"  # 所有聊天上传的文件归一到此虚拟数据源
_VIRTUAL_DS_SOURCE_TAG = "chat_upload_virtual"  # tech_metadata.source 标记


@router.post("/upload")
async def upload_attachment(
    file: UploadFile = File(...),
    session_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传附件 → 归入「聊天上传数据」虚拟数据源 → 返回元信息。

    支持两种类型：
    - Excel (.xlsx/.xls)：解析 sheet 名 + 列名，作为数据表查询
    - 图片 (.png/.jpg/.jpeg/.bmp/.webp/.gif/.tiff)：存为文件，供 llm_vision 使用

    限制：单文件 ≤ 5MB。
    设计：所有上传文件归一到同一个虚拟数据源（mode=files）。
          同名文件上传加时间戳后缀（不覆盖），路径互不相同 → 保留多版本。
    """
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.datasource import DataSource

    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")
    filename = os.path.basename(file.filename)  # 防路径穿越
    ext = os.path.splitext(filename)[1].lower()
    is_image = ext in _ALLOWED_IMAGE_EXTS

    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过 5MB 限制（当前 {len(content)/1024/1024:.1f}MB)")
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    # 同名文件加时间戳后缀，保留多版本不覆盖
    base = os.path.splitext(filename)[0]
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    saved_filename = f"{base}_{ts}{ext}"
    user_dir = os.path.join(_UPLOAD_DIR, str(current_user.id))
    os.makedirs(user_dir, exist_ok=True)
    file_path = os.path.join(user_dir, saved_filename)
    with open(file_path, "wb") as f:
        f.write(content)

    table_name_prefix = saved_filename  # 表名 = 完整文件名（带后缀），唯一标识

    if is_image:
        sheet_names = []
        columns = []
    elif ext in (".xlsx", ".xls"):
        # Excel：解析 sheet 名 + 首个 sheet 的列名
        try:
            import pandas as pd
            xls = pd.ExcelFile(file_path)
            sheet_names = list(xls.sheet_names)
            first_df = pd.read_excel(file_path, sheet_name=sheet_names[0], nrows=5)
            columns = [str(c) for c in first_df.columns]
        except Exception as e:
            logger.warning(f"Excel 解析失败 [{filename}]: {e}")
            sheet_names = []
            columns = []
    else:
        # 其他文件类型（CSV/PDF/Word/视频等）：不解析，由 Agent 按需用工具处理
        sheet_names = []
        columns = []

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
        "is_image": is_image,
    }

    if datasource is None:
        # 首次上传：创建虚拟数据源
        datasource = DataSource(
            name=_VIRTUAL_DS_NAME,
            type="generic_file",
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

    # 上传后立即把 selectedData 持久化到 session context（刷新不丢）
    if session_id:
        try:
            from app.models.chat import ChatSession as _CS
            _sess = await db.execute(
                select(_CS).where(_CS.id == UUID(session_id), _CS.user_id == current_user.id)
            )
            _sess_obj = _sess.scalar_one_or_none()
            if _sess_obj:
                _ctx = dict(_sess_obj.context or {})
                _ctx["source_datasource_id"] = str(datasource.id)
                _ctx["source_datasource_name"] = _VIRTUAL_DS_NAME
                if not is_image:
                    _ctx["source_data_name"] = table_name_prefix
                    _ctx["source_filename"] = saved_filename
                _sess_obj.context = _ctx
                await db.commit()
        except Exception as e:
            logger.warning(f"上传后持久化 session context 失败: {e}")

    logger.info(f"聊天附件上传成功: {filename} -> {saved_filename} (虚拟数据源 {datasource.id}, prefix={table_name_prefix}, sheets={sheet_names})")

    return {
        "datasource_id": str(datasource.id),
        "name": _VIRTUAL_DS_NAME,
        "filename": filename,
        "table_name_prefix": table_name_prefix,
        "size_bytes": len(content),
        "sheets": sheet_names,
        "columns": columns,
        "is_image": is_image,
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


@router.patch("/sessions/{session_id}/context", response_model=ChatSessionResponse)
async def update_session_context(
    session_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新会话上下文（前端选数据/目标表后即时持久化）"""
    logger.info(f"[context-patch] session={session_id} payload={payload}")
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    ctx = dict(session.context or {})
    ctx.update(payload)
    session.context = ctx
    session.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(session)
    logger.info(f"[context-patch] saved, context={session.context}")
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
    current_user: User = Depends(get_current_user),
):
    """流式响应 - 支持多智能体路由"""

    def _get_ready_params(ctx: dict) -> list:
        """已确定的参数列表"""
        params = []
        if ctx.get("source_datasource_name"):
            params.append(f"源数据源: {ctx['source_datasource_name']}")
        if ctx.get("source_data_name"):
            params.append(f"源表: {ctx['source_data_name']}")
        if ctx.get("target_datasource_name"):
            params.append(f"目标数据源: {ctx['target_datasource_name']}")
        if ctx.get("target_data_name"):
            params.append(f"目标表: {ctx['target_data_name']}")
        _wmode = ctx.get("target_write_mode", "")
        if _wmode:
            _wmode_label = {"overwrite": "覆盖", "append": "追加", "direct": "直接使用", "create": "新建表"}.get(_wmode, _wmode)
            params.append(f"写入策略: {_wmode_label}（if_table_exists={_wmode}）")
        if ctx.get("last_skill_name") or ctx.get("last_pipeline_name"):
            params.append(f"技能: {ctx.get('last_skill_name') or ctx.get('last_pipeline_name')}")
        return params

    def _get_missing_params(ctx: dict, msg_type: str) -> list:
        """缺失的参数列表"""
        missing = []
        if not ctx.get("source_datasource_id") and not ctx.get("source_datasource_name"):
            missing.append("源数据源")
        if not ctx.get("source_data_name") and not ctx.get("source_table_name"):
            missing.append("源数据表")
        if msg_type == "processing":
            if not ctx.get("target_datasource_id") and not ctx.get("target_datasource_name"):
                missing.append("目标数据源")
            if not ctx.get("target_data_name") and not ctx.get("target_table_name"):
                missing.append("目标数据表")
        return missing

    def _build_params_hint(ctx: dict, msg_type: str) -> str:
        """构建参数提示文本（已确定 + 缺失）"""
        ready = _get_ready_params(ctx)
        missing = _get_missing_params(ctx, msg_type)
        hint = ""
        if ready:
            hint += "✅ 已确定参数：" + "，".join(ready)
        if missing:
            if hint:
                hint += "\n\n"
            hint += "⚠️ 还缺：" + "、".join(missing) + "，请补充"
        return hint

    async def generate():
        session_id = str(request.session_id)
        cancel_event = asyncio.Event()
        _active_stream_events[session_id] = cancel_event
        full_response = ""

        try:
            from app.core.database import async_session as _stream_session
            # ===== 段1：会话加载 + 存消息 + 数据源查询 + commit（独立 session，commit 后释放）=====
            async with _stream_session() as db:
                # 加载会话上下文（源/目标数据源和表，跨消息持久化）
                _sess_result = await db.execute(
                    select(ChatSession).where(ChatSession.id == request.session_id, ChatSession.user_id == current_user.id)
                )
                _session_obj = _sess_result.scalar_one_or_none()
                _session_ctx = _session_obj.context if _session_obj and _session_obj.context else {}

                # 向后兼容：旧 session_ctx 用 source_table_name/target_table_name，迁移到新字段名
                if "source_table_name" in _session_ctx and "source_data_name" not in _session_ctx:
                    _session_ctx["source_data_name"] = _session_ctx.pop("source_table_name")
                if "target_table_name" in _session_ctx and "target_data_name" not in _session_ctx:
                    _session_ctx["target_data_name"] = _session_ctx.pop("target_table_name")

                # directExecute 时不存用户消息（前端复用已有消息，不弹新的）
                _user_message_id = None
                if not request.direct_execute:
                    user_message = ChatMessage(
                        session_id=request.session_id,
                        role="user",
                        content=request.content,
                    )
                    db.add(user_message)
                    await db.flush()
                    _user_message_id = user_message.id

                # 刷新会话 updated_at，使会话列表按最近活跃排序
                from sqlalchemy import update as sa_update
                await db.execute(
                    sa_update(ChatSession).where(ChatSession.id == request.session_id)
                    .values(updated_at=datetime.utcnow())
                )
                await db.flush()

                # 设置当前用户的 LLM 配置（API Key 按用户隔离，contextvars 请求级生效）
                from app.services.llm import init_user_llm_context, llm_manager
                _llm_cfg = await init_user_llm_context(current_user.id)

                if not _llm_cfg:
                    _err_msg = "❌ 未配置大模型，请在「系统设置 → 大模型管理」中配置 API Key 和模型后重试。"
                    yield f"data: {json.dumps({'type': 'content', 'content': _err_msg}, ensure_ascii=False)}\n\n"
                    full_response = _err_msg
                    async with _stream_session() as save_session:
                        save_session.add(ChatMessage(
                            session_id=request.session_id, role="assistant",
                            content=full_response,
                        ))
                        await save_session.commit()
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                    return

                await llm_manager.initialize()

                history_result = await db.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.session_id == request.session_id,
                        *([] if request.direct_execute else [ChatMessage.id != _user_message_id]),
                    )
                    .order_by(ChatMessage.created_at.desc())
                    .limit(20)
                )
                history_messages = list(history_result.scalars().all())
                history_messages.reverse()

                # 优先处理附件：用户上传了数据文件 → 直接用虚拟数据源，不推断
                # 用户从 data_suggestion 选择了数据 → 直接用选中的数据源
                datasource_context = ""
                data_preview = ""
                matched_names = []
                _user_msg = request.content
                _attachment_matched = False

                # 用户选择了数据源（前端传 selected_datasource_id）
                if request.selected_datasource_id:
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
                        _can_use = (
                            sel_ds.created_by == current_user.id
                            or current_user.is_superuser
                            or await check_permission(db, current_user.id, "datasource", sel_ds.id, "use",
                                is_owner=(sel_ds.created_by == current_user.id), is_superuser=current_user.is_superuser)
                        )
                        if _can_use:
                            # 虚拟数据源（聊天上传）需要注入图片/数据文件附件提示
                            if sel_ds.name == _VIRTUAL_DS_NAME:
                                _tech = sel_ds.tech_metadata or {}
                                _all_files = _tech.get("files", [])
                                _sel_prefix = request.selected_table_name or ""
                                _att_files = [f for f in _all_files if f.get("table_name_prefix") == _sel_prefix] if _sel_prefix else (_all_files[-1:] if _all_files else [])
                                if _att_files:
                                    _image_files = [f for f in _att_files if f.get("is_image")]
                                    _data_files = [f for f in _att_files if not f.get("is_image")]
                                    att_lines = []
                                    if _data_files:
                                        att_lines.extend([
                                            f"【本次对话附件】用户上传了以下文件到「{_VIRTUAL_DS_NAME}」数据源，请用以下工具按 datasource_id 查询：",
                                            f"数据源名: {_VIRTUAL_DS_NAME}",
                                            f"datasource_id: {sel_ds.id}",
                                            f"数据源类型: generic_file（文件型，非 DB）",
                                            "",
                                            "可用工具：",
                                            "- query_table_data / get_table_schema / execute_sql",
                                            "",
                                            "本次上传文件：",
                                        ])
                                        for _f in _data_files:
                                            _prefix = _f.get("table_name_prefix", "")
                                            _sheets = _f.get("sheets") or []
                                            att_lines.append(f"- 文件: {_f.get('original_filename', '')}")
                                            att_lines.append(f"  表名前缀: {_prefix}")
                                            if _sheets:
                                                att_lines.append(f"  工作表(sheets): {', '.join(_sheets)}")
                                                att_lines.append(f"  完整表名: {_prefix}_{_sheets[0]}")
                                    if _image_files:
                                        att_lines.append("")
                                        att_lines.append("【图片附件】用户上传了以下图片，请用 llm_vision 工具分析图片内容：")
                                        att_lines.append(f"datasource_id: {sel_ds.id}")
                                        for _f in _image_files:
                                            _img_path = _f.get("file_path", "")
                                            _img_name = _f.get("original_filename", "")
                                            att_lines.append(f"- 图片: {_img_name}")
                                            att_lines.append(f"  图片路径(file_path): {_img_path}")
                                            att_lines.append(f"  调用示例: call_tool(\"llm_vision\", image_path=\"{_img_path}\", prompt=\"请识别图片中的所有文字和数据\")")
                                        att_lines.append("用 call_tool(\"llm_vision\", image_path=..., prompt=...) 识别图片内容后，给出分析结论。")
                                    if att_lines:
                                        _user_msg = "\n".join(att_lines) + f"\n\n---\n\n{request.content}"
                            else:
                                datasource_context, data_preview = await _build_selected_datasource_context(
                                    sel_ds, request.selected_table_name, request.content
                                )
                            matched_names = [sel_ds.name]
                            _attachment_matched = True
                            _session_ctx["source_datasource_id"] = str(sel_ds.id)
                            _session_ctx["source_datasource_name"] = sel_ds.name
                            _session_ctx["source_data_name"] = request.selected_table_name

                # 用户选择了目标表（前端从 target_suggestion 选择后带上）
                if request.target_datasource_id:
                    from app.models.datasource import DataSource as _DS
                    _tgt_sel = await db.execute(
                        select(_DS).where(_DS.id == UUID(request.target_datasource_id), _DS.is_active == True)
                    )
                    _tgt_ds = _tgt_sel.scalars().first()
                    if _tgt_ds:
                        _session_ctx["target_datasource_id"] = str(_tgt_ds.id)
                        _session_ctx["target_datasource_name"] = _tgt_ds.name
                        _session_ctx["target_data_name"] = request.target_data_name
                        _session_ctx["target_filename"] = request.target_data_name
                        if request.target_write_mode:
                            _session_ctx["target_write_mode"] = request.target_write_mode

                # 用户选择了技能/流程（前端从 skill_suggestion 选择后带上）
                if request.selected_skill_id:
                    if request.selected_skill_type == "pipeline":
                        _session_ctx["last_pipeline_id"] = request.selected_skill_id
                        _session_ctx["last_pipeline_name"] = request.selected_skill_name or ""
                    else:
                        _session_ctx["last_skill_id"] = request.selected_skill_id
                        _session_ctx["last_skill_name"] = request.selected_skill_name or ""

                # 附件处理：用户上传文件后 selectedData 设了虚拟数据源
                if request.selected_datasource_id and not _attachment_matched:
                    from app.models.datasource import DataSource as _DS
                    att_result = await db.execute(
                        select(_DS).where(
                            _DS.id == UUID(request.selected_datasource_id),
                            _DS.is_active == True,
                        )
                    )
                    virtual_ds = att_result.scalars().first()
                    if virtual_ds and virtual_ds.name == _VIRTUAL_DS_NAME:
                        _tech = virtual_ds.tech_metadata or {}
                        _all_files = _tech.get("files", [])
                        # 用 table_name_prefix 匹配用户选的文件（selected_table_name 就是 table_name_prefix）
                        _sel_prefix = request.selected_table_name or ""
                        _att_files = [f for f in _all_files if f.get("table_name_prefix") == _sel_prefix] if _sel_prefix else _all_files[-1:] if _all_files else []
                        if _att_files:
                            # 图片和数据文件分开处理
                            _image_files = [f for f in _att_files if f.get("is_image")]
                            _data_files = [f for f in _att_files if not f.get("is_image")]
                            att_lines = []

                            if _data_files:
                                att_lines.extend([
                                    f"【本次对话附件】用户上传了以下文件到「{_VIRTUAL_DS_NAME}」数据源，请用以下工具按 datasource_id 查询：",
                                    f"数据源名: {_VIRTUAL_DS_NAME}",
                                    f"datasource_id: {virtual_ds.id}",
                                    f"数据源类型: generic_file（文件型，非 DB）",
                                    "",
                                    "可用工具：",
                                    "- query_table_data: 分页拉数据（page/page_size，默认100行）",
                                    "- get_table_schema: 查看表结构",
                                    "- execute_sql: 用 DuckDB 在内存跑 SQL（支持 SELECT/WHERE/GROUP BY/JOIN，"
                                    "  统计/聚合优先用此工具，比翻页拉数据再算高效）",
                                    "",
                                    "本次上传文件：",
                                ])
                                for _f in _data_files:
                                    _prefix = _f.get("table_name_prefix", "")
                                    _sheets = _f.get("sheets") or []
                                    att_lines.append(f"- 文件: {_f.get('original_filename', '')}")
                                    att_lines.append(f"  表名前缀: {_prefix}")
                                    if _sheets:
                                        att_lines.append(f"  工作表(sheets): {', '.join(_sheets)}")
                                        att_lines.append(f"  完整表名: {_prefix}_{_sheets[0]}（其余工作表类似，前缀_工作表名）")
                                        _example_tbl = f'{_prefix}_{_sheets[0]}'
                                        att_lines.append(f"  SQL 示例: call_tool(\"execute_sql\", datasource_id=\"{virtual_ds.id}\", sql=\"SELECT COUNT(*) FROM \\\"{_example_tbl}\\\"\")")
                                att_lines.append("如未指定具体工作表，默认查询第一个工作表。")

                            if _image_files:
                                att_lines.append("")
                                att_lines.append("【图片附件】用户上传了以下图片，请用 llm_vision 工具分析图片内容：")
                                att_lines.append(f"datasource_id: {virtual_ds.id}")
                                for _f in _image_files:
                                    _img_path = _f.get("file_path", "")
                                    _img_name = _f.get("original_filename", "")
                                    att_lines.append(f"- 图片: {_img_name}")
                                    att_lines.append(f"  图片路径(file_path): {_img_path}")
                                    att_lines.append(f"  调用示例: call_tool(\"llm_vision\", image_path=\"{_img_path}\", prompt=\"请识别图片中的所有文字和数据\")")
                                att_lines.append("用 call_tool(\"llm_vision\", image_path=..., prompt=...) 识别图片内容后，给出分析结论。")

                            _user_msg = "\n".join(att_lines) + f"\n\n---\n\n{request.content}"
                            matched_names = [_VIRTUAL_DS_NAME]
                            _attachment_matched = True
                            # 把虚拟数据源写入 session_ctx（与用户选择数据源一致）
                            _session_ctx["source_datasource_id"] = str(virtual_ds.id)
                            _session_ctx["source_datasource_name"] = _VIRTUAL_DS_NAME
                            # 数据文件设 source_data_name（表名前缀），图片不设（不是数据表）
                            if _data_files:
                                _session_ctx["source_data_name"] = _data_files[0].get("table_name_prefix", "")

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

            from app.services.chat_router import classify_message
            from app.services.llm import llm_manager
            from app.core.database import async_session as _new_session

            # ===== direct_execute: 用户点「直接处理」，跳过匹配直接走 Agent =====
            if request.direct_execute:
                _msg_type = _session_ctx.get("last_msg_type", "processing")
                # 展示已确定的参数
                _ready = _get_ready_params(_session_ctx)
                if _ready:
                    yield f"data: {json.dumps({'type': 'executing', 'message': '已确定参数：' + '，'.join(_ready)}, ensure_ascii=False)}\n\n"
                # 检查参数是否齐全
                _missing = _get_missing_params(_session_ctx, _msg_type)
                if _missing:
                    yield f"data: {json.dumps({'type': 'content', 'content': _build_params_hint(_session_ctx, _msg_type)}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                    return
                _type_label = {"analysis": "数据分析", "processing": "数据处理"}.get(_msg_type, _msg_type)
                logger.info(f"[direct_execute] session={session_id} msg_type={_msg_type}")
                _skill_instruction_generated = False
                # 用户点「使用技能」走调试模式调用技能；「直接处理」不走技能
                if request.use_skill and (_session_ctx.get("last_skill_id") or _session_ctx.get("last_pipeline_id")):
                    _skill_id = _session_ctx.get("last_skill_id") or _session_ctx.get("last_pipeline_id")
                    yield f"data: {json.dumps({'type': 'executing', 'message': f'正在调用技能...'}, ensure_ascii=False)}\n\n"
                    _skill_instruction_generated = True
                    try:
                        from app.models.skill import Skill as _SkillModel
                        from app.services.skill_parser import read_skill_md, read_skill_script, read_lessons
                        from app.services.multi_agent import ensure_agent_runtime, build_debug_context, build_debug_message, stream_agent_events_sse
                        from pathlib import Path as _Path
                        from app.core.config import settings as _settings
                        async with _new_session() as _sk_sess:
                            _sk_result = await _sk_sess.execute(select(_SkillModel).where(_SkillModel.id == UUID(_skill_id)))
                            _sk = _sk_result.scalar_one_or_none()
                            # 在 session 内提取基本类型，避免 DetachedInstanceError
                            _sk_path = _sk.skill_path if _sk else None
                            _sk_display = _sk.display_name or _sk.name if _sk else ""
                            _sk_desc = _sk.description if _sk else ""
                            _sk_name = _sk.name if _sk else ""
                            _sk_type = _sk.skill_type if _sk else ""
                        if _sk_path:
                            _sk_folder = _Path(_settings.SKILL_STORAGE_PATH) / _sk_path
                            _sk_md = read_skill_md(_sk_folder) if _sk_folder else ""
                            _sk_script = read_skill_script(_sk_folder, "main.py") or "" if _sk_folder else ""
                            _sk_lessons = read_lessons(_sk_folder) if _sk_folder else ""
                            # 展示技能信息 + 数据上下文 + 用户指令
                            _ready = _get_ready_params(_session_ctx)
                            # 用数据上下文拼具体需求给 Agent
                            _src_ds = _session_ctx.get("source_datasource_name", "")
                            _src_tbl = _session_ctx.get("source_data_name", "")
                            _tgt_ds = _session_ctx.get("target_datasource_name", "")
                            _tgt_tbl = _session_ctx.get("target_data_name", "")
                            _skill_info = f"📋 技能：{_sk_display}"
                            if _sk_desc:
                                _skill_info += f"\n描述：{_sk_desc}"
                            if _ready:
                                _skill_info += "\n\n✅ 数据参数：" + "，".join(_ready)
                            # 拼具体需求
                            _detail = request.content
                            if _src_ds and _src_tbl:
                                _detail = f"把 {_src_ds} 的 {_src_tbl} 表"
                                if _tgt_ds and _tgt_tbl:
                                    _detail += f"导出到 {_tgt_ds} 的 {_tgt_tbl} 表"
                                else:
                                    _detail += f" {request.content}"
                            _skill_info += f"\n\n📝 执行需求：{_detail}"
                            full_response += _skill_info
                            yield f"data: {json.dumps({'type': 'content', 'content': _skill_info}, ensure_ascii=False)}\n\n"
                            _runtime = ensure_agent_runtime()
                            _debug_context = build_debug_context(
                                db=None,
                                user_id=current_user.id,
                                target_type="skill",
                                history=[],
                                script_name="main.py",
                                script_content=_sk_script,
                                function_name=None,
                                lessons=_sk_lessons,
                                source_datasource_id=_session_ctx.get("source_datasource_id", ""),
                                source_datasource_name=_session_ctx.get("source_datasource_name", ""),
                                source_data_name=_session_ctx.get("source_data_name", ""),
                                target_datasource_id=_session_ctx.get("target_datasource_id", ""),
                                target_datasource_name=_session_ctx.get("target_datasource_name", ""),
                                target_data_name=_session_ctx.get("target_data_name", ""),
                                debug_folder=_sk_folder,
                                debug_skill_path=_sk_folder,
                                debug_skill_md=_sk_md[:1500] if _sk_md else "",
                                debug_skill_md_full=_sk_md,
                            )
                            _debug_msg = build_debug_message(_detail, _debug_context)
                            _is_analysis = _sk_type == "analysis"
                            _agent_name = "data_analyst" if _is_analysis else "data_processor"
                            logger.info(f"[direct_execute] 走调试模式调用技能: {_sk_name} agent={_agent_name}")
                            # SSE 保活：20 秒无事件则发 ping，防止长时间执行导致 network error
                            _agen = _runtime.run(_agent_name, _debug_msg, _debug_context).__aiter__()
                            _exec_failed = False
                            while True:
                                _fut = asyncio.ensure_future(_agen.__anext__())
                                done, pending = await asyncio.wait({_fut}, timeout=20)
                                if not done:
                                    yield f"data: {json.dumps({'type': 'ping'}, ensure_ascii=False)}\n\n"
                                    done, pending = await asyncio.wait({_fut}, timeout=120)
                                    if not done:
                                        _fut.cancel()
                                        logger.error(f"[direct_execute] 技能执行超时: {_sk.name}")
                                        yield f"data: {json.dumps({'type': 'error', 'content': '技能执行超时，请稍后重试'}, ensure_ascii=False)}\n\n"
                                        _exec_failed = True
                                        break
                                try:
                                    _agent_event = _fut.result()
                                except StopAsyncIteration:
                                    break
                                except Exception as e:
                                    logger.error(f"[direct_execute] Agent 执行异常: {e}", exc_info=True)
                                    yield f"data: {json.dumps({'type': 'error', 'content': f'技能执行出错: {e}'}, ensure_ascii=False)}\n\n"
                                    _exec_failed = True
                                    break
                                _t = _agent_event.get("type")
                                if _t == "done":
                                    pass  # content 已通过 content 事件流式传过，done 不重复 yield
                                elif _t == "agent_switch":
                                    _agent_display = _agent_event.get("display_name", _agent_event.get("agent", ""))
                                    _agent_reason = _agent_event.get("reason_display", _agent_event.get("reason", ""))
                                    yield f"data: {json.dumps({'type': 'agent_switch', 'agent': _agent_event.get('agent', ''), 'display_name': _agent_display, 'reason': _agent_event.get('reason', ''), 'reason_display': _agent_reason}, ensure_ascii=False)}\n\n"
                                elif _t == "content":
                                    _c = _agent_event.get("content", "")
                                    if _c:
                                        full_response += _c
                                        yield f"data: {json.dumps(_agent_event, ensure_ascii=False, default=str)}\n\n"
                                elif _t in ("thinking", "model", "executing", "progress", "tool_action", "tool_summary", "run_result", "inspecting", "inspection_report", "retry", "round", "give_up"):
                                    yield f"data: {json.dumps(_agent_event, ensure_ascii=False, default=str)}\n\n"
                            # 保存 assistant 消息到 DB（含异常时部分内容恢复）
                            async with _new_session() as save_session:
                                _save_content = full_response or ("技能执行失败" if _exec_failed else "技能执行完成")
                                save_session.add(ChatMessage(
                                    session_id=request.session_id, role="assistant",
                                    content=_save_content,
                                ))
                                _sess = await save_session.get(ChatSession, request.session_id)
                                if _sess:
                                    _sess.context = dict(_session_ctx)
                                await save_session.commit()
                            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                            return
                    except Exception as e:
                        logger.warning(f"[direct_execute] 技能调用失败: {e}")
                        yield f"data: {json.dumps({'type': 'content', 'content': f'⚠ 技能调用失败: {e}'}, ensure_ascii=False)}\n\n"
            else:
                # ===== classify: 一次 LLM 判断意图 + keep =====
                yield f"data: {json.dumps({'type': 'executing', 'message': '正在理解您的需求...'}, ensure_ascii=False)}\n\n"
                _msg_type, _keep_source, _keep_target, _keep_skill, _classify_events = await classify_message(request.content, _session_ctx)
                for _ev in _classify_events:
                    if _ev.get("type") == "error":
                        yield f"data: {json.dumps({'type': 'content', 'content': _ev['content']}, ensure_ascii=False)}\n\n"
                        full_response += _ev["content"]
                    elif _ev.get("type") in ("model", "thinking"):
                        yield f"data: {json.dumps(_ev, ensure_ascii=False)}\n\n"
                _type_label = {"analysis": "数据分析", "processing": "数据处理", "chat": "智能对话"}.get(_msg_type, _msg_type)
                yield f"data: {json.dumps({'type': 'executing', 'message': f'已识别：{_type_label}，正在为您准备...'}, ensure_ascii=False)}\n\n"
                logger.info(f"[classify] session={session_id} msg_type={_msg_type} keep_source={_keep_source} keep_target={_keep_target} keep_skill={_keep_skill} content={request.content[:50]!r}")

                # keep=change → 清 context 对应项（keep=true 不清，保留已有参数）
                _ctx_changed = False
                if not _keep_source:
                    _session_ctx.pop("source_datasource_id", None)
                    _session_ctx.pop("source_datasource_name", None)
                    _session_ctx.pop("source_data_name", None)
                    _ctx_changed = True
                if not _keep_target:
                    _session_ctx.pop("target_datasource_id", None)
                    _session_ctx.pop("target_datasource_name", None)
                    _session_ctx.pop("target_data_name", None)
                    _ctx_changed = True
                if not _keep_skill:
                    _session_ctx.pop("last_skill_id", None)
                    _session_ctx.pop("last_skill_name", None)
                    _session_ctx.pop("last_pipeline_id", None)
                    _session_ctx.pop("last_pipeline_name", None)
                    _ctx_changed = True
                if _ctx_changed:
                    async with _new_session() as _ctx_sess:
                        _ctx_obj = await _ctx_sess.get(ChatSession, request.session_id)
                        if _ctx_obj:
                            _ctx_obj.context = dict(_session_ctx)
                        await _ctx_sess.commit()

                # 记住 msg_type，供 direct_execute 复用
                _session_ctx["last_msg_type"] = _msg_type

            # ===== 恢复数据源上下文（direct_execute 和非 chat 都需要）=====
            if not _attachment_matched and _session_ctx.get("source_datasource_id"):
                from app.models.datasource import DataSource as _DS
                async with _new_session() as _ctx_ds_sess:
                    _ctx_src = await _ctx_ds_sess.execute(select(_DS).where(_DS.id == UUID(_session_ctx["source_datasource_id"]), _DS.is_active == True))
                    _ctx_ds = _ctx_src.scalars().first()
                    if _ctx_ds:
                        _can_use_ctx = (_ctx_ds.created_by == current_user.id or current_user.is_superuser)
                        if _can_use_ctx:
                            datasource_context, data_preview = await _build_selected_datasource_context(
                                _ctx_ds, _session_ctx.get("source_data_name"), request.content
                            )
                            matched_names = [_ctx_ds.name]
                            _attachment_matched = True

            if not _attachment_matched and not request.direct_execute:
                async with _new_session() as _ds_inf_sess:
                    datasource_context, data_preview, matched_names = await build_datasource_context(
                        _ds_inf_sess, current_user.id, request.content
                    )
                _user_msg = f"{data_preview}\n\n---\n\n{request.content}" if data_preview else request.content

            # 注入已知的数据上下文到 user message
            _ctx_lines = []
            if _session_ctx.get("source_datasource_name"):
                _ctx_lines.append(f"源数据源: {_session_ctx['source_datasource_name']}")
            if _session_ctx.get("source_data_name"):
                _ctx_lines.append(f"源表: {_session_ctx['source_data_name']}")
            if _session_ctx.get("target_datasource_name"):
                _ctx_lines.append(f"目标数据源: {_session_ctx['target_datasource_name']}")
            if _session_ctx.get("target_data_name"):
                _ctx_lines.append(f"目标表: {_session_ctx['target_data_name']}")
            if _ctx_lines:
                _user_msg = f"【已确定的数据上下文】\n" + "\n".join(_ctx_lines) + f"\n\n---\n\n{_user_msg}"

            compressed_history = await _compress_history(history_messages, session_id)

            # ===== chat 类型：走 ChatAgent =====
            if _msg_type == "chat" and not request.direct_execute:
                from app.services.multi_agent import ensure_agent_runtime, AgentMessage, HandoffReason, stream_agent_events_sse
                _runtime = ensure_agent_runtime()
                _chat_context = {
                    "user_id": current_user.id,
                    "history": compressed_history,
                    "has_preinjected_data": False,
                    "last_config_target": _session_ctx.get("last_config_target", ""),
                }
                _chat_msg = AgentMessage(
                    from_agent="user",
                    to_agent="chat_agent",
                    reason=HandoffReason.DELEGATE,
                    payload={"user_message": _user_msg, "history": compressed_history},
                    context=_chat_context,
                )
                yield f"data: {json.dumps({'type': 'executing', 'message': '正在思考...'}, ensure_ascii=False)}\n\n"
                try:
                    async for event in stream_agent_events_sse(_runtime, _chat_msg, _chat_context, user_id=current_user.id, agent_name="chat_agent"):
                        if event.startswith("data: "):
                            _parsed = json.loads(event[6:])
                            if _parsed.get("type") == "content" and _parsed.get("content"):
                                full_response += _parsed["content"]
                            elif _parsed.get("type") == "done":
                                if not full_response and _parsed.get("result", {}).get("content"):
                                    full_response = _parsed["result"]["content"]
                        yield event
                except Exception as e:
                    logger.error(f"chat LLM 调用失败: {e}")
                    full_response += f"\n\n❌ 响应出错: {e}"
                    yield f"data: {json.dumps({'type': 'content', 'content': f'❌ 响应出错: {e}'}, ensure_ascii=False)}\n\n"
                # 把 last_config_target 写回 session_ctx（持久化到 DB，下次对话能用）
                if _chat_context.get("last_config_target"):
                    _session_ctx["last_config_target"] = _chat_context["last_config_target"]
                async with _new_session() as save_session:
                    save_session.add(ChatMessage(
                        session_id=request.session_id, role="assistant",
                        content=full_response,
                    ))
                    _sess = await save_session.get(ChatSession, request.session_id)
                    if _sess:
                        _sess.context = dict(_session_ctx)
                    await save_session.commit()
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                return

            # ===== 非 chat 且非 direct_execute：并行匹配 =====
            if not request.direct_execute and _msg_type != "chat":
                from app.services.match_service import (
                    llm_match_tables, llm_match_skills, llm_match_pipelines,
                )
                from app.models.datasource import DataSource
                from app.models.skill import Skill
                from app.models.pipeline import Pipeline
                from app.services.permission_service import check_permission

                _all_suggestions = []

                try:
                    # 判断三路是否需要匹配
                    _need_source = not _keep_source or not bool(_session_ctx.get("source_datasource_id") and _session_ctx.get("source_data_name"))
                    _need_target = _msg_type == "processing" and (not _keep_target or not bool(_session_ctx.get("target_datasource_id") and _session_ctx.get("target_data_name")))
                    _need_skill = not _keep_skill or not bool(_session_ctx.get("last_skill_id") or _session_ctx.get("last_pipeline_id"))

                    # ===== 段5：匹配阶段（独立 session，闭包共用，匹配完释放）=====
                    async with _new_session() as db:
                        # 预查数据源（当前用户的 + 虚拟数据源，排除其他用户的私有数据源）
                        _all_ds = [ds for ds in (await db.execute(select(DataSource).where(DataSource.is_active == True))).scalars().all()
                                   if ds.name and (ds.created_by == current_user.id or current_user.is_superuser or ds.is_virtual)]

                        # 预统计匹配池规模（给用户丰富的进度提示）
                        from app.models.datasource import TableMetadata as _TM
                        from sqlalchemy import func as _func
                        _skill_pool = (await db.execute(select(Skill))).scalars().all()
                        # 按 msg_type 过滤技能池（与 llm_match_skills 内部过滤逻辑一致）
                        if _msg_type == "analysis":
                            _skill_pool = [s for s in _skill_pool if s.skill_type == "analysis"]
                        elif _msg_type == "processing":
                            _skill_pool = [s for s in _skill_pool if s.skill_type != "analysis"]
                        _pipe_pool = (await db.execute(select(Pipeline).where(Pipeline.is_active == True, Pipeline.is_builtin == False))).scalars().all()
                        # 数据表匹配池：只统计用户消息中提到的数据源的表数（按名称去重）
                        _mentioned_ds = []
                        _seen_ds_names = set()
                        for ds in _all_ds:
                            if ds.name and ds.name in request.content and ds.name not in _seen_ds_names:
                                _mentioned_ds.append(ds)
                                _seen_ds_names.add(ds.name)
                        _mentioned_tbl_cnt = 0
                        if _mentioned_ds:
                            _mentioned_tbl_cnt = (await db.execute(
                                select(_func.count()).select_from(_TM).where(_TM.data_source_id.in_([ds.id for ds in _mentioned_ds]))
                            )).scalar() or 0

                        async def _match_source():
                            """源表匹配"""
                            if not _need_source:
                                return None
                            _ds_names = [ds.name for ds in _all_ds if ds.name in request.content]
                            if not _ds_names:
                                return {"type": "missing_source"}
                            table_matches, _, _events = await llm_match_tables(request.content, db)
                            _results = []
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
                                _results.append({
                                    "type": "table",
                                    "datasource_id": str(ds.id),
                                    "datasource_name": ds.name,
                                    "table_name": table_name,
                                    "row_count": meta.get("row_count"),
                                    "column_count": meta.get("column_count"),
                                    "similarity": score,
                                    "can_use": can_use,
                                })
                            if _results:
                                return {"type": "data_suggestion", "matches": _results}
                            return {"type": "data_no_match"}

                        async def _match_target():
                            """目标表匹配（仅 processing）"""
                            if not _need_target:
                                return None
                            _tgt_ds_names = [ds.name for ds in _all_ds if ds.name in request.content]
                            if not _tgt_ds_names:
                                return {"type": "missing_target"}
                            target_matches, _, _events = await llm_match_tables(request.content, db)
                            _results = []
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
                                _results.append({
                                    "type": "target_table",
                                    "datasource_id": str(_ds.id),
                                    "datasource_name": _ds.name,
                                    "table_name": _tname,
                                    "row_count": meta.get("row_count"),
                                    "column_count": meta.get("column_count"),
                                    "similarity": score,
                                    "can_use": _can_use,
                                })
                            if _results:
                                return {"type": "target_suggestion", "matches": _results}
                            return {"type": "target_no_match"}

                        async def _match_skill():
                            """技能/流程匹配"""
                            if not _need_skill:
                                return None
                            _results = []
                            if _msg_type == "processing":
                                # processing: 流程和技能都匹配，合并展示给用户选择
                                pipe_matches, _ = await llm_match_pipelines(request.content, db, _msg_type)
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
                                    _results.append({
                                        "type": "pipeline",
                                        "id": str(p.id),
                                        "name": p.display_name or p.name,
                                        "description": p.description or "",
                                        "similarity": score,
                                        "can_use": can_use,
                                    })
                            # 技能匹配（processing 和 analysis 都匹配技能）
                            skill_matches, _ = await llm_match_skills(request.content, db, _msg_type)
                            _results = []
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
                                _results.append({
                                    "type": "skill",
                                    "id": str(s.id),
                                    "name": s.display_name or s.name,
                                    "description": s.description or "",
                                    "similarity": score,
                                    "can_use": can_use,
                                })
                            if _results:
                                return {"type": "skill_suggestion", "matches": _results}
                            return {"type": "skill_no_match"}

                        if _need_source:
                            if _mentioned_ds:
                                _ds_names_str = '、'.join(ds.name for ds in _mentioned_ds)
                                yield f"data: {json.dumps({'type': 'executing', 'message': f'正在从「{_ds_names_str}」匹配数据表（{_mentioned_tbl_cnt} 张表中）...'}, ensure_ascii=False)}\n\n"
                            else:
                                yield f"data: {json.dumps({'type': 'executing', 'message': '未识别到数据源名称，请指定数据源'}, ensure_ascii=False)}\n\n"
                        elif _session_ctx.get("source_datasource_name") and _session_ctx.get("source_data_name"):
                            _src_ds = _session_ctx["source_datasource_name"]
                            _src_tbl = _session_ctx["source_data_name"]
                            yield f"data: {json.dumps({'type': 'executing', 'message': f'✓ 沿用上次选定的数据：{_src_ds} → {_src_tbl}'}, ensure_ascii=False)}\n\n"
                        if _need_target:
                            if _mentioned_ds:
                                _ds_names_str = '、'.join(ds.name for ds in _mentioned_ds)
                                yield f"data: {json.dumps({'type': 'executing', 'message': f'正在从「{_ds_names_str}」匹配目标表（{_mentioned_tbl_cnt} 张表中）...'}, ensure_ascii=False)}\n\n"
                            else:
                                yield f"data: {json.dumps({'type': 'executing', 'message': '未识别到数据源名称，请指定目标数据源'}, ensure_ascii=False)}\n\n"
                        elif _msg_type == "processing" and _session_ctx.get("target_datasource_name"):
                            _tgt_ds = _session_ctx["target_datasource_name"]
                            _tgt_tbl = _session_ctx["target_data_name"]
                            yield f"data: {json.dumps({'type': 'executing', 'message': f'✓ 沿用上次选定的目标表：{_tgt_ds} → {_tgt_tbl}'}, ensure_ascii=False)}\n\n"
                        if _need_skill:
                            if _msg_type == "processing":
                                yield f"data: {json.dumps({'type': 'executing', 'message': f'正在匹配技能/流程（{len(_pipe_pool)} 个流程，{len(_skill_pool)} 个技能中）...'}, ensure_ascii=False)}\n\n"
                            else:
                                yield f"data: {json.dumps({'type': 'executing', 'message': f'正在匹配技能（{len(_skill_pool)} 个技能中）...'}, ensure_ascii=False)}\n\n"
                        elif _session_ctx.get("last_skill_name") or _session_ctx.get("last_pipeline_name"):
                            _sk = _session_ctx.get("last_skill_name") or _session_ctx.get("last_pipeline_name")
                            yield f"data: {json.dumps({'type': 'executing', 'message': f'✓ 沿用上次选定的技能：{_sk}'}, ensure_ascii=False)}\n\n"
                        if cancel_event.is_set():
                            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                            return

                        # 三路完全独立并行
                        _s_res, _t_res, _k_res = await asyncio.gather(
                            _match_source(), _match_target(), _match_skill(),
                            return_exceptions=True,
                        )

                    # 处理异常和结果
                    for _res in (_s_res, _t_res, _k_res):
                        if isinstance(_res, Exception):
                            logger.error(f"[match] 匹配异常: {_res}", exc_info=True)
                            continue
                        if _res:
                            _all_suggestions.append(_res)

                    # keep_skill 跳过匹配但已有技能 → 把已选技能作为卡片展示
                    if not _need_skill and (_session_ctx.get("last_skill_id") or _session_ctx.get("last_pipeline_id")):
                        _sk_id = _session_ctx.get("last_skill_id") or _session_ctx.get("last_pipeline_id")
                        _sk_name = _session_ctx.get("last_skill_name") or _session_ctx.get("last_pipeline_name") or ""
                        _sk_type = "pipeline" if _session_ctx.get("last_pipeline_id") else "skill"
                        if not any(s["type"] == "skill_suggestion" for s in _all_suggestions):
                            _all_suggestions.append({"type": "skill_suggestion", "matches": [{
                                "type": _sk_type,
                                "id": str(_sk_id),
                                "name": _sk_name,
                                "description": "",
                                "similarity": 1.0,
                                "can_use": True,
                            }]})

                    # 匹配结果汇总提示
                    _result_lines = []
                    for _res in _all_suggestions:
                        if _res["type"] == "data_suggestion":
                            _result_lines.append(f"✓ 数据表匹配到 {len(_res['matches'])} 个结果")
                        elif _res["type"] == "target_suggestion":
                            _result_lines.append(f"✓ 目标表匹配到 {len(_res['matches'])} 个结果")
                        elif _res["type"] == "skill_suggestion":
                            _result_lines.append(f"✓ 技能/流程匹配到 {len(_res['matches'])} 个结果")
                        elif _res["type"] == "missing_source":
                            _result_lines.append("✗ 未识别到数据源名称")
                        elif _res["type"] == "missing_target":
                            _result_lines.append("✗ 未识别到目标数据源名称")
                        elif _res["type"] == "data_no_match":
                            _result_lines.append("✗ 数据表未匹配到结果")
                        elif _res["type"] == "target_no_match":
                            _result_lines.append("✗ 目标表未匹配到结果")
                        elif _res["type"] == "skill_no_match":
                            _result_lines.append("✗ 技能/流程未匹配到结果")
                    if _result_lines:
                        yield f"data: {json.dumps({'type': 'executing', 'message': '，'.join(_result_lines)}, ensure_ascii=False)}\n\n"

                    # 保存消息 + yield 所有匹配结果事件（每路独立，不复杂判断）
                    # 展示已确定的参数和缺失的参数
                    _params_hint = _build_params_hint(_session_ctx, _msg_type)
                    _match_msg = "检测到匹配结果，请选择操作。"
                    if _params_hint:
                        _match_msg += "\n\n" + _params_hint
                    async with _new_session() as save_session:
                        save_session.add(ChatMessage(
                            session_id=request.session_id, role="assistant",
                            content=_match_msg,
                        ))
                        _sess = await save_session.get(ChatSession, request.session_id)
                        if _sess:
                            _sess.context = dict(_session_ctx)
                        await save_session.commit()

                    # 逐路 yield 事件——匹配到的发 suggestion，没匹配到的发 no_match 类型
                    for sug in _all_suggestions:
                        logger.info(f"[match] yield suggestion: type={sug['type']}")
                        if sug["type"] in ("data_suggestion", "target_suggestion", "skill_suggestion"):
                            yield f"data: {json.dumps({'type': sug['type'], 'msg_type': _msg_type, 'matches': sug['matches']}, ensure_ascii=False, default=str)}\n\n"
                        elif sug["type"] == "missing_source":
                            yield f"data: {json.dumps({'type': 'source_datasource_no_match', 'msg_type': _msg_type}, ensure_ascii=False)}\n\n"
                        elif sug["type"] == "missing_target":
                            yield f"data: {json.dumps({'type': 'target_datasource_no_match', 'msg_type': _msg_type}, ensure_ascii=False)}\n\n"
                        elif sug["type"] == "data_no_match":
                            yield f"data: {json.dumps({'type': 'source_table_no_match', 'msg_type': _msg_type}, ensure_ascii=False)}\n\n"
                        elif sug["type"] == "target_no_match":
                            yield f"data: {json.dumps({'type': 'target_table_no_match', 'msg_type': _msg_type}, ensure_ascii=False)}\n\n"
                        elif sug["type"] == "skill_no_match":
                            yield f"data: {json.dumps({'type': 'skill_no_match', 'msg_type': _msg_type}, ensure_ascii=False)}\n\n"

                    # 兜底：没有任何 suggestion 时才检查参数是否齐全
                    if not _all_suggestions:
                        _missing = _get_missing_params(_session_ctx, _msg_type)
                        if _missing:
                            yield f"data: {json.dumps({'type': 'content', 'content': _build_params_hint(_session_ctx, _msg_type)}, ensure_ascii=False)}\n\n"

                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                    return
                except Exception as e:
                    import traceback as _tb
                    _err = f"⚠️ 匹配检测出错：{e}\n\n"
                    logger.error(f"[match] 匹配出错，停止处理: {e}\n{_tb.format_exc()}")
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

            # 如果有已选技能且指令未在 direct_execute 生成过，生成技能调用指令替换 _user_msg
            if not _skill_instruction_generated and (_session_ctx.get("last_skill_id") or _session_ctx.get("last_pipeline_id")):
                _skill_id = _session_ctx.get("last_skill_id") or _session_ctx.get("last_pipeline_id")
                _skill_name = _session_ctx.get("last_skill_name") or _session_ctx.get("last_pipeline_name") or ""
                yield f"data: {json.dumps({'type': 'executing', 'message': f'正在生成技能调用指令...'}, ensure_ascii=False)}\n\n"
                try:
                    from app.services.skill_parser import read_skill_md
                    from app.models.skill import Skill as _SkillModel
                    async with _new_session() as _instr_sess:
                        _skill_result = await _instr_sess.execute(select(_SkillModel).where(_SkillModel.id == UUID(_skill_id)))
                        _skill = _skill_result.scalar_one_or_none()
                        # 在 session 内提取基本类型
                        _skill_path = _skill.skill_path if _skill else None
                        _skill_display = _skill.display_name or _skill.name if _skill else _skill_name
                        _skill_desc = _skill.description if _skill else ""
                        _skill_name_actual = _skill.name if _skill else _skill_name
                    if _skill_path:
                        from pathlib import Path as _Path
                        from app.core.config import settings as _settings
                        _skill_folder = _Path(_settings.SKILL_STORAGE_PATH) / _skill_path
                        _skill_md = read_skill_md(_skill_folder) if _skill_folder else ""
                        _skill_ctx_lines = _get_ready_params(_session_ctx)
                        _skill_chat_context = "\n".join(_skill_ctx_lines) if _skill_ctx_lines else "无已知数据上下文"
                        _instruction = await llm_manager.chat_with_messages([
                            {"role": "system", "content": (
                                "你是一个技能调用指令生成器。根据技能的 SKILL.md（参数规范 + 使用示例）和用户的对话上下文，"
                                "生成一条符合技能使用示例格式的调用指令。\n\n"
                                "## 严格要求\n"
                                "1. 指令必须符合 SKILL.md 中「使用方式」的示例格式\n"
                                "2. 从对话上下文中提取具体的数据源名、表名等参数值，不要用「这个数据源」「这张表」等代词\n"
                                "3. 只使用技能需要的参数，不需要的参数不要硬塞\n"
                                "4. 只输出一条指令，不要解释，不要输出 JSON\n"
                                "5. 如果对话上下文不足以确定某个参数，用「请指定」标注\n"
                            )},
                            {"role": "user", "content": (
                                f"## 技能信息\n技能名称：{_skill_display}\n技能描述：{_skill_desc or ''}\n\n"
                                f"## SKILL.md\n{_skill_md[:3000]}\n\n"
                                f"## 已知数据上下文\n{_skill_chat_context}\n\n"
                                f"## 用户消息\n{request.content}\n\n"
                                f"请根据以上信息，生成一条符合技能使用示例格式的调用指令。"
                            )},
                        ], temperature=0.2, max_tokens=500)
                        _instruction = _instruction.strip()
                        if _instruction.startswith("```"):
                            _lines = _instruction.split("\n")
                            _instruction = "\n".join(_lines[1:-1]) if len(_lines) > 2 else _instruction.strip("`")
                        if _instruction:
                            _user_msg = _instruction
                            yield f"data: {json.dumps({'type': 'content', 'content': f'📋 技能调用指令：\n\n{_instruction}'}, ensure_ascii=False)}\n\n"
                            logger.info(f"[route] 生成技能指令: {_instruction[:100]!r}")
                except Exception as e:
                    logger.warning(f"[route] 技能指令生成失败: {e}")

            runtime = ensure_agent_runtime()

            trace_id = str(uuid4())
            context = {
                "user_id": current_user.id,
                "datasource_context": datasource_context,
                "persona": ASSISTANT_PERSONA,
                "session_id": session_id,
                "history": compressed_history,
                "has_preinjected_data": bool(data_preview),
                "session_ctx": _session_ctx,
            }

            # 如果有已选技能，把技能信息注入 context，并在 user_msg 里提示 Agent 调用技能
            if _skill_instruction_generated or (_session_ctx.get("last_skill_id") and not _skill_instruction_generated):
                try:
                    from app.models.skill import Skill as _SkillModel
                    from app.services.skill_parser import read_skill_md, read_skill_script
                    from pathlib import Path as _Path
                    from app.core.config import settings as _settings
                    _sk_id = _session_ctx.get("last_skill_id") or _session_ctx.get("last_pipeline_id")
                    async with _new_session() as _inj_sess:
                        _sk_result = await _inj_sess.execute(select(_SkillModel).where(_SkillModel.id == UUID(_sk_id)))
                        _sk = _sk_result.scalar_one_or_none()
                        # 在 session 内提取基本类型
                        _sk_path = _sk.skill_path if _sk else None
                        _sk_name = _sk.name if _sk else ""
                        _sk_display = _sk.display_name or _sk.name if _sk else ""
                        _sk_desc = _sk.description if _sk else ""
                    if _sk_path:
                        _sk_folder = _Path(_settings.SKILL_STORAGE_PATH) / _sk_path
                        _sk_md = read_skill_md(_sk_folder) if _sk_folder else ""
                        _sk_script = read_skill_script(_sk_folder, "main.py") if _sk_folder else None
                        context["skill_id"] = _sk_id
                        context["skill_name"] = _sk_name
                        context["skill_path"] = str(_sk_folder) if _sk_folder else ""
                        context["skill_md"] = _sk_md[:3000] if _sk_md else ""
                        context["skill_script"] = _sk_script[:3000] if _sk_script else ""
                        # 在 user_msg 里提示 Agent 使用技能
                        _user_msg = f"【请使用技能执行】\n技能：{_sk_display}\n技能描述：{_sk_desc or ''}\n\n用户需求：{request.content}\n\n请调用技能脚本来完成用户需求。"
                        logger.info(f"[route] 注入技能 context: {_sk_name}")
                except Exception as e:
                    logger.warning(f"[route] 技能 context 注入失败: {e}")

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
            # 先推错误到前端（SSE 可能还没关闭）
            try:
                yield f"data: {json.dumps({'type': 'content', 'content': f'❌ 响应出错: {e}'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'error', 'content': err_detail}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
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
