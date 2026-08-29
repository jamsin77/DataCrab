---
name: match-and-merge-records
description: 在多个数据表/数据源之间检测匹配、重复的记录，支持查重、对账、跨表比对、找重复、去重、合并重复数据、标记重复项、导出重复记录；用户说"检测重复""匹配数据""对账""查重""跨表找重复""合并重复表""数据对账"时使用此技能
version: "1.0.0"
skill_type: processing
tags:
  - 匹配
  - 去重
  - 查重
  - 对账
  - 跨表比对
  - 重复检测
  - 数据合并
---

# 跨表匹配与去重

## 功能说明

在指定的多个数据表（可跨数据源）之间检测匹配/重复的记录，支持按一个或多个关键列（如名称、编号、ID 等）进行匹配。检测到匹配结果后，可根据用户选择的操作执行后续处理：

- `detect`：仅检测并返回重复记录（不改数据）
- `export`：导出重复记录到输出表
- `deduplicate`：去重（保留第一条）并写入输出表
- `mark`：为所有记录添加重复标记（`is_duplicate`、`duplicate_group`），写入输出表

适用于文物、凭证、交易数据等场景下跨表查重、对账、合并重复数据。

## 使用方式

```
检测 "文物列表.全国文物" 和 "文物库.national_cultural_relic_protection_unit" 中按"名称"匹配的重复记录
```

```
跨表比对 "文物列表.全国重点文物保护单位" 和 "聊天上传数据.全国重点文物保护单位_20260817_080029"，按"名称"查重
```

```
在 "凭证检索库" 的多个 credential_ocr_results 表中按"身份证号"检测重复，导出重复项
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `table_specs` | str | ✅ | - | 表规范列表，格式为 `数据源名.表名`，多个用逗号分隔，如 `文物列表.全国文物,文物库.national_cultural_relic_protection_unit` |
| `match_columns` | str | ✅ | - | 匹配列名，多个用逗号分隔，如 `名称` 或 `名称,编号` |
| `action` | str | ❌ | detect | 操作类型：detect / export / deduplicate / mark |
| `output_datasource` | str | ❌ | None | 输出数据源名称（action 为 export/deduplicate/mark 时必填） |
| `output_table` | str | ❌ | None | 输出表名（action 为 export/deduplicate/mark 时必填） |
| `keep` | str | ❌ | first | deduplicate 时保留哪条记录：first（第一条）/ last（最后一条） |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心匹配/查重/去重脚本，并发加载多表数据，支持跨数据源匹配和多种操作 |

## 注意事项

- `table_specs` 中数据源名与表名用第一个 `.` 分隔（数据源名不含点）
- 不同表中 `match_columns` 指定的列需存在（脚本会用 `resolve_column` 自动解析，如 `名称`→`name`）
- `detect` 不写入任何数据，仅返回匹配结果
- `export` / `deduplicate` / `mark` 需要指定 `output_datasource` 和 `output_table`
- 数据量大时脚本会自动分批写入，每批 1000 行