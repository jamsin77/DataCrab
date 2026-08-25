---
name: data-etl
description: 把数据从 Excel/CSV/数据库等源表导出/迁移/同步/搬运到另一个数据源（如 SQLite），同时支持列名映射、中英文翻译、格式清洗、空值填充、类型转换等处理，适合多源数据整合、报表数据准备、数据搬家、导入导出等场景
version: "1.0.0"
author: DataCrab
skill_type: processing
tags:
  - 数据迁移
  - 列名转换
  - 数据处理
  - 语言翻译
---

# 数据 ETL 技能 (Data ETL)

## 📌 典型使用场景

当您需要将分散在 Excel、CSV、SQLite 等不同数据源中的业务数据整合到统一的数据库或文件时，往往还要顺便做一些数据清洗和转换。  
本技能就是为这类场景设计的：它能够帮您自动完成从源到目标的“搬运”工作，同时支持：

- **列名不一致？** 可以按映射关系自动重命名，甚至自动翻译中英文列名。
- **有些列用不上？** 直接删除不需要的列。
- **缺了关键字段？** 添加常量列（例如数据来源、批次号）。
- **数据格式不统一？** 对列值进行 trim、大小写转换、空值填充、类型转换、添加前缀/后缀、替换等处理。
- **需要中英文翻译？** 对指定列调用翻译算子，逐条翻译，适合跨语言数据整合。
- **目标表已存在？** 支持追加、替换、清空重写、按主键更新等多种策略，不会盲目覆盖。
- **目标表不存在？** 自动根据目标数据源类型建表，无需手动准备。

### 真实场景举例

- 将文物系统导出的 Excel 表格迁移到 SQLite 分析库，同时把中文名称翻译成英文供国际团队使用。
- 将多个 CSV 文件合并到 SQLite 的同一张订单表中，新数据追加，旧数据按主键更新。
- 从测试数据库搬数据到正式环境，要求自动删除调试列、统一日期格式，并添加“数据来源”字段。

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