"""对话路由器——判断用户消息走哪个 Agent

规则：
- 含分析类关键词且不含修改类关键词 → DataAnalyst（只读分析）
- 其余 → DataProcessor（默认兜底，保持现有行为）
"""

ANALYSIS_KEYWORDS = {"查询", "统计", "分析", "分布", "多少", "查看", "列出", "有多少", "汇总", "占比", "排名", "趋势", "平均值", "最大值", "最小值", "计数", "分组", "对比"}

MODIFY_KEYWORDS = {"清洗", "转换", "修改", "处理", "分类", "写入", "导入", "导出", "删除", "更新", "补全", "修复", "脱敏", "去重", "合并", "拆分", "格式化", "标准化", "迁移", "生成", "创建", "新建", "安装", "添加连接器", "添加模型", "注册"}


def route_agent(user_message: str) -> str:
    """根据用户消息关键词路由到合适的 Agent。

    Returns:
        "data_analyst" — 只读分析类问题
        "data_processor" — 修改/处理类问题（默认兜底）
    """
    if not user_message:
        return "data_processor"

    has_analysis = any(kw in user_message for kw in ANALYSIS_KEYWORDS)
    has_modify = any(kw in user_message for kw in MODIFY_KEYWORDS)

    if has_analysis and not has_modify:
        return "data_analyst"
    return "data_processor"
