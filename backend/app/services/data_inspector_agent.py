"""DataInspector 数据检查智能体

改进点：
- StuckDetector 卡死检测（J）
- 反幻觉：防"只规划不执行"（K）+ 无工具支撑的数据声明警告（P）
- 动态轮次预算（Q）
- 上下文压力主动告警（R）
- 输出长度升级（S）
- 三级反幻觉注入：strict 级别（T）
"""

import json
import asyncio
from typing import Dict, Any, AsyncGenerator

from loguru import logger

from app.services.multi_agent import BaseAgent, AgentMessage, HandoffReason
from app.services.llm import llm_manager
from app.services.inspector_tools import inspector_tools
from app.services.agent_utils import (
    StuckDetector,
    is_planning_only,
    should_warn_ungrounded_claim,
    estimate_complexity,
    get_turn_budget,
    get_context_pressure_level,
    build_pressure_warning,
    get_anti_hallucination_section,
)
from app.services.tool_guidance import get_tool_guidance

DATA_INSPECTOR_INSTRUCTIONS = """你是 DataCrab 的数据检查智能体（DataInspector），一位数据质量专家。

## 核心能力
- 擅长数据标准检查、质量评估和安全审计
- 能对数据进行三维度检查：标准合规、质量评估、安全审计

## 工作准则
1. 检查时优先使用 profile_data 获取数据概览，再针对性检查
2. 发现问题必须给出：问题描述、严重等级、影响范围、修复建议
3. 对修复后的数据必须再次检查确认
4. 严重等级：info < warning < error < critical
5. 检查依据下方「数据标准库」和「数据质量库」，命中后在问题中标注对应 STD-xxx / DQ-xxx 编号
6. 格式类标准（正则/校验位）用确定性逻辑执行；跨表/ETL 对数用 SQL 聚合；语义类用 LLM 判断

## 检查维度
- **标准检查**：字段命名规范、类型一致性、编码规范
- **质量检查**：完整性、唯一性、范围合理性、业务逻辑一致性
- **安全检查**：PII识别、敏感数据暴露、脱敏完整性

## 交接规则
- 发现问题时，使用 handoff_to_processor 交接给数据处理智能体修复
- 所有问题已修复时，返回检查通过结果
"""

DATA_INSPECTOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "profile_data",
            "description": "获取数据概览：行数、列数、各列类型、空值率、唯一值数、样本数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源ID"},
                    "table_name": {"type": "string", "description": "表名"},
                },
                "required": ["datasource_id", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_standards",
            "description": "检查数据是否符合命名规范、类型标准、编码规范",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源ID"},
                    "table_name": {"type": "string", "description": "表名"},
                    "standard_rules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "检查规则列表，如 ['naming_convention', 'type_consistency', 'encoding_check']",
                    },
                },
                "required": ["datasource_id", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_quality",
            "description": "检查数据质量：完整性、唯一性、范围合理性、业务逻辑一致性",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源ID"},
                    "table_name": {"type": "string", "description": "表名"},
                    "quality_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "质量维度，如 ['completeness', 'uniqueness', 'validity', 'consistency']",
                    },
                },
                "required": ["datasource_id", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_security",
            "description": "检查数据安全：PII识别、敏感数据暴露、脱敏完整性",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源ID"},
                    "table_name": {"type": "string", "description": "表名"},
                },
                "required": ["datasource_id", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_etl_quality",
            "description": "ETL过程质量对数检查：数据量不异常增减、记录数/金额汇总对数、检索结果不超总量（引用 DQ-ETL 规则）",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_datasource_id": {"type": "string", "description": "源数据源ID"},
                    "source_table": {"type": "string", "description": "源表名"},
                    "target_datasource_id": {"type": "string", "description": "目标数据源ID"},
                    "target_table": {"type": "string", "description": "目标表名"},
                    "amount_column": {"type": "string", "description": "金额列名（可选，用于金额汇总对数）"},
                },
                "required": ["source_datasource_id", "source_table", "target_datasource_id", "target_table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_processor",
            "description": "将检查发现的问题交接给数据处理智能体进行修复",
            "parameters": {
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "description": "问题列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string", "description": "问题描述"},
                                "severity": {"type": "string", "enum": ["warning", "error", "critical"]},
                                "column": {"type": "string", "description": "涉及列名"},
                                "suggestion": {"type": "string", "description": "修复建议"},
                            },
                        },
                    },
                    "summary": {"type": "string", "description": "检查摘要"},
                },
                "required": ["issues", "summary"],
            },
        },
    },
]

# 输出长度升级链（S）
_OUTPUT_TOKEN_ESCALATION = [3000, 6000, 12000]


class DataInspectorAgent(BaseAgent):
    name = "data_inspector"
    display_name = "数据检查智能体"
    description = "对加工后的数据进行标准检查、质量检查、安全检查，发现错误后记录并反馈"
    instructions = DATA_INSPECTOR_INSTRUCTIONS
    tools = DATA_INSPECTOR_TOOLS
    capabilities = ["data_quality", "data_standards", "data_security", "inspection"]

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        """注入数据标准库 + 数据质量库，检查时引用 STD-xxx / DQ-xxx 编号"""
        base = self.instructions
        try:
            from pathlib import Path
            from app.core.config import settings
            std_dir = Path(settings.SKILL_STORAGE_PATH).parent / "standards"
            for name, title in [
                ("data_standards.md", "数据标准库（字段格式/约束，检查时引用 STD-xxx）"),
                ("data_quality_rules.md", "数据质量库（质量检查规则，检查时引用 DQ-xxx）"),
                ("data_security_rules.md", "数据安全规则库（安全检查规则，检查时引用 SEC-xxx）"),
            ]:
                p = std_dir / name
                if p.exists():
                    base += f"\n\n## {title}\n{p.read_text(encoding='utf-8')}"
        except Exception:
            pass
        # 三级反幻觉注入：DataInspector 用 strict 级别（T）
        anti_hallucination = get_anti_hallucination_section("strict")
        return base + "\n" + get_tool_guidance() + anti_hallucination

    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        db = context.get("db")
        user_id = context.get("user_id")

        if not db or not user_id:
            yield {"type": "done", "result": {"error": "缺少数据库会话或用户ID"}}
            return

        # 将 payload 中的数据源信息写入 context，供 handoff_to_processor 回交时使用（P2-5）
        context["current_datasource_id"] = message.payload.get("datasource_id", "")
        context["current_table_name"] = message.payload.get("table_name", "")

        await llm_manager.initialize()

        system_prompt = self.build_system_prompt(context)
        local_messages = [{"role": "system", "content": system_prompt}]

        if message.reason == HandoffReason.INSPECT_RESULT or message.reason == HandoffReason.DELEGATE:
            ds_id = message.payload.get("datasource_id", "")
            table_name = message.payload.get("table_name", "")
            op_desc = message.payload.get("operation_description", "")
            result_summary = message.payload.get("result_summary", "")

            inspect_prompt = f"请对以下数据进行全面检查：\n\n"
            inspect_prompt += f"- 数据源ID: {ds_id}\n"
            inspect_prompt += f"- 表名: {table_name}\n"
            if op_desc:
                inspect_prompt += f"- 操作描述: {op_desc}\n"
            if result_summary:
                inspect_prompt += f"- 处理结果摘要: {result_summary}\n"
            inspect_prompt += "\n请先使用 profile_data 获取数据概览，然后依次执行标准检查、质量检查和安全检查。"

            local_messages.append({"role": "user", "content": inspect_prompt})
        elif message.reason == HandoffReason.FIX_COMPLETED:
            ds_id = message.payload.get("datasource_id", "")
            table_name = message.payload.get("table_name", "")
            inspect_prompt = f"数据已修复，请对以下数据进行复查：\n\n"
            inspect_prompt += f"- 数据源ID: {ds_id}\n"
            inspect_prompt += f"- 表名: {table_name}\n"
            inspect_prompt += "\n请确认之前的问题是否已修复，并检查是否引入新问题。"

            local_messages.append({"role": "user", "content": inspect_prompt})
        else:
            user_msg = message.payload.get("user_message", message.payload.get("content", ""))
            if user_msg:
                local_messages.append({"role": "user", "content": user_msg})
            else:
                yield {"type": "done", "result": {"error": "空消息"}}
                return

        stuck_detector = StuckDetector()

        # 动态轮次预算（Q）：检查任务通常 medium 复杂度
        inspect_msg = message.payload.get("user_message", message.payload.get("content", ""))
        complexity = estimate_complexity(inspect_msg) if inspect_msg else "medium"
        max_iterations = get_turn_budget(complexity)
        logger.info(f"DataInspector: complexity={complexity}, budget={max_iterations} turns")

        had_any_tool_calls = False
        pressure_warned = False
        output_token_idx = 0

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
                    local_messages.append({"role": "user", "content": "请不要只描述计划，直接开始执行检查操作。"})
                    continue

                # 反幻觉：无工具支撑的数据声明警告（P）
                if not had_any_tool_calls:
                    warn = should_warn_ungrounded_claim(content, had_tool_calls_this_turn=False)
                    if warn and i < max_iterations - 1:
                        local_messages.append({"role": "assistant", "content": content})
                        local_messages.append({"role": "user", "content": warn})
                        continue

                # 卡死检测：空转检查（J）
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

            # 卡死检测：重复调用检查（J）
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

            results = await self._execute_tool_calls_parallel(tool_calls, db, context)
            for r in results:
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]})
                yield {"type": "tool_result", "tool_call_id": r["tool_call_id"], "content": r["content"]}

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
                    logger.info(f"DataInspector 上下文压力告警: level={level}, ratio={ratio:.1%}")

        yield {"type": "content", "content": "检查超时，请稍后重试。"}
        yield {"type": "done", "result": {"agent": self.name, "content": "检查超时"}}

    async def _execute_tool_calls_parallel(self, tool_calls: list, db, context: Dict) -> list:
        async def _safe_execute(tc):
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}
            result = await self._execute_tool(tc["function"]["name"], func_args, db, context)
            return {"tool_call_id": tc["id"], "content": result}

        results = await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])
        return list(results)

    async def _execute_tool(self, name: str, arguments: dict, db, context: Dict) -> str:
        logger.info(f"DataInspector执行工具: {name}")

        if name == "profile_data":
            result = await inspector_tools.profile_data(
                arguments["datasource_id"], arguments["table_name"], db
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        elif name == "check_data_standards":
            result = await inspector_tools.check_data_standards(
                arguments["datasource_id"],
                arguments["table_name"],
                db,
                arguments.get("standard_rules"),
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        elif name == "check_data_quality":
            result = await inspector_tools.check_data_quality(
                arguments["datasource_id"],
                arguments["table_name"],
                db,
                arguments.get("quality_dimensions"),
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        elif name == "check_data_security":
            result = await inspector_tools.check_data_security(
                arguments["datasource_id"], arguments["table_name"], db
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        elif name == "check_etl_quality":
            result = await inspector_tools.check_etl_quality(
                arguments["source_datasource_id"],
                arguments["source_table"],
                arguments["target_datasource_id"],
                arguments["target_table"],
                db,
                arguments.get("amount_column"),
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        elif name == "handoff_to_processor":
            return json.dumps({
                "_handoff": True,
                "to": "data_processor",
                "reason": HandoffReason.FIX_REQUIRED.value,
                "payload": {
                    "issues": arguments.get("issues", []),
                    "summary": arguments.get("summary", ""),
                    "datasource_id": context.get("current_datasource_id", ""),
                    "table_name": context.get("current_table_name", ""),
                },
            }, ensure_ascii=False)
        else:
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
