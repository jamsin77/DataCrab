---
name: semantic-classify
description: 对数据列进行AI语义分类/标注/提取，支持自动检测分类类别或使用预定义类别，可选择新增列或更新已有列，适合从地址提取省市、文本分类、数据打标、语义标注等场景
version: "1.0.0"
skill_type: processing
tags:
  - 语义分类
  - LLM
  - 数据标注
  - 文物
  - 交易数据
---

# 语义分类技能 (semantic_classify)

## 功能描述
对数据源中指定列的值进行语义分类，使用LLM自动识别类别或将值归入预定义类别，并将分类结果写回数据源。此外，支持根据某一列的内容进行语音解析或提取，用提取后的内容进行分类。

## 使用方式
```
对 "文物列表" 的 "文物信息表" 中 "材质" 列进行语义分类
```
```
从 "交易数据" 的 "交易记录" 表中，对 "交易类型" 列进行分类，预定义类别为"买入,卖出,置换"
```
```
对 "文物列表" 的 "文物信息表" 中 "年代" 列提取内容后分类
```

## 参数规范

| 参数名 | 别名 | 类型 | 必选 | 默认值 | 说明 |
|--------|------|------|------|--------|------|
| datasource_name | datasource, source_datasource, source_datasource_name | str | 是 | - | 数据源名称 |
| table_name | table, source_table, source_table_name | str | 是 | - | 表名 |
| column_name | column, classify_column, source_column | str | 是 | - | 要分类的列名 |
| target_column | output_column, result_column, new_column_name | str | 否 | {column}_分类 | 分类结果写入的列名 |
| mode | write_mode, column_mode | str | 否 | add | add=新增列 / update=更新已有列 |
| categories | category_list, predefined_categories | str | 否 | "" | 预定义类别（逗号分隔），留空则AI自动检测 |
| batch_size | llm_batch_size | int | 否 | 50 | LLM每批处理的唯一值数量 |
| if_table_exists | write_strategy, table_exists_strategy | str | 否 | replace | 写入策略: fail/append/replace/overwrite/truncate/delete_rows/upsert |
| extract_column | extract_from_column | str | 否 | - | 用于语音解析或提取的列名，留空则不进行提取 |

## 输出
返回包含以下字段的字典：
- success: 是否成功
- total_rows: 总行数
- classified_column: 实际分类的列名
- target_column: 分类结果列名
- unique_values_classified: 分类的唯一值数量
- categories_found: 检测到的类别列表
- category_distribution: 类别分布字典
- rows_written: 写入行数
