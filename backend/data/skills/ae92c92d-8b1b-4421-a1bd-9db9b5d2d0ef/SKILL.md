---
name: document-rule-extractor
description: 解析 PDF 或 Word 格式的规则文档，自动提取规则并导入/更新规则知识库表，支持覆盖已存在的规则。用户说“把规则文档解析入库”“提取规则到知识库”“更新规则表”“解析规则文档”时匹配本技能。
version: "1.0.0"
skill_type: processing
tags:
  - 规则提取
  - PDF
  - Word
  - 知识库
  - 文档解析
---

# 文档规则提取入库

## 功能说明
从 PDF / Word（.docx）格式的规则文档中提取结构化规则，写入目标数据源的规则知识库表。支持自动判断规则是否已存在（按规则编号 rule_code），已存在的规则会被新规则覆盖，不存在的规则追加写入。

提取的规则字段包括：
- `rule_code`：规则编号（唯一键）
- `rule_name`：规则名称
- `category`：规则分类（标准 / 质量 / 安全）
- `applicable_fields`：适用字段
- `format_regex`：格式正则表达式
- `check_logic`：检查逻辑描述
- `severity`：严重等级（info / warn / error / critical）
- `description`：规则详细解释
- `source_document`：来源文档路径
- `updated_at`：更新时间

## 使用方式
```
解析文件 "/data/rules/风控规则.pdf" 并写入 "凭证检索库" 的 rules_knowledge_base 表
```
```
从 "/data/rules/贷款规则.docx" 提取规则，更新到 "凭证检索库" 的 rules_knowledge_base 表，覆盖已存在的规则
```
```
解析多个文件：/data/rules/规则1.pdf,/data/rules/规则2.docx，写入知识库
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `document_paths` | str | ✅ | - | PDF / Word 文件路径，多个用英文逗号分隔 |
| `target_datasource_name` | str | ❌ | 凭证检索库 | 目标数据源名称（用于写入规则表） |
| `target_table_name` | str | ❌ | rules_knowledge_base | 目标规则表名 |
| `if_table_exists` | str | ❌ | replace | 写入策略：fail/append/replace/overwrite/truncate 等 |

> 说明：目标数据源默认为“凭证检索库”（postgresql），用户可根据实际需求调整。如果目标表不存在，脚本会自动创建。

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心处理脚本：解析文档、LLM 提取规则、合并写入 |

## 注意事项
- PDF 解析需要环境安装 `pypdf` 或 `PyPDF2` 库；Word 解析需要 `python-docx` 库。
- 如果所有文档解析失败，脚本会返回 `success=False` 并报错。
- 规则覆盖以 `rule_code` 为唯一键，请确保 LLM 提取的规则编号在文档中唯一或可自动生成不冲突的编号。