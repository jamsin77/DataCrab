---
name: migrate-and-translate-to-chinese
description: 把数据从一个数据源原样迁移/搬移/复制/同步到另一个数据源或数据表，支持导入、导出、搬数据、数据搬运，搬过去时非中文内容自动翻译成中文，其他数据保持不变
version: "1.0.0"
skill_type: processing
tags:
  - 迁移
  - 翻译
  - 数据同步
  - 中文翻译
  - 搬数据
---

# 数据迁移并翻译中文

## 功能说明
将源数据源中的表数据原封不动地迁移到目标数据源。迁移过程中自动检测文本字段：
- 已经是中文的内容**原样保留**
- 不是中文的文本（英文、日文、韩文等）**自动翻译成简体中文**后再写入目标
- 数字、日期、符号、列名、数据类型保持不变

适用于跨数据源的数据迁移、搬运、同步、备份、导入导出等场景。

当前环境中的真实数据源（均可作为源或目标，通过 `call_tool("list_user_datasources", by_name=...)` 动态查找）：
- 文物列表（excel）
- 文物库（postgresql）
- 交易数据（excel）
- 凭证库（generic_file）
- 凭证检索库（postgresql）
- 培训视频（generic_file）
- 培训知识库（chroma）
- 聊天上传数据（generic_file）表：`交易数据_20260904_080023.png`、`交易数据_验证_20260908_20260909_015320.xlsx`、`WPS表格工作表_20260915_081545.xls`

## 使用方式
```
把 "交易数据" 数据源里的表迁移到 "文物库" 数据源，非中文翻译成中文
```
```
从 "聊天上传数据" 数据源把 "交易数据_验证_20260908_20260909_015320.xlsx" 迁移到 "凭证库"，翻译成中文
```
```
将 "文物列表" 的 artifacts 表同步到 "凭证库"，保留非中文原文（不翻译）
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `source_datasource_name` | str | ✅ | - | 源数据源名称 |
| `source_table_name` | str | ✅ | - | 源表名（或源文件名） |
| `target_datasource_name` | str | ✅ | - | 目标数据源名称 |
| `target_table_name` | str | ❌ | 与源表同名 | 目标表名，不填默认同源表名 |
| `translate_non_chinese` | bool | ❌ | True | 是否将非中文文本翻译成中文 |
| `if_table_exists` | str | ❌ | replace | 写入策略：fail/append/replace/overwrite/truncate/upsert |
| `batch_size` | int | ❌ | 1000 | 分批写入大小 |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心迁移与翻译脚本，支持大表分页读取、批量翻译、分批写入 |