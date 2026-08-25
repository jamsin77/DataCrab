"""对话路由器——一次 LLM 调用判断消息类型 + 是否继续用当前已选数据。

不使用关键词匹配（关键词列表永远列不全），完全靠 LLM 语义判断。
LLM 不可用时用默认值兜底，不用关键词。
"""

from loguru import logger


async def classify_message(user_message: str, session_ctx: dict | None = None) -> tuple:
    """一次 LLM 调用判断消息类型 + 是否继续用当前已选数据。

    Args:
        user_message: 用户消息
        session_ctx: 会话上下文（含 source_datasource_name/source_table_name），可选

    Returns:
        (msg_type, keep_data, events)
        - msg_type: "analysis" / "processing" / "chat"
        - keep_data: True=继续用当前已选数据（跳过数据表匹配），False=换/重新选或无已选数据
        - events: 流式事件列表
    """
    if not user_message:
        return "chat", False, []
    try:
        from app.services.llm import llm_manager
        _ds = (session_ctx or {}).get("source_datasource_name", "")
        _tbl = (session_ctx or {}).get("source_table_name", "")
        _has_data = bool(_ds)
        prompt = (
            "判断用户消息，只输出两个词用 | 分隔，不要解释：\n"
            "1. 类型：analysis / processing / chat\n"
            "   - analysis：只读分析（查看/统计/查找/浏览数据，不修改）\n"
            "   - processing：数据处理（清洗/转换/导入导出/脱敏等修改）\n"
            "   - chat：闲聊/问候/设置\n"
            "2. 数据：keep 或 change\n"
        )
        if _has_data:
            prompt += (
                f"   当前已选数据源：{_ds}，数据表：{_tbl}\n"
                "   判断依据：用户是否要选择或者查看新数据？\n"
                "   - keep：用户在说当前已选的数据\n"
                "   - change：用户在说当前数据之外的其他数据\n"
            )
        prompt += f"\n用户消息：{user_message}"
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
        logger.info(f"[classify] msg={user_message[:50]!r} resp={resp!r}")
        _type = "processing"
        _keep = False
        if "analysis" in resp:
            _type = "analysis"
        elif "chat" in resp:
            _type = "chat"
        if _has_data and "keep" in resp:
            _keep = True
        return _type, _keep, events
    except Exception:
        return "processing", False, []

