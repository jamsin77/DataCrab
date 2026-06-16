# 文物检索专家技能

## 📋 技能简介

文物检索专家是一个强大的数据采集和检索技能，能够从权威网站采集各级保护文物信息，构建本地知识库，并支持多条件检索。

## 🎯 核心功能

### 1. 数据采集
- 从维基百科采集文物信息
- 从百度百科采集文物信息
- 从国家文物局官网采集文物信息
- 支持自定义数据源扩展

### 2. 知识库管理
- 自动构建本地知识库（JSON格式）
- 支持增量更新（append模式）
- 支持完全替换（replace模式）
- 自动去重（根据名称+地址）

### 3. 多条件检索
- 按名称检索（模糊匹配）
- 按时代检索（模糊匹配）
- 按地区检索（模糊匹配）
- 按保护级别检索
- 按文物类型检索
- 按批次检索
- 支持多条件组合检索

### 4. 统计分析
- 按时代统计文物分布
- 按级别统计文物分布
- 按类型统计文物分布
- 按地区统计文物分布

### 5. 数据导出
- 导出为Excel格式
- 支持数据备份和分享

## 📖 使用方法

### 在DataCrab中上传

1. 打开DataCrab前端界面
2. 进入"技能"页面
3. 点击"上传Skills"按钮
4. 选择 `cultural_relics_expert.py` 文件
5. 上传成功后即可使用

### 在聊天中使用

上传成功后，可以在对话中自然语言调用：

```
用户：帮我构建文物知识库
AI：[调用技能] 正在从权威网站采集文物信息...

用户：检索明代的文物
AI：[调用技能] 找到 XX 条明代文物...

用户：统计北京地区有多少文物
AI：[调用技能] 北京地区共有 XX 处文物...

用户：导出文物数据到Excel
AI：[调用技能] 已导出到 cultural_relics_export.xlsx
```

### 直接调用（Python）

```python
from cultural_relics_expert import cultural_relics_expert

# 1. 构建知识库
result = cultural_relics_expert(
    action="build",
    sources="wikipedia,baidu,gov",
    max_items=100,
    update_mode="append"
)
print(result["message"])

# 2. 检索文物
result = cultural_relics_expert(
    action="search",
    era="明",
    location="北京",
    limit=20
)
print(f"找到 {result['count']} 条文物")

# 3. 获取统计
stats = cultural_relics_expert(action="stats")
print(stats["message"])

# 4. 导出数据
export = cultural_relics_expert(action="export")
print(export["message"])
```

## 🔧 参数说明

### action（操作类型）

| 值 | 说明 | 必需参数 |
|----|------|---------|
| search | 检索文物 | 可选：name, era, location, level, relic_type, batch, limit |
| build | 构建知识库 | 可选：sources, max_items, update_mode |
| stats | 获取统计信息 | 无 |
| export | 导出知识库 | 无 |

### 检索参数

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| name | str | 文物名称（模糊匹配） | "故宫"、"长城" |
| era | str | 时代（模糊匹配） | "明"、"唐"、"汉" |
| location | str | 地址/地区（模糊匹配） | "北京"、"陕西" |
| level | str | 保护级别 | "全国重点文物保护单位" |
| relic_type | str | 文物类型 | "古建筑"、"古遗址" |
| batch | str | 批次 | "第一批"、"第二批" |
| limit | int | 返回数量限制 | 100 |

### 构建参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| sources | str | 数据来源（逗号分隔） | "wikipedia,baidu,gov" |
| max_items | int | 每来源最大爬取数量 | 100 |
| update_mode | str | 更新模式（append/replace） | "append" |

## 📊 使用示例

### 示例1: 首次使用 - 构建知识库

```python
result = cultural_relics_expert(
    action="build",
    sources="wikipedia,baidu,gov",
    max_items=200,
    update_mode="append"
)

# 返回结果
{
    "success": True,
    "stats": {
        "total": 600,
        "kb_total": 600,
        "by_source": {
            "维基百科": 200,
            "百度百科": 200,
            "国家文物局": 200
        }
    },
    "message": "知识库构建完成，本次爬取 600 条，知识库共 600 条"
}
```

### 示例2: 检索明代文物

```python
result = cultural_relics_expert(
    action="search",
    era="明",
    limit=50
)

# 返回结果
{
    "success": True,
    "count": 45,
    "results": [
        {
            "名称": "故宫",
            "时代": "明、清",
            "地址": "北京市东城区",
            "级别": "世界文化遗产",
            "批次": "第一批",
            "类型": "古建筑",
            ...
        },
        ...
    ],
    "message": "找到 45 条匹配的文物"
}
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

# 返回陕西省的唐代古建筑
```

### 示例4: 获取统计信息

```python
stats = cultural_relics_expert(action="stats")

# 返回结果
{
    "success": True,
    "statistics": {
        "总数": 1000,
        "按时代": {
            "明": 150,
            "清": 120,
            "唐": 80,
            ...
        },
        "按级别": {
            "世界文化遗产": 50,
            "全国重点文物保护单位": 800,
            ...
        },
        "按类型": {
            "古建筑": 400,
            "古遗址": 300,
            ...
        },
        "按地区": {
            "北京": 100,
            "陕西": 80,
            ...
        }
    },
    "message": "知识库共 1000 条文物"
}
```

### 示例5: 导出知识库

```python
export = cultural_relics_expert(action="export")

# 返回结果
{
    "success": True,
    "output_path": "cultural_relics_export.xlsx",
    "count": 1000,
    "message": "知识库已导出到 cultural_relics_export.xlsx，共 1000 条"
}
```

## 📂 生成的文件

### cultural_relics_kb.json
知识库数据文件，JSON格式，包含：
- relics: 文物列表
- metadata: 元数据（总数、最后更新时间等）

### cultural_relics_export.xlsx
导出的Excel文件，包含所有文物信息，可用Excel打开查看。

## 💡 最佳实践

### 1. 首次使用
```python
# 构建知识库
cultural_relics_expert(
    action="build",
    max_items=500,  # 建议采集更多数据
    update_mode="append"
)
```

### 2. 定期更新
```python
# 每周更新一次（使用append模式）
cultural_relics_expert(
    action="build",
    max_items=100,
    update_mode="append"  # 追加新数据，自动去重
)
```

### 3. 检索优化
```python
# 使用limit限制返回数量
result = cultural_relics_expert(
    action="search",
    era="明",
    limit=20  # 只返回前20条
)
```

### 4. 数据备份
```python
# 定期导出备份
cultural_relics_expert(action="export")

# 同时备份JSON文件
import shutil
shutil.copy("cultural_relics_kb.json", "cultural_relics_kb_backup.json")
```

## ⚠️ 注意事项

1. **网络连接**：构建知识库需要网络连接，请确保网络畅通

2. **首次使用**：建议先构建知识库，否则检索结果为空

3. **数据准确性**：爬取的数据可能不完整，建议人工核实重要信息

4. **法律合规**：请遵守相关网站的使用条款和robots.txt

5. **知识库大小**：大量数据会增加文件大小，建议定期清理

6. **请求频率**：代码已内置请求间隔，避免被封禁

## 🔄 更新日志

### v1.0.0 (2026-06-14)
- ✅ 初始版本发布
- ✅ 支持从维基百科、百度百科、国家文物局采集数据
- ✅ 支持多条件检索
- ✅ 支持统计分析
- ✅ 支持导出Excel

## 📞 技术支持

如有问题或建议，请联系开发团队。

---

**文件位置**: `D:\DataCrab\skills\cultural_relics_expert.py`

**上传方式**: DataCrab前端 → 技能页面 → 上传Skills → 选择此文件