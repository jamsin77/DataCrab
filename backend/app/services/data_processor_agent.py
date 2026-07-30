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
from typing import Dict, Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.services.multi_agent import BaseAgent, AgentMessage, HandoffReason
from app.services.llm import llm_manager
from app.services.shared_tools import SHARED_TOOL_SCHEMAS, execute_shared_tool
from app.services.agent_utils import (
    truncate_tool_result,
    estimate_tokens,
    extract_identifiers,
    build_identifier_hint,
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
)
from app.services.tool_guidance import get_tool_guidance
from app.services.prompt_docs import SANDBOX_TOOLS_DOC, PLATFORM_CONVENTIONS_DOC

DATA_PROCESSOR_INSTRUCTIONS = """你是 DataCrab 的 DataProcessor（数据处理智能体），一位数据处理专家。

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
6. **翻译优先用算子**：涉及文本翻译（如中英文互译、列翻译、表名/列名翻译）时，优先调用「文本翻译」算子完成，不要在脚本中自行编写 LLM 翻译逻辑

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
- 数据处理完成后，使用 handoff_to_inspector 交接给 DataInspector
- 当用户请求是数据质量检查相关时，直接交接（delegate）给 DataInspector
"""

# handoff 工具（DataProcessor 专用）
HANDOFF_TOOL = {
    "type": "function",
    "function": {
        "name": "handoff_to_inspector",
        "description": "将处理结果交接给 DataInspector 进行质量检查。无需传参，自动使用当前调试的数据源和表",
        "parameters": {
            "type": "object",
            "properties": {
                "operation_description": {"type": "string", "description": "本次数据处理的操作描述"},
                "result_summary": {"type": "string", "description": "处理结果摘要"},
            },
        },
    },
}

# 调试模式工具（modify_script + run_script + modify_and_run）
MODIFY_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "modify_script",
        "description": "修改当前调试的技能/脚本（不执行）。提供修改后的函数代码（可含多个 def 定义），系统自动合并到现有脚本（同名函数替换，新函数自动插入 if __name__ 之前）并做语法检查。技能调试时若需更新参数规范/描述等技能元信息，可通过 skill_md 一并提供更新后的完整 SKILL.md 全文，系统会同步写入。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                "code": {"type": "string", "description": "修改后的函数代码（可含一个或多个 def 定义；同名函数替换，新函数自动插入 if __name__ 之前）"},
                "skill_md": {"type": "string", "description": "（仅技能调试）更新后的完整 SKILL.md 全文。当需要新增/修改参数规范、描述等技能元信息时提供。修改函数签名（增减参数）时务必同步更新此处的参数规范表。算子/流程调试无需此参数。"},
            },
            "required": ["code"],
        },
    },
}

RUN_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "run_script",
        "description": "运行当前调试的技能/脚本（在沙箱中执行），返回执行结果。技能调试时参数须符合 SKILL.md 参数规范表（必选参数不可缺失）。执行失败时会返回错误信息和修复提示。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                "parameters": {"type": "object", "description": "执行参数（业务参数，如数据源名、表名、策略等），须符合 SKILL.md 参数规范"},
            },
            "required": [],
        },
    },
}

MODIFY_AND_RUN_TOOL = {
    "type": "function",
    "function": {
        "name": "modify_and_run",
        "description": "修改技能/脚本并立即执行（推荐优先使用）。一步完成：合并代码（+ 可选更新 SKILL.md）→ 语法检查 → 执行验证。比分别调用 modify_script + run_script 更高效，节省一轮对话。支持一次输出多个函数（同名替换，新函数自动插入 if __name__ 之前）。技能调试时可通过 skill_md 同步更新技能规范。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                "code": {"type": "string", "description": "修改后的函数代码（可含一个或多个 def 定义；同名函数替换，新函数自动插入 if __name__ 之前）"},
                "skill_md": {"type": "string", "description": "（仅技能调试）更新后的完整 SKILL.md 全文。需要新增/修改参数规范、描述等技能元信息时提供。算子/流程调试无需此参数。"},
                "parameters": {"type": "object", "description": "执行参数（业务参数，如数据源名、表名、策略等），须符合 SKILL.md 参数规范"},
            },
            "required": ["code"],
        },
    },
}

EDIT_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_script",
        "description": "行级补丁修改脚本（不执行）。提供 old_string（脚本中唯一存在的原文片段）和 new_string（替换内容），系统精确定位并替换，只改动需要变化的部分。适合小修改——输出量小、不会截断。old_string 必须逐字匹配且唯一；不唯一时多带几行上下文；找不到时先调 read_script 查看逐字内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                "old_string": {"type": "string", "description": "脚本中要被替换的原文片段（逐字复制，必须唯一匹配）。多带几行上下文以保证唯一。"},
                "new_string": {"type": "string", "description": "替换后的新内容（保持正确缩进）"},
                "skill_md": {"type": "string", "description": "（仅技能调试）更新后的完整 SKILL.md 全文。需要改参数规范/描述时提供。"},
            },
            "required": ["old_string", "new_string"],
        },
    },
}

EDIT_AND_RUN_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_and_run",
        "description": "行级补丁修改脚本并立即执行（小修改首选，推荐优先使用）。一步完成：精确补丁 → 语法检查 → 执行验证。比 modify_and_run 更省 token（只输出改动片段，不重写整函数，不会截断）。old_string 必须逐字唯一匹配；不匹配会报错，此时先调 read_script 查看逐字内容再重试。大范围重写（整函数/多函数）才用 modify_and_run。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                "old_string": {"type": "string", "description": "脚本中要被替换的原文片段（逐字复制，必须唯一匹配）"},
                "new_string": {"type": "string", "description": "替换后的新内容（保持正确缩进）"},
                "parameters": {"type": "object", "description": "执行参数（业务参数，如数据源名、表名、策略等），须符合 SKILL.md 参数规范"},
                "skill_md": {"type": "string", "description": "（仅技能调试）更新后的完整 SKILL.md 全文。"},
            },
            "required": ["old_string", "new_string"],
        },
    },
}

READ_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "read_script",
        "description": "读取代码的逐字内容（不压缩，带行号）。默认返回前 2000 行，大文件用 grep_script 搜关键词定位行号后，传 offset/limit 只读相关行。scope='script'（默认）读当前调试脚本，行级补丁前调用获取精确 old_string；scope='platform' 读平台源码指定行范围。平台代码只读，不可修改。",
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["script", "platform"], "description": "script=用户脚本（默认），platform=平台源码"},
                "script_name": {"type": "string", "description": "脚本文件名（仅 scope=script）"},
                "function_name": {"type": "string", "description": "可选，仅 scope=script 时读取指定函数"},
                "file_path": {"type": "string", "description": "平台源码文件名（仅 scope=platform，如 connectors.py）"},
                "offset": {"type": "integer", "description": "起始行号（1-indexed，grep 到行号后用 offset=行号-5）"},
                "limit": {"type": "integer", "description": "读取行数（不传时默认返回前 2000 行；配合 offset 只读相关行，如 limit=15）"},
            },
            "required": [],
        },
    },
}

GREP_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "grep_script",
        "description": "在代码中搜索（正则匹配），返回匹配行+行号+上下文。定位行号后传给 read_script 的 offset 参数只读相关行。scope='script'（默认）搜当前调试脚本；scope='platform' 搜平台源码（connectors.py/skill_runner.py 等）。例如：grep_script('write_table_data') 找到行号 123，再 read_script(offset=118, limit=15) 读上下文。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则表达式（默认大小写不敏感）"},
                "scope": {"type": "string", "enum": ["script", "platform"], "description": "script=搜用户脚本（默认），platform=搜平台源码"},
                "script_name": {"type": "string", "description": "脚本文件名（仅 scope=script）"},
                "function_name": {"type": "string", "description": "可选，仅 scope=script 时限定函数范围"},
                "file_filter": {"type": "string", "description": "可选，仅 scope=platform 时限定文件名（如 connectors.py）"},
                "context_lines": {"type": "integer", "description": "上下文行数（默认 3）"},
                "case_sensitive": {"type": "boolean", "description": "是否大小写敏感（默认 false）"},
            },
            "required": ["pattern"],
        },
    },
}

DEBUG_TOOLS = [MODIFY_SCRIPT_TOOL, RUN_SCRIPT_TOOL, MODIFY_AND_RUN_TOOL, EDIT_SCRIPT_TOOL, EDIT_AND_RUN_TOOL, READ_SCRIPT_TOOL, GREP_SCRIPT_TOOL]

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


_PLATFORM_ISSUE_SIGNALS = [
    "平台问题", "平台能力缺失", "平台不支持", "平台限制",
    "不是脚本问题", "修改脚本无法解决", "无法绕过", "平台 bug",
    "连接器不支持", "连接器无法", "沙箱不支持", "沙箱未注入",
    "platform issue", "connector does not support",
]

def _is_platform_issue_report(content: str) -> bool:
    """检测 agent 输出是否明确判定为平台问题（而非脚本问题）。
    排除疑问句（"是不是"/"是否"/"让我看看"等），避免调查阶段误触发。"""
    if not content or len(content) < 4:
        return False
    # 疑问/调查句式 → 不是结论，不触发
    _investigation_markers = ["是不是", "是否", "让我看看", "让我检查", "看一下", "检查一下", "确认一下", "需要确认"]
    if any(m in content for m in _investigation_markers):
        return False
    return any(sig in content for sig in _PLATFORM_ISSUE_SIGNALS)

DEBUG_INSTRUCTIONS = """你是 DataCrab 调试助手。修复前先判断：这是DataCrab能修复的技能错误吗？平台限制（连接器不支持创建新文件/表等）直接报告不可修复，不要硬改脚本。
看错误信息，修复脚本并执行。每次修改都要全力解决问题，不要指望下一次。执行成功后系统自动检查数据质量，无需手动操作。总共 {max_rounds} 轮，执行错误最多 {max_exec_failures} 次。

## 必须遵守
- 平台已内置 llm_vision/llm_chat/call_operator/query_table_data/write_table_data 等函数，**必须优先使用内置函数**，不要在脚本中安装数据库扩展（如 plpython3u）、不要直接调用外部 API、不要自己造轮子
- 下方「内置工具函数」文档列出了所有可用函数和签名，修改脚本前先看
"""

# 技能调试额外说明：把调试对象从「脚本」提升为「技能」整体（SKILL.md 规范 + 脚本）
SKILL_DEBUG_EXTRA = """

## 技能级操作说明（你正在调试技能，不是孤立脚本）
技能 = SKILL.md 规范（参数定义/描述/处理类型）+ scripts/main.py 脚本。你的修改和运行都应面向技能整体：
- **修改技能**：通过 `code` 修改脚本函数（函数级合并）；若需新增/修改参数规范、描述等技能元信息，通过 `skill_md` 提供**更新后的完整 SKILL.md 全文**，系统会一并写入。两者可在同一次 modify_and_run 调用中同时提供。
- **运行技能**：`run_script` 的 parameters 必须符合 SKILL.md 参数规范表（必选参数不可缺失，系统会校验并告警）。
- **保持一致**：修改函数签名（增减参数）时，务必同步更新 SKILL.md 的参数规范表，使脚本与技能规范一致。
- SKILL.md 全文已在下方展示，需要修改时输出完整新版本到 skill_md 参数。
"""

# 调试 system prompt 静态前缀缓存（借鉴 DeepAnalyze sectionCache：字节稳定 → 命中 prefix cache）
# key = (is_skill, max_rounds, max_inspections)；一次会话内不变
_DEBUG_STATIC_PROMPT_CACHE: Dict[tuple, str] = {}

DATA_PROCESSOR_TOOLS = SHARED_TOOL_SCHEMAS + [HANDOFF_TOOL] + EXTENSION_TOOLS


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
        has_preinjected_data = context.get("has_preinjected_data", False)

        # 模型选择 + 降级链（与调试模式一致）
        chosen_model = await llm_manager.pick_model_async(user_msg, context.get("history", []))
        from app.services.llm import _circuit
        degradation_chain = llm_manager._degradation_chain(chosen_model)

        for i in range(max_iterations):
            logger.info(f"[run] 第{i+1}轮开始, budget={max_iterations}")
            yield {"type": "round", "round": i + 1}

            # 上下文压缩（对齐 OpenCode compaction）
            if should_compact(local_messages):
                local_messages = await compact_messages(local_messages, llm_manager)

            # 降级链：逐个尝试可用模型
            response = None
            for attempt_model in degradation_chain:
                if not _circuit.is_available(attempt_model):
                    continue
                try:
                    response = await llm_manager.chat_with_tools(
                        messages=local_messages, tools=self.tools, model=attempt_model,
                        temperature=0.3
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

            # 推理过程（GLM 等推理模型返回 reasoning_content）
            reasoning = response.get("reasoning")
            if reasoning:
                yield {"type": "thinking", "content": reasoning}

            if not tool_calls:
                content = response.get("content", "")

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
            try:
                result = await self._execute_tool(tc["function"]["name"], func_args, db, user_id, context)
                return {"tool_call_id": tc["id"], "content": result}
            except Exception as e:
                logger.error(f"平台工具异常 {tc['function']['name']}: {e}")
                return {"tool_call_id": tc["id"], "content": json.dumps({"success": False, "error": f"平台工具异常（这不是脚本问题，修改脚本无法解决）: {tc['function']['name']} 执行失败 - {e}"}, ensure_ascii=False)}

        results = await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])
        return list(results)

    @staticmethod
    def _script_summary(script: str, script_name: str = "main.py") -> str:
        """生成脚本摘要：函数名+行号+docstring 首行，不放假代码。agent 按需用 grep_script/read_script 查看。"""
        lines = script.splitlines()
        total = len(lines)
        try:
            import ast
            tree = ast.parse(script)
            funcs = []
            imports = []
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    seg = ast.get_source_segment(script, node) or ""
                    imports.append(seg.strip())
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node) or ""
                    doc_first = doc.split('\n')[0].strip() if doc else ""
                    # 完整签名：含 *args/**kwargs，不截断（截断会让 LLM 重写时漏 **kwargs → runner 传参 TypeError）
                    sig_parts = [a.arg for a in node.args.args]
                    if node.args.vararg:
                        sig_parts.append(f"*{node.args.vararg.arg}")
                    elif node.args.kwonlyargs:
                        sig_parts.append("*")
                    sig_parts.extend(a.arg for a in node.args.kwonlyargs)
                    if node.args.kwarg:
                        sig_parts.append(f"**{node.args.kwarg.arg}")
                    args = ", ".join(sig_parts)
                    funcs.append(f"- L{node.lineno} {node.name}({args}){' — ' + doc_first if doc_first else ''}")
            result = f"## 当前脚本（{script_name}，共 {total} 行）\n"
            if imports:
                result += f"导入: {'; '.join(imports[:5])}{'...' if len(imports) > 5 else ''}\n"
            if funcs:
                result += "函数列表:\n" + "\n".join(funcs)
            else:
                result += "(无可解析的函数)"
            result += "\n需要查看具体代码时用 read_script（看某函数全文）或 grep_script（搜关键词）。"
            return result
        except SyntaxError:
            return f"## 当前脚本（{script_name}，共 {total} 行）\n脚本有语法错误，用 read_script 查看逐字内容。"

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

    @staticmethod
    def _save_session_log(local_messages: list, context: dict, inspection_round: int):
        """从 local_messages 提取调试历史，保存到 context 供 DataInspector 回交后参考。"""
        _session_entries = []
        _round_num = 0
        for _msg in local_messages:
            if _msg["role"] == "assistant" and _msg.get("tool_calls"):
                _round_num += 1
                _names = [tc["function"]["name"] for tc in _msg["tool_calls"]]
                _summary = (_msg.get("content") or "")[:200]
                _session_entries.append(f"第{_round_num}轮: 调用 {' '.join(_names)}")
                if _summary.strip():
                    _session_entries.append(f"  说明: {_summary}")
            elif _msg["role"] == "tool":
                try:
                    _td = json.loads(_msg["content"])
                    if isinstance(_td, dict):
                        if not _td.get("success"):
                            _e = str(_td.get("error") or _td.get("message") or "")[:200]
                            _session_entries.append(f"  结果: 失败 — {_e}")
                        elif _td.get("modify") and _td.get("result"):
                            _diff = _td.get("diff_summary") or []
                            _diff_str = ", ".join(_diff[:5]) if _diff else "未知"
                            _inner = _td.get("result", {})
                            _ok = _inner.get("success", True) if isinstance(_inner, dict) else True
                            _session_entries.append(f"  修改: {_diff_str}")
                            _session_entries.append(f"  执行: {'成功' if _ok else '失败'}")
                        elif _td.get("modify"):
                            _session_entries.append(f"  结果: 脚本修改成功")
                        elif _td.get("result") is not None:
                            _session_entries.append(f"  结果: 执行成功")
                except Exception:
                    pass
        _new_log = "\n".join(_session_entries[-20:])
        _prev_log = context.get("debug_session_log", "")
        context["debug_session_log"] = (_prev_log + f"\n[第{inspection_round+1}轮调试]\n" + _new_log)[-2000:]

    @staticmethod
    def _compress_tool_result(content: str) -> str:
        """智能压缩工具结果：失败保留错误全量，成功保留摘要+前3行数据。"""
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                return content[:3000]
            is_fail = not data.get("success") or data.get("error")
            # stdout: 失败保留首300+尾1000，成功保留首300+尾300
            stdout = str(data.get("stdout", ""))
            if is_fail and len(stdout) > 1300:
                data["stdout"] = stdout[:300] + "\n... [省略中间部分] ...\n" + stdout[-1000:]
            elif not is_fail and len(stdout) > 600:
                data["stdout"] = stdout[:300] + "\n... [省略中间部分] ...\n" + stdout[-300:]
            # result: 保留标量字段，截断大数组
            result = data.get("result")
            if isinstance(result, dict):
                for k, v in list(result.items()):
                    if isinstance(v, list) and len(v) > 3:
                        result[k] = v[:3] + [f"... (共 {len(v)} 项)"]
                    elif isinstance(v, str) and len(v) > 300:
                        result[k] = v[:300] + "..."
                    elif isinstance(v, dict) and len(str(v)) > 500:
                        result[k] = "（大型对象已省略）"
            # error: 始终完整保留
            # diff_summary: 始终完整保留（已很紧凑）
            return json.dumps(data, ensure_ascii=False, default=str)
        except (json.JSONDecodeError, TypeError):
            return content[:3000]

    async def _finalize_script_change(self, merged: str, current: str, script_name: str,
                                       arguments: dict, db: AsyncSession, context: Dict) -> str:
        """持久化合并后的脚本（operator/pipeline/skill）+ skill_md + AST 语法检查 + diff。
        modify_script 与 edit_script 共用此方法，返回 JSON 结果字符串。"""
        context["debug_script_content"] = merged

        # 写入对应存储
        if context.get("debug_type") == "operator":
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
            from app.models.pipeline import Pipeline
            from sqlalchemy import select as sa_select
            pipe_id = context.get("debug_pipeline_id")
            pipe_result = await db.execute(sa_select(Pipeline).where(Pipeline.id == pipe_id))
            pipe = pipe_result.scalar_one_or_none()
            if pipe:
                pipe.main_code = merged
                await db.flush()
        else:
            folder = context.get("debug_folder")
            if folder:
                from app.services.skill_parser import write_skill_script
                write_skill_script(folder, script_name, merged)

        # skill_md 同步
        _skill_md_updated = False
        _new_md = (arguments.get("skill_md") or "").strip()
        if _new_md and context.get("debug_type") in (None, "skill"):
            folder = context.get("debug_folder")
            if folder:
                from app.services.skill_parser import write_skill_md as _wsm
                _wsm(folder, _new_md)
                context["debug_skill_md_full"] = _new_md
                context["debug_skill_md"] = _new_md[:1200]
                _skill_md_updated = True
                logger.info(f"debug modify_script: SKILL.md 已更新 ({len(_new_md)} 字符)")

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

        diff_lines = _compute_diff_summary(current, merged)
        return json.dumps({
            "success": True,
            "script_name": script_name,
            "message": "技能已更新，语法检查通过" if _skill_md_updated else "脚本已更新，语法检查通过",
            "skill_md_updated": _skill_md_updated,
            "merged_preview": merged[:8000],
            "changed_lines": diff_lines,
        }, ensure_ascii=False)

    async def _execute_tool(self, name: str, arguments: dict, db: AsyncSession, user_id, context: Dict) -> str:
        logger.info(f"DataProcessor执行工具: {name}")

        if name == "handoff_to_inspector":
            # 优先从 context 取（可靠 UUID），不信任 LLM 传的 datasource_id（可能是中文名）
            ds_id = context.get("debug_output_datasource_id") or context.get("debug_datasource_id") or context.get("current_datasource_id") or arguments.get("datasource_id", "")
            tbl = context.get("debug_output_table") or context.get("debug_table_name") or context.get("current_table_name", "")
            return json.dumps({
                "_handoff": True,
                "to": "data_inspector",
                "reason": HandoffReason.INSPECT_RESULT.value,
                "payload": {
                    "datasource_id": ds_id,
                    "table_name": tbl,
                    "operation_description": arguments.get("operation_description", ""),
                    "result_summary": arguments.get("result_summary", ""),
                },
            }, ensure_ascii=False)

        # ---- 调试模式工具 ----
        if name == "modify_script":
            if not context.get("_script_has_been_read"):
                return json.dumps({"success": False, "error": "必须先调用 read_script 查看脚本内容，再修改。"}, ensure_ascii=False)
            code = arguments.get("code", "")
            if not code:
                return json.dumps({"success": False, "error": "缺少 code"})
            script_name = arguments.get("script_name") or context.get("debug_script_name", "main.py")
            try:
                from app.services.operator_parser import apply_partial_code
                current = context.get("debug_script_content", "")
                merged = apply_partial_code(current, code)
                return await self._finalize_script_change(merged, current, script_name, arguments, db, context)
            except Exception as e:
                logger.warning(f"modify_script 失败: {e}")
                return json.dumps({"success": False, "error": str(e)})

        if name == "edit_script":
            if not context.get("_script_has_been_read"):
                return json.dumps({"success": False, "error": "必须先调用 read_script 查看脚本内容，再修改。"}, ensure_ascii=False)
            # 行级补丁（对齐 OpenCode edit）：小修改只输出 old/new 片段，不重写整函数
            old_string = arguments.get("old_string", "")
            new_string = arguments.get("new_string", "")
            if not old_string:
                return json.dumps({"success": False, "error": "缺少 old_string"}, ensure_ascii=False)
            script_name = arguments.get("script_name") or context.get("debug_script_name", "main.py")
            try:
                from app.services.operator_parser import apply_patch
                current = context.get("debug_script_content", "")
                patch = apply_patch(current, old_string, new_string)
                if not patch.get("success"):
                    return json.dumps({"success": False, "error": patch.get("message", "补丁失败"), "patch_error": True}, ensure_ascii=False)
                return await self._finalize_script_change(patch["code"], current, script_name, arguments, db, context)
            except Exception as e:
                logger.warning(f"edit_script 失败: {e}")
                return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

        if name == "read_script":
            scope = arguments.get("scope", "script")
            if scope == "platform":
                file_path = arguments.get("file_path", "")
                if not file_path:
                    return json.dumps({"success": False, "error": "缺少 file_path"}, ensure_ascii=False)
                search_dir = Path(__file__).resolve().parent.parent
                candidates = [
                    search_dir / file_path,
                    search_dir / "services" / file_path,
                    search_dir / "api" / "v1" / "endpoints" / file_path,
                ]
                resolved = None
                for c in candidates:
                    try:
                        rp = c.resolve()
                        if str(rp).startswith(str(search_dir.resolve())) and rp.exists():
                            resolved = rp
                            break
                    except Exception:
                        continue
                if not resolved:
                    return json.dumps({"success": False, "error": f"文件未找到: {file_path}"}, ensure_ascii=False)
                offset = max(1, int(arguments.get("offset", 1)))
                limit = min(200, int(arguments.get("limit", 50)))
                try:
                    with open(resolved, encoding="utf-8") as f:
                        all_lines = f.readlines()
                    start = offset - 1
                    end = min(len(all_lines), start + limit)
                    seg_lines = [f"L{i+1}: {all_lines[i].rstrip()}" for i in range(start, end)]
                    return json.dumps({"success": True, "file": os.path.relpath(str(resolved), str(search_dir)),
                                       "offset": offset, "limit": limit, "total_lines": len(all_lines),
                                       "content": "\n".join(seg_lines)}, ensure_ascii=False)
                except Exception as e:
                    return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
            # scope='script' — 读当前脚本逐字内容（带行号，对齐 OpenCode Read）
            script_name = arguments.get("script_name") or context.get("debug_script_name", "main.py")
            # 每次从磁盘刷新（确保行号和文件一致，不受内存旧版本影响）
            _folder = context.get("debug_folder")
            if _folder:
                _file_path = Path(_folder) / "scripts" / script_name
                if _file_path.exists():
                    current = _file_path.read_text(encoding="utf-8")
                    context["debug_script_content"] = current
                else:
                    current = context.get("debug_script_content", "")
            else:
                current = context.get("debug_script_content", "")
            function_name = arguments.get("function_name")
            offset = int(arguments.get("offset", 0))
            limit = int(arguments.get("limit", 0))
            # 标记脚本已读（edit_script/modify_script 前必须先 read）
            context["_script_has_been_read"] = True

            if function_name:
                try:
                    import ast as _ast
                    tree = _ast.parse(current)
                    for node in _ast.iter_child_nodes(tree):
                        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == function_name:
                            seg = _ast.get_source_segment(current, node) or ""
                            seg_lines = seg.splitlines()
                            start_line = node.lineno
                            total = len(seg_lines)
                            # 支持 offset/limit（对齐 OpenCode Read），不传则返回整个函数
                            if offset > 0 or limit > 0:
                                s = max(0, (offset - 1) if offset > 0 else 0)
                                e = min(total, s + limit) if limit > 0 else total
                            else:
                                s = 0
                                e = total
                            numbered = "\n".join(f"L{start_line + i}: {seg_lines[i]}" for i in range(s, e))
                            return json.dumps({"success": True, "script_name": script_name, "function": function_name,
                                               "start_line": start_line, "content": numbered, "total_lines": total,
                                               "shown_lines": e - s}, ensure_ascii=False)
                    return json.dumps({"success": False, "error": f"未找到函数 {function_name}"}, ensure_ascii=False)
                except SyntaxError as _se:
                    return json.dumps({"success": False, "error": f"脚本语法错误，无法解析函数：{_se.msg}（第{_se.lineno}行）。可先用 modify_script 整函数替换修复语法。"}, ensure_ascii=False)
            # 默认返回前 2000 行（对齐 OpenCode Read），传 offset/limit 读指定范围
            _DEFAULT_READ_CAP = 2000
            all_lines = current.splitlines()
            _total = len(all_lines)
            if offset > 0 or limit > 0:
                start = max(0, (offset - 1) if offset > 0 else 0)
                end = min(_total, start + limit) if limit > 0 else min(_total, start + _DEFAULT_READ_CAP)
            else:
                start = 0
                end = min(_total, _DEFAULT_READ_CAP)
            numbered = "\n".join(f"L{i+1}: {all_lines[i]}" for i in range(start, end))
            result = {"success": True, "script_name": script_name, "offset": start + 1,
                      "limit": end - start, "total_lines": _total, "content": numbered}
            if end < _total:
                result["has_more"] = True
                result["hint"] = f"还有 {_total - end} 行未显示，用 grep_script 搜关键词定位行号后传 offset 读取"
            return json.dumps(result, ensure_ascii=False)

        if name == "grep_script":
            scope = arguments.get("scope", "script")
            pattern = arguments.get("pattern", "")
            if not pattern:
                return json.dumps({"success": False, "error": "缺少 pattern"}, ensure_ascii=False)
            context_lines = int(arguments.get("context_lines", 3))
            import re as _grep_re

            if scope == "platform":
                file_filter = arguments.get("file_filter", "*.py")
                import glob as _glob
                search_dir = Path(__file__).resolve().parent.parent
                files = _glob.glob(str(search_dir / "**" / file_filter), recursive=True)
                flags = 0 if arguments.get("case_sensitive") else _grep_re.IGNORECASE
                try:
                    regex = _grep_re.compile(pattern, flags)
                except _grep_re.error as e:
                    return json.dumps({"success": False, "error": f"正则表达式错误: {e}"}, ensure_ascii=False)
                all_matches = []
                for fpath in sorted(files):
                    try:
                        with open(fpath, encoding="utf-8") as f:
                            lines = f.readlines()
                    except Exception:
                        continue
                    for i, line in enumerate(lines):
                        if regex.search(line):
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            snippet_lines = []
                            for j in range(start, end):
                                prefix = ">>" if j == i else "  "
                                snippet_lines.append(f"{prefix} L{j+1}: {lines[j].rstrip()}")
                            all_matches.append({"file": str(Path(fpath).relative_to(search_dir)), "line": i + 1,
                                                "snippet": "\n".join(snippet_lines)})
                if not all_matches:
                    return json.dumps({"success": True, "pattern": pattern, "scope": "platform",
                                       "matches": [], "total_matches": 0, "message": "未找到匹配"}, ensure_ascii=False)
                _MAX = 50
                truncated = len(all_matches) > _MAX
                result = {"success": True, "pattern": pattern, "scope": "platform",
                          "matches": all_matches[:_MAX], "total_matches": len(all_matches)}
                if truncated:
                    result["truncated"] = True
                    result["message"] = f"匹配数超过 {_MAX}，仅显示前 {_MAX} 个。请用 file_filter 限定文件或用更精确的 pattern。"
                return json.dumps(result, ensure_ascii=False)

            # scope='script' — 搜当前脚本
            script_name = arguments.get("script_name") or context.get("debug_script_name", "main.py")
            current = context.get("debug_script_content", "")
            case_sensitive = arguments.get("case_sensitive", False)
            function_name = arguments.get("function_name")
            all_lines = current.splitlines()
            if function_name:
                try:
                    import ast as _ast
                    tree = _ast.parse(current)
                    func_start = None
                    func_end = None
                    for node in _ast.iter_child_nodes(tree):
                        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == function_name:
                            func_start = node.lineno
                            func_end = getattr(node, "end_lineno", func_start)
                            break
                    if func_start is None:
                        return json.dumps({"success": False, "error": f"未找到函数 {function_name}"}, ensure_ascii=False)
                    search_lines = all_lines[func_start - 1: func_end]
                    line_offset = func_start
                except SyntaxError as _se:
                    return json.dumps({"success": False, "error": f"脚本语法错误，无法解析函数：{_se.msg}（第{_se.lineno}行）。可先用 modify_script 整函数替换修复语法。"}, ensure_ascii=False)
            else:
                search_lines = all_lines
                line_offset = 1
            flags = 0 if case_sensitive else _grep_re.IGNORECASE
            try:
                regex = _grep_re.compile(pattern, flags)
            except _grep_re.error as e:
                return json.dumps({"success": False, "error": f"正则表达式错误: {e}"}, ensure_ascii=False)
            match_indices = [i for i, line in enumerate(search_lines) if regex.search(line)]
            if not match_indices:
                return json.dumps({"success": True, "pattern": pattern, "script_name": script_name,
                                   "function": function_name, "matches": [], "total_matches": 0,
                                   "message": "未找到匹配"}, ensure_ascii=False)
            _MAX_MATCHES = 50
            truncated = len(match_indices) > _MAX_MATCHES
            match_blocks = []
            for idx in match_indices[:_MAX_MATCHES]:
                start = max(0, idx - context_lines)
                end = min(len(search_lines), idx + context_lines + 1)
                snippet_lines = []
                for j in range(start, end):
                    prefix = ">>" if j == idx else "  "
                    snippet_lines.append(f"{prefix} L{line_offset + j}: {search_lines[j]}")
                match_blocks.append({"line": line_offset + idx, "snippet": "\n".join(snippet_lines)})
            result = {"success": True, "pattern": pattern, "script_name": script_name,
                      "function": function_name, "matches": match_blocks, "total_matches": len(match_indices)}
            if truncated:
                result["truncated"] = True
                result["message"] = f"匹配数超过 {_MAX_MATCHES}，仅显示前 {_MAX_MATCHES} 个。请用更精确的 pattern 或指定 function_name 缩小范围。"
            return json.dumps(result, ensure_ascii=False)

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
                    # 流程：复用 skill_runner 子进程沙箱（与技能执行同一框架）
                    from app.services.skill_runner import run_skill_script_by_content_async
                    result = await run_skill_script_by_content_async(
                        script_content=context.get("debug_script_content", ""),
                        parameters=parameters,
                        user_id=str(user_id) if user_id else None,
                        entry_function=context.get("debug_function_name"),
                        timeout=600,
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
                    logger.info(f"debug run_script (pipeline): success={not _failed}")
                    return json.dumps(result, ensure_ascii=False, default=str)
                else:
                    # 技能：subprocess 沙箱
                    folder = context.get("debug_folder")
                    if not folder:
                        return json.dumps({"success": False, "error": "缺少 folder"})
                    from app.services.skill_runner import run_skill_script_async
                    ds_id = context.get("debug_datasource_id")
                    ds_name = context.get("debug_datasource_name")
                    tbl = context.get("debug_table_name")
                    # 技能级运行：按 SKILL.md 参数规范校验必选参数（非阻断，仅告警）
                    _param_warning = self._check_required_params(context, parameters)
                    result = await run_skill_script_async(
                        skill_path=folder, script_name=script_name, parameters=parameters,
                        input_data=None, datasource_id=ds_id, datasource_name=ds_name, table_name=tbl,
                        user_id=str(user_id) if user_id else None,
                        timeout=600,
                    )
                    if _param_warning:
                        result["param_warning"] = _param_warning
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
                "skill_md": arguments.get("skill_md", ""),
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

        if name == "edit_and_run":
            # 合并工具：edit_script + run_script 一步到位（行级补丁版，小修改首选）
            _edit_result = await self._execute_tool("edit_script", {
                "old_string": arguments.get("old_string", ""),
                "new_string": arguments.get("new_string", ""),
                "script_name": arguments.get("script_name") or context.get("debug_script_name", "main.py"),
                "skill_md": arguments.get("skill_md", ""),
            }, db, user_id, context)
            try:
                _mdata = json.loads(_edit_result)
            except json.JSONDecodeError:
                _mdata = {"success": False, "error": "edit 结果解析失败"}
            if not _mdata.get("success"):
                # 补丁失败（未找到/不唯一/语法错误）→ 直接返回，不执行
                return _edit_result
            # 补丁成功 → 执行
            _run_result = await self._execute_tool("run_script", {
                "script_name": arguments.get("script_name") or context.get("debug_script_name", "main.py"),
                "parameters": arguments.get("parameters", {}),
            }, db, user_id, context)
            try:
                _rdata = json.loads(_run_result)
            except json.JSONDecodeError:
                _rdata = {"success": False, "error": "run 结果解析失败"}
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
                "default_model": info.get("default_model", ""),
            })

        # 可用模型列表（带能力描述，供 LLM 了解当前可选项）
        available_models = [
            {"model": val, "description": desc}
            for val, desc in llm_manager._available_models_with_desc()
        ]

        return _json.dumps({
            "current_provider": llm_manager.provider,
            "current_model": llm_manager.model,
            "current_api_base": llm_manager.api_base or get_provider_api_base(llm_manager.provider) or "",
            "available_models": available_models,
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

    def build_debug_system_prompt(self, context: Dict[str, Any], round_num: int = 1) -> str:
        """构建调试模式 system prompt（精简版，对齐 OpenCode）。"""
        max_rounds = context.get("debug_max_rounds", 7)
        max_exec_failures = context.get("debug_max_exec_failures", 3)
        prompt = DEBUG_INSTRUCTIONS.replace("{max_rounds}", str(max_rounds)).replace("{max_exec_failures}", str(max_exec_failures))

        # 沙箱函数签名契约（对齐 OpenCode：工具 schema 永远在 prompt 里，LLM 不必猜 API）
        # 放静态区保证字节稳定 → 命中 prefix cache；含 llm_vision(image_path,...) 等关键签名
        prompt += "\n\n" + SANDBOX_TOOLS_DOC
        prompt += "\n\n" + PLATFORM_CONVENTIONS_DOC

        # 目标连接器能力（1-2 行，不放完整能力清单）
        target_ds_type = context.get("debug_output_datasource_type", "")
        if target_ds_type:
            from app.services.tool_guidance import PLATFORM_CAPABILITIES
            _caps = PLATFORM_CAPABILITIES.get("connector", {}).get(target_ds_type, {})
            _wtd = _caps.get("write_table_data", {})
            _can_create = _wtd.get("create_new_file", _wtd.get("create_new_table", False))
            prompt += f"\n目标连接器({target_ds_type}): 创建新文件/表={'✅' if _can_create else '❌'}, execute_sql={'✅' if _caps.get('execute_sql') else '❌'}"
            if not _can_create:
                prompt += "。标❌的能力修改脚本无法绕过，直接报告"

        # 动态信息（精简：不放脚本摘要，LLM 需要时用 read_script 读）
        parts = []
        if context.get("debug_function_name") == "_pipeline_entry":
            parts.append("入口函数 _pipeline_entry 参数已固化，直接调 run_script 执行即可，不需要先读脚本")
        last_params = context.get("debug_last_success_params")
        if last_params:
            parts.append(f"最近成功参数: {json.dumps(last_params, ensure_ascii=False, default=str)[:300]}")

        ctx = context.get("debug_user_context", {})
        if ctx:
            _ds = ctx.get("datasource_name") or ""
            _tbl = ctx.get("table_name") or ""
            if _ds or _tbl:
                parts.append(f"数据源: {_ds}, 表: {_tbl}")

        _tool_calls = context.get("debug_tool_calls")
        if _tool_calls:
            _tc_lines = [f"- {_tc.get('tool')}: {'✅' if _tc.get('success') else '❌'} {str(_tc.get('message',''))[:150]}" for _tc in _tool_calls]
            parts.append("上次工具调用:\n" + "\n".join(_tc_lines))

        _exec_stdout = context.get("debug_exec_stdout")
        if _exec_stdout:
            parts.append(f"上次输出:\n```\n{_exec_stdout[:1000]}\n```")

        if parts:
            prompt += "\n\n" + "\n\n".join(parts)
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

        # 注入跨 handoff 调试历史（避免 DataProcessor 忘记之前尝试过什么）
        if context.get("debug_session_log"):
            local_messages.append({
                "role": "user",
                "content": f"## 之前调试历史（避免重复已失败的修复方向）\n{context['debug_session_log']}"
            })

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

        # 调试模式工具（对齐 OpenCode：5 个工具，职责清晰）
        # read_script=Read, grep_script=Grep, edit_script=Edit, run_script=Bash
        # handoff 不在工具里——执行成功后 runtime 自动交接 DataInspector
        # edit_and_run/modify_and_run 已删除：先 edit_script 改，再 run_script 跑
        debug_tools = [EDIT_SCRIPT_TOOL, RUN_SCRIPT_TOOL, READ_SCRIPT_TOOL, GREP_SCRIPT_TOOL]

        max_fix_attempts = context.get("debug_max_rounds", 7)
        _fix_attempts = context.get("debug_total_rounds", 0)  # 跨 handoff 持久化，只数 fix 工具
        _total_llm_calls = 0  # 仅用于日志
        _MAX_EXEC_FAILURES = context.get("debug_max_exec_failures", 3)  # 首次执行成功前连续执行失败上限（可配置）
        _exec_failures_before_success = context.get("debug_exec_failures", 0)
        _execution_succeeded = context.get("debug_execution_succeeded", False)
        _should_handoff = False
        _handoff_output_table = None
        script_name = context.get("debug_script_name", "main.py")

        logger.info("[run_debug] 开始，max_fix_attempts=" + str(max_fix_attempts) + " tools=" + str([t.get("function",{}).get("name","?") for t in debug_tools]))

        yield {"type": "model", "content": await llm_manager.pick_model_async(user_msg, history)}

        while _fix_attempts < max_fix_attempts:
            _total_llm_calls += 1

            # 上下文压缩（对齐 OpenCode compaction）
            if should_compact(local_messages):
                yield {"type": "content", "content": "\n📦 正在压缩上下文...\n"}
                local_messages = await compact_messages(local_messages, llm_manager)

            local_messages[0] = {"role": "system", "content": self.build_debug_system_prompt(context, _fix_attempts + 1)}

            content = ""
            tool_calls = []

            logger.info("[run_debug] LLM调用#" + str(_total_llm_calls) + "（修改尝试" + str(_fix_attempts + 1) + "/" + str(max_fix_attempts) + "）")
            async for event in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=debug_tools, temperature=0.1,
                model=None, tool_choice="auto",
            ):
                t = event["type"]
                if t == "thinking":
                    yield event
                elif t == "content":
                    content += event["content"]
                    yield event
                elif t == "tool_calls":
                    tool_calls = event["tool_calls"]

            logger.info("[run_debug] LLM调用#" + str(_total_llm_calls) + "返回 content_len=" + str(len(content)) + " tool_calls=" + str(len(tool_calls)))

            # 检测是否为修改尝试（edit_script/run_script）
            _has_fix = tool_calls and any(tc["function"]["name"] in ("edit_script", "run_script") for tc in tool_calls)
            _has_edit = tool_calls and any(tc["function"]["name"] == "edit_script" for tc in tool_calls)
            if _has_fix:
                _fix_attempts += 1
                context["debug_total_rounds"] = _fix_attempts
                _action = "modify" if _has_edit else "execute"
                _label = "修改尝试" if _has_edit else "执行"
                yield {"type": "round", "round": _fix_attempts, "action": _action}
                yield {"type": "content", "content": f"\n第{_fix_attempts}次{_label}："}
                if _fix_attempts == max_fix_attempts:
                    yield {"type": "content", "content": f"⚠️ 这是最后一次机会（第 {max_fix_attempts}/{max_fix_attempts} 次）。如果错误来自平台限制，请直接报告。\n"}

            # 工具调用显示（对齐 OpenCode：工具名 + 关键参数 + diff）
            _script_name = context.get("debug_script_name", "main.py")
            if tool_calls:
                _actions = []
                for tc in tool_calls:
                    _name = tc["function"]["name"]
                    _label = {"read_script": f"📖 {_script_name}", "grep_script": f"🔍 {_script_name}", "edit_script": f"✏️ {_script_name}", "run_script": f"▶️ {_script_name}"}.get(_name, _name)
                    try:
                        _args = json.loads(tc["function"]["arguments"])
                        if _name == "read_script":
                            _offset = _args.get("offset", 0)
                            _limit = _args.get("limit", 0)
                            if _offset and _limit:
                                _label += f" L{_offset}-L{_offset + _limit - 1}"
                        elif _name == "grep_script":
                            _pattern = _args.get("pattern", "")
                            if _pattern:
                                _label += f" \"{_pattern[:40]}\""
                        elif _name == "edit_script":
                            _old = _args.get("old_string", "")
                            _new = _args.get("new_string", "")
                            if _old or _new:
                                _diff_lines = [f"- {l}" for l in _old.splitlines()[:20]]
                                _diff_lines += [f"+ {l}" for l in _new.splitlines()[:20]]
                                _label += "\n```diff\n" + "\n".join(_diff_lines) + "\n```"
                    except Exception:
                        pass
                    _actions.append(_label)
                yield {"type": "content", "content": '\n'.join(_actions) + '\n'}

            if not tool_calls:
                # LLM 不调工具 = 在下结论。判定为平台问题 → 退出
                if _is_platform_issue_report(content):
                    yield {"type": "platform_issue", "message": content}
                    yield {"type": "done", "result": {"agent": self.name, "content": content, "platform_issue": True}}
                    return
                if context.get("debug_analyze_only"):
                    yield {"type": "done", "result": {"agent": self.name, "content": content}}
                    return
                local_messages.append({"role": "assistant", "content": content})
                local_messages.append({"role": "user", "content": "请调用工具修改并执行脚本。"})
                continue

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

            results = await self._execute_tool_calls_parallel(tool_calls, db, user_id, context)
            # 工具结果摘要（像 OpenCode 显示 grep/read 结果）
            _result_lines = []
            _pending_handoff = None
            for r in results:
                tool_name = ""
                for tc in tool_calls:
                    if tc["id"] == r["tool_call_id"]:
                        tool_name = tc["function"]["name"]
                        break

                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]})

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
                        _content = _rd.get("content", "")
                        _func = _rd.get("function", "")
                        _total = _rd.get("total_lines", 0)
                        _truncated = _rd.get("truncated", False)
                        _header = f"  📖 {_script_name}"
                        if _func:
                            _header += f":{_func}"
                        # 从 content 提取实际行号范围（确保和内容一致）
                        _cl = _content.split("\n")
                        _first_line = ""
                        _last_line = ""
                        for _cl_line in _cl:
                            if _cl_line.strip().startswith("L"):
                                _first_line = _cl_line.strip().split(":")[0]
                                break
                        for _cl_line in reversed(_cl):
                            if _cl_line.strip().startswith("L"):
                                _last_line = _cl_line.strip().split(":")[0]
                                break
                        if _first_line and _last_line:
                            _header += f" {_first_line}-{_last_line}"
                            # 计算实际读取行数
                            try:
                                _n1 = int(_first_line.lstrip("L"))
                                _n2 = int(_last_line.lstrip("L"))
                                _header += f" (读了{_n2 - _n1 + 1}行"
                                if _total:
                                    _header += f"/共{_total}行"
                                _header += ")"
                            except ValueError:
                                if _total:
                                    _header += f" (共{_total}行)"
                        elif _total:
                            _header += f" (共{_total}行)"
                        if len(_cl) > 20:
                            _cl = _cl[:20] + ["..."]
                        _result_lines.append(_header + "\n```\n" + "\n".join(_cl) + "\n```")
                    elif tool_name == "get_table_schema" and _rd.get("success"):
                        _cols = len(_rd.get("columns", []))
                        _result_lines.append(f"  表结构: {_cols} 列")
                    elif tool_name == "query_table_data" and _rd.get("success"):
                        _rows = _rd.get("row_count", 0)
                        _result_lines.append(f"  查询: {_rows} 行")
                    elif tool_name == "list_user_datasources" and _rd.get("success"):
                        _cnt = len(_rd.get("datasources", _rd.get("data", [])))
                        _result_lines.append(f"  数据源: {_cnt} 个")
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
                    _inner_r = rdata.get("result") if isinstance(rdata.get("result"), dict) else {}
                    _is_fail = (not rdata.get("success")
                                or ("success" in _inner_r and not _inner_r["success"])
                                or (rdata.get("error") and str(rdata.get("error")).strip())
                                or (_inner_r.get("error") and str(_inner_r.get("error")).strip()))
                    if not _is_fail:
                        yield {"type": "content", "content": "\n✅ 执行成功\n"}
                        _should_handoff = True
                        _execution_succeeded = True
                        context["debug_execution_succeeded"] = True
                        _exec_failures_before_success = 0
                        context["debug_exec_failures"] = 0
                        _wt = rdata.get("written_tables")
                        if _wt:
                            _handoff_output_table = _wt[-1].get("table_name")
                            context["debug_output_datasource_id"] = _wt[-1].get("datasource_id")
                        else:
                            _handoff_output_table = _inner_r.get("output_table") if _inner_r else None
                        context["debug_output_table"] = _handoff_output_table
                        folder = context.get("debug_folder")
                        if folder:
                            try:
                                from app.services import experience as _exp
                                if _exp.read_negative(folder):
                                    _exp.append_positive(folder, source="debug-chat", parameters={}, result_summary=str(_inner_r)[:200], script_name=script_name)
                            except Exception as e:
                                logger.warning(f"记录正例失败(非致命): {e}")
                    else:
                        _err_msg = str(rdata.get("error") or _inner_r.get("error") or "")
                        _err_type = rdata.get("error_type") or _inner_r.get("error_type") or ""
                        yield {"type": "content", "content": f"\n❌ 执行失败：{_err_msg[:300]}\n"}
                        if _err_type and any(kw in _err_type for kw in ("环境问题", "平台限制", "数据问题")):
                            yield {"type": "give_up", "reason": _err_type}
                            yield {"type": "done", "result": {"agent": self.name, "content": _err_type}}
                            return
                        if not _execution_succeeded:
                            _exec_failures_before_success += 1
                            context["debug_exec_failures"] = _exec_failures_before_success
                            if _exec_failures_before_success >= _MAX_EXEC_FAILURES:
                                yield {"type": "give_up", "reason": f"连续 {_exec_failures_before_success} 次执行失败，无法自动修复"}
                                yield {"type": "done", "result": {"agent": self.name, "content": content or "执行失败"}}
                                return
                        folder = context.get("debug_folder")
                        if folder and _err_msg:
                            try:
                                from app.services import experience as _exp
                                _exp.append_negative(folder, source="debug-chat", error_type="execution_error", error_message=_err_msg, stdout=rdata.get("stdout", ""), script_name=script_name, context_summary=f"工具: {tool_name}\nAI输出: {content[:200]}")
                            except Exception as e:
                                logger.warning(f"记录反例失败(非致命): {e}")

                try:
                    result_data = json.loads(r["content"])
                    if isinstance(result_data, dict) and result_data.get("_handoff"):
                        _pending_handoff = {
                            "to": result_data["to"], "reason": result_data["reason"],
                            "payload": result_data.get("payload", {}),
                        }
                except (json.JSONDecodeError, AttributeError):
                    pass

            # yield 调查工具结果摘要
            if _result_lines:
                yield {"type": "content", "content": "\n".join(_result_lines) + "\n"}

            # 先处理执行成功触发的自动 handoff（含写入表信息）
            if _should_handoff:
                ds_id = context.get("debug_output_datasource_id") or context.get("debug_datasource_id") or context.get("current_datasource_id", "")
                tbl = _handoff_output_table or context.get("debug_table_name") or context.get("current_table_name", "")
                logger.info(f"[handoff检查] _should_handoff=True, ds_id={ds_id}, tbl={tbl}, written_tables={rdata.get('written_tables') if 'rdata' in dir() else 'N/A'}, output_table={_handoff_output_table}")
                if context.get("debug_max_inspections", 7) <= 0:
                    yield {"type": "done", "result": {"agent": self.name, "content": "修复成功", "success": True}}
                    return
                ds_id = context.get("debug_output_datasource_id") or context.get("debug_datasource_id") or context.get("current_datasource_id", "")
                tbl = _handoff_output_table or context.get("debug_table_name") or context.get("current_table_name", "")
                # 目标表信息不能为空——空了 Inspector 不知道检查什么
                if not ds_id or not tbl:
                    yield {"type": "content", "content": f"\n⚠ 执行成功但无法确定检查目标（数据源ID={ds_id or '空'}, 表名={tbl or '空'}），跳过质量检查\n"}
                    yield {"type": "done", "result": {"agent": self.name, "content": "执行成功，但无法启动质量检查：目标表信息缺失"}}
                    return
                _is_recheck = _inspection_round > 0
                yield {
                    "type": "handoff", "to": "data_inspector",
                    "reason": HandoffReason.FIX_COMPLETED.value if _is_recheck else HandoffReason.INSPECT_RESULT.value,
                    "payload": {
                        "datasource_id": ds_id, "table_name": tbl,
                        "operation_description": f"第 {_inspection_round} 轮修复后复查" if _is_recheck else "技能调试执行成功，自动交接质量检查",
                        "result_summary": "执行成功",
                    },
                    "from": self.name,
                }
                return

            # 再处理 LLM 显式调用的 handoff_to_inspector（所有工具结果已处理完毕）
            if _pending_handoff:
                yield {
                    "type": "handoff", "to": _pending_handoff["to"], "reason": _pending_handoff["reason"],
                    "payload": _pending_handoff["payload"], "from": self.name,
                }
                return

        # 修改次数用完 → 让 LLM 判断是代码问题还是平台问题
        _classify_msg = (
            f"经过 {_fix_attempts} 次修改尝试（上限 {max_fix_attempts} 次），脚本仍然无法通过检查。\n"
            f"最后的错误信息：{content[:500] if content else '无'}\n\n"
            "请判断这个错误属于以下哪类，一句话说明原因：\n"
            "1. 代码问题（可以通过修改脚本修复）\n"
            "2. 平台限制（如连接器不支持某功能、数据源类型限制等，修改脚本无法解决）\n"
            "3. 环境问题（如数据源不可达、权限不足、文件不存在等）\n"
            "只回答分类和原因，不要输出代码。"
        )
        local_messages.append({"role": "user", "content": _classify_msg})
        _classification = ""
        try:
            async for _evt in llm_manager.chat_stream_with_tools_and_thinking(
                messages=local_messages, tools=debug_tools, temperature=0.1,
                model=None, tool_choice="auto",
            ):
                if _evt.get("type") == "content":
                    _classification += _evt.get("content", "")
                    yield _evt
        except Exception:
            pass

        yield {"type": "give_up", "reason": _classification[:1000] if _classification else f"已达到最大修改次数（{_fix_attempts}次）"}
        yield {"type": "done", "result": {"agent": self.name, "content": _classification or content or "调试失败"}}
