"""共享的AI助手上下文文档 - 注入到所有AI助手的system prompt中"""

SAFETY_RULES_DOC = """## 安全红线（必须遵守）
- 算子/技能只能处理用户的业务数据，绝不能修改 DataCrab 平台自身
- 不得生成访问或修改平台系统表（users, roles, permissions, data_sources等）的代码
- 不得生成修改平台源代码、配置文件的代码
- 脚本中只能操作用户数据源的业务数据，不能操作平台系统数据
- 如果用户要求修改平台本身，请明确拒绝

## 用户内容可自由修改
- 用户可以自由创建、修改、调试、删除自己的对话、算子、技能
- 算子和技能脚本通过 call_tool() 调用工具访问用户数据
- 脚本可以使用 call_tool("llm_generate", ...) 调用大模型进行智能分析
- 用户可以用自然语言添加和修改数据源连接器与模型适配器（AI 生成代码，沙箱加载；所有连接器地位平等，含标准类型均可修改）

## 修改后必验证
- 生成或修改脚本后，必须验证修改未引入错误
- 如果验证失败，分析错误并提供修复方案

## 输出默认同源
- 数据处理生成新文件时，如果用户未指定输出路径（output_dir），默认保存到 DataSource（数据源）指定的文件路径下
- 如果 DataSource 来自数据库而非文件，需要用户明确指定输出路径"""

PLATFORM_CONVENTIONS_DOC = """## 平台约定（生成/修改/调试脚本时必须遵守）

### 工具调用
- 脚本中所有数据操作都通过 `call_tool(tool_name, **args)` 调用，返回 dict
- 查询数据: `call_tool("query_table_data", datasource_id=..., table_name=...)` → {"success", "data": [行dict], "columns": [列名], "row_count": int}
- 写入数据: `call_tool("write_table_data", datasource_id=..., table_name=..., records=[...], if_table_exists="append")`
- 执行 SQL: `call_tool("execute_sql", datasource_id=..., sql="SELECT ...")` → {"success", "data": [...], "columns": [...]}
- 按名查数据源: `call_tool("list_user_datasources", by_name="数据源名")` → {"id": "uuid", "name": ..., "type": ...}
- LLM 调用: `call_tool("llm_generate", prompt="...", system_prompt="...")` → {"content": "回复文本"}
- 图片 OCR: `call_tool("llm_vision", image_path="...", prompt="...")` → {"result": "分析文本"}
- 分块读取: `call_tool("iter_table_data", datasource_id=..., table_name=..., page=1, page_size=10000)` → {"columns", "rows", "page", "total", "has_next"}
- 读文件: `call_tool("read_file", path="...")` → {"format": "text/json/csv", "content": ...}
- 写文件: `call_tool("write_file", path="...", data=..., format="csv")` → {"success", "path", "size"}
- 视频信息: `call_tool("extract_video_info", video_path="...")` → {duration, width, height, fps, ...}
- 抽关键帧: `call_tool("extract_keyframes", video_path="...", max_frames=8)` → {"frames": [...]}
- 内置变量: `pd` (pandas) 已内置，无需 import

### 翻译场景
- 中英文翻译使用 `call_tool("llm_generate", prompt=..., system_prompt="你是翻译助手")`

### 图片 OCR 场景
- 图片文字提取/识别**必须用 `call_tool("llm_vision", image_path=..., prompt=...)`**

### 视频处理场景
- 视频信息提取用 `call_tool("extract_video_info", video_path=...)`
- 视频关键画面抽取用 `call_tool("extract_keyframes", video_path=...)`，返回帧图片路径列表
- 视频内容理解：先抽帧 → 对每帧 `call_tool("llm_vision", image_path=frame["image_path"], prompt=...)` 做内容分析

### 列名处理
- 用户用自然语言提到列名时，用 difflib.get_close_matches 做模糊匹配，不要直接 df[name]
- 示例: `import difflib; col = difflib.get_close_matches("价格", list(df.columns), n=1, cutoff=0.6)`

### 数据写入
- 写入时用 `if_table_exists` 参数控制策略：fail/append/replace/overwrite/truncate/delete_rows/upsert/create_new
- 分批写入时，第一批用原策略，后续批次用 append
- 写入后检查返回值的 `success` 字段，失败时 raise 而不是静默继续

### 大表处理
- 数据量超过 1 万行时，用 `call_tool("iter_table_data", ...)` 分页读取，避免一次性加载到内存
- 处理大数据时必须周期性 `print()` 输出进度，避免长时间无输出被判定卡死

### 进度输出规范（所有耗时操作通用）
- 每个耗时操作前后都 `print` 进度
- 循环体内也要 print（如"正在处理第 3/10 条"）
- 格式: `[步骤号/总步骤] 描述...` → 完成时: `完成: 数量/结果`
- 耗时超过 30 秒的操作必须加中间进度 print
- 持续输出可防止框架 idle 超时杀进程，也让用户实时感知进度

### 并发处理
- I/O 密集型任务用 `concurrent.futures.ThreadPoolExecutor`
- 独立子任务才并发，有依赖关系的步骤保持串行
- 并发数控制在 4-8，避免压垮数据源或触发 API 限流
- 示例：
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _process_table(ds_id, table_name):
    result = call_tool("query_table_data", datasource_id=ds_id, table_name=table_name)
    if not result.get("success"):
        raise ValueError(f"查询失败: {result.get('error')}")
    df = pd.DataFrame(result["data"], columns=result["columns"])
    return _transform(df)

tables = ["table_a", "table_b", "table_c"]
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(_process_table, ds_id, t): t for t in tables}
    results = {}
    for fut in as_completed(futures):
        results[futures[fut]] = fut.result()
```"""
