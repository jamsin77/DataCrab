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
import os
from pathlib import Path
from typing import Dict, Any, AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.services.multi_agent import BaseAgent, AgentMessage, HandoffReason
from app.services.llm import llm_manager
from app.services.tool_registry import execute_tool, get_tool_schemas
from app.services.agent_utils import (
    truncate_tool_result,
    get_anti_hallucination_section,
    StuckDetector,
    SearchSaturationDetector,
    estimate_complexity,
    get_turn_budget,
    should_warn_ungrounded_claim,
    get_context_pressure_level,
    build_pressure_warning,
    should_compact,
    compact_messages,
    build_tool_action_event,
)
from app.services.tool_guidance import get_tool_guidance
from app.services.prompt_docs import SANDBOX_TOOLS_DOC, PLATFORM_CONVENTIONS_DOC

DATA_PROCESSOR_INSTRUCTIONS = """你是 DataCrab 的 DataProcessor（数据处理智能体），一位数据处理专家。

## 核心能力
- 擅长 SQL、pandas、数据清洗和转换
- 能理解用户意图并生成/修改算子和技能
- 能调度执行数据处理流程
- 能为用户生成和修改数据源连接器和模型适配器

## 安全红线
DataCrab 只能处理用户数据，绝不能修改平台自身。
- 禁止修改：平台源代码/配置/数据库结构、平台系统表（users/roles/permissions/data_sources 等）、平台运行环境
- 允许修改：用户对话/算子/技能/流程、用户数据源中的业务数据、文件链接目录中的文件、所有数据源连接器（含标准类型，均可通过 save_connector 修改）、所有模型适配器
- 用户要求修改平台本身时明确拒绝

## 工作准则
1. 输出默认同源：处理后的数据默认写回原数据源路径
2. 修改后必验证：每次修改数据/代码后必须测试验证
3. 准确优先：所有数据结论必须基于工具返回的实际数据，不得编造
4. 翻译优先用算子：涉及文本翻译时，优先调用「文本翻译」算子，不在脚本中自行编写 LLM 翻译逻辑
5. 脚本内置函数：帮用户编写脚本时使用内置函数（query_table_data/get_table_schema/get_datasource_id_by_name 等，由运行环境注入），禁止 import datacrab 或 pip install datacrab

## 扩展能力（用户可扩展数据源连接器与大模型适配器）
- save_connector：用户说"添加/修改 MongoDB 连接器"时，生成继承 BaseConnector 的 Python 类（实现 connect/test_connection/get_schema/get_table_data/get_table_stats/close）
- delete_connector：用户说"删除连接器"时调用（已被数据源使用的无法删除）
- save_llm_adapter：用户说"添加 Claude/Anthropic"时，生成 OpenAI 兼容适配器类（接收 api_key/base_url/model，禁止硬编码 API Key）
- delete_llm_adapter：用户说"删除 Provider"时调用，传入 provider_name
"""

# 工具列表声明（schema + 实现统一在 tool_registry.py 注册中心管理）
MAIN_TOOLS = [
    "web_fetch", "kb_search", "list_user_datasources",
    "query_table_data", "get_table_schema", "execute_sql",
    "list_user_file_links", "save_file_to_link",
]
DEBUG_TOOL_NAMES = [
    "edit_script", "run_script", "read_script", "grep_script", "list_user_datasources",
]


DEBUG_INSTRUCTIONS = """你是 DataCrab 调试助手。用 read_script/grep_script 读代码定位问题，用 edit_script 修改，用 run_script 执行验证。

执行错误最多 {max_exec_failures} 次。
推理过程用中文。

## 输出规范（关键）
调工具前，先完整输出本次修改的说明（改了什么、为什么改）。写完整一句话再调工具，不要写到一半就切到工具调用——用户会看到截断的文字。说明要简洁但完整，不要长篇大论。

## 错误处理（对齐 OpenCode）
VERY IMPORTANT: 修改完成后，必须调 run_script 执行验证结果是否正确。不要在没验证的情况下连续修改多次。
收到执行错误后，看 error 信息自主判断：能通过修改脚本修复的就修（如加进度输出防超时、修 bug、加参数校验），修不了的就说明原因停止。不要反复尝试同一个修改。

## 平台规范
- 平台已内置 llm_vision/llm_chat/call_operator/query_table_data/write_table_data 等函数，优先使用内置函数，不要在脚本中安装数据库扩展、不要直接调用外部 API
- 下方「内置工具函数」文档列出了所有可用函数和签名，修改脚本前先看
"""

# 调试 system prompt 静态前缀缓存（借鉴 DeepAnalyze sectionCache：字节稳定 → 命中 prefix cache）
# key = (is_skill, max_rounds, max_inspections)；一次会话内不变
_DEBUG_STATIC_PROMPT_CACHE: Dict[tuple, str] = {}

# 主对话 system prompt 静态缓存（persona + instructions + 沙箱文档 + 工具指引 + 反幻觉）
# 纯静态，进程级 memoize → 字节稳定命中 GLM prefix cache
_MAIN_STATIC_PROMPT_CACHE: Optional[str] = None




def _compute_diff_summary(old_code: str, new_code: str) -> list:
    """计算代码变更摘要，返回变更行列表"""
    import difflib
    old_lines = old_code.splitlines()
    new_lines = new_code.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=0))
    changed = []
    for line in diff:
        if line.startswith('@@') or line.startswith('---') or line.startswith('+++'):
            continue
        if line.startswith('+') or line.startswith('-'):
            changed.append(line[:200])
    return changed[:30]


def classify_execution_result(rdata: dict) -> dict:
    """分类 run_script 执行结果：成功 / 失败（对齐 OpenCode：靠 LLM 看 error 自主判断，不做平台/脚本问题分类）。

    供 DataProcessorAgent.run_debug 和 DataAnalystAgent.run_debug 复用，
    消除三处重复的 _inner_r / _warnings_r / _is_fail 判断逻辑。

    Returns:
        {
            "is_fail": bool,            # 是否失败
            "err_msg": str,             # 错误信息（失败时）
            "warn_text": str,           # warnings 文本（含 tool_failures 合并）
            "warnings": list,           # 原始 warnings list（含 tool_failures 合并）
            "tool_failures": list,      # 原始 tool_failures list
            "inner_result": dict,       # 内部 result dict
        }
    """
    _inner = rdata.get("result") if isinstance(rdata.get("result"), dict) else {}
    _warnings = (_inner.get("warnings") if _inner else None) or rdata.get("warnings") or []
    _tool_failures = rdata.get("tool_failures") or []
    if _tool_failures and isinstance(_tool_failures, list):
        _warnings = list(_warnings) + list(_tool_failures)
    _warn_text = ""
    if _warnings:
        _warn_text = "; ".join(_warnings[:5]) if isinstance(_warnings, list) else str(_warnings)[:500]

    _is_fail = (not rdata.get("success")
                or ("success" in _inner and not _inner["success"])
                or (rdata.get("error") and str(rdata.get("error")).strip())
                or (_inner.get("error") and str(_inner.get("error")).strip()))

    _err_msg = str(rdata.get("error") or _inner.get("error") or "") if _is_fail else ""

    return {
        "is_fail": _is_fail,
        "err_msg": _err_msg,
        "warn_text": _warn_text,
        "warnings": _warnings,
        "tool_failures": _tool_failures,
        "inner_result": _inner,
    }


def _build_give_up_reason(count: int, err_msg: str) -> str:
    """构造执行错误上限的退出原因 — 两个 Agent 共用"""
    return f"连续 {count} 次执行失败：{err_msg[:300]}"


def _record_negative(folder, err_msg: str, rdata: dict, script_name: str,
                     content: str = "", tool_name: str = "") -> None:
    """记录执行反例到经验库 — 两个 Agent 共用

    Args:
        folder: 经验库目录（debug_folder）
        err_msg: 错误信息
        rdata: run_script 返回的完整结果 dict
        script_name: 脚本名
        content: 本轮 LLM 输出文本（Processor 传，用于 context_summary）
        tool_name: 触发工具名（Processor 传，用于 context_summary）
    """
    if not folder or not err_msg:
        return
    try:
        from app.services import experience as _exp
        _kwargs = dict(
            source="debug-chat",
            error_type="execution_error",
            error_message=err_msg,
            stdout=rdata.get("stdout", ""),
            script_name=script_name,
        )
        if content or tool_name:
            _kwargs["context_summary"] = f"工具: {tool_name}\nAI输出: {content[:200]}"
        _exp.append_negative(folder, **_kwargs)
    except Exception as e:
        logger.warning(f"记录反例失败(非致命): {e}")


def _record_give_up(folder: str, reason: str, content: str, script_name: str) -> None:
    """记录 LLM give_up 时的归因到经验库（LLM 对错误的判断 + 放弃理由）。

    与 _record_negative 的区别：
    - _record_negative 记的是"错误事实"（执行失败的 error_message）
    - _record_give_up 记的是"LLM 归因"（LLM 判断为非脚本问题/平台问题后放弃的理由）
    """
    if not folder:
        return
    try:
        from app.services import experience as _exp
        _exp.append_negative(
            folder,
            source="debug-chat",
            error_type="llm_give_up",
            error_message=reason[:500],
            script_name=script_name,
            context_summary=f"LLM归因: {content[:800]}",
        )
        logger.info(f"[give_up] 已记录 LLM 归因到经验库: {reason[:100]}")
    except Exception as e:
        logger.warning(f"记录 give_up 归因失败(非致命): {e}")


def _slim_run_script_result(content: str) -> str:
    """构建 run_script 工具结果用于 LLM tool 消息（对齐 OpenCode Bash：完整传递错误信息）。

    成功：传完整 result dict + written_tables + warnings
    失败：传完整 error（不截断）+ error_type + warnings
    删除：stdout（已通过 progress 事件推给前端）、sandbox 元信息、execution_time_ms
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return truncate_tool_result(content)
    if not isinstance(data, dict):
        return truncate_tool_result(content)
    slim = {}
    _cls = classify_execution_result(data)
    _inner = _cls["inner_result"]
    _warnings = _cls["warnings"]
    _tool_failures = _cls["tool_failures"]
    if not _cls["is_fail"]:
        slim["success"] = True
        if data.get("written_tables"):
            slim["written_tables"] = data["written_tables"]
        if _inner:
            _inner_json = json.dumps(_inner, ensure_ascii=False, default=str)
            if len(_inner_json) <= 2000:
                slim["result"] = _inner
            else:
                _summary_parts = []
                for k in ("total_rows", "classified_column", "target_column",
                           "unique_values_classified", "rows_written", "migrated_rows",
                           "mode", "categories", "ocr_success", "ocr_fail",
                           "output_table", "target_table"):
                    if k in _inner:
                        _summary_parts.append(f"{k}={_inner[k]}")
                if _summary_parts:
                    slim["result_summary"] = ", ".join(_summary_parts)
                slim["result_truncated"] = True
        if _warnings:
            slim["warnings"] = _warnings
        if _tool_failures:
            slim["tool_failures"] = _tool_failures
        if data.get("param_warning"):
            slim["param_warning"] = data["param_warning"]
    else:
        slim["success"] = False
        slim["error"] = str(data.get("error") or _inner.get("error") or "未知错误")
        _err_type = data.get("error_type") or _inner.get("error_type") or ""
        if _err_type:
            slim["error_type"] = _err_type
        if _warnings:
            slim["warnings"] = _warnings
        if _tool_failures:
            slim["tool_failures"] = _tool_failures
        # 失败时保留 stdout 最后 500 字符（含 [SkillRunner] ... failed 等关键上下文，对齐 OpenCode Bash 失败时完整 error + stderr）
        _stdout = str(data.get("stdout") or "")
        if _stdout:
            slim["stdout"] = _stdout[-500:]
        if data.get("param_warning"):
            slim["param_warning"] = data["param_warning"]
    return json.dumps(slim, ensure_ascii=False, default=str)


class DataProcessorAgent(BaseAgent):
    name = "data_processor"
    display_name = "数据处理智能体"
    description = "理解用户意图、生成/修改算子和技能、调度执行、溯源修复"
    instructions = DATA_PROCESSOR_INSTRUCTIONS
    tools = get_tool_schemas(MAIN_TOOLS)
    capabilities = ["data_processing", "data_query", "operator_generation"]

    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        # 调试模式：分派到 run_debug()，走流式工具调用 + edit_script/run_script
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

        # 动态上下文（数据源列表）注入为 user 消息前缀，不进 system prompt 保证字节稳定
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

        stuck_detector = StuckDetector()
        saturation_detector = SearchSaturationDetector()

        # 动态轮次预算（Q）
        user_msg = message.payload.get("user_message", message.payload.get("content", ""))
        complexity = estimate_complexity(user_msg)
        max_iterations = get_turn_budget(complexity)
        logger.info(f"DataProcessor: complexity={complexity}, budget={max_iterations} turns")

        had_any_tool_calls = False
        pressure_warned = False
        has_preinjected_data = context.get("has_preinjected_data", False)

        for i in range(max_iterations):
            logger.info(f"[run] 第{i+1}轮开始, budget={max_iterations}")

            # 上下文压缩（对齐 OpenCode compaction）
            if should_compact(local_messages):
                local_messages = await compact_messages(local_messages, llm_manager)

            # 流式调用（实时推送 thinking/content/tool_calls）
            tool_calls = []
            content = ""
            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=self.tools, model=llm_manager._default,
                temperature=0.3, tool_choice="auto",
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

            if not tool_calls:
                # 反幻觉：无工具支撑的数据声明警告（P）
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

            if content:
                yield {"type": "content", "content": content}

            # 工具调用过程显示 → 独立 tool_action 事件（让用户看到调用了哪些工具）
            if tool_calls:
                yield build_tool_action_event(tool_calls)

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            # 实时 yield progress（技能脚本 stdout 逐行），不再等 gather 结束后批量 yield
            async for _prog_evt in self._execute_tools_with_progress(tool_calls, db, user_id, context):
                yield _prog_evt
            results = context.pop("_last_tool_results", [])
            for r in results:
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": truncate_tool_result(r["content"])})
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
        """构建主对话 system prompt 静态区（字节稳定 → 命中 prefix cache）。

        静态区 = persona + instructions + 沙箱文档 + 工具指引 + 反幻觉。
        进程级 memoize（_MAIN_STATIC_PROMPT_CACHE），一次构建全程不变。
        动态信息（datasource_context）通过 run() 注入为 user 消息前缀，不进 system。
        """
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

    async def _execute_tool_calls_parallel(self, tool_calls: list, db: AsyncSession, user_id, context: Dict) -> list:
        async def _safe_execute(tc):
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}
            try:
                result = await execute_tool(tc["function"]["name"], func_args, db, user_id, context)
                return {"tool_call_id": tc["id"], "content": result}
            except Exception as e:
                logger.error(f"平台工具异常 {tc['function']['name']}: {e}")
                return {"tool_call_id": tc["id"], "content": json.dumps({"success": False, "error": f"平台工具异常（这不是脚本问题，修改脚本无法解决）: {tc['function']['name']} 执行失败 - {e}"}, ensure_ascii=False)}

        results = await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])
        return list(results)

    async def _execute_tools_with_progress(self, tool_calls: list, db, user_id, context: Dict):
        """执行工具调用，期间实时 yield progress 事件（技能脚本 stdout 逐行）。

        用 asyncio.Queue 把 run_script 子进程的 stdout 进度实时推送给前端，
        而不是等 gather 结束后批量 yield（旧模式进度要等几十秒才显示）。

        最终结果存入 context["_last_tool_results"]，调用方从中取。
        """
        progress_queue = asyncio.Queue()
        context["_progress_queue"] = progress_queue

        # 启动工具执行任务
        exec_task = asyncio.ensure_future(
            self._execute_tool_calls_parallel(tool_calls, db, user_id, context)
        )

        # 同时监控 queue 和 task：queue 有数据就 yield，task 完成就拿结果
        while not exec_task.done():
            q_task = asyncio.ensure_future(progress_queue.get())
            done, pending = await asyncio.wait(
                {exec_task, q_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=2.0,
            )
            # 取消未完成的 queue.get task（避免泄漏）
            for p in pending:
                if p is not exec_task:
                    p.cancel()
            for d in done:
                if d is exec_task:
                    continue
                # queue.get() 完成 → 有 progress
                try:
                    prog_msg = d.result()
                    if prog_msg:
                        yield {"type": "progress", "message": prog_msg}
                except (asyncio.CancelledError, Exception):
                    pass

        # task 已完成，drain 队列里剩余的 progress
        while not progress_queue.empty():
            try:
                prog_msg = progress_queue.get_nowait()
                if prog_msg:
                    yield {"type": "progress", "message": prog_msg}
            except asyncio.QueueEmpty:
                break

        context.pop("_progress_queue", None)
        # 清空已 yield 的 progress（避免后续重复 yield）
        context.pop("_execution_progress", None)

        results = exec_task.result()
        context["_last_tool_results"] = results

    @staticmethod
    def _check_required_params(context: Dict[str, Any], parameters: Dict[str, Any]) -> str:
        """按 SKILL.md 参数规范表校验必选参数是否缺失。返回告警字符串（无缺失返回空串）。

        技能级运行的语义：参数须符合技能规范，而非随意填脚本函数。非阻断，仅告警。
        识别两种必选标记：✅（必选列）/ ❌（可选），或行内含「必选/必填」文字。
        """
        if context.get("debug_type") not in (None, "skill"):
            return ""
        skill_md = context.get("debug_skill_md_full") or context.get("debug_skill_md") or ""
        if not skill_md:
            return ""
        required = []
        in_table = False
        req_col = -1  # 「必选」列在 cells 中的索引
        for line in skill_md.split("\n"):
            s = line.strip()
            if "参数" in s and ("说明" in s or "类型" in s or "描述" in s):
                in_table = True
                req_col = -1
                cells = [c.strip() for c in s.split("|")[1:-1]]
                for idx, c in enumerate(cells):
                    if "必选" in c or "必填" in c or "required" in c.lower():
                        req_col = idx
                        break
                continue
            if in_table and s.startswith("|") and not s.startswith("|--") and not s.startswith("| ---"):
                cells = [c.strip() for c in s.split("|")[1:-1]]
                if len(cells) >= 2 and cells[0] and cells[0] not in ("参数", "Parameter", "---"):
                    pname = cells[0].strip().strip("`")
                    if not pname:
                        continue
                    is_req = False
                    if req_col >= 0 and req_col < len(cells):
                        cell = cells[req_col]
                        is_req = ("✅" in cell or cell == "是" or "必选" in cell
                                  or "必填" in cell or "true" in cell.lower() or cell == "Y")
                    if not is_req and ("必选" in s or "必填" in s):
                        is_req = True
                    if is_req:
                        required.append(pname)
            elif in_table and s and not s.startswith("|"):
                in_table = False
        if not required:
            return ""
        # 排除运行时自动注入的参数（datasource/table 等），避免误报
        _auto = ("datasource", "table_name", "table", "tables", "table_names", "datasource_id", "datasource_name")
        missing = [p for p in required if p not in parameters and not any(a in p for a in _auto)]
        if not missing:
            return ""
        return f"SKILL.md 规范要求必选参数 {required}，当前缺失：{missing}。请补齐后运行。"


    # ==================== 调试模式 ====================

    def build_debug_system_prompt(self, context: Dict[str, Any]) -> str:
        """构建调试模式 system prompt 静态区（字节稳定 → 命中 prefix cache）。

        静态区 = 指令 + 沙箱函数签名 + 平台规范 + 目标连接器能力。
        一次会话内不变，用 _DEBUG_STATIC_PROMPT_CACHE memoize。
        动态信息（参数/上下文）通过 build_debug_dynamic_hints 注入为 user 消息，
        不混入 system prompt 以保证字节稳定。
        """
        max_exec_failures = context.get("debug_max_exec_failures", 3)
        target_ds_type = context.get("debug_output_datasource_type", "")
        cache_key = (max_exec_failures, target_ds_type)

        cached = _DEBUG_STATIC_PROMPT_CACHE.get(cache_key)
        if cached is not None:
            return cached

        prompt = DEBUG_INSTRUCTIONS.replace("{max_exec_failures}", str(max_exec_failures))

        # 沙箱函数签名契约（对齐 OpenCode：工具 schema 永远在 prompt 里，LLM 不必猜 API）
        prompt += "\n\n" + SANDBOX_TOOLS_DOC
        prompt += "\n\n" + PLATFORM_CONVENTIONS_DOC

        # 目标连接器能力（1-2 行，不放完整能力清单）
        if target_ds_type:
            from app.services.tool_guidance import PLATFORM_CAPABILITIES
            _caps = PLATFORM_CAPABILITIES.get("connector", {}).get(target_ds_type, {})
            _wtd = _caps.get("write_table_data", {})
            _can_create = _wtd.get("create_new_file", _wtd.get("create_new_table", False))
            prompt += f"\n目标连接器({target_ds_type}): 创建新文件/表={'✅' if _can_create else '❌'}, execute_sql={'✅' if _caps.get('execute_sql') else '❌'}"
            if not _can_create:
                prompt += "。标❌的能力修改脚本无法绕过，直接报告"

        _DEBUG_STATIC_PROMPT_CACHE[cache_key] = prompt
        return prompt

    def build_debug_dynamic_hints(self, context: Dict[str, Any], user_message: str = "") -> str:
        """构建调试模式动态提示（注入为 user 消息，不进 system prompt）。

        会话级动态信息：入口函数提示、最近成功参数、本次执行参数、双数据源上下文、
        所有可用数据源列表（供 LLM 匹配用户提到的名称→UUID）。
        """
        parts = []
        if context.get("debug_function_name") == "_pipeline_entry":
            parts.append("入口函数 _pipeline_entry 参数已固化，直接调 run_script 执行即可，不需要先读脚本")
        last_params = context.get("debug_last_success_params")
        if last_params:
            parts.append(f"参考：上次成功执行的参数为 {json.dumps(last_params, ensure_ascii=False, default=str)[:300]}，本次请以用户当前指令的源表、目标表、参数为准")
        debug_params = context.get("debug_parameters")
        if debug_params:
            parts.append(f"本次执行参数: {json.dumps(debug_params, ensure_ascii=False, default=str)[:500]}")

        # 双数据源上下文（源端 + 目标端）
        _src_ds = context.get("debug_source_datasource_name", "")
        _src_tbl = context.get("debug_source_table_name", "")
        _tgt_ds = context.get("debug_target_datasource_name", "")
        _tgt_tbl = context.get("debug_target_table_name", "")
        if _src_ds or _tgt_ds:
            _ds_lines = []
            if _src_ds:
                _ds_lines.append(f"  源数据源: {_src_ds}" + (f", 表: {_src_tbl}" if _src_tbl else ""))
            if _tgt_ds:
                _ds_lines.append(f"  目标数据源: {_tgt_ds}" + (f", 表: {_tgt_tbl}" if _tgt_tbl else ""))
            parts.append("当前技能关联的数据源：\n" + "\n".join(_ds_lines))

        # 注入所有可用数据源列表（名称+UUID），让 LLM 能匹配用户提到的数据源名称
        _all_ds = context.get("debug_all_datasources") or []
        if _all_ds:
            _ds_list = "\n".join(f"  - {d['name']} (UUID: {d['id']}, 类型: {d['type']})" for d in _all_ds)
            parts.append(f"用户所有可用数据源：\n{_ds_list}\n\n用户指令中提到的数据源名称，请从上述列表中找到对应UUID，再调用工具。")

        return "\n\n".join(parts) if parts else ""

    async def run_debug(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        """调试模式运行：流式工具调用 + 自愈 + DataInspector 交接。

        与 run() 的区别：
        - 用 chat_stream_with_tools_and_thinking()（流式推理 + 工具调用）
        - 额外工具：edit_script / run_script
        - 自愈循环：run_script 失败时 LLM 自动看到错误并重试
        - 执行成功后 RunTime 自动交接 DataInspector
        """
        db: AsyncSession = context.get("db")
        user_id = context.get("user_id")
        if not db or not user_id:
            yield {"type": "done", "result": {"error": "缺少数据库会话或用户ID"}}
            return

        await llm_manager.initialize()

        # 跨 Agent 上下文持久化：Inspector 回交时恢复之前的工具调用历史
        # （对齐 OpenCode 连续消息链——LLM 知道自己之前改了什么代码）
        _saved_messages = context.get("_processor_local_messages")
        if _saved_messages and message.reason == HandoffReason.FIX_REQUIRED:
            local_messages = list(_saved_messages)
        else:
            system_prompt = self.build_debug_system_prompt(context)
            local_messages = [{"role": "system", "content": system_prompt}]
            history = context.get("history", [])
            if history:
                local_messages.extend(history)

        # 动态提示（会话级参数/上下文，拼到用户消息前缀，不进 system prompt 保证字节稳定）
        _user_msg = message.payload.get("user_message", "") if message.payload else ""
        _dynamic_hints = self.build_debug_dynamic_hints(context, _user_msg)

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
                if issue.get('column'):
                    fix_prompt += f" (列: {issue['column']})"
                if issue.get('suggestion'):
                    fix_prompt += f" → 建议: {issue['suggestion']}"
                fix_prompt += "\n"
            fix_prompt += "\n请分析问题根源，修改脚本修复，修复后重新执行。"
            if _dynamic_hints:
                fix_prompt = fix_prompt + "\n\n" + _dynamic_hints
            local_messages.append({"role": "user", "content": fix_prompt})
            user_msg = fix_prompt
        else:
            user_msg = message.payload.get("user_message", message.payload.get("content", ""))
            if not user_msg:
                yield {"type": "done", "result": {"error": "空消息"}}
                return
            if _dynamic_hints:
                user_msg = user_msg + "\n\n" + _dynamic_hints
            local_messages.append({"role": "user", "content": user_msg})

        # 调试模式工具（对齐 OpenCode：5 个工具，职责清晰）
        # read_script=Read, grep_script=Grep, edit_script=Edit, run_script=Bash
        # 交接不在工具里——执行成功后 RunTime 自动交接 DataInspector
        # 4 个工具对齐 OpenCode：edit_script=Edit / run_script=Bash / read_script=Read / grep_script=Grep
        debug_tools = get_tool_schemas(DEBUG_TOOL_NAMES)

        _fix_attempts = context.get("debug_total_rounds", 0)  # 跨 Agent 持久化，只数 run_script（一次修改尝试=一次修改+执行）
        _total_llm_calls = 0  # 仅用于日志
        _MAX_EXEC_FAILURES = context.get("debug_max_exec_failures", 3)  # 首次执行成功前连续执行失败上限（可配置）
        _exec_failures_before_success = context.get("debug_exec_failures", 0)
        _execution_succeeded = context.get("debug_execution_succeeded", False)
        _just_succeeded = False
        script_name = context.get("debug_script_name", "main.py")
        _stuck = StuckDetector(max_total_rounds=50)
        _last_round_had_fix = False
        _tool_call_meta: Dict[str, tuple] = {}

        logger.info("[run_debug] 开始，无修改次数上限，exec_failures上限=" + str(_MAX_EXEC_FAILURES) + " tools=" + str([t.get("function",{}).get("name","?") for t in debug_tools]))

        while True:
            _total_llm_calls += 1

            # 已消费工具结果清理：上一轮调了 edit_script/run_script → 更早的 read/grep 结果已过时
            if _last_round_had_fix:
                for _mi in range(len(local_messages)):
                    _m = local_messages[_mi]
                    if _m.get("role") == "tool" and isinstance(_m.get("content"), str):
                        _tc_id = _m.get("tool_call_id", "")
                        _tc_info = _tool_call_meta.get(_tc_id)
                        if _tc_info and _tc_info[0] in ("read_script", "grep_script"):
                            local_messages[_mi] = {**_m, "content": f"[已归档] {_tc_info[0]}: {_tc_info[1]}"}
                _last_round_had_fix = False
                _tool_call_meta.clear()

            # 上下文压缩（对齐 OpenCode compaction：摘要旧消息 + 保留近期原文 + 标识符保护）
            # system prompt 在初始化时构建一次，字节稳定命中 prefix cache，不每轮重建
            if should_compact(local_messages):
                local_messages = await compact_messages(local_messages, llm_manager)

            content = ""
            tool_calls = []

            logger.info("[run_debug] LLM调用#" + str(_total_llm_calls) + "（修改尝试" + str(_fix_attempts + 1) + "）")
            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=debug_tools, temperature=0.1,
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

            logger.info("[run_debug] LLM调用#" + str(_total_llm_calls) + "返回 content_len=" + str(len(content)) + " tool_calls=" + str(len(tool_calls)))

            # 检测是否为修改尝试（只数 run_script：一次"修改尝试"=一次"修改+执行"完整循环，不算单纯 edit_script）
            _has_fix = tool_calls and any(tc["function"]["name"] == "run_script" for tc in tool_calls)
            _has_edit = tool_calls and any(tc["function"]["name"] == "edit_script" for tc in tool_calls)
            if _has_fix:
                _last_round_had_fix = True
                _fix_attempts += 1
                context["debug_total_rounds"] = _fix_attempts
                _action = "modify" if _has_edit else "execute"
                _round_evt = {"type": "round", "round": _fix_attempts, "action": _action}
                yield _round_evt

            # 工具调用显示 → 独立 tool_action 事件（不进 content，对齐 OpenCode）
            _script_name = context.get("debug_script_name", "main.py")
            if tool_calls:
                _actions = []
                for tc in tool_calls:
                    _name = tc["function"]["name"]
                    _icon = {"read_script": "📖", "grep_script": "🔍", "edit_script": "✏️", "run_script": "▶️"}.get(_name, "")
                    _act = {"tool": _name, "icon": _icon, "script": _script_name}
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
                # LLM 无工具调用 = 判断完毕（对齐 OpenCode）
                _record_give_up(context.get("debug_folder", ""), content[:500] or "未执行工具操作", content, _script_name)
                yield {"type": "give_up", "reason": content[:500] or "未执行工具操作"}
                yield {"type": "done", "result": {"agent": self.name, "content": content or "未执行工具操作"}}
                return

            # StuckDetector：记录工具调用，检测卡死模式
            _stuck_hint = None
            for tc in tool_calls:
                try:
                    _args = json.loads(tc["function"]["arguments"])
                except Exception:
                    _args = {}
                _hint = _stuck.record_tool_call(tc["function"]["name"], _args)
                if _hint:
                    _stuck_hint = _hint
                    break

            # 总轮次上限 → 强制退出
            if _stuck_hint and "总轮次上限" in _stuck_hint:
                yield {"type": "give_up", "reason": _stuck_hint}
                yield {"type": "done", "result": {"agent": self.name, "content": content or _stuck_hint}}
                return

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            for tc in tool_calls:
                _tn = tc["function"]["name"]
                if _tn == "run_script":
                    yield {"type": "executing", "message": f"正在执行 {_script_name}..."}
                    break

            # 实时 yield progress（技能脚本 stdout 逐行），不再等 gather 结束后批量 yield
            async for _prog_evt in self._execute_tools_with_progress(tool_calls, db, user_id, context):
                yield _prog_evt
            results = context.pop("_last_tool_results", [])
            # 工具结果摘要（像 OpenCode 显示 grep/read 结果）
            _result_lines = []
            for r in results:
                tool_name = ""
                for tc in tool_calls:
                    if tc["id"] == r["tool_call_id"]:
                        tool_name = tc["function"]["name"]
                        break

                # tool 消息精简（对齐 OpenCode：tool result 只留关键信息，不塞 stdout/整脚本）
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
                    _tool_content = truncate_tool_result(r["content"])
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": _tool_content})

                # 调查工具结果显示（对齐 OpenCode：显示实际内容，不只是字符数摘要）
                try:
                    _rd = json.loads(r["content"])
                    if tool_name == "grep_script" and _rd.get("success"):
                        _cnt = _rd.get("total_matches", 0)
                        _matches = _rd.get("matches", [])
                        _pattern = _rd.get("pattern", "")
                        if _cnt == 0:
                            _result_lines.append(f'  🔍 搜索 "{_pattern[:30]}" → 无匹配')
                        else:
                            _glines = [f'  🔍 搜索 "{_pattern[:30]}" → {_cnt} 个匹配:']
                            for _m in _matches[:10]:
                                _line = _m.get("line", "")
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
                        _content = _rd.get("content", "")
                        _first_line = ""
                        _last_line = ""
                        for _cl_line in _content.split("\n"):
                            if _cl_line.strip().startswith("L"):
                                _first_line = _cl_line.strip().split(":")[0]
                                break
                        for _cl_line in reversed(_content.split("\n")):
                            if _cl_line.strip().startswith("L"):
                                _last_line = _cl_line.strip().split(":")[0]
                                break
                        _lines_read = ""
                        if _first_line and _last_line:
                            try:
                                _n1 = int(_first_line.lstrip("L"))
                                _n2 = int(_last_line.lstrip("L"))
                                _lines_read = f"{_n2 - _n1 + 1}行"
                            except ValueError:
                                pass
                        _suffix = f"{_lines_read}/{_total}行" if _lines_read and _total else (_lines_read or (f"共{_total}行" if _total else ""))
                        _result_lines.append(f"  ✓ 已读取 {_func or ''}{(' ' + _suffix) if _suffix else ''}".rstrip())
                    elif tool_name == "get_table_schema" and _rd.get("success"):
                        _cols = len(_rd.get("columns", []))
                        _result_lines.append(f"  表结构: {_cols} 列")
                    elif tool_name == "query_table_data" and _rd.get("success"):
                        _rows = _rd.get("row_count", 0)
                        _result_lines.append(f"  查询: {_rows} 行")
                except Exception as e:
                    logger.warning(f"调查工具摘要生成失败(非致命): {e}")

                if tool_name == "edit_script":
                    try:
                        rdata = json.loads(r["content"])
                    except json.JSONDecodeError as e:
                        logger.error(f"工具 {tool_name} 结果 JSON 解析失败: {e}")
                        yield {"type": "content", "content": f"\n⚠ 工具结果解析失败: {e}\n原始内容: {r['content'][:500]}\n"}
                        continue
                    _mdata = rdata.get("modify", rdata)
                    if _mdata.get("success"):
                        yield {"type": "script_updated", "script_name": rdata.get("script_name", "main.py")}
                        if _mdata.get("skill_md_updated"):
                            yield {"type": "skill_md_updated"}

                if tool_name == "run_script":
                    try:
                        rdata = json.loads(r["content"])
                    except json.JSONDecodeError as e:
                        logger.error(f"工具 {tool_name} 结果 JSON 解析失败: {e}")
                        yield {"type": "content", "content": f"\n⚠ 工具结果解析失败: {e}\n原始内容: {r['content'][:500]}\n"}
                        continue
                    yield {"type": "run_result", "result": rdata}
                    _cls = classify_execution_result(rdata)
                    _inner_r = _cls["inner_result"]
                    _warn_text_r = _cls["warn_text"]
                    if not _cls["is_fail"]:
                        _just_succeeded = True
                        _execution_succeeded = True
                        context["debug_execution_succeeded"] = True
                        _exec_failures_before_success = 0
                        context["debug_exec_failures"] = 0
                        _wt = rdata.get("written_tables")
                        logger.info(f"[run_debug] run_script成功, written_tables={_wt}, inner_result_keys={list(_inner_r.keys()) if _inner_r else 'None'}")
                        if _wt:
                            context["debug_output_table"] = _wt[-1].get("table_name")
                            context["debug_output_datasource_id"] = _wt[-1].get("datasource_id")
                        elif _inner_r:
                            _output_tbl = _inner_r.get("output_table")
                            if _output_tbl:
                                context["debug_output_table"] = _output_tbl
                        folder = context.get("debug_folder")
                        if folder:
                            try:
                                from app.services import experience as _exp
                                if _exp.read_negative(folder):
                                    _exp.append_positive(folder, source="debug-chat", parameters={}, result_summary=str(_inner_r)[:200], script_name=script_name)
                            except Exception as e:
                                logger.warning(f"记录正例失败(非致命): {e}")
                    else:
                        _err_msg = _cls["err_msg"]
                        logger.info(f"[run_debug] run_script失败: err_msg={_err_msg[:200]}")
                        # 执行错误计数：首次成功前连续失败达上限 → give_up
                        if not _execution_succeeded:
                            _exec_failures_before_success += 1
                            context["debug_exec_failures"] = _exec_failures_before_success
                            if _exec_failures_before_success >= _MAX_EXEC_FAILURES:
                                _reason = _build_give_up_reason(_exec_failures_before_success, _err_msg)
                                yield {"type": "give_up", "reason": _reason}
                                yield {"type": "done", "result": {"agent": self.name, "content": content or "执行失败"}}
                                return
                        _record_negative(
                            context.get("debug_folder"), _err_msg, rdata,
                            script_name, content=content, tool_name=tool_name,
                        )



            # yield 调查工具结果摘要 → 独立 tool_summary 事件（不进 content）
            if _result_lines:
                yield {"type": "tool_summary", "summaries": _result_lines}

            # 记录本轮工具调用到 context（供下一轮 system prompt 显示）
            context["debug_tool_calls"] = [
                {"tool": tc["function"]["name"],
                 "success": not any("error" in r.get("content", "") for r in results if r["tool_call_id"] == tc["id"]),
                 "message": _result_lines[i] if i < len(_result_lines) else ""}
                for i, tc in enumerate(tool_calls)
            ]

            # StuckDetector 干预提示注入（在 assistant + tool 消息之后，作为下一轮引导）
            if _stuck_hint:
                local_messages.append({"role": "user", "content": _stuck_hint})

            # 执行成功 → done 带执行结果，RunTime 决定是否交接 Inspector
            if _just_succeeded:
                # 保存 local_messages 到 context，供 Inspector 回交时恢复（跨 Agent 上下文持久化）
                context["_processor_local_messages"] = local_messages
                yield {"type": "done", "result": {
                    "agent": self.name, "content": "执行成功", "success": True,
                    "execution_success": True,
                    "output_datasource_id": context.get("debug_output_datasource_id", ""),
                    "output_table": context.get("debug_output_table", ""),
                }}
                return



        # 循环正常退出（LLM 主动停止或 StuckDetector 兜底）
        _record_give_up(context.get("debug_folder", ""), content[:500] if content else "调试结束", content, _script_name)
        yield {"type": "give_up", "reason": content[:500] if content else "调试结束"}
        yield {"type": "done", "result": {"agent": self.name, "content": content or "调试失败"}}
