"""对话API端点"""

import asyncio
import json
import os
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status, Query
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
from app.services.tool_guidance import get_tool_guidance

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


def _build_system_prompt(datasource_context: str) -> str:
    from app.services.prompt_docs import SANDBOX_TOOLS_DOC, SAFETY_RULES_DOC
    persona_block = f"{ASSISTANT_PERSONA}\n\n---\n\n" if ASSISTANT_PERSONA else ""
    tool_guidance = get_tool_guidance()
    return f"""{persona_block}## 数据源知识库
{datasource_context}

{SANDBOX_TOOLS_DOC}

{SAFETY_RULES_DOC}

{tool_guidance}"""


async def build_datasource_context(
    db: AsyncSession,
    user_id: UUID,
    user_message: str = "",
) -> str:
    result = await db.execute(
        select(DataSource).where(
            DataSource.is_active == True,
            DataSource.created_by == user_id,
        )
    )
    sources = result.scalars().all()

    if not sources:
        return '\n## 可用数据源\n当前没有配置任何数据源。建议用户先在【数据源管理】页面添加数据源。\n'

    lines = ["\n## 可用数据源（工具的知识库）"]
    lines.append(f"以下 {len(sources)} 个数据源已配置，可供用户分析：\n")

    for ds in sources:
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

    # 当用户消息中提到了数据源名称时，自动查询实际数据
    # 预览作为一次性 user message 注入（不进 system prompt），保持 system 字节稳定命中 prefix cache
    data_previews = await _query_datasource_previews(sources, user_message)

    return "\n".join(lines), data_previews


async def _query_datasource_previews(sources, user_message: str) -> str:
    """查询用户消息中提到的数据源的实际数据预览"""
    from app.services.connectors import get_connector
    if not user_message:
        return ""

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

    matched_sources = []
    for ds in sources:
        ds_name_lower = ds.name.lower()
        if ds_name_lower in msg_lower:
            matched_sources.append(ds)
            continue
        name_keywords = ds_name_lower.replace('_', ' ').replace('-', ' ').split()
        if any(kw in msg_lower for kw in name_keywords):
            matched_sources.append(ds)
            continue

    if not matched_sources and sources:
        data_keywords = ['数据', '分析', '统计', '查询', '看看', '查看', 'data', 'analyze']
        if any(kw in msg_lower for kw in data_keywords):
            matched_sources = [sources[0]]

    for ds in matched_sources:

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
        return "\n## 实时数据查询结果\n以下是从数据源中查询到的真实数据，请基于这些数据回答用户问题：\n" + "\n".join(previews)
    return ""


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
    await db.delete(session)


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


@router.post("/messages", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    request: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送消息"""
    # 验证会话存在
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == request.session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    # 保存用户消息
    user_message = ChatMessage(
        session_id=request.session_id,
        role="user",
        content=request.content,
    )
    db.add(user_message)
    await db.flush()
    await db.refresh(user_message)

    # 刷新会话 updated_at，使会话列表按最近活跃排序
    session.updated_at = datetime.utcnow()
    await db.flush()

    try:
        # 设置当前用户的 LLM 配置（API Key 按用户隔离）
        from app.services.llm import init_user_llm_context
        await init_user_llm_context(current_user.id)

        # 初始化LLM
        await llm_manager.initialize()

        # 获取历史消息（最近20条，不包括当前刚保存的）
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

        # 构建数据源知识库（含实时数据查询）
        datasource_context, data_preview = await build_datasource_context(
            db, current_user.id, request.content
        )

        # 构建 system prompt（不含实时数据预览，保持字节稳定命中 prefix cache）
        system_content = _build_system_prompt(datasource_context)

        # 组装 messages 列表
        messages = [{"role": "system", "content": system_content}]

        messages.extend(await _compress_history(history_messages, str(request.session_id)))

        # 实时数据预览作为一次性 user message 注入（不进 system，避免破坏 prefix cache）
        user_content = f"{data_preview}\n\n---\n\n{request.content}" if data_preview else request.content
        messages.append({"role": "user", "content": user_content})

        logger.info(f"chat messages: system={len(system_content)}chars, history={len(history_messages)}, total={len(messages)}")
        for i, m in enumerate(messages):
            preview = m["content"][:80].replace("\n", "\\n")
            logger.debug(f"  msg[{i}] role={m['role']} preview={preview}...")

        ai_content = await llm_manager.chat_with_messages(messages, max_tokens=2000)

    except Exception as e:
        logger.error(f"LLM调用失败: {e}")
        ai_content = f"处理您的请求时出现错误: {str(e)}"

    # 保存AI响应
    ai_message = ChatMessage(
        session_id=request.session_id,
        role="assistant",
        content=ai_content,
    )
    db.add(ai_message)
    await db.flush()
    await db.refresh(ai_message)

    return ai_message


# ==================== 上下文压缩 ====================
# 会话历史压缩缓存：session_id -> (摘要文本, 已摘要覆盖到的最后一条消息id)
_HISTORY_SUMMARIES: dict = {}
HISTORY_CHAR_BUDGET = 6000   # 历史原文总 token 估算超过此值则触发压缩
HISTORY_KEEP_RECENT = 6      # 压缩时保留最近 N 条原文
PREVIEW_CHAR_LIMIT = 5000    # 单个数据源预览的字符上限


async def _compress_history(history_messages: list, session_id: str) -> list:
    """历史消息分层压缩：总量超预算时，旧消息摘要 + 最近若干条原文。

    改进（L）：标识符机械抽取——压缩时提取表名/数据源ID/UUID，保留在摘要中。
    改进（M）：使用 CJK 感知的 token 估算替代字符数。
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
    else:
        try:
            older_text = "\n".join(f"[{m.role}] {(m.content or '')[:500]}" for m in older)
            # 标识符保护：从旧消息中机械提取表名/数据源ID/UUID（L）
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
        except Exception as e:
            logger.warning(f"历史摘要生成失败，降级为仅保留近期: {e}")
            summary = None

    compressed: list = []
    if summary:
        compressed.append({"role": "system", "content": f"## 先前对话摘要\n{summary}"})
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
            from app.services.llm import init_user_llm_context
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

            datasource_context, data_preview = await build_datasource_context(
                db, current_user.id, request.content
            )

            # 实时数据预览作为一次性 user message 注入（不进 system，避免破坏 prefix cache）
            _user_msg = f"{data_preview}\n\n---\n\n{request.content}" if data_preview else request.content

            # 提交用户消息，释放 SQLite 写锁（避免流式期间 database is locked）
            await db.commit()

            # 统一路由：始终从 data_processor 开始，Agent 自主决定是否 handoff（O）
            from app.services.multi_agent import ensure_agent_runtime, AgentMessage, HandoffReason

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
            }

            message = AgentMessage(
                from_agent="user",
                to_agent="data_processor",
                reason=HandoffReason.DELEGATE,
                payload={"user_message": _user_msg, "content": _user_msg},
                context=context,
                trace_id=trace_id,
            )

            agen = runtime.run("data_processor", message, context).__aiter__()
            while True:
                if cancel_event.is_set():
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

                if event.get("type") == "agent_switch":
                    yield f"data: {json.dumps({'type': 'agent_switch', 'agent': event['agent'], 'reason': event['reason']}, ensure_ascii=False)}\n\n"
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
