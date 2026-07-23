"""Agent服务 - 赋予LLM实际执行操作的能力

改进点：
- 工具定义和实现使用 shared_tools（去重 F）
- 工具结果自动截断（E，在 shared_tools 内实现）
- StuckDetector 卡死检测（J）
- 反幻觉检查：防"只规划不执行"（K）+ 无工具支撑的数据声明警告（P）
- delegate_to_inspector 工具：Agent 自主决定是否交接检查（O）
- 动态轮次预算（Q）：按任务复杂度分配迭代上限
- 上下文压力主动告警（R）：50%/60% 阈值注入提示
- 三级反幻觉注入（T）：standard 级别
"""

import json
import asyncio
from typing import Dict, Any, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm import llm_manager
from app.models.datasource import DataSource
from app.models.filelink import FileLink
from app.services.connectors import get_connector
from app.services.shared_tools import SHARED_TOOL_SCHEMAS, execute_shared_tool
from app.services.agent_utils import (
    StuckDetector,
    should_warn_ungrounded_claim,
    estimate_complexity,
    get_turn_budget,
    get_context_pressure_level,
    build_pressure_warning,
    get_anti_hallucination_section,
)
from loguru import logger

# Agent 自主 handoff 工具（O）：让 Agent 自己决定是否需要检查
DELEGATE_TOOL = {
    "type": "function",
    "function": {
        "name": "delegate_to_inspector",
        "description": "将当前数据处理结果交接给 DataInspector 进行质量检查。当你认为数据处理已完成、需要验证质量或用户要求检查时调用",
        "parameters": {
            "type": "object",
            "properties": {
                "datasource_id": {"type": "string", "description": "数据源ID"},
                "table_name": {"type": "string", "description": "检查的表名"},
                "operation_description": {"type": "string", "description": "本次数据处理的操作描述"},
                "result_summary": {"type": "string", "description": "处理结果摘要"},
            },
            "required": ["datasource_id", "table_name"],
        },
    },
}

TOOLS = SHARED_TOOL_SCHEMAS + [DELEGATE_TOOL]


@dataclass
class AgentContext:
    db: AsyncSession
    user_id: UUID
    datasource_context: str = ""
    persona: str = ""


class AgentService:
    """Agent服务 - 让LLM可以调用工具执行实际操作"""

    def __init__(self):
        self.tools = TOOLS

    async def _execute_tool(self, name: str, arguments: dict, ctx: AgentContext) -> str:
        logger.info(f"Agent执行工具: {name}")

        if name == "delegate_to_inspector":
            return json.dumps({
                "_delegate": True,
                "to": "data_inspector",
                "payload": {
                    "datasource_id": arguments.get("datasource_id", ""),
                    "table_name": arguments.get("table_name", ""),
                    "operation_description": arguments.get("operation_description", ""),
                    "result_summary": arguments.get("result_summary", ""),
                },
            }, ensure_ascii=False)

        return await execute_shared_tool(name, arguments, ctx.db, ctx.user_id)

    async def _execute_tool_calls_parallel(self, tool_calls: list, ctx: AgentContext) -> list:
        """并行执行多个独立工具调用，返回结果列表"""
        async def _safe_execute(tc):
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}
            result = await self._execute_tool(tc["function"]["name"], func_args, ctx)
            return {"tool_call_id": tc["id"], "content": result, "tool_name": tc["function"]["name"]}

        results = await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])
        return list(results)

    async def run(self, messages: List[Dict[str, str]], ctx: AgentContext) -> str:
        await llm_manager.initialize()
        local_messages = list(messages)
        stuck_detector = StuckDetector()

        # 动态轮次预算（Q）：按用户消息复杂度分配迭代上限
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break
        complexity = estimate_complexity(user_msg)
        max_iterations = get_turn_budget(complexity)
        logger.info(f"Agent run: complexity={complexity}, budget={max_iterations} turns")

        had_any_tool_calls = False
        pressure_warned = False
        has_preinjected = "实时数据查询结果" in ctx.datasource_context

        for i in range(max_iterations):
            response = await llm_manager.chat_with_tools(
                messages=local_messages, tools=self.tools, temperature=0.3
            )
            tool_calls = response.get("tool_calls", [])
            finish_reason = response.get("finish_reason")

            if not tool_calls:
                content = response.get("content", "")

                # 反幻觉：无工具支撑的数据声明警告（P）
                # 例外：system prompt 已预注入实时数据时跳过
                if not had_any_tool_calls and not has_preinjected:
                    warn = should_warn_ungrounded_claim(content, had_tool_calls_this_turn=False)
                    if warn and i < max_iterations - 1:
                        local_messages.append({"role": "assistant", "content": content})
                        local_messages.append({"role": "user", "content": warn})
                        continue

                # 卡死检测：空转检查
                intervention = stuck_detector.record_idle()
                if intervention and i < max_iterations - 1:
                    local_messages.append({"role": "assistant", "content": content})
                    local_messages.append({"role": "user", "content": intervention})
                    continue

                return content

            had_any_tool_calls = True

            # 卡死检测：重复调用检查
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                intervention = stuck_detector.record_tool_call(tc["function"]["name"], args)
                if intervention:
                    local_messages.append({"role": "user", "content": intervention})

            local_messages.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            results = await self._execute_tool_calls_parallel(tool_calls, ctx)
            for r in results:
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]})

            # 上下文压力主动告警（R）
            level, ratio = get_context_pressure_level(local_messages)
            if level > 0 and not pressure_warned:
                warning = build_pressure_warning(level, ratio)
                if warning:
                    local_messages.append({"role": "user", "content": warning})
                    pressure_warned = True
                    logger.info(f"上下文压力告警: level={level}, ratio={ratio:.1%}")

        return "处理超时，请简化您的问题后重试。"

    async def run_stream(self, messages: List[Dict[str, str]], ctx: AgentContext) -> AsyncGenerator[str, None]:
        await llm_manager.initialize()
        local_messages = list(messages)
        stuck_detector = StuckDetector()

        # 动态轮次预算（Q）
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break
        complexity = estimate_complexity(user_msg)
        max_iterations = get_turn_budget(complexity)
        logger.info(f"Agent run_stream: complexity={complexity}, budget={max_iterations} turns")

        had_any_tool_calls = False
        pressure_warned = False
        has_preinjected = "实时数据查询结果" in ctx.datasource_context

        for i in range(max_iterations):
            response = await llm_manager.chat_with_tools(
                messages=local_messages, tools=self.tools, temperature=0.3
            )
            tool_calls = response.get("tool_calls", [])
            finish_reason = response.get("finish_reason")

            if not tool_calls:
                content = response.get("content", "")

                # 反幻觉：无工具支撑的数据声明警告（P）
                # 例外：system prompt 已预注入实时数据时跳过
                if not had_any_tool_calls and not has_preinjected:
                    warn = should_warn_ungrounded_claim(content, had_tool_calls_this_turn=False)
                    if warn and i < max_iterations - 1:
                        local_messages.append({"role": "assistant", "content": content})
                        local_messages.append({"role": "user", "content": warn})
                        continue

                # 卡死检测：空转检查
                intervention = stuck_detector.record_idle()
                if intervention and i < max_iterations - 1:
                    local_messages.append({"role": "assistant", "content": content})
                    local_messages.append({"role": "user", "content": intervention})
                    continue

                if content:
                    yield {"type": "content", "content": content}
                yield {"type": "done", "result": {"agent": self.name, "content": content}}
                return

            had_any_tool_calls = True

            # 卡死检测：重复调用检查
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                intervention = stuck_detector.record_tool_call(tc["function"]["name"], args)
                if intervention:
                    local_messages.append({"role": "user", "content": intervention})

            content = response.get("content") or ""
            if content:
                yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'status', 'content': f'正在执行 {len(tool_calls)} 个操作...'}, ensure_ascii=False)}\n\n"

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            results = await self._execute_tool_calls_parallel(tool_calls, ctx)
            for r in results:
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]})
                # 检测 delegate 信号
                if r.get("tool_name") == "delegate_to_inspector":
                    try:
                        data = json.loads(r["content"])
                        if data.get("_delegate"):
                            yield f"data: {json.dumps({'type': 'delegate', 'to': data['to'], 'payload': data['payload']}, ensure_ascii=False)}\n\n"
                    except (json.JSONDecodeError, KeyError):
                        pass

            # 上下文压力主动告警（R）
            level, ratio = get_context_pressure_level(local_messages)
            if level > 0 and not pressure_warned:
                warning = build_pressure_warning(level, ratio)
                if warning:
                    local_messages.append({"role": "user", "content": warning})
                    pressure_warned = True
                    logger.info(f"上下文压力告警: level={level}, ratio={ratio:.1%}")

        yield f"data: {json.dumps({'type': 'content', 'content': '处理超时，请简化您的问题后重试。'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"


agent_service = AgentService()
