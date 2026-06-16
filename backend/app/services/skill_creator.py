"""Skill Creator - AI 生成完整 Skill 包"""

from pathlib import Path
from typing import Dict, Any

from loguru import logger

from app.services.llm import llm_manager
from app.services.skill_parser import parse_skill_md, build_skill_md


SKILL_CREATOR_SYSTEM_PROMPT = """你是一个 Skill Creator，专门为 DataCrab 数据平台创建 Skills。

## Skill 定义
Skill 是遵循 Agent Skills 开放标准的模块化能力包，包含：
- SKILL.md：核心指令文档（YAML 元数据 + Markdown 指令）
- scripts/：可执行 Python 脚本
- references/：参考资料

## 输出格式（严格遵守）
你必须在一次回复中输出完整的 Skill 包内容。使用以下分隔符：

```yaml
---
name: skill-name
description: 技能描述
---
```

## SKILL.md 内容规范
用 Markdown 编写，包含：
1. 功能说明
2. 使用方式
3. 脚本说明
4. 参数规范

## scripts/*.py 规范
- 使用 pandas 处理数据
- 第一个参数是 DataFrame
- 函数名和参数要有类型注解
- 有完整的 docstring
- 处理边界情况（空表、列不存在等）
- 使用 print() 输出处理进度

## 内置工具函数（可在脚本中直接调用）
- query_table_data(datasource_id, table_name, limit, offset, order_by) → DataFrame
- get_table_schema(datasource_id, table_name) → dict
- get_datasource_id_by_name(name) → str

## 数据源参考
- "文物测试数据" (Excel)
- "SQLite测试数据库" (SQLite)
- "CSVFormTest" (CSV)"""


async def generate_skill(prompt: str) -> Dict[str, Any]:
    """根据自然语言描述生成完整 Skill 包"""
    await llm_manager.initialize()

    user_prompt = f"""请根据以下需求，创建一个完整的 Skill 包：

{prompt}

请输出：
1. SKILL.md（包含 YAML front matter + Markdown 内容）
2. scripts/main.py（核心处理脚本）
3. 如果必要，scripts/ 下可以有更多脚本
4. 如果有参考资料，输出 references/

使用以下格式输出：

===SKILL_MD===
（SKILL.md 完整内容）
===SKILL_MD_END===

===SCRIPT:main.py===
（脚本内容）
===SCRIPT_END===

（如有其他脚本，继续用 ===SCRIPT:文件名.py=== 格式）
"""

    try:
        raw_response = await llm_manager.chat_with_messages(
            messages=[
                {"role": "system", "content": SKILL_CREATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=4000,
        )
    except Exception as e:
        logger.error(f"Skill Creator 生成失败: {e}")
        raise

    return _parse_creator_response(raw_response)


def _parse_creator_response(raw: str) -> Dict[str, Any]:
    """解析 Skill Creator 的原始输出"""
    result = {
        "skill_md": "",
        "scripts": {},
        "front_matter": {},
    }

    sections = raw.split("===SKILL_MD===")
    if len(sections) > 1:
        md_part = sections[1].split("===SKILL_MD_END===")[0].strip()
        result["skill_md"] = md_part
        parsed = parse_skill_md(md_part)
        result["front_matter"] = parsed["front_matter"]

    lines = raw.split("\n")
    current_script = None
    script_content = []

    for line in lines:
        if line.startswith("===SCRIPT:") and line.endswith("==="):
            if current_script and script_content:
                result["scripts"][current_script] = "\n".join(script_content).strip()
            current_script = line[len("===SCRIPT:"):-len("===")].strip()
            script_content = []
        elif line == "===SCRIPT_END===":
            if current_script and script_content:
                result["scripts"][current_script] = "\n".join(script_content).strip()
            current_script = None
            script_content = []
        elif current_script:
            script_content.append(line)

    if current_script and script_content:
        result["scripts"][current_script] = "\n".join(script_content).strip()

    return result


def create_skill_on_disk(skill_path: Path, skill_md: str, scripts: Dict[str, str]):
    """在磁盘上创建 Skill 文件夹结构"""
    skill_path.mkdir(parents=True, exist_ok=True)

    (skill_path / "SKILL.md").write_text(skill_md, encoding="utf-8")

    scripts_dir = skill_path / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    for filename, content in scripts.items():
        (scripts_dir / filename).write_text(content, encoding="utf-8")

    refs_dir = skill_path / "references"
    refs_dir.mkdir(exist_ok=True)

    assets_dir = skill_path / "assets"
    assets_dir.mkdir(exist_ok=True)

    logger.info(f"Skill 文件夹已创建: {skill_path}")