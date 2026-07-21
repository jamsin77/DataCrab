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


def _collect_severe_issues(local_messages):
    """从工具结果中收集 error/critical 级问题；存在 fatal 时不强制交接（按指令应停止）。"""
    severe = []
    has_fatal = False
    for m in local_messages:
        if m.get("role") != "tool":
            continue
        try:
            data = json.loads(m.get("content", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        for issue in data.get("issues", []) or []:
            sev = str(issue.get("severity", "")).lower()
            if sev == "fatal":
                has_fatal = True
            elif sev in ("error", "critical"):
                severe.append(issue)
    if has_fatal:
        return []
    return severe


DATA_INSPECTOR_INSTRUCTIONS = """你是 DataCrab 的数据检查智能体（DataInspector），一位数据质量专家。

## 核心能力
- 擅长数据标准检查、质量评估和安全审计
- 能对数据进行三维度检查：标准合规、质量评估、安全审计

## 工作准则
1. 检查对象是数据处理后的目标表（结果表），不是源表。系统已自动传入目标表信息，直接检查即可
2. 检查时优先使用 profile_data 获取数据概览，再针对性检查
3. 发现问题必须给出：问题描述、严重等级、影响范围、修复建议
4. 对修复后的数据必须再次检查确认
5. 严重等级：info < warning < error < critical < fatal
6. 检查依据下方「数据标准库」和「数据质量库」，命中后在问题中标注对应 STD-xxx / DQ-xxx 编号
7. 格式类标准（正则/校验位）用确定性逻辑执行；跨表/ETL 对数用 SQL 聚合；语义类用 LLM 判断

## 检查维度
- **标准检查**：字段命名规范、类型一致性、编码规范
- **质量检查**：完整性、唯一性、范围合理性、业务逻辑一致性
- **安全检查**：PII识别、敏感数据暴露、脱敏完整性

## 交接规则
- 发现 `fatal` 问题（违反法律法规）：**不要**交接修复，直接在内容中说明违法风险并停止
- 发现 `error` 或 `critical` 问题：使用 handoff_to_processor 交接给数据处理智能体**自动修复**
- 仅发现 `warning` 问题：在内容中列出问题，说明由用户决定是否修复，不要交接
- 所有问题已修复或无问题时，返回检查通过结果
"""

DATA_INSPECTOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "profile_data",
            "description": "获取数据概览：行数、列数、各列类型、空值率、唯一值数、样本数据。无需传参，自动检查当前数据源和表",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_standards",
            "description": "检查数据是否符合命名规范、类型标准、编码规范。无需传参，自动检查当前数据源和表",
            "parameters": {
                "type": "object",
                "properties": {
                    "standard_rules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "检查规则列表，如 ['naming_convention', 'type_consistency', 'encoding_check']",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_quality",
            "description": "检查数据质量：完整性、唯一性、范围合理性、业务逻辑一致性。无需传参，自动检查当前数据源和表",
            "parameters": {
                "type": "object",
                "properties": {
                    "quality_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "质量维度，如 ['completeness', 'uniqueness', 'validity', 'consistency']",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_security",
            "description": "检查数据安全：PII识别、敏感数据暴露、脱敏完整性。无需传参，自动检查当前数据源和表",
            "parameters": {
                "type": "object",
                "properties": {},
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
                                "severity": {"type": "string", "enum": ["warning", "error", "critical", "fatal"]},
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
        # Inspector 有自己的工具集，不注入共享工具能力表（P2 优化）
        anti_hallucination = get_anti_hallucination_section("strict")
        return base + anti_hallucination

    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        """流式推理 + 工具调用，推理过程实时展示给用户。"""
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

        yield {"type": "model", "content": llm_manager.pick_model(inspect_msg or "数据检查")}

        for i in range(max_iterations):
            _llm_model = None
            _llm_tool_choice = "auto"
            _llm_max_tokens = 12000
            content = ""
            tool_calls = []
            finish_reason = None

            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=self.tools, temperature=0.3, max_tokens=_llm_max_tokens,
                model=_llm_model, tool_choice=_llm_tool_choice,
            ):
                t = event["type"]
                if t == "thinking":
                    yield event
                elif t == "content":
                    content += event["content"]
                    yield event
                elif t == "tool_calls":
                    tool_calls = event["tool_calls"]
                elif t == "finish":
                    finish_reason = event["finish_reason"]

            if not tool_calls:
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

                # 强制交接：检查工具发现 error/critical 但 LLM 未调 handoff_to_processor
                if had_any_tool_calls and i < max_iterations - 1:
                    _severe = _collect_severe_issues(local_messages)
                    if _severe:
                        local_messages.append({"role": "assistant", "content": content})
                        _redirect = (
                            "检查工具发现了 error/critical 级问题，但你没有调用 handoff_to_processor 交接修复。"
                            "请立即调用 handoff_to_processor 工具，将下列问题通过 issues 参数传入"
                            "（每项含 description/severity/column/suggestion），让 DataProcessor 自动修复：\n"
                            + json.dumps(_severe, ensure_ascii=False, default=str)
                        )
                        local_messages.append({"role": "user", "content": _redirect})
                        continue

                # content 已在流式阶段逐 token 输出，不再重复 yield 全量
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
                        issues = result_data.get("payload", {}).get("issues", [])
                        summary = result_data.get("payload", {}).get("summary", "")
                        has_fatal = any(i.get("severity") == "fatal" for i in issues)
                        has_auto_fix = any(i.get("severity") in ("error", "critical") for i in issues)

                        if has_fatal:
                            fatal_issues = [i for i in issues if i.get("severity") == "fatal"]
                            yield {"type": "fatal", "issues": fatal_issues, "summary": summary}
                            # content 已在流式阶段逐 token 输出，不再重复 yield
                            yield {"type": "done", "result": {"agent": self.name, "content": "发现致命问题（违反法律法规），已停止处理"}}
                            return
                        elif not has_auto_fix:
                            yield {"type": "warning_confirmation", "issues": issues, "summary": summary}
                            # content 已在流式阶段逐 token 输出，不再重复 yield
                            yield {"type": "done", "result": {"agent": self.name, "content": "仅发现警告问题，等待用户确认是否修复"}}
                            return
                        else:
                            # error/critical → 自动修复
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

        # 自动从 context 填充数据源和表名（LLM 无需手动传参，避免中文表名复制错误）
        # 优先用 context 值（可靠 UUID），不信任 LLM 传的 datasource_id（可能是中文名）
        ds_id = context.get("current_datasource_id", "") or arguments.get("datasource_id", "")
        tbl = context.get("current_table_name", "")
        if not ds_id or not tbl:
            return json.dumps({"error": "缺少数据源ID或表名（context 中未找到当前数据源信息）"}, ensure_ascii=False)

        # 如果 ds_id 不是合法 UUID，尝试按数据源名称解析
        try:
            import uuid as _uuid
            _uuid.UUID(str(ds_id))
        except (ValueError, AttributeError):
            try:
                from app.models.datasource import DataSource as _DS
                from sqlalchemy import select as _select
                _r = await db.execute(_select(_DS).where(_DS.name == str(ds_id)))
                _ds = _r.scalar_one_or_none()
                if _ds:
                    ds_id = str(_ds.id)
                else:
                    return json.dumps({"error": f"数据源 '{ds_id}' 不存在或不是有效的UUID"}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": f"数据源ID格式错误: {ds_id}，解析失败: {e}"}, ensure_ascii=False)

        if name == "profile_data":
            result = await inspector_tools.profile_data(ds_id, tbl, db)
            return json.dumps(result, ensure_ascii=False, default=str)
        elif name == "check_data_standards":
            result = await inspector_tools.check_data_standards(
                ds_id, tbl, db, arguments.get("standard_rules"),
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        elif name == "check_data_quality":
            result = await inspector_tools.check_data_quality(
                ds_id, tbl, db, arguments.get("quality_dimensions"),
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        elif name == "check_data_security":
            result = await inspector_tools.check_data_security(ds_id, tbl, db)
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
