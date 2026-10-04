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
            if session_ctx.get("source_datasource_name") and session_ctx.get("source_data_name"):
                _ctx_lines.append(f"当前源表：{session_ctx['source_datasource_name']} → {session_ctx['source_data_name']}")
            if session_ctx.get("target_datasource_name") and session_ctx.get("target_data_name"):
                _ctx_lines.append(f"当前目标表：{session_ctx['target_datasource_name']} → {session_ctx['target_data_name']}")
            if session_ctx.get("last_skill_name"):
                _ctx_lines.append(f"当前技能：{session_ctx['last_skill_name']}")
            elif session_ctx.get("last_pipeline_name"):
                _ctx_lines.append(f"当前流程：{session_ctx['last_pipeline_name']}")
        _ctx_block = "\n".join(_ctx_lines) if _ctx_lines else "（无已选数据）"

        prompt = (
            "判断用户消息，输出四个词用 | 分隔，不要解释，不要推理：\n"
            "1. 类型：analysis / processing / chat\n"
            "   - analysis：用户想分析数据内容，不改变数据本身\n"
            "   - processing：用户想对数据进行加工处理，使其发生变化\n"
            "   - chat：其他一切——闲聊提问、平台配置管理（查看/修改/添加 Provider、模型、API Key、数据源连接器、备注说明）、系统操作咨询等。注意：'刷新列表''加备注''改配置'这类针对平台设置的操作不算 processing\n"
            "2. 源数据表：keep 或 change（当前数据表不适合当前需求时 change，继续用才 keep）\n"
            "3. 目标数据表：keep 或 change（当前目标表不适合当前需求时 change）\n"
            "4. 技能：keep 或 change（当前技能不适合当前需求时 change）\n"
            f"\n当前已选数据：\n{_ctx_block}\n"
            f"\n用户消息：{user_message}\n"
            "只输出四个词用 | 分隔，例如：analysis|change|keep|keep"
        )

        events = []
        resp = await llm_manager.chat_with_messages(
            messages=[{"role": "user", "content": prompt}],
            model=llm_manager._flash, temperature=0.0, enable_thinking=False,
        )
        resp = resp.strip().lower()
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


async def extract_params(user_message: str, session_ctx: dict | None = None) -> dict:
    """从用户补充消息中提取数据任务缺失参数（目标数据源/目标表/写入策略）。

    仅在上一轮提示缺参数后调用——用户的补充说明（如"目标跟源相同""表名你定"）
    不该当成新任务重新匹配技能，而应提取为参数。

    Returns:
        {"target_datasource": str, "target_table": str, "write_mode": str}
        - target_datasource: 数据源名 / "same_as_source"（目标与源相同）/ 空（未提及）
        - target_table: 表名 / "auto"（用户让自动定义）/ 空（未提及）
        - write_mode: overwrite/append/create/direct / 空（未提及）
        用户在描述全新任务时全字段为空。
    """
    _empty = {"target_datasource": "", "target_table": "", "write_mode": ""}
    if not user_message:
        return _empty
    try:
        from app.services.llm import llm_manager

        _ctx_lines = []
        if session_ctx:
            if session_ctx.get("source_datasource_name") and session_ctx.get("source_data_name"):
                _ctx_lines.append(f"源数据源：{session_ctx['source_datasource_name']}，源表：{session_ctx['source_data_name']}")
            if session_ctx.get("target_datasource_name"):
                _ctx_lines.append(f"目标数据源：{session_ctx['target_datasource_name']}")
            if session_ctx.get("target_data_name"):
                _ctx_lines.append(f"目标表：{session_ctx['target_data_name']}")
        _ctx_block = "；".join(_ctx_lines) if _ctx_lines else "（无）"

        prompt = (
            "用户上一个数据任务缺少参数，现在发来的消息可能是参数补充说明。从消息中提取参数信息。\n"
            f"当前任务已选参数：{_ctx_block}\n\n"
            f"用户消息：{user_message}\n\n"
            "输出 JSON（不要解释，不要推理）：\n"
            '{"target_datasource": "数据源名称；用户说目标与源相同/同一个/写回源里则输出 same_as_source；未提及输出空字符串", '
            '"target_table": "表名；用户说你自己定/随便取/自动生成则输出 auto；未提及输出空字符串", '
            '"write_mode": "覆盖=overwrite/追加=append/新建表=create/直接使用=direct；未提及输出空字符串"}\n'
            "注意：如果用户在描述一个全新的任务（换数据换需求）而不是给当前任务补参数，所有字段输出空字符串。"
        )
        resp = await llm_manager.chat_with_messages(
            messages=[{"role": "user", "content": prompt}],
            model=llm_manager._flash, temperature=0.0, enable_thinking=False,
        )
        logger.info(f"[extract_params] msg={user_message[:80]!r}")
        logger.info(f"[extract_params] LLM raw resp={resp!r}")

        import json as _json
        import re as _re
        m = _re.search(r"\{.*\}", resp, _re.DOTALL)
        if not m:
            return _empty
        data = _json.loads(m.group(0))
        return {
            "target_datasource": str(data.get("target_datasource", "") or "").strip(),
            "target_table": str(data.get("target_table", "") or "").strip(),
            "write_mode": str(data.get("write_mode", "") or "").strip(),
        }
    except Exception as e:
        logger.error(f"[extract_params] LLM 调用失败: {e}")
        return _empty
