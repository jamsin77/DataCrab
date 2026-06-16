import re

file_path = r'd:\DataCrab\backend\app\services\nl_service.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 修复所有被截断的正则表达式
# 将 r'\s*```\n 替换为 r'\s*```$'
content = content.replace("r'\\s*```\n", "r'\\s*```$'\n")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('文件已修复')
