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