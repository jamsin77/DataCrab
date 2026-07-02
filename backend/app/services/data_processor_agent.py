"""DataProcessor 数据处理智能体

改进点：
- 工具定义和实现使用 shared_tools（去重 F）
- StuckDetector 卡死检测（J）
- 反幻觉检查（K）+ 无工具支撑的数据声明警告（P）
- 工具能力表注入 system prompt（D）
- 动态轮次预算（Q）
- 上下文压力主动告警（R）
- 输出长度升级（S）
- 三级反幻觉注入：standard 级别（T）
"""

import json
import asyncio
from typing import Dict, Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.services.multi_agent import BaseAgent, AgentMessage, HandoffReason
from app.services.llm import llm_manager
from app.services.shared_tools import SHARED_TOOL_SCHEMAS, execute_shared_tool
from app.services.agent_utils import (
    StuckDetector,
    is_planning_only,
    should_warn_ungrounded_claim,
    estimate_complexity,
    get_turn_budget,
    get_context_pressure_level,
    build_pressure_warning,
    get_anti_hallucination_section,
    SearchSaturationDetector,
)
from app.services.tool_guidance import get_tool_guidance

DATA_PROCESSOR_INSTRUCTIONS = """你是 DataCrab 的数据处理智能体（DataProcessor），一位数据处理专家。

## 核心能力
- 擅长 SQL、pandas、数据清洗和转换
- 能理解用户意图并生成/修改算子和技能
- 能调度执行数据处理流程

## 工作准则
1. **安全红线**：DataCrab 不能修改平台自身，只能处理用户数据
2. **输出默认同源**：处理后的数据默认写回原数据源
3. **修改后必验证**：每次修改数据后必须验证结果
4. **交接检查**：数据处理完成后，应交接给 DataInspector 进行质量检查
5. **准确优先**：所有数据结论必须基于工具返回的实际数据，不得编造或凭记忆推测

## 当收到 DataInspector 的检查结果时
- 应定位问题根源
- 修改处理逻辑修复问题
- 重新执行后再次交接检查

## 交接规则
- 数据处理完成后，使用 handoff_to_inspector 交接给检查智能体
- 当用户请求是数据质量检查相关时，直接交接（delegate）给 DataInspector
"""

# handoff 工具（DataProcessor 专用）
HANDOFF_TOOL = {
    "type": "function",
    "function": {
        "name": "handoff_to_inspector",
        "description": "将处理结果交接给数据检查智能体进行质量检查",
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

DATA_PROCESSOR_TOOLS = SHARED_TOOL_SCHEMAS + [HANDOFF_TOOL]

# 输出长度升级链（S）
_OUTPUT_TOKEN_ESCALATION = [3000, 6000, 12000]


class DataProcessorAgent(BaseAgent):
    name = "data_processor"
    display_name = "数据处理智能体"
    description = "理解用户意图、生成/修改算子和技能、调度执行、溯源修复"
    instructions = DATA_PROCESSOR_INSTRUCTIONS
    tools = DATA_PROCESSOR_TOOLS
    capabilities = ["data_processing", "data_query", "operator_generation"]

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

        # 注入压缩历史（O：统一路由后由 chat.py 传入）
        history = context.get("history", [])
        if history:
            local_messages.extend(history)

        if message.payload:
            if message.reason == HandoffReason.FIX_REQUIRED:
                issues = message.payload.get("issues", [])
                summary = message.payload.get("summary", "")
                fix_prompt = f"DataInspector 发现以下问题需要修复：\n\n摘要：{summary}\n\n问题列表：\n"
                for i, issue in enumerate(issues, 1):
                    fix_prompt += f"{i}. [{issue.get('severity', 'warning')}] {issue.get('description', '')}"
                    if issue.get("column"):
                        fix_prompt += f" (列: {issue['column']})"
                    if issue.get("suggestion"):
                        fix_prompt += f" → 建议: {issue['suggestion']}"
                    fix_prompt += "\n"
                fix_prompt += "\n请分析问题根源，修复数据，修复完成后使用 handoff_to_inspector 交接再检查。"
                local_messages.append({"role": "user", "content": fix_prompt})
            else:
                user_msg = message.payload.get("user_message", message.payload.get("content", ""))
                if user_msg:
                    local_messages.append({"role": "user", "content": user_msg})
        else:
            yield {"type": "done", "result": {"error": "空消息"}}
            return

        stuck_detector = StuckDetector()
        saturation_detector = SearchSaturationDetector()

        # 动态轮次预算（Q）
        user_msg = message.payload.get("user_message", message.payload.get("content", ""))
        complexity = estimate_complexity(user_msg)
        max_iterations = get_turn_budget(complexity)
        logger.info(f"DataProcessor: complexity={complexity}, budget={max_iterations} turns")

        had_any_tool_calls = False
        pressure_warned = False
        output_token_idx = 0
        has_preinjected_data = context.get("has_preinjected_data", False)

        for i in range(max_iterations):
            max_tokens = _OUTPUT_TOKEN_ESCALATION[min(output_token_idx, len(_OUTPUT_TOKEN_ESCALATION) - 1)]
            response = await llm_manager.chat_with_tools(
                messages=local_messages, tools=self.tools, temperature=0.3, max_tokens=max_tokens
            )
            tool_calls = response.get("tool_calls", [])
            finish_reason = response.get("finish_reason")

            # 输出长度升级（S）
            if finish_reason == "length" and output_token_idx < len(_OUTPUT_TOKEN_ESCALATION) - 1:
                output_token_idx += 1
                logger.warning(f"输出被截断(finish_reason=length)，升级 max_tokens 到 {_OUTPUT_TOKEN_ESCALATION[output_token_idx]}")
                local_messages.append({"role": "assistant", "content": response.get("content") or ""})
                local_messages.append({"role": "user", "content": "上一段输出被截断了，请用更大的输出长度重新生成完整内容。"})
                continue

            if not tool_calls:
                content = response.get("content", "")

                # 反幻觉：防"只规划不执行"（K）
                if is_planning_only(content) and i == 0:
                    local_messages.append({"role": "assistant", "content": content})
                    local_messages.append({"role": "user", "content": "请不要只描述计划，直接开始执行操作。"})
                    continue

                # 反幻觉：无工具支撑的数据声明警告（P）
                # 例外：system prompt 已预注入实时数据时，Agent 基于预注入数据回答是合理的
                if not had_any_tool_calls and not has_preinjected_data:
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
                yield {"type": "content", "content": content}

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            results = await self._execute_tool_calls_parallel(tool_calls, db, user_id, context)
            for r in results:
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]})
                yield {"type": "tool_result", "tool_call_id": r["tool_call_id"], "content": r["content"]}

                # 搜索饱和检测（U）：对 kb_search 结果检测重复
                tool_name = ""
                for tc in tool_calls:
                    if tc["id"] == r["tool_call_id"]:
                        tool_name = tc["function"]["name"]
                        break
                if tool_name in ("kb_search", "query_table_data"):
                    sat_warn = saturation_detector.record_search(r["content"])
                    if sat_warn:
                        local_messages.append({"role": "user", "content": sat_warn})

                try:
                    result_data = json.loads(r["content"])
                    if isinstance(result_data, dict) and result_data.get("_handoff"):
                        yield {
                            "type": "handoff",
                            "to": result_data["to"],
                            "reason": result_data["reason"],
                            "payload": result_data.get("payload", {}),
                            "from": self.name,
                        }
                        return
                except (json.JSONDecodeError, AttributeError):
                    pass

            # 上下文压力主动告警（R）
            level, ratio = get_context_pressure_level(local_messages)
            if level > 0 and not pressure_warned:
                warning = build_pressure_warning(level, ratio)
                if warning:
                    local_messages.append({"role": "user", "content": warning})
                    pressure_warned = True
                    logger.info(f"DataProcessor 上下文压力告警: level={level}, ratio={ratio:.1%}")

        yield {"type": "content", "content": "处理超时，请简化您的问题后重试。"}
        yield {"type": "done", "result": {"agent": self.name, "content": "处理超时"}}

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        datasource_context = context.get("datasource_context", "")
        persona = context.get("persona", "")
        persona_block = f"{persona}\n\n---\n\n" if persona else ""
        ctx_block = f"\n## 可用数据源\n{datasource_context}\n" if datasource_context else ""
        tool_guidance = get_tool_guidance()
        # 三级反幻觉注入：DataProcessor 用 standard 级别（T）
        anti_hallucination = get_anti_hallucination_section("standard")
        return f"{persona_block}{self.instructions}{ctx_block}\n{tool_guidance}{anti_hallucination}"

    async def _execute_tool_calls_parallel(self, tool_calls: list, db: AsyncSession, user_id, context: Dict) -> list:
        async def _safe_execute(tc):
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}
            result = await self._execute_tool(tc["function"]["name"], func_args, db, user_id, context)
            return {"tool_call_id": tc["id"], "content": result}

        results = await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])
        return list(results)

    async def _execute_tool(self, name: str, arguments: dict, db: AsyncSession, user_id, context: Dict) -> str:
        logger.info(f"DataProcessor执行工具: {name}")

        if name == "handoff_to_inspector":
            return json.dumps({
                "_handoff": True,
                "to": "data_inspector",
                "reason": HandoffReason.INSPECT_RESULT.value,
                "payload": {
                    "datasource_id": arguments.get("datasource_id", ""),
                    "table_name": arguments.get("table_name", ""),
                    "operation_description": arguments.get("operation_description", ""),
                    "result_summary": arguments.get("result_summary", ""),
                },
            }, ensure_ascii=False)

        return await execute_shared_tool(name, arguments, db, user_id)
