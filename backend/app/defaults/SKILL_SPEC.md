# DataCrab 技能规范（SKILL_SPEC）

> 本文档是 DataCrab 技能的**单一真相源**。技能创建、调试、检查均以本规范为准。

## 1. 技能结构

```
skill-name/
├── SKILL.md          # 核心指令文档（YAML 元数据 + Markdown 说明）
├── scripts/          # 可执行 Python 脚本
│   └── main.py       # 主入口脚本（必须）
├── references/       # 参考资料（可选）
└── assets/           # 静态资源（可选）
```

## 2. SKILL.md 格式

```yaml
---
name: skill-name              # 英文短横线命名，体现核心功能
description: 技能描述
version: "1.0.0"
tags:
  - 标签1
  - 标签2
---

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

### 3.2 必须遵守的规则

| 规则 | 说明 |
|------|------|
| **所有函数必须在 `if __name__` 之前** | 执行时 `if __name__ == '__main__':` 及其后所有代码会被自动删除。函数放在后面会导致 `NameError` |
| **用 `print()` 输出进度** | 用户能看到执行过程 |
| **用 `log(level, message)` 输出日志** | level=info/warn/error，格式化为 `[INFO] message` |
| **返回值必须含 `success` 字段** | `{"success": True, ...}` 或 `{"success": False, "error": "..."}` |
| **有类型注解和 docstring** | 函数参数标注类型，函数有文档字符串 |
| **处理边界情况** | 空表、列不存在、数据源不可达等 |

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
- 例外：用户可用自然语言添加自定义数据源连接器和自定义模型适配器（AI 生成代码，沙箱加载），这两项是唯一允许用户扩展的平台能力

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
