"""Skill Runner - 沙箱执行 Skill 脚本"""

import asyncio
import json
import math
import os
import sys
import time
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from app.core.config import settings


def _sanitize_nans(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nans(v) for v in obj]
    return obj

def _strip_main_block(script_content: str) -> str:
    """去掉脚本中 if __name__ == '__main__': 块，避免与模板的 __main__ 块冲突"""
    import re
    pattern = r'\nif\s+__name__\s*==\s*["\']__main__["\']\s*:.*'
    return re.sub(pattern, '', script_content, flags=re.DOTALL)


SKILL_RUNNER_TEMPLATE = """
import json
import sys
import traceback
import pandas as pd

ALLOWED_IMPORTS = {{"pd": pd, "json": json, "numpy": __import__("numpy") if "numpy" in sys.modules else None}}

INJECTED_DATA = {injected_data}
INJECTED_PARAMS = {injected_params}
USES_ARGPARSE = {uses_argparse}

def _get_input():
    if INJECTED_DATA is not None:
        if isinstance(INJECTED_DATA, list):
            return pd.DataFrame(INJECTED_DATA)
        elif isinstance(INJECTED_DATA, dict):
            return pd.DataFrame([INJECTED_DATA])
        return INJECTED_DATA
    return None

def _get_params():
    return INJECTED_PARAMS

def _build_argv_from_params(params):
    argv = [sys.argv[0]] if sys.argv else ["script"]
    for key, val in params.items():
        k = key if key.startswith("--") else "--" + key
        if isinstance(val, bool):
            if val:
                argv.append(k)
        elif isinstance(val, list):
            argv.append(k)
            for v in val:
                argv.append(str(v))
        else:
            argv.append(k)
            argv.append(str(val))
    return argv

def _run_async_query(script_code):
    import subprocess, sys
    proc = subprocess.run(
        [sys.executable, "-c", script_code],
        capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
        cwd=r"{cwd}"
    )
    output_lines = [l for l in proc.stdout.strip().split("\\n") if l.strip()]
    if output_lines:
        try:
            return json.loads(output_lines[-1])
        except:
            pass
    return None

def _sanitize_nans(obj):
    import math
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {{k: _sanitize_nans(v) for k, v in obj.items()}}
    if isinstance(obj, list):
        return [_sanitize_nans(v) for v in obj]
    return obj

def _dc_query_table_data(datasource_id, table_name, limit=1000, offset=0, order_by=None):
    print(f"[SkillRunner] query_table: ds={{datasource_id}}, table={{table_name}}, limit={{limit}}")
    code = (
        "import asyncio, json, sys\\n"
        "sys.path.insert(0, r'{backend_path}')\\n"
        "from app.core.database import async_session\\n"
        "from app.services.connectors import get_connector_manager\\n"
        "\\n"
        "async def _q():\\n"
        "    async with async_session() as session:\\n"
        "        mgr = get_connector_manager(session)\\n"
        "        result = await mgr.query_table('{{ds_id}}', '{{tbl}}', {{lim}}, {{off}}, '{{ord}}')\\n"
        "        if result is not None:\\n"
        "            return result.to_dict(orient='records')\\n"
        "    return None\\n"
        "\\n"
        "r = asyncio.run(_q())\\n"
        "print(json.dumps(r or []))\\n"
    ).format(ds_id=datasource_id, tbl=table_name, lim=limit, off=offset, ord=order_by or '')
    data = _run_async_query(code)
    if data:
        return pd.DataFrame(data)
    return pd.DataFrame()

def _dc_get_table_schema(datasource_id, table_name):
    code = (
        "import asyncio, json, sys\\n"
        "sys.path.insert(0, r'{backend_path}')\\n"
        "from app.core.database import async_session\\n"
        "from app.services.connectors import get_connector_manager\\n"
        "\\n"
        "async def _q():\\n"
        "    async with async_session() as session:\\n"
        "        mgr = get_connector_manager(session)\\n"
        "        return await mgr.get_table_schema('{{ds_id}}', '{{tbl}}')\\n"
        "\\n"
        "r = asyncio.run(_q())\\n"
        "print(json.dumps(r or {{{{}}}}))\\n"
    ).format(ds_id=datasource_id, tbl=table_name)
    data = _run_async_query(code)
    return data if data else {{"columns": [], "row_count": 0}}

def _dc_get_datasource_id_by_name(name):
    code = (
        "import asyncio, json, sys\\n"
        "sys.path.insert(0, r'{backend_path}')\\n"
        "from app.core.database import async_session\\n"
        "from app.services.connectors import get_connector_manager\\n"
        "\\n"
        "async def _q():\\n"
        "    async with async_session() as session:\\n"
        "        mgr = get_connector_manager(session)\\n"
        "        sources = await mgr.list_datasources()\\n"
        "        for s in sources:\\n"
        "            if s.get('name') == '{{nm}}' or s.get('display_name') == '{{nm}}':\\n"
        "                return s.get('id')\\n"
        "    return None\\n"
        "\\n"
        "r = asyncio.run(_q())\\n"
        "print(json.dumps(r))\\n"
    ).format(nm=name)
    data = _run_async_query(code)
    return data

def get_table_data(datasource_id, table_name, limit=1000, offset=0):
    import re as _re
    if not _re.match(r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}', str(datasource_id)):
        _resolved = _dc_get_datasource_id_by_name(str(datasource_id))
        if _resolved:
            datasource_id = _resolved
    df = _dc_query_table_data(datasource_id, table_name, limit, offset)
    return {{"success": True, "data": df.to_dict(orient="records"), "columns": list(df.columns), "row_count": len(df)}}

query_table_data = get_table_data

def llm_chat(prompt, system_prompt=None, temperature=0.7, max_tokens=2000):
    # 在技能脚本中直接调用平台大模型
    # prompt: 用户消息
    # system_prompt: 可选的系统提示词
    # temperature: 温度参数 (0.0-2.0)
    # max_tokens: 最大token数
    # 返回: 大模型的文本回复
    import json as _json
    _bp = r'{backend_path}'
    _payload = _json.dumps({{"prompt": prompt, "system_prompt": system_prompt, "temperature": temperature, "max_tokens": int(max_tokens)}}, ensure_ascii=False)
    _runner = (
        "import asyncio, json, sys\\n"
        "sys.path.insert(0, r'" + _bp + "')\\n"
        "from app.services.llm import llm_manager\\n"
        "\\n"
        "_payload = " + repr(_payload) + "\\n"
        "_cfg = json.loads(_payload)\\n"
        "\\n"
        "async def _q():\\n"
        "    await llm_manager.initialize()\\n"
        "    messages = []\\n"
        "    if _cfg['system_prompt']:\\n"
        "        messages.append({{'role': 'system', 'content': _cfg['system_prompt']}})\\n"
        "    messages.append({{'role': 'user', 'content': _cfg['prompt']}})\\n"
        "    if len(messages) > 1:\\n"
        "        return await llm_manager.chat_with_messages(messages, temperature=_cfg['temperature'], max_tokens=_cfg['max_tokens'])\\n"
        "    return await llm_manager.chat(_cfg['prompt'], temperature=_cfg['temperature'], max_tokens=_cfg['max_tokens'])\\n"
        "\\n"
        "r = asyncio.run(_q())\\n"
        "print(json.dumps(r, ensure_ascii=False))\\n"
    )
    result = _run_async_query(_runner)
    if result is not None:
        return result
    return ""

def write_table_data(datasource_id, table_name, records=None, data=None, if_table_exists="fail", table_remark="", column_remarks=None, **extra):
    import re as _re
    if not _re.match(r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}', str(datasource_id)):
        _resolved = _dc_get_datasource_id_by_name(str(datasource_id))
        if _resolved:
            datasource_id = _resolved
    _records = data if data is not None else records
    import json as _json, subprocess, sys as _sys, tempfile as _tf, os as _os

    # 将额外参数序列化，通过临时文件传递
    _kwargs = {{}}
    if if_table_exists and if_table_exists != "fail":
        _kwargs["if_table_exists"] = if_table_exists
    if table_remark:
        _kwargs["table_remark"] = table_remark
    if column_remarks:
        _kwargs["column_remarks"] = column_remarks
    _kwargs.update(extra)
    _extra = _json.dumps(_sanitize_nans(_kwargs), ensure_ascii=False)
    _tmp = _tf.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    _tmp.write(_json.dumps(_sanitize_nans(_records), ensure_ascii=False))
    _tmp.close()
    _tmp_extra = _tf.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    _tmp_extra.write(_extra)
    _tmp_extra.close()
    try:
        code = (
            "import asyncio, json, sys, os\\n"
            "sys.path.insert(0, r'{backend_path}')\\n"
            "from app.core.database import async_session\\n"
            "from app.services.connectors import get_connector_manager\\n"
            "\\n"
            "async def _q():\\n"
            "    with open(r'{{tmp_path}}', encoding='utf-8') as _f:\\n"
            "        _records = json.load(_f)\\n"
            "    with open(r'{{tmp_extra}}', encoding='utf-8') as _f2:\\n"
            "        _kwargs = json.load(_f2)\\n"
            "    async with async_session() as session:\\n"
            "        mgr = get_connector_manager(session)\\n"
            "        return await mgr.write_table('{{ds_id}}', '{{tbl}}', _records, **_kwargs)\\n"
            "\\n"
            "result = asyncio.run(_q())\\n"
            "print(json.dumps(result or {{{{}}}}))\\n"
            "os.unlink(r'{{tmp_path}}')\\n"
            "os.unlink(r'{{tmp_extra}}')\\n"
        ).format(ds_id=datasource_id, tbl=table_name, tmp_path=_tmp.name.replace('\\\\', '/'), tmp_extra=_tmp_extra.name.replace('\\\\', '/'))
        _result = _run_async_query(code)
    finally:
        try:
            _os.unlink(_tmp.name)
        except OSError:
            pass
        try:
            _os.unlink(_tmp_extra.name)
        except OSError:
            pass
    return _result if _result else {{"success": False, "message": "write failed"}}

def log(level, message, *args):
    _lvl = str(level).upper() if level else "INFO"
    print(f"[{{_lvl}}] {{message}}" + (" " + " ".join(str(a) for a in args) if args else ""))

# Inject into builtins so scripts using get_data_accessor() can find them
import builtins as _builtins
_builtins.get_table_data = get_table_data
_builtins.query_table_data = get_table_data
_builtins.write_table_data = write_table_data
_builtins.llm_chat = llm_chat
_builtins.log = log
_builtins.get_datasource_id_by_name = _dc_get_datasource_id_by_name
_builtins.get_table_schema = _dc_get_table_schema

# __SCRIPT_CONTENT__

if __name__ == "__main__":
    input_data = _get_input()
    params = _get_params()
    if USES_ARGPARSE:
        import sys as _sys
        _argv = _build_argv_from_params(params)
        _sys.argv = _argv
        main()
    else:
        result = {function_name}(input_data, **params) if input_data is not None else {function_name}(**params)
        if result is not None:
            if hasattr(result, "to_dict"):
                print("__RESULT__" + json.dumps(_sanitize_nans(result.to_dict(orient="records")), ensure_ascii=False, default=str))
            elif isinstance(result, dict):
                serializable = {{}}
                for k, v in result.items():
                    if hasattr(v, "to_dict"):
                        serializable[k] = _sanitize_nans(v.to_dict(orient="records"))
                    else:
                        serializable[k] = _sanitize_nans(v)
                print("__RESULT__" + json.dumps(serializable, ensure_ascii=False, default=str))
            elif isinstance(result, list):
                print("__RESULT__" + json.dumps(_sanitize_nans(result), ensure_ascii=False, default=str))
            else:
                print("__RESULT__" + json.dumps({{"value": str(result)}}, ensure_ascii=False))
"""


def run_skill_script(
    skill_path: Path,
    script_name: str = "main.py",
    parameters: Dict[str, Any] = None,
    input_data: Any = None,
    datasource_id: str = None,
    table_name: str = None,
    datasource_name: str = None,
    timeout: int = None,
) -> Dict[str, Any]:
    """在沙箱中执行 Skill 脚本"""
    timeout = timeout or settings.SKILL_RUNNER_TIMEOUT
    parameters = parameters or {}
    script_path = skill_path / "scripts" / script_name

    if not script_path.exists():
        return {
            "success": False,
            "error": f"脚本不存在: {script_path}",
            "stdout": "",
            "execution_time_ms": 0,
        }

    script_content = script_path.read_text(encoding="utf-8")

    import ast
    function_name = "main"
    uses_argparse = False
    try:
        tree = ast.parse(script_content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "argparse":
                        uses_argparse = True
                        break
            elif isinstance(node, ast.ImportFrom):
                if node.module == "argparse":
                    uses_argparse = True
        if not uses_argparse:
            func_defs = [(node.name, node) for node in ast.iter_child_nodes(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")]
            if func_defs:
                def _param_count(func_node):
                    return len(func_node.args.args) + len(func_node.args.kwonlyargs) + len(func_node.args.posonlyargs)
                best = max(func_defs, key=lambda f: _param_count(f[1]))
                if "main" in [f[0] for f in func_defs]:
                    main_node = next(f[1] for f in func_defs if f[0] == "main")
                    if _param_count(main_node) > 0:
                        function_name = "main"
                    else:
                        function_name = best[0]
                else:
                    function_name = best[0]
        if uses_argparse:
            logger.info(f"检测到 argparse 脚本，将参数转为命令行格式")
    except SyntaxError:
        pass

    if uses_argparse:
        script_content = _strip_main_block(script_content)
        function_name = "main"

    if datasource_id and "datasource" not in parameters and "datasource_id" not in parameters:
        if uses_argparse and datasource_name:
            parameters["datasource"] = datasource_name
        else:
            parameters["datasource"] = datasource_id
    if table_name and "tables" not in parameters and "table" not in parameters and "table_name" not in parameters and "table_names" not in parameters:
        if uses_argparse:
            parameters["tables"] = [table_name]
            parameters["table_names"] = [table_name]
        else:
            parameters["table_name"] = table_name

    data_literal = repr(input_data) if input_data is not None else "None"
    params_literal = repr(parameters)

    backend_path = Path(__file__).resolve().parent.parent.parent
    cwd = str(Path.cwd())
    backend_path_str = str(backend_path).replace("\\", "/")
    cwd_str = cwd.replace("\\", "/")

    runner_script = SKILL_RUNNER_TEMPLATE.format(
        injected_data=data_literal,
        injected_params=params_literal,
        function_name=function_name,
        uses_argparse=uses_argparse,
        backend_path=backend_path_str,
        cwd=cwd_str,
    )
    runner_script = runner_script.replace("# __SCRIPT_CONTENT__", script_content)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(runner_script)
        temp_path = f.name

    try:
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(skill_path),
            env={**os.environ, "PYTHONPATH": str(backend_path)},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        if proc.returncode != 0:
            error_msg = stderr.strip() or stdout.strip()[:500] or "脚本执行失败（无错误输出）"
        else:
            error_msg = None

        if stderr.strip() and proc.returncode == 0:
            stdout += "\n[stderr]\n" + stderr

        result = None
        for line in stdout.split("\n"):
            if "__RESULT__" in line:
                try:
                    json_str = line.split("__RESULT__", 1)[1].strip()
                    result = json.loads(json_str)
                    result = _sanitize_nans(result)
                    stdout = stdout.replace(line, "")
                except json.JSONDecodeError:
                    pass
                break

        return {
            "success": proc.returncode == 0,
            "result": result,
            "error": error_msg,
            "stdout": stdout.strip(),
            "execution_time_ms": round(elapsed_ms, 2),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"脚本执行超时（{timeout}秒）",
            "stdout": "",
            "execution_time_ms": timeout * 1000,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "execution_time_ms": 0,
        }
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass


async def run_skill_script_async(
    skill_path: Path,
    script_name: str = "main.py",
    parameters: Dict[str, Any] = None,
    input_data: Any = None,
    datasource_id: str = None,
    table_name: str = None,
    datasource_name: str = None,
    timeout: int = None,
) -> Dict[str, Any]:
    """异步执行 Skill 脚本，委托给同步版本以避免 Windows 上的 NotImplementedError"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_skill_script(
            skill_path=skill_path,
            script_name=script_name,
            parameters=parameters,
            input_data=input_data,
            datasource_id=datasource_id,
            table_name=table_name,
            datasource_name=datasource_name,
            timeout=timeout,
        ),
    )