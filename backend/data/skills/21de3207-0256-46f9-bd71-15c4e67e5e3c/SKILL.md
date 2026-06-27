---
name: data-etl
description: 在不同数据源之间迁移数据，支持列名转换、列删除、列添加及基本数据处理（类型转换、空值填充、字符串处理、中英文翻译等）
version: "1.0.0"
author: DataCrab
tags:
  - 数据迁移
  - 列名转换
  - 数据处理
  - 语言翻译
---

# 数据 ETL 技能 (Data ETL)

## 📌 功能说明

本技能用于在不同数据源（Excel、SQLite、CSV 等）之间迁移数据。迁移过程中支持：

1. **列名转换**：将源列名重命名为目标列名
2. **列删除**：删除不需要的列
3. **列添加**：添加常量列
4. **数据处理**：对列值进行基本转换处理
5. **中英文翻译**：在 ETL 过程中对指定列调用语言翻译算子，实现中英文自动翻译
6. **批量写入**：支持分批写入目标数据源

### 支持的数据处理类型

| 类型 | 说明 | 附加参数 |
|------|------|---------|
| `trim` | 去除字符串首尾空格 | - |
| `upper` | 转为大写 | - |
| `lower` | 转为小写 | - |
| `fill_na` | 填充空值 | `value`: 填充值 |
| `to_int` | 转为整数 | - |
| `to_float` | 转为浮点数 | `round`: 小数位数 |
| `to_str` | 转为字符串 | - |
| `to_date` | 转为日期 | `format`: 日期格式 |
| `prefix` | 添加前缀 | `value`: 前缀字符串 |
| `suffix` | 添加后缀 | `value`: 后缀字符串 |
| `replace` | 字符串替换 | `old`: 旧值, `new`: 新值 |
| `translate` | 中英文翻译（调用语言翻译算子） | `source_lang`: 源语言（`zh`/`en`），`target_lang`: 目标语言（`zh`/`en`） |

### 语言翻译算子说明

当 ETL 过程中有中英文翻译需求时，可通过 `translate` 处理类型调用语言翻译算子：

- **`source_lang`**：源语言，支持 `zh`（中文）和 `en`（英文）
- **`target_lang`**：目标语言，支持 `zh`（中文）和 `en`（英文）

常见翻译场景：
  - `zh → en`：将中文列值翻译为英文
  - `en → zh`：将英文列值翻译为中文

> ⚠️ 翻译算子会对列中每个值逐条调用翻译服务，处理大数据量时可能较慢，建议结合 `limit` 参数控制处理行数或分批处理。

## 🚀 使用方式

### 基本迁移

```
将 "CSVFormTest" 数据源中的 "users" 表迁移到 "SQLite测试数据库" 的 "migrated_users" 表
```

### 带列名转换的迁移

```
将 "文物测试数据" 的 "artifacts" 表迁移到 "SQLite测试数据库" 的 "artifacts_copy" 表，
列名映射：id → artifact_id, name → artifact_name, type → category
```

### 带数据处理的迁移

```
将 "CSVFormTest" 的 "products" 表迁移到 "SQLite测试数据库" 的 "products_clean" 表，
对 name 列去除空格，对 price 列转为浮点数保留2位小数，对 status 列转大写，
删除 temp 列，添加 source 列值为 "CSV"
```

### 带中英文翻译的迁移

```
将 "文物测试数据" 的 "artifacts" 表迁移到 "SQLite测试数据库" 的 "artifacts_en" 表，
对 name 列进行中文翻译为英文（source_lang: zh, target_lang: en），
对 description 列进行中文翻译为英文（source_lang: zh, target_lang: en），
列名映射：name → name_en, description → description_en
```

```
将 "CSVFormTest" 的 "products" 表迁移到 "SQLite测试数据库" 的 "products_zh" 表，
对 product_name 列进行英文翻译为中文（source_lang: en, target_lang: zh），
对 category 列进行英文翻译为中文（source_lang: en, target_lang: zh）
```

## 📋 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `source_datasource_name` | str | ✅ | - | 源数据源名称 |
| `source_table_name` | str | ✅ | - | 源表名 |
| `target_datasource_name` | str | ✅ | - | 目标数据源名称 |
| `target_table_name` | str | ✅ | - | 目标表名 |
| `column_mapping` | dict | ❌ | None | 列名映射 `{源列名: 目标列名}` |
| `column_transforms` | dict | ❌ | None | 列转换规则 `{列名: {type: 类型, ...}}` |
| `drop_columns` | list | ❌ | None | 要删除的列名列表 |
| `add_columns` | dict | ❌ | None | 要添加的列 `{列名: 值}` |
| `batch_size` | int | ❌ | 1000 | 批量写入大小 |
| `limit` | int | ❌ | 10000 | 读取行数上限 |
| `output_dir` | str | ❌ | None | 输出目录（文件型数据源时使用） |

### `column_transforms` 中 `translate` 类型示例

```json
{
  "name": {
    "type": "translate",
    "source_lang": "zh",
    "target_lang": "en"
  },
  "description": {
    "type": "translate",
    "source_lang": "zh",
    "target_lang": "en"
  }
}
```

### 处理顺序

1. 读取源数据
2. 删除指定列（`drop_columns`）
3. 应用列转换（`column_transforms`，包含翻译算子调用）
4. 列名映射（`column_mapping`）
5. 添加新列（`add_columns`）
6. 写入目标数据源

### 输出路径说明

- 如果目标数据源为文件型（CSV/Excel）且未指定 `output_dir`，默认保存到目标数据源文件所在目录
- 如果目标数据源为数据库（SQLite），数据直接写入目标表，`output_dir` 不生效
- 如需导出为独立文件，请明确指定 `output_dir` 路径

## 📁 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心迁移脚本，包含 `migrate_data()` 主函数和 `apply_column_transform()` 列转换工具函数。当列转换类型为 `translate` 时，调用语言翻译算子完成中英文翻译 |

## 常见问题与经验

### 数据迁移执行中断
- **问题描述**: 调用 `migrate_data` 执行数据迁移时触发 `execution_error`，导致任务中断。
- **根因分析**: 源/目标数据源连接异常、表名不存在或数据类型转换不兼容导致底层报错。
- **修复建议**: 执行前增加数据源连通性与目标表存在性校验，完善数据转换时的异常捕获机制。

### 错误日志截断问题
- **问题描述**: 错误堆栈信息在输出时被截断，无法获取完整的报错详情和具体代码行。
- **根因分析**: 日志输出预览长度受限，未将完整的 Traceback 信息优先展示或持久化保存。
- **修复建议**: 优化日志捕获机制，确保关键异常堆栈不被截断，或将完整日志写入文件供排查。
