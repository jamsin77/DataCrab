"""
文物检索专家技能打包脚本
将技能打包成可以直接上传到DataCrab的格式
"""
import os
import shutil
import json

print("=" * 60)
print("文物检索专家技能打包工具")
print("=" * 60)

# 创建打包目录
package_dir = "cultural_relics_expert_package"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

print(f"\n✅ 创建打包目录: {package_dir}")

# 复制技能文件
skill_file = "skills/cultural_relics_expert.py"
if os.path.exists(skill_file):
    shutil.copy(skill_file, f"{package_dir}/cultural_relics_expert.py")
    print(f"✅ 复制技能文件: cultural_relics_expert.py")
else:
    print(f"❌ 技能文件不存在: {skill_file}")
    exit(1)

# 创建技能元数据
metadata = {
    "name": "cultural_relics_expert",
    "display_name": "文物检索专家",
    "description": "从权威网站检索各级保护文物信息，生成知识库，支持多条件检索",
    "category": "data_collection",
    "version": "1.0.0",
    "author": "DataCrab",
    "tags": ["文物", "检索", "知识库", "数据采集", "文化遗产"],
    "function_name": "cultural_relics_expert",
    "parameters": [
        {
            "name": "action",
            "type": "str",
            "required": True,
            "description": "操作类型：search(检索)、build(构建)、stats(统计)、export(导出)"
        },
        {
            "name": "name",
            "type": "str",
            "required": False,
            "description": "文物名称（模糊匹配）"
        },
        {
            "name": "era",
            "type": "str",
            "required": False,
            "description": "时代（模糊匹配），如：明、唐、汉"
        },
        {
            "name": "location",
            "type": "str",
            "required": False,
            "description": "地址/地区（模糊匹配），如：北京、陕西"
        },
        {
            "name": "level",
            "type": "str",
            "required": False,
            "description": "保护级别，如：全国重点文物保护单位"
        },
        {
            "name": "relic_type",
            "type": "str",
            "required": False,
            "description": "文物类型，如：古建筑、古遗址"
        },
        {
            "name": "batch",
            "type": "str",
            "required": False,
            "description": "批次，如：第一批"
        },
        {
            "name": "limit",
            "type": "int",
            "required": False,
            "default": 100,
            "description": "返回数量限制"
        },
        {
            "name": "sources",
            "type": "str",
            "required": False,
            "default": "wikipedia,baidu,gov",
            "description": "数据来源（逗号分隔）"
        },
        {
            "name": "max_items",
            "type": "int",
            "required": False,
            "default": 100,
            "description": "每来源最大爬取数量"
        },
        {
            "name": "update_mode",
            "type": "str",
            "required": False,
            "default": "append",
            "description": "更新模式：append(追加) 或 replace(替换)"
        }
    ],
    "inputs": [
        {
            "name": "action",
            "type": "str",
            "required": True
        }
    ],
    "outputs": [
        {
            "name": "result",
            "type": "dict"
        }
    ],
    "usage_examples": [
        "检索明代的文物",
        "统计北京地区有多少文物",
        "构建文物知识库",
        "导出文物数据到Excel",
        "查找故宫的相关信息",
        "检索唐代的古建筑"
    ]
}

with open(f"{package_dir}/metadata.json", 'w', encoding='utf-8') as f:
    json.dump(metadata, f, ensure_ascii=False, indent=2)
print(f"✅ 创建元数据文件: metadata.json")

# 复制README
readme_file = "skills/README.md"
if os.path.exists(readme_file):
    shutil.copy(readme_file, f"{package_dir}/README.md")
    print(f"✅ 复制说明文件: README.md")

# 创建使用示例文件
example_code = '''"""
文物检索专家技能使用示例
"""
from cultural_relics_expert import cultural_relics_expert

# 示例1: 构建知识库（首次使用）
print("示例1: 构建知识库")
result = cultural_relics_expert(
    action="build",
    sources="wikipedia,baidu,gov",
    max_items=100,
    update_mode="append"
)
print(f"结果: {result['message']}")

# 示例2: 检索明代文物
print("\\n示例2: 检索明代文物")
result = cultural_relics_expert(
    action="search",
    era="明",
    limit=20
)
print(f"找到 {result['count']} 条明代文物")
for relic in result['results'][:5]:
    print(f"  - {relic['名称']} ({relic['时代']}) - {relic['地址']}")

# 示例3: 按地区检索
print("\\n示例3: 检索北京地区的文物")
result = cultural_relics_expert(
    action="search",
    location="北京",
    limit=10
)
print(f"北京地区共 {result['count']} 条文物")

# 示例4: 组合条件检索
print("\\n示例4: 检索唐代古建筑")
result = cultural_relics_expert(
    action="search",
    era="唐",
    relic_type="古建筑",
    limit=15
)
print(f"找到 {result['count']} 条唐代古建筑")

# 示例5: 获取统计信息
print("\\n示例5: 获取统计信息")
stats = cultural_relics_expert(action="stats")
print(f"知识库总数: {stats['statistics']['总数']}")
print(f"按时代分布: {stats['statistics']['按时代']}")
print(f"按地区分布: {stats['statistics']['按地区']}")

# 示例6: 导出知识库
print("\\n示例6: 导出知识库到Excel")
export = cultural_relics_expert(action="export")
print(f"导出结果: {export['message']}")
'''

with open(f"{package_dir}/examples.py", 'w', encoding='utf-8') as f:
    f.write(example_code)
print(f"✅ 创建示例文件: examples.py")

# 创建安装说明
install_guide = '''# 文物检索专家技能安装说明

## 📦 文件清单

- `cultural_relics_expert.py` - 技能主文件（上传到DataCrab）
- `metadata.json` - 技能元数据
- `README.md` - 详细使用说明
- `examples.py` - 使用示例代码

## 🚀 安装步骤

### 方法1: 上传到DataCrab（推荐）

1. 打开DataCrab前端界面
2. 进入"技能"页面
3. 点击"上传Skills"按钮
4. 选择 `cultural_relics_expert.py` 文件
5. 上传成功后即可在聊天中使用

### 方法2: 直接使用（Python）

1. 将 `cultural_relics_expert.py` 复制到你的项目目录
2. 安装依赖：`pip install pandas requests beautifulsoup4 openpyxl`
3. 导入使用：`from cultural_relics_expert import cultural_relics_expert`

## 📖 快速开始

```python
from cultural_relics_expert import cultural_relics_expert

# 1. 构建知识库（首次使用）
result = cultural_relics_expert(action="build", max_items=100)
print(result["message"])

# 2. 检索文物
result = cultural_relics_expert(action="search", era="明", limit=20)
print(f"找到 {result['count']} 条文物")

# 3. 获取统计
stats = cultural_relics_expert(action="stats")
print(stats["message"])
```

## 💡 在DataCrab聊天中使用

上传成功后，可以直接用自然语言调用：

- "帮我构建文物知识库"
- "检索明代的文物"
- "统计北京地区有多少文物"
- "导出文物数据"

## ⚠️ 注意事项

1. 首次使用需要先构建知识库
2. 构建知识库需要网络连接
3. 建议定期更新知识库（使用append模式）

## 📞 技术支持

如有问题，请查看 README.md 获取详细说明。
'''

with open(f"{package_dir}/INSTALL.md", 'w', encoding='utf-8') as f:
    f.write(install_guide)
print(f"✅ 创建安装说明: INSTALL.md")

# 打包成zip
import zipfile
zip_file = "cultural_relics_expert.zip"
if os.path.exists(zip_file):
    os.remove(zip_file)

with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for file in os.listdir(package_dir):
        file_path = os.path.join(package_dir, file)
        zipf.write(file_path, file)

print(f"\n✅ 打包完成: {zip_file}")

# 显示文件列表
print(f"\n📦 打包内容:")
for file in os.listdir(package_dir):
    file_path = os.path.join(package_dir, file)
    size = os.path.getsize(file_path)
    print(f"   - {file} ({size:,} bytes)")

print(f"\n{'='*60}")
print("打包成功！")
print(f"{'='*60}")
print(f"\n上传方式:")
print(f"1. 打开DataCrab前端 → 技能页面")
print(f"2. 点击'上传Skills'按钮")
print(f"3. 选择文件: {package_dir}/cultural_relics_expert.py")
print(f"\n或使用打包文件: {zip_file}")