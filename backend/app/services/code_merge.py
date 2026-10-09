"""3-way code merge for concurrent skill debugging.

多个调试会话同时修改同一个技能脚本，保存时用 3-way merge 合并回主干。
策略：AST 函数级合并 → difflib 行级合并 → LLM 兜底。
"""
import ast
import difflib
from typing import Dict, List, Optional, Tuple

from loguru import logger


def _split_top_blocks(code: str) -> Dict[str, str]:
    """AST 拆分顶层块：imports / 函数 / 类 / if __name__ 块。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"__full__": code}
    lines = code.splitlines()
    blocks: Dict[str, str] = {}
    for node in ast.iter_child_nodes(tree):
        start = node.lineno - 1
        end = node.end_lineno if hasattr(node, "end_lineno") else start + 1
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            blocks[node.name] = "\n".join(lines[start:end])
        elif isinstance(node, ast.ClassDef):
            blocks[node.name] = "\n".join(lines[start:end])
        elif isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            blocks.setdefault("__imports__", "")
            if blocks["__imports__"]:
                blocks["__imports__"] += "\n"
            blocks["__imports__"] += "\n".join(lines[start:end])
        elif isinstance(node, ast.If):
            test = ast.dump(node.test) if hasattr(node, "test") else ""
            if "__main__" in test or "hasattr(sys" in test:
                blocks["__main__"] = "\n".join(lines[start:end])
            else:
                blocks.setdefault(f"__other_{start}__", "\n".join(lines[start:end]))
        else:
            blocks.setdefault(f"__other_{start}__", "\n".join(lines[start:end]))
    if not blocks:
        blocks["__full__"] = code
    return blocks


def _reassemble(blocks: Dict[str, str], order: List[str]) -> str:
    parts = []
    for key in order:
        if key in blocks:
            parts.append(blocks[key])
    return "\n\n".join(parts)


def _get_block_order(code: str) -> List[str]:
    """获取顶层块的出现顺序。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ["__full__"]
    order = []
    lines = code.splitlines()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            order.append(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if "__imports__" not in order:
                order.append("__imports__")
        elif isinstance(node, ast.If):
            test = ast.dump(node.test) if hasattr(node, "test") else ""
            if "__main__" in test or "hasattr(sys" in test:
                order.append("__main__")
            else:
                order.append(f"__other_{node.lineno - 1}__")
        else:
            order.append(f"__other_{node.lineno - 1}__")
    return order


def _merge_blocks(
    base: Dict[str, str],
    mine: Dict[str, str],
    theirs: Dict[str, str],
) -> Tuple[Dict[str, str], List[str]]:
    """逐块 3-way 决策。返回 (merged_blocks, conflict_block_names)。"""
    merged: Dict[str, str] = {}
    conflicts: List[str] = []
    all_keys = set(base) | set(mine) | set(theirs)
    for key in all_keys:
        b = base.get(key, "")
        m = mine.get(key, "")
        t = theirs.get(key, "")
        if m == t:
            merged[key] = m
        elif m == b and t != b:
            merged[key] = t
        elif t == b and m != b:
            merged[key] = m
        elif not m and not t:
            merged[key] = ""
        elif not m:
            merged[key] = t
        elif not t:
            merged[key] = m
        elif m == b and t == b:
            merged[key] = b
        else:
            line_merged = _merge_lines(b, m, t)
            if line_merged is not None:
                merged[key] = line_merged
            else:
                conflicts.append(key)
                merged[key] = _conflict_markers(m, t)
    return merged, conflicts


def _merge_lines(base: str, mine: str, theirs: str) -> Optional[str]:
    """行级 3-way merge：用 difflib SequenceMatcher 合并不重叠的变更。"""
    base_lines = base.splitlines()
    mine_lines = mine.splitlines()
    theirs_lines = theirs.splitlines()
    sm_mine = difflib.SequenceMatcher(None, base_lines, mine_lines)
    sm_theirs = difflib.SequenceMatcher(None, base_lines, theirs_lines)
    mine_ops = sm_mine.get_opcodes()
    theirs_ops = sm_theirs.get_opcodes()
    mine_changes = [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in mine_ops if tag != "equal"]
    theirs_changes = [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in theirs_ops if tag != "equal"]
    for m_i1, m_i2, _, _ in mine_changes:
        for t_i1, t_i2, _, _ in theirs_changes:
            if m_i1 < t_i2 and t_i1 < m_i2:
                return None
    result = list(base_lines)
    all_changes = []
    for i1, i2, j1, j2 in mine_changes:
        all_changes.append((i1, i2, mine_lines[j1:j2]))
    for i1, i2, j1, j2 in theirs_changes:
        all_changes.append((i1, i2, theirs_lines[j1:j2]))
    all_changes.sort(key=lambda x: x[0], reverse=True)
    for i1, i2, replacement in all_changes:
        result[i1:i2] = replacement
    return "\n".join(result)


def _conflict_markers(mine: str, theirs: str) -> str:
    return f"<<<<<<< mine\n{mine}\n=======\n{theirs}\n>>>>>>> theirs"


async def _llm_merge_conflict(base: str, mine: str, theirs: str, block_name: str) -> str:
    """LLM 兜底合并冲突块。"""
    from app.services.llm import llm_manager
    prompt = f"""你是代码合并专家。两个开发者同时修改了同一个代码块「{block_name}」，需要合并为一个版本。
请保留双方的意图，不要丢功能。直接输出合并后的完整代码，不要解释。

=== 基线版本 ===
{base}

=== 版本A（我的修改）===
{mine}

=== 版本B（他人的修改）===
{theirs}
"""
    try:
        resp = await llm_manager.chat_with_messages(
            messages=[{"role": "user", "content": prompt}],
            model=None,
            temperature=0.0,
        )
        content = resp.get("content", "").strip() if isinstance(resp, dict) else ""
        if content and "<<<<<<<" not in content:
            return content
    except Exception as e:
        logger.warning(f"[code_merge] LLM 合并失败: {e}")
    return _conflict_markers(mine, theirs)


async def merge_scripts(
    base_code: str,
    mine_code: str,
    theirs_code: str,
) -> Tuple[str, List[str]]:
    """3-way merge 两个版本到主干。

    Args:
        base_code: 会话开始时的原始快照
        mine_code: 本次会话的工作副本版本
        theirs_code: 当前磁盘主干版本（可能被其他会话改过）

    Returns:
        (merged_code, unresolved_conflicts)
    """
    if mine_code == theirs_code:
        return mine_code, []
    if mine_code == base_code:
        return theirs_code, []
    if theirs_code == base_code:
        return mine_code, []

    base_blocks = _split_top_blocks(base_code)
    mine_blocks = _split_top_blocks(mine_code)
    theirs_blocks = _split_top_blocks(theirs_code)
    if "__full__" in base_blocks or "__full__" in mine_blocks or "__full__" in theirs_blocks:
        line_merged = _merge_lines(base_code, mine_code, theirs_code)
        if line_merged is not None:
            return line_merged, []
        llm_merged = await _llm_merge_conflict(base_code, mine_code, theirs_code, "__full__")
        if "<<<<<<<" not in llm_merged:
            return llm_merged, ["__full__"]
        return llm_merged, ["__full__"]

    order = _get_block_order(base_code)
    seen = set(order)
    for key in _get_block_order(mine_code):
        if key not in seen:
            order.append(key)
            seen.add(key)
    for key in _get_block_order(theirs_code):
        if key not in seen:
            order.append(key)
            seen.add(key)

    merged_blocks, conflicts = _merge_blocks(base_blocks, mine_blocks, theirs_blocks)

    if conflicts:
        for name in conflicts[:3]:
            b = base_blocks.get(name, "")
            m = mine_blocks.get(name, "")
            t = theirs_blocks.get(name, "")
            resolved = await _llm_merge_conflict(b, m, t, name)
            if "<<<<<<<" not in resolved:
                merged_blocks[name] = resolved
                conflicts.remove(name)

    result = _reassemble(merged_blocks, order)
    return result, conflicts
