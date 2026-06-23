"""Skill Creator - AI 生成完整 Skill 包"""

from pathlib import Path
from typing import Dict, Any, AsyncGenerator

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
- 函数名和参数要有类型注解
- 有完整的 docstring
- 处理边界情况（空表、列不存在等）
- 使用 print() 输出处理进度

## 内置工具函数（可在脚本中直接调用，无需 import）
- query_table_data(datasource_id, table_name, limit=1000) → dict: {"success": bool, "data": [行dict], "columns": [列名], "row_count": int}
- get_table_data(datasource_id, table_name, limit=1000) → 同 query_table_data
- get_table_schema(datasource_id, table_name) → dict: {"columns": [...], "row_count": int}
- get_datasource_id_by_name(name) → str (数据源UUID)
- write_table_data(datasource_id, table_name, records=...) → dict

⚠️ **绝对禁止** `import datacrab` 或 `from datacrab import ...`，datacrab 包不存在！
⚠️ **绝对禁止** `pip install datacrab`，datacrab 不是可安装的包！
⚠️ 上述函数由运行环境自动注入到全局作用域，脚本中直接使用即可
⚠️ `if __name__ == '__main__':` 块会被系统自动去掉，main() 由系统调用

## 数据源参考
- "文物测试数据" (Excel)
- "SQLite测试数据库" (SQLite)
- "CSVFormTest" (CSV)

🚫 安全红线（必须遵守）：
- Skill 只能处理用户的业务数据，绝不能修改 DataCrab 平台自身
- 不得生成访问或修改平台系统表（users, roles, permissions, data_sources等）的代码
- 不得生成修改平台源代码、配置文件的代码
- 不得生成删除或篡改平台用户、角色、权限的代码
- 如果用户要求创建修改平台本身的技能，在脚本中抛出 ValueError("不允许修改平台自身")
- 脚本中只能操作用户数据源的业务数据，不能操作平台系统数据

✅ 技能属于用户内容，可以自由创建和修改：
- 用户可以自由创建、修改、调试、删除自己的技能
- 技能脚本可以查询和处理用户数据源中的业务数据
- 技能脚本可以使用内置工具函数（query_table_data, get_table_schema, get_datasource_id_by_name）访问用户数据

✅ 创建后必验证（必须遵守）：
- 脚本中必须包含自测逻辑：在 if __name__ == "__main__" 块中用少量示例数据调用主函数
- 自测应验证：1) 脚本无语法错误 2) 主函数能正常执行 3) 返回结果格式正确
- 如果自测发现问题，在输出中说明原因并提供修复后的脚本

✅ 输出默认同源（必须遵守）：
- 数据处理生成新文件时，如果用户未指定输出路径（output_dir），默认保存到 DataSource（数据源）指定的文件路径下（即 connection_config.file_path 所在目录）
- 脚本中必须提供 output_dir 参数，且默认值应为 DataSource 文件所在目录
- 如果 DataSource 来自数据库而非文件，需要用户明确指定输出路径
- 在 SKILL.md 中说明输出路径的默认行为"""


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


async def generate_skill_stream(prompt: str) -> AsyncGenerator[Dict[str, Any], None]:
    """流式生成 Skill 包，逐步返回生成过程"""
    await llm_manager.initialize()

    yield {"type": "status", "message": "正在分析需求..."}

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

    yield {"type": "status", "message": "正在调用 LLM 生成..."}

    full_response = ""
    try:
        async for chunk in llm_manager.chat_stream_with_messages(
            messages=[
                {"role": "system", "content": SKILL_CREATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        ):
            full_response += chunk
            yield {"type": "chunk", "content": chunk}

            if "===SKILL_MD===" in full_response and "===SKILL_MD_END===" not in full_response:
                if "===SKILL_MD_END===" not in chunk:
                    yield {"type": "progress", "message": "正在生成 SKILL.md..."}

            for marker in ["===SCRIPT:"]:
                if marker in full_response:
                    last_script_start = full_response.rfind(marker)
                    remaining = full_response[last_script_start:]
                    if "===SCRIPT_END===" not in remaining:
                        script_name_match = remaining[len(marker):].split("===")
                        if script_name_match:
                            yield {"type": "progress", "message": f"正在生成脚本 {script_name_match[0]}..."}

    except Exception as e:
        logger.error(f"Skill Creator 流式生成失败: {e}")
        yield {"type": "error", "message": str(e)}
        return

    yield {"type": "status", "message": "生成完成，正在解析..."}

    parsed = _parse_creator_response(full_response)

    if not parsed.get("skill_md"):
        yield {"type": "error", "message": "LLM 未生成有效的 SKILL.md，请重试"}
        return

    yield {"type": "status", "message": f"解析完成：SKILL.md + {len(parsed.get('scripts', {}))} 个脚本"}
    yield {"type": "done", "data": parsed}