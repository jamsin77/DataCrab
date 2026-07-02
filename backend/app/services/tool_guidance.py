"""工具诚实能力表

借鉴 DeepAnalyze 的"工具诚实"原则：把每个工具的真实能力、覆盖率和局限性
以能力表形式注入系统提示，让 Agent 基于完整信息自主决策工具组合，
而不是靠"优先使用 X"这类推荐性语言来引导。
"""

TOOL_CAPABILITY_TABLE = """## 工具能力表（诚实声明）

以下是各工具的真实能力和已知局限。请基于这些信息自主选择工具组合：

| 工具 | 覆盖率 | 精确度 | 已知局限 |
|------|--------|--------|----------|
| query_table_data | 默认最多100行 | 高 | 筛选/排序时先加载最多50000行到内存再过滤，大表可能较慢；不支持跨表JOIN，复杂关联需写算子脚本 |
| get_table_schema | 仅采样5行推断类型 | 中 | 行数依赖get_table_stats，部分数据源可能不支持；类型推断基于样本，可能有偏差 |
| list_user_datasources | 全量 | 高 | 会逐个连接数据源获取表列表，数据源多时较慢 |
| list_user_file_links | 全量 | 高 | 仅返回目录类型的链接 |
| save_file_to_link | 精确写入 | 高 | 只能写入CSV格式文本；路径必须在链接目录范围内（沙箱限制） |
| profile_data | 全表扫描 | 高 | 大表（万行以上）较慢；返回的是统计概览，不含原始数据行 |
| check_data_standards | 按列检查 | 高 | 格式类标准用确定性正则；命名规范检查基于规则，可能有边界情况 |
| check_data_quality | 按维度检查 | 高 | 完整性/唯一性用确定性逻辑；业务逻辑一致性需要LLM判断，可能有偏差 |
| check_data_security | 全表扫描 | 高 | PII识别基于正则+关键词，复杂场景可能遗漏；不修改数据，仅报告 |
| check_etl_quality | 源表+目标表对比 | 高 | 需要源和目标都可访问；金额汇总对数需要指定金额列 |
| kb_search | top_k默认5 | 中 | 仅搜索已上传文档的向量索引，top_k硬限制必然遗漏相关内容；PDF/DOCX仅纯文本，表格图片丢失；不支持结构化数据源 |

### 工具选择原则
- 需要原始数据 → query_table_data（注意 limit 限制）
- 需要表结构 → get_table_schema
- 需要数据概览/统计 → profile_data（比 query_table_data 更适合了解全貌）
- 需要检查数据质量 → check_data_quality / check_data_standards / check_data_security
- 需要跨表关联/复杂计算 → 写算子脚本（query_table_data 不支持 JOIN）
- 需要保存结果 → save_file_to_link
- 需要从文档/手册/报告中查找信息 → kb_search（注意 top_k 限制，需全面时多次不同关键词搜索）

注意：以上是能力描述，不是强制路由。请根据具体任务自主判断。
"""


def get_tool_guidance() -> str:
    """获取工具能力表文本，用于注入 system prompt。"""
    return TOOL_CAPABILITY_TABLE
