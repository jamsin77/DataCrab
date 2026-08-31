"""共享工具——向后兼容层。

工具 schema 和实现已迁移到 tool_registry.py 统一注册中心。
本文件保留向后兼容导出（SHARED_TOOL_SCHEMAS / execute_shared_tool / ANALYSIS_TOOLS），
内部委托 tool_registry，不再有自己的 schema 或实现代码。
"""
from app.services.tool_registry import (
    execute_tool,
    get_tool_schemas,
    SHARED_TOOL_SCHEMAS,
)

# 向后兼容：旧代码通过 execute_shared_tool 调用（委托 execute_tool，传 context={}）
async def execute_shared_tool(name, arguments, db, user_id):
    return await execute_tool(name, arguments, db, user_id, {})


# 向后兼容：DataAnalyst 旧版用 ANALYSIS_TOOLS（现在直接用 get_tool_schemas）
ANALYSIS_TOOLS = get_tool_schemas([
    "query_table_data", "get_table_schema", "list_user_datasources",
    "execute_sql", "kb_search",
])
