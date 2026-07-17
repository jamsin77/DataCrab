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
    context_summary: str = "",
) -> None:
    """追加一条反例（失败记录）。context_summary 记录推理过程中的关键信息。"""
    data = read_experience(base)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "source": source,  # run / debug / nl
        "script_name": script_name,
        "error_type": error_type,
        "error_message": (error_message or "")[:500],
        "parameters": parameters or {},
        "stdout_preview": (stdout or "")[:200],
        "context_summary": (context_summary or "")[:800],
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


# ==================== 调试历史（Agent 长期记忆）====================

MAX_DEBUG_HISTORY = 50  # 最多保留 50 条调试记录


def append_debug_history(base: Path, *, session_log: str) -> None:
    """追加一次调试会话的修改历史到 experience.json。
    session_log 是 run_debug 结束时生成的本轮修改摘要文本。"""
    if not session_log or not session_log.strip():
        return
    data = read_experience(base)
    data.setdefault("debug_history", [])
    data["debug_history"].append({
        "timestamp": datetime.now().isoformat(),
        "session_log": session_log[:2000],
    })
    if len(data["debug_history"]) > MAX_DEBUG_HISTORY:
        data["debug_history"] = data["debug_history"][-MAX_DEBUG_HISTORY:]
    _write(base, data)


def read_debug_history(base: Path) -> str:
    """读取调试历史，返回拼接的文本（用于注入系统提示词）。"""
    data = read_experience(base)
    history = data.get("debug_history", [])
    if not history:
        return ""
    # 取最近 5 次调试会话
    recent = history[-5:]
    parts = []
    for h in recent:
        ts = h.get("timestamp", "")[:19]
        log = h.get("session_log", "")
        parts.append(f"[{ts}]\n{log}")
    return "\n\n".join(parts)


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


# ==================== 跨算子经验聚合（N）====================
# 借鉴 DeepAnalyze AutoDream 的跨会话经验整合思想，
# 将多个算子/技能的经验 lessons 做一次 LLM 整合，提炼通用数据处理模式。

GLOBAL_LESSONS_FILE = "global_lessons.md"


def global_lessons_path() -> Path:
    """全局经验文件路径"""
    from app.core.config import settings
    return Path(settings.SKILL_STORAGE_PATH).parent / GLOBAL_LESSONS_FILE


def read_global_lessons() -> str:
    """读取全局通用经验"""
    p = global_lessons_path()
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


async def distill_cross_patterns(db, user_id) -> str:
    """跨算子经验聚合：收集所有算子+技能的 lessons，用 LLM 提炼通用模式（N）。

    借鉴 DeepAnalyze 的 AutoDream 思路，但适合 DataCrab 的粒度：
    - DataCrab 按 算子/skill 积累经验（experience.json → lessons）
    - 本函数把多个 lessons 做一次跨算子整合，发现通用数据处理经验
    - 结果存到 global_lessons.md，在生成/修改算子时注入
    """
    # 收集所有 lessons
    parts = []
    try:
        from app.models.operator import Operator
        from sqlalchemy import select
        res = await db.execute(select(Operator).where(Operator.author == user_id))
        for op in res.scalars():
            ls = read_lessons(operator_experience_dir(op.id))
            if ls:
                parts.append(f"### 算子「{op.display_name or op.name}」经验\n{ls[:300]}")
    except Exception:
        pass
    try:
        from app.models.skill import Skill
        from sqlalchemy import select
        from app.core.config import settings
        skill_base = Path(settings.SKILL_STORAGE_PATH)
        res = await db.execute(select(Skill).where(Skill.author == user_id))
        for s in res.scalars():
            sp = skill_base / str(s.id)
            ls = read_lessons(sp)
            if ls:
                parts.append(f"### 技能「{s.display_name or s.name}」经验\n{ls[:300]}")
    except Exception:
        pass

    if not parts:
        return ""

    # 用 LLM 提炼通用模式
    try:
        from app.services.llm import llm_manager
        all_lessons = "\n\n".join(parts)[:8000]
        prompt = f"""以下是多个算子和技能各自积累的数据处理经验。请从中提炼出通用的数据处理模式和最佳实践，
不要重复单个算子的细节，而是找出跨算子的共性规律。输出限 500 字以内，用中文。

{all_lessons}
"""
        distilled = await llm_manager.chat_with_messages(
            messages=[
                {"role": "system", "content": "你是数据处理经验整合助手。从多条经验中提炼通用模式。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=600,
        )
        if distilled:
            global_lessons_path().parent.mkdir(parents=True, exist_ok=True)
            global_lessons_path().write_text(distilled, encoding="utf-8")
            return distilled
    except Exception as e:
        from loguru import logger
        logger.warning(f"跨算子经验聚合失败: {e}")

    return ""


async def collect_all_lessons_with_global(db, user_id) -> str:
    """收集该用户所有经验 + 全局通用经验，用于注入提示词。"""
    parts = []
    # 全局通用经验
    global_ls = read_global_lessons()
    if global_ls:
        parts.append(f"## 通用数据处理经验\n{global_ls[:500]}")
    # 各算子/技能经验
    individual = await collect_all_lessons(db, user_id)
    if individual:
        parts.append(individual)
    return "\n\n".join(parts) if parts else ""
