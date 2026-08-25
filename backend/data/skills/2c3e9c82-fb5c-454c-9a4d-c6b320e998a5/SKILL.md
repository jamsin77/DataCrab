---
name: cultural-relics-expert
display_name: 文物检索专家
description: 从权威网站检索/查询/搜索各级保护文物信息，生成文物知识库，支持多条件检索、关键字搜索、名录查询，适合文物数据采集、文化遗产信息收集等场景
version: 1.0.0
category: data_collection
skill_type: processing
tags:
  - 文物
  - 检索
  - 知识库
  - 数据采集
  - 文化遗产
author: DataCrab
---

# 文物检索专家

## 功能概述

文物检索专家是一个强大的数据采集和检索技能，能够：
- 从权威网站采集各级保护文物信息
- 构建本地文物知识库
- 支持多条件检索文物
- 提供统计分析功能
- 支持导出为Excel格式

## 核心功能

### 1. 数据采集
从多个权威网站采集文物信息：
- 维基百科（Wikipedia）
- 百度百科
- 国家文物局官网

### 2. 知识库管理
- 自动构建本地知识库（JSON格式）
- 支持增量更新和去重
- 持久化存储

### 3. 多条件检索
支持按以下条件检索：
- 名称（模糊匹配）
- 时代（模糊匹配）
- 地区（模糊匹配）
- 保护级别
- 文物类型
- 批次

### 4. 统计分析
- 按时代统计文物分布
- 按级别统计文物分布
- 按类型统计文物分布
- 按地区统计文物分布

### 5. 数据导出
- 导出为Excel格式
- 支持数据备份和分享

## 使用方法

### 在DataCrab聊天中使用

```
用户：帮我构建文物知识库
AI：正在从权威网站采集文物信息...

用户：检索明代的文物
AI：找到 XX 条明代文物...

用户：统计北京地区有多少文物
AI：北京地区共有 XX 处文物...

用户：导出文物数据到Excel
AI：已导出到 cultural_relics_export.xlsx
```

### Python调用示例

```python
from cultural_relics_expert import cultural_relics_expert

# 1. 构建知识库
result = cultural_relics_expert(
    action="build",
    sources="wikipedia,baidu,gov",
    max_items=100
)

# 2. 检索文物
result = cultural_relics_expert(
    action="search",
    era="明",
    location="北京",
    limit=20
)

# 3. 获取统计
stats = cultural_relics_expert(action="stats")

# 4. 导出数据
export = cultural_relics_expert(action="export")
```

## 参数说明

### action（操作类型）

| 值 | 说明 |
|----|------|
| search | 检索文物 |
| build | 构建知识库 |
| stats | 获取统计信息 |
| export | 导出知识库 |

### 检索参数

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| name | str | 文物名称（模糊匹配） | "故宫" |
| era | str | 时代（模糊匹配） | "明"、"唐" |
| location | str | 地址/地区（模糊匹配） | "北京"、"陕西" |
| level | str | 保护级别 | "全国重点文物保护单位" |
| relic_type | str | 文物类型 | "古建筑"、"古遗址" |
| batch | str | 批次 | "第一批" |
| limit | int | 返回数量限制 | 100 |

### 构建参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| sources | str | 数据来源（逗号分隔） | "wikipedia,baidu,gov" |
| max_items | int | 每来源最大爬取数量 | 100 |
| update_mode | str | 更新模式（append/replace） | "append" |

## 使用示例

### 示例1: 构建知识库

```python
result = cultural_relics_expert(
    action="build",
    sources="wikipedia,baidu,gov",
    max_items=200,
    update_mode="append"
)
```

### 示例2: 检索明代文物

```python
result = cultural_relics_expert(
    action="search",
    era="明",
    limit=50
)
```

### 示例3: 组合条件检索

```python
result = cultural_relics_expert(
    action="search",
    era="唐",
    location="陕西",
    relic_type="古建筑",
    limit=30
)
```

### 示例4: 获取统计信息

```python
stats = cultural_relics_expert(action="stats")
print(f"知识库总数: {stats['statistics']['总数']}")
```

### 示例5: 导出知识库

```python
export = cultural_relics_expert(action="export")
print(f"导出路径: {export['output_path']}")
```

## 生成的文件

### cultural_relics_kb.json
知识库数据文件，包含：
- relics: 文物列表
- metadata: 元数据（总数、最后更新时间等）

### cultural_relics_export.xlsx
导出的Excel文件，包含所有文物信息。

## 最佳实践

### 1. 首次使用
先构建知识库：
```python
cultural_relics_expert(action="build", max_items=500)
```

### 2. 定期更新
每周更新一次（使用append模式）：
```python
cultural_relics_expert(
    action="build",
    max_items=100,
    update_mode="append"
)
```

### 3. 检索优化
使用limit限制返回数量：
```python
cultural_relics_expert(
    action="search",
    era="明",
    limit=20
)
```

## 注意事项

1. **网络连接**：构建知识库需要网络连接
2. **首次使用**：建议先构建知识库，否则检索结果为空
3. **数据准确性**：爬取的数据可能不完整，建议人工核实重要信息
4. **法律合规**：请遵守相关网站的使用条款
5. **知识库大小**：大量数据会增加文件大小，建议定期清理

## 更新日志

### v1.0.0 (2026-06-14)
- 初始版本发布
- 支持从维基百科、百度百科、国家文物局采集数据
- 支持多条件检索
- 支持统计分析
- 支持导出Excel