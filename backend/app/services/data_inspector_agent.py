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
from app.services.tool_registry import execute_tool, get_tool_schemas
from app.services.agent_utils import (
    StuckDetector,
    should_warn_ungrounded_claim,
    estimate_complexity,
    get_turn_budget,
    get_context_pressure_level,
    build_pressure_warning,
    get_anti_hallucination_section,
    should_compact,
    compact_messages,
    truncate_tool_result,
)


DATA_INSPECTOR_INSTRUCTIONS = """你是 DataCrab 的 DataInspector（数据检查智能体），一位数据质量专家。

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

## 严重等级纪律（必须严格遵守）
- **严重等级必须与工具返回的 severity 一致**，不得自行升级、降级或发明新的等级
- 工具返回 `[CRITICAL]` 才能标 critical；返回 `[ERROR]` 才能标 error；返回 `[WARNING]` 才能标 warning
- 严禁在文本里自行宣称"这是 critical 业务问题"——若工具结果里没有该级别，不得使用该级别
- 不得根据"业务影响"主观调整 severity；severity 由规则库定义，工具确定性产出

## 检查维度
- **标准检查**：字段命名规范、类型一致性、编码规范
- **质量检查**：完整性、唯一性、范围合理性、业务逻辑一致性
- **安全检查**：PII识别、敏感数据暴露、脱敏完整性

## 结果输出
- 发现 `fatal` 问题（违反法律法规）：直接在内容中说明违法风险并停止
- 其他问题：在内容中列出（含严重等级、影响范围、修复建议），由用户决定是否修复
"""

class DataInspectorAgent(BaseAgent):
    name = "data_inspector"
    display_name = "数据检查智能体"
    description = "对加工后的数据进行标准检查、质量检查、安全检查，发现错误后记录并反馈"
    instructions = DATA_INSPECTOR_INSTRUCTIONS
    tools = get_tool_schemas([
        "web_fetch", "kb_search", "list_user_datasources",
        "profile_data", "check_data_standards", "check_data_quality", "check_data_security",
    ])
    capabilities = ["data_quality", "data_standards", "data_security", "inspection"]

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        """精简 system prompt（规则文件移到 user message，不在每轮重复）"""
        base = self.instructions
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

        # 将 payload 中的数据源信息写入 context（供 RunTime 回交时使用）
        context["current_datasource_id"] = message.payload.get("datasource_id", "")
        context["current_table_name"] = message.payload.get("table_name", "")

        # 加载技能专属规则（如有 skill_path 且存在 rules.md）
        skill_rules = None
        _skill_path = context.get("debug_skill_path") or message.payload.get("skill_path")
        if _skill_path:
            try:
                from app.services.standards_parser import parse_skill_rules
                skill_rules = parse_skill_rules(_skill_path)
                if not (skill_rules.get("std") or skill_rules.get("dq") or skill_rules.get("sec")):
                    skill_rules = None  # 全空则不传，避免无谓循环
            except Exception as e:
                logger.warning(f"加载技能规则失败(非致命): {e}")

        await llm_manager.initialize()

        system_prompt = self.build_system_prompt(context)
        local_messages = [{"role": "system", "content": system_prompt}]
        context["_local_messages"] = local_messages

        if message.reason == HandoffReason.INSPECT_RESULT or message.reason == HandoffReason.DELEGATE:
            ds_id = message.payload.get("datasource_id", "")
            table_name = message.payload.get("table_name", "")
            op_desc = message.payload.get("operation_description", "")
            result_summary = message.payload.get("result_summary", "")

            # 预执行所有检查（加载数据1次 → 4项检查 → 紧凑报告）
            yield {"type": "inspecting", "message": "正在执行数据质量检查..."}
            from app.services.inspector_tools import inspector_tools
            check_results = await inspector_tools.run_all_checks(ds_id, table_name, db, skill_rules=skill_rules)
            context["_check_results"] = check_results
            report = inspector_tools.format_report(check_results)

            inspect_prompt = f"数据已自动检查完成，结果如下：\n\n{report}\n\n"
            if op_desc:
                inspect_prompt += f"操作描述: {op_desc}\n"
            inspect_prompt += "\n请分析以上检查结果。发现问题请列出（含严重等级、影响范围、修复建议）；无问题请说明检查通过。"

            local_messages.append({"role": "user", "content": inspect_prompt})
            logger.info(f"[Inspector-DEBUG] INSPECT_RESULT report_len={len(report)} report_preview={report[:200]}")
            yield {"type": "inspection_report", "report": report}

        elif message.reason == HandoffReason.FIX_COMPLETED:
            ds_id = message.payload.get("datasource_id", "")
            table_name = message.payload.get("table_name", "")

            # 复查：重新预执行（清缓存，加载最新数据）
            yield {"type": "inspecting", "message": "正在复查数据质量..."}
            from app.services.inspector_tools import inspector_tools
            check_results = await inspector_tools.run_all_checks(ds_id, table_name, db, skill_rules=skill_rules)
            context["_check_results"] = check_results
            report = inspector_tools.format_report(check_results)

            inspect_prompt = f"数据已修复并重新检查，结果如下：\n\n{report}\n\n请确认之前的问题是否已修复，并检查是否引入新问题。"

            local_messages.append({"role": "user", "content": inspect_prompt})
            logger.info(f"[Inspector-DEBUG] FIX_COMPLETED report_len={len(report)} report_preview={report[:200]}")
            yield {"type": "inspection_report", "report": report}

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

        for i in range(max_iterations):
            # 上下文压缩（对齐 OpenCode compaction）
            if should_compact(local_messages):
                local_messages = await compact_messages(local_messages, llm_manager)

            content = ""
            tool_calls = []
            finish_reason = None

            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=self.tools, temperature=0.3,
                model=llm_manager._flash, tool_choice="auto",
            ):
                t = event["type"]
                if t == "model":
                    yield event
                elif t == "thinking":
                    yield event
                elif t == "content":
                    content += event["content"]
                    # 不立即 yield content，等流式结束后决定（反幻觉可能要抑制）
                elif t == "tool_calls":
                    tool_calls = event["tool_calls"]
                elif t == "finish":
                    finish_reason = event["finish_reason"]

            # 流式结束：决定是否输出 content
            if not tool_calls:
                # 反幻觉：无工具支撑的数据声明警告
                if not had_any_tool_calls:
                    warn = should_warn_ungrounded_claim(content, had_tool_calls_this_turn=False)
                    if warn and i < max_iterations - 1:
                        # 抑制本轮 content（不 yield），注入警告让 LLM 重新调工具
                        local_messages.append({"role": "assistant", "content": content})
                        local_messages.append({"role": "user", "content": warn})
                        continue

                # 卡死检测：空转检查
                intervention = stuck_detector.record_idle()
                if intervention and i < max_iterations - 1:
                    local_messages.append({"role": "assistant", "content": content})
                    local_messages.append({"role": "user", "content": intervention})
                    continue

                # 最终结论：输出 content
                yield {"type": "content", "content": content}
                yield {"type": "done", "result": {"agent": self.name, "content": content, "success": True, "check_results": context.get("_check_results")}}
                return

            # 有工具调用：输出 content（LLM 在解释要做什么）
            yield {"type": "content", "content": content}

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

            results = []
            for tc in tool_calls:
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    func_args = {}
                # 自动从 context 填充数据源和表名（LLM 无需手动传参）
                ds_id = context.get("current_datasource_id", "") or func_args.get("datasource_id", "")
                tbl = context.get("current_table_name", "")
                if ds_id:
                    func_args["datasource_id"] = ds_id
                if tbl:
                    func_args["table_name"] = tbl
                # UUID 解析（如果 ds_id 是名称而非 UUID）
                if ds_id:
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
                                func_args["datasource_id"] = str(_ds.id)
                        except Exception:
                            pass
                _r = await execute_tool(tc["function"]["name"], func_args, db, context.get("_user_id"), context)
                results.append({"tool_call_id": tc["id"], "content": _r})
            for r in results:
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": truncate_tool_result(r["content"])})
                yield {"type": "tool_result", "tool_call_id": r["tool_call_id"], "content": r["content"]}


            # 上下文压力主动告警（R）
            level, ratio = get_context_pressure_level(local_messages)
            if level > 0 and not pressure_warned:
                warning = build_pressure_warning(level, ratio)
                if warning:
                    local_messages.append({"role": "user", "content": warning})
                    pressure_warned = True
                    logger.info(f"DataInspector 上下文压力告警: level={level}, ratio={ratio:.1%}")

        yield {"type": "content", "content": "检查超时，请稍后重试。"}
        yield {"type": "done", "result": {"agent": self.name, "content": "检查超时", "success": False, "check_results": context.get("_check_results")}}

