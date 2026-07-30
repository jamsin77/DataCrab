"""Pipeline Builder - 从 Skill 机械转换流程（保留调试好的脚本，不重新生成）"""

import ast
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from app.services.skill_parser import read_skill_md, read_skill_script, list_skill_scripts
from app.services.skill_runner import _strip_main_block


async def build_pipeline_from_skill(
    skill_path_str: str,
    skill_id: str,
    skill_name: str,
    skill_display_name: str,
    fixed_parameters: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """从 Skill 机械转换 Pipeline：保留调试好的脚本原样，固化参数调用。

    不调用 LLM，不重新生成代码。main_code = skill 脚本内容（剥 if __name__ 块）。
    如果提供 fixed_parameters（最近成功执行参数），在末尾追加 _pipeline_entry
    函数固化参数调用 main，流程执行时不需要用户填参数。
    """
    skill_path = Path(skill_path_str)

    skill_md = read_skill_md(skill_path) or ""

    scripts = {}
    for script_info in list_skill_scripts(skill_path):
        name = script_info["name"] if isinstance(script_info, dict) else script_info
        content = script_info.get("content") if isinstance(script_info, dict) else read_skill_script(skill_path, script_info)
        scripts[name] = content

    main_script = scripts.get("main.py") or next(iter(scripts.values()), "")
    if not main_script:
        raise ValueError("Skill 没有可执行脚本")

    main_code = _strip_main_block(main_script)

    uses_argparse, function_name = _detect_entry(main_code)

    parameters = _extract_parameters_from_skill(skill_md, main_code, uses_argparse)

    skill_calls = _analyze_skill_calls(main_code, skill_id, skill_name)

    entry_function = function_name
    if fixed_parameters:
        for p in parameters:
            if p["name"] in fixed_parameters:
                p["default"] = fixed_parameters[p["name"]]
        main_code += _build_pipeline_entry(fixed_parameters, uses_argparse)
        entry_function = "_pipeline_entry"

    logger.info(
        f"Pipeline 从 Skill 机械转换: {skill_name}, "
        f"argparse={uses_argparse}, entry={entry_function}, "
        f"params={len(parameters)}, fixed={bool(fixed_parameters)}, "
        f"code={len(main_code)} 字符"
    )

    return {
        "main_code": main_code,
        "entry_function": entry_function,
        "parameters": parameters,
        "skill_calls": skill_calls,
    }


def _build_pipeline_entry(fixed_parameters: Dict[str, Any], uses_argparse: bool) -> str:
    """构建流程入口函数 _pipeline_entry，固化参数调用 main。

    argparse 脚本：把参数转为 sys.argv 后调用 main()
    非 argparse 脚本：直接 main(**fixed_parameters)
    """
    if uses_argparse:
        argv_parts = ["'script'"]
        for key, val in fixed_parameters.items():
            k = key if key.startswith("--") else "--" + key
            if isinstance(val, bool):
                if val:
                    argv_parts.append(repr(k))
            elif isinstance(val, list):
                argv_parts.append(repr(k))
                for v in val:
                    argv_parts.append(repr(str(v)))
            else:
                argv_parts.append(repr(k))
                argv_parts.append(repr(str(val)))
        argv_str = ", ".join(argv_parts)
        return f"""

# === 流程入口：固化参数调用 main ===
def _pipeline_entry(**kwargs):
    import sys as _sys
    _sys.argv = [{argv_str}]
    return main()
"""
    else:
        params_repr = repr(fixed_parameters)
        return f"""

# === 流程入口：固化参数调用 main ===
def _pipeline_entry(**kwargs):
    return main(**{params_repr})
"""


def _detect_entry(script_content: str) -> tuple:
    """AST 检测脚本入口。

    Returns:
        (uses_argparse, function_name)
        - argparse 脚本 → (True, "main")，执行器靠 _build_argv_from_params 转 argv
        - 非 argparse → (False, function_name)，直接 func(**params) 调用
    """
    uses_argparse = False
    function_name = "main"
    try:
        tree = ast.parse(script_content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "argparse" for a in node.names):
                uses_argparse = True
            elif isinstance(node, ast.ImportFrom) and node.module == "argparse":
                uses_argparse = True
        if uses_argparse:
            return True, "main"
        func_defs = [
            (n.name, n)
            for n in ast.iter_child_nodes(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
        ]
        if func_defs:
            def _pc(fn):
                return len(fn.args.args) + len(fn.args.kwonlyargs) + len(fn.args.posonlyargs)

            best = max(func_defs, key=lambda f: _pc(f[1]))
            if "main" in [f[0] for f in func_defs]:
                main_node = next(f[1] for f in func_defs if f[0] == "main")
                function_name = "main" if _pc(main_node) > 0 else best[0]
            else:
                function_name = best[0]
    except SyntaxError:
        pass
    return uses_argparse, function_name


def _extract_parameters_from_skill(
    skill_md: str, script_content: str, uses_argparse: bool
) -> List[Dict[str, Any]]:
    """提取参数列表。

    argparse 脚本：从 add_argument 调用提取 name/required/type/description
    非 argparse：从 main() 函数签名提取
    补充：从 SKILL.md 参数表匹配描述和类型
    """
    if uses_argparse:
        params = _extract_argparse_params(script_content)
    else:
        params = _extract_main_params(script_content)

    md_params = _parse_skill_md_param_table(skill_md)
    for p in params:
        md_info = md_params.get(p["name"])
        if md_info:
            if not p.get("description"):
                p["description"] = md_info.get("description", "")
            if (not p.get("type") or p["type"] == "any") and md_info.get("type"):
                p["type"] = md_info["type"]
    return params


def _extract_argparse_params(script_content: str) -> List[Dict[str, Any]]:
    """AST 提取 argparse add_argument 调用的参数定义。"""
    params = []
    try:
        tree = ast.parse(script_content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "add_argument":
                    name = None
                    required = False
                    description = ""
                    ptype = "any"
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            val = arg.value
                            if val.startswith("--"):
                                name = val.lstrip("-")
                            elif val.startswith("-") and name is None:
                                name = val.lstrip("-")
                    for kw in node.keywords:
                        if kw.arg == "required" and isinstance(kw.value, ast.Constant):
                            required = bool(kw.value.value)
                        elif kw.arg == "help" and isinstance(kw.value, ast.Constant):
                            description = kw.value.value or ""
                        elif kw.arg == "type":
                            if isinstance(kw.value, ast.Name):
                                ptype = kw.value.id
                            elif isinstance(kw.value, ast.Attribute):
                                ptype = kw.value.attr
                    if name:
                        params.append({
                            "name": name,
                            "type": ptype,
                            "required": required,
                            "description": description,
                        })
    except SyntaxError:
        logger.warning("argparse 参数提取失败（语法错误），返回空列表")
    return params


def _parse_skill_md_param_table(skill_md: str) -> Dict[str, Dict[str, Any]]:
    """从 SKILL.md 参数表（markdown table）解析参数信息。

    格式：
    | 参数名 | 类型 | 必填 | 说明 |
    | :--- | :--- | :--- | :--- |
    | datasource | string | 是 | 数据源名称 |
    """
    result: Dict[str, Dict[str, Any]] = {}
    lines = skill_md.split("\n")
    in_table = False
    for line in lines:
        stripped = line.strip()
        if "|" in stripped and ("参数" in stripped or "类型" in stripped or "必填" in stripped):
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            break
        if "---" in stripped:
            continue
        parts = [p.strip() for p in stripped.split("|")]
        parts = [p for p in parts if p]
        if len(parts) >= 4:
            name = parts[0]
            ptype = parts[1]
            required = "是" in parts[2]
            desc = parts[3]
            result[name] = {"type": ptype, "required": required, "description": desc}
    return result


def _analyze_skill_calls(code: str, skill_id: str, skill_name: str) -> List[Dict[str, Any]]:
    """AST 分析主函数中对 Skill 脚本函数的调用"""
    calls = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name and func_name.startswith("_skill_"):
                    calls.append({
                        "skill_id": skill_id,
                        "skill_name": skill_name,
                        "script": "scripts/main.py",
                        "function": func_name,
                        "line": node.lineno if hasattr(node, 'lineno') else 0,
                    })
    except SyntaxError:
        logger.warning("Pipeline main_code 语法检查失败，跳过调用分析")
    return calls


def _extract_main_params(code: str) -> List[Dict[str, Any]]:
    """AST 提取 main 函数的参数定义，并从 docstring 中解析参数说明"""
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                docstring = ast.get_docstring(node) or ""
                param_docs = _parse_docstring_params(docstring)

                params = []
                for arg in node.args.args:
                    name = arg.arg
                    params.append({
                        "name": name,
                        "type": _annotation_to_str(arg.annotation),
                        "required": True,
                        "description": param_docs.get(name, ""),
                    })
                for arg in node.args.kwonlyargs:
                    name = arg.arg
                    params.append({
                        "name": name,
                        "type": _annotation_to_str(arg.annotation),
                        "required": False,
                        "description": param_docs.get(name, ""),
                    })
                if node.args.vararg:
                    name = f"*{node.args.vararg.arg}"
                    raw_name = node.args.vararg.arg
                    params.append({
                        "name": name,
                        "type": "tuple",
                        "required": False,
                        "description": param_docs.get(raw_name, param_docs.get(name, "")),
                    })
                if node.args.kwarg:
                    name = f"**{node.args.kwarg.arg}"
                    raw_name = node.args.kwarg.arg
                    params.append({
                        "name": name,
                        "type": "dict",
                        "required": False,
                        "description": param_docs.get(raw_name, param_docs.get(name, "")),
                    })
                return params
    except SyntaxError:
        pass
    return []


def _parse_docstring_params(docstring: str) -> Dict[str, str]:
    """从 docstring 的 Args:/Arguments:/Parameters: 部分解析参数说明"""
    import re
    result: Dict[str, str] = {}
    lines = docstring.split("\n")
    in_args = False
    current_name = ""
    current_desc = ""

    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if low in ("args:", "arguments:", "parameters:", "参数:"):
            in_args = True
            continue
        if in_args:
            if low in ("returns:", "return:", "yields:", "raises:", "examples:", "example:", "note:", "notes:"):
                if current_name:
                    result[current_name] = current_desc.strip()
                break
            m = re.match(r'^(\*{0,2}\w+)\s*[:：]\s*(.*)$', stripped)
            if m:
                if current_name:
                    result[current_name] = current_desc.strip()
                current_name = m.group(1).lstrip("*")
                current_desc = m.group(2)
            elif stripped and current_name:
                current_desc += " " + stripped
            elif not stripped:
                if current_name and current_desc:
                    result[current_name] = current_desc.strip()
                    current_name = ""
                    current_desc = ""

    if current_name:
        result[current_name] = current_desc.strip()

    return result


def _annotation_to_str(ann) -> str:
    if ann is None:
        return "any"
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Constant):
        return str(ann.value)
    return "any"
