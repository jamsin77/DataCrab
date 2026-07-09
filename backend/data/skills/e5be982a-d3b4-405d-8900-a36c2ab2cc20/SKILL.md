---
name: extract-image-info
description: 从图片（身份证、营业执照等）中提取关键信息，写入指定数据源，识别失败的标记为待人工审核
version: "1.0.0"
tags:
  - 图片识别
  - OCR
  - 信息提取
  - 人工审核
---

# 图片关键信息提取

## 功能说明
从数据源中读取包含图片URL的记录，调用大模型（多模态LLM）识别图片内容，提取身份证、营业执照等证件上的关键信息，将提取结果写入目标数据源。对于识别失败、置信度低或无图片的记录，自动打上"待人工审核"标记。

支持文档类型：
- **身份证**：姓名、性别、民族、出生日期、住址、身份证号、签发机关、有效期限
- **营业执照**：统一社会信用代码、企业名称、企业类型、法定代表人、注册资本、成立日期、营业期限、经营范围、住所
- **自动识别**：由LLM自动判断文档类型并提取所有可见关键信息

## 使用方式
```
从 "文物库" 的 "relic" 表中提取 "image_url" 列的图片信息，写入 "文物库" 的 "image_extracted_info" 表
```
```
提取 "交易数据" 中 "印尼工程机械采购询价单" 表 "附件图片" 列的身份证信息，写入 "文物库" 的 "id_card_info" 表，文档类型为 "id_card"
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `source_datasource_name` | str | ✅ | - | 源数据源名称 |
| `source_table_name` | str | ✅ | - | 源表名 |
| `target_datasource_name` | str | ✅ | - | 目标数据源名称 |
| `target_table_name` | str | ✅ | - | 目标表名 |
| `image_column` | str | ✅ | - | 图片URL/路径列名 |
| `doc_type` | str | ❌ | auto | 文档类型：id_card/business_license/auto |
| `if_table_exists` | str | ❌ | fail | 写入策略：fail/append/replace/overwrite/truncate/upsert |
| `batch_size` | int | ❌ | 500 | 分批写入批次大小 |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心处理脚本：读取图片URL → LLM识别 → 解析提取结果 → 分批写入 → 标记异常 |