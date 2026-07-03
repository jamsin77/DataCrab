"""对话API端点"""

import asyncio
import json
import os
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
    NLDataProcessRequest,
    NLDataProcessResponse,
    NLStreamEvent,
)
from app.api.deps import get_current_user
from app.services.llm import llm_manager
from app.services.agent_config import agent_config
from app.services.agent_utils import estimate_tokens, build_identifier_hint
from app.services.tool_guidance import get_tool_guidance

router = APIRouter()

# 延迟导入：只在需要时才加载重型模块
_nl_service = None
_skill_library = None


def _get_nl_service():
    global _nl_service, _skill_library
    if _nl_service is None:
        from app.services.nl_service import NLService
        from app.services.skill_library import SkillLibrary
        _skill_library = SkillLibrary()
        _nl_service = NLService(llm_manager, _skill_library)
    return _nl_service

# 加载助理人格文件
_persona_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_persona_path = os.path.join(_persona_dir, "services", "personal.md")
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

## 重要提示
如果上面的上下文中包含了【实时数据查询结果】，说明已经为用户自动查询了真实数据。
请基于这些真实数据直接告诉用户数据的内容，比如列出表中有哪些字段、前几行数据是什么。
如果数据较多，请概括总结数据的特征（如总行数、列名、数据类型等）。

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
            lines.append(f"- 用户: {cfg.get('user', 'N/A')}")
            lines.append(f"- 基础路径: {cfg.get('base_path', '/')}")

        if ds.table_metadata:
            table_names = [t.table_name for t in ds.table_metadata if t.table_name]
            if table_names:
                lines.append(f"- 包含的表/文件: {', '.join(table_names[:10])}")
                if len(table_names) > 10:
                    lines.append(f"  ...还有 {len(table_names) - 10} 个")

        lines.append("")

    # 当用户消息中提到了数据源名称时，自动查询实际数据
    data_previews = await _query_datasource_previews(sources, user_message)
    if data_previews:
        lines.append(data_previews)

    return "\n".join(lines)


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

    try:
        # 初始化技能库
        nl_svc = _get_nl_service()
        await nl_svc.skill_library.initialize()

        # 初始化LLM
        await llm_manager.initialize()

        # 调用NL处理服务进行意图识别和技能匹配
        nl_result = await _get_nl_service().process(
            text=request.content,
            context={"user_id": str(current_user.id)}
        )

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
        datasource_context = await build_datasource_context(
            db, current_user.id, request.content
        )

        # 构建 system prompt
        system_content = _build_system_prompt(datasource_context)

        # 组装 messages 列表
        messages = [{"role": "system", "content": system_content}]

        messages.extend(await _compress_history(history_messages, str(request.session_id)))

        messages.append({"role": "user", "content": request.content})

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

        try:
            user_message = ChatMessage(
                session_id=request.session_id,
                role="user",
                content=request.content,
            )
            db.add(user_message)
            await db.flush()

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

            datasource_context = await build_datasource_context(
                db, current_user.id, request.content
            )

            # 统一路由：始终从 data_processor 开始，Agent 自主决定是否 handoff（O）
            from app.services.multi_agent import AgentRuntime, AgentMessage, HandoffReason, agent_registry
            from app.services.data_processor_agent import DataProcessorAgent
            from app.services.data_inspector_agent import DataInspectorAgent

            if not agent_registry.get("data_processor"):
                agent_registry.register(DataProcessorAgent())
            if not agent_registry.get("data_inspector"):
                agent_registry.register(DataInspectorAgent())

            runtime = AgentRuntime(agent_registry, llm_manager)

            trace_id = str(uuid4())
            compressed_history = await _compress_history(history_messages, session_id)
            context = {
                "db": db,
                "user_id": current_user.id,
                "datasource_context": datasource_context,
                "persona": ASSISTANT_PERSONA,
                "session_id": session_id,
                "history": compressed_history,
                "has_preinjected_data": "实时数据查询结果" in datasource_context,
            }

            message = AgentMessage(
                from_agent="user",
                to_agent="data_processor",
                reason=HandoffReason.DELEGATE,
                payload={"user_message": request.content, "content": request.content},
                context=context,
                trace_id=trace_id,
            )

            full_response = ""
            async for event in runtime.run("data_processor", message, context):
                if cancel_event.is_set():
                    yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                    return

                if event.get("type") == "agent_switch":
                    yield f"data: {json.dumps({'type': 'agent_switch', 'agent': event['agent'], 'reason': event['reason']}, ensure_ascii=False)}\n\n"
                elif event.get("type") == "content":
                    content = event.get("content", "")
                    full_response += content
                    yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
                elif event.get("type") == "tool_result":
                    yield f"data: {json.dumps({'type': 'tool_result', 'content': event.get('content', '')[:200]}, ensure_ascii=False)}\n\n"
                elif event.get("type") == "done":
                    pass
                else:
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

            ai_message = ChatMessage(
                session_id=request.session_id,
                role="assistant",
                content=full_response,
            )
            db.add(ai_message)
            await db.flush()

            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式响应失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
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

@router.post("/process-data", response_model=NLDataProcessResponse)
async def process_data_with_natural_language(
    request: NLDataProcessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """使用自然语言处理数据"""
    try:
        import pandas as pd
        from app.services.nl_data_processor import nl_processor
        from app.services.skill_library import skill_library

        # 初始化技能库
        await skill_library.initialize()

        # 获取输入数据
        if request.data:
            input_df = pd.DataFrame(request.data)
        elif request.file_id:
            # 从文件加载数据
            result = await db.execute(
                select(FileLink).where(FileLink.id == request.file_id)
            )
            file_link = result.scalar_one_or_none()
            if not file_link:
                raise HTTPException(status_code=404, detail="文件不存在")

            # 根据文件类型加载
            file_path = file_link.file_path
            if file_path.endswith('.csv'):
                input_df = pd.read_csv(file_path)
            elif file_path.endswith('.xlsx') or file_path.endswith('.xls'):
                input_df = pd.read_excel(file_path)
            elif file_path.endswith('.json'):
                input_df = pd.read_json(file_path)
            else:
                raise HTTPException(status_code=400, detail="不支持的文件格式")
        else:
            raise HTTPException(status_code=400, detail="请提供数据或文件ID")

        # 构建处理请求
        from app.services.nl_data_processor import DataProcessingRequest
        process_request = DataProcessingRequest(
            natural_language=request.natural_language,
            input_data=input_df,
            session_id=str(request.session_id or uuid4()),
            context={"user_id": str(current_user.id)}
        )

        # 处理
        result = await nl_processor.process(process_request)

        # 转换输出数据为JSON格式
        output_json = None
        if result.output_data is not None:
            output_json = result.output_data.to_dict(orient="records")

        return NLDataProcessResponse(
            success=result.success,
            output_data=output_json,
            pipeline_name=result.pipeline_name,
            steps=result.steps,
            explanation=result.explanation,
            execution_time=result.execution_time,
            error=result.error,
            logs=result.logs
        )

    except Exception as e:
        logger.error(f"自然语言数据处理失败: {e}")
        return NLDataProcessResponse(
            success=False,
            error=str(e),
            logs=[f"处理失败: {e}"]
        )


@router.post("/process-data-stream")
async def process_data_streaming(
    request: NLDataProcessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式处理数据"""
    async def generate():
        try:
            import pandas as pd
            from app.services.nl_data_processor import nl_processor, DataProcessingRequest
            from app.services.skill_library import skill_library

            # 初始化技能库
            await skill_library.initialize()

            # 获取输入数据
            if request.data:
                input_df = pd.DataFrame(request.data)
            elif request.file_id:
                result = await db.execute(
                    select(FileLink).where(FileLink.id == request.file_id)
                )
                file_link = result.scalar_one_or_none()
                if not file_link:
                    yield f"data: {json.dumps({'type': 'error', 'message': '文件不存在'}, ensure_ascii=False)}\n\n"
                    return
                file_path = file_link.file_path
                if file_path.endswith('.csv'):
                    input_df = pd.read_csv(file_path)
                elif file_path.endswith('.xlsx'):
                    input_df = pd.read_excel(file_path)
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': '不支持的文件格式'}, ensure_ascii=False)}\n\n"
                    return
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': '请提供数据或文件ID'}, ensure_ascii=False)}\n\n"
                return

            # 构建处理请求
            process_request = DataProcessingRequest(
                natural_language=request.natural_language,
                input_data=input_df,
                session_id=str(request.session_id or uuid4()),
                context={"user_id": str(current_user.id)}
            )

            # 流式处理
            for event in await nl_processor.process_streaming(process_request):
                # 转换DataFrame为JSON
                if "preview" in event and event["preview"] is not None:
                    preview = event["preview"]
                    if "data" in preview and isinstance(preview["data"], list):
                        pass  # 已经是JSON格式

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"流式处理失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/skills")
async def list_available_skills():
    """列出可用技能"""
    from app.services.skill_library import skill_library
    await skill_library.initialize()
    skills = skill_library.list_skills()
    return {
        "skills": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "display_name": s.get("display_name"),
                "description": s.get("description"),
                "category": s.get("category"),
                "tags": s.get("tags", [])
            }
            for s in skills
        ]
    }
