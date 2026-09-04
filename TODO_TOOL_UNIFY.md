# 工具统一 + 算子迁移沙箱 — ✅ 已完成（第三十二轮）

> 本文档已归档，所有任务已完成。详见 AGENTS.md 第三十二轮记录。当前实现状态以 AGENTS.md「现状校正（文档 vs 代码实际）」为准。

## 背景
DataCrab 有两套工具实现：Agent 工具（tool_registry.py，主进程）和沙箱工具（skill_runner.py 模板，子进程 HTTP）。同一能力两套实现是历史演进（先有沙箱工具，后加 Agent 时复制了一份）。目标是统一成一套工具，一个 handler 实现，两个入口（LLM 决策 / 脚本调用）。

同时算子脚本仍在主进程 exec 执行（sandbox_ns.py），需要迁移到沙箱（skill_runner 子进程），和技能/流程统一。

## 一、工具统一（8 项）

### 1. 合并重叠工具到 tool_registry（5 对）
| Agent 工具 | 沙箱工具 | 合并方案 |
|---|---|---|
| `query_table_data` | `get_table_data` / `query_table_data` | 合并成一个 `query_table_data`，删 `get_table_data`（沙箱两个名字同一个实现） |
| `get_table_schema` | `get_table_schema` | 直接合并，handler 已在 tool_registry |
| `execute_sql` | `execute_sql` | 直接合并，handler 已在 tool_registry |
| `llm_vision` | `llm_vision` | 直接合并，handler 已在 tool_registry |
| `list_user_datasources` | `list_tables` + `get_datasource_id_by_name` | `list_user_datasources` handler 扩展：传 `datasource_id` 参数时返回该数据源的表列表（替代 `list_tables`）；传 `by_name` 参数时返回数据源 ID（替代 `get_datasource_id_by_name`） |

文件：
- `backend/app/services/tool_registry.py` — 扩展 `list_user_datasources` handler
- `backend/app/services/skill_runner.py` — 删沙箱函数定义

### 2. 迁移沙箱独有工具到 tool_registry（5 个）
| 工具 | 来源 | handler 逻辑 |
|---|---|---|
| `write_table_data` | skill_runner.py L241 | 调 connector.write_table_data()，记录 _WRITTEN_TABLES |
| `iter_table_data` | skill_runner.py L299 | 分页调 connector.get_table_data()，yield 每块 |
| `extract_video_info` | skill_runner.py L447 | 调 video_utils.probe_video() |
| `extract_keyframes` | skill_runner.py L461 | 调 video_utils.extract_keyframes() |
| `resolve_column` | skill_runner.py L507 | 列名模糊匹配（精确→忽略大小写→difflib 模糊） |

文件：
- `backend/app/services/tool_registry.py` — 新增 5 个 register_tool + handler
- `backend/app/services/skill_runner.py` — 删沙箱函数定义

### 3. 迁移 llm_chat→llm_generate 到 tool_registry
- 沙箱有 `llm_chat`，Agent 没有。改名 `llm_generate` 注册到 tool_registry
- handler：调 `llm_manager.chat(prompt, system_prompt=, temperature=, max_tokens=)`
- 4 个技能用了 `llm_chat`：语义分类(26d263ab)、语义合并(7940a035)、翻译(2f66eb58)、视频处理(a6371346)

文件：
- `backend/app/services/tool_registry.py` — 新增 register_tool("llm_generate", ...)
- `backend/app/services/skill_runner.py` — 删 llm_chat 函数

### 4. 合并 read_file/write_file 到 tool_registry
- `read_file` 和 Agent 的 `read_script` 语义不同（read_file 读任意文件自动检测格式，read_script 读脚本全文带行号），不合并，各自注册
- `write_file` 和 Agent 的 `save_file_to_link` 类似但不同（write_file 直接写路径，save_file_to_link 写到 FileLink 目录），各自注册
- handler 参考现有 `/internal/files/read` 和 `/internal/files/write` 端点逻辑

文件：
- `backend/app/services/tool_registry.py` — 新增 register_tool("read_file", ...) + register_tool("write_file", ...)
- `backend/app/services/skill_runner.py` — 删 read_file/write_file 函数

### 5. skill_runner 模板改为 call_tool 统一调用
- 删掉模板里所有沙箱函数定义（get_table_data/query_table_data/write_table_data/execute_sql/list_tables/iter_table_data/read_file/write_file/llm_vision/llm_chat/extract_video_info/extract_keyframes/resolve_column/get_datasource_id_by_name/get_table_schema）
- 替换为一个通用 `call_tool(tool_name, **args)` 函数，通过 HTTP 调 `/internal/execute-tool` 端点
- builtins 注入改为：`_builtins.call_tool = call_tool`（只注入这一个入口）
- 技能脚本改为用 `call_tool("query_table_data", datasource_id="xxx", table_name="yyy")` 调用
- 但这会破坏所有现有技能脚本（直接调 `query_table_data()` 而非 `call_tool("query_table_data", ...)`）

**兼容方案**：模板里保留一个 `call_tool` + 一个 `_proxy_tool(name)` 工厂函数，自动为每个工具名生成代理：
```python
def call_tool(tool_name, **args):
    # HTTP 调 /internal/execute-tool
    ...

def _proxy_tool(name):
    def _w(*args, **kwargs):
        return call_tool(name, *args, **kwargs)
    return _w

# 兼容现有脚本：直接调函数名
_builtins.query_table_data = _proxy_tool("query_table_data")
_builtins.write_table_data = _proxy_tool("write_table_data")
_builtins.llm_generate = _proxy_tool("llm_generate")
# ... 每个工具都生成代理
```
这样技能脚本不需要改调用方式，只是底层实现从各自的 HTTP wrapper 变成统一的 call_tool。

文件：
- `backend/app/services/skill_runner.py` — SKILL_RUNNER_TEMPLATE 重写

### 6. 新增 /internal/execute-tool 统一端点
- 在 `backend/app/api/v1/endpoints/datasource.py` 新增 `POST /internal/execute-tool`
- 接收 `{tool_name, args, user_id}`
- 内部调 `execute_tool(tool_name, args, db, user_id, context={})`（tool_registry 的统一入口）
- 无认证（仅供沙箱子进程本机调用，和现有 /internal/* 端点一致）

文件：
- `backend/app/api/v1/endpoints/datasource.py`

### 7. 删 SANDBOX_TOOLS_DOC，system prompt 改为注入 tool_guidance
- 删 `backend/app/services/prompt_docs.py` 里的 `SANDBOX_TOOLS_DOC`
- 技能创建/调试时的 system prompt 改为注入 `get_tool_guidance(debug=True)`（JSON Schema 格式的工具能力表）
- `PLATFORM_CONVENTIONS_DOC` 保留（平台规范文档，和工具无关）
- 影响文件：
  - `backend/app/services/prompt_docs.py` — 删 SANDBOX_TOOLS_DOC
  - `backend/app/services/skill.py` — debug-chat system prompt 改引用 tool_guidance
  - `backend/app/services/data_processor_agent.py` — build_debug_system_prompt 改引用 tool_guidance
  - `backend/app/services/data_analyst_agent.py` — build_debug_system_prompt 改引用 tool_guidance
  - `backend/app/services/tool_guidance.py` — available_functions 列表更新（删 call_operator/compute_map/log，加 llm_generate/write_table_data/iter_table_data/read_file/write_file/extract_video_info/extract_keyframes/resolve_column）

### 8. 9 个技能脚本改名
- `get_table_data` → `query_table_data`（所有技能脚本）
- `llm_chat` → `llm_generate`（4 个技能：26d263ab/7940a035/2f66eb58/a6371346）
- 如果用了第 5 项的兼容方案（_proxy_tool），则不需要改名——脚本直接调函数名仍然有效

文件：
- `backend/data/skills/*/scripts/main.py`（9 个技能）

## 二、算子迁移沙箱（4 项）

### 9. operator.py 算子执行从 exec 改为调 skill_runner
- 当前：`backend/app/api/v1/endpoints/operator.py` 用 `exec(op.script_content, exec_ns)` 在主进程执行算子
- 改为：调 `skill_runner.run_skill_script_by_content_async(script_content=op.script_content, parameters=..., user_id=..., entry_function=op.function_name)`
- 影响位置：operator.py 的算子执行端点（L60 附近）+ 算子调试端点（L209 附近）

文件：
- `backend/app/api/v1/endpoints/operator.py`

### 10. tool_registry.py _run_script_handler operator 分支改为调 skill_runner
- 当前：`backend/app/services/tool_registry.py` L735-756 的 `_run_script_handler` 里 `debug_type == "operator"` 分支用 exec 执行
- 改为：调 `skill_runner.run_skill_script_by_content_async`（和 pipeline 分支一致）

文件：
- `backend/app/services/tool_registry.py`

### 11. task_runner.py 算子调度执行改为调 skill_runner
- 当前：`backend/app/services/task_runner.py` L289 用 `build_operator_namespace` + exec 执行算子
- 改为：调 `skill_runner.run_skill_script_by_content_async`

文件：
- `backend/app/services/task_runner.py`

### 12. 删 sandbox_ns.py
- 删 `backend/app/services/sandbox_ns.py`（build_operator_namespace / run_async_in_thread / _get_allowed_paths）
- 删所有引用：operator.py / tool_registry.py / task_runner.py 的 import

文件：
- 删 `backend/app/services/sandbox_ns.py`
- 改 `backend/app/api/v1/endpoints/operator.py` — 删 import
- 改 `backend/app/services/tool_registry.py` — 删 import
- 改 `backend/app/services/task_runner.py` — 删 import

## 三、已完成的不用再做

- DataProcessor/DataAnalyst 合并 debug_mode 分模式 ✅（已完成）
- ChatAgent 去掉 kb_search/list_user_datasources ✅（已完成）
- DataInspector 去掉 kb_search ✅（已完成）
- 沙箱清除 call_operator/compute_map/log ✅（已完成）
- tool_registry.py 补 import os ✅（已完成）
- chat.py done 不重复 yield ✅（已完成）
- LLM Provider seed 不覆盖 is_public ✅（已完成）

## 四、未完成的独立任务（不在本次范围）

- 通用数据源（GenericFileConnector / 聊天上传数据 type 改 generic_file / data_type 标注）
- 前端 data_type 图标展示
- ExcelConnector 回退

## 五、工具最终清单（统一后）

### Agent 工具（tool_registry 注册，JSON Schema 格式）
ChatAgent（6）：
- web_fetch / get_llm_config / save_llm_adapter / delete_llm_adapter / save_connector / delete_connector

DataProcessor（21）：
- web_fetch / kb_search / list_user_datasources
- query_table_data / get_table_schema / execute_sql
- list_user_file_links / save_file_to_link
- llm_vision / llm_generate
- read_file / write_file
- write_table_data / iter_table_data / resolve_column
- extract_video_info / extract_keyframes
- edit_script / run_script / read_script / grep_script

DataAnalyst（19）：
- 同 DataProcessor 但去掉 list_user_file_links / save_file_to_link / write_table_data

DataInspector（6）：
- web_fetch / list_user_datasources
- profile_data / check_data_standards / check_data_quality / check_data_security

### 沙箱入口（skill_runner 模板）
- `call_tool(tool_name, **args)` — 统一 HTTP 调 /internal/execute-tool
- `_proxy_tool(name)` — 兼容旧脚本直接调函数名
- builtins 注入所有工具名的代理（query_table_data/write_table_data/llm_generate/...）

## 六、关键文件清单

| 文件 | 改动 |
|---|---|
| `backend/app/services/tool_registry.py` | +8 个 register_tool + handler，扩展 list_user_datasources，改 _run_script_handler operator 分支 |
| `backend/app/services/skill_runner.py` | SKILL_RUNNER_TEMPLATE 重写（删 15 个函数，加 call_tool + _proxy_tool） |
| `backend/app/api/v1/endpoints/datasource.py` | +/internal/execute-tool 端点 |
| `backend/app/api/v1/endpoints/operator.py` | 算子执行改调 skill_runner，删 sandbox_ns import |
| `backend/app/services/task_runner.py` | 算子调度改调 skill_runner，删 sandbox_ns import |
| `backend/app/services/sandbox_ns.py` | 删除 |
| `backend/app/services/prompt_docs.py` | 删 SANDBOX_TOOLS_DOC，更新 PLATFORM_CONVENTIONS_DOC |
| `backend/app/services/tool_guidance.py` | available_functions 更新 |
| `backend/app/services/skill.py` | debug-chat system prompt 改引用 tool_guidance |
| `backend/app/services/data_processor_agent.py` | build_debug_system_prompt 改引用 tool_guidance |
| `backend/app/services/data_analyst_agent.py` | build_debug_system_prompt 改引用 tool_guidance |
| `backend/data/skills/*/scripts/main.py` | 9 个技能脚本改名（如果不用兼容方案） |

## 七、风险点

1. **9 个技能脚本不能断** — 用 _proxy_tool 兼容方案可以不改脚本
2. **iter_table_data 是生成器** — call_tool 返回的是 HTTP 响应（JSON），不是生成器；iter_table_data 需要特殊处理（call_tool 返回第一块数据 + has_next，脚本循环调 call_tool("iter_table_data", ..., page=2)）
3. **write_table_data 记录 _WRITTEN_TABLES** — handler 里需要记录写入的表名到 context，供 RunTime handoff 用
4. **/internal/execute-tool 需要传 user_id** — 子进程没有用户认证，靠 user_id 参数鉴权（和现有 /internal/* 端点一致）
5. **算子脚本的函数签名和技能脚本不同** — 算子是 `def process(**params)`，技能是 `def main(args)`，迁移到 skill_runner 时 entry_function 和参数传递要适配
