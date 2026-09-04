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
from typing import Any, Dict

from loguru import logger

from app.core.config import settings

# 沙箱并发数限制（最多同时执行 3 个脚本，防止资源争抢）
SANDBOX_MAX_CONCURRENCY = 3
sandbox_semaphore = None  # 延迟初始化（需要 event loop）


def _get_sandbox_semaphore():
    global sandbox_semaphore
    if sandbox_semaphore is None:
        sandbox_semaphore = asyncio.Semaphore(SANDBOX_MAX_CONCURRENCY)
    return sandbox_semaphore


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





import re as _re


def _fix_traceback_lines(error_msg: str, preamble_lines: int) -> str:
    """修正 traceback 中的行号：临时文件行号 → 原始脚本行号。

    子进程临时文件 = 模板前缀（preamble_lines 行）+ 脚本内容 + 模板后缀。
    traceback 中的 line N → 原始脚本 line (N - preamble_lines)。
    """
    if preamble_lines <= 0:
        return error_msg

    def _replace_line(match):
        prefix = match.group(1)  # 'line '
        num = int(match.group(2))
        fixed = num - preamble_lines
        if fixed > 0:
            return f"{prefix}{fixed}"
        return match.group(0)

    # 匹配 traceback 中的 "line 123" 模式
    return _re.sub(r'(line\s+)(\d+)', _replace_line, error_msg)


def _extract_exception_type(error_msg: str) -> str:
    """从 Python traceback 提取异常类型名（最后一行）。

    traceback 最后一行格式：ExceptionType: message 或 ExceptionType
    返回空串表示提取失败（按脚本错误处理，让 LLM 修复）。
    """
    if not error_msg:
        return ""
    lines = [l.strip() for l in error_msg.strip().splitlines() if l.strip()]
    if not lines:
        return ""
    last = lines[-1]
    exc_type = last.split(":", 1)[0].strip()
    if not exc_type:
        return ""
    if not (exc_type[0].isalpha() or exc_type[0] == "_"):
        return ""
    if not exc_type[1:].replace("_", "").isalnum():
        return ""
    return exc_type


SKILL_RUNNER_TEMPLATE = """
import json
import sys
import os
import traceback
import urllib.error
import pandas as pd

_API_BASE = os.environ.get("DATACRAB_API_BASE", "http://localhost:8000")

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
    try:
        body = e.read().decode("utf-8")
        import json as _j
        detail = _j.loads(body).get("detail") or _j.loads(body).get("error") or body
        return str(detail)
    except Exception:
        return str(e)

# ==================== 统一工具调用入口 ====================

# 在安装 hook 前先缓存需要的模块引用（hook 安装后不能再 import os/urllib）
import os as _os_mod
import urllib.request as _urllib_req
import urllib.error as _urllib_err

def call_tool(tool_name, **args):
    '''统一工具调用入口：通过 HTTP 调 /internal/execute-tool 端点。
    所有数据操作（查询/写入/SQL/LLM/文件/视频）都通过此函数调用。
    返回 dict，具体格式见各工具的 JSON Schema。'''
    _payload = json.dumps({{"tool_name": tool_name, "args": args, "user_id": INJECTED_USER_ID}}, ensure_ascii=False, default=str).encode("utf-8")
    _req = _urllib_req.Request(
        f"{{_API_BASE}}/api/v1/datasources/internal/execute-tool",
        data=_payload,
        headers={{"Content-Type": "application/json"}},
        method="POST",
    )
    print(f"[SkillRunner] call_tool: {{tool_name}}")
    try:
        with _urllib_req.urlopen(_req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    except _urllib_err.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] call_tool({{tool_name}}) failed: HTTP {{e.code}} {{_msg}}")
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] call_tool({{tool_name}}) failed: {{e}}")
        raise

# ==================== 沙箱安全：__import__ hook + open() 限制 ====================

import builtins as _builtins

_BLOCKED_MODULES = frozenset({{
    "os", "sys", "subprocess", "shutil", "ctypes",
    "sqlite3", "psycopg2", "pymysql", "asyncpg", "sqlalchemy",
    "socket", "http", "http.client", "urllib",
    "multiprocessing", "signal", "gc",
    "importlib", "builtins",
    "app",
}})

_orig_import = _builtins.__import__

def _sandbox_import(name, globals=None, locals=None, fromlist=(), level=0):
    _top = name.split(".")[0]
    if _top in _BLOCKED_MODULES:
        raise ImportError(f"沙箱禁止导入: {{name}}（如需数据操作请使用 call_tool）")
    return _orig_import(name, globals, locals, fromlist, level)

_builtins.__import__ = _sandbox_import

_SANDBOX_CWD = _os_mod.path.abspath(".")
_SANDBOX_ALLOWED_DIRS = []
try:
    _dirs_json = _os_mod.environ.get("SANDBOX_ALLOWED_DIRS", "")
    if _dirs_json:
        _SANDBOX_ALLOWED_DIRS = json.loads(_dirs_json)
except Exception:
    pass

_orig_open = _builtins.open

def _sandbox_open(file, mode="r", *args, **kwargs):
    _path = _os_mod.path.abspath(str(file))
    if _path.startswith(_SANDBOX_CWD):
        return _orig_open(file, mode, *args, **kwargs)
    for _d in _SANDBOX_ALLOWED_DIRS:
        if _path.startswith(_os_mod.path.abspath(_d)):
            return _orig_open(file, mode, *args, **kwargs)
    raise PermissionError(f"沙箱禁止访问目录外文件: {{file}}")

_builtins.open = _sandbox_open
_builtins.call_tool = call_tool

# ==================== 工具调用日志 ====================

_TOOL_CALL_LOG = []

_orig_call_tool = call_tool

def _logged_call_tool(tool_name, **args):
    import time as _time
    _start = _time.time()
    try:
        _result = _orig_call_tool(tool_name, **args)
        _success = True
        _message = ""
        if isinstance(_result, dict):
            _success = _result.get("success", True)
            _message = _result.get("message", "") or _result.get("error", "")
        _log_entry = {{
            "tool": tool_name,
            "success": _success,
            "message": str(_message)[:300] if _message else "",
            "elapsed_ms": round((_time.time() - _start) * 1000, 2),
        }}
        # 记录 write_table_data 的目标表信息（供 RunTime handoff Inspector 用）
        if tool_name == "write_table_data" and _success:
            _log_entry["datasource_id"] = args.get("datasource_id", "")
            _log_entry["table_name"] = args.get("table_name", "")
        _TOOL_CALL_LOG.append(_log_entry)
        return _result
    except Exception as _e:
        _TOOL_CALL_LOG.append({{
            "tool": tool_name,
            "success": False,
            "message": str(_e)[:300],
            "elapsed_ms": round((_time.time() - _start) * 1000, 2),
        }})
        raise

_builtins.call_tool = _logged_call_tool

# atexit 确保脚本崩溃时也输出 tool_call_log
import atexit as _atexit
def _print_tool_call_log():
    if _TOOL_CALL_LOG:
        print("__TOOL_CALL_LOG__" + json.dumps(_sanitize_nans(_TOOL_CALL_LOG), ensure_ascii=False, default=str))
_atexit.register(_print_tool_call_log)

# __SCRIPT_CONTENT__

if __name__ == "__main__":
    input_data = _get_input()
    params = _get_params()
    if USES_ARGPARSE:
        import sys as _sys
        _argv = _build_argv_from_params(params)
        _sys.argv = _argv
        for _k, _v in params.items():
            globals()[_k] = _v
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
        # 检查是否有写入表记录（通过 call_tool 的 write_table_data 返回值追踪）
        # _WRITTEN_TABLES 由 handler 侧管理，通过 result 返回
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
    """在沙箱中执行 Skill 脚本（委托给流式版本，丢弃进度，只返回结果）"""
    for item in run_skill_script_streaming(
        skill_path=skill_path,
        script_name=script_name,
        parameters=parameters,
        input_data=input_data,
        datasource_id=datasource_id,
        table_name=table_name,
        datasource_name=datasource_name,
        timeout=timeout,
        user_id=user_id,
    ):
        if item.get("type") == "result":
            return item["result"]
    return {"success": False, "error": "执行无结果返回", "stdout": "", "execution_time_ms": 0}


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
    async with _get_sandbox_semaphore():
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
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
        return result


_MARKER_PREFIXES = ("__RESULT__", "__TOOL_CALL_LOG__")


def _detect_entry_function(script_content: str) -> tuple:
    """AST 分析脚本内容，返回 (function_name, uses_argparse)。"""
    import ast as _ast
    function_name = "main"
    uses_argparse = False
    try:
        tree = _ast.parse(script_content)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    if alias.name == "argparse":
                        uses_argparse = True
                        break
            elif isinstance(node, _ast.ImportFrom):
                if node.module == "argparse":
                    uses_argparse = True
        if not uses_argparse:
            func_defs = [(n.name, n) for n in _ast.iter_child_nodes(tree) if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and not n.name.startswith("_")]
            if func_defs:
                def _param_count(fn):
                    return len(fn.args.args) + len(fn.args.kwonlyargs) + len(fn.args.posonlyargs) + (1 if fn.args.vararg else 0) + (1 if fn.args.kwarg else 0)
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
            function_name = "main"
    except SyntaxError:
        pass
    return function_name, uses_argparse


def _stream_execute(proc, timeout: int, temp_path: str, sandbox_cwd: str = None):
    """共享的流式执行核心：读取子进程 stdout，yield progress，最后 yield result。
    负责：超时检测（idle + 硬上限双层）、标记行解析、错误分类、临时文件清理。

    双层 timeout：
    - idle timeout（timeout 参数，默认 300s）：无输出超过此时长 → 杀进程。
      脚本持续 print/log 进度时不会触发，适合大数据处理场景。
    - 硬上限（SKILL_RUNNER_MAX_TIMEOUT，默认 1800s）：无论是否有输出，总时长超此上限 → 杀进程。
      防止脚本无限续命。
    """
    stdout_lines = []
    tool_failures = []  # 收集 [SkillRunner] xxx failed 行（脚本 try-except 吞异常时仍可检测）
    result = None
    tool_call_log = None
    _stdout_truncated = False
    _MAX_STDOUT_LINES = 5000
    _MAX_STDOUT_BYTES = 5_000_000  # 5MB

    try:
        import subprocess as _sp
        import threading as _threading
        import queue as _queue

        start = time.perf_counter()
        _idle_timeout = timeout
        _hard_cap = settings.SKILL_RUNNER_MAX_TIMEOUT
        _last_output = start
        _timeout_reason = None

        _line_q: _queue.Queue = _queue.Queue()

        def _stdout_reader():
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    _line_q.put(line.rstrip("\n\r"))
            except Exception:
                pass
            finally:
                _line_q.put(None)

        # stderr 也用线程读，避免 PIPE 缓冲区满导致死锁（进程 stderr.write 阻塞 → 不再输出 stdout → idle timeout → kill → stderr 丢失）
        _stderr_lines: list = []
        def _stderr_reader():
            try:
                while True:
                    line = proc.stderr.readline()
                    if not line:
                        break
                    _stderr_lines.append(line)
            except Exception:
                pass

        _reader_thread = _threading.Thread(target=_stdout_reader, daemon=True)
        _reader_thread.start()
        _stderr_thread = _threading.Thread(target=_stderr_reader, daemon=True)
        _stderr_thread.start()

        _timed_out = False
        while True:
            try:
                line = _line_q.get(timeout=1.0)
            except _queue.Empty:
                _now = time.perf_counter()
                if _now - _last_output >= _idle_timeout:
                    _timed_out = True
                    _timeout_reason = "idle"
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except _sp.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
                if _now - start >= _hard_cap:
                    _timed_out = True
                    _timeout_reason = "hard_cap"
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except _sp.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
                continue
            if line is None:
                break
            if not line:
                continue
            _last_output = time.perf_counter()
            is_marker = False
            for marker in _MARKER_PREFIXES:
                if marker in line:
                    is_marker = True
                    try:
                        json_str = line.split(marker, 1)[1].strip()
                        parsed = json.loads(json_str)
                        if marker == "__RESULT__":
                            result = _sanitize_nans(parsed)
                        elif marker == "__TOOL_CALL_LOG__":
                            tool_call_log = parsed
                    except (json.JSONDecodeError, IndexError):
                        pass
                    break
            if is_marker:
                continue
            if not _stdout_truncated and (len(stdout_lines) >= _MAX_STDOUT_LINES or sum(len(l) for l in stdout_lines) >= _MAX_STDOUT_BYTES):
                stdout_lines.append("[stdout 已截断，超过上限]")
                _stdout_truncated = True
                continue
            if not _stdout_truncated:
                stdout_lines.append(line)
            if "[SkillRunner]" in line and "failed" in line.lower():
                tool_failures.append(line)
            if not _stdout_truncated:
                yield {"type": "progress", "message": line}

        if not _timed_out:
            remaining = _hard_cap - (time.perf_counter() - start)
            if remaining <= 0:
                remaining = 1
            try:
                proc.wait(timeout=remaining)
            except _sp.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except _sp.TimeoutExpired:
                    proc.kill()
                proc.wait()

        stderr = "".join(_stderr_lines) if _stderr_lines else (proc.stderr.read() if proc.stderr else "")
        _stderr_thread.join(timeout=3)
        elapsed_ms = (time.perf_counter() - start) * 1000

        if _timed_out:
            if _timeout_reason == "idle":
                error_msg = f"脚本执行超时（无输出 {_idle_timeout}秒），脚本可能存在死循环或处理数据量过大导致执行缓慢。如脚本正在处理大数据，可在脚本中周期性 print/log 进度以避免 idle 超时"
            else:
                error_msg = f"脚本执行超时（总时长超过 {_hard_cap}秒 上限）"
            error_type = "超时"
        else:
            error_type = None
            if proc.returncode != 0:
                error_msg = stderr.strip() or "\n".join(stdout_lines)[-500:] or "脚本执行失败（无错误输出）"
                _preamble_lines = SKILL_RUNNER_TEMPLATE[:SKILL_RUNNER_TEMPLATE.find("# __SCRIPT_CONTENT__")].count("\n")
                error_msg = _fix_traceback_lines(error_msg, _preamble_lines)
                error_type = _extract_exception_type(error_msg)
            else:
                error_msg = None

        if stderr.strip() and proc.returncode == 0:
            stdout_lines.append("[stderr]")
            stdout_lines.append(stderr.strip())

        stdout_text = "\n".join(stdout_lines)

        yield {"type": "result", "result": {
            "success": proc.returncode == 0,
            "result": result,
            "written_tables": None,
            "tool_calls": tool_call_log or [],
            "tool_failures": tool_failures,
            "sandbox": {
                "injected_functions": ["call_tool"],
            },
            "error": error_msg,
            "error_type": error_type,
            "stderr": stderr.strip() if stderr else "",
            "stdout": stdout_text.strip(),
            "execution_time_ms": round(elapsed_ms, 2),
        }}

    except Exception as e:
        yield {"type": "result", "result": {
            "success": False, "error": str(e), "stdout": "", "execution_time_ms": 0,
        }}
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass
        if sandbox_cwd:
            try:
                import shutil as _shutil
                _shutil.rmtree(sandbox_cwd, ignore_errors=True)
            except:
                pass


def run_skill_script_streaming(
    skill_path: Path = None,
    script_name: str = "main.py",
    script_content: str = None,
    parameters: Dict[str, Any] = None,
    input_data: Any = None,
    datasource_id: str = None,
    table_name: str = None,
    datasource_name: str = None,
    timeout: int = None,
    user_id: str = None,
    cwd: str = None,
    entry_function: str = None,
):
    """流式执行脚本，逐行 yield 进度行，最后 yield 完整结果 dict。

    两种模式：
    - 传 skill_path：从 skill_path/scripts/script_name 读脚本，自动注入 datasource/table 参数
    - 传 script_content：直接用内容字符串，不注入数据源参数

    yield 格式：
    - {"type": "progress", "message": "stdout 行内容"}  逐行进度
    - {"type": "result", "result": {...}}                最终结果
    """
    parameters = parameters or {}
    timeout = timeout or settings.SKILL_RUNNER_TIMEOUT

    if skill_path:
        logger.info(f"run_skill_script_streaming: timeout={timeout}, script={script_name}")
        script_path = skill_path / "scripts" / script_name
        if not script_path.exists():
            yield {"type": "result", "result": {
                "success": False, "error": f"脚本不存在: {script_path}", "stdout": "", "execution_time_ms": 0,
            }}
            return
        script_content = script_path.read_text(encoding="utf-8")

    function_name, uses_argparse = _detect_entry_function(script_content)
    if entry_function:
        function_name = entry_function
        uses_argparse = False
    script_content = _strip_main_block(script_content)

    if skill_path and datasource_id and "datasource" not in parameters and "datasource_id" not in parameters and "datasource_name" not in parameters:
        if uses_argparse and datasource_name:
            parameters["datasource"] = datasource_name
        else:
            parameters["datasource"] = datasource_id
            if datasource_name:
                parameters["datasource_name"] = datasource_name
    if skill_path and table_name and "tables" not in parameters and "table" not in parameters and "table_name" not in parameters and "table_names" not in parameters:
        if uses_argparse:
            parameters["tables"] = [table_name]
            parameters["table_names"] = [table_name]
        else:
            parameters["table_name"] = table_name

    data_literal = repr(input_data) if input_data is not None else "None"
    params_literal = repr(parameters)

    runner_script = SKILL_RUNNER_TEMPLATE.format(
        injected_data=data_literal,
        injected_params=params_literal,
        function_name=function_name,
        uses_argparse=uses_argparse,
        user_id=repr(str(user_id) if user_id else None),
    )
    runner_script = runner_script.replace("# __SCRIPT_CONTENT__", script_content)

    # 沙箱安全：环境变量白名单（不传密钥）
    _SANDBOX_ENV_KEYS = frozenset({
        "PATH", "HOME", "TEMP", "TMP", "TMPDIR",
        "SYSTEMROOT", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
        "PYTHONIOENCODING", "PYTHONUNBUFFERED", "PYTHONPATH",
        "DATACRAB_API_BASE",
        "LANG", "LC_ALL", "LC_CTYPE",
    })
    sandbox_env = {k: v for k, v in os.environ.items() if k in _SANDBOX_ENV_KEYS}
    sandbox_env["PYTHONIOENCODING"] = "utf-8"
    sandbox_env["PYTHONUNBUFFERED"] = "1"
    # 不设 PYTHONPATH（防止 import app.* 读平台源码）
    sandbox_env.pop("PYTHONPATH", None)

    # 沙箱安全：cwd 改为临时目录（防止相对路径读平台文件）
    import tempfile as _tempfile_mod
    sandbox_cwd = _tempfile_mod.mkdtemp(prefix="dc_sandbox_")
    # 收集授权目录传给子进程（供 open() 沙箱化使用）
    # 异步收集太重，这里用简化版：只传 skill_path 和 DATACRAB_API_BASE 所在目录
    _allowed_dirs = []
    if skill_path:
        _allowed_dirs.append(str(skill_path.resolve()))
    sandbox_env["SANDBOX_ALLOWED_DIRS"] = json.dumps(_allowed_dirs, ensure_ascii=False)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(runner_script)
        temp_path = f.name

    import subprocess as _sp
    # POSIX 资源限制（Linux/macOS）
    import platform as _platform
    _preexec = None
    if _platform.system() != "Windows":
        def _set_resource_limits():
            import resource as _resource
            try:
                # 内存上限 2GB
                _mem_limit = 2 * 1024 * 1024 * 1024
                _resource.setrlimit(_resource.RLIMIT_AS, (_mem_limit, _mem_limit))
            except (ValueError, _resource.error):
                pass
            try:
                # CPU 时间上限 600 秒（累计）
                _resource.setrlimit(_resource.RLIMIT_CPU, (600, 600))
            except (ValueError, _resource.error):
                pass
            try:
                # 文件大小上限 500MB（防填满磁盘）
                _resource.setrlimit(_resource.RLIMIT_FSIZE, (500 * 1024 * 1024, 500 * 1024 * 1024))
            except (ValueError, _resource.error):
                pass
        _preexec = _set_resource_limits

    try:
        proc = _sp.Popen(
            [sys.executable, temp_path],
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=sandbox_cwd,
            env=sandbox_env,
            preexec_fn=_preexec,
        )
    except Exception as e:
        try:
            os.unlink(temp_path)
        except:
            pass
        try:
            import shutil as _shutil
            _shutil.rmtree(sandbox_cwd, ignore_errors=True)
        except:
            pass
        yield {"type": "result", "result": {
            "success": False, "error": str(e), "stdout": "", "execution_time_ms": 0,
        }}
        return
    yield from _stream_execute(proc, timeout, temp_path, sandbox_cwd)


async def run_skill_script_streaming_async(
    skill_path: Path,
    script_name: str = "main.py",
    parameters: Dict[str, Any] = None,
    input_data: Any = None,
    datasource_id: str = None,
    table_name: str = None,
    datasource_name: str = None,
    timeout: int = None,
    user_id: str = None,
):
    """异步流式执行 Skill 脚本。yield progress 事件 + 最终 result。"""
    import asyncio as _asyncio
    import queue as _queue

    _sem = _get_sandbox_semaphore()
    await _sem.acquire()
    try:
        _q: _asyncio.Queue = _asyncio.Queue()

        def _sync_gen():
            try:
                for item in run_skill_script_streaming(
                    skill_path=skill_path, script_name=script_name, parameters=parameters,
                    input_data=input_data, datasource_id=datasource_id, table_name=table_name,
                    datasource_name=datasource_name, timeout=timeout, user_id=user_id,
                ):
                    _q.put_nowait(item)
            finally:
                _q.put_nowait(None)  # sentinel

        loop = _asyncio.get_event_loop()
        task = loop.run_in_executor(None, _sync_gen)

        while True:
            try:
                item = await _asyncio.wait_for(_q.get(), timeout=30.0)
            except _asyncio.TimeoutError:
                yield {"type": "ping"}
                continue
            if item is None:
                break
            yield item

        await task
    finally:
        _sem.release()


# ============================================================================
# by_content 系列：接收脚本内容字符串（而非 skill_path），供 pipeline_executor 复用
# 委托给 run_skill_script_streaming(script_content=...)，丢弃进度，只返回结果
# ============================================================================


def run_skill_script_by_content(
    script_content: str,
    parameters: Dict[str, Any] = None,
    input_data: Any = None,
    user_id: str = None,
    timeout: int = None,
    cwd: str = None,
    entry_function: str = None,
) -> Dict[str, Any]:
    """在沙箱中执行脚本内容字符串（委托给流式版本，丢弃进度，只返回结果）。"""
    for item in run_skill_script_streaming(
        script_content=script_content,
        parameters=parameters,
        input_data=input_data,
        user_id=user_id,
        timeout=timeout,
        cwd=cwd,
        entry_function=entry_function,
    ):
        if item.get("type") == "result":
            return item["result"]
    return {"success": False, "error": "执行无结果返回", "stdout": "", "execution_time_ms": 0}

async def run_skill_script_by_content_async(
    script_content: str,
    parameters: Dict[str, Any] = None,
    input_data: Any = None,
    user_id: str = None,
    timeout: int = None,
    cwd: str = None,
    entry_function: str = None,
) -> Dict[str, Any]:
    """异步执行脚本内容字符串，委托给同步版本。"""
    async with _get_sandbox_semaphore():
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_skill_script_by_content(
                script_content=script_content,
                parameters=parameters,
                input_data=input_data,
                user_id=user_id,
                timeout=timeout,
                cwd=cwd,
                entry_function=entry_function,
            ),
        )
        return result