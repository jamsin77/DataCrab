---
name: metadata-sync-ai-enhance
description: 跨多个数据源收集表元数据，使用AI增强描述/标签/分类，检测跨数据源关系并写入元数据注册表
version: "1.0.0"
tags:
  - 元数据
  - 数据治理
  - AI增强
  - 跨数据源
  - 同步
---

# 元数据同步与AI增强

## 功能说明
针对指定的多个数据源（文物列表、文物库、交易数据、凭证库、凭证检索库），自动完成以下工作：

1. **元数据收集**：遍历每个数据源的每张表，收集表结构（列名、类型）、行数、样本数据
2. **AI增强**：调用大模型为每张表生成中文描述、列含义说明、数据分类标签、数据质量观察
3. **跨源关系检测**：AI分析不同数据源中表与表之间的关联（同数据副本/互补/结构相似/引用关系）
4. **元数据写入**：将增强后的元数据和关系信息写入目标数据源的两张表（metadata_sync + metadata_cross_source_relations）

## 使用方式
```
同步并AI增强所有数据源的元数据
```
```
对 "文物列表,文物库" 的元数据进行同步和AI增强，写入到 "文物库"
```
```
同步 "交易数据,凭证检索库" 的元数据到 "凭证检索库"，关闭跨源分析
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `datasource_names` | str | ❌ | "" | 要处理的数据源名称，逗号分隔；空则处理全部5个数据源 |
| `target_datasource_name` | str | ❌ | 文物库 | 元数据写入的目标数据源名称 |
| `metadata_table_name` | str | ❌ | metadata_sync | 元数据注册表名 |
| `relations_table_name` | str | ❌ | metadata_cross_source_relations | 跨源关系表名 |
| `enable_ai_enhancement` | bool | ❌ | True | 是否启用AI增强 |
| `enable_cross_source_analysis` | bool | ❌ | True | 是否启用跨源关系检测 |
| `sample_size` | int | ❌ | 5 | 每张表采样行数（用于AI分析） |
| `ai_batch_size` | int | ❌ | 5 | AI增强每批处理的表数量 |
| `write_batch_size` | int | ❌ | 500 | 写入数据源时的批次大小 |
| `if_table_exists` | str | ❌ | replace | 写入策略：fail/append/replace/overwrite/truncate |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心处理脚本：元数据收集 → AI增强 → 跨源关系检测 → 写入注册表 |