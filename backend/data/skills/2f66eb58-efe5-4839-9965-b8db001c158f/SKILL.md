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
5. **中英文翻译**：在 ETL 过程中如果有语言翻译的需求，优先调用"文本翻译"算子对指定列进行中英文自动翻译
6. **批量写入**：支持分批写入目标数据源
7. **目标表已存在处理**：当指定的目标数据表已经存在时，支持在原表上操作，可选择追加内容或增加表的列，或者将原有内容删除后追加，以及按照主键更新原有内容
8. **目标表自动创建**：如果目标表不存在，根据目标数据源的类型自动创建目标表

数据检查：
1. **数据量检查**：数据的记录条数或者数据文件个数，在迁移不应该有太大变化，前后变化不应该超过10%
2. **数据内容检查**：数据内容中不应该出现乱码

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
| `translate` | 中英文翻译（调用"文本翻译"算子） | `source_lang`: 源语言（`zh`/`en`），`target_lang`: 目标语言（`zh`/`en`） |

### 文本翻译算子说明

当 ETL 过程中有中英文翻译需求时，可通过 `translate` 处理类型优先调用"文本翻译"算子：

- **`source_lang`**：源语言，支持 `zh`（中文）和 `en`（英文）
- **`target_lang`**：目标语言，支持 `zh`（中文）和 `en`（英文）

常见翻译场景：
  - `zh → en`：将中文列值翻译为英文
  - `en → zh`：将英文列值翻译为中文

> ⚠️ 翻译算子会对列中每个值逐条调用翻译服务，处理大数据量时可能较慢，建议结合 `limit` 参数控制处理行数或分批处理。

### 目标表不存在时的处理策略

当目标数据表不存在时，会根据目标数据源的类型自动创建目标表：

| 目标数据源类型 | 创建方式 |
|------|------|
| SQLite | 根据迁移后的数据列结构自动执行 `CREATE TABLE` 语句创建表 |
| CSV | 自动创建 CSV 文件，首行写入列名 |
| Excel | 自动创建 Excel 文件和工作表，首行写入列名 |

> ✅ 自动创建表时，表结构（列名、列顺序）基于经过列删除、列转换、列名映射、列添加等处理后的最终数据结构。

### 目标表已存在时的处理策略

当目标数据表已经存在时，通过 `if_table_exists` 参数控制处理方式：

| 策略 | 说明 |
|------|------|
| `fail` | 默认行为，目标表已存在时报错中止 |
| `append` | 在原表上追加数据，不修改表结构 |
| `replace` | DROP TABLE 后重建表（丢弃索引、约束、序列等） |
| `overwrite` | 清空表数据 + 自动补齐缺失列（保留表结构和索引） |
| `truncate` | 同 `overwrite` |
| `delete_rows` | DELETE 清空数据（保留表结构，不补列） |
| `upsert` | 按 id 列做 INSERT ON CONFLICT DO UPDATE（无 id 列则退化为 append） |
| `create_new` | 表已存在时自动创建新表（表名加 _1, _2 后缀），不存在则正常创建 |

> ⚠️ 使用 `append` 时，源数据的列应与目标表列兼容；使用 `add_columns` 时，仅会新增列，不会修改或删除已有列的数据。

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

### 目标表已存在时追加数据

```
将 "CSVFormTest" 的 "orders" 表迁移到 "SQLite测试数据库" 的 "orders_all" 表，
目标表已存在，追加数据（if_table_exists: append）
```

### 目标表已存在时增加列

```
将 "CSVFormTest" 的 "products" 表迁移到 "SQLite测试数据库" 的 "products" 表，
目标表已存在，增加新列（if_table_exists: add_columns），
添加 remark 列值为 "imported"
```

### 目标表已存在时删除后追加数据

```
将 "CSVFormTest" 的 "orders" 表迁移到 "SQLite测试数据库" 的 "orders_all" 表，
目标表已存在，删除原有内容后追加数据（if_table_exists: delete_append）
```

### 目标表已存在时按主键更新数据

```
将 "CSVFormTest" 的 "orders" 表迁移到 "SQLite测试数据库" 的 "orders_all" 表，
目标表已存在，按主键更新数据（if_table_exists: update）
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
| `if_table_exists` | str | ❌ | `fail` | 目标表已存在时的处理策略：`fail`（报错）、`append`（追加）、`replace`（删表重建）、`overwrite`/`truncate`（清空+补列）、`delete_rows`（清空不补列）、`upsert`（按id更新或插入）、`delete_append`（删除后追加）、`update`（按主键更新） |
| `auto_translate` | bool | ❌ | False | 中文→英文：将中文表名/列名自动翻译为英文标识符 |
| `translate_to_cn` | bool | ❌ | False | 英文→中文：将英文表名/列名自动翻译为中文（使用 LLM 翻译） |
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
6. 检查目标表是否存在：如果不存在，根据目标数据源类型自动创建目标表；如果已存在，根据 `if_table_exists` 策略处理（报错 / 追加 / 增加列 / 清空重写 / 删除后追加 / 更新）
7. 写入目标数据源

### 输出路径说明

- 如果目标数据源为文件型（CSV/Excel）且未指定 `output_dir`，默认保存到目标数据源文件所在目录
- 如果目标数据源为数据库（SQLite），数据直接写入目标表，`output_dir` 不生效
- 如需导出为独立文件，请明确指定 `output_dir` 路径

## 📁 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心迁移脚本，包含 `migrate_data()` 主函数和 `apply_column_transform()` 列转换工具函数。当列转换类型为 `translate` 时，调用"文本翻译"算子完成中英文翻译。支持通过 `if_table_exists` 参数处理目标表已存在的场景（追加数据或增加列）。当目标表不存在时，根据目标数据源类型自动创建表 |

## 常见问题与经验