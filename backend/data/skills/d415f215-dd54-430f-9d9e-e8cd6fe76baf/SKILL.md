---
name: semantic-merge-records
description: 按条件筛选源数据，基于字段语义与大模型匹配将源数据归并到目标数据中，支持归并校验
version: "1.0.1"
tags:
  - 归并
  - 语义匹配
  - 数据清洗
  - 去重
---

# 语义归并结构化数据

## 功能说明
从指定数据源表中，按筛选条件选出"源数据"（待归并数据），剩余数据作为"目标数据"。利用大模型对指定字段的语义进行相似性匹配，将源数据归并到语义最相似的目标记录中。归并后的数据默认写入一张新的数据表，不影响原始表数据。

**归并策略**：
- `keep_target`：匹配成功时保留目标记录、丢弃源记录（默认）
- `merge_fields`：匹配成功时将源记录中目标记录缺失的字段补入目标记录

**校验规则**：
1. 归并后总条数 ≤ 原始总条数（不应增多）
2. 减少条数 ≤ 源数据条数（减少的不超过被归并的）

## 注意事项
- 如果用到翻译，尽量使用文本翻译算子，而非在归并流程中自行处理翻译逻辑。
- 归并结果默认写入新表 `{table_name}_merged`，不会覆盖原始表。

## 使用方式
```
将 "文物列表" 的 "全国文物" 表中 "批次==第七批" 的数据按 "名称" 字段语义归并
```
```
从 "文物库" 的 "relic" 表中筛选 "status==duplicate" 的数据，按 "name" 字段语义归并到其他数据，输出到 relic_merged 表
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `datasource_name` | str | ✅ | - | 数据源名称 |
| `table_name` | str | ✅ | - | 表名 |
| `filter_condition` | str | ✅ | - | 筛选条件，支持 `列名==值`、`列名!=值`、`列名 contains 值` 或自然语言 |
| `merge_field` | str | ✅ | - | 用于语义匹配的字段名 |
| `output_table_name` | str | ❌ | {table_name}_merged | 输出表名，默认生成新表 |
| `if_table_exists` | str | ❌ | overwrite | 写入策略：fail/append/replace/overwrite/truncate/upsert |
| `merge_strategy` | str | ❌ | keep_target | 归并策略：keep_target/merge_fields |
| `batch_size` | int | ❌ | 1000 | 数据写入批次大小 |
| `llm_batch_size` | int | ❌ | 20 | LLM 语义匹配批次大小 |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心归并处理脚本，含筛选、语义匹配、归并执行、校验、写入 |