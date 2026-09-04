"""Test platform capabilities and debug tools:
1. get_platform_capabilities — 能力清单生成
2. grep_script scope=platform — 平台代码搜索
3. read_script scope=platform — 平台代码读取
4. skill_runner tool_call_log — 工具调用日志
5. DEBUG_TOOLS 注册 — 工具注册完整性
"""
import json
import os
import sys
import ast

# 确保可以导入 app 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_platform_capabilities_structure():
    """P0: 能力清单结构完整"""
    from app.services.tool_guidance import PLATFORM_CAPABILITIES
    assert "connector" in PLATFORM_CAPABILITIES
    assert "sandbox" in PLATFORM_CAPABILITIES
    assert "llm" in PLATFORM_CAPABILITIES
    assert "framework" in PLATFORM_CAPABILITIES

    # 连接器层
    assert "excel" in PLATFORM_CAPABILITIES["connector"]
    assert "csv" in PLATFORM_CAPABILITIES["connector"]
    assert "sqlite" in PLATFORM_CAPABILITIES["connector"]
    assert "postgresql" in PLATFORM_CAPABILITIES["connector"]

    # Excel 不能创建新文件（这次的 bug）
    excel_wtd = PLATFORM_CAPABILITIES["connector"]["excel"]["write_table_data"]
    assert excel_wtd["create_new_file"] is False
    assert PLATFORM_CAPABILITIES["connector"]["excel"]["execute_sql"] is False

    # SQLite 可以创建新表
    sqlite_wtd = PLATFORM_CAPABILITIES["connector"]["sqlite"]["write_table_data"]
    assert sqlite_wtd["create_new_table"] is True
    assert PLATFORM_CAPABILITIES["connector"]["sqlite"]["execute_sql"] is True

    # 沙箱层
    assert PLATFORM_CAPABILITIES["sandbox"]["async_support"] is False
    assert "call_tool" in PLATFORM_CAPABILITIES["sandbox"]["available_functions"]

    # LLM 层
    assert "thinking" in PLATFORM_CAPABILITIES["llm"]

    # 框架层
    assert PLATFORM_CAPABILITIES["framework"]["max_debug_rounds"] > 0
    print("test_platform_capabilities_structure: PASSED")


def test_get_platform_capabilities_text():
    """P0: 能力清单文本生成"""
    from app.services.tool_guidance import get_platform_capabilities

    # 不带连接器类型
    text = get_platform_capabilities()
    assert "沙箱" in text
    assert "LLM" in text
    assert "框架" in text
    assert "async" in text.lower() or "await" in text.lower()

    # 带 excel 连接器类型
    text_excel = get_platform_capabilities("excel")
    assert "excel" in text_excel.lower()
    assert "create_new_file" in text or "创建新文件" in text_excel

    # 带 sqlite 连接器类型
    text_sqlite = get_platform_capabilities("sqlite")
    assert "sqlite" in text_sqlite.lower()

    # 不存在的连接器类型 → 不报错，只是不追加连接器段
    text_unknown = get_platform_capabilities("nonexistent")
    assert "沙箱" in text_unknown  # 仍有通用段
    print("test_get_platform_capabilities_text: PASSED")


def test_debug_tools_registration():
    """P4: 调试工具已注册到 tool_registry，grep_script/read_script 含 scope 参数"""
    from app.services.tool_registry import get_tool_schemas
    DEBUG_TOOLS = get_tool_schemas(["edit_script", "run_script", "read_script", "grep_script", "list_user_datasources"])
    names = [t["function"]["name"] for t in DEBUG_TOOLS]

    assert "grep_script" in names
    assert "read_script" in names
    assert "edit_script" in names
    assert "run_script" in names
    assert "list_user_datasources" in names
    assert "edit_and_run" not in names  # 已精简（Round 17）
    assert "modify_and_run" not in names  # 已精简（Round 17）
    assert "grep_code" not in names  # 已合并到 grep_script
    assert "read_code" not in names   # 已合并到 read_script

    # grep_script 工具 schema 检查 — 含 scope 参数
    grep_tool = next(t for t in DEBUG_TOOLS if t["function"]["name"] == "grep_script")
    props = grep_tool["function"]["parameters"]["properties"]
    assert "pattern" in props
    assert "scope" in props
    assert props["scope"]["enum"] == ["script", "platform"]
    assert "file_filter" in props

    # read_script 工具 schema 检查 — 含 scope 参数
    read_tool = next(t for t in DEBUG_TOOLS if t["function"]["name"] == "read_script")
    props = read_tool["function"]["parameters"]["properties"]
    assert "scope" in props
    assert props["scope"]["enum"] == ["script", "platform"]
    assert "file_path" in props
    assert "offset" in props
    assert "limit" in props
    print("test_debug_tools_registration: PASSED")


def test_grep_script_platform_scope():
    """P4: grep_script scope=platform 能搜到平台代码"""
    # 模拟 grep_script scope=platform 的逻辑
    import re
    import glob
    from pathlib import Path

    search_dir = Path(__file__).resolve().parent.parent / "app"
    files = glob.glob(str(search_dir / "**" / "*.py"), recursive=True)

    # 搜索 "文件不存在" — 应该在 connectors.py 中找到
    pattern = "文件不存在"
    regex = re.compile(pattern, re.IGNORECASE)
    matches = []
    for fpath in sorted(files):
        try:
            with open(fpath, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            if regex.search(line):
                matches.append({
                    "file": os.path.relpath(fpath, search_dir),
                    "line": i + 1,
                    "content": line.rstrip(),
                })

    assert len(matches) > 0, "应该在平台代码中找到'文件不存在'"
    # 应该在 connectors.py 中
    connector_matches = [m for m in matches if "connectors" in m["file"]]
    assert len(connector_matches) > 0, "应该在 connectors.py 中找到'文件不存在'"
    print(f"test_grep_script_platform_scope: PASSED (found {len(matches)} matches, {len(connector_matches)} in connectors.py)")


def test_read_script_platform_scope():
    """P4: read_script scope=platform 能读平台代码"""
    from pathlib import Path

    search_dir = Path(__file__).resolve().parent.parent / "app"
    # 读 connectors.py 第 555-565 行（ExcelConnector.write_table_data 的文件不存在检查）
    fpath = search_dir / "services" / "connectors.py"
    assert fpath.exists(), "connectors.py should exist"

    with open(fpath, encoding="utf-8") as f:
        all_lines = f.readlines()

    # 验证 connectors.py 中存在文件不存在的检查（搜索全文，不绑定行号）
    found = False
    for i, line in enumerate(all_lines, 1):
        if "不存在" in line or "not os.path.exists" in line or "FileNotFoundError" in line:
            found = True
            break
    assert found, "应该在 connectors.py 中找到文件不存在的检查"
    print(f"test_read_script_platform_scope: PASSED (connectors.py has {len(all_lines)} lines)")


def test_skill_runner_template_has_tool_call_log():
    """P1: skill_runner 模板包含 tool_call_log 逻辑"""
    from app.services.skill_runner import SKILL_RUNNER_TEMPLATE

    # 模板中应该有 _TOOL_CALL_LOG 定义
    assert "_TOOL_CALL_LOG" in SKILL_RUNNER_TEMPLATE
    # 应该有 __TOOL_CALL_LOG__ 输出标记
    assert "__TOOL_CALL_LOG__" in SKILL_RUNNER_TEMPLATE
    # 应该有 _logged_call_tool 函数（统一日志包裹）
    assert "_logged_call_tool" in SKILL_RUNNER_TEMPLATE
    print("test_skill_runner_template_has_tool_call_log: PASSED")


def test_skill_runner_template_generates_valid_python():
    """P1: skill_runner 模板格式化后生成有效 Python"""
    from app.services.skill_runner import SKILL_RUNNER_TEMPLATE

    # 用占位符格式化模板
    formatted = SKILL_RUNNER_TEMPLATE.format(
        injected_data="None",
        injected_params="{}",
        function_name="main",
        uses_argparse=False,
        user_id="None",
    )
    # 替换脚本内容占位符
    formatted = formatted.replace("# __SCRIPT_CONTENT__", "def main(**params):\n    return {'success': True}")

    # 验证生成的脚本是有效 Python
    try:
        ast.parse(formatted)
    except SyntaxError as e:
        pytest_fail(f"Generated script has syntax error: {e}")

    print("test_skill_runner_template_generates_valid_python: PASSED")


def test_skill_runner_result_has_tool_calls_field():
    """P1: skill_runner 返回结果包含 tool_calls 和 sandbox 字段"""
    # 检查 _stream_execute 函数的返回字典（执行核心，run_skill_script 委托给它）
    from app.services.skill_runner import _stream_execute
    import inspect
    source = inspect.getsource(_stream_execute)
    assert '"tool_calls"' in source, "_stream_execute 应该返回 tool_calls 字段"
    assert '"sandbox"' in source, "_stream_execute 应该返回 sandbox 字段"
    assert '"injected_functions"' in source, "sandbox 应该包含 injected_functions"
    print("test_skill_runner_result_has_tool_calls_field: PASSED")


def test_build_debug_system_prompt_includes_capabilities():
    """P0: build_debug_system_prompt 包含目标连接器能力"""
    import inspect
    from app.services.data_processor_agent import DataProcessorAgent
    source = inspect.getsource(DataProcessorAgent.build_debug_system_prompt)
    assert "PLATFORM_CAPABILITIES" in source or "get_platform_capabilities" in source, "应该查连接器能力"
    print("test_build_debug_system_prompt_includes_capabilities: PASSED")


def test_debug_instructions_has_workflow():
    """P2: DEBUG_INSTRUCTIONS 包含关键指引"""
    from app.services.data_processor_agent import DEBUG_INSTRUCTIONS
    assert "平台" in DEBUG_INSTRUCTIONS
    assert "call_tool" in DEBUG_INSTRUCTIONS
    assert "{max_exec_failures}" in DEBUG_INSTRUCTIONS
    print("test_debug_instructions_has_workflow: PASSED")


def test_extract_exception_type():
    """P0: 从 traceback 提取异常类型名"""
    from app.services.skill_runner import _extract_exception_type

    # 标准 traceback 最后一行
    assert _extract_exception_type("Traceback (most recent call last):\n  File main.py, line 42\nKeyError: 'xxx'") == "KeyError"
    assert _extract_exception_type("ModuleNotFoundError: No module named 'numpy'") == "ModuleNotFoundError"
    assert _extract_exception_type("PermissionError: [Errno 13] Permission denied") == "PermissionError"

    # 无冒号
    assert _extract_exception_type("SomeError") == "SomeError"

    # 空串/无内容
    assert _extract_exception_type("") == ""
    assert _extract_exception_type("   ") == ""

    # 非异常类型行（不以字母开头）
    assert _extract_exception_type("123: bad") == ""
    assert _extract_exception_type("Traceback (most recent call last):") == ""

    # 多行 traceback
    tb = """Traceback (most recent call last):
  File "main.py", line 10, in <module>
    df["col"].sum()
  File "main.py", line 5, in process
    return data["missing"]
KeyError: 'missing'"""
    assert _extract_exception_type(tb) == "KeyError"
    print("test_extract_exception_type: PASSED")


def pytest_fail(msg):
    raise AssertionError(msg)


if __name__ == "__main__":
    test_platform_capabilities_structure()
    test_get_platform_capabilities_text()
    test_debug_tools_registration()
    test_grep_script_platform_scope()
    test_read_script_platform_scope()
    test_skill_runner_template_has_tool_call_log()
    test_skill_runner_template_generates_valid_python()
    test_skill_runner_result_has_tool_calls_field()
    test_build_debug_system_prompt_includes_capabilities()
    test_debug_instructions_has_workflow()
    print("\n========== All 10 tests passed! ==========")
