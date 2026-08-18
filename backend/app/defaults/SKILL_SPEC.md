# DataCrab 技能规范（SKILL_SPEC）

> 本文档是 DataCrab 技能的**单一真相源**。技能创建、调试、检查均以本规范为准。

## 1. 技能结构

```
skill-name/
├── SKILL.md          # 核心指令文档（YAML 元数据 + Markdown 说明）
├── scripts/          # 可执行 Python 脚本
│   └── main.py       # 主入口脚本（必须）
├── references/       # 参考资料（可选）
├── assets/           # 静态资源（可选）
└── rules.md          # 技能专属规则（可选，数据处理类技能用）
```

### rules.md（技能专属规则，可选）

数据处理类技能可在包内放置 `rules.md`，定义该技能**额外**的数据检查规则。DataInspector 在执行全局规则之外，会合并执行这些技能规则。

**编号前缀**（默认，可在 `rules.md` 内自定义）：
- `SKILL-STD-xxx`：标准类规则（格式正则/合法值），套用全局 STD 检查分支
- `SKILL-DQ-xxx`：质量类规则（完整性/唯一性/有效性），套用全局 DQ 检查分支
- `SKILL-SEC-xxx`：安全类规则（PII/敏感字段），套用全局 SEC 检查分支

**规则格式**（与全局规则库一致）：

```markdown
### SKILL-STD-001 身份证号格式
- 分类: 个人信息
- 适用字段: id_card,身份证号
- 格式正则: ^\d{17}[\dXx]$
- 严重等级: error

### SKILL-DQ-001 国家级文物编号必填
- 适用范围: 表
- 检查逻辑: protection_level='国家级' 时 serial_no 不能为空
- 阈值: 0
- 严重等级: critical

### SKILL-SEC-001 修复后手机号必须脱敏
- 分类: PII
- 适用范围: phone,mobile
- 检测正则: ^1\d{10}$
- 检测逻辑: 未脱敏的手机号明文
- 严重等级: critical
```

**合并执行**：inspector_tools 先跑全局规则，再跑技能规则，问题在报告中均列出。技能规则不替换全局规则，是补充检查。

**适用范围**：仅数据处理类技能（`skill_type: processing`）触发 Inspector，需放 `rules.md`；分析类技能只读不触发 Inspector，无需规则。

## 2. SKILL.md 格式

```yaml
---
name: skill-name              # 英文短横线命名，体现核心功能
description: 技能描述
version: "1.0.0"
skill_type: processing         # 技能类型：processing=数据处理 / analysis=数据分析
tags:
  - 标签1
  - 标签2
---

### skill_type 判定规则（必须填写）

| 类型 | 适用场景 | 对应 Agent | 特征 |
|------|----------|-----------|------|
| `processing` | 清洗、转换、修改、写入数据 | DataProcessor | 会修改数据/写表 |
| `analysis` | 查询、统计、分析、可视化、生成报告 | DataAnalyst | 只读不改，输出结论/图表 |

**判定标准**：技能执行后是否修改了源数据。只查不改用 `analysis`，要修改用 `processing`。无法判断时默认 `processing`。

# 技能标题

## 功能说明
描述技能做什么、处理什么数据。

## 使用方式
```
从 "数据源名" 的 "表名" 中筛选 "条件"
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `datasource_name` | str | ✅ | - | 数据源名称 |
| `table_name` | str | ❌ | - | 表名 |
| `if_table_exists` | str | ❌ | fail | 写入策略：fail/append/replace/overwrite/truncate/upsert |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心处理脚本 |
```

### name 命名规范
- 根据用户需求语义生成有意义的英文名，用短横线连接
- **禁止** generate_skill、new_skill、custom_skill 等无意义通用名
- 示例：`filter-by-dynasty`、`fill-missing-values`、`monthly-sales-stats`

## 3. 脚本规范

### 3.1 入口函数

```python
def main(**params):
    """主入口，系统注入用户参数"""
    return migrate_data(**params)
```

### 3.1.1 代码组织建议

复杂逻辑应拆分为多个聚焦的子函数，`main` 只做编排：

```python
def _load_data(datasource_name, table_name):
    """加载数据"""
    ...

def _clean_data(df):
    """清洗数据"""
    ...

def _transform_data(df):
    """转换数据"""
    ...

def _write_data(df, target_datasource, target_table):
    """写入结果"""
    ...

def migrate_data(**params):
    """主业务函数：编排各步骤"""
    df = _load_data(params["source_datasource"], params["source_table"])
    df = _clean_data(df)
    df = _transform_data(df)
    _write_data(df, params["target_datasource"], params["target_table"])
    return {"success": True, "rows": len(df)}

def main(**params):
    return migrate_data(**params)
```

拆分的好处：
- 每个子函数可独立用 `edit_and_run` 精确修改
- 调试时只需重写出错的子函数，不必重写整个 `main`
- 代码更清晰，更容易被 DataInspector 检查

### 3.2 必须遵守的规则

| 规则 | 说明 |
|------|------|
| **所有函数必须在 `if __name__` 之前** | 执行时 `if __name__ == '__main__':` 及其后所有代码会被自动删除。函数放在后面会导致 `NameError` |
| **用 `print()` 输出进度** | 用户能看到执行过程 |
| **用 `log(level, message)` 输出日志** | level=info/warn/error，格式化为 `[INFO] message` |
| **返回值必须含 `success` 字段** | `{"success": True, ...}` 或 `{"success": False, "error": "..."}` |
| **有类型注解和 docstring** | 函数参数标注类型，函数有文档字符串 |
| **处理边界情况** | 空表、列不存在、数据源不可达等 |
| **不得吞掉平台错误** | `llm_chat`/`llm_vision` 等内置函数的异常**不得用 try-except 吞掉后返回 `success=True`**。LLM 不可用、API key 未配置、连接失败等属于平台错误，应让异常传播（脚本崩溃），而非降级为空值继续执行 |
| **工具返回值必须检查 success** | `query_table_data`/`write_table_data`/`execute_sql`/`call_operator` 等返回 `{success: bool, ...}`，调用后必须检查 `success` 字段，失败时 `raise`，不得静默继续 |
| **只有核心操作完成才能 success=True** | 如果脚本的核心操作（如 OCR、翻译、分类）全部失败，即使脚本没崩溃也必须返回 `success=False`，不得用空值/默认值冒充结果 |

### 3.3 返回值格式

```python
# 成功
return {
    "success": True,
    "migrated_rows": 5296,
    "columns": ["name", "era", "address"],
    "target_table": "table_name"
}

# 失败
return {
    "success": False,
    "error": "找不到源数据源: 'xxx'",
    "message": "参数校验失败"
}
```

### 3.4 参数兼容映射

主函数应支持参数名别名映射，兼容系统注入的不同参数名：

```python
def main(**kwargs):
    param_aliases = {
        'source_datasource_name': ['source_datasource_name', 'source_datasource', 'datasource'],
        'source_table_name': ['source_table_name', 'source_table', 'table_name'],
        'target_datasource_name': ['target_datasource_name', 'target_datasource'],
    }
    # 映射后调用业务函数
```

## 4. 沙箱可用函数

> 以下函数由运行环境自动注入到全局作用域，**直接调用，无需 import**。

### 4.1 数据查询

| 函数 | 签名 | 返回 |
|------|------|------|
| `query_table_data` | `(datasource_id_or_name, table_name, limit=1000)` | `{"success": bool, "data": [...], "columns": [...], "row_count": int}` |
| `get_table_data` | 同上 | 同上（别名） |
| `get_table_schema` | `(datasource_id_or_name, table_name)` | `{"columns": [...], "row_count": int}` |
| `get_datasource_id_by_name` | `(name)` | `str` 数据源UUID |

### 4.2 数据写入

| 函数 | 签名 | 说明 |
|------|------|------|
| `write_table_data` | `(datasource_id_or_name, table_name, records=None, data=None, if_table_exists="fail", table_remark="", column_remarks=None)` | 写入数据到数据源 |

**`if_table_exists` 策略**：

| 策略 | 说明 | 会清空已有数据 |
|------|------|:---:|
| `fail` | 报错 | ❌ |
| `append` | 追加 | ❌ |
| `replace` | 删表重建 | ✅ |
| `overwrite` | 清空+补列+写入 | ✅ |
| `truncate` | 清空不补列+写入 | ✅ |
| `upsert` | 按ID更新或插入 | ❌ |

### 4.3 大模型调用

```python
result = llm_chat(
    prompt,                    # 用户消息（必填）
    system_prompt=None,        # 系统提示词（可选）
    temperature=0.7,           # 温度 0.0-2.0
    max_tokens=2000            # 最大生成 token 数
)
# 返回: str（大模型的文本回复）
```

### 4.4 日志

```python
log("info", "开始处理...")
log("warn", "数据量异常")
log("error", "写入失败")
# 输出: [INFO] 开始处理...
```

### 4.5 内置变量

- `pd` (pandas) 和 `json` 已内置，无需 import
- **禁止** `import datacrab` 或 `pip install datacrab`，datacrab 包不存在

## 5. 分批写入规范

当数据量大于 `batch_size` 时，必须分批写入：

```python
def _write_records(records, table_name, if_table_exists, batch_size=1000):
    """分批写入：第一批用原策略（如 overwrite/replace/truncate），后续批次用 append"""
    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    for i in range(0, len(records), batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"  # 后续批次追加，避免清空前面批次
        write_table_data(target_ds, table_name, records=batch, if_table_exists=current_strategy)
```

## 6. 安全红线

- 算子/技能**只能处理用户业务数据**，不能修改 DataCrab 平台自身
- **不得访问平台系统表**（users, roles, permissions, data_sources 等）
- **不得修改平台源代码、配置文件**
- 如果用户要求修改平台本身，**明确拒绝**
- 例外：用户可用自然语言添加和修改数据源连接器与模型适配器（AI 生成代码，沙箱加载）。所有连接器（含 PostgreSQL/MySQL/CSV/Excel 等标准类型）地位平等，均可通过 save_connector 修改其代码和配置项

## 7. 数据质量要求

数据处理完成后，结果数据应满足：

| 维度 | 要求 |
|------|------|
| **完整性** | 必填字段无空值；非必填字段空值率在合理范围 |
| **唯一性** | 主键/业务键无重复 |
| **标准合规** | 字段格式符合规范（日期、手机号、身份证等） |
| **类型一致** | 同一列数据类型一致 |
| **安全合规** | 无明文 PII（身份证、手机号等），无凭证泄露 |

DataInspector 会从这三个维度检查：标准检查（STD-xxx）、质量检查（DQ-xxx）、安全检查（SEC-xxx）。

## 8. 常见模式

### 8.1 列名映射（中文→英文）

```python
column_mapping = {"名称": "name", "时代": "era", "地址": "address"}
df = df.rename(columns=column_mapping)
```

### 8.2 自动生成 ID

```python
df["ID"] = [f"{i+1:08d}" for i in range(len(df))]  # 00000001, 00000002, ...
```

### 8.3 自动生成时间戳

```python
from datetime import datetime
df["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
```

### 8.4 数据源名称→ID

```python
ds_id = get_datasource_id_by_name("文物列表")
if not ds_id:
    raise ValueError(f"找不到数据源: 文物列表")
```
