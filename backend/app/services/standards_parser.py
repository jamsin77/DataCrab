"""数据标准库 / 数据质量库 MD 解析器

将 data_standards.md / data_quality_rules.md 解析为结构化规则，供 DataInspector 检查工具确定性执行。
"""
import re
from pathlib import Path
from typing import List, Dict, Optional

from app.core.config import settings


def _standards_dir() -> Path:
    return Path(settings.SKILL_STORAGE_PATH).parent / "standards"


def parse_standards() -> List[Dict]:
    """解析 data_standards.md，返回所有标准（含正则、合法值、约束规则）。

    每条: {id, name, category, fields, regex, legal_values, severity}
    """
    p = _standards_dir() / "data_standards.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    standards: List[Dict] = []

    # 匹配每个 `### STD-xxx 名称` 小节
    pattern = re.compile(
        r'^### (STD-\S+)\s+(.+?)\n((?:(?!^### |^---$).)+)',
        re.MULTILINE | re.DOTALL,
    )
    for m in pattern.finditer(text):
        sid = m.group(1)
        name = m.group(2).strip()
        body = m.group(3)
        category = ""
        fields: List[str] = []
        regex: Optional[str] = None
        legal_values: List[str] = []
        severity = "warning"
        for line in body.splitlines():
            ls = line.strip()
            if ls.startswith("- 分类"):
                category = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 适用字段"):
                fields_str = ls.split(":", 1)[1].strip()
                fields = [f.strip() for f in re.split(r"[,，]", fields_str) if f.strip()]
            elif ls.startswith("- 格式正则"):
                regex = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 合法值"):
                val_str = ls.split(":", 1)[1].strip()
                for part in re.split(r'\s*或\s*', val_str):
                    legal_values.extend([v.strip() for v in part.split('/') if v.strip()])
            elif ls.startswith("- 严重等级"):
                severity = ls.split(":", 1)[1].strip()
        # 不再跳过无正则规则（枚举/数值约束等也要返回）
        standards.append({
            "id": sid,
            "name": name,
            "category": category,
            "fields": fields,
            "regex": regex,
            "legal_values": legal_values,
            "severity": severity,
        })
    return standards


def _parse_threshold_value(threshold: str) -> Optional[float]:
    """从阈值文本提取数值：'10%' → 0.1, '5%' → 0.05, '0.01' → 0.01, '0' → 0.0, '95%' → 0.95"""
    if not threshold:
        return None
    m = re.search(r'(\d+(\.\d+)?)\s*%', threshold)
    if m:
        return float(m.group(1)) / 100.0
    m = re.search(r'(\d+(\.\d+)?)', threshold)
    if m:
        v = float(m.group(1))
        # 纯数值若 ≥1 且非百分比，按原值（如 0.01 保持，24 保持 24）
        return v
    return None


def parse_quality_rules() -> List[Dict]:
    """解析 data_quality_rules.md，返回规则列表。

    每条: {id, name, dimension, scope, logic, threshold, threshold_value, severity}
    """
    p = _standards_dir() / "data_quality_rules.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    rules: List[Dict] = []

    pattern = re.compile(
        r'^### (DQ-\S+)\s+(.+?)\n((?:(?!^### |^---$).)+)',
        re.MULTILINE | re.DOTALL,
    )
    # 预扫章节维度（## 一、完整性 Completeness）
    chapter_dims: Dict[int, str] = {}
    for m in re.finditer(r'^##\s+(.+?)$', text, re.MULTILINE):
        chapter_dims[m.start()] = m.group(1).strip()

    for m in pattern.finditer(text):
        rid = m.group(1)
        name = m.group(2).strip()
        body = m.group(3)
        # 找到该规则之前的最近章节作为维度
        dim = ""
        starts = [s for s in chapter_dims if s <= m.start()]
        if starts:
            dim = chapter_dims[max(starts)]
        scope = ""
        logic = ""
        threshold = ""
        severity = "warning"
        for line in body.splitlines():
            ls = line.strip()
            if ls.startswith("- 适用范围"):
                scope = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 检查逻辑"):
                logic = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 阈值"):
                threshold = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 严重等级"):
                severity = ls.split(":", 1)[1].strip()
        rules.append({
            "id": rid,
            "name": name,
            "dimension": dim,
            "scope": scope,
            "logic": logic,
            "threshold": threshold,
            "threshold_value": _parse_threshold_value(threshold),
            "severity": severity,
        })
    return rules


def parse_security_rules() -> List[Dict]:
    """解析 data_security_rules.md，返回所有安全规则（含正则和检测逻辑）。

    每条: {id, name, category, scope, regex, detection_logic, severity}
    """
    p = _standards_dir() / "data_security_rules.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    rules: List[Dict] = []

    pattern = re.compile(
        r'^### (SEC-\S+)\s+(.+?)\n((?:(?!^### |^---$).)+)',
        re.MULTILINE | re.DOTALL,
    )
    for m in pattern.finditer(text):
        sid = m.group(1)
        name = m.group(2).strip()
        body = m.group(3)
        category = ""
        scope = ""
        regex: Optional[str] = None
        detection_logic = ""
        severity = "warning"
        for line in body.splitlines():
            ls = line.strip()
            if ls.startswith("- 分类"):
                category = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 适用范围"):
                scope = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 检测正则"):
                regex = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 检测逻辑"):
                detection_logic = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 严重等级"):
                severity = ls.split(":", 1)[1].strip()
        rules.append({
            "id": sid,
            "name": name,
            "category": category,
            "scope": scope,
            "regex": regex,
            "detection_logic": detection_logic,
            "severity": severity,
        })
    return rules


def match_columns(columns: List[str], std_fields: List[str]) -> List[str]:
    """根据标准的适用字段名匹配实际列名。
    规则：精确匹配（忽略大小写）；或字段名（长度≥4）作为列名子串，避免短名误报。
    """
    matched = []
    for col in columns:
        col_low = col.lower()
        for f in std_fields:
            if not f:
                continue
            fl = f.lower()
            if col_low == fl or (len(fl) >= 4 and fl in col_low):
                matched.append(col)
                break
    return matched


# ==================== 技能专属规则 ====================

def _parse_rules_md(text: str, id_prefix: str) -> List[Dict]:
    """通用 MD 规则解析：按 `### <前缀>-xxx 名称` 提取规则。

    Args:
        text: rules.md 文件内容
        id_prefix: 规则编号前缀（如 SKILL-STD / SKILL-DQ / SKILL-SEC）

    返回与全局解析器结构一致的规则列表（按前缀类别自动套用 STD/DQ/SEC 字段集）。
    """
    if not text or not id_prefix:
        return []
    # 按前缀匹配（如 "SKILL-STD-"），前缀本身可含子前缀
    pattern = re.compile(
        r'^### (' + re.escape(id_prefix) + r'-\S+)\s+(.+?)\n((?:(?!^### |^---$).)+)',
        re.MULTILINE | re.DOTALL,
    )
    rules: List[Dict] = []
    # 根据前缀末段决定字段集
    tail = id_prefix.rsplit("-", 1)[-1].upper()  # STD / DQ / SEC
    for m in pattern.finditer(text):
        rid = m.group(1)
        name = m.group(2).strip()
        body = m.group(3)
        rule: Dict = {"id": rid, "name": name}
        severity = "warning"
        for line in body.splitlines():
            ls = line.strip()
            if ls.startswith("- 严重等级"):
                severity = ls.split(":", 1)[1].strip()
            elif tail == "STD":
                if ls.startswith("- 分类"):
                    rule["category"] = ls.split(":", 1)[1].strip()
                elif ls.startswith("- 适用字段"):
                    rule["fields"] = [f.strip() for f in re.split(r"[,，]", ls.split(":", 1)[1].strip()) if f.strip()]
                elif ls.startswith("- 格式正则"):
                    rule["regex"] = ls.split(":", 1)[1].strip()
                elif ls.startswith("- 合法值"):
                    rule["legal_values"] = [v.strip() for v in re.split(r"[/]", ls.split(":", 1)[1].strip()) if v.strip()]
            elif tail == "DQ":
                if ls.startswith("- 适用范围"):
                    rule["scope"] = ls.split(":", 1)[1].strip()
                elif ls.startswith("- 适用字段"):
                    rule["fields"] = [f.strip() for f in re.split(r"[,，]", ls.split(":", 1)[1].strip()) if f.strip()]
                elif ls.startswith("- 检查逻辑"):
                    rule["logic"] = ls.split(":", 1)[1].strip()
                elif ls.startswith("- 格式正则") or ls.startswith("- 检测正则"):
                    rule["regex"] = ls.split(":", 1)[1].strip()
                elif ls.startswith("- 合法值"):
                    rule["legal_values"] = [v.strip() for v in re.split(r"[/]", ls.split(":", 1)[1].strip()) if v.strip()]
                elif ls.startswith("- 阈值"):
                    rule["threshold"] = ls.split(":", 1)[1].strip()
                    rule["threshold_value"] = _parse_threshold_value(rule["threshold"])
            elif tail == "SEC":
                if ls.startswith("- 分类"):
                    rule["category"] = ls.split(":", 1)[1].strip()
                elif ls.startswith("- 适用范围"):
                    rule["scope"] = ls.split(":", 1)[1].strip()
                elif ls.startswith("- 适用字段"):
                    rule["fields"] = [f.strip() for f in re.split(r"[,，]", ls.split(":", 1)[1].strip()) if f.strip()]
                elif ls.startswith("- 检测正则"):
                    rule["regex"] = ls.split(":", 1)[1].strip()
                elif ls.startswith("- 检测逻辑"):
                    rule["detection_logic"] = ls.split(":", 1)[1].strip()
        rule["severity"] = severity
        rules.append(rule)
    return rules


def parse_skill_rules(skill_path) -> Dict[str, List[Dict]]:
    """解析技能包内 rules.md，返回按类别分组的规则列表。

    Args:
        skill_path: 技能包文件夹路径（str/Path），内含 rules.md

    Returns:
        {"std": [...], "dq": [...], "sec": [...]}
        每个元素结构与全局 parse_standards/parse_quality_rules/parse_security_rules 一致。
        无 rules.md 或解析失败返回空列表。

    rules.md 格式示例（默认前缀 SKILL-STD-/SKILL-DQ-/SKILL-SEC-）：
        ### SKILL-STD-001 身份证号格式
        - 适用字段: id_card,身份证号
        - 格式正则: ^\\d{17}[\\dXx]$
        - 严重等级: error

        ### SKILL-DQ-001 国家级文物编号必填
        - 检查逻辑: protection_level='国家级' 时 serial_no 不能为空
        - 阈值: 0
        - 严重等级: critical
    """
    from pathlib import Path
    p = Path(skill_path) / "rules.md" if not str(skill_path).endswith("rules.md") else Path(skill_path)
    if not p.exists():
        return {"std": [], "dq": [], "sec": []}
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return {"std": [], "dq": [], "sec": []}
    return {
        "std": _parse_rules_md(text, "SKILL-STD"),
        "dq": _parse_rules_md(text, "SKILL-DQ"),
        "sec": _parse_rules_md(text, "SKILL-SEC"),
    }
