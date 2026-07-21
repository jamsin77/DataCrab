"""Agent 工程工具函数

借鉴 DeepAnalyze 的工程设计：
- CJK 感知的 token 估算
- 工具结果截断保护
- 卡死检测器（StuckDetector）
- 标识符机械抽取（压缩保护）
- 反幻觉检查工具
- 动态轮次预算（进度感知替代硬上限）
- 上下文压力主动告警
- 三级反幻觉注入（basic/standard/strict）
- 搜索饱和检测（SearchSaturationDetector）
"""
import re
import json
import hashlib
from typing import Dict, Any, List, Set, Optional, Tuple


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

    借鉴 DeepAnalyze 的 StuckDetector，识别两种模式：
    - 重复调用：连续 N 轮调用相同工具 + 相同参数
    - 空转：连续 N 轮有输出但没有工具调用
    """

    def __init__(self, repeat_threshold: int = 2, idle_threshold: int = 3):
        self.repeat_threshold = repeat_threshold
        self.idle_threshold = idle_threshold
        self._call_history: List[str] = []
        self._idle_count: int = 0

    def record_tool_call(self, tool_name: str, arguments: dict) -> Optional[str]:
        """记录一次工具调用，返回干预提示（如果检测到卡死）或 None。"""
        args_str = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        signature = hashlib.md5(f"{tool_name}:{args_str}".encode()).hexdigest()
        self._call_history.append(signature)
        self._idle_count = 0

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

_PLANNING_PREFIXES = (
    "我将", "让我", "首先", "我已", "策略", "计划", "步骤", "将采取",
    "接下来", "下面我", "我的思路", "I will", "Let me", "First",
)


def has_data_claims(text: str) -> bool:
    """检查文本中是否包含数据声明（数字、统计结论等）。"""
    if not text:
        return False
    for pattern in _DATA_CLAIM_PATTERNS:
        if pattern.search(text):
            return True
    return False


def is_planning_only(text: str) -> bool:
    """检查文本是否只是规划文本（"我将...然后...最后..."）而没有实际产出。

    借鉴 DeepAnalyze 的"防只规划不执行"机制。
    """
    if not text or len(text) > 2000:
        return False
    stripped = text.strip()
    return any(stripped.startswith(prefix) for prefix in _PLANNING_PREFIXES)


def should_warn_ungrounded_claim(output_text: str, had_tool_calls_this_turn: bool) -> Optional[str]:
    """检查 agent 输出中是否有无工具支撑的数据声明。

    借鉴 DeepAnalyze 的反幻觉检查：如果输出包含数据声明但本轮没有工具调用，
    返回警告提示。
    """
    if not output_text:
        return None
    if has_data_claims(output_text) and not had_tool_calls_this_turn:
        return (
            "你的输出包含数据结论（数字/统计），但本轮未调用任何数据查询工具。"
            "请确认数据来源：是用工具查到的，还是基于记忆/推测？"
            "如果是后者，请先调用工具查询实际数据。"
        )
    return None


# ==================== 动态轮次预算（进度感知）====================

_COMPLEXITY_KEYWORDS = {
    "simple": ["查询", "查看", "看看", "显示", "列出", "多少", "count", "show", "list", "什么是"],
    "complex": ["分析", "清洗", "转换", "合并", "关联", "交叉", "对比", "报告", "批量", "全部",
                 "analyze", "clean", "transform", "merge", "join", "compare", "report"],
}


def estimate_complexity(user_message: str) -> str:
    """根据用户消息估算任务复杂度。

    借鉴 DeepAnalyze 的 calculateDynamicTurnBudget：
    - simple：简单查询、单表查找
    - medium：中等分析、多步处理
    - complex：复杂多表分析、全量处理、报告生成
    """
    if not user_message:
        return "simple"
    msg_lower = user_message.lower()
    complex_hits = sum(1 for kw in _COMPLEXITY_KEYWORDS["complex"] if kw in msg_lower or kw in user_message)
    if complex_hits >= 2:
        return "complex"
    if complex_hits == 1:
        return "medium"
    return "simple"


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
        "list_user_datasources", "list_user_file_links",
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
