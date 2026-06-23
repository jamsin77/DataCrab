"""Pipeline Builder - 从 Skill 生成 Python 主函数"""

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.llm import llm_manager
from app.services.skill_parser import read_skill_md, read_skill_script, list_skill_scripts


PIPELINE_BUILDER_SYSTEM_PROMPT = """你是一个 Python 代码生成器，专门为 DataCrab 数据平台生成数据处理流程的主函数。

## 流程定义
流程（Pipeline）就是一个完整的 Python 主函数，它负责：
1. 从数据源读取数据（使用 ConnectorManager）
2. 调用 Skill 脚本中的函数处理数据
3. 将处理结果写回数据源

## 安全红线 🚫
- 流程只能处理用户的业务数据，绝不能修改 DataCrab 平台自身
- 不得生成访问或修改平台系统表（users, roles, permissions, data_sources等）的代码
- 不得生成修改平台源代码、配置文件的代码
- 如果用户要求修改平台本身，抛出 ValueError("不允许修改平台自身")
- 脚本中只能操作用户数据源的业务数据，不能操作平台系统数据

## 流程属于用户内容，可以自由创建和修改 ✅
- 用户可以自由创建、修改、执行、删除自己的流程
- 流程脚本可以查询和处理用户数据源中的业务数据
- 流程脚本可以使用 ConnectorManager 访问用户数据

## 修改后必验证 ✅
- 生成或修改流程代码后，必须在末尾包含 if __name__ == "__main__" 自测块
- 自测块中用示例数据调用 main 函数，验证流程能正常执行
- 如果自测失败，分析错误原因并提供修复方案

## 输出默认同源 📂
- 数据处理生成新文件时，如果用户未指定输出路径，默认保存到 DataSource（数据源）指定的文件路径下
- 流程的 main 函数应提供 output_dir 参数，默认值推断为 DataSource 文件所在目录
- 如果 DataSource 来自数据库而非文件，需要用户明确指定输出路径

## 输出格式（严格遵守）
只输出一个完整的 Python 文件，不要包含任何解释性文字。格式如下：

```python
'''
流程: {display_name}
描述: {description}
从 Skill 生成: {skill_name}
'''

import argparse
import json
import pandas as pd

from app.services.connectors import ConnectorManager


# === Skill 脚本函数（内联） ===
def _skill_main(df, **kwargs):
    '''Skill 主处理函数 - 从 scripts/main.py 内联'''
    ...


# === 主函数 ===
def main(datasource_name, table_name, **kwargs):
    '''
    流程主函数
    
    Args:
        datasource_name: 数据源名称
        table_name: 表名
        **kwargs: 其他处理参数
    '''
    cm = ConnectorManager()
    
    # 1. 读取数据
    data = cm.read_table(datasource_name, table_name)
    df = pd.DataFrame(data["rows"], columns=data["columns"])
    
    # 2. 调用 Skill 脚本处理
    result_df = _skill_main(df, **kwargs)
    
    # 3. 写入结果
    cm.write_table(datasource_name, table_name, result_df)
    
    return result_df


# === 命令行入口 ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="流程: {display_name}")
    parser.add_argument("datasource_name", type=str, help="数据源名称")
    parser.add_argument("table_name", type=str, help="表名")
    parser.add_argument("--params", type=str, default="{}", help="JSON格式的额外参数")
    
    args = parser.parse_args()
    extra = json.loads(args.params)
    
    result = main(args.datasource_name, args.table_name, **extra)
    print(result)
```

## 规则
1. 必须使用 ConnectorManager.read_table() 读数据，write_table() 写数据
2. 数据源参数用名称（ConnectorManager 内部自动解析为 UUID）
3. Skill 脚本中的函数内联到主文件中，函数名加 _skill_ 前缀避免冲突
4. 保留 Skill 脚本的完整业务逻辑，不要简化
5. 处理边界情况（空表返回、列不存在等）
6. 函数签名和参数使用类型注解
7. 使用 print() 输出处理进度"""


async def build_pipeline_from_skill(skill_path_str: str, skill_id: str, skill_name: str, skill_display_name: str) -> Dict[str, Any]:
    """从 Skill 生成 Pipeline 主函数"""
    await llm_manager.initialize()

    skill_path = Path(skill_path_str)

    skill_md = read_skill_md(skill_path) or ""
    scripts = {}
    for script_info in list_skill_scripts(skill_path):
        name = script_info["name"] if isinstance(script_info, dict) else script_info
        content = script_info.get("content") if isinstance(script_info, dict) else read_skill_script(skill_path, script_info)
        scripts[name] = content

    params_info = _extract_skill_params(skill_md)
    scripts_text = ""
    for name, content in scripts.items():
        scripts_text += f"\n### scripts/{name}\n```python\n{content}\n```\n"

    user_prompt = f"""请根据以下 Skill 信息生成一个完整的 Python 流程主函数。

## Skill 信息
- 名称: {skill_name}
- 显示名称: {skill_display_name}
- 参数: {params_info}

## SKILL.md 内容
{skill_md[:3000]}

## 脚本内容
{scripts_text[:8000]}

请生成完整的 Python 主函数文件。"""

    full_response = ""
    async for chunk in llm_manager.chat_stream_with_messages(
        messages=[
            {"role": "system", "content": PIPELINE_BUILDER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    ):
        full_response += chunk

    main_code = _extract_python_code(full_response)
    skill_calls = _analyze_skill_calls(main_code, skill_id, skill_name)
    params = _extract_main_params(main_code)

    return {
        "main_code": main_code,
        "entry_function": "main",
        "parameters": params,
        "skill_calls": skill_calls,
    }


def _extract_python_code(raw: str) -> str:
    """从 LLM 响应中提取 Python 代码块"""
    if "```python" in raw:
        start = raw.index("```python") + 10
        end = raw.rindex("```")
        return raw[start:end].strip()
    if "```" in raw:
        parts = raw.split("```")
        for i in range(1, len(parts), 2):
            if "import" in parts[i] or "def " in parts[i]:
                return parts[i].strip()
    return raw.strip()


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
    """AST 提取 main 函数的参数定义"""
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                params = []
                for arg in node.args.args:
                    params.append({
                        "name": arg.arg,
                        "type": _annotation_to_str(arg.annotation),
                        "required": True,
                        "description": "",
                    })
                for arg in node.args.kwonlyargs:
                    params.append({
                        "name": arg.arg,
                        "type": _annotation_to_str(arg.annotation),
                        "required": False,
                        "description": "",
                    })
                if node.args.vararg:
                    params.append({
                        "name": f"*{node.args.vararg.arg}",
                        "type": "tuple",
                        "required": False,
                        "description": "",
                    })
                if node.args.kwarg:
                    params.append({
                        "name": f"**{node.args.kwarg.arg}",
                        "type": "dict",
                        "required": False,
                        "description": "",
                    })
                return params
    except SyntaxError:
        pass
    return []


def _annotation_to_str(ann) -> str:
    if ann is None:
        return "any"
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Constant):
        return str(ann.value)
    return "any"


def _extract_skill_params(skill_md: str) -> str:
    """从 SKILL.md 中提取参数表格文本"""
    lines = skill_md.split("\n")
    in_table = False
    params = []
    for line in lines:
        if "|" in line and ("参数" in line or "类型" in line or "必填" in line):
            in_table = True
            continue
        if in_table:
            if "|" in line and not line.strip().startswith("#"):
                params.append(line.strip())
            else:
                break
    return "\n".join(params) if params else "无参数定义"
