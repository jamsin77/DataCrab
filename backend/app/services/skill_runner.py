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
import urllib.error
import pandas as pd

ALLOWED_IMPORTS = {{"pd": pd, "json": json, "numpy": __import__("numpy") if "numpy" in sys.modules else None}}

INJECTED_DATA = {injected_data}
INJECTED_PARAMS = {injected_params}
USES_ARGPARSE = {uses_argparse}
INJECTED_USER_ID = {user_id}

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

def _sanitize_nans(obj):
    import math
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {{k: _sanitize_nans(v) for k, v in obj.items()}}
    if isinstance(obj, list):
        return [_sanitize_nans(v) for v in obj]
    return obj

def _http_err(e):
    # 从 urllib HTTPError 中提取后端返回的实际错误信息
    try:
        body = e.read().decode("utf-8")
        import json as _j
        detail = _j.loads(body).get("detail") or _j.loads(body).get("error") or body
        return str(detail)
    except Exception:
        return str(e)

def _resolve_ds(datasource_id):
    # 数据源名称 → UUID（如果不是 UUID 格式则尝试解析）
    import re as _re
    if not _re.match(r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}', str(datasource_id)):
        _resolved = _dc_get_datasource_id_by_name(str(datasource_id))
        if _resolved:
            return _resolved
    return str(datasource_id)

def _dc_query_table_data(datasource_id, table_name, limit=1000, offset=0, order_by=None):
    print(f"[SkillRunner] query_table: ds={{datasource_id}}, table={{table_name}}, limit={{limit}}")
    import urllib.request, urllib.parse
    page = (offset // limit) + 1 if limit > 0 else 1
    _tn = urllib.parse.quote(str(table_name))
    _ds = urllib.parse.quote(str(datasource_id), safe='')
    url = f"http://localhost:8000/api/v1/datasources/internal/datasources/{{_ds}}/tables/{{_tn}}/data?page={{page}}&page_size={{limit}}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return pd.DataFrame(data.get("rows", []))
    except urllib.error.HTTPError as e:
        print(f"[SkillRunner] query failed: HTTP {{e.code}} {{_http_err(e)}}")
        return pd.DataFrame()
    except Exception as e:
        print(f"[SkillRunner] query failed: {{e}}")
        return pd.DataFrame()

def _dc_get_table_schema(datasource_id, table_name):
    import urllib.request, urllib.parse
    _ds = urllib.parse.quote(str(datasource_id), safe='')
    url = f"http://localhost:8000/api/v1/datasources/internal/datasources/{{_ds}}/schema"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("tables", [])
    except urllib.error.HTTPError as e:
        print(f"[SkillRunner] schema failed: HTTP {{e.code}} {{_http_err(e)}}")
        return []
    except Exception as e:
        print(f"[SkillRunner] schema failed: {{e}}")
        return []

def _dc_get_datasource_id_by_name(name):
    import urllib.request
    url = "http://localhost:8000/api/v1/datasources/internal/datasources"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            sources = json.loads(resp.read().decode("utf-8"))
        for s in sources:
            if s.get("name") == name:
                return s.get("id")
        return None
    except Exception as e:
        print(f"[SkillRunner] resolve datasource failed: {{e}}")
        return None

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
    # 在技能脚本中直接调用平台大模型（通过内部 HTTP 端点，自动使用当前用户的 LLM 配置）
    # prompt: 用户消息
    # system_prompt: 可选的系统提示词
    # temperature: 温度参数 (0.0-2.0)
    # max_tokens: 最大token数
    # 返回: 大模型的文本回复
    import urllib.request
    _payload = json.dumps({{"prompt": prompt, "system_prompt": system_prompt, "temperature": temperature, "max_tokens": int(max_tokens), "user_id": INJECTED_USER_ID}}).encode("utf-8")
    _req = urllib.request.Request("http://localhost:8000/api/v1/datasources/internal/llm/chat", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("content", "")
    except urllib.error.HTTPError as e:
        print(f"[SkillRunner] llm_chat failed: HTTP {{e.code}} {{_http_err(e)}}")
        return ""
    except Exception as e:
        print(f"[SkillRunner] llm_chat failed: {{e}}")
        return ""

def write_table_data(datasource_id, table_name, records=None, data=None, if_table_exists="fail", table_remark="", column_remarks=None, **extra):
    import re as _re
    if not _re.match(r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}', str(datasource_id)):
        _resolved = _dc_get_datasource_id_by_name(str(datasource_id))
        if _resolved:
            datasource_id = _resolved
    _records = data if data is not None else records
    import urllib.request, urllib.parse
    _kwargs = {{}}
    if if_table_exists and if_table_exists != "fail":
        _kwargs["if_table_exists"] = if_table_exists
    if table_remark:
        _kwargs["table_remark"] = table_remark
    if column_remarks:
        _kwargs["column_remarks"] = column_remarks
    _kwargs.update(extra)
    _payload = json.dumps({{"records": _sanitize_nans(_records or []), **_kwargs}}).encode("utf-8")
    _tn = urllib.parse.quote(str(table_name))
    _ds = urllib.parse.quote(str(datasource_id), safe='')
    _url = f"http://localhost:8000/api/v1/datasources/internal/datasources/{{_ds}}/tables/{{_tn}}/data"
    _req = urllib.request.Request(_url, data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] write_table_data failed: HTTP {{e.code}} {{_msg}}")
        return {{"success": False, "message": _msg}}
    except Exception as e:
        print(f"[SkillRunner] write_table_data failed: {{e}}")
        return {{"success": False, "message": str(e)}}

def log(level, message, *args):
    _lvl = str(level).upper() if level else "INFO"
    print(f"[{{_lvl}}] {{message}}" + (" " + " ".join(str(a) for a in args) if args else ""))

def list_tables(datasource_id):
    # 列出数据源中的所有表名
    # datasource_id: 数据源 UUID 或名称
    # 返回: list[str] 表名列表
    import re as _re
    if not _re.match(r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}', str(datasource_id)):
        _resolved = _dc_get_datasource_id_by_name(str(datasource_id))
        if _resolved:
            datasource_id = _resolved
    import urllib.request, urllib.parse
    _ds = urllib.parse.quote(str(datasource_id), safe='')
    _url = f"http://localhost:8000/api/v1/datasources/internal/datasources/{{_ds}}/tables"
    try:
        with urllib.request.urlopen(_url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("tables", [])
    except urllib.error.HTTPError as e:
        print(f"[SkillRunner] list_tables failed: HTTP {{e.code}} {{_http_err(e)}}")
        return []
    except Exception as e:
        print(f"[SkillRunner] list_tables failed: {{e}}")
        return []

def iter_table_data(datasource_id, table_name, chunk_size=10000):
    # 分块迭代读取大表数据（避免一次性加载到内存）
    # datasource_id: 数据源 UUID 或名称
    # table_name: 表名
    # chunk_size: 每块行数（默认 10000）
    # 返回: 生成器，每次 yield 一个 dict {{"columns": [...], "rows": [...], "page": int, "total": int, "has_next": bool}}
    import re as _re
    if not _re.match(r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}', str(datasource_id)):
        _resolved = _dc_get_datasource_id_by_name(str(datasource_id))
        if _resolved:
            datasource_id = _resolved
    import urllib.request, urllib.parse
    _tn = urllib.parse.quote(str(table_name))
    _ds = urllib.parse.quote(str(datasource_id), safe='')
    page = 1
    while True:
        _url = f"http://localhost:8000/api/v1/datasources/internal/datasources/{{_ds}}/tables/{{_tn}}/chunks?chunk_size={{chunk_size}}&page={{page}}"
        try:
            with urllib.request.urlopen(_url, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"[SkillRunner] iter_table_data page {{page}} failed: HTTP {{e.code}} {{_http_err(e)}}")
            break
        except Exception as e:
            print(f"[SkillRunner] iter_table_data page {{page}} failed: {{e}}")
            break
        yield data
        if not data.get("has_next", False):
            break
        page += 1

def execute_sql(datasource_id, sql, params=None, limit=10000):
    # 在数据源上执行 SQL（支持 JOIN/聚合/窗口函数等复杂查询）
    # datasource_id: 数据源 UUID 或名称
    # sql: SQL 语句（DB 型数据源原生 SQL）
    # limit: 最大返回行数（默认 10000）
    # 返回: dict {{"success": bool, "data": [行dict], "columns": [列名], "row_count": int}}
    import re as _re
    if not _re.match(r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}', str(datasource_id)):
        _resolved = _dc_get_datasource_id_by_name(str(datasource_id))
        if _resolved:
            datasource_id = _resolved
    import urllib.request, urllib.parse
    _payload = json.dumps({{"sql": sql, "limit": int(limit)}}).encode("utf-8")
    _ds = urllib.parse.quote(str(datasource_id), safe='')
    _url = f"http://localhost:8000/api/v1/datasources/internal/datasources/{{_ds}}/sql"
    _req = urllib.request.Request(_url, data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {{"success": True, "data": data.get("rows", []), "columns": data.get("columns", []), "row_count": data.get("row_count", 0)}}
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] execute_sql failed: HTTP {{e.code}} {{_msg}}")
        return {{"success": False, "data": [], "columns": [], "row_count": 0, "error": _msg}}
    except Exception as e:
        print(f"[SkillRunner] execute_sql failed: {{e}}")
        return {{"success": False, "data": [], "columns": [], "row_count": 0, "error": str(e)}}

def read_file(path, format=None):
    # 读取文件内容（自动检测格式，路径必须在文件链接授权目录内）
    # path: 文件路径（必须在用户已挂载的文件链接目录范围内）
    # format: 可选，强制指定格式（text/json/csv）
    # 返回: text→str, json→dict/list, csv/excel→dict {{"columns": [...], "rows": [...]}}
    import urllib.request
    _payload = json.dumps({{"path": path, "user_id": INJECTED_USER_ID}}).encode("utf-8")
    _req = urllib.request.Request("http://localhost:8000/api/v1/datasources/internal/files/read", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        fmt = data.get("format", "text")
        if fmt == "text":
            return data.get("content", "")
        elif fmt == "json":
            return data.get("content", {{}})
        elif fmt == "csv":
            return {{"columns": data.get("columns", []), "rows": data.get("rows", [])}}
        return data.get("content", "")
    except urllib.error.HTTPError as e:
        print(f"[SkillRunner] read_file failed: HTTP {{e.code}} {{_http_err(e)}}")
        return ""
    except Exception as e:
        print(f"[SkillRunner] read_file failed: {{e}}")
        return ""

def write_file(path, data, format=None):
    # 写入文件（路径必须在文件链接授权目录内）
    # path: 文件路径
    # data: 要写入的内容（str/dict/list）
    # format: 可选，强制指定格式
    # 返回: dict {{"success": bool, "path": str, "size": int}}
    import urllib.request
    _payload = json.dumps({{"path": path, "data": data, "format": format, "user_id": INJECTED_USER_ID}}, ensure_ascii=False).encode("utf-8")
    _req = urllib.request.Request("http://localhost:8000/api/v1/datasources/internal/files/write", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] write_file failed: HTTP {{e.code}} {{_msg}}")
        return {{"success": False, "error": _msg}}
    except Exception as e:
        print(f"[SkillRunner] write_file failed: {{e}}")
        return {{"success": False, "error": str(e)}}

def compute_map(fn, partitions, backend="local", **kwargs):
    # 对分块数据并行执行函数（分布式计算抽象）
    # fn: 处理函数，接收一个 partition，返回处理结果
    # partitions: 分块列表（通常来自 iter_table_data）
    # backend: "sequential"(顺序调试) / "local"(本机 multiprocessing 并行) / "ray"(分布式预留)
    # **kwargs: 如 workers=4
    # 返回: 结果列表，顺序与 partitions 一致
    #
    # 注意：技能沙箱在子进程中运行，multiprocessing 的 spawn 模式要求 fn 可被 pickle。
    # 如果 fn 是脚本中定义的局部函数，backend="local" 可能失败，此时自动降级为顺序执行。
    from app.services.compute_backend import compute_map as _cm
    return _cm(fn, partitions, backend=backend, **kwargs)

def llm_vision(image_path, prompt, system_prompt=None, temperature=0.3, max_tokens=2000):
    # 图片理解/OCR（发送图片到视觉大模型，返回文本）
    # image_path: 图片文件路径（必须在文件链接授权目录内）
    # prompt: 要问的问题，如"提取图片中的所有文字"或"描述图片内容"
    # system_prompt: 可选系统提示词
    # temperature: 温度（默认0.3，图片识别用低温度更准确）
    # max_tokens: 最大返回token数（默认2000）
    # 返回: str 大模型的文本回复
    import urllib.request
    _payload = json.dumps({{"image_path": image_path, "prompt": prompt, "system_prompt": system_prompt, "temperature": temperature, "max_tokens": int(max_tokens), "user_id": INJECTED_USER_ID}}, ensure_ascii=False).encode("utf-8")
    _req = urllib.request.Request("http://localhost:8000/api/v1/datasources/internal/llm/vision", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("content", "")
    except urllib.error.HTTPError as e:
        print(f"[SkillRunner] llm_vision failed: HTTP {{e.code}} {{_http_err(e)}}")
        return ""
    except Exception as e:
        print(f"[SkillRunner] llm_vision failed: {{e}}")
        return ""

# Inject into builtins so scripts using get_data_accessor() can find them
import builtins as _builtins
_builtins.get_table_data = get_table_data
_builtins.query_table_data = get_table_data
_builtins.write_table_data = write_table_data
_builtins.execute_sql = execute_sql
_builtins.list_tables = list_tables
_builtins.iter_table_data = iter_table_data
_builtins.read_file = read_file
_builtins.write_file = write_file
_builtins.compute_map = compute_map
_builtins.llm_vision = llm_vision
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
    user_id: str = None,
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

    runner_script = SKILL_RUNNER_TEMPLATE.format(
        injected_data=data_literal,
        injected_params=params_literal,
        function_name=function_name,
        uses_argparse=uses_argparse,
        user_id=repr(str(user_id) if user_id else None),
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
            env={**os.environ, "PYTHONPATH": str(backend_path), "PYTHONIOENCODING": "utf-8"},
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
    user_id: str = None,
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
            user_id=user_id,
        ),
    )