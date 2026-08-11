"""工具诚实能力表

借鉴 DeepAnalyze 的"工具诚实"原则：把每个工具的真实能力、覆盖率和局限性
以能力表形式注入系统提示，让 Agent 基于完整信息自主决策工具组合，
而不是靠"优先使用 X"这类推荐性语言来引导。
"""

# 主对话工具能力表（共享工具 + 扩展工具，不含调试工具）
_MAIN_TOOL_CAPABILITY_TABLE = """## 工具能力表（诚实声明）

| 工具 | 覆盖率 | 精确度 | 已知局限 |
|------|--------|--------|----------|
| query_table_data | 默认最多100行 | 高 | 筛选/排序时先加载最多50000行到内存再过滤，大表可能较慢；不支持跨表JOIN，复杂关联需写算子脚本 |
| get_table_schema | 仅采样5行推断类型 | 中 | 行数依赖get_table_stats，部分数据源可能不支持；类型推断基于样本，可能有偏差 |
| list_user_file_links | 全量 | 高 | 仅返回目录类型的链接 |
| save_file_to_link | 精确写入 | 高 | 只能写入CSV格式文本；路径必须在链接目录范围内（沙箱限制） |
| profile_data | 全表扫描 | 高 | 大表（万行以上）较慢；返回的是统计概览，不含原始数据行 |
| check_data_standards | 按列检查 | 高 | 格式类标准用确定性正则；命名规范检查基于规则，可能有边界情况 |
| check_data_quality | 按维度检查 | 高 | 完整性/唯一性用确定性逻辑；业务逻辑一致性需要LLM判断，可能有偏差 |
| check_data_security | 全表扫描 | 高 | PII识别基于正则+关键词，复杂场景可能遗漏；不修改数据，仅报告 |
| check_etl_quality | 源表+目标表对比 | 高 | 需要源和目标都可访问；金额汇总对数需要指定金额列 |
| kb_search | top_k默认5 | 中 | 仅搜索已上传文档的向量索引，top_k硬限制必然遗漏相关内容；PDF/DOCX仅纯文本，表格图片丢失；不支持结构化数据源 |

以上是能力描述，不是强制路由。请根据具体任务自主判断。
"""

# 调试模式工具能力表（调试工具，不含共享工具）
_DEBUG_TOOL_CAPABILITY_TABLE = """## 调试工具能力表（诚实声明）

| 工具 | 输出量 | 精确度 | 已知局限 |
|------|--------|--------|----------|
| edit_and_run / edit_script | 小（只输出 old/new 片段） | 高（精确字符串匹配） | old_string 必须逐字唯一匹配；不唯一需补上下文；找不到时先 read_script 查看逐字内容 |
| modify_and_run / modify_script | 大（输出整个函数/脚本） | 中（函数级合并，同名替换） | 输出量大可能截断；LLM 重生成整脚本可能丢 import；支持一次输出多个函数（同名替换，新函数自动插入 if __name__ 之前） |
| read_script | 无（只读） | 高（逐字+行号） | scope=script 读用户脚本全文（大脚本占 token，可指定 function_name）；scope=platform 读平台源码指定行范围（只读不可修改） |
| grep_script | 无（只读） | 高（正则+行号） | scope=script 搜用户脚本定位 old_string；scope=platform 搜平台源码追踪错误来源；只返回匹配行+上下文，比 read_script 省 token |

以上是能力描述，不是强制路由。请根据具体任务自主判断。
"""

TOOL_CAPABILITY_TABLE = _MAIN_TOOL_CAPABILITY_TABLE

PLATFORM_CAPABILITIES = {
    "connector": {
        "excel": {
            "write_table_data": {"create_new_file": False, "create_new_sheet": False,
                                 "if_table_exists": ["fail", "append", "overwrite"]},
            "execute_sql": False,
        },
        "csv": {
            "write_table_data": {"create_new_file": True,
                                 "if_table_exists": ["fail", "append", "overwrite"]},
            "execute_sql": False,
        },
        "sqlite": {
            "write_table_data": {"create_new_table": True,
                                 "if_table_exists": ["fail", "append", "replace", "overwrite",
                                                     "truncate", "delete_rows", "upsert", "create_new"]},
            "execute_sql": True,
        },
        "postgresql": {
            "write_table_data": {"create_new_table": True,
                                 "if_table_exists": ["fail", "append", "replace", "overwrite",
                                                     "truncate", "delete_rows", "upsert", "create_new"]},
            "execute_sql": True,
        },
        "mysql": {
            "write_table_data": {"create_new_table": True,
                                 "if_table_exists": ["fail", "append", "replace", "overwrite",
                                                     "truncate", "delete_rows", "upsert", "create_new"]},
            "execute_sql": True,
        },
    },
    "sandbox": {
        "async_support": False,
        "network_access": False,
        "available_functions": [
            "write_table_data", "get_table_data", "query_table_data", "execute_sql",
            "get_table_schema", "list_tables", "iter_table_data", "llm_chat", "llm_vision",
            "extract_video_info", "extract_keyframes",
            "log", "read_file", "write_file", "compute_map", "call_operator",
            "get_datasource_id_by_name", "resolve_column",
        ],
    },
    "llm": {
        "thinking": "已开启（推理后输出+调工具，对齐 OpenCode）",
        "rate_limit_retry": "指数退避(429/超时/500)",
    },
    "framework": {
        "max_debug_rounds": 7,
        "max_handoffs": 17,
        "context_compression": True,
        "inspection_after_success": True,
    },
}


def get_platform_capabilities(target_connector_type: str = None) -> str:
    """生成平台能力清单文本，注入 debug system prompt。

    target_connector_type: 目标数据源的连接器类型（如 excel/sqlite/postgresql）。
    如果提供，额外注入该连接器的具体能力。
    """
    caps = PLATFORM_CAPABILITIES
    lines = ["## 平台能力与限制"]

    lines.append("### 沙箱（L2）")
    sb = caps["sandbox"]
    lines.append(f"- async/await: {'✅' if sb['async_support'] else '❌ 不支持（需用 run_async_in_thread）'}")
    lines.append(f"- 直接网络访问: {'✅' if sb['network_access'] else '❌ 禁止（需走内部 HTTP 端点）'}")
    lines.append(f"- 可用函数: {', '.join(sb['available_functions'])}")
    lines.append("- 如果遇到 NameError 且该函数不在列表中 → 平台未注入，不是脚本 bug")

    lines.append("\n### LLM（L3）")
    llm = caps["llm"]
    lines.append(f"- Thinking: {llm['thinking']}")
    lines.append(f"- 速率限制: {llm['rate_limit_retry']}")

    lines.append("\n### 框架（L4）")
    fw = caps["framework"]
    lines.append(f"- 最多 {fw['max_debug_rounds']} 轮修复")
    lines.append(f"- handoff 上限 {fw['max_handoffs']} 次")
    lines.append(f"- 上下文压缩: {'✅' if fw['context_compression'] else '❌'}")
    lines.append("- 如果循环被终止 → 检查是否触发上限，不是脚本失败")

    if target_connector_type and target_connector_type in caps["connector"]:
        c = caps["connector"][target_connector_type]
        wtd = c.get("write_table_data", {})
        lines.append(f"\n### 目标连接器（{target_connector_type}）")
        can_create = wtd.get("create_new_file", wtd.get("create_new_table", False))
        lines.append(f"- 创建新文件/表: {'✅' if can_create else '❌ 不支持'}")
        lines.append(f"- execute_sql: {'✅' if c.get('execute_sql') else '❌ 不支持'}")
        if wtd.get("if_table_exists"):
            lines.append(f"- if_table_exists 策略: {', '.join(wtd['if_table_exists'])}")
        lines.append("- ⚠️ 标❌的能力，修改脚本无法绕过，应向用户报告")

    return "\n".join(lines)


def get_tool_guidance(debug: bool = False) -> str:
    """获取工具能力表文本，用于注入 system prompt。

    debug=True 返回调试工具能力表（edit/modify/read/grep），
    debug=False 返回主对话工具能力表（共享工具 + 扩展工具）。
    """
    return _DEBUG_TOOL_CAPABILITY_TABLE if debug else _MAIN_TOOL_CAPABILITY_TABLE
