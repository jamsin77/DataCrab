"""ChatAgent 通用对话智能体

处理闲聊/问候/系统配置/提问咨询等非数据操作。
拥有配置管理工具（save_llm_adapter/delete_llm_adapter/get_llm_config/save_connector/delete_connector）
和通用只读工具（web_fetch/kb_search/list_user_datasources）。

不参与 handoff（跟 DataAnalyst 一样独立）。
"""
import json
from typing import Dict, Any, AsyncGenerator, Optional

from loguru import logger

from app.services.multi_agent import BaseAgent, AgentMessage
from app.services.llm import llm_manager
from app.services.tool_registry import execute_tool, get_tool_schemas
from app.services.agent_utils import (
    StuckDetector,
    should_compact,
    compact_messages,
    build_tool_action_event,
)

CHAT_INSTRUCTIONS = """你是 DataCrab 的通用对话智能体，负责处理非数据操作的对话请求。

## 核心能力
- 联网查资料：通过 web_fetch 抓取网页内容（如官方文档、模型列表）
- 知识库检索：通过 kb_search 搜索已上传文档
- 平台配置管理：通过 save_llm_adapter/delete_llm_adapter/get_llm_config 管理 LLM Provider，通过 save_connector/delete_connector 管理数据源连接器
- 查看数据源列表：通过 list_user_datasources 列出用户数据源

## 工作准则
1. 用户要求查最新信息（如"GLM 有没有新模型"）时，必须调 web_fetch 抓取官网页面，不要说"我无法访问"
2. 用户要求添加/修改/删除 Provider 或连接器时，调用相应配置工具
3. 不处理数据查询/清洗/转换——引导用户描述数据任务
4. 回复简洁直接，中文优先
"""


_MAIN_STATIC_PROMPT_CACHE: Optional[str] = None


def _format_tool_summary(content: str) -> str:
    """把工具返回的 JSON 格式化成可读摘要。"""
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            return content[:200]
        if data.get("error"):
            return f"❌ {data['error'][:200]}"
        if data.get("success"):
            return f"✅ {data.get('message', '操作成功')[:200]}"
        if "datasources" in data:
            _names = [d.get("name", "?") for d in data["datasources"][:5]]
            _more = f" 等{len(data['datasources'])}个" if len(data["datasources"]) > 5 else ""
            return f"找到数据源：{', '.join(_names)}{_more}"
        if "file_links" in data:
            _names = [l.get("name", "?") for l in data["file_links"][:5]]
            return f"文件链接：{', '.join(_names) or '无'}"
        if "providers" in data:
            _names = [p.get("name", "?") for p in data["providers"][:8]]
            return f"已注册 Provider：{', '.join(_names)}"
        if "available_models" in data:
            _models = [m.get("model", "?") for m in data["available_models"][:5]]
            return f"可用模型：{', '.join(_models)}"
        if "url" in data and "content" in data:
            _len = len(data["content"])
            return f"已抓取网页（{_len} 字符）：{data['url'][:60]}"
        if "results" in data:
            _n = len(data["results"])
            return f"检索到 {_n} 条结果" if _n else "未检索到结果"
        # 兜底：取关键字段
        for k in ("message", "status", "content"):
            if data.get(k):
                return str(data[k])[:200]
        return content[:200]
    except (json.JSONDecodeError, TypeError):
        return content[:200]


class ChatAgent(BaseAgent):
    name = "chat_agent"
    display_name = "通用对话智能体"
    description = "闲聊/咨询/系统配置管理（Provider/连接器）"
    instructions = CHAT_INSTRUCTIONS
    tools = get_tool_schemas([
        "web_fetch", "kb_search", "list_user_datasources",
        "get_llm_config", "save_llm_adapter", "delete_llm_adapter",
        "save_connector", "delete_connector",
    ])
    capabilities = ["chat", "platform_config", "web_fetch"]

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        global _MAIN_STATIC_PROMPT_CACHE
        if _MAIN_STATIC_PROMPT_CACHE is not None:
            return _MAIN_STATIC_PROMPT_CACHE
        prompt = self.instructions
        from app.services.tool_guidance import get_tool_guidance
        prompt += "\n\n" + get_tool_guidance()
        _MAIN_STATIC_PROMPT_CACHE = prompt
        return prompt

    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        from sqlalchemy.ext.asyncio import AsyncSession
        db: AsyncSession = context.get("db")
        user_id = context.get("user_id")

        if not db or not user_id:
            yield {"type": "done", "result": {"error": "缺少数据库会话或用户ID"}}
            return

        await llm_manager.initialize()

        system_prompt = self.build_system_prompt(context)
        local_messages = [{"role": "system", "content": system_prompt}]

        # persona 注入
        import os
        _persona_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        _persona_path = os.path.join(_persona_dir, "services", "soul.md")
        if os.path.exists(_persona_path):
            with open(_persona_path, "r", encoding="utf-8") as f:
                local_messages.insert(0, {"role": "system", "content": f.read().strip()})

        history = context.get("history", [])
        if history:
            local_messages.extend(history)

        # 注入上次操作对象上下文（让 LLM 知道用户上次改的是哪个 Provider/连接器）
        _last_target = context.get("last_config_target", "")
        if _last_target:
            local_messages.append({"role": "system", "content": f"提示：用户上次操作的配置对象是「{_last_target}」。当用户说改回来或刷新一下时，默认指这个对象，除非用户明确指定其他对象。"})

        if message.payload:
            user_msg = message.payload.get("user_message", message.payload.get("content", ""))
            if user_msg:
                local_messages.append({"role": "user", "content": user_msg})
        else:
            yield {"type": "done", "result": {"error": "空消息"}}
            return

        stuck_detector = StuckDetector(max_total_rounds=10)

        for i in range(10):
            if should_compact(local_messages):
                local_messages = await compact_messages(local_messages, llm_manager)

            content = ""
            tool_calls = []

            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=self.tools, temperature=0.3,
                model=llm_manager._default, tool_choice="auto",
            ):
                t = event["type"]
                if t == "model":
                    yield event
                elif t == "thinking":
                    yield event
                elif t == "content":
                    content += event["content"]
                elif t == "tool_calls":
                    tool_calls = event["tool_calls"]

            if not tool_calls:
                intervention = stuck_detector.record_idle()
                if intervention and i < 9:
                    local_messages.append({"role": "assistant", "content": content})
                    local_messages.append({"role": "user", "content": intervention})
                    continue

                if content:
                    yield {"type": "content", "content": content}
                yield {"type": "done", "result": {"agent": self.name, "content": content}}
                return

            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                intervention = stuck_detector.record_tool_call(tc["function"]["name"], args)
                if intervention:
                    local_messages.append({"role": "user", "content": intervention})

            if content:
                yield {"type": "content", "content": content}

            if tool_calls:
                yield build_tool_action_event(tool_calls)

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            import asyncio
            async def _safe_exec(tc):
                try:
                    _args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    _args = {}
                try:
                    _r = await execute_tool(tc["function"]["name"], _args, db, user_id, context)
                    return {"tool_call_id": tc["id"], "content": _r}
                except Exception as e:
                    logger.error(f"ChatAgent 工具异常 {tc['function']['name']}: {e}")
                    return {"tool_call_id": tc["id"], "content": json.dumps({"error": str(e)}, ensure_ascii=False)}

            results = await asyncio.gather(*[_safe_exec(tc) for tc in tool_calls])

            # 记录配置操作对象到 context（供下次对话使用）
            for tc in tool_calls:
                _tname = tc["function"]["name"]
                try:
                    _targs = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    _targs = {}
                if _tname in ("save_llm_adapter", "delete_llm_adapter", "get_llm_config"):
                    _provider = _targs.get("provider_name", "")
                    if _provider:
                        context["last_config_target"] = f"LLM Provider: {_provider}"
                        logger.info(f"[ChatAgent] last_config_target = Provider:{_provider}")
                elif _tname in ("save_connector", "delete_connector"):
                    _connector = _targs.get("name", "")
                    if _connector:
                        context["last_config_target"] = f"数据源连接器: {_connector}"
                        logger.info(f"[ChatAgent] last_config_target = Connector:{_connector}")

            for r in results:
                from app.services.agent_utils import truncate_tool_result
                _tc_content = truncate_tool_result(r["content"])
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": _tc_content})
                # 生成可读摘要（不直接显示原始 JSON）
                _summary = _format_tool_summary(r["content"])
                yield {"type": "tool_summary", "summaries": [_summary]}
