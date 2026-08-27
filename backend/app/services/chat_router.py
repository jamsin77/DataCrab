"""对话路由器——一次 LLM 调用判断消息类型 + 是否继续用当前已选数据/流程/技能。

不使用关键词匹配（关键词列表永远列不全），完全靠 LLM 语义判断。
LLM 不可用时用默认值兜底，不用关键词。
"""

from loguru import logger


async def classify_message(user_message: str, session_ctx: dict | None = None) -> tuple:
    """一次 LLM 调用判断消息类型 + 是否继续用当前已选源表/目标表/流程/技能。

    完全靠 LLM 根据用户消息判断意图，不传 context 信息。
    默认 keep，只有用户明确说换才 change。

    Args:
        user_message: 用户消息
        session_ctx: 会话上下文（保留参数兼容，不使用）

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

        prompt = (
            "判断用户消息，输出四个词用 | 分隔，不要解释：\n"
            "1. 类型：analysis / processing / chat\n"
            "   - analysis：只读分析（查看/统计/查找/浏览数据，不修改）\n"
            "   - processing：数据处理（清洗/转换/导入导出/脱敏等修改）\n"
            "   - chat：闲聊/问候/设置\n"
            "2. 源数据表：keep 或 change（默认 keep，用户要更换源表才 change）\n"
            "3. 目标数据表：keep 或 change（默认 keep，用户要更换目标表才 change）\n"
            "4. 技能：keep 或 change（默认 keep，用户要更换技能才 change）\n"
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
        logger.info(f"[classify] msg={user_message[:50]!r} resp={resp!r}")

        _type = "processing"
        _keep_source = True
        _keep_target = True
        _keep_skill = True

        if "analysis" in resp:
            _type = "analysis"
        elif "chat" in resp:
            _type = "chat"

        parts = resp.split("|")
        if len(parts) >= 2:
            _keep_source = "change" not in parts[1].strip()
        if len(parts) >= 3:
            _keep_target = "change" not in parts[2].strip()
        if len(parts) >= 4:
            _keep_skill = "change" not in parts[3].strip()

        return _type, _keep_source, _keep_target, _keep_skill, events
    except Exception:
        return "processing", False, False, False, []
