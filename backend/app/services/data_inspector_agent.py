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
 

def _parse_skill_rule_issues(content: str) -> list:
    """从 LLM 输出的 content 里解析技能规则 issue。

    优先解析 ```json {"skill_rule_issues": [...]} ```；
    解析失败时兜底从自然语言文本提取 SKILL-DQ-xxx + 问题描述。
    """
    import re as _re
    if not content:
        return []
    # 方式 1：解析 JSON 块
    m = _re.search(r'```json\s*(\{.*?\})\s*```', content, _re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            issues = data.get("skill_rule_issues", [])
            result = []
            for iss in issues:
                sev = iss.get("severity", "warning")
                if sev == "pass":
                    continue
                result.append({
                    "rule_id": iss.get("rule_id", ""),
                    "severity": sev,
                    "table": iss.get("table", ""),
                    "column": iss.get("column", ""),
                    "description": iss.get("description", ""),
                    "suggestion": iss.get("suggestion", ""),
                })
            if result:
                return result
        except (json.JSONDecodeError, KeyError):
            pass

    # 方式 2：兜底从自然语言提取 SKILL-DQ-xxx 规则判断
    # 匹配：### ✅ SKILL-DQ-001 通过 / ### [ERROR] SKILL-DQ-001 问题描述
    result = []
    for m in _re.finditer(r'SKILL-(?:DQ|STD|SEC)-\d{3}', content):
        rid = m.group()
        # 取该规则 ID 后面 200 字符的上下文
        start = m.start()
        ctx = content[start:start + 300]
        # 跳过通过的
        if '通过' in ctx[:50] or '✅' in ctx[:50] or 'pass' in ctx[:50].lower():
            continue
        # 提取 severity
        sev = "warning"
        for s in ("error", "critical", "fatal"):
            if s in ctx[:100].lower():
                sev = s
                break
        # 提取问题描述（规则 ID 后面的文本，取第一行或到下一个 ###）
        desc_match = _re.search(r'SKILL-(?:DQ|STD|SEC)-\d{3}[：:\s]*(.+?)(?:\n###|\n-|\n\n|$)', ctx, _re.DOTALL)
        desc = desc_match.group(1).strip()[:200] if desc_match else "检查发现问题"
        result.append({
            "rule_id": rid,
            "severity": sev,
            "table": "",
            "column": "",
            "description": desc,
            "suggestion": "",
        })
    return result


def _format_skill_rules_for_llm(skill_rules: Dict) -> str:
    """把纯自然语言技能规则（无 regex/legal_values）格式化为 LLM 可判断的文本。"""
    if not skill_rules:
        return ""
    _nl_rules = []
    for cat_key, cat_label in [("std", "标准"), ("dq", "质量"), ("sec", "安全")]:
        for r in skill_rules.get(cat_key, []):
            if r.get("regex") or r.get("legal_values"):
                continue  # 有确定性实现的不交给 LLM
            rid = r.get("id", "")
            name = r.get("name", "")
            logic = r.get("logic") or r.get("scope") or r.get("detection_logic") or ""
            sev = r.get("severity", "warning")
            _nl_rules.append(f"- [{cat_label}] {rid} {name}: {logic}（严重等级: {sev}）")
    if not _nl_rules:
        return ""
    return "\n\n以下技能专属规则无法自动检查，请基于上述报告数据主观判断：\n" + "\n".join(_nl_rules)


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
        "web_fetch", "list_user_datasources",
        "profile_data", "check_data_standards", "check_data_quality", "check_data_security",
        "read_file", "query_table_data",
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

        if not user_id:
            yield {"type": "done", "result": {"error": "缺少用户ID"}}
            return

        # 用独立 session 执行检查，避免依赖 SSE handler 的主 session
        from app.core.database import async_session as _insp_session

        # 将 payload 中的数据源信息写入 context（供 RunTime 回交时使用）
        _output_tables = message.payload.get("output_tables", [])
        if not _output_tables:
            # 兼容旧 payload（单值）
            _ds = message.payload.get("datasource_id", "")
            _tbl = message.payload.get("table_name", "")
            if _ds and _tbl:
                _output_tables = [{"datasource_id": _ds, "table_name": _tbl}]
        logger.info(f"[Inspector] output_tables={json.dumps(_output_tables, ensure_ascii=False)}")
        context["current_datasource_id"] = _output_tables[0].get("datasource_id", "") if _output_tables else ""
        context["current_table_name"] = _output_tables[0].get("table_name", "") if _output_tables else ""
        context["debug_output_tables"] = _output_tables

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
            op_desc = message.payload.get("operation_description", "")
            result_summary = message.payload.get("result_summary", "")

            # 预执行所有检查（遍历所有写入表）
            yield {"type": "inspecting", "message": f"正在检查 {len(_output_tables)} 张表的数据质量..."}
            from app.services.inspector_tools import inspector_tools
            _all_reports = []
            _all_check_results = {}
            for _idx, _tbl_info in enumerate(_output_tables, 1):
                _ds_id = _tbl_info.get("datasource_id", "")
                _tbl_name = _tbl_info.get("table_name", "")
                if not _ds_id or not _tbl_name:
                    continue
                yield {"type": "progress", "message": f"正在检查第 {_idx}/{len(_output_tables)} 张表：{_tbl_name}"}
                logger.info(f"[Inspector] 检查表 {_idx}/{len(_output_tables)}: {_tbl_name}")
                yield {"type": "progress", "message": f"  📊 {_tbl_name}：正在获取数据概览..."}
                async with _insp_session() as _chk_sess:
                    _cr = await inspector_tools.run_all_checks(_ds_id, _tbl_name, _chk_sess, skill_rules=skill_rules)
                _all_check_results[_tbl_name] = _cr
                _issue_count = sum(len(r.get("issues", [])) for r in _cr.values() if isinstance(r, dict))
                _dim_summary = []
                for _dim, _label in [("standards", "标准"), ("quality", "质量"), ("security", "安全")]:
                    _dr = _cr.get(_dim, {}) if isinstance(_cr, dict) else {}
                    _di = len(_dr.get("issues", [])) if isinstance(_dr, dict) else 0
                    _dim_summary.append(f"{_label}{_di}个问题" if _di else f"{_label}✅")
                logger.info(f"[Inspector] 表 {_tbl_name} 检查完成: {_issue_count} 个问题")
                yield {"type": "progress", "message": f"✓ {_tbl_name} 检查完成（{_issue_count} 个问题：{', '.join(_dim_summary)}）"}
                _rpt = inspector_tools.format_report(_cr, skill_rules=skill_rules)
                _all_reports.append(f"### 表: {_tbl_name}\n\n{_rpt}")
            context["_check_results"] = _all_check_results if len(_output_tables) > 1 else (list(_all_check_results.values())[0] if _all_check_results else {})
            report = "\n\n---\n\n".join(_all_reports) if _all_reports else "无写入表可检查"

            inspect_prompt = f"数据已自动检查完成，结果如下：\n\n{report}\n\n"
            if op_desc:
                inspect_prompt += f"操作描述: {op_desc}\n"
            # 注入源数据源信息（供 LLM 用 read_file / query_table_data 对比）
            _user_msg = message.payload.get("user_message", "") or context.get("debug_user_message", "")
            if _user_msg:
                inspect_prompt += f"用户原始请求: {_user_msg[:500]}\n"
            _src_ds_name = context.get("debug_source_datasource_name", "")
            _src_data_name = context.get("debug_source_data_name", "")
            _src_ds_id = context.get("debug_source_datasource_id", "")
            if _src_ds_name or _src_data_name:
                inspect_prompt += f"源数据源: {_src_ds_name}（ID: {_src_ds_id}），源表/文件: {_src_data_name}\n"
            # 列出所有输出表（供 LLM 用 query_table_data 逐表查询）
            if _output_tables:
                _tbl_list = "\n".join(f"  - 数据源ID: {t.get('datasource_id','')}, 表名: {t.get('table_name','')}" for t in _output_tables)
                inspect_prompt += f"输出表清单（可用 query_table_data 查询数据）:\n{_tbl_list}\n"
            inspect_prompt += _format_skill_rules_for_llm(skill_rules)
            inspect_prompt += "\n\n你可以使用 read_file 读取源文档、query_table_data 查看提取后的实际数据，来对照判断技能专属规则。"
            inspect_prompt += "\n\n**必须逐条检查以下技能专属规则：**"
            inspect_prompt += "\n1. SKILL-DQ-001：用 read_file 读源文档，对比提取后的表行数/列数是否一致"
            inspect_prompt += "\n2. SKILL-DQ-002：用 query_table_data 查看各表数据，检查是否有孤立空值（合并单元格未回填）"
            inspect_prompt += "\n3. SKILL-DQ-003：用 query_table_data 查看多级表头表，检查子列父项值是否完整回填"
            inspect_prompt += "\n\n检查完成后，在分析结论的末尾输出以下 JSON（用 ```json 包裹），供系统自动触发修复："
            inspect_prompt += "\n```json"
            inspect_prompt += "\n{\"skill_rule_issues\": ["
            inspect_prompt += "\n  {\"rule_id\": \"SKILL-DQ-001\", \"severity\": \"error\", \"table\": \"表名\", \"column\": \"列名或空\", \"description\": \"问题描述\", \"suggestion\": \"修复建议\"},"
            inspect_prompt += "\n  {\"rule_id\": \"SKILL-DQ-002\", \"severity\": \"pass\", \"table\": \"\", \"column\": \"\", \"description\": \"\", \"suggestion\": \"\"}"
            inspect_prompt += "\n]}"
            inspect_prompt += "\n```"
            inspect_prompt += "\nseverity 必须是 error/warning/pass 之一（SKILL-DQ 规则默认 error）。pass 表示该条规则检查通过。"
            inspect_prompt += "\n\n其他确定性检查结果也请分析，发现问题同样列出（含严重等级、修复建议）。"

            local_messages.append({"role": "user", "content": inspect_prompt})
            logger.info(f"[Inspector-DEBUG] INSPECT_RESULT report_len={len(report)} report_head={report[:200]} report_tail={report[-400:]}")
            yield {"type": "inspection_report", "report": report}

        elif message.reason == HandoffReason.FIX_COMPLETED:
            # 复查：重新预执行所有写入表（清缓存，加载最新数据）
            yield {"type": "inspecting", "message": f"正在复查 {len(_output_tables)} 张表的数据质量..."}
            from app.services.inspector_tools import inspector_tools
            _all_reports = []
            _all_check_results = {}
            for _idx, _tbl_info in enumerate(_output_tables, 1):
                _ds_id = _tbl_info.get("datasource_id", "")
                _tbl_name = _tbl_info.get("table_name", "")
                if not _ds_id or not _tbl_name:
                    continue
                yield {"type": "progress", "message": f"正在复查第 {_idx}/{len(_output_tables)} 张表：{_tbl_name}"}
                logger.info(f"[Inspector] 复查表 {_idx}/{len(_output_tables)}: {_tbl_name}")
                yield {"type": "progress", "message": f"  📊 {_tbl_name}：正在获取数据概览..."}
                async with _insp_session() as _chk_sess:
                    _cr = await inspector_tools.run_all_checks(_ds_id, _tbl_name, _chk_sess, skill_rules=skill_rules)
                _all_check_results[_tbl_name] = _cr
                _issue_count = sum(len(r.get("issues", [])) for r in _cr.values() if isinstance(r, dict))
                _dim_summary = []
                for _dim, _label in [("standards", "标准"), ("quality", "质量"), ("security", "安全")]:
                    _dr = _cr.get(_dim, {}) if isinstance(_cr, dict) else {}
                    _di = len(_dr.get("issues", [])) if isinstance(_dr, dict) else 0
                    _dim_summary.append(f"{_label}{_di}个问题" if _di else f"{_label}✅")
                logger.info(f"[Inspector] 表 {_tbl_name} 复查完成: {_issue_count} 个问题")
                yield {"type": "progress", "message": f"✓ {_tbl_name} 复查完成（{_issue_count} 个问题：{', '.join(_dim_summary)}）"}
                _rpt = inspector_tools.format_report(_cr, skill_rules=skill_rules)
                _all_reports.append(f"### 表: {_tbl_name}\n\n{_rpt}")
            context["_check_results"] = _all_check_results if len(_output_tables) > 1 else (list(_all_check_results.values())[0] if _all_check_results else {})
            report = "\n\n---\n\n".join(_all_reports) if _all_reports else "无写入表可检查"

            inspect_prompt = f"数据已修复并重新检查，结果如下：\n\n{report}\n\n"
            _user_msg = message.payload.get("user_message", "") or context.get("debug_user_message", "")
            if _user_msg:
                inspect_prompt += f"用户原始请求: {_user_msg[:500]}\n"
            inspect_prompt += _format_skill_rules_for_llm(skill_rules)
            inspect_prompt += "\n\n你可以使用 read_file 读取源文档、query_table_data 查看提取后的实际数据，来对照判断技能专属规则。"
            inspect_prompt += "\n\n检查完成后，在分析结论的末尾输出以下 JSON（用 ```json 包裹），供系统自动触发修复："
            inspect_prompt += "\n```json"
            inspect_prompt += "\n{\"skill_rule_issues\": ["
            inspect_prompt += "\n  {\"rule_id\": \"SKILL-DQ-001\", \"severity\": \"error\", \"table\": \"表名\", \"column\": \"列名或空\", \"description\": \"问题描述\", \"suggestion\": \"修复建议\"}"
            inspect_prompt += "\n]}"
            inspect_prompt += "\n```"
            inspect_prompt += "\nseverity 必须是 error/warning/pass 之一。pass 表示该条规则检查通过。"
            inspect_prompt += "\n请确认之前的问题是否已修复，并检查是否引入新问题。"

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

        # 预执行分支：LLM 可用工具读源文档/查数据做主观判断
        _tools = self.tools

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
                messages=local_messages, tools=_tools, temperature=0.3,
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

                # 最终结论：解析 SKILL-DQ JSON issue，塞入 check_results
                _skill_issues = _parse_skill_rule_issues(content)
                if _skill_issues:
                    _cr = context.get("_check_results", {})
                    if isinstance(_cr, dict):
                        _cr["skill_rule_issues"] = _skill_issues
                        context["_check_results"] = _cr
                    logger.info(f"[Inspector] 解析到 {len(_skill_issues)} 条技能规则 issue")
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
                # 自动从 context 填充数据源和表名（仅当 LLM 未手动传参时）
                if not func_args.get("datasource_id") and context.get("current_datasource_id"):
                    func_args["datasource_id"] = context.get("current_datasource_id")
                if not func_args.get("table_name") and context.get("current_table_name"):
                    func_args["table_name"] = context.get("current_table_name")
                ds_id = func_args.get("datasource_id", "")
                # UUID 解析（如果 ds_id 是名称而非 UUID）
                if ds_id:
                    try:
                        import uuid as _uuid
                        _uuid.UUID(str(ds_id))
                    except (ValueError, AttributeError):
                        try:
                            from app.models.datasource import DataSource as _DS
                            from sqlalchemy import select as _select
                            from app.core.database import async_session as _insp_session
                            async with _insp_session() as _ds_sess:
                                _r = await _ds_sess.execute(_select(_DS).where(_DS.name == str(ds_id)))
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

