# -*- coding: utf-8 -*-
import openpyxl

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "test-cases"
headers = ["step", "msg", "type", "keep", "action", "operation"]
ws.append(headers)

cases = [
    (1, "帮我查一下在文物库数据源，那个数据表更像合并后的文物信息列表？", "analysis", "", "select_data", "出现数据匹配建议，点 选择此数据"),
    (2, "我要把这个数据导出一份？可以吗？", "processing", "true", "no_suggestion", "提示指定目标数据源，等待 Agent 响应"),
    (3, "导出到 文物列表 数据源", "processing", "true", "select_data", "出现目标表匹配建议，点 选择此数据"),
    (4, "导出到 文物列表 数据源", "processing", "true", "use_skill", "出现技能匹配建议 data-etl，点 使用技能 跳转"),
    (5, "再看看文物列表数据源，哪个数据是迁移过来的数据", "analysis", "false", "no_suggestion", "换数据源，Agent 直接分析对比"),
    (6, "好的，那我们就分析这个数据表", "analysis", "true", "no_suggestion", "Agent 分析数据表结构和内容"),
    (7, "我想把这张表按照地址提取出地级市作为新的一列，可以吗？", "processing", "true", "use_skill", "出现技能匹配建议 semantic-classify，点 使用技能 跳转"),
    (8, "这些数据迁移到另一个数据源", "processing", "true", "no_suggestion", "Agent 直接处理迁移请求"),
    (9, "统计一下有多少行", "analysis", "true", "no_suggestion", "Agent 统计行数"),
    (10, "分析这个数据表", "analysis", "true", "no_suggestion", "Agent 分析数据表"),
    (11, "统计下Top50的地级市文物数量", "analysis", "true", "no_suggestion", "Agent 统计 Top50 地级市文物数量"),
    (12, "你好", "chat", "", "no_suggestion", "闲聊，Agent 回复问候"),
]

for c in cases:
    ws.append(c)

ws.column_dimensions["A"].width = 6
ws.column_dimensions["B"].width = 50
ws.column_dimensions["C"].width = 12
ws.column_dimensions["D"].width = 8
ws.column_dimensions["E"].width = 16
ws.column_dimensions["F"].width = 40

path = r"D:\DataCrab\tests\e2e\test-cases.xlsx"
wb.save(path)
print("saved")
