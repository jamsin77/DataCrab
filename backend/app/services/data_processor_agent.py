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
from pathlib import Path
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

# 调试模式工具（modify_script + run_script）
MODIFY_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "modify_script",
        "description": "修改当前调试的脚本。提供修改后的函数代码，系统自动合并到现有脚本（函数级合并）。只需输出修改的函数，不用输出整个脚本。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                "code": {"type": "string", "description": "修改后的函数代码（Python 代码，含 def 定义）"},
            },
            "required": ["code"],
        },
    },
}

RUN_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "run_script",
        "description": "在沙箱中执行当前调试的脚本，返回执行结果。执行失败时会返回错误信息，根据错误修改脚本后可再次执行。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                "parameters": {"type": "object", "description": "执行参数（业务参数，如数据源名、表名、策略等）"},
            },
            "required": [],
        },
    },
}

DEBUG_TOOLS = [MODIFY_SCRIPT_TOOL, RUN_SCRIPT_TOOL]

# 加载统一技能规范（单一真相源）
_SPEC_PATH = Path(__file__).resolve().parent.parent / "defaults" / "SKILL_SPEC.md"
_SKILL_SPEC = _SPEC_PATH.read_text(encoding="utf-8") if _SPEC_PATH.exists() else ""

DEBUG_INSTRUCTIONS = """你是 DataCrab 平台的调试助手（DataProcessor 角色），正在调试一个脚本。

## 你的能力（通过工具调用）
1. **modify_script**: 修改脚本代码（只需输出修改的函数，系统自动合并）
2. **run_script**: 执行脚本，获取结果
3. **handoff_to_inspector**: 执行成功后交接给 DataInspector 进行数据质量检查
4. **query_table_data / get_table_schema / write_table_data**: 查询/写入数据（通用数据处理工具）

## 工作流程
1. 分析用户问题或错误信息
2. 用 modify_script 修改脚本
3. 用 run_script 执行验证
4. 如果执行失败，根据错误信息继续修改（自动重试，最多 {max_rounds} 轮）
5. 执行成功后，用 handoff_to_inspector 交接质量检查
6. 如果 DataInspector 发现问题，修改脚本修复后重新执行（最多 {max_inspections} 轮检查修复）

## 规则
- 修改脚本时只需输出修改的函数，系统会自动合并
- run_script 的 parameters 必须包含技能所需的关键参数，不能为空
- 推理请简洁，直奔重点
- 执行成功后**必须**调用 handoff_to_inspector 交接质量检查

## 技能规范（脚本必须符合此规范）
""" + _SKILL_SPEC

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
        # 调试模式：分派到 run_debug()，走流式工具调用 + modify_script/run_script
        if context.get("debug_mode"):
            async for event in self.run_debug(message, context):
                yield event
            return

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

        # ---- 调试模式工具 ----
        if name == "modify_script":
            code = arguments.get("code", "")
            if not code:
                return json.dumps({"success": False, "error": "缺少 code"})
            script_name = arguments.get("script_name") or context.get("debug_script_name", "main.py")
            try:
                from app.services.operator_parser import apply_partial_code
                current = context.get("debug_script_content", "")
                merged = apply_partial_code(current, code)
                context["debug_script_content"] = merged

                if context.get("debug_type") == "operator":
                    # 算子：更新数据库
                    from app.models.operator import Operator
                    from sqlalchemy import select as sa_select
                    op_id = context.get("debug_operator_id")
                    op_result = await db.execute(sa_select(Operator).where(Operator.id == op_id))
                    op = op_result.scalar_one_or_none()
                    if op:
                        op.script_content = merged
                        from app.services.operator_parser import parse_python_script
                        try:
                            parsed = parse_python_script(merged)
                            if parsed.get("function_name"):
                                op.function_name = parsed["function_name"]
                                op.inputs = parsed.get("inputs", op.inputs)
                                op.outputs = parsed.get("outputs", op.outputs)
                                op.parameters = parsed.get("parameters", op.parameters)
                        except Exception:
                            pass
                        await db.flush()
                elif context.get("debug_type") == "pipeline":
                    # 流程：更新数据库
                    from app.models.pipeline import Pipeline
                    from sqlalchemy import select as sa_select
                    pipe_id = context.get("debug_pipeline_id")
                    pipe_result = await db.execute(sa_select(Pipeline).where(Pipeline.id == pipe_id))
                    pipe = pipe_result.scalar_one_or_none()
                    if pipe:
                        pipe.main_code = merged
                        await db.flush()
                else:
                    # 技能：写入文件
                    folder = context.get("debug_folder")
                    if folder:
                        from app.services.skill_parser import write_skill_script
                        write_skill_script(folder, script_name, merged)

                logger.info(f"debug modify_script: {script_name} 已更新 ({len(merged)} 字符)")
                return json.dumps({"success": True, "script_name": script_name, "message": "脚本已更新", "merged_preview": merged[:8000]}, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"modify_script 失败: {e}")
                return json.dumps({"success": False, "error": str(e)})

        if name == "run_script":
            script_name = arguments.get("script_name") or context.get("debug_script_name", "main.py")
            parameters = arguments.get("parameters", {})
            for key in ["datasource_id", "datasource_name"]:
                parameters.pop(key, None)
            if not parameters and context.get("debug_last_success_params"):
                parameters = dict(context["debug_last_success_params"])
                for key in ["datasource_id", "datasource_name", "datasource", "table_name"]:
                    parameters.pop(key, None)
            try:
                if context.get("debug_type") == "operator":
                    # 算子：exec() 沙箱执行
                    import io, time as _time, inspect as _inspect
                    from app.api.v1.endpoints.operator import _build_operator_namespace, _sanitize_op
                    script = context.get("debug_script_content", "")
                    func_name = context.get("debug_function_name", "")
                    captured = io.StringIO()
                    exec_ns = {"__builtins__": __builtins__, "print": lambda *a, **kw: print(*a, file=captured, **kw)}
                    exec_ns.update(_build_operator_namespace(user_id))
                    exec(script, exec_ns)
                    debug_func = exec_ns.get(func_name)
                    if not debug_func:
                        return json.dumps({"success": False, "error": f"脚本中未找到函数: {func_name}"})
                    exec_start = _time.time()
                    is_async = _inspect.iscoroutinefunction(debug_func)
                    exec_result = await debug_func(**parameters) if is_async else debug_func(**parameters)
                    if hasattr(exec_result, "to_dict"):
                        exec_result = exec_result.to_dict(orient="records")
                    elapsed = (_time.time() - exec_start) * 1000
                    result = {"success": True, "result": _sanitize_op(exec_result), "stdout": captured.getvalue() or None, "execution_time_ms": round(elapsed, 2)}
                    context["debug_last_success_params"] = parameters
                    logger.info(f"debug run_script (operator): success=True")
                    return json.dumps(result, ensure_ascii=False, default=str)
                elif context.get("debug_type") == "pipeline":
                    return json.dumps({"success": False, "error": "流程调试不支持直接执行，请使用流程执行功能"})
                else:
                    # 技能：subprocess 沙箱
                    folder = context.get("debug_folder")
                    if not folder:
                        return json.dumps({"success": False, "error": "缺少 folder"})
                    from app.services.skill_runner import run_skill_script_async
                    ds_id = context.get("debug_datasource_id")
                    ds_name = context.get("debug_datasource_name")
                    tbl = context.get("debug_table_name")
                    result = await run_skill_script_async(
                        skill_path=folder, script_name=script_name, parameters=parameters,
                        input_data=None, datasource_id=ds_id, datasource_name=ds_name, table_name=tbl,
                    )
                    _inner = result.get("result") if isinstance(result.get("result"), dict) else {}
                    _failed = (not result.get("success")
                               or ("success" in _inner and not _inner["success"])
                               or (result.get("error") and str(result.get("error")).strip())
                               or (_inner.get("error") and str(_inner.get("error")).strip()))
                    if not _failed:
                        context["debug_last_success_params"] = parameters
                    logger.info(f"debug run_script (skill): success={not _failed}")
                    return json.dumps(result, ensure_ascii=False, default=str)
            except Exception as e:
                logger.warning(f"run_script 失败: {e}")
                return json.dumps({"success": False, "error": str(e)})

        return await execute_shared_tool(name, arguments, db, user_id)

    # ==================== 调试模式 ====================

    def build_debug_system_prompt(self, context: Dict[str, Any]) -> str:
        """构建调试模式 system prompt"""
        max_rounds = context.get("debug_max_rounds", 7)
        max_inspections = context.get("debug_max_inspections", 7)
        prompt = DEBUG_INSTRUCTIONS.replace("{max_rounds}", str(max_rounds)).replace("{max_inspections}", str(max_inspections))

        # 当前脚本
        script_content = context.get("debug_script_content", "")
        script_name = context.get("debug_script_name", "main.py")
        if script_content:
            prompt += f"\n## 当前脚本（{script_name}）\n```python\n{script_content[:50000]}\n```\n"

        # SKILL.md 摘要
        skill_md = context.get("debug_skill_md", "")
        if skill_md:
            prompt += f"\n## SKILL.md（摘要）\n```\n{skill_md[:1000]}\n```\n"

        # 参数规范
        params_section = context.get("debug_params_section", "")
        if params_section:
            prompt += f"\n## 参数规范\n{params_section[:1500]}\n"

        # 最近成功参数
        last_params = context.get("debug_last_success_params")
        if last_params:
            prompt += f"\n## 最近一次成功执行的参数\n```json\n{json.dumps(last_params, ensure_ascii=False, default=str)}\n```\n用户未明确指定新参数时，请复用这些参数执行。\n"

        # 用户调试输入
        ctx = context.get("debug_user_context", {})
        if ctx:
            ctx_parts = []
            if ctx.get("nl_query"):
                ctx_parts.append(f"- 自然语言输入：{ctx['nl_query']}")
            elif ctx.get("cmd_str"):
                ctx_parts.append(f"- 命令行输入：{ctx['cmd_str']}")
            elif ctx.get("json_params"):
                ctx_parts.append(f"- JSON参数：{ctx['json_params']}")
            if ctx_parts:
                prompt += "\n## 用户调试输入\n" + "\n".join(ctx_parts) + "\n优先使用这些输入作为执行参数。"

        # 数据源信息
        ds_name = context.get("debug_datasource_name")
        tbl = context.get("debug_table_name")
        if ds_name or tbl:
            prompt += f"\n## 调试数据源\n- 数据源：{ds_name or '未选择'}\n- 表名：{tbl or '未选择'}\n"

        # 历史经验
        lessons = context.get("debug_lessons", "")
        if lessons:
            prompt += f"\n## 历史经验（修改脚本时参考）\n{lessons[:800]}\n"

        # 工具能力表 + 反幻觉
        prompt += "\n" + get_tool_guidance()
        prompt += "\n" + get_anti_hallucination_section("standard")

        return prompt

    async def run_debug(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        """调试模式运行：流式工具调用 + 自愈 + DataInspector 交接。

        与 run() 的区别：
        - 用 chat_stream_with_tools_and_thinking()（流式推理 + 工具调用）
        - 额外工具：modify_script / run_script
        - 自愈循环：run_script 失败时 LLM 自动看到错误并重试
        - 执行成功后 handoff_to_inspector 触发 DataInspector
        """
        db: AsyncSession = context.get("db")
        user_id = context.get("user_id")
        if not db or not user_id:
            yield {"type": "done", "result": {"error": "缺少数据库会话或用户ID"}}
            return

        await llm_manager.initialize()

        system_prompt = self.build_debug_system_prompt(context)
        local_messages = [{"role": "system", "content": system_prompt}]

        # 注入历史
        history = context.get("history", [])
        if history:
            local_messages.extend(history)

        # 用户消息
        # 消息处理：区分初始用户消息 vs DataInspector 回交的修复请求
        _inspection_round = context.get("debug_inspection_round", 0)
        if message.reason == HandoffReason.FIX_REQUIRED:
            # DataInspector 发现问题，回交修复
            _inspection_round += 1
            context["debug_inspection_round"] = _inspection_round
            _max_inspections = context.get("debug_max_inspections", 7)
            if _inspection_round > _max_inspections:
                yield {"type": "content", "content": f"已达到最大检查修复轮次（{_max_inspections}轮），DataInspector 仍发现问题，请人工介入。"}
                yield {"type": "give_up", "reason": f"经过 {_inspection_round} 轮检查修复，数据质量问题仍未完全解决。"}
                yield {"type": "done", "result": {"agent": self.name, "content": "检查修复超限"}}
                return
            issues = message.payload.get("issues", [])
            summary = message.payload.get("summary", "")
            fix_prompt = f"DataInspector 发现以下数据质量问题需要修复（第{_inspection_round}轮检查）：\n\n摘要：{summary}\n\n问题列表：\n"
            for idx, issue in enumerate(issues, 1):
                fix_prompt += f"{idx}. [{issue.get('severity', 'warning')}] {issue.get('description', '')}"
                if issue.get("column"):
                    fix_prompt += f" (列: {issue['column']})"
                if issue.get("suggestion"):
                    fix_prompt += f" → 建议: {issue['suggestion']}"
                fix_prompt += "\n"
            fix_prompt += "\n请分析问题根源，修改脚本修复，修复后重新执行并调用 handoff_to_inspector 交接再检查。"
            local_messages.append({"role": "user", "content": fix_prompt})
            user_msg = fix_prompt
            yield {"type": "round", "round": _inspection_round}
        else:
            user_msg = message.payload.get("user_message", message.payload.get("content", ""))
            if not user_msg:
                yield {"type": "done", "result": {"error": "空消息"}}
                return
            local_messages.append({"role": "user", "content": user_msg})

        # 调试模式工具 = 通用工具 + handoff + 调试工具
        debug_tools = DATA_PROCESSOR_TOOLS + DEBUG_TOOLS

        stuck_detector = StuckDetector()
        max_iterations = context.get("debug_max_rounds", 7)
        had_any_tool_calls = False
        _last_error_sig = None
        _same_error_count = 0
        _should_stop = False
        _run_succeeded = False  # run_script 成功过

        yield {"type": "model", "content": llm_manager.pick_model(user_msg, history)}

        for i in range(max_iterations):
            # 每轮重建 system prompt（含最新脚本内容，让 AI 看到自己的修改）
            local_messages[0] = {"role": "system", "content": self.build_debug_system_prompt(context)}

            # 第2轮起：yield 轮次事件（前端分轮展示）
            if i > 0:
                yield {"type": "round", "round": i + 1}

            # 流式 LLM 调用（推理 + 工具调用）
            content = ""
            tool_calls = []
            finish_reason = None
            clear_thinking = False

            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=debug_tools, temperature=0.3, max_tokens=8000,
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
                elif t == "clear_thinking":
                    yield event
                    clear_thinking = True
                    content = ""

            if clear_thinking:
                continue  # 长度升级，重试

            if not tool_calls:
                # 无工具调用 → 检查反幻觉
                if is_planning_only(content) and i == 0:
                    local_messages.append({"role": "assistant", "content": content})
                    local_messages.append({"role": "user", "content": "请不要只描述计划，直接开始执行操作。"})
                    continue
                if content:
                    yield {"type": "content", "content": content}
                yield {"type": "done", "result": {"agent": self.name, "content": content}}
                return

            had_any_tool_calls = True

            # 卡死检测
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                intervention = stuck_detector.record_tool_call(tc["function"]["name"], args)
                if intervention:
                    local_messages.append({"role": "user", "content": intervention})

            # 记录 assistant 消息
            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            # 执行前：如果有 run_script 工具，先通知前端"正在执行"
            for tc in tool_calls:
                if tc["function"]["name"] == "run_script":
                    yield {"type": "executing", "message": "正在执行脚本..."}
                    break

            # 执行工具
            results = await self._execute_tool_calls_parallel(tool_calls, db, user_id, context)
            for r in results:
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]})

                # 翻译工具结果为前端事件
                tool_name = ""
                for tc in tool_calls:
                    if tc["id"] == r["tool_call_id"]:
                        tool_name = tc["function"]["name"]
                        break

                if tool_name == "modify_script":
                    try:
                        rdata = json.loads(r["content"])
                        if rdata.get("success"):
                            yield {"type": "script_updated", "script_name": rdata.get("script_name", "main.py")}
                    except Exception:
                        pass

                elif tool_name == "run_script":
                    try:
                        rdata = json.loads(r["content"])
                        yield {"type": "run_result", "result": rdata}

                        # 失败判定 + 经验记录 + 重复错误检测
                        _inner_r = rdata.get("result") if isinstance(rdata.get("result"), dict) else {}
                        _is_fail = (not rdata.get("success")
                                    or ("success" in _inner_r and not _inner_r["success"])
                                    or (rdata.get("error") and str(rdata.get("error")).strip())
                                    or (_inner_r.get("error") and str(_inner_r.get("error")).strip()))
                        _err_msg = str(rdata.get("error") or _inner_r.get("error") or "")

                        if _is_fail and _err_msg:
                            # 重复错误检测：取错误前 100 字作签名
                            _sig = _err_msg[:100]
                            if _sig == _last_error_sig:
                                _same_error_count += 1
                            else:
                                _last_error_sig = _sig
                                _same_error_count = 1

                            # 经验记录：失败 → 反例 + 错误日志
                            folder = context.get("debug_folder")
                            if folder:
                                try:
                                    from app.services.skill_parser import read_skill_script
                                    from app.api.v1.endpoints.skill import append_error_log
                                    append_error_log(folder, script_name, "execution_error", _err_msg, {}, rdata.get("stdout", ""), "debug-chat")
                                except Exception:
                                    pass

                            # 连续 3 次相同错误 → 停止，进入 give_up
                            if _same_error_count >= 3:
                                yield {"type": "content", "content": f"\n连续 {_same_error_count} 次出现相同错误，自动停止重试。"}
                                _should_stop = True
                                break
                        elif not _is_fail:
                            # 成功 → 记录正例 + 停止重试
                            _last_error_sig = None
                            _same_error_count = 0
                            _run_succeeded = True
                            # 不直接停止——让 LLM 在下一轮调 handoff_to_inspector 交接检查
                            local_messages.append({"role": "user", "content": "脚本执行成功！请调用 handoff_to_inspector 交接数据质量检查。"})
                            folder = context.get("debug_folder")
                            if folder:
                                try:
                                    from app.services import experience as _exp
                                    if _exp.read_negative(folder):
                                        _exp.append_positive(folder, source="debug-chat", parameters={}, result_summary=str(_inner_r)[:200], script_name=script_name)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                # 检查 handoff
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

            # 重复错误或成功 → 跳出外层重试循环
            if _should_stop:
                break

        # 成功 → 直接结束（不做 give_up 分析）
        if _run_succeeded:
            yield {"type": "done", "result": {"agent": self.name, "content": "执行成功"}}
            return

        # 轮次耗尽或重复错误 → 让 AI 分析无法修复的原因
        _reason = f"连续 {_same_error_count} 次相同错误" if _same_error_count >= 3 else f"已达到最大调试轮次（{max_iterations}）"
        feedback_msg = (
            f"{_reason}，脚本仍然执行失败。\n"
            "请分析以上错误信息，判断是否确实无法修复。\n"
            "如果无法修复，请明确列出无法修复的原因（如环境依赖缺失、数据源不可达、表结构不兼容等），不要再次输出修改脚本。\n"
        )
        if _last_error_sig:
            feedback_msg += f"\n最近重复出现的错误：\n{_last_error_sig}"
        local_messages.append({"role": "assistant", "content": content})
        local_messages.append({"role": "user", "content": feedback_msg})

        full_content = ""
        async for event in llm_manager.chat_stream_with_tools_and_thinking(
            messages=local_messages, tools=debug_tools, temperature=0.3, max_tokens=4000,
        ):
            if event["type"] in ("thinking", "content"):
                yield event
                if event["type"] == "content":
                    full_content += event["content"]
        yield {"type": "give_up", "reason": full_content[:2000]}
        yield {"type": "done", "result": {"agent": self.name, "content": full_content}}
