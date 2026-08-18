---
name: split-table-export
description: 根据指定列或AI推断的分类规则，将数据表分割并保存为包含多个Sheet的Excel文件
version: 1.0.0
tags: 
  - data-processing
  - export
  - ai-mapping
---

# 数据表分割导出 Skill

## 1. 功能说明
本 Skill 用于将指定数据源中的数据表按照特定列的值进行分割，并将分割后的数据分别保存到一个 Excel 文件的不同 Sheet 中。

**核心特性：**
- **基础分割**：直接按照指定列的唯一值进行分割。
- **智能映射**：支持通过自然语言描述分割意图（如"按地级市分割"），利用 AI 辅助将原始列值（如"区县"）映射到目标分类（如"地级市"）。
- **自动导出**：生成格式规范的 Excel 文件，每个分类对应一个 Sheet。

## 2. 参数说明

| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| datasource | string | 是 | 数据源名称（如 "SQLite测试数据库"） |
| tables | string | 是 | 待分割的数据表名称 |
| split_column | string | 是 | 用于分割的列名 |
| output_filename | string | 是 | 输出的 Excel 文件名（无需后缀） |
| mapping_instruction | string | 否 | 映射指令。如果提供，将尝试使用 AI 将列值映射到新分类。例如："请根据区县名称判断所属的地级市" |

## 3. 命令行调试

### 必选参数示例
```bash
python main.py --datasource "文物测试数据库" --tables "文物信息表" --split_column "区县" --output_filename "文物按区县分类"
```

### 全部参数示例
```bash
python main.py --datasource "文物测试数据库" --tables "文物信息表" --split_column "区县" --output_filename "文物按地级市分类" --mapping_instruction "请判断以下区县属于哪个地级市"
```

## 4. 脚本说明
- **scripts/main.py**: 主执行脚本，负责获取数据、调用映射逻辑、分割数据及导出 Excel。

## 5. 输出结果
脚本执行完成后，将在当前工作目录生成指定的 Excel 文件，控制台会输出每个 Sheet 的写入日志。
