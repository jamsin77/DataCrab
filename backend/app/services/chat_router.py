"""对话路由器——一次 LLM 调用判断消息类型 + 是否继续用当前已选数据/流程/技能。

不使用关键词匹配（关键词列表永远列不全），完全靠 LLM 语义判断。
LLM 不可用时用默认值兜底，不用关键词。
"""

from loguru import logger


async def classify_message(user_message: str, session_ctx: dict | None = None) -> tuple:
    """一次 LLM 调用判断消息类型 + 是否继续用当前已选源表/目标表/流程/技能。

    把当前已选数据（数据源名/表名/技能名）传给 LLM，让它能判断用户是否在要求换。
    默认 keep，只有用户明确要换才 change。

    Args:
        user_message: 用户消息
        session_ctx: 会话上下文（提供当前已选数据源/表名/技能名供 LLM 判断）

    Returns:
        (msg_type, keep_source, keep_target, keep_skill, events)
        - msg_type: "analysis" / "processing" / "chat"
        - keep_source: True=继续用当前源表，False=换/重新匹配
        - keep_target: True=继续用当前目标表，False=换/重新匹配
        - keep_skill: True=继续用当前技能/流程，False=换/重新匹配
        - events: 流式事件列表
    """
    if not user_message:
        return "chat", False, False, False, []
    try:
        from app.services.llm import llm_manager

        # 构建当前已选数据上下文（让 LLM 能判断用户是否在要求换）
        _ctx_lines = []
        if session_ctx:
            if session_ctx.get("source_datasource_name") and session_ctx.get("source_table_name"):
                _ctx_lines.append(f"当前源表：{session_ctx['source_datasource_name']} → {session_ctx['source_table_name']}")
            if session_ctx.get("target_datasource_name") and session_ctx.get("target_table_name"):
                _ctx_lines.append(f"当前目标表：{session_ctx['target_datasource_name']} → {session_ctx['target_table_name']}")
            if session_ctx.get("last_skill_name"):
                _ctx_lines.append(f"当前技能：{session_ctx['last_skill_name']}")
            elif session_ctx.get("last_pipeline_name"):
                _ctx_lines.append(f"当前流程：{session_ctx['last_pipeline_name']}")
        _ctx_block = "\n".join(_ctx_lines) if _ctx_lines else "（无已选数据）"

        prompt = (
            "判断用户消息，输出四个词用 | 分隔，不要解释：\n"
            "1. 类型：analysis / processing / chat\n"
            "   - analysis：只读分析（查看/统计/查找/浏览数据，不修改）\n"
            "   - processing：数据处理（清洗/转换/加工/导入/导出/迁移/修改/合并等数据操作）\n"
            "   - chat：闲聊/问候/提问/咨询/平台配置管理（模型Provider/数据源连接器等配置操作）\n"
            "2. 源数据表：keep 或 change（用户要换另一张表/数据源才 change，继续用当前表才 keep）\n"
            "3. 目标数据表：keep 或 change（用户要换另一张目标表才 change）\n"
            "4. 技能：keep 或 change（用户要换技能才 change）\n"
            f"\n当前已选数据：\n{_ctx_block}\n"
            f"\n用户消息：{user_message}"
        )

        events = []
        resp_text = ""
        async for event in llm_manager.chat_stream_with_thinking(
            messages=[{"role": "user", "content": prompt}],
            model=llm_manager._flash, temperature=0.0,
        ):
            events.append(event)
            if event.get("type") == "content":
                resp_text += event["content"]
        resp = resp_text.strip().lower()
        logger.info(f"[classify] msg={user_message[:80]!r}")
        logger.info(f"[classify] ctx_block={_ctx_block!r}")
        logger.info(f"[classify] LLM raw resp={resp!r}")

        _type = "chat"
        _keep_source = True
        _keep_target = True
        _keep_skill = True

        parts = resp.split("|")
        logger.info(f"[classify] parts={parts}")
        if parts and parts[0].strip():
            _first = parts[0].strip()
            if "analysis" in _first:
                _type = "analysis"
            elif "processing" in _first:
                _type = "processing"
            elif "chat" in _first:
                _type = "chat"

        if len(parts) >= 2:
            _keep_source = "change" not in parts[1].strip()
        if len(parts) >= 3:
            _keep_target = "change" not in parts[2].strip()
        if len(parts) >= 4:
            _keep_skill = "change" not in parts[3].strip()

        logger.info(f"[classify] result: type={_type} keep_source={_keep_source} keep_target={_keep_target} keep_skill={_keep_skill}")
        return _type, _keep_source, _keep_target, _keep_skill, events
    except Exception as e:
        logger.error(f"[classify] LLM 调用失败: {e}")
        events = [{"type": "error", "content": f"❌ 路由判断失败: {e}"}]
        return "chat", False, False, False, events
