"""Skill Creator - AI 生成完整 Skill 包"""

from pathlib import Path
from typing import Dict, Any, AsyncGenerator

from loguru import logger

from app.services.llm import llm_manager
from app.services.skill_parser import parse_skill_md, build_skill_md
from app.services.prompt_docs import SANDBOX_TOOLS_DOC, SAFETY_RULES_DOC


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

⚠️ **name 命名规范（必须遵守）**：
- name 必须是根据用户需求语义生成的有意义英文名，用短横线连接
- 禁止使用 generate_skill、new_skill、custom_skill 等无意义通用名称
- 命名应体现技能的核心功能，例如：
  - 用户需求"按朝代筛选文物" → name: filter-by-dynasty
  - 用户需求"数据缺失值填充" → name: fill-missing-values
  - 用户需求"销售数据月度统计" → name: monthly-sales-stats
  - 用户需求"删除重复记录" → name: remove-duplicates

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

""" + SANDBOX_TOOLS_DOC + "\n\n" + SAFETY_RULES_DOC + """

## 示例 Skill 包

用户需求："按朝代筛选文物数据"

===SKILL_MD===
---
name: filter-by-dynasty
description: 按朝代筛选文物数据，支持单朝代和多朝代筛选
version: "1.0.0"
tags:
  - 筛选
  - 文物
  - 朝代
---

# 按朝代筛选文物

## 功能说明
从文物数据源中按朝代筛选记录，支持单个或多个朝代（逗号分隔）。

## 使用方式
```
筛选 "文物数据" 中朝代为 "唐" 的文物
```
```
从 "文物数据" 的 artifacts 表中筛选朝代为 "唐,宋" 的文物
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `datasource_name` | str | ✅ | - | 数据源名称 |
| `table_name` | str | ❌ | artifacts | 表名 |
| `dynasties` | str | ✅ | - | 朝代，多个用逗号分隔 |
| `output_dir` | str | ❌ | None | 输出目录 |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心筛选脚本 |
===SKILL_MD_END===

===SCRIPT:main.py===
import pandas as pd
from typing import Dict, Any, Optional, List

def filter_by_dynasty(
    datasource_name: str,
    table_name: str = "artifacts",
    dynasties: str = "",
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        raise ValueError(f"找不到数据源: {datasource_name}")

    result = query_table_data(ds_id, table_name)
    if not result.get("success"):
        raise ValueError(f"读取数据失败: {result.get('error')}")

    df = pd.DataFrame(result["data"], columns=result["columns"])
    if df.empty:
        return {"success": True, "filtered_count": 0, "data": []}

    dynasty_list = [d.strip() for d in dynasties.split(",") if d.strip()]
    dynasty_col = None
    for col in df.columns:
        if "朝代" in col or "dynasty" in col.lower():
            dynasty_col = col
            break

    if dynasty_col is None:
        raise ValueError(f"未找到朝代列，现有列: {list(df.columns)}")

    filtered = df[df[dynasty_col].astype(str).isin(dynasty_list)]
    print(f"筛选完成: {len(df)} → {len(filtered)} 条 (朝代: {', '.join(dynasty_list)})")

    if output_dir:
        import os
        path = os.path.join(output_dir, f"filtered_{table_name}.csv")
        filtered.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"已保存: {path}")

    return {
        "success": True,
        "filtered_count": len(filtered),
        "columns": list(filtered.columns),
        "data": filtered.to_dict(orient="records")[:10],
    }


def main(**params):
    return filter_by_dynasty(**params)
===SCRIPT_END==="""


async def generate_skill(prompt: str, datasource_info: str = "", lessons: str = "") -> Dict[str, Any]:
    """根据自然语言描述生成完整 Skill 包"""
    await llm_manager.initialize()

    ds_section = ""
    if datasource_info:
        ds_section = f"""

## 当前用户的数据源
{datasource_info}

请在脚本中使用上述真实的数据源名称和表名，使用 get_datasource_id_by_name("数据源名称") 获取数据源ID。
"""

    lessons_section = ""
    if lessons:
        lessons_section = f"""

## 历史经验总结（从过往技能错误中学习，避免同类问题）
{lessons}

请在生成脚本时参考以上经验，避免犯相同的错误。如果经验中有相关的修复建议，在脚本中体现。
"""

    user_prompt = f"""请根据以下需求，创建一个完整的 Skill 包：

{prompt}
{ds_section}
{lessons_section}
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


async def generate_skill_stream(prompt: str, datasource_info: str = "", lessons: str = "") -> AsyncGenerator[Dict[str, Any], None]:
    """流式生成 Skill 包，逐步返回生成过程"""
    await llm_manager.initialize()

    yield {"type": "status", "message": "正在分析需求..."}

    ds_section = ""
    if datasource_info:
        ds_section = f"""

## 当前用户的数据源
{datasource_info}

请在脚本中使用上述真实的数据源名称和表名，使用 get_datasource_id_by_name("数据源名称") 获取数据源ID。
"""

    lessons_section = ""
    if lessons:
        lessons_section = f"""

## 历史经验总结（从过往技能错误中学习，避免同类问题）
{lessons}

请在生成脚本时参考以上经验，避免犯相同的错误。如果经验中有相关的修复建议，在脚本中体现。
"""

    user_prompt = f"""请根据以下需求，创建一个完整的 Skill 包：

{prompt}
{ds_section}
{lessons_section}
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