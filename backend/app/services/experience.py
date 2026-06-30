"""统一经验库服务（算子 + 技能共用）

Phase 1：反例库（negative）+ 经验归纳（lessons）。正例（positive）二期。
存储：每个算子/技能一个目录下的 experience.json，结构统一：
{
  "negative": [{timestamp, source, script_name, error_type, error_message, parameters, stdout_preview}],
  "positive": [],   # 二期
  "lessons": ""     # LLM 归纳的经验总结
}
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

EXPERIENCE_FILE = "experience.json"
MAX_NEGATIVE = 200


def operator_experience_dir(operator_id) -> Path:
    """算子经验目录：backend/data/operator_experiences/{operator_id}"""
    from app.core.config import settings
    base = Path(settings.SKILL_STORAGE_PATH).parent / "operator_experiences" / str(operator_id)
    return base


def read_experience(base: Path) -> Dict[str, Any]:
    """读取统一经验。base 为技能目录或算子经验目录。"""
    p = base / EXPERIENCE_FILE
    if not p.exists():
        return {"negative": [], "positive": [], "lessons": ""}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"negative": [], "positive": [], "lessons": ""}
    data.setdefault("negative", [])
    data.setdefault("positive", [])
    data.setdefault("lessons", "")
    return data


def _write(base: Path, data: Dict[str, Any]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / EXPERIENCE_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def append_negative(
    base: Path,
    *,
    source: str,
    error_type: str,
    error_message: str,
    parameters: Optional[Dict[str, Any]] = None,
    stdout: str = "",
    script_name: str = "",
) -> None:
    """追加一条反例（失败记录）。"""
    data = read_experience(base)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "source": source,  # run / debug / nl
        "script_name": script_name,
        "error_type": error_type,
        "error_message": (error_message or "")[:500],
        "parameters": parameters or {},
        "stdout_preview": (stdout or "")[:200],
    }
    data["negative"].append(entry)
    if len(data["negative"]) > MAX_NEGATIVE:
        data["negative"] = data["negative"][-MAX_NEGATIVE:]
    _write(base, data)


def read_negative(base: Path) -> List[Dict[str, Any]]:
    return read_experience(base)["negative"]


def append_positive(
    base: Path,
    *,
    source: str,
    parameters: Optional[Dict[str, Any]] = None,
    result_summary: str = "",
    script_name: str = "",
) -> None:
    """追加一条正例（成功模式，尤其修错后成功的模式）。"""
    data = read_experience(base)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "script_name": script_name,
        "parameters": parameters or {},
        "result_summary": (result_summary or "")[:300],
    }
    data["positive"].append(entry)
    if len(data["positive"]) > MAX_NEGATIVE:
        data["positive"] = data["positive"][-MAX_NEGATIVE:]
    _write(base, data)


def read_positive(base: Path) -> List[Dict[str, Any]]:
    return read_experience(base)["positive"]


def read_lessons(base: Path) -> str:
    """读取经验总结。优先 experience.json，兜底读 SKILL.md「常见问题与经验」（兼容旧技能）。"""
    ls = read_experience(base).get("lessons", "")
    if ls:
        return ls
    skill_md = base / "SKILL.md"
    if skill_md.exists():
        import re
        text = skill_md.read_text(encoding="utf-8")
        m = re.search(r"## 常见问题与经验\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return ""


def write_lessons(base: Path, lessons: str) -> None:
    data = read_experience(base)
    data["lessons"] = (lessons or "").strip()
    _write(base, data)


async def collect_all_lessons(db, user_id) -> str:
    """收集该用户所有算子+技能的经验总结，用于注入生成/修改/调试提示词。"""
    parts = []
    # 算子经验
    try:
        from app.models.operator import Operator
        from sqlalchemy import select
        res = await db.execute(select(Operator).where(Operator.author == user_id))
        for op in res.scalars():
            ls = read_lessons(operator_experience_dir(op.id))
            if ls:
                parts.append(f"### 算子「{op.display_name or op.name}」经验\n{ls[:500]}")
    except Exception:
        pass
    # 技能经验
    try:
        from app.models.skill import Skill
        from sqlalchemy import select
        skill_base = Path(settings.SKILL_STORAGE_PATH)
        res = await db.execute(select(Skill).where(Skill.author == user_id))
        for s in res.scalars():
            sp = skill_base / str(s.id)
            ls = read_lessons(sp)
            if ls:
                parts.append(f"### 技能「{s.display_name or s.name}」经验\n{ls[:500]}")
    except Exception:
        pass
    return "\n\n".join(parts) if parts else ""


def experience_stats(base: Path) -> Dict[str, int]:
    data = read_experience(base)
    return {
        "negative_count": len(data.get("negative", [])),
        "positive_count": len(data.get("positive", [])),
        "has_lessons": bool(data.get("lessons", "")),
    }
