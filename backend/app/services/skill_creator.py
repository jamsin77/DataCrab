"""Skill Creator - AI 生成完整 Skill 包"""

from pathlib import Path
from typing import Dict, Any, AsyncGenerator

from loguru import logger

from app.services.llm import llm_manager
from app.services.skill_parser import parse_skill_md, build_skill_md
from app.services.prompt_docs import SANDBOX_TOOLS_DOC, SAFETY_RULES_DOC, PLATFORM_CONVENTIONS_DOC
from app.services.tool_guidance import get_tool_guidance
from app.services.agent_utils import get_anti_hallucination_section


# 加载统一技能规范（单一真相源）
_SPEC_PATH = Path(__file__).resolve().parent.parent / "defaults" / "SKILL_SPEC.md"
SKILL_SPEC = _SPEC_PATH.read_text(encoding="utf-8") if _SPEC_PATH.exists() else ""


# 常见陷阱警告
_COMMON_PITFALLS = """
## 常见陷阱（必须避免）

### 1. query_table_data 返回 dict，不是 DataFrame
```python
# ❌ 错误：直接当 DataFrame 用
result = query_table_data(ds_id, table_name)
print(result.columns)  # AttributeError: 'dict' object has no attribute 'columns'

# ✅ 正确：从 dict 取出 data 构造 DataFrame
result = query_table_data(ds_id, table_name)
if not result.get("success"):
    raise ValueError(f"查询失败: {result.get('error')}")
df = pd.DataFrame(result["data"], columns=result["columns"])
```

### 2. 不要用 if result: 判断查询成功
```python
# ❌ 错误（空 dict 或 success=False 的 dict 行为不可预测）
if result:
    process(result)

# ✅ 正确
if result.get("success") and result.get("data") is not None:
    process(result["data"])
```

### 3. 不要用 if data: 判断 DataFrame 是否为空
```python
# ❌ 错误（会抛 ValueError: truth value of DataFrame is ambiguous）
if df:
    process(df)

# ✅ 正确
if df is not None and not df.empty:
    process(df)
```

### 4. write_table_data 的 records 参数是 list[dict]，不是 DataFrame
```python
# ❌ 错误（传 DataFrame）
write_table_data(ds_id, table_name, records=df)

# ✅ 正确（转成 list[dict]）
write_table_data(ds_id, table_name, records=df.to_dict(orient="records"), if_table_exists="replace")
```

### 5. write_table_data 返回 dict，检查 success 字段
```python
# ❌ 错误
write_table_data(ds_id, table_name, records=data)
print("写入成功")

# ✅ 正确
result = write_table_data(ds_id, table_name, records=data, if_table_exists="replace")
if not result.get("success"):
    raise ValueError(f"写入失败: {result.get('message')}")
```

### 6. 完整端到端示例：查询 → 处理 → 写回
```python
def main(datasource_name, table_name, output_table=None):
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        raise ValueError(f"找不到数据源: {datasource_name}")

    # 查询
    result = query_table_data(ds_id, table_name)
    if not result.get("success"):
        raise ValueError(f"查询失败: {result.get('error')}")
    df = pd.DataFrame(result["data"], columns=result["columns"])
    if df.empty:
        return {"success": True, "message": "无数据", "count": 0}

    # 处理
    df["processed_at"] = pd.Timestamp.now().isoformat()
    print(f"处理完成: {len(df)} 行")

    # 写回
    target = output_table or table_name
    write_result = write_table_data(
        ds_id, target,
        records=df.to_dict(orient="records"),
        if_table_exists="replace",
    )
    if not write_result.get("success"):
        raise ValueError(f"写入失败: {write_result.get('message')}")

    return {"success": True, "count": len(df), "target_table": target}
```

### 7. 不要用 try-except 吞掉 llm_chat/llm_vision 的异常
```python
# ❌ 错误：吞掉异常，返回 success=True 掩盖平台错误
try:
    result = llm_vision(image_path, prompt)
except Exception as e:
    warnings.append(f"llm_vision 调用失败: {e}")
    result = ""  # 空值继续跑
return {"success": True, "warnings": warnings}  # ← LLM 未配置时 OCR 全空但仍报成功

# ✅ 正确：让异常传播，框架捕获后交给调试助手判断
result = llm_vision(image_path, prompt)  # 失败时 raise，脚本中止

# ✅ 正确（批量处理允许个别失败）：统计失败率，全失败时 raise
results = []
fail_count = 0
for img in images:
    try:
        results.append(llm_vision(img, prompt))
    except Exception:
        fail_count += 1
if fail_count == len(images):
    raise RuntimeError(f"全部 {len(images)} 个 llm_vision 调用失败，可能 LLM 未配置")
```

### 8. execute_sql / call_operator 返回 dict，检查 success
```python
# ❌ 错误：不检查返回值
result = execute_sql(ds_id, "SELECT * FROM users")
df = pd.DataFrame(result["data"])  # 如果 execute_sql 失败，data=[] → 空 DataFrame 静默继续

# ✅ 正确
result = execute_sql(ds_id, "SELECT * FROM users")
if not result.get("success"):
    raise ValueError(f"SQL 执行失败: {result.get('error')}")
df = pd.DataFrame(result["data"], columns=result["columns"])
```
"""


SKILL_CREATOR_SYSTEM_PROMPT = """你是一个 Skill Creator，专门为 DataCrab 数据工程智能体创建 Skills。

## 技能规范（必须严格遵守）

""" + SKILL_SPEC + """

""" + SANDBOX_TOOLS_DOC + """

""" + PLATFORM_CONVENTIONS_DOC + """

""" + _COMMON_PITFALLS + """

""" + SAFETY_RULES_DOC + """

""" + get_tool_guidance() + """

""" + get_anti_hallucination_section("standard") + """

## 输出格式（严格遵守）
你必须在一次回复中输出完整的 Skill 包内容。使用以下分隔符：

```yaml
---
name: skill-name
description: 技能描述
---
```

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

def _load_data(datasource_name: str, table_name: str) -> pd.DataFrame:
    # 从数据源加载表数据
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        raise ValueError(f"找不到数据源: {datasource_name}")
    result = query_table_data(ds_id, table_name)
    if not result.get("success"):
        raise ValueError(f"读取数据失败: {result.get('error')}")
    return pd.DataFrame(result["data"], columns=result["columns"])

def _find_dynasty_column(df: pd.DataFrame) -> str:
    # 自动检测朝代列名
    for col in df.columns:
        if "朝代" in col or "dynasty" in col.lower():
            return col
    raise ValueError(f"未找到朝代列，现有列: {list(df.columns)}")

def _filter_by_dynasty(df: pd.DataFrame, dynasties: str) -> pd.DataFrame:
    # 按朝代筛选
    dynasty_col = _find_dynasty_column(df)
    dynasty_list = [d.strip() for d in dynasties.split(",") if d.strip()]
    filtered = df[df[dynasty_col].astype(str).isin(dynasty_list)]
    print(f"筛选完成: {len(df)} → {len(filtered)} 条 (朝代: {', '.join(dynasty_list)})")
    return filtered

def _save_result(df: pd.DataFrame, output_dir: Optional[str], table_name: str) -> None:
    # 保存结果到文件
    if output_dir:
        import os
        path = os.path.join(output_dir, f"filtered_{table_name}.csv")
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"已保存: {path}")

def filter_by_dynasty(
    datasource_name: str,
    table_name: str = "artifacts",
    dynasties: str = "",
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    # 主业务函数：编排各步骤
    df = _load_data(datasource_name, table_name)
    if df.empty:
        return {"success": True, "filtered_count": 0, "data": []}
    filtered = _filter_by_dynasty(df, dynasties)
    _save_result(filtered, output_dir, table_name)
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
            max_tokens=8000,
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
    _progress_sent = set()
    try:
        async for chunk in llm_manager.chat_stream_with_thinking(
            messages=[
                {"role": "system", "content": SKILL_CREATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        ):
            t = chunk.get("type", "")
            if t == "model":
                yield {"type": "model", "content": chunk["content"]}
            elif t == "thinking":
                yield {"type": "thinking", "content": chunk["content"]}
            elif t == "content":
                full_response += chunk["content"]
                yield {"type": "chunk", "content": chunk["content"]}

                if "===SKILL_MD===" in full_response and "===SKILL_MD_END===" not in full_response:
                    if "skill_md" not in _progress_sent:
                        _progress_sent.add("skill_md")
                        yield {"type": "progress", "message": "正在生成 SKILL.md..."}

                for marker in ["===SCRIPT:"]:
                    if marker in full_response:
                        last_script_start = full_response.rfind(marker)
                        remaining = full_response[last_script_start:]
                        if "===SCRIPT_END===" not in remaining:
                            script_name_match = remaining[len(marker):].split("===")
                            if script_name_match:
                                skey = f"script_{script_name_match[0]}"
                                if skey not in _progress_sent:
                                    _progress_sent.add(skey)
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

    # 脚本验证：AST 语法检查 + _strip_main_block 检查
    yield {"type": "status", "message": "正在验证脚本..."}
    import ast as _ast
    import re as _re
    _warnings = []
    for _sname, _scontent in parsed.get("scripts", {}).items():
        # AST 语法验证
        try:
            _ast.parse(_scontent)
        except SyntaxError as _se:
            yield {"type": "error", "message": f"脚本 {_sname} 语法错误（第{_se.lineno}行）: {_se.msg}"}
            return
        # 检查函数是否在 if __name__ 之后（会被 _strip_main_block 删除）
        _if_match = _re.search(r'\nif\s+__name__\s*==\s*["\']__main__["\']\s*:', _scontent)
        if _if_match:
            _after = _scontent[_if_match.end():]
            if _re.search(r'^\s*def\s+', _after, _re.MULTILINE):
                _w = f"脚本 {_sname} 有函数定义在 if __name__ 之后，执行时会被自动删除导致 NameError"
                _warnings.append(_w)
                yield {"type": "warning", "message": _w}
        # 检查是否有 main 入口函数
        if not _re.search(r'^def\s+main\s*\(', _scontent, _re.MULTILINE):
            _w = f"脚本 {_sname} 未找到 main() 入口函数"
            _warnings.append(_w)
            yield {"type": "warning", "message": _w}

    if _warnings:
        yield {"type": "status", "message": f"验证完成：{len(_warnings)} 个警告（技能已生成，建议在调试助手中修复）"}
    else:
        yield {"type": "status", "message": "验证通过，脚本符合规范"}

    yield {"type": "done", "data": parsed}