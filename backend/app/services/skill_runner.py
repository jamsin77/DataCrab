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
    url = f"{{_API_BASE}}/api/v1/datasources/internal/datasources/{{_ds}}/tables/{{_tn}}/data?page={{page}}&page_size={{limit}}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return pd.DataFrame(data.get("rows", []))
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] query failed: HTTP {{e.code}} {{_msg}}")
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] query failed: {{e}}")
        raise

def _dc_get_table_schema(datasource_id, table_name):
    import urllib.request, urllib.parse
    _ds = urllib.parse.quote(str(datasource_id), safe='')
    url = f"{{_API_BASE}}/api/v1/datasources/internal/datasources/{{_ds}}/schema"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("tables", [])
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] schema failed: HTTP {{e.code}} {{_msg}}")
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] schema failed: {{e}}")
        raise

def _dc_get_datasource_id_by_name(name):
    import urllib.request
    url = f"{{_API_BASE}}/api/v1/datasources/internal/datasources"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            sources = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"非脚本错误：数据源服务不可达（{{e}}）")
    for s in sources:
        if s.get("name") == name:
            return s.get("id")
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
    _req = urllib.request.Request(f"{{_API_BASE}}/api/v1/datasources/internal/llm/chat", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("content", "")
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] llm_chat failed: HTTP {{e.code}} {{_msg}}")
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] llm_chat failed: {{e}}")
        raise

_WRITTEN_TABLES = []

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
    _url = f"{{_API_BASE}}/api/v1/datasources/internal/datasources/{{_ds}}/tables/{{_tn}}/data"
    _req = urllib.request.Request(_url, data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=300) as resp:
            _resp_data = json.loads(resp.read().decode("utf-8"))
            _WRITTEN_TABLES.append({{"datasource_id": str(datasource_id), "table_name": str(table_name)}})
            return _resp_data
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
    _url = f"{{_API_BASE}}/api/v1/datasources/internal/datasources/{{_ds}}/tables"
    try:
        with urllib.request.urlopen(_url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("tables", [])
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] list_tables failed: HTTP {{e.code}} {{_msg}}")
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] list_tables failed: {{e}}")
        raise

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
        _url = f"{{_API_BASE}}/api/v1/datasources/internal/datasources/{{_ds}}/tables/{{_tn}}/chunks?chunk_size={{chunk_size}}&page={{page}}"
        try:
            with urllib.request.urlopen(_url, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            _msg = _http_err(e)
            print(f"[SkillRunner] iter_table_data page {{page}} failed: HTTP {{e.code}} {{_msg}}")
            raise RuntimeError(_msg)
        except Exception as e:
            print(f"[SkillRunner] iter_table_data page {{page}} failed: {{e}}")
            raise
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
    _url = f"{{_API_BASE}}/api/v1/datasources/internal/datasources/{{_ds}}/sql"
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
    _req = urllib.request.Request(f"{{_API_BASE}}/api/v1/datasources/internal/files/read", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
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
        _msg = _http_err(e)
        print(f"[SkillRunner] read_file failed: HTTP {{e.code}} {{_msg}}")
        # fail-fast：透传后端错误（如"不支持读取图片，请用 llm_vision"），不吞成空串掩盖信号
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] read_file failed: {{e}}")
        raise

def write_file(path, data, format=None):
    # 写入文件（路径必须在文件链接授权目录内）
    # path: 文件路径
    # data: 要写入的内容（str/dict/list）
    # format: 可选，强制指定格式
    # 返回: dict {{"success": bool, "path": str, "size": int}}
    import urllib.request
    _payload = json.dumps({{"path": path, "data": data, "format": format, "user_id": INJECTED_USER_ID}}, ensure_ascii=False).encode("utf-8")
    _req = urllib.request.Request(f"{{_API_BASE}}/api/v1/datasources/internal/files/write", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
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
    _req = urllib.request.Request(f"{{_API_BASE}}/api/v1/datasources/internal/llm/vision", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("content", "")
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] llm_vision failed: HTTP {{e.code}} {{_msg}}")
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] llm_vision failed: {{e}}")
        raise

def extract_video_info(video_path):
    # 提取视频元数据（时长、分辨率、帧率、编码等）
    # video_path: 视频文件路径（必须在文件链接授权目录内）
    # 返回: dict {{"duration": float, "width": int, "height": int, "fps": float, "codec": str, ...}}
    import urllib.request
    _payload = json.dumps({{"video_path": video_path, "user_id": INJECTED_USER_ID}}).encode("utf-8")
    _req = urllib.request.Request(f"{{_API_BASE}}/api/v1/datasources/internal/video/info", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] extract_video_info failed: HTTP {{e.code}} {{_msg}}")
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] extract_video_info failed: {{e}}")
        raise

def extract_keyframes(video_path, max_frames=8, output_dir=None, method="auto"):
    # 抽取视频关键帧，输出为 JPEG 图片文件
    # video_path: 视频文件路径（必须在文件链接授权目录内）
    # max_frames: 最多抽取帧数（默认 8）
    # output_dir: 输出目录（默认在视频同目录下建 _keyframes 子目录）
    # method: "auto"（场景检测+等间隔补充）或 "interval"（纯等间隔）
    # 返回: list[dict] 如 [{{"frame": 1, "timestamp": 2.5, "image_path": "/path/to/frame_001.jpg"}}, ...]
    # 抽出的帧图片可直接传给 llm_vision 做内容理解
    import urllib.request
    _payload = json.dumps({{"video_path": video_path, "max_frames": int(max_frames), "output_dir": output_dir, "method": method, "user_id": INJECTED_USER_ID}}, ensure_ascii=False).encode("utf-8")
    _req = urllib.request.Request(f"{{_API_BASE}}/api/v1/datasources/internal/video/keyframes", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("frames", [])
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] extract_keyframes failed: HTTP {{e.code}} {{_msg}}")
        raise RuntimeError(_msg)
    except Exception as e:
        print(f"[SkillRunner] extract_keyframes failed: {{e}}")
        raise

def call_operator(operator_name, **params):
    # 调用用户自定义算子（通过内部 HTTP 端点执行算子脚本）
    # operator_name: 算子名称或 UUID
    # **params: 传给算子函数的参数
    # 返回: dict {{"success": bool, "result": ..., "stdout": str, "error": str}}
    import urllib.request
    _payload = json.dumps({{"operator_name": operator_name, "parameters": params, "user_id": INJECTED_USER_ID}}, ensure_ascii=False, default=str).encode("utf-8")
    _req = urllib.request.Request(f"{{_API_BASE}}/api/v1/operators/internal/execute", data=_payload, headers={{"Content-Type": "application/json"}}, method="POST")
    try:
        with urllib.request.urlopen(_req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _msg = _http_err(e)
        print(f"[SkillRunner] call_operator failed: HTTP {{e.code}} {{_msg}}")
        return {{"success": False, "error": _msg}}
    except Exception as e:
        print(f"[SkillRunner] call_operator failed: {{e}}")
        return {{"success": False, "error": str(e)}}

def resolve_column(df, name):
    # 按 name 解析 DataFrame 实际列名（精确 → 忽略大小写 → 模糊匹配）。找不到返回 None。
    # 用于用户提到的列名与实际列名不一致（中英文/近义词）场景：如用户说"价格"但实际列是 price。
    # 不用 LLM 翻译匹配——非确定性（换模型结果变）+ 破坏候选优先级（不精确候选抢先返回）
    import difflib
    cols = list(df.columns)
    name_s = str(name).strip()
    if not name_s:
        return None
    # 1. 精确匹配
    if name_s in cols:
        return name_s
    # 2. 忽略大小写/空白
    _low = {{str(c).strip().lower(): c for c in cols}}
    if name_s.lower() in _low:
        return _low[name_s.lower()]
    # 3. 模糊匹配（difflib，cutoff=0.6，捕捉近义词/拼写差异）
    _str_cols = [str(c) for c in cols]
    _m = difflib.get_close_matches(name_s, _str_cols, n=1, cutoff=0.6)
    if _m:
        return _m[0]
    return None

# Tool call log — 记录每个平台工具调用的结果，供调试 agent 判断错误来源
_TOOL_CALL_LOG = []

def _wrap_tool_log(_func_name, _func):
    import time as _time
    def _wrapper(*args, **kwargs):
        _start = _time.time()
        try:
            _result = _func(*args, **kwargs)
            _success = True
            _message = ""
            if isinstance(_result, dict):
                _success = _result.get("success", True)
                _message = _result.get("message", "") or _result.get("error", "")
            _TOOL_CALL_LOG.append({{
                "tool": _func_name,
                "success": _success,
                "message": str(_message)[:300] if _message else "",
                "elapsed_ms": round((_time.time() - _start) * 1000, 2),
            }})
            return _result
        except Exception as _e:
            _TOOL_CALL_LOG.append({{
                "tool": _func_name,
                "success": False,
                "message": str(_e)[:300],
                "elapsed_ms": round((_time.time() - _start) * 1000, 2),
            }})
            raise
    return _wrapper

# Inject into builtins so scripts using get_data_accessor() can find them
import builtins as _builtins
_builtins.get_table_data = _wrap_tool_log("get_table_data", get_table_data)
_builtins.query_table_data = _wrap_tool_log("query_table_data", get_table_data)
_builtins.write_table_data = _wrap_tool_log("write_table_data", write_table_data)
_builtins.execute_sql = _wrap_tool_log("execute_sql", execute_sql)
_builtins.list_tables = _wrap_tool_log("list_tables", list_tables)
_builtins.iter_table_data = _wrap_tool_log("iter_table_data", iter_table_data)
_builtins.read_file = _wrap_tool_log("read_file", read_file)
_builtins.write_file = _wrap_tool_log("write_file", write_file)
_builtins.compute_map = compute_map
_builtins.llm_vision = _wrap_tool_log("llm_vision", llm_vision)
_builtins.llm_chat = _wrap_tool_log("llm_chat", llm_chat)
_builtins.call_operator = _wrap_tool_log("call_operator", call_operator)
_builtins.extract_video_info = _wrap_tool_log("extract_video_info", extract_video_info)
_builtins.extract_keyframes = _wrap_tool_log("extract_keyframes", extract_keyframes)
_builtins.log = log
_builtins.get_datasource_id_by_name = _wrap_tool_log("get_datasource_id_by_name", _dc_get_datasource_id_by_name)
_builtins.get_table_schema = _wrap_tool_log("get_table_schema", _dc_get_table_schema)
_builtins.resolve_column = resolve_column

# atexit 确保脚本崩溃时也输出 tool_call_log（供调试 agent 追踪错误来源）
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
        if _WRITTEN_TABLES:
            print("__WRITTEN_TABLES__" + json.dumps(_sanitize_nans(_WRITTEN_TABLES), ensure_ascii=False, default=str))
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


_MARKER_PREFIXES = ("__RESULT__", "__WRITTEN_TABLES__", "__TOOL_CALL_LOG__")


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


def _stream_execute(proc, timeout: int, temp_path: str):
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
    written_tables = None
    tool_call_log = None

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

        _reader_thread = _threading.Thread(target=_stdout_reader, daemon=True)
        _reader_thread.start()

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
                        elif marker == "__WRITTEN_TABLES__":
                            written_tables = parsed
                        elif marker == "__TOOL_CALL_LOG__":
                            tool_call_log = parsed
                    except (json.JSONDecodeError, IndexError):
                        pass
                    break
            if is_marker:
                continue
            stdout_lines.append(line)
            if "[SkillRunner]" in line and "failed" in line.lower():
                tool_failures.append(line)
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

        stderr = proc.stderr.read() if proc.stderr else ""
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
            "written_tables": written_tables,
            "tool_calls": tool_call_log or [],
            "tool_failures": tool_failures,
            "sandbox": {
                "injected_functions": [
                    "get_table_data", "query_table_data", "write_table_data", "execute_sql",
                    "get_table_schema", "list_tables", "iter_table_data", "llm_chat", "llm_vision", "extract_video_info", "extract_keyframes",
                    "log", "read_file", "write_file", "compute_map",
                    "get_datasource_id_by_name", "resolve_column",
                ],
            },
            "error": error_msg,
            "error_type": error_type,
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

    import subprocess as _sp
    try:
        proc = _sp.Popen(
            [sys.executable, temp_path],
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(skill_path) if skill_path else (cwd or str(backend_path)),
            env={**os.environ, "PYTHONPATH": str(backend_path), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
        )
    except Exception as e:
        try:
            os.unlink(temp_path)
        except:
            pass
        yield {"type": "result", "result": {
            "success": False, "error": str(e), "stdout": "", "execution_time_ms": 0,
        }}
        return
    yield from _stream_execute(proc, timeout, temp_path)


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

    _q: _asyncio.Queue = _asyncio.Queue()

    def _sync_gen():
        for item in run_skill_script_streaming(
            skill_path=skill_path, script_name=script_name, parameters=parameters,
            input_data=input_data, datasource_id=datasource_id, table_name=table_name,
            datasource_name=datasource_name, timeout=timeout, user_id=user_id,
        ):
            _q.put_nowait(item)
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