"""DataAnalyst 数据分析智能体

定位：只读分析——查询、统计、分布、洞察。不修改数据/脚本，不参与 handoff。
信息链简单线性：system + user + tool + 结论。

与 DataProcessor 的边界：
- 只查不改 → DataAnalyst
- 要修改数据/脚本 → DataProcessor
"""

import json
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.services.multi_agent import BaseAgent, AgentMessage
from app.services.llm import llm_manager
from app.services.shared_tools import execute_shared_tool, ANALYSIS_TOOLS
from app.services.agent_utils import (
    truncate_tool_result,
    StuckDetector,
    estimate_complexity,
    get_turn_budget,
    should_warn_ungrounded_claim,
    get_context_pressure_level,
    build_pressure_warning,
    should_compact,
    compact_messages,
    get_anti_hallucination_section,
)
from app.services.tool_guidance import get_tool_guidance

# 分析场景更大的截断阈值（需要看更多数据做分析）
ANALYSIS_MAX_TOOL_RESULT_CHARS = 30000
ANALYSIS_MAX_PREVIEW_ROWS = 50


def _truncate_analysis_result(result_str: str) -> str:
    """分析场景截断：保留更多数据行（50行），截断时提示分页"""
    if not result_str or len(result_str) <= ANALYSIS_MAX_TOOL_RESULT_CHARS:
        return result_str
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return result_str[:ANALYSIS_MAX_TOOL_RESULT_CHARS] + "\n\n... [结果过大已截断]"
    if isinstance(data, dict):
        truncated = dict(data)
        rows = truncated.get("rows")
        if isinstance(rows, list) and len(rows) > ANALYSIS_MAX_PREVIEW_ROWS:
            truncated["rows_preview"] = rows[:ANALYSIS_MAX_PREVIEW_ROWS]
            truncated["rows"] = f"[已截断：共 {len(rows)} 行，已显示前 {ANALYSIS_MAX_PREVIEW_ROWS} 行。用 offset 分页获取后续数据]"
            truncated["truncated"] = True
        result = json.dumps(truncated, ensure_ascii=False, default=str)
        if len(result) > ANALYSIS_MAX_TOOL_RESULT_CHARS:
            if isinstance(data.get("rows"), list):
                data["rows"] = f"[已截断：共 {len(data['rows'])} 行，已显示前 {ANALYSIS_MAX_PREVIEW_ROWS} 行]"
                data["rows_preview"] = data["rows"][:ANALYSIS_MAX_PREVIEW_ROWS] if isinstance(data.get("rows"), list) else []
            result = json.dumps(data, ensure_ascii=False, default=str)[:ANALYSIS_MAX_TOOL_RESULT_CHARS]
        return result
    return result_str[:ANALYSIS_MAX_TOOL_RESULT_CHARS] + "\n\n... [结果过大已截断]"


DATA_ANALYST_INSTRUCTIONS = """你是 DataCrab 的 DataAnalyst（数据分析智能体），一位数据分析专家。

## 核心能力
- 擅长数据查询、统计分析、数据分布洞察
- 能编写 SQL 进行复杂查询（聚合、分组、窗口函数）
- 能理解数据结构并给出分析结论

## 工作准则
1. 只读不写：你只负责查询和分析，不修改数据、不生成脚本、不创建算子
2. 准确优先：所有数据结论必须基于工具返回的实际数据，不得编造
3. 先查后说：提到表名/列名前先调 get_table_schema 确认结构；报告数据前先调 query_table_data/execute_sql 获取实际数据
4. 分析深度：不只是罗列数据，要给出分布特征、异常点、趋势洞察
5. 分页意识：大表用 limit/offset 分页查询，避免一次加载过多数据

## 不负责的事
- 数据清洗/转换/写入 → 交给 DataProcessor
- 生成/修改技能/算子脚本 → 交给 DataProcessor
- 数据质量检查 → 交给 DataInspector
"""

_MAIN_STATIC_PROMPT_CACHE: Optional[str] = None


class DataAnalystAgent(BaseAgent):
    name = "data_analyst"
    display_name = "数据分析智能体"
    description = "只读数据查询、统计分析、分布洞察"
    instructions = DATA_ANALYST_INSTRUCTIONS
    tools = ANALYSIS_TOOLS
    capabilities = ["data_query", "data_analysis"]

    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        db: AsyncSession = context.get("db")
        user_id = context.get("user_id")

        if not db or not user_id:
            yield {"type": "done", "result": {"error": "缺少数据库会话或用户ID"}}
            return

        await llm_manager.initialize()

        system_prompt = self.build_system_prompt(context)
        local_messages = [{"role": "system", "content": system_prompt}]

        history = context.get("history", [])
        if history:
            local_messages.extend(history)

        _datasource_ctx = context.get("datasource_context", "")

        if message.payload:
            user_msg = message.payload.get("user_message", message.payload.get("content", ""))
            if user_msg:
                if _datasource_ctx:
                    user_msg = _datasource_ctx + "\n\n---\n\n" + user_msg
                local_messages.append({"role": "user", "content": user_msg})
        else:
            yield {"type": "done", "result": {"error": "空消息"}}
            return

        stuck_detector = StuckDetector(max_total_rounds=15)

        user_msg = message.payload.get("user_message", message.payload.get("content", ""))
        complexity = estimate_complexity(user_msg)
        max_iterations = get_turn_budget(complexity)
        logger.info(f"DataAnalyst: complexity={complexity}, budget={max_iterations} turns")

        had_any_tool_calls = False
        pressure_warned = False
        has_preinjected_data = context.get("has_preinjected_data", False)

        for i in range(max_iterations):
            if should_compact(local_messages):
                local_messages = await compact_messages(local_messages, llm_manager)

            response = await llm_manager.chat_with_tools(
                messages=local_messages, tools=self.tools, model=llm_manager._default,
                temperature=0.3
            )
            if response is None:
                yield {"type": "content", "content": "所有模型均不可用，请稍后重试或检查模型配置。"}
                yield {"type": "done", "result": {"agent": self.name, "content": "模型不可用"}}
                return
            if i == 0:
                yield {"type": "model", "content": llm_manager._default}
            tool_calls = response.get("tool_calls", [])
            finish_reason = response.get("finish_reason")

            reasoning = response.get("reasoning")
            if reasoning:
                yield {"type": "thinking", "content": reasoning}

            if not tool_calls:
                content = response.get("content", "")

                if not had_any_tool_calls and not has_preinjected_data:
                    warn = should_warn_ungrounded_claim(content, had_tool_calls_this_turn=False)
                    if warn and i < max_iterations - 1:
                        local_messages.append({"role": "assistant", "content": content})
                        local_messages.append({"role": "user", "content": warn})
                        continue

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
                yield {"type": "content", "content": content}

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            # 执行工具
            async def _safe_execute(tc):
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    func_args = {}
                try:
                    result = await execute_shared_tool(tc["function"]["name"], func_args, db, user_id)
                    return {"tool_call_id": tc["id"], "content": result}
                except Exception as e:
                    logger.error(f"DataAnalyst 工具异常 {tc['function']['name']}: {e}")
                    return {"tool_call_id": tc["id"], "content": json.dumps({"error": f"工具执行失败: {e}"}, ensure_ascii=False)}

            results = await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])
            for r in results:
                _truncated = _truncate_analysis_result(r["content"])
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": _truncated})
                yield {"type": "tool_result", "tool_call_id": r["tool_call_id"], "content": r["content"]}

            level, ratio = get_context_pressure_level(local_messages)
            if level > 0 and not pressure_warned:
                warning = build_pressure_warning(level, ratio)
                if warning:
                    local_messages.append({"role": "user", "content": warning})
                    pressure_warned = True
                    logger.info(f"DataAnalyst 上下文压力告警: level={level}, ratio={ratio:.1%}")

        yield {"type": "content", "content": "分析超时，请简化您的问题后重试。"}
        yield {"type": "done", "result": {"agent": self.name, "content": "分析超时"}}

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        global _MAIN_STATIC_PROMPT_CACHE
        if _MAIN_STATIC_PROMPT_CACHE is not None:
            return _MAIN_STATIC_PROMPT_CACHE

        persona = context.get("persona", "")
        persona_block = f"{persona}\n\n---\n\n" if persona else ""
        tool_guidance = get_tool_guidance()
        anti_hallucination = get_anti_hallucination_section("standard")
        prompt = f"{persona_block}{self.instructions}\n{tool_guidance}{anti_hallucination}"
        _MAIN_STATIC_PROMPT_CACHE = prompt
        return prompt
