"""文物检索专家技能打包脚本（正确格式）"""
import os
import shutil
import zipfile

print("=" * 60)
print("文物检索专家技能打包工具")
print("=" * 60)

# 技能目录
skill_dir = "cultural_relics_expert_skill"

# 检查必需文件
required_files = [
    "SKILL.md",
    "scripts/cultural_relics_expert.py"
]

print("\n检查技能文件...")
for file in required_files:
    file_path = os.path.join(skill_dir, file)
    if os.path.exists(file_path):
        size = os.path.getsize(file_path)
        print(f"✅ {file} ({size:,} bytes)")
    else:
        print(f"❌ 缺少文件: {file}")
        exit(1)

# 创建打包文件
zip_file = "cultural_relics_expert.zip"
if os.path.exists(zip_file):
    os.remove(zip_file)

print(f"\n打包技能...")

with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
    # 添加SKILL.md
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    zipf.write(skill_md_path, "SKILL.md")
    print(f"✅ 添加 SKILL.md")
    
    # 添加scripts目录下的所有文件
    scripts_dir = os.path.join(skill_dir, "scripts")
    if os.path.exists(scripts_dir):
        for file in os.listdir(scripts_dir):
            if file.endswith('.py'):
                file_path = os.path.join(scripts_dir, file)
                zipf.write(file_path, f"scripts/{file}")
                print(f"✅ 添加 scripts/{file}")

# 显示打包结果
print(f"\n{'='*60}")
print("打包完成！")
print(f"{'='*60}")

zip_size = os.path.getsize(zip_file)
print(f"\n📦 打包文件: {zip_file}")
print(f"   大小: {zip_size:,} bytes")

print(f"\n📋 包含文件:")
with zipfile.ZipFile(zip_file, 'r') as zipf:
    for info in zipf.infolist():
        print(f"   - {info.filename} ({info.file_size:,} bytes)")

print(f"\n{'='*60}")
print("上传说明")
print(f"{'='*60}")
print(f"\n方法1: 直接上传到DataCrab")
print(f"1. 打开DataCrab前端 → 技能页面")
print(f"2. 点击'上传Skills'按钮")
print(f"3. 选择文件: {zip_file}")
print(f"4. 上传成功！")

print(f"\n方法2: 解压后上传")
print(f"1. 解压 {zip_file}")
print(f"2. 将整个文件夹上传到DataCrab")

print(f"\n{'='*60}")