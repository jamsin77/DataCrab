# 平台静默失败审查报告

> 审查时间：2026-07-22
> 状态：已验证，待修复

## P0-0. `internal/llm/vision` + `internal_read_file` 端点 UUID 类型不匹配（500 错误）

- **文件**：`backend/app/api/v1/endpoints/datasource.py`
- **line 544-545**（`internal/llm/vision`）：`select(FileLink).where(FileLink.created_by == user_id)`
- **line 737**（`internal_read_file`）：同样的查询
- **根因**：`user_id` 从 JSON body 来的是字符串（`skill_runner.py:646` 用 `repr(str(user_id))` 注入），但 `FileLink.created_by` 是 SQLAlchemy UUID 类型列。绑定时处理器调 `value.hex` → `'str' object has no attribute 'hex'` → 500
- **影响**：`llm_vision` 和 `read_file` 从技能沙箱调用时全部 500。extract-image-info 的 71 张图 OCR 全部失败（`llm_vision` catch 500 返回 ""，技能标"OCR返回空结果"）
- **暴露原因**：之前 extract-image-info 技能传垃圾路径给 `llm_vision`，根本到不了端点。修好技能后真正调到了端点，翻出了这个藏着的平台 bug
- **修法**：端点查询前转 UUID：`from uuid import UUID; _uid = UUID(str(user_id)) if user_id else None`，然后 `FileLink.created_by == _uid`
- **破坏风险**：低（纯修复，查询条件不变）

## 审查方法

对 `skill_runner.py`、`connectors.py`、`sandbox_ns.py`、`shared_tools.py` 四个核心文件做全面搜索 + 亲自读码验证，区分真问题和误报。

---

## P0 — 必须修（数据丢失 / 错误放大）

### P0-1. CSV/Excel `write_table_data` 的 `fail` 策略静默覆盖文件

- **文件**：`connectors.py`
- **CSV**（line 391-404）：只检查 `strategy == "append"`，其他策略（含 `fail`）直接 `df_new.to_csv()` 覆盖
- **Excel**（line 557-580）：`kwargs` 接了但根本不读 `if_table_exists`，永远覆盖目标 sheet
- **影响**：用户指定 `if_table_exists="fail"`（已存在则报错），文件被静默覆盖 → **数据丢失**
- **修法**：
  - CSV：`if _os.path.exists(file_path) and strategy == "fail": return {"success": False, "message": f"文件已存在: {file_path}"}`
  - Excel：读 `strategy = kwargs.get("if_table_exists", "fail")`，`fail` 时检查文件/sheet 存在→报错
- **破坏风险**：低（修复 bug，原本就该报错）

### P0-2. 错误结果被缓存 30 分钟

- **文件**：`shared_tools.py` line 455-456
- **代码**：`cache.put(name, arguments, result)` 不检查 result 是否含 `error` key
- **影响**：瞬态错误（网络抖动、DB 锁）被缓存 30 分钟，后续重试命中缓存返回同样的错误，LLM 以为是永久错误
- **修法**：`put` 前检查 `json.loads(result).get("error")` → 有 error 则跳过缓存
- **破坏风险**：低

---

## P1 — 应该修（错误不可见）

### P1-1. 连接器连接失败后返回空数据

- **文件**：`connectors.py`，14 个方法
- **模式**：`if not self._connection: return pd.DataFrame() / return [] / return {}`
- **涉及连接器**：MySQL（line 236-237, 250-251, 264-265, 275-276）、SQLite（line 1136-1137, 1151-1152, 1166-1167, 1176-1177）、OBS（line 639-640, 675-676, 707-708）、HDFS（line 822-823, 855-856, 891-892）
- **影响**：连接失败 → 返回空 DataFrame/空列表 → shared_tools 当成功返回 `{"total_matched": 0}` → Agent 看到"成功，0 行"，无法区分空表和连接失败
- **修法**：`if not self._connection: raise ConnectionError(f"{connector_type} 连接失败，无法执行 {method_name}")`
- **破坏风险**：中（需要确认上游 shared_tools 的 try/except 能捕获 ConnectionError）

### P1-2. `list_user_datasources` 的 `close()` 在 try 内

- **文件**：`shared_tools.py` line 269-275
- **代码**：
  ```python
  try:
      connector = get_connector(...)
      schema = await connector.get_schema()
      item["tables"] = [s.get("table_name", "") for s in schema if s.get("table_name")]
      await connector.close()  # ← 在 try 内！
  except Exception:
      item["tables"] = []  # ← close() 失败会覆盖已获取的 schema
  ```
- **影响**：`get_schema()` 成功但 `close()` 失败 → `tables` 被覆盖为 `[]`，丢弃已获取数据
- **修法**：`close()` 移到 `finally` 块
- **破坏风险**：低

### P1-3. stats 获取 `except: pass`

- **文件**：`shared_tools.py`
- **query_table_data**（line 201-205）：stats 失败 → `total=0` → `total or len(df)` 回退到页大小 → Agent 看到错误行数
- **get_table_schema**（line 237-240）：stats 失败 → `row_count: "未知"`，无法区分"不支持"和"出错了"
- **修法**：`except Exception as e: logger.warning(f"stats 获取失败: {e}")`，total 保持 0 但不覆盖
- **破坏风险**：低

### P1-4. `list_user_datasources` schema 获取失败 → `tables=[]`

- **文件**：`shared_tools.py` line 274-275
- **影响**：数据源连接失败 → `tables=[]` → Agent 以为数据源是空的
- **修法**：`item["tables"] = []` 改为 `item["tables"] = []; item["error"] = str(e)`
- **破坏风险**：低

---

## P2 — 谨慎修（可能破坏现有技能）

### P2-1. skill_runner.py 工具函数返回空值而非 raise

- **文件**：`skill_runner.py`（模板字符串内，注意 `{{` 转义）
- **涉及函数**（6 个，返回空值而非 raise）：

| 函数 | 行 | 当前返回 | 应改为 |
|------|-----|---------|--------|
| `_dc_query_table_data` | 159, 162 | `return pd.DataFrame()` | `raise RuntimeError(_msg)` / `raise` |
| `_dc_get_table_schema` | 174, 177 | `return []` | `raise` |
| `llm_chat` | 220, 223 | `return ""` | `raise RuntimeError(_msg)` / `raise` |
| `llm_vision` | 425, 428 | `return ""` | `raise RuntimeError(_msg)` / `raise` |
| `list_tables` | 283, 286 | `return []` | `raise` |
| `iter_table_data` | 310, 313 | `break`（静默截断） | `raise` |

- **重要细节**：每个函数都有 `print` 到 stdout，错误信息不是完全消失——但脚本不 raise → runner 报 success → 调试 Agent 看到成功 + stdout 里的错误文字，不会当错误处理
- **`iter_table_data` 最危险**：`break` 导致静默截断，调用方以为读完了全部数据
- **修法**：对齐 `read_file` 的 fail-fast 模式（line 366-373 已修好），except 中 `raise RuntimeError(_msg)` / `raise`
- **破坏风险**：中（技能需有 try/except 包裹工具调用；现有不包裹的技能会从"静默空值"变成"报错终止"——但这是期望行为）

### P2-2. skill_runner.py `write_table_data` / `execute_sql` 返回 error dict 不 raise

- **文件**：`skill_runner.py`
- **write_table_data**（line 256, 259）：`return {"success": False, "message": _msg}`
- **execute_sql**（line 342, 345）：`return {"success": False, "data": [], ...}`
- **判断**：**不改**。错误信息在返回值里，不是静默。很多技能检查 `success` 字段。改成 raise 会破坏这些技能。
- **如果改**：需同时审计所有技能的 write_table_data 调用是否都有 success 检查

---

## 不修（误报 / 已修复 / 低优先）

### 已修复
- `read_file` 对图片返回乱码 → 已改 fail-fast（本轮修复）
- `write_table_data` 不支持策略静默 fall-through → 已加 `VALID_WRITE_STRATEGIES` 校验（本轮修复）
- `give_up` 事件 reason 被前端忽略 → 已修前端显示 `data.reason`（本轮修复）

### 误报
- **`write_table_data` / `execute_sql` 返回 error dict**：不是静默，错误在返回值里
- **sandbox_ns.py 问题**：是算子沙箱（用得少），优先级低于 skill_runner（技能沙箱）
- **`run_skill_script` JSON parse `except: pass`**：是输出解析，不是工具函数错误处理
- **连接器 if/elif 无 else**：已有 `VALID_WRITE_STRATEGIES` 在 `ConnectorManager.write_table` 入口兜底

### 低优先（可后续处理）
- `sandbox_ns.py` `get_table_schema` 不检查 error key（line 62）
- `sandbox_ns.py` `read_file` catch-all 对未知二进制格式返回乱码（line 225-226）
- `sandbox_ns.py` `llm_vision` 未知图片格式静默当 jpeg（line 304）
- `connectors.py` `execute_query` 在文件型连接器返回空 DataFrame（应 `NotImplementedError`）
- `shared_tools.py` 4 个外层 except 不打 logger
- `skill_runner.py` `run_skill_script` 最终 catch-all 丢弃 stdout（line 768-774）

---

## 修复顺序建议

1. P0-1（CSV/Excel fail 覆盖）→ P0-2（错误缓存）→ 验证
2. P1-1（连接失败空返回）→ P1-2（close 在 try）→ P1-3（stats pass）→ P1-4（tables=[]）→ 验证
3. P2-1（skill_runner 6 函数 raise）→ 跑全部测试 → 验证现有技能不 break
