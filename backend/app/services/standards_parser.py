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
    """解析 data_standards.md，返回可自动检查的标准列表（含格式正则的）。

    每条: {id, name, category, fields, regex, severity}
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
            elif ls.startswith("- 严重等级"):
                severity = ls.split(":", 1)[1].strip()
        if regex:
            standards.append({
                "id": sid,
                "name": name,
                "category": category,
                "fields": fields,
                "regex": regex,
                "severity": severity,
            })
    return standards


def parse_quality_rules() -> List[Dict]:
    """解析 data_quality_rules.md，返回规则列表。

    每条: {id, dimension, scope, logic, threshold, severity}
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
    for m in pattern.finditer(text):
        rid = m.group(1)
        name = m.group(2).strip()
        body = m.group(3)
        dimension = ""
        threshold = ""
        severity = "warning"
        for line in body.splitlines():
            ls = line.strip()
            if ls.startswith("- 维度") or ls.startswith("- 适用范围"):
                if not dimension and ls.startswith("- 维度"):
                    dimension = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 阈值"):
                threshold = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 严重等级"):
                severity = ls.split(":", 1)[1].strip()
        rules.append({
            "id": rid,
            "name": name,
            "dimension": dimension,
            "threshold": threshold,
            "severity": severity,
        })
    return rules


def parse_security_rules() -> List[Dict]:
    """解析 data_security_rules.md，返回安全规则列表（含检测正则的）。

    每条: {id, name, category, scope, regex, severity}
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
        severity = "warning"
        for line in body.splitlines():
            ls = line.strip()
            if ls.startswith("- 分类"):
                category = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 适用范围"):
                scope = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 检测正则"):
                regex = ls.split(":", 1)[1].strip()
            elif ls.startswith("- 严重等级"):
                severity = ls.split(":", 1)[1].strip()
        if regex:
            rules.append({
                "id": sid,
                "name": name,
                "category": category,
                "scope": scope,
                "regex": regex,
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
