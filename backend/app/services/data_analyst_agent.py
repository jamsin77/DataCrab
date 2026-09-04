"""DataAnalyst 数据分析智能体

定位：只读分析——查询、统计、分布、洞察。不修改数据/脚本，不参与 handoff。
信息链简单线性：system + user + tool + 结论。

与 DataProcessor 的边界：
- 只查不改 → DataAnalyst
- 要修改数据/脚本 → DataProcessor

调试模式（run_debug）：分析技能调试时由 DataAnalystAgent 控制，简化循环——
- 3 次执行错误上限（无 Inspector handoff，无修改次数限制）
- 执行成功即返回结果（不交接 Inspector 检查）
- 无转流程
- 工具复用 DataProcessor 的调试工具（edit_script/run_script/read_script/grep_script）
"""

import json
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.services.multi_agent import BaseAgent, AgentMessage
from app.services.llm import llm_manager
from app.services.tool_registry import execute_tool, get_tool_schemas
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
    build_tool_action_event,
)
from app.services.tool_guidance import get_tool_guidance
from app.services.prompt_docs import PLATFORM_CONVENTIONS_DOC

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
- 能用 llm_vision 分析图片内容（OCR、图表识别、画面描述）

## 工作准则
1. 只读不写：你只负责查询和分析，不修改数据、不生成脚本、不创建算子
2. 准确优先：所有数据结论必须基于工具返回的实际数据，不得编造
3. 先查后说：提到表名/列名前先调 get_table_schema 确认结构；报告数据前先调 query_table_data/execute_sql 获取实际数据
4. 分析深度：不只是罗列数据，要给出分布特征、异常点、趋势洞察
5. 分页意识：大表用 limit/offset 分页查询，避免一次加载过多数据

## 分析结果呈现
分析完成后必须给出清晰结论。除文字说明外，对于"统计/分布/对比/占比"类分析结果，必须按以下格式输出图表块，前端会自动渲染成可视化图表：

### 图表块格式

```
<chart type="bar" title="图表标题" x_label="X轴标签" y_label="Y轴标签">
{"categories": ["A","B","C"], "values": [100,200,150]}
</chart>
```

- `type`: bar（柱状图）/ line（折线图）/ pie（饼图）
- `categories`: X 轴分类（饼图用每项名称）
- `values`: 数值列表
- `x_label` / `y_label` / `title`: 可选
- 多组数据用 `series`：`{"categories": ["A","B"], "series": [{"name":"Q1","values":[100,200]}, {"name":"Q2","values":[150,180]}]}`

### 呈现准则
1. 表格数据超过 5 行 → 用图表呈现，更直观
2. 分布/占比 → 优先饼图
3. 数量对比 → 优先柱状图
4. 趋势 → 优先折线图
5. 图表块前后可以加文字说明，但数据结论应优先用图表表达

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
    tools = get_tool_schemas([
        "web_fetch", "kb_search", "list_user_datasources",
        "query_table_data", "get_table_schema", "execute_sql", "llm_vision",
        "iter_table_data", "read_file", "llm_generate",
        "edit_script", "run_script", "read_script", "grep_script",
    ])
    capabilities = ["data_query", "data_analysis"]

    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        db: AsyncSession = context.get("db")  # 保留兼容（execute_tool 内部用独立 session）
        user_id = context.get("user_id")

        if not user_id:
            yield {"type": "done", "result": {"error": "缺少用户ID"}}
            return

        await llm_manager.initialize()

        # 调试上下文
        _is_debug = bool(context.get("debug_folder") or context.get("debug_script_content"))
        _MAX_EXEC_FAILURES = context.get("debug_max_exec_failures", 3)
        _exec_failures = 0
        _tool_call_meta: Dict[str, tuple] = {}
        _last_round_had_fix = False
        script_name = context.get("debug_script_name", "main.py")

        # system prompt
        if _is_debug:
            system_prompt = self.build_debug_system_prompt(context)
        else:
            system_prompt = self.build_system_prompt(context)

        local_messages = [{"role": "system", "content": system_prompt}]

        history = context.get("history", [])
        if history:
            local_messages.extend(history)

        _datasource_ctx = context.get("datasource_context", "")

        if message.payload:
            user_msg = message.payload.get("user_message", message.payload.get("content", ""))
            if not user_msg:
                yield {"type": "done", "result": {"error": "空消息"}}
                return
            if _is_debug:
                _dynamic_hints = self.build_debug_dynamic_hints(context, user_msg)
                if _dynamic_hints:
                    user_msg = user_msg + "\n\n" + _dynamic_hints
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
        if _is_debug:
            max_iterations = 50
        logger.info(f"DataAnalyst: complexity={complexity}, budget={max_iterations} turns, debug={_is_debug}")

        had_any_tool_calls = False
        pressure_warned = False
        has_preinjected_data = context.get("has_preinjected_data", False)

        # 导入辅助函数
        from app.services.data_processor_agent import (
            _slim_run_script_result,
            classify_execution_result,
            _build_give_up_reason, _record_negative,
        )

        async def _safe_execute(tc):
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}
            try:
                result = await execute_tool(tc["function"]["name"], func_args, db, user_id, context)
                return {"tool_call_id": tc["id"], "content": result}
            except Exception as e:
                logger.error(f"DataAnalyst 工具异常 {tc['function']['name']}: {e}")
                return {"tool_call_id": tc["id"], "content": json.dumps({"error": f"工具执行失败: {e}"}, ensure_ascii=False)}

        for i in range(max_iterations):
            if should_compact(local_messages):
                local_messages = await compact_messages(local_messages, llm_manager)

            content = ""
            tool_calls = []

            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=self.tools,
                temperature=0.1 if _is_debug else 0.3,
                model=llm_manager._default, tool_choice="auto",
            ):
                t = event["type"]
                if t == "model":
                    yield event
                elif t == "thinking":
                    yield event
                elif t == "content":
                    content += event["content"]
                    yield event
                elif t == "tool_calls":
                    tool_calls = event["tool_calls"]

            # 修改尝试检测
            _has_fix = tool_calls and any(tc["function"]["name"] in ("edit_script", "run_script") for tc in tool_calls)
            if _has_fix:
                _last_round_had_fix = True

            # 工具调用显示
            if tool_calls:
                _actions = []
                for tc in tool_calls:
                    _name = tc["function"]["name"]
                    _icon = {"read_script": "📖", "grep_script": "🔍", "edit_script": "✏️", "run_script": "▶️"}.get(_name, "🔧")
                    _act = {"tool": _name, "icon": _icon, "script": script_name}
                    try:
                        _args = json.loads(tc["function"]["arguments"])
                        if _name == "read_script":
                            _offset = _args.get("offset", 0)
                            _limit = _args.get("limit", 0)
                            if _offset and _limit:
                                _act["detail"] = f"L{_offset}-L{_offset + _limit - 1}"
                        elif _name == "grep_script":
                            _pattern = _args.get("pattern", "")
                            if _pattern:
                                _act["detail"] = f'"{_pattern[:40]}"'
                        elif _name == "edit_script":
                            _old = _args.get("old_string", "")
                            _new = _args.get("new_string", "")
                            if _old or _new:
                                _diff_lines = [f"- {l}" for l in _old.splitlines()[:20]]
                                _diff_lines += [f"+ {l}" for l in _new.splitlines()[:20]]
                                _act["diff"] = "\n".join(_diff_lines)
                    except Exception:
                        pass
                    _actions.append(_act)
                yield {"type": "tool_action", "actions": _actions}

            if not tool_calls:
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

                if _is_debug:
                    _record_negative(context.get("debug_folder", ""), content[:500] or "未执行工具操作", content, script_name)
                    yield {"type": "give_up", "reason": content[:500] or "未执行工具操作"}

                if content:
                    yield {"type": "content", "content": content}
                yield {"type": "done", "result": {"agent": self.name, "content": content}}
                return

            had_any_tool_calls = True

            # StuckDetector
            _stuck_hint = None
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                _hint = stuck_detector.record_tool_call(tc["function"]["name"], args)
                if _hint:
                    _stuck_hint = _hint
                    break

            if _stuck_hint and "总轮次上限" in _stuck_hint:
                yield {"type": "give_up", "reason": _stuck_hint}
                yield {"type": "done", "result": {"agent": self.name, "content": content or _stuck_hint}}
                return

            if content:
                yield {"type": "content", "content": content}

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            # 执行工具
            results = await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])

            # 工具结果处理
            _result_lines = []
            for r in results:
                tool_name = ""
                for tc in tool_calls:
                    if tc["id"] == r["tool_call_id"]:
                        tool_name = tc["function"]["name"]
                        break

                # tool 消息精简
                if tool_name in ("read_script", "grep_script"):
                    _tool_content = r["content"]
                    try:
                        _rd_meta = json.loads(r["content"])
                        _meta_desc = _rd_meta.get("function") or _rd_meta.get("pattern") or _rd_meta.get("file") or ""
                        _tool_call_meta[r["tool_call_id"]] = (tool_name, _meta_desc[:60])
                    except Exception:
                        _tool_call_meta[r["tool_call_id"]] = (tool_name, "")
                elif tool_name == "run_script":
                    _tool_content = _slim_run_script_result(r["content"])
                else:
                    _tool_content = _truncate_analysis_result(r["content"])
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": _tool_content})

                # 工具结果显示
                try:
                    _rd = json.loads(r["content"])
                    if tool_name == "grep_script" and _rd.get("success"):
                        _cnt = _rd.get("total_matches", 0)
                        _pattern = _rd.get("pattern", "")
                        if _cnt == 0:
                            _result_lines.append(f'  🔍 搜索 "{_pattern[:30]}" → 无匹配')
                        else:
                            _glines = [f'  🔍 搜索 "{_pattern[:30]}" → {_cnt} 个匹配:']
                            for _m in _rd.get("matches", [])[:10]:
                                for _sl in _m.get("snippet", "").split("\n"):
                                    _sl = _sl.strip()
                                    if _sl.startswith(">>"):
                                        _glines.append(f"  {_sl}")
                            if _cnt > 10:
                                _glines.append(f"  ...（共 {_cnt} 个）")
                            _result_lines.append("\n".join(_glines))
                    elif tool_name == "read_script" and _rd.get("success"):
                        _total = _rd.get("total_lines", 0)
                        _func = _rd.get("function", "")
                        _result_lines.append(f"  ✓ 已读取 {_func or ''} 共{_total}行".rstrip())
                    elif tool_name == "get_table_schema" and _rd.get("success"):
                        _cols = len(_rd.get("columns", []))
                        _result_lines.append(f"  表结构: {_cols} 列")
                    elif tool_name == "query_table_data" and _rd.get("success"):
                        _rows = _rd.get("row_count", 0)
                        _result_lines.append(f"  查询: {_rows} 行")
                except Exception:
                    pass

                # edit_script 结果
                if tool_name == "edit_script":
                    try:
                        rdata = json.loads(r["content"])
                    except json.JSONDecodeError:
                        continue
                    _mdata = rdata.get("modify", rdata)
                    if _mdata.get("success"):
                        yield {"type": "script_updated", "script_name": rdata.get("script_name", "main.py")}
                        if _mdata.get("skill_md_updated"):
                            yield {"type": "skill_md_updated"}

                # run_script 结果
                if tool_name == "run_script":
                    try:
                        rdata = json.loads(r["content"])
                    except json.JSONDecodeError as e:
                        yield {"type": "content", "content": f"\n⚠ 工具结果解析失败: {e}\n"}
                        continue
                    yield {"type": "run_result", "result": rdata}

                    _cls = classify_execution_result(rdata)
                    if not _cls["is_fail"]:
                        # 执行成功 → 直接返回（无 Inspector handoff）
                        yield {"type": "done", "result": {
                            "agent": self.name, "content": content or "执行成功", "success": True,
                            "execution_success": True,
                        }}
                        return
                    else:
                        _err_msg = _cls["err_msg"]
                        _exec_failures += 1
                        if _exec_failures >= _MAX_EXEC_FAILURES:
                            _reason = _build_give_up_reason(_exec_failures, _err_msg)
                            yield {"type": "give_up", "reason": _reason}
                            yield {"type": "done", "result": {"agent": self.name, "content": content or "执行失败"}}
                            return
                        yield {"type": "round", "round": _exec_failures, "action": "execute"}
                        _record_negative(
                            context.get("debug_folder"), _err_msg, rdata,
                            context.get("debug_script_name", "main.py"),
                        )

            # yield 调查工具结果摘要
            if _result_lines:
                yield {"type": "tool_summary", "summaries": _result_lines}

            # StuckDetector 干预
            if _stuck_hint:
                local_messages.append({"role": "user", "content": _stuck_hint})

            # 上下文压力告警
            level, ratio = get_context_pressure_level(local_messages)
            if level > 0 and not pressure_warned:
                warning = build_pressure_warning(level, ratio)
                if warning:
                    local_messages.append({"role": "user", "content": warning})
                    pressure_warned = True
                    logger.info(f"DataAnalyst 上下文压力告警: level={level}, ratio={ratio:.1%}")

        # 超时
        if _is_debug:
            yield {"type": "give_up", "reason": f"连续 {_exec_failures} 次执行失败"}
        else:
            yield {"type": "content", "content": "分析超时，请简化您的问题后重试。"}
        yield {"type": "done", "result": {"agent": self.name, "content": "超时"}}

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

    # ==================== 调试模式辅助 ====================

    _DEBUG_PROMPT_CACHE: Optional[str] = None

    ANALYSIS_DEBUG_INSTRUCTIONS = """你是 DataCrab 数据分析调试助手。执行错误最多 {max_exec_failures} 次。
推理过程用中文。

## 定位
数据分析技能只读不写——执行后不修改源数据。你的任务是运行分析脚本，查看结果。

## 工作流（对齐 OpenCode）
1. 用 read_script/grep_script 查看脚本（如需理解逻辑）
2. 用 run_script 执行脚本，查看结果
3. 如果执行出错：用 edit_script 修复 bug，再 run_script 验证
4. 执行成功即可返回分析结果

## 与数据处理调试的区别
- 无 Inspector 质量检查（分析不改数据，无需检查）
- 无修改次数限制（只有执行错误上限 {max_exec_failures} 次）
- 执行成功即结束

## 错误处理
看 traceback 自主判断：能修就修，修不了就说明原因停止。
"""

    def build_debug_system_prompt(self, context: Dict[str, Any]) -> str:
        if DataAnalystAgent._DEBUG_PROMPT_CACHE is not None:
            return DataAnalystAgent._DEBUG_PROMPT_CACHE
        max_exec_failures = context.get("debug_max_exec_failures", 3)
        prompt = self.ANALYSIS_DEBUG_INSTRUCTIONS.replace("{max_exec_failures}", str(max_exec_failures))
        prompt += "\n\n" + PLATFORM_CONVENTIONS_DOC
        DataAnalystAgent._DEBUG_PROMPT_CACHE = prompt
        return prompt

    def build_debug_dynamic_hints(self, context: Dict[str, Any], user_message: str = "") -> str:
        """动态提示（注入为 user 消息前缀，不进 system prompt 保证字节稳定）"""
        parts = []
        last_params = context.get("debug_last_success_params")
        if last_params:
            parts.append(f"参考：上次成功执行的参数为 {json.dumps(last_params, ensure_ascii=False, default=str)[:300]}")
        debug_params = context.get("debug_parameters")
        if debug_params:
            parts.append(f"本次执行参数: {json.dumps(debug_params, ensure_ascii=False, default=str)[:500]}")
        _src_ds = context.get("debug_source_datasource_name", "")
        _src_tbl = context.get("debug_source_data_name", "")
        if _src_ds:
            parts.append(f"数据源: {_src_ds}" + (f", 表: {_src_tbl}" if _src_tbl else ""))
        _all_ds = context.get("debug_all_datasources") or []
        if _all_ds:
            _ds_list = "\n".join(f"  - {d['name']} (UUID: {d['id']}, 类型: {d['type']})" for d in _all_ds)
            parts.append(f"用户所有可用数据源：\n{_ds_list}")
        return "\n\n".join(parts) if parts else ""
