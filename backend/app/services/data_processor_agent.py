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
- **能为用户生成和修改数据源连接器和模型适配器**

## 工作准则
1. **安全红线**：DataCrab 不能修改平台自身，只能处理用户数据
2. **输出默认同源**：处理后的数据默认写回原数据源
3. **修改后必验证**：每次修改数据后必须验证结果
4. **交接检查**：数据处理完成后，应交接给 DataInspector 进行质量检查
5. **准确优先**：所有数据结论必须基于工具返回的实际数据，不得编造或凭记忆推测

## 扩展能力（允许用户扩展平台的数据源连接器与大模型适配器）
当用户要求添加或删除数据源类型、大模型厂商时，你可以生成代码并调用工具注册或删除：

### save_connector — 添加数据源连接器
用户说"添加 MongoDB 连接器"时，生成一个继承 BaseConnector 的 Python 类，实现 connect/test_connection/get_schema/get_table_data/get_table_stats/close 方法。
代码中可通过 __import__ 使用第三方库（如 pymongo、redis 等），但禁止 import os/subprocess/sys 等危险模块。
同名或同显示名称的连接器会被覆盖更新（不会产生重复）。

### delete_connector — 删除数据源连接器
用户说"删除 MongoDB 连接器"时调用。已被数据源使用的连接器无法删除（需先删除相关数据源）。仅所有者或管理员可删。

### save_llm_adapter — 添加大模型适配器
用户说"添加 Anthropic Claude"时，生成一个适配器类，实现 .chat.completions.create() 兼容接口。
适配器接收 api_key/base_url/model 参数，将 OpenAI messages 格式转为厂商原生格式，调用厂商 API 后转回 OpenAI 响应格式。
禁止在适配器代码中硬编码 API Key。

### delete_llm_adapter — 删除大模型适配器
用户说"删除某个 Provider"时调用，传入 provider_name。

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

# 调试模式工具（modify_script + run_script + modify_and_run）
MODIFY_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "modify_script",
        "description": "修改当前调试的脚本（不执行）。提供修改后的函数代码，系统自动合并到现有脚本（函数级合并）并做语法检查。只需输出修改的函数，不用输出整个脚本。适用于需要多次修改后再执行的场景。",
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
        "description": "在沙箱中执行当前调试的脚本，返回执行结果。执行失败时会返回错误信息和修复提示。",
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

MODIFY_AND_RUN_TOOL = {
    "type": "function",
    "function": {
        "name": "modify_and_run",
        "description": "修改脚本并立即执行（推荐优先使用）。一步完成：合并代码 → 语法检查 → 执行验证。比分别调用 modify_script + run_script 更高效，节省一轮对话。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                "code": {"type": "string", "description": "修改后的函数代码（Python 代码，含 def 定义）"},
                "parameters": {"type": "object", "description": "执行参数（业务参数，如数据源名、表名、策略等）"},
            },
            "required": ["code"],
        },
    },
}

DEBUG_TOOLS = [MODIFY_SCRIPT_TOOL, RUN_SCRIPT_TOOL, MODIFY_AND_RUN_TOOL]

# 自定义扩展工具（save_connector + save_llm_adapter）

# BaseConnector 契约规范——save_connector 生成代码时必须严格遵守
CONNECTOR_CONTRACT = """BaseConnector 契约（所有方法必须是 async def）：
- async def connect(self) -> bool  # 建立连接，返回 True/False
- async def test_connection(self) -> bool  # 测试连接，返回 True/False（不是元组）
- async def get_schema(self) -> list[dict]  # 返回表列表，每个 dict 必须含 {"table_name": "xxx", "table_type": "xxx"}，不能返回单个 dict
- async def get_table_data(self, table: str, page: int = 1, page_size: int = 20, filters: dict = None, sort: dict = None) -> "pd.DataFrame"  # 签名必须含 page 和 page_size 参数，返回 pandas DataFrame（不是 list）
- async def get_table_stats(self, table: str) -> dict  # 返回 {"row_count": N}
- async def close(self) -> None  # 关闭连接
execute_query 可选，非结构化数据源无需实现（基类有默认空实现返回空 DataFrame）。"""

SAVE_CONNECTOR_TOOL = {
    "type": "function",
    "function": {
        "name": "save_connector",
        "description": "保存数据源连接器（新建或更新）。用户提供自然语言描述，你生成继承 BaseConnector 的 Python 类代码，系统验证后注册。注册后用户即可在数据源管理中创建该类型的数据源。同名或同显示名称的连接器会被覆盖更新，不会产生重复。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "连接器类型名（英文小写，如 mongodb、redis）。更新已有连接器时尽量沿用原 name"},
                "display_name": {"type": "string", "description": "显示名称（如 MongoDB）"},
                "description": {"type": "string", "description": "连接器描述"},
                "code": {"type": "string", "description": CONNECTOR_CONTRACT},
                "config_template": {"type": "array", "description": "配置项模板，前端据此动态渲染表单。每项 {name,label,type,required,default?,options?,depends_on?}。type 支持：string(文本)、number(数字)、password(密码)、boolean(开关)、select(下拉选择，需配 options:[{label,value}])、filepath(文件路径选择器，带浏览按钮)、folderpath(文件夹路径选择器)、filepath_list(多文件路径列表，可增删)。文件类连接器务必用 filepath/folderpath/filepath_list 而非 string，这样前端会显示文件浏览按钮。depends_on 可选，条件显隐，如 {\"mode\":\"files\"}", "items": {"type": "object", "properties": {"name": {"type": "string"}, "label": {"type": "string"}, "type": {"type": "string"}, "required": {"type": "boolean"}}}},
            },
            "required": ["name", "display_name", "code"],
        },
    },
}

SAVE_LLM_ADAPTER_TOOL = {
    "type": "function",
    "function": {
        "name": "save_llm_adapter",
        "description": "注册或更新大模型 Provider。已存在的 Provider 会被刷新更新。注册后可在模型配置中选择该 Provider。所有 Provider 地位平等。",
        "parameters": {
            "type": "object",
            "properties": {
                "provider_name": {"type": "string", "description": "厂商标识（英文小写，如 anthropic、google、moonshot）"},
                "display_name": {"type": "string", "description": "显示名称（如 Anthropic Claude）"},
                "description": {"type": "string", "description": "Provider 描述"},
                "api_base": {"type": "string", "description": "API 基础地址（如 https://api.moonshot.cn/v1）"},
                "models": {"type": "array", "description": "可用模型列表", "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}}}},
                "default_model": {"type": "string", "description": "默认深度模型名（用于深度推理场景，如 glm-5.2、moonshot-v1-128k）"},
                "fast_model": {"type": "string", "description": "快速模型名（用于简单任务，如 glm-4-flash、moonshot-v1-8k）"},
                "code": {"type": "string", "description": "适配器类代码（OpenAI 兼容厂商可不传，非兼容厂商必须传）。类必须实现 chat_completion(messages, model, temperature, max_tokens, stream) 方法"},
            },
            "required": ["provider_name", "display_name", "api_base"],
        },
    },
}

GET_LLM_CONFIG_TOOL = {
    "type": "function",
    "function": {
        "name": "get_llm_config",
        "description": "查询当前平台的 LLM 配置信息，包括当前使用的 Provider、模型、API地址、所有已注册的 Provider 列表。用户要求添加或更新模型时，先调用此工具了解现有配置。",
        "parameters": {"type": "object", "properties": {}},
    },
}

DELETE_LLM_ADAPTER_TOOL = {
    "type": "function",
    "function": {
        "name": "delete_llm_adapter",
        "description": "删除指定的 LLM Provider。用户要求删除、移除某个 Provider 时调用此工具。删除后该 Provider 不可用。",
        "parameters": {
            "type": "object",
            "properties": {
                "provider_name": {"type": "string", "description": "要删除的 Provider 标识（如 moonshot、deepseek）"},
            },
            "required": ["provider_name"],
        },
    },
}

DELETE_CONNECTOR_TOOL = {
    "type": "function",
    "function": {
        "name": "delete_connector",
        "description": "删除指定的数据源连接器。用户要求删除、移除某个连接器时调用此工具。已被数据源使用的连接器无法删除。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "要删除的连接器类型名（如 universal_file、generic_file）"},
            },
            "required": ["name"],
        },
    },
}

EXTENSION_TOOLS = [SAVE_CONNECTOR_TOOL, DELETE_CONNECTOR_TOOL, SAVE_LLM_ADAPTER_TOOL, GET_LLM_CONFIG_TOOL, DELETE_LLM_ADAPTER_TOOL]

# 加载统一技能规范（单一真相源）
_SPEC_PATH = Path(__file__).resolve().parent.parent / "defaults" / "SKILL_SPEC.md"
_SKILL_SPEC = _SPEC_PATH.read_text(encoding="utf-8") if _SPEC_PATH.exists() else ""

DEBUG_INSTRUCTIONS = """你是 DataCrab 平台的调试助手（DataProcessor 角色），正在调试一个脚本。

## 你的能力（通过工具调用）
1. **modify_and_run**（推荐）：修改脚本并立即执行，一步到位
2. **modify_script**: 仅修改脚本（不执行），适用于需要多次修改后再执行的场景
3. **run_script**: 执行脚本，获取结果
4. **handoff_to_inspector**: 执行成功后交接给 DataInspector 进行数据质量检查
5. **query_table_data / get_table_schema / write_table_data**: 查询/写入数据（通用数据处理工具）

## 工作流程
1. 分析用户问题或错误信息
2. **先在推理中分析错误根因**，确定修复方向后再改代码
3. 用 modify_and_run 修改并执行（推荐，一步到位）
4. 如果执行失败，根据错误信息和修复提示继续修改（自动重试，最多 {max_rounds} 轮）
5. 执行成功后，用 handoff_to_inspector 交接质量检查
6. 如果 DataInspector 发现问题，修改脚本修复后重新执行（最多 {max_inspections} 轮检查修复）

## 规则
- **优先使用 modify_and_run**，减少不必要的对话轮次
- 修改脚本时只需输出修改的函数，系统会自动合并并做语法检查
- run_script 的 parameters 必须包含技能所需的关键参数，不能为空
- 推理请简洁，直奔重点
- 看到错误后先分析根因，不要盲目尝试
- 执行成功后**必须**调用 handoff_to_inspector 交接质量检查

## 技能规范（脚本必须符合此规范）
""" + _SKILL_SPEC

DATA_PROCESSOR_TOOLS = SHARED_TOOL_SCHEMAS + [HANDOFF_TOOL] + EXTENSION_TOOLS


# 输出长度升级链（S）
_OUTPUT_TOKEN_ESCALATION = [3000, 6000, 12000]


def _analyze_error(error_msg: str) -> str:
    """分析错误信息，返回修复提示"""
    if not error_msg:
        return ""
    hints = []
    if "ModuleNotFoundError" in error_msg or "ImportError" in error_msg:
        import re as _re
        m = _re.search(r"No module named '(\S+)'", error_msg)
        mod = m.group(1) if m else "该模块"
        hints.append(f"缺少依赖模块 {mod}，请检查 import 语句或使用替代方案")
    elif "KeyError" in error_msg:
        import re as _re
        m = _re.search(r"KeyError: (.+)", error_msg)
        key = m.group(1).strip() if m else ""
        hints.append(f"字典键 {key} 不存在，请检查键名拼写或数据中是否包含该键")
    elif "TypeError" in error_msg and "argument" in error_msg:
        hints.append("参数类型/数量不匹配，请检查函数签名和传参")
    elif "TypeError" in error_msg:
        hints.append("类型不匹配，请检查变量类型是否正确")
    elif "IndexError" in error_msg:
        hints.append("索引越界，请检查列表/数组长度")
    elif "ValueError" in error_msg:
        hints.append("值不合法，请检查参数值范围")
    elif "AttributeError" in error_msg:
        import re as _re
        m = _re.search(r"has no attribute '(\w+)'", error_msg)
        attr = m.group(1) if m else "该属性"
        hints.append(f"对象没有属性/方法 '{attr}'，请检查对象类型")
    elif "SyntaxError" in error_msg:
        hints.append("语法错误，请检查代码格式（括号、缩进、冒号等）")
    elif "NameError" in error_msg:
        import re as _re
        m = _re.search(r"name '(\w+)' is not defined", error_msg)
        name = m.group(1) if m else "变量"
        hints.append(f"变量 '{name}' 未定义，请检查拼写或是否需要 import")
    elif "FileNotFoundError" in error_msg or "路径不存在" in error_msg:
        hints.append("文件/路径不存在，请检查路径是否正确")
    elif "连接" in error_msg or "Connection" in error_msg or "connect" in error_msg.lower():
        hints.append("数据库连接失败，请检查数据源配置和连接参数")
    elif "权限" in error_msg or "Permission" in error_msg:
        hints.append("权限不足，请检查用户权限")
    elif "表已存在" in error_msg or "already exists" in error_msg:
        hints.append("表已存在，请使用 if_table_exists 参数处理（如 truncate/drop/append）")
    elif "列" in error_msg and "不匹配" in error_msg:
        hints.append("列不匹配，请检查 column_mapping 配置和目标表结构")
    if hints:
        return hints[0]
    return ""


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
                fix_prompt += "\n请分析问题根源，修复数据，修复完成后使用 handoff_to_inspector 交接再检查。注意：这些都是 error 或 critical 级别问题，需要自动修复。fatal 级别问题不会交接给你（会直接停止），warning 级别问题由用户决定。"
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

        # 模型选择 + 降级链（与调试模式一致）
        chosen_model = llm_manager.pick_model(user_msg, context.get("history", []))
        from app.services.llm import _circuit
        degradation_chain = llm_manager._degradation_chain(chosen_model)

        for i in range(max_iterations):
            max_tokens = _OUTPUT_TOKEN_ESCALATION[min(output_token_idx, len(_OUTPUT_TOKEN_ESCALATION) - 1)]

            # 降级链：逐个尝试可用模型
            response = None
            for attempt_model in degradation_chain:
                if not _circuit.is_available(attempt_model):
                    continue
                try:
                    response = await llm_manager.chat_with_tools(
                        messages=local_messages, tools=self.tools, model=attempt_model,
                        temperature=0.3, max_tokens=max_tokens
                    )
                    _circuit.record_success(attempt_model)
                    if i == 0:
                        yield {"type": "model", "content": attempt_model}
                    break
                except Exception as e:
                    _circuit.record_failure(attempt_model)
                    logger.warning(f"模型 {attempt_model} 调用失败: {e}，尝试降级")
                    continue
            if response is None:
                yield {"type": "content", "content": "所有模型均不可用，请稍后重试或检查模型配置。"}
                yield {"type": "done", "result": {"error": "all models unavailable"}}
                return
            tool_calls = response.get("tool_calls", [])
            finish_reason = response.get("finish_reason")

            # 输出长度升级（S）
            if finish_reason == "length" and output_token_idx < len(_OUTPUT_TOKEN_ESCALATION) - 1:
                output_token_idx += 1
                logger.warning(f"输出被截断(finish_reason=length)，升级 max_tokens 到 {_OUTPUT_TOKEN_ESCALATION[output_token_idx]}")
                local_messages.append({"role": "assistant", "content": response.get("content") or ""})
                local_messages.append({"role": "user", "content": "上一段输出被截断了，请用更大的输出长度重新生成完整内容。"})
                continue

            # 推理过程（GLM 等推理模型返回 reasoning_content）
            reasoning = response.get("reasoning")
            if reasoning:
                yield {"type": "thinking", "content": reasoning}

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

                # AST 语法预检
                import ast as _ast
                try:
                    _ast.parse(merged)
                except SyntaxError as _se:
                    logger.warning(f"modify_script 语法错误: {_se}")
                    return json.dumps({
                        "success": False,
                        "error": f"语法错误（第{_se.lineno}行）: {_se.msg}",
                        "syntax_error": True,
                        "merged_preview": merged[:3000],
                    }, ensure_ascii=False)

                # diff 摘要
                diff_lines = _compute_diff_summary(current, merged)

                return json.dumps({
                    "success": True,
                    "script_name": script_name,
                    "message": "脚本已更新，语法检查通过",
                    "merged_preview": merged[:8000],
                    "changed_lines": diff_lines,
                }, ensure_ascii=False)
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
                        user_id=str(user_id) if user_id else None,
                    )
                    _inner = result.get("result") if isinstance(result.get("result"), dict) else {}
                    _failed = (not result.get("success")
                               or ("success" in _inner and not _inner["success"])
                               or (result.get("error") and str(result.get("error")).strip())
                               or (_inner.get("error") and str(_inner.get("error")).strip()))
                    if not _failed:
                        context["debug_last_success_params"] = parameters
                    else:
                        _err = str(result.get("error") or _inner.get("error") or "")
                        _hint = _analyze_error(_err)
                        if _hint:
                            result["error_hint"] = _hint
                    logger.info(f"debug run_script (skill): success={not _failed}")
                    return json.dumps(result, ensure_ascii=False, default=str)
            except Exception as e:
                logger.warning(f"run_script 失败: {e}")
                _hint = _analyze_error(str(e))
                return json.dumps({"success": False, "error": str(e), **({"error_hint": _hint} if _hint else {})}, ensure_ascii=False)

        if name == "modify_and_run":
            # 合并工具：modify_script + run_script 一步到位
            _modify_result = await self._execute_tool("modify_script", {
                "code": arguments.get("code", ""),
                "script_name": arguments.get("script_name") or context.get("debug_script_name", "main.py"),
            }, db, user_id, context)
            try:
                _mdata = json.loads(_modify_result)
            except json.JSONDecodeError:
                _mdata = {"success": False, "error": "modify 结果解析失败"}
            if not _mdata.get("success"):
                # 修改失败（含语法错误）→ 直接返回，不执行
                return _modify_result
            # 修改成功 → 执行
            _run_result = await self._execute_tool("run_script", {
                "script_name": arguments.get("script_name") or context.get("debug_script_name", "main.py"),
                "parameters": arguments.get("parameters", {}),
            }, db, user_id, context)
            try:
                _rdata = json.loads(_run_result)
            except json.JSONDecodeError:
                _rdata = {"success": False, "error": "run 结果解析失败"}
            # 合并结果
            _rdata["modify"] = _mdata
            _rdata["script_name"] = _mdata.get("script_name", "main.py")
            return json.dumps(_rdata, ensure_ascii=False, default=str)

        # ---- 自定义扩展工具 ----
        if name == "save_connector":
            return await self._handle_save_connector(arguments, db, user_id)

        if name == "delete_connector":
            return await self._handle_delete_connector(arguments, db, user_id)

        if name == "save_llm_adapter":
            return await self._handle_save_llm_adapter(arguments, db, user_id)

        if name == "delete_llm_adapter":
            return await self._handle_delete_llm_adapter(arguments)

        if name == "get_llm_config":
            return await self._handle_get_llm_config()

        return await execute_shared_tool(name, arguments, db, user_id)

    async def _handle_save_connector(self, arguments: dict, db: AsyncSession, user_id) -> str:
        """保存数据源连接器：验证代码 → 存 DB → 注册缓存"""
        import json as _json
        connector_name = arguments.get("name", "").strip().lower()
        display_name = arguments.get("display_name", connector_name)
        description = arguments.get("description", "")
        code = arguments.get("code", "")
        config_template = arguments.get("config_template", [])

        if not connector_name or not code:
            return _json.dumps({"success": False, "error": "缺少 name 或 code"}, ensure_ascii=False)

        # 验证代码：能 exec + 找到 BaseConnector 子类
        from app.services.connectors import register_custom_connector
        try:
            register_custom_connector(connector_name, code)
        except Exception as e:
            return _json.dumps({"success": False, "error": f"代码验证失败: {e}"}, ensure_ascii=False)

        # 存入数据库（覆盖同名或同 display_name，避免重复）— 用独立 session 避免与流式 session 冲突
        from app.core.database import async_session
        from app.models.custom_extension import CustomConnector
        from sqlalchemy import select as sa_select, or_
        async with async_session() as save_session:
            existing = await save_session.execute(
                sa_select(CustomConnector).where(
                    or_(CustomConnector.name == connector_name, CustomConnector.display_name == display_name),
                    CustomConnector.is_active == True,
                )
            )
            # 用 first() 而非 scalar_one_or_none()，避免已有重复记录时报 MultipleResultsFound
            record = existing.scalars().first()
            if record:
                # 覆盖已有记录（保持原 name 不变，避免破坏已创建的数据源引用）
                record.display_name = display_name
                record.description = description
                record.code = code
                record.config_template = config_template
                record.is_active = True
                # 若存在其他同 display_name 的重复记录，停用它们
                dup_result = await save_session.execute(
                    sa_select(CustomConnector).where(
                        CustomConnector.display_name == display_name,
                        CustomConnector.is_active == True,
                        CustomConnector.id != record.id,
                    )
                )
                for dup in dup_result.scalars().all():
                    dup.is_active = False
            else:
                record = CustomConnector(
                    name=connector_name,
                    display_name=display_name,
                    description=description,
                    code=code,
                    config_template=config_template,
                    created_by=user_id,
                )
                save_session.add(record)
            await save_session.commit()
            logger.info(f"连接器已保存: {record.name} (display={display_name})")
            return _json.dumps({"success": True, "message": f"连接器 '{display_name}' 已注册，现在可以在数据源管理中创建该类型的数据源"}, ensure_ascii=False)

    async def _handle_delete_connector(self, arguments: dict, db: AsyncSession, user_id) -> str:
        """删除数据源连接器：校验所有权 + 数据源使用 → 软删除 + 移除注册"""
        import json as _json
        connector_name = arguments.get("name", "").strip().lower()
        if not connector_name:
            return _json.dumps({"success": False, "error": "缺少 name"}, ensure_ascii=False)

        from app.core.database import async_session
        from app.models.custom_extension import CustomConnector
        from app.models.datasource import DataSource
        from app.models.user import User
        from sqlalchemy import select as sa_select, func
        async with async_session() as del_session:
            result = await del_session.execute(
                sa_select(CustomConnector).where(CustomConnector.name == connector_name, CustomConnector.is_active == True)
            )
            record = result.scalar_one_or_none()
            if not record:
                return _json.dumps({"success": False, "error": f"连接器 '{connector_name}' 不存在"}, ensure_ascii=False)

            # 所有权：仅所有者或超管可删
            user_result = await del_session.execute(sa_select(User).where(User.id == user_id))
            cur_user = user_result.scalar_one_or_none()
            is_super = bool(cur_user and cur_user.is_superuser)
            if record.created_by != user_id and not is_super:
                return _json.dumps({"success": False, "error": "无权删除此连接器（仅所有者或管理员可删）"}, ensure_ascii=False)

            # 限制：已被数据源使用的连接器不能删除
            ds_count = await del_session.scalar(
                sa_select(func.count(DataSource.id)).where(
                    DataSource.type == connector_name,
                    DataSource.is_active == True,
                )
            )
            if ds_count and ds_count > 0:
                return _json.dumps({"success": False, "error": f"该连接器已被 {ds_count} 个数据源使用，无法删除。请先删除或迁移相关数据源"}, ensure_ascii=False)

            display_name = record.display_name or connector_name
            record.is_active = False
            await del_session.commit()

        # 从内存注册表移除
        from app.services.connectors import _connector_registry, _sync_supported_types
        _connector_registry.pop(connector_name, None)
        _sync_supported_types()

        logger.info(f"连接器已删除: {connector_name}")
        return _json.dumps({"success": True, "message": f"连接器 '{display_name}' ({connector_name}) 已删除"}, ensure_ascii=False)

    async def _handle_save_llm_adapter(self, arguments: dict, db: AsyncSession, user_id) -> str:
        """注册或更新 LLM Provider：验证代码 → 存 DB → 注册缓存（已存在则刷新）"""
        import json as _json
        provider_name = arguments.get("provider_name", "").strip().lower()
        display_name = arguments.get("display_name", provider_name)
        description = arguments.get("description", "")
        api_base = arguments.get("api_base", "")
        models = arguments.get("models", [])
        default_model = arguments.get("default_model", "")
        fast_model = arguments.get("fast_model", "")
        code = arguments.get("code", "")

        if not provider_name or not api_base:
            return _json.dumps({"success": False, "error": "缺少 provider_name 或 api_base"}, ensure_ascii=False)

        # 如果有适配器代码，验证；OpenAI 兼容厂商可不传 code
        if code:
            from app.services.llm import register_custom_adapter
            try:
                register_custom_adapter(provider_name, code)
            except Exception as e:
                return _json.dumps({"success": False, "error": f"适配器代码验证失败: {e}"}, ensure_ascii=False)

        # 存入数据库（已存在则更新）— 用独立 session 避免与流式 session 冲突
        from app.core.database import async_session
        from app.models.custom_extension import LLMProvider
        from sqlalchemy import select as sa_select
        async with async_session() as save_session:
            existing = await save_session.execute(sa_select(LLMProvider).where(LLMProvider.provider_name == provider_name))
            record = existing.scalar_one_or_none()
            if record:
                record.display_name = display_name
                record.description = description
                record.api_base = api_base
                record.models = models
                record.default_model = default_model
                record.fast_model = fast_model
                if code:
                    record.code = code
                record.is_active = True
            else:
                record = LLMProvider(
                    provider_name=provider_name,
                    display_name=display_name,
                    description=description,
                    api_base=api_base,
                    models=models,
                    default_model=default_model,
                    fast_model=fast_model,
                    code=code or None,
                    created_by=user_id,
                )
                save_session.add(record)
            await save_session.commit()

        # 刷新内存缓存
        from app.services.llm import refresh_provider
        refresh_provider(provider_name, {
            "display_name": display_name,
            "description": description,
            "api_base": api_base,
            "models": models,
            "default_model": default_model,
            "fast_model": fast_model,
            "code": code or None,
        })

        logger.info(f"Provider 已保存: {provider_name}")
        return _json.dumps({"success": True, "message": f"Provider '{display_name}' 已注册，可在模型配置中使用"}, ensure_ascii=False)

    async def _handle_get_llm_config(self) -> str:
        """查询当前 LLM 配置"""
        import json as _json
        from app.services.llm import get_all_providers, get_provider_api_base

        all_providers = []
        for name, info in get_all_providers().items():
            all_providers.append({
                "name": name,
                "display_name": info.get("display_name", name),
                "description": info.get("description", ""),
                "api_base": info.get("api_base", "") or "",
                "models": info.get("models", []),
                "fast_model": info.get("fast_model", ""),
            })

        return _json.dumps({
            "current_provider": llm_manager.provider,
            "current_model": llm_manager.model,
            "current_api_base": llm_manager.api_base or get_provider_api_base(llm_manager.provider) or "",
            "fast_model": llm_manager.fast_model,
            "api_key_configured": bool(llm_manager.api_key),
            "providers": all_providers,
            "hint": "用户要求注册或更新 Provider 时，始终调用 save_llm_adapter 工具。已存在的 Provider 会被刷新更新。所有 Provider 地位平等。用户要求删除 Provider 时，调用 delete_llm_adapter 工具。"
        }, ensure_ascii=False)

    async def _handle_delete_llm_adapter(self, arguments: dict) -> str:
        """删除 LLM Provider"""
        import json as _json
        provider_name = arguments.get("provider_name", "").strip().lower()
        if not provider_name:
            return _json.dumps({"success": False, "error": "缺少 provider_name"}, ensure_ascii=False)

        from app.core.database import async_session
        from app.models.custom_extension import LLMProvider
        from sqlalchemy import select as sa_select
        async with async_session() as session:
            result = await session.execute(
                sa_select(LLMProvider).where(LLMProvider.provider_name == provider_name, LLMProvider.is_active == True)
            )
            record = result.scalar_one_or_none()
            if not record:
                return _json.dumps({"success": False, "error": f"Provider '{provider_name}' 不存在"}, ensure_ascii=False)

            display_name = record.display_name or provider_name
            record.is_active = False
            await session.commit()

        # 从内存缓存移除
        from app.services.llm import _custom_adapter_cache, _provider_registry
        _custom_adapter_cache.pop(provider_name, None)
        _provider_registry.pop(provider_name, None)

        logger.info(f"Provider 已删除: {provider_name}")
        return _json.dumps({"success": True, "message": f"Provider '{display_name}' ({provider_name}) 已删除"}, ensure_ascii=False)

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
            thinking_content = ""
            tool_calls = []
            finish_reason = None
            clear_thinking = False

            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=debug_tools, temperature=0.1, max_tokens=8000,
            ):
                t = event["type"]
                if t == "thinking":
                    thinking_content += event.get("content", "")
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
                # content 已在流式循环中逐块 yield，此处不再重复发送
                yield {"type": "done", "result": {"agent": self.name, "content": content}}
                return

            had_any_tool_calls = True

            # 空轮次补充：LLM 直接调用工具但未输出推理/正文时，补一句提示让用户知道这轮做了什么
            if not content:
                _TOOL_LABELS = {
                    "modify_script": "修改脚本", "run_script": "执行脚本",
                    "modify_and_run": "修改并执行脚本", "save_connector": "保存连接器",
                    "delete_connector": "删除连接器", "query_table_data": "查询数据",
                    "get_table_schema": "获取表结构", "list_user_datasources": "列出数据源",
                    "handoff_to_inspector": "交接检查", "save_llm_adapter": "保存模型适配器",
                    "delete_llm_adapter": "删除模型适配器", "get_llm_config": "查询模型配置",
                    "kb_search": "知识库检索", "save_file_to_link": "保存文件",
                }
                _labels = [_TOOL_LABELS.get(tc["function"]["name"], tc["function"]["name"]) for tc in tool_calls]
                yield {"type": "content", "content": f"（执行操作：{' → '.join(_labels)}）"}

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

            # 执行前：如果有 run_script / modify_and_run 工具，先通知前端"正在执行"
            for tc in tool_calls:
                if tc["function"]["name"] == "modify_and_run":
                    yield {"type": "executing", "message": "正在修改并执行脚本..."}
                    break
                elif tc["function"]["name"] == "run_script":
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

                elif tool_name == "modify_and_run":
                    try:
                        rdata = json.loads(r["content"])
                        # 修改成功 → yield script_updated
                        _mdata = rdata.get("modify", {})
                        if _mdata.get("success"):
                            yield {"type": "script_updated", "script_name": rdata.get("script_name", "main.py")}
                        # 执行结果 → yield run_result + 失败检测（同 run_script 逻辑）
                        yield {"type": "run_result", "result": rdata}
                        _inner_r = rdata.get("result") if isinstance(rdata.get("result"), dict) else {}
                        _is_fail = (not rdata.get("success")
                                    or ("success" in _inner_r and not _inner_r["success"])
                                    or (rdata.get("error") and str(rdata.get("error")).strip())
                                    or (_inner_r.get("error") and str(_inner_r.get("error")).strip()))
                        _err_msg = str(rdata.get("error") or _inner_r.get("error") or "")
                        if _is_fail:
                            if not _err_msg:
                                _err_msg = "执行返回失败（success=False），无明确错误信息"
                            _sig = _err_msg[:100]
                            if _sig == _last_error_sig:
                                _same_error_count += 1
                            else:
                                _last_error_sig = _sig
                                _same_error_count = 1
                            folder = context.get("debug_folder")
                            if folder:
                                try:
                                    from app.services import experience as _exp
                                    _ctx_summary = f"工具: {tool_name}\n推理摘要: {thinking_content[:400]}\nAI输出: {content[:200]}"
                                    _exp.append_negative(folder, source="debug-chat", error_type="execution_error", error_message=_err_msg, stdout=rdata.get("stdout", ""), script_name=script_name, context_summary=_ctx_summary)
                                except Exception:
                                    pass
                            if _same_error_count >= 3:
                                yield {"type": "content", "content": f"\n连续 {_same_error_count} 次出现相同错误，自动停止重试。"}
                                _should_stop = True
                                break
                        elif not _is_fail:
                            _last_error_sig = None
                            _same_error_count = 0
                            _run_succeeded = True
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
            messages=local_messages, tools=debug_tools, temperature=0.1, max_tokens=4000,
        ):
            if event["type"] in ("thinking", "content"):
                yield event
                if event["type"] == "content":
                    full_content += event["content"]
        yield {"type": "give_up", "reason": full_content[:2000]}

        # 将"无法修复"的原因分析存入经验库，下次调试可直接参考
        folder = context.get("debug_folder")
        if folder:
            try:
                from app.services import experience as _exp
                _exp.write_lessons(folder, full_content.strip())
                logger.info(f"已将 give_up 分析存入经验库: {folder}")
            except Exception as e:
                logger.warning(f"存储 give_up 经验失败: {e}")

        yield {"type": "done", "result": {"agent": self.name, "content": full_content}}
