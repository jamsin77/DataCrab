"""Agent 工程工具函数

借鉴 DeepAnalyze 的工程设计：
- CJK 感知的 token 估算
- 工具结果截断保护
- 卡死检测器（StuckDetector）
- 标识符机械抽取（压缩保护）
- 反幻觉检查工具
- 动态轮次预算（进度感知替代硬上限）
- 上下文压缩（Compaction，对齐 OpenCode）
- 上下文压力主动告警
- 三级反幻觉注入（basic/standard/strict）
- 搜索饱和检测（SearchSaturationDetector）
"""
import re
import json
import hashlib
import logging
from typing import Dict, Any, List, Set, Optional, Tuple

logger = logging.getLogger(__name__)


# ==================== Token 估算（CJK 感知）====================

def estimate_tokens(text: str) -> int:
    """CJK 感知的 token 估算。

    借鉴 DeepAnalyze 的 CJK 字符级估算：
    - CJK 字符（中日韩）≈ 1.5 token/字
    - 非 ASCII 字符 ≈ 0.5 token/字
    - ASCII 字符 ≈ 0.25 token/字
    """
    if not text:
        return 0
    cjk = 0
    non_ascii = 0
    ascii_chars = 0
    for ch in text:
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF or 0x3040 <= cp <= 0x30FF or 0xAC00 <= cp <= 0xD7AF:
            cjk += 1
        elif cp > 127:
            non_ascii += 1
        else:
            ascii_chars += 1
    return int(cjk * 1.5 + non_ascii * 0.5 + ascii_chars * 0.25)


# ==================== 工具结果截断 ====================

MAX_TOOL_RESULT_CHARS = 8000


def truncate_tool_result(result_str: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """截断过大的工具返回结果，防止撑爆上下文。

    如果 JSON 结果超过 max_chars，保留结构信息 + 前 5 行数据 + 截断提示。
    """
    if not result_str or len(result_str) <= max_chars:
        return result_str

    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        # 非 JSON 直接截断
        return result_str[:max_chars] + "\n\n... [结果过大已截断]"

    if isinstance(data, dict):
        truncated = dict(data)
        rows = truncated.get("rows")
        if isinstance(rows, list) and len(rows) > 5:
            truncated["rows_preview"] = rows[:5]
            truncated["rows"] = f"[已截断：共 {len(rows)} 行，仅显示前 5 行。如需更多数据请缩小查询范围或使用分页]"
            truncated["truncated"] = True
        result = json.dumps(truncated, ensure_ascii=False, default=str)
        if len(result) > max_chars:
            # 还是太大，激进截断
            if isinstance(data.get("rows"), list):
                data["rows"] = f"[已截断：共 {len(data['rows'])} 行]"
                data["columns"] = data.get("columns", [])
                data["truncated"] = True
                result = json.dumps(data, ensure_ascii=False, default=str)
            if len(result) > max_chars:
                result = result[:max_chars] + "\n\n... [结果过大已截断]"
        return result

    return result_str[:max_chars] + "\n\n... [结果过大已截断]"


# ==================== 卡死检测器 ====================

class StuckDetector:
    """检测 Agent 原地打转。

    识别两种模式：
    - 重复调用：连续 N 轮调用相同工具 + 相同参数
    - 空转：连续 N 轮有输出但没有工具调用
    另有总轮次上限兜底，防止无限循环。
    """

    def __init__(self, repeat_threshold: int = 2, idle_threshold: int = 3, max_total_rounds: int = 15):
        self.repeat_threshold = repeat_threshold
        self.idle_threshold = idle_threshold
        self.max_total_rounds = max_total_rounds
        self._call_history: List[str] = []
        self._idle_count: int = 0
        self._total_rounds: int = 0

    def record_tool_call(self, tool_name: str, arguments: dict) -> Optional[str]:
        """记录一次工具调用，返回干预提示（如果检测到卡死）或 None。"""
        args_str = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        signature = hashlib.md5(f"{tool_name}:{args_str}".encode()).hexdigest()
        self._call_history.append(signature)
        self._idle_count = 0
        self._total_rounds += 1

        # 检测总轮次上限
        if self._total_rounds >= self.max_total_rounds:
            return (
                f"已达到总轮次上限（{self.max_total_rounds} 轮），无法继续修复。"
                "如果这是可修复的问题，请总结已调查的信息，给出修复建议后结束。"
            )

        # 检测重复调用
        if len(self._call_history) >= self.repeat_threshold:
            recent = self._call_history[-self.repeat_threshold:]
            if len(set(recent)) == 1:
                self._call_history.clear()
                return (
                    "你刚才已连续重复调用相同的工具和参数，但没有取得进展。"
                    "请尝试不同策略：换一个工具、调整参数、或重新分析问题。"
                )

        return None

    def record_idle(self) -> Optional[str]:
        """记录一轮无工具调用的输出，返回干预提示或 None。"""
        self._idle_count += 1
        if self._idle_count >= self.idle_threshold:
            self._idle_count = 0
            return (
                "已连续多轮没有执行工具操作。如果任务尚未完成，"
                "请使用可用工具执行实际操作（查询数据、检查质量等）。"
            )
        return None

    def reset(self):
        self._call_history.clear()
        self._idle_count = 0
        self._total_rounds = 0



# ==================== 标识符机械抽取（压缩保护）====================

_IDENTIFIER_PATTERNS = [
    (re.compile(r'[\da-fA-F]{8}-[\da-fA-F]{4}-[\da-fA-F]{4}-[\da-fA-F]{4}-[\da-fA-F]{12}'), "UUID"),
    (re.compile(r'数据源\s*(?:ID|id|Id)?[:：]\s*(\S+)'), "数据源"),
    (re.compile(r'表\s*名?[:：]\s*(\S+)'), "表名"),
    (re.compile(r'datasource_id["\']?\s*[:：]\s*["\']?([\w-]+)'), "datasource_id"),
    (re.compile(r'table_name["\']?\s*[:：]\s*["\']?(\w+)'), "table_name"),
]


def extract_identifiers(text: str) -> Set[str]:
    """从文本中机械抽取标识符（UUID、表名、数据源 ID 等）。

    借鉴 DeepAnalyze 的标识符保护原则：压缩时机械抽取并保留标识符，
    防止压缩后 Agent 忘了之前查过什么表又重复搜索。
    """
    identifiers: Set[str] = set()
    if not text:
        return identifiers
    for pattern, label in _IDENTIFIER_PATTERNS:
        for match in pattern.finditer(text):
            # 取整个匹配或第一个分组
            value = match.group(1) if match.groups() else match.group(0)
            value = value.strip().strip('"\'`,，。')
            if value and len(value) < 100:
                identifiers.add(value)
    return identifiers


def build_identifier_hint(messages_text: str) -> str:
    """从历史消息文本中提取标识符，生成压缩保护提示。"""
    identifiers = extract_identifiers(messages_text)
    if not identifiers:
        return ""
    id_list = sorted(identifiers)[:20]
    return f"\n\n请在摘要中保留以下关键标识符：{', '.join(id_list)}"


# ==================== 反幻觉检查 ====================

# 数据声明模式：数字 + 统计关键词
_DATA_CLAIM_PATTERNS = [
    re.compile(r'\d+\.?\d*\s*(?:行|条|个|列|万|亿|%|％)', re.IGNORECASE),
    re.compile(r'(?:总计|平均|最大|最小|总和|均值|标准差|方差|平均值为?)\s*[:：值]*\s*\d', re.IGNORECASE),
    re.compile(r'(?:共有|总共有|包含|存在)\s*\d', re.IGNORECASE),
]


def has_data_claims(text: str) -> bool:
    """检查文本中是否包含数据声明（数字、统计结论等）。"""
    if not text:
        return False
    for pattern in _DATA_CLAIM_PATTERNS:
        if pattern.search(text):
            return True
    return False


def should_warn_ungrounded_claim(output_text: str, had_tool_calls_this_turn: bool) -> Optional[str]:
    """检查 agent 输出中是否有无工具支撑的数据声明。

    借鉴 DeepAnalyze 的反幻觉检查：如果输出包含数据声明但本轮没有工具调用，
    返回警告提示。
    """
    if not output_text:
        return None
    if has_data_claims(output_text) and not had_tool_calls_this_turn:
        return (
            "你的输出包含数据结论，但本轮未调用任何检查工具。"
            "请直接调用检查工具（profile_data/check_data_standards/check_data_quality/check_data_security）"
            "获取实际数据，不要解释或承认错误，直接调用工具。"
        )
    return None


# ==================== 动态轮次预算（进度感知）====================

def estimate_complexity(user_message: str) -> str:
    """任务复杂度估算（对齐 OpenCode：不靠关键词，固定中等预算）。"""
    return "medium"


def get_turn_budget(complexity: str) -> int:
    """根据复杂度返回轮次预算。"""
    return {"simple": 15, "medium": 25, "complex": 40}.get(complexity, 15)


# ==================== 上下文压力主动告警 ====================

# 默认上下文窗口（token），GLM 等主流模型约 128K
DEFAULT_CONTEXT_WINDOW = 128000
PRESSURE_WARN_THRESHOLD = 0.50   # 50% 注入 Level-1 提示
PRESSURE_URGENT_THRESHOLD = 0.60  # 60% 注入 Level-2 紧急提示


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += estimate_tokens(str(part.get("text", "")))
        # tool_calls 也占 token
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                total += estimate_tokens(json.dumps(fn, ensure_ascii=False))
    return total


def get_context_pressure_level(
    messages: List[Dict[str, Any]],
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> Tuple[int, float]:
    """返回上下文压力等级和占比。

    返回 (level, ratio)：
    - level 0：正常
    - level 1：警告（≥50%）
    - level 2：紧急（≥60%）
    """
    total = estimate_messages_tokens(messages)
    ratio = total / context_window if context_window > 0 else 0.0
    if ratio >= PRESSURE_URGENT_THRESHOLD:
        return 2, ratio
    if ratio >= PRESSURE_WARN_THRESHOLD:
        return 1, ratio
    return 0, ratio


def build_pressure_warning(level: int, ratio: float) -> str:
    """构建上下文压力告警提示。"""
    pct = int(ratio * 100)
    if level == 1:
        return (
            f"当前上下文已使用约 {pct}%。如果你已收集了大量信息但尚未保存，"
            "建议现在用 save_file_to_link 将重要发现保存到文件，避免后续上下文压缩时丢失细节。"
        )
    if level == 2:
        return (
            f"当前上下文已使用约 {pct}%，接近上限。请立即精简输出，"
            "优先保存关键结论到文件，避免冗长的中间过程描述。"
        )
    return ""


# ==================== 上下文压缩（Compaction，对齐 OpenCode） ====================

COMPACTION_THRESHOLD = 0.75  # 上下文使用 75% 时触发压缩
COMPACTION_TAIL_TURNS = 2    # 保留最近 2 轮对话原文


def should_compact(messages: List[Dict[str, Any]], context_window: int = DEFAULT_CONTEXT_WINDOW) -> bool:
    """检查是否需要压缩上下文。"""
    total = estimate_messages_tokens(messages)
    ratio = total / context_window if context_window > 0 else 0.0
    return ratio >= COMPACTION_THRESHOLD


def extract_identifiers_from_messages(messages: List[Dict[str, Any]]) -> str:
    """从消息列表中机械抽取标识符（UUID/表名/数据源ID等），压缩时不丢失。

    复用 extract_identifiers(text) 的完整模式集，逐条消息抽取后去重排序。
    同时抽取 tool_calls arguments 中的标识符（数据源 ID/表名常出现在工具参数中）。
    """
    identifiers: Set[str] = set()
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str) and content:
            identifiers |= extract_identifiers(content)
        for tc in m.get("tool_calls") or []:
            args = tc.get("function", {}).get("arguments", "")
            if args:
                identifiers |= extract_identifiers(args)
    return "\n".join(sorted(identifiers)) if identifiers else ""


async def compact_messages(
    messages: List[Dict[str, Any]],
    llm_manager=None,
    tail_turns: int = COMPACTION_TAIL_TURNS,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> List[Dict[str, Any]]:
    """压缩上下文：旧消息摘要 + 最近 N 轮原文。

    对齐 OpenCode compaction：
    - system prompt 保留
    - 最近 tail_turns 轮对话保留原文
    - 旧消息用 LLM 压缩成摘要
    - 标识符机械抽取，不依赖 LLM
    """
    if len(messages) <= tail_turns * 2 + 1:
        return messages  # 消息太少，不需要压缩

    # 分割：system + 旧消息 + 最近 N 轮
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    # 计算 tail_turns 对应的消息数（1 轮 = user + assistant[+ tool]）
    # 以 user 消息作为轮次边界，倒序数到第 tail_turns 个 user 即为保留区起点
    tail_count = 0
    split_idx = len(non_system)
    for i in range(len(non_system) - 1, -1, -1):
        if non_system[i].get("role") == "user":
            tail_count += 1
            if tail_count >= tail_turns:
                split_idx = i
                break

    old_messages = non_system[:split_idx]
    recent_messages = non_system[split_idx:]

    if not old_messages:
        return messages

    # 机械抽取标识符
    id_hint = extract_identifiers_from_messages(old_messages)

    # 构建压缩 prompt
    old_text = []
    for m in old_messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, str) and content:
            old_text.append(f"[{role}] {content[:1000]}")
        elif m.get("tool_calls"):
            tc_parts = []
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                args = fn.get("arguments", "")
                tc_parts.append(f"{name}({args[:200]})")
            old_text.append(f"[{role}] 调用工具: {', '.join(tc_parts)}")

    old_summary = "\n".join(old_text)[-4000:]  # 最多 4000 字符给 LLM 压缩

    compact_prompt = (
        "请将以下对话历史压缩成简洁摘要，保留：关键发现、错误信息、已做的修改、重要参数值。"
        "丢弃：冗余的工具调用细节、重复的调查过程。"
        f"\n\n标识符（必须保留）：\n{id_hint}\n"
        f"\n\n对话历史：\n{old_summary}\n\n"
        "输出摘要（500字以内）："
    )

    summary = ""
    if llm_manager:
        try:
            summary = await llm_manager.generate(compact_prompt, temperature=0.1)
            summary = summary.strip()[:1000]
        except Exception as e:
            logger.warning(f"上下文压缩 LLM 调用失败，使用机械摘要: {e}")
            summary = ""

    if not summary:
        # 兜底：机械摘要
        summary = f"[上下文压缩] 之前 {len(old_messages)} 条消息已压缩。关键标识符:\n{id_hint}"

    # 构建压缩后的消息列表
    compacted = list(system_msgs)
    summary_text = f"## 之前对话摘要（自动压缩）\n{summary}\n\n--- 以上为压缩的历史，以下是最近的对话 ---"
    if recent_messages and recent_messages[0].get("role") == "user":
        recent_messages = list(recent_messages)
        recent_messages[0] = {
            **recent_messages[0],
            "content": summary_text + "\n\n" + recent_messages[0].get("content", ""),
        }
    else:
        compacted.append({"role": "user", "content": summary_text})
    compacted.extend(recent_messages)

    _old_tokens = estimate_messages_tokens(messages)
    _new_tokens = estimate_messages_tokens(compacted)
    logger.info(f"上下文压缩: {len(messages)} 条 → {len(compacted)} 条, {_old_tokens} → {_new_tokens} tokens (省 {_old_tokens - _new_tokens})")

    return compacted


# ==================== 三级反幻觉注入 ====================

_ANTI_HALLUCINATION_SECTIONS: Dict[str, str] = {
    "basic": (
        "\n\n## 反幻觉约束（basic）\n"
        "- 所有数据结论必须基于工具返回的实际数据，不得编造或凭记忆推测\n"
        "- 不确定的信息应标注「需验证」\n"
    ),
    "standard": (
        "\n\n## 反幻觉约束（standard）\n"
        "- 所有数据结论必须基于工具返回的实际数据，不得编造或凭记忆推测\n"
        "- 引用数据时须标注来源：[来源: 数据源名/表名]\n"
        "- 区分文档事实与推理结论，推理结论须明确标注「推理」\n"
        "- 禁止用模型自身知识补充工具未返回的信息\n"
    ),
    "strict": (
        "\n\n## 反幻觉约束（strict）\n"
        "- 提到数据源/表存在前必须用工具确认\n"
        "- 使用工具获取精确计数，禁止估算行数/数量\n"
        "- 所有数字结论必须附带工具调用来源\n"
        "- 三层验证：广泛发现 → 逐一深入 → 系统化输出\n"
        "- 引用格式：[来源: 数据源ID/表名]\n"
    ),
}


def get_anti_hallucination_section(level: str = "basic") -> str:
    """获取指定级别的反幻觉约束文本，用于注入 system prompt。

    借鉴 DeepAnalyze 的三级反幻觉注入：
    - basic：通用对话（General Agent）
    - standard：检索分析（Explore/Compile Agent / DataProcessor）
    - strict：事实核查（Verify Agent / DataInspector）
    """
    return _ANTI_HALLUCINATION_SECTIONS.get(level, _ANTI_HALLUCINATION_SECTIONS["basic"])


# ==================== 工具调用过程显示（对齐 OpenCode）====================

# 工具图标映射
_TOOL_ICON_MAP = {
    "query_table_data": "📊",
    "get_table_schema": "📋",
    "execute_sql": "🔍",
    "list_user_datasources": "📚",
    "list_user_file_links": "🔗",
    "save_file_to_link": "💾",
    "write_table_data": "✍️",
    "kb_search": "🔎",
    "web_fetch": "🔗",
    # Inspector 工具
    "profile_data": "📈",
    "check_data_standards": "📐",
    "check_data_quality": "✅",
    "check_data_security": "🔒",
    # 调试工具
    "read_script": "📖",
    "grep_script": "🔍",
    "edit_script": "✏️",
    "run_script": "▶️",
    # 扩展工具
    "call_operator": "⚙️",
    "get_llm_config": "🤖",
    "save_llm_adapter": "🤖",
    "delete_llm_adapter": "🗑️",
}


def build_tool_action_event(tool_calls: list) -> Dict[str, Any]:
    """根据 tool_calls 构造 tool_action 事件，用于前端显示工具调用过程。

    前端显示形如：📊 execute_sql: SELECT 批次, COUNT(*) FROM ...
    每个 tool_call 一个 _act 条目，actions 列表传给前端逐个显示。
    """
    _actions = []
    for tc in tool_calls:
        _name = tc["function"]["name"]
        _icon = _TOOL_ICON_MAP.get(_name, "🔧")
        _act = {"tool": _name, "icon": _icon}
        try:
            _args = json.loads(tc["function"]["arguments"])
            if _name == "execute_sql":
                _sql = _args.get("sql", "").strip()
                # 单行化 + 截断
                _sql = re.sub(r"\s+", " ", _sql)[:200]
                if _sql:
                    _act["detail"] = _sql
            elif _name == "query_table_data":
                _tbl = _args.get("table_name", "")
                _page = _args.get("page", 1)
                if _tbl:
                    _act["detail"] = f"表={_tbl}" + (f", 第{_page}页" if _page > 1 else "")
            elif _name == "get_table_schema":
                _tbl = _args.get("table_name", "")
                if _tbl:
                    _act["detail"] = f"表={_tbl}"
            elif _name == "kb_search":
                _q = _args.get("query", "")[:50]
                if _q:
                    _act["detail"] = f'"{_q}"'
            elif _name == "write_table_data":
                _tbl = _args.get("table_name", "")
                if _tbl:
                    _act["detail"] = f"写入表={_tbl}"
            elif _name == "read_script":
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
                    _diff_lines = [f"- {l}" for l in _old.splitlines()[:15]]
                    _diff_lines += [f"+ {l}" for l in _new.splitlines()[:15]]
                    _act["diff"] = "\n".join(_diff_lines)
            elif _name == "run_script":
                _act["detail"] = "执行脚本"
        except Exception:
            pass
        _actions.append(_act)
    return {"type": "tool_action", "actions": _actions}


# ==================== 搜索饱和检测 ====================

class SearchSaturationDetector:
    """检测重复搜索是否不再产生新信息。

    借鉴 DeepAnalyze 的 SearchSaturationDetector：
    跟踪最近搜索结果的关键内容，用 Jaccard 重叠度判断是否饱和。
    """

    def __init__(self, threshold: float = 0.80, consecutive_limit: int = 3):
        self.threshold = threshold
        self.consecutive_limit = consecutive_limit
        self._recent_results: List[Set[str]] = []
        self._saturated_count = 0

    def record_search(self, result_content: str) -> Optional[str]:
        """记录一次搜索结果，返回饱和干预提示或 None。"""
        tokens = set(re.findall(r'[\w\u4e00-\u9fff]{2,}', result_content.lower()))
        if not tokens:
            return None

        if self._recent_results:
            prev = self._recent_results[-1]
            if prev:
                overlap = len(tokens & prev) / len(tokens | prev)
                if overlap >= self.threshold:
                    self._saturated_count += 1
                else:
                    self._saturated_count = 0
        self._recent_results.append(tokens)
        if len(self._recent_results) > 5:
            self._recent_results.pop(0)

        if self._saturated_count >= self.consecutive_limit:
            self._saturated_count = 0
            return (
                "最近多次搜索返回高度相似的结果，可能已搜尽相关信息。"
                "请换一个角度分析，或基于已有信息输出结论。"
            )
        return None

    def reset(self):
        self._recent_results.clear()
        self._saturated_count = 0


# ==================== 工具结果 LRU 缓存 ====================

import time
from collections import OrderedDict


class ToolResultCache:
    """只读工具的会话内 LRU 去重缓存。

    借鉴 DeepAnalyze 的 ToolResultCache：
    - key = toolName + sorted(args)
    - 只缓存只读工具（查询类）
    - 默认 30 分钟 TTL、50 条上限
    """

    READONLY_TOOLS = frozenset({
        "query_table_data", "get_table_schema",
        "list_user_file_links",
        "kb_search", "profile_data",
        "check_data_standards", "check_data_quality", "check_data_security",
    })

    def __init__(self, ttl: int = 1800, max_entries: int = 50):
        self._cache: OrderedDict[str, tuple] = OrderedDict()
        self._ttl = ttl
        self._max_entries = max_entries

    def _make_key(self, tool_name: str, args: dict) -> str:
        return f"{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"

    def get(self, tool_name: str, args: dict) -> Optional[str]:
        if tool_name not in self.READONLY_TOOLS:
            return None
        key = self._make_key(tool_name, args)
        entry = self._cache.get(key)
        if entry is None:
            return None
        result, ts = entry
        if time.time() - ts > self._ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return result

    def put(self, tool_name: str, args: dict, result: str):
        if tool_name not in self.READONLY_TOOLS:
            return
        key = self._make_key(tool_name, args)
        self._cache[key] = (result, time.time())
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)

    def clear(self):
        self._cache.clear()
