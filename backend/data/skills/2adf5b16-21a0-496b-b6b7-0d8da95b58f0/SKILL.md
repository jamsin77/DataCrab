---
name: image-table-to-excel
description: 把包含表格的图片识别/解析/转换成 Excel 表，提取图片中的表格数据并导出到数据源（如交易数据、聊天上传数据），支持图片转表格、表格图片识别、图片表格转Excel、图片 OCR 表格提取，遇到非表格图片自动报错停止解析
version: "1.0.0"
skill_type: processing
tags:
  - 图片识别
  - 表格提取
  - OCR
  - Excel
  - 图片转表格
---

# 图片表格解析为 Excel

## 功能说明
使用视觉大模型识别图片中的表格，提取表头与行数据，写入目标数据源（默认为「交易数据」Excel 数据源）。如果图片不包含表格（如普通照片、文档段落、非表格截图），脚本会报错并停止解析，不会写入任何数据。

## 使用方式
```
解析图片 /path/to/table_image.png 中的表格，保存到交易数据
```
```
将图片 D:/images/报价表.jpg 解析成 Excel 表，写入交易数据的新表 parsed_image_table
```
```
把聊天上传数据里的微信图片表格识别出来，导出到文物列表数据源
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `image_path` | str | ✅ | - | 待解析的表格图片文件路径（必填） |
| `target_datasource_name` | str | ❌ | 交易数据 | 目标数据源名称（例如：交易数据、文物列表、聊天上传数据） |
| `target_table_name` | str | ❌ | parsed_image_table | 目标表名，默认 `parsed_image_table` |
| `if_table_exists` | str | ❌ | fail | 写入策略：fail/append/replace/overwrite/truncate/upsert |
| `max_retries` | int | ❌ | 2 | 视觉识别失败重试次数，默认 2 次 |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心脚本：调用 `llm_vision` 识别图片，解析表格 JSON，校验非表格图片，写入目标数据源 |

## 注意事项
- 图片路径必须是可被沙箱访问的本地文件路径（例如 `D:/images/xxx.png`）。
- 视觉模型可能因图片质量、复杂合并单元格等原因提取不准确，建议先检查图片清晰度。
- 非表格图片会返回 `success: False`，不会写入任何数据。