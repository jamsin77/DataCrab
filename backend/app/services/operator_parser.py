"""Python脚本解析器 - 从上传的.py文件中提取算子定义"""

import ast
import re
from typing import Dict, Any, Optional, List


TYPE_MAP = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list": "list",
    "dict": "dict",
    "bytes": "bytes",
    "tuple": "tuple",
    "set": "set",
}


def parse_python_script(script_content: str) -> Dict[str, Any]:
    """解析Python脚本，提取函数签名、参数、返回值等信息（仅返回第一个公开函数，保持向后兼容）"""
    results = parse_python_script_multi(script_content)
    if results:
        return results[0]
    return {
        "function_name": None,
        "description": "",
        "parameters": [],
        "inputs": [],
        "outputs": [],
    }


def parse_python_script_multi(script_content: str) -> List[Dict[str, Any]]:
    """解析Python脚本，为每个公开函数提取函数签名、参数、返回值等信息"""
    tree = ast.parse(script_content)

    func_names = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            func_names.append(node)

    if not func_names:
        return []

    results = []
    for func_def in func_names:
        result = {
            "function_name": func_def.name,
            "description": "",
            "parameters": [],
            "inputs": [],
            "outputs": [],
        }

        docstring = ast.get_docstring(func_def)
        if docstring:
            result["description"] = docstring.strip()

        args = func_def.args
        all_args = list(args.args) if args.args else []
        all_args += list(args.kwonlyargs) if args.kwonlyargs else []

        defaults_count = len(args.defaults)
        no_default_count = len(all_args) - defaults_count

        for i, arg in enumerate(all_args):
            anno_type = _get_annotation_str(arg.annotation) if arg.annotation else None

            has_default = i >= no_default_count
            default_index = i - no_default_count if has_default else -1
            raw_default = args.defaults[default_index] if has_default and default_index < len(args.defaults) else None
            default_value = _serialize_default(raw_default)

            if anno_type is None and default_value is not None:
                anno_type = _infer_type_from_default(default_value)
            if anno_type is None:
                anno_type = _infer_type_from_name(arg.arg)

            param_info = {
                "name": arg.arg,
                "type": anno_type,
                "required": not has_default,
                "default": default_value,
            }
            result["parameters"].append(param_info)

            if not has_default:
                result["inputs"].append({
                    "name": arg.arg,
                    "type": anno_type,
                    "required": True,
                })

        return_annotation = func_def.returns
        if return_annotation:
            result["outputs"].append({
                "name": "result",
                "type": _get_annotation_str(return_annotation),
            })
        else:
            result["outputs"].append({"name": "result", "type": "any"})

        results.append(result)

    return results


def _get_annotation_str(node) -> str:
    if node is None:
        return "any"
    if isinstance(node, ast.Name):
        return TYPE_MAP.get(node.id, node.id)
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Subscript):
        base = _get_annotation_str(node.value)
        return base
    if isinstance(node, ast.Attribute):
        return node.attr
    return "any"


def _infer_type_from_name(arg_name: str) -> str:
    lower = arg_name.lower()
    if lower in ("df", "data", "dataframe", "table"):
        return "DataFrame"
    if lower in ("columns", "cols", "column_list"):
        return "list[str]"
    if lower.endswith("_column") or lower.endswith("_col"):
        return "str"
    if lower in ("filepath", "path", "filename"):
        return "str"
    return "any"


def _infer_type_from_default(default_value: str) -> str:
    try:
        val = eval(default_value)
        if isinstance(val, bool):
            return "bool"
        if isinstance(val, int):
            return "int"
        if isinstance(val, float):
            return "float"
        if isinstance(val, str):
            return "str"
        if isinstance(val, list):
            return "list"
        if isinstance(val, dict):
            return "dict"
    except Exception:
        pass
    return "any"


def _serialize_default(node) -> Optional[str]:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Name):
        if node.id in ("True", "False", "None"):
            return node.id
        return node.id
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
            return repr(-node.operand.value)
    return None


def extract_script_name(filename: str) -> str:
    return re.sub(r"\.py$", "", filename, flags=re.IGNORECASE)


def _find_main_block_line(code: str) -> int:
    """找到 if __name__ == '__main__': 的行号（0-based），用于确定新函数插入位置。
    找不到返回末尾行数（即追加到文件末尾）。"""
    try:
        tree = ast.parse(code)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.If):
                test = node.test
                if (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == '__name__'
                    and len(test.ops) == 1
                    and isinstance(test.ops[0], ast.Eq)
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == '__main__'):
                    return node.lineno - 1
    except SyntaxError:
        pass
    return len(code.split('\n'))


def _ensure_var_kwargs(func_code: str, func_name: str) -> str:
    """若函数定义缺少 **kwargs 则补上（防止 LLM 重写时丢失，导致 runner 传多余参数报 TypeError）。

    仅在外层调用方确认"原函数有 **kwargs 而新函数没有"时调用。
    对齐 OpenCode Edit 语义：行级补丁天然保上下文，不会丢参数；本函数是整函数替换的兜底保护。
    """
    try:
        tree = ast.parse(func_code)
    except SyntaxError:
        return func_code

    target = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            target = node
            break
    if not target or target.args.kwarg:
        return func_code  # 找不到或已有 **kwargs

    lines = func_code.split("\n")
    # 签名范围：def 行 到 body 第一行之前（1-based）
    sig_end = target.body[0].lineno - 1
    sig_start = target.lineno
    # 从签名末行往前找含 ) 的行
    for i in range(sig_end - 1, sig_start - 2, -1):
        if 0 <= i < len(lines) and ")" in lines[i]:
            line = lines[i]
            idx = line.rfind(")")
            before = line[:idx].rstrip()
            if before.endswith("("):
                lines[i] = before + "**kwargs" + line[idx:]
            elif before.endswith(","):
                lines[i] = before + " **kwargs" + line[idx:]
            else:
                lines[i] = before + ", **kwargs" + line[idx:]
            return "\n".join(lines)
    return func_code  # 找不到 )，放弃


def apply_partial_code(original_code: str, partial_code: str) -> str:
    """将部分代码（函数级修改）合并到原始脚本中。

    策略：
    1. 始终走函数级合并——同名函数替换，新函数插入 if __name__ 之前
    2. 不再做全量替换（避免 LLM 带 import 的多函数代码覆盖整个脚本）
    3. 原始脚本语法错误时回退为直接替换
    """
    partial_stripped = partial_code.strip()

    try:
        partial_tree = ast.parse(partial_stripped)
    except SyntaxError:
        return partial_stripped  # 语法错误，直接返回

    partial_top_defs = [n for n in ast.iter_child_nodes(partial_tree)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]

    # 函数级合并（不再全量替换）
    try:
        orig_tree = ast.parse(original_code)
    except SyntaxError:
        return partial_stripped  # 原始脚本语法错误，直接替换

    # 新函数是否有 **kwargs（防止 LLM 重写时丢失）
    new_kwargs_map = {}
    for node in partial_top_defs:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            new_kwargs_map[node.name] = node.args.kwarg is not None

    # 原函数是否有 **kwargs
    orig_kwargs_map = {}
    for node in ast.iter_child_nodes(orig_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            orig_kwargs_map[node.name] = node.args.kwarg is not None

    # 收集 partial 中的定义名 → 源代码片段（若旧有 **kwargs 新无 → 自动补回）
    partial_lines = partial_stripped.split("\n")
    replacements = {}
    for node in partial_top_defs:
        if hasattr(node, 'name'):
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, 'end_lineno') else start + 1
            code_seg = "\n".join(partial_lines[start:end])
            # 签名保护：旧函数有 **kwargs 但新函数丢了 → 补回（防 runner 传参 TypeError）
            if orig_kwargs_map.get(node.name) and not new_kwargs_map.get(node.name):
                code_seg = _ensure_var_kwargs(code_seg, node.name)
            replacements[node.name] = code_seg

    if not replacements:
        return partial_stripped  # 没有可替换的定义

    # 在原始代码中找到同名定义并替换
    orig_lines = original_code.split("\n")
    # 收集需要替换的行范围（从后往前替换，避免行号偏移）
    replace_ranges = []
    for node in ast.iter_child_nodes(orig_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in replacements:
                start = node.lineno - 1
                end = node.end_lineno if hasattr(node, 'end_lineno') else start + 1
                replace_ranges.append((start, end, node.name, replacements[node.name]))

    if not replace_ranges:
        # 原脚本中没有同名定义 → 在 if __name__ 之前插入（避免被 _strip_main_block 删除）
        insert_pos = _find_main_block_line(original_code)
        orig_lines = original_code.split("\n")
        orig_lines.insert(insert_pos, "\n\n" + partial_stripped + "\n")
        return "\n".join(orig_lines)

    # 从后往前替换
    replace_ranges.sort(key=lambda x: x[0], reverse=True)
    for start, end, name, new_code in replace_ranges:
        orig_lines[start:end] = [new_code]

    # 检查是否有新函数（非同名替换）需要插入到 if __name__ 之前
    replaced_names = {name for _, _, name, _ in replace_ranges}
    new_funcs = {name: code for name, code in replacements.items() if name not in replaced_names}
    if new_funcs:
        result = "\n".join(orig_lines)
        insert_pos = _find_main_block_line(result)
        result_lines = result.split("\n")
        new_block = "\n\n" + "\n\n".join(new_funcs.values()) + "\n"
        result_lines.insert(insert_pos, new_block)
        return "\n".join(result_lines)

    return "\n".join(orig_lines)


def apply_patch(original_code: str, old_string: str, new_string: str) -> dict:
    """行级补丁：在 original_code 中用 new_string 替换 old_string（必须唯一匹配）。

    对齐 OpenCode 的 edit 原语——小修改只产生小输出，避免整脚本重写导致截断。
    返回 {"success": bool, "code": str, "message": str}。
    匹配策略：① 精确字符串匹配（唯一）→ ② 逐行 strip 后的宽松匹配（容错缩进）。
    """
    if not old_string:
        return {"success": False, "message": "old_string 不能为空"}

    # 1. 精确匹配
    count = original_code.count(old_string)
    if count == 1:
        return {"success": True, "code": original_code.replace(old_string, new_string, 1),
                "message": "精确匹配替换成功"}
    if count > 1:
        return {"success": False,
                "message": f"old_string 在脚本中出现 {count} 次，不唯一。请补充更多上下文行使其唯一。"}

    # 2. 宽松匹配：逐行 strip 后比较（容错缩进/尾随空白）
    orig_lines = original_code.splitlines()
    old_lines = old_string.splitlines()
    if not old_lines or len(old_lines) > len(orig_lines):
        return {"success": False,
                "message": "old_string 未在脚本中找到（精确匹配失败）。请先调用 read_script 查看当前逐字内容。"}
    orig_stripped = [l.strip() for l in orig_lines]
    old_stripped = [l.strip() for l in old_lines]
    matches = []
    for i in range(len(orig_stripped) - len(old_stripped) + 1):
        if orig_stripped[i:i + len(old_stripped)] == old_stripped:
            matches.append(i)
    if len(matches) == 1:
        start = matches[0]
        end = start + len(old_lines)
        result_lines = orig_lines[:]
        result_lines[start:end] = new_string.splitlines()
        return {"success": True, "code": "\n".join(result_lines),
                "message": "宽松匹配（忽略行首尾空白）替换成功"}
    if len(matches) > 1:
        return {"success": False,
                "message": f"宽松匹配仍出现 {len(matches)} 次，不唯一。请补充更多上下文。"}
    return {"success": False,
            "message": "old_string 未在脚本中找到（精确与宽松匹配均失败）。请先调用 read_script 查看当前逐字内容。"}