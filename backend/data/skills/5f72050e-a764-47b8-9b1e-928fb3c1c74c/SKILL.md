---
description: 对数据表进行统计分析、排序、分组聚合、TopK、频次统计、描述统计和综合摘要，支持生成报表和统计图表，适合数据概览、统计分析、分布查看、数据汇总等场景
name: data-statistics
skill_type: analysis
tags:
- 分析
- 排序
- 汇总
- TopK
- 图表
- 报表
version: 1.1.0
---

# 数据表统计

## 功能说明
对指定数据源中的单个数据表执行多种分析操作，支持：
- **排序**：按指定列排序，返回全表或指定行数。
- **TopK**：按指定列排序，返回前 K 条记录。
- **分组聚合**：按某列分组，对另一列进行聚合（求和、平均、计数、最大值、最小值）。
- **频次统计**：统计某列各值的出现次数。
- **描述统计**：对数值列输出均值、标准差、分位数等统计量。
- **综合摘要**：输出表的行数、列数、类型、缺失值等基本信息。
- **报表与图表**：将分析结果导出为 HTML 报表或统计图表（折线图、柱状图、饼图等），并支持直接下载图表文件。

结果可写入数据源的新表，或仅返回预览数据；图表和报表以文件形式输出到数据源指定路径，并提供下载链接。

## 使用方式
```
从 "文物列表" 的 "national_key_cultural_relic_protection_units" 表中按保护级别分组，统计各单位数量
```
```
对 "交易数据" 的 "印尼工程机械采购报价表_2026" 按 "总价" 降序排列，取前 10 条
```
```
查看 "文物库" 的 "relic" 表的描述统计
```
```
按 "销售数据" 的 "monthly_sales" 表按月分组统计销售额，并生成柱状图
```
```
分析 "用户行为" 的 "events" 表事件类型频次，输出饼图并下载
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `datasource_name` | str | ✅ | - | 数据源名称 |
| `table_name` | str | ✅ | - | 要统计的表名 |
| `stat_type` | str | ✅ | - | 统计类型：sort / topk / groupby / value_counts / describe / summary |
| `sort_column` | str | ❌ | - | 排序依据列（用于 sort、topk） |
| `sort_order` | str | ❌ | desc | 排序方向：asc / desc |
| `top_k` | int | ❌ | 10 | 返回前几条记录（用于 topk） |
| `groupby_column` | str | ❌ | - | 分组依据列（用于 groupby、value_counts） |
| `agg_column` | str | ❌ | - | 聚合目标列（用于 groupby） |
| `agg_func` | str | ❌ | count | 聚合函数：sum / mean / max / min / count |
| `output_table` | str | ❌ | - | 输出表名（不指定则仅返回预览） |
| `if_table_exists` | str | ❌ | replace | 写入策略：fail / append / replace / overwrite / truncate / upsert / create_new |
| `chart_type` | str | ❌ | - | 图表类型：line / bar / pie / ... 不指定则不生成图表 |
| `chart_title` | str | ❌ | 自动生成 | 图表标题 |
| `chart_x_column` | str | ❌ | 分组列或索引列 | 图表 X 轴数据列 |
| `chart_y_column` | str | ❌ | 聚合结果列 | 图表 Y 轴数据列 |
| `output_format` | str | ❌ | html | 报表输出格式：html / png / pdf（仅图表） |
| `download` | bool | ❌ | false | 是否直接返回下载链接 |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心统计脚本，根据 `stat_type` 路由到对应处理函数 |
| `chart.py` | 图表生成模块，支持折线图、柱状图、饼图等常见图表，并输出为 HTML 或图片文件 |
| `report.py` | 报表组装模块，可将分析结果与图表组合为完整 HTML 报表 |