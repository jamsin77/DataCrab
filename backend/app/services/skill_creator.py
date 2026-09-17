"""Skill Creator - AI 生成完整 Skill 包"""

from pathlib import Path
from typing import Dict, Any, AsyncGenerator

from loguru import logger

from app.services.llm import llm_manager
from app.services.skill_parser import parse_skill_md, build_skill_md
from app.services.prompt_docs import SAFETY_RULES_DOC, PLATFORM_CONVENTIONS_DOC
from app.services.tool_guidance import get_tool_guidance
from app.services.agent_utils import get_anti_hallucination_section


# 加载统一技能规范（单一真相源）
_SPEC_PATH = Path(__file__).resolve().parent.parent / "defaults" / "SKILL_SPEC.md"
SKILL_SPEC = _SPEC_PATH.read_text(encoding="utf-8") if _SPEC_PATH.exists() else ""


# 常见陷阱警告
_COMMON_PITFALLS = """
## 常见陷阱（必须避免）

### 1. call_tool("query_table_data", ...) 返回 dict，不是 DataFrame
```python
# ❌ 错误：直接当 DataFrame 用
result = call_tool("query_table_data", datasource_id=ds_id, table_name=table_name)
print(result.columns)  # AttributeError: 'dict' object has no attribute 'columns'

# ✅ 正确：从 dict 取出 data 构造 DataFrame
result = call_tool("query_table_data", datasource_id=ds_id, table_name=table_name)
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

### 4. call_tool("write_table_data", ...) 的 records 参数是 list[dict]，不是 DataFrame
```python
# ❌ 错误（传 DataFrame）
call_tool("write_table_data", datasource_id=ds_id, table_name=table_name, records=df)

# ✅ 正确（转成 list[dict]）
call_tool("write_table_data", datasource_id=ds_id, table_name=table_name, records=df.to_dict(orient="records"), if_table_exists="replace")
```

### 5. call_tool("write_table_data", ...) 返回 dict，检查 success 字段
```python
# ❌ 错误
call_tool("write_table_data", datasource_id=ds_id, table_name=table_name, records=data)
print("写入成功")

# ✅ 正确
result = call_tool("write_table_data", datasource_id=ds_id, table_name=table_name, records=data, if_table_exists="replace")
if not result.get("success"):
    raise ValueError(f"写入失败: {result.get('message')}")
```

### 6. 完整端到端示例：查询 → 处理 → 写回
```python
def main(datasource_name, table_name, output_table=None):
    ds_id = call_tool("list_user_datasources", by_name=datasource_name)["id"]
    if not ds_id:
        raise ValueError(f"找不到数据源: {datasource_name}")

    # 查询
    result = call_tool("query_table_data", datasource_id=ds_id, table_name=table_name)
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
    write_result = call_tool("write_table_data",
        datasource_id=ds_id, table_name=target,
        records=df.to_dict(orient="records"),
        if_table_exists="replace",
    )
    if not write_result.get("success"):
        raise ValueError(f"写入失败: {write_result.get('message')}")

    return {"success": True, "count": len(df), "target_table": target, "target_datasource": datasource_name}
```

### 7. 不要用 try-except 吞掉 llm_chat/llm_vision 的异常
```python
# ❌ 错误：吞掉异常，返回 success=True 掩盖平台错误
try:
    result = call_tool("llm_vision", image_path=image_path, prompt=prompt)["result"]
except Exception as e:
    warnings.append(f"llm_vision 调用失败: {e}")
    result = ""  # 空值继续跑
return {"success": True, "warnings": warnings}  # ← LLM 未配置时 OCR 全空但仍报成功

# ✅ 正确：让异常传播，框架捕获后交给调试助手判断
result = call_tool("llm_vision", image_path=image_path, prompt=prompt)["result"]  # 失败时 raise，脚本中止

# ✅ 正确（批量处理允许个别失败）：统计失败率，全失败时 raise
results = []
fail_count = 0
for img in images:
    try:
        results.append(call_tool("llm_vision", image_path=img, prompt=prompt)["result"])
    except Exception:
        fail_count += 1
if fail_count == len(images):
    raise RuntimeError(f"全部 {len(images)} 个 llm_vision 调用失败，可能 LLM 未配置")
```

### 8. call_tool("execute_sql", ...) / call_tool("write_table_data", ...) 返回 dict，检查 success
```python
# ❌ 错误：不检查返回值
result = call_tool("execute_sql", datasource_id=ds_id, sql="SELECT * FROM users")
df = pd.DataFrame(result["data"])  # 如果 execute_sql 失败，data=[] → 空 DataFrame 静默继续

# ✅ 正确
result = call_tool("execute_sql", datasource_id=ds_id, sql="SELECT * FROM users")
if not result.get("success"):
    raise ValueError(f"SQL 执行失败: {result.get('error')}")
df = pd.DataFrame(result["data"], columns=result["columns"])
```

### 9. 每一步关键操作必须 print 进度（防止超时 + 用户可感知）
```python
# ❌ 错误：耗时操作期间无输出，框架判定卡死 → 超时杀进程
frames = call_tool("extract_keyframes", video_path=video_path, max_frames=8)["frames"]
result = call_tool("llm_vision", image_path=image_path, prompt=prompt)["result"]
call_tool("write_table_data", datasource_id=ds_id, table_name=table, records=data)

# ✅ 正确：每步操作前 print 进度，框架持续收到输出不判定超时
print(f"[1/5] 开始抽取关键帧（最多 {max_frames} 帧）...")
frames = call_tool("extract_keyframes", video_path=video_path, max_frames=max_frames)["frames"]
print(f"[1/5] 抽取完成: {len(frames)} 帧")

print(f"[2/5] 开始分析第 {i+1}/{len(frames)} 帧 (时间戳: {frame['timestamp']:.1f}s)...")
result = call_tool("llm_vision", image_path=image_path, prompt=prompt)["result"]
print(f"[2/5] 帧 {i+1} 分析完成: {len(result)} 字符")

print(f"[3/5] 开始写入 {len(records)} 条记录到 {datasource_name}.{table_name}...")
call_tool("write_table_data", datasource_id=ds_id, table_name=table, records=data)
print(f"[3/5] 写入完成")

# 规范：
# 1. 每个耗时操作（llm_vision/llm_chat/extract_keyframes/write_table_data/query_table_data）前后都 print
# 2. 循环体内也要 print（如"正在处理第 3/10 条"）
# 3. 格式: [步骤号/总步骤] 描述... → 完成描述: 数量/结果
# 4. 耗时超过 30 秒的操作必须加中间进度 print（如批量写入每 100 条打一次）
```
"""


SKILL_CREATOR_SYSTEM_PROMPT = """你是一个 Skill Creator，专门为 DataCrab 数据工程智能体创建 Skills。

## 技能规范（必须严格遵守）

""" + SKILL_SPEC + """

""" + PLATFORM_CONVENTIONS_DOC + """

""" + _COMMON_PITFALLS + """

""" + SAFETY_RULES_DOC + """

""" + get_tool_guidance() + """

""" + get_anti_hallucination_section("standard") + """

## description 写作规范（影响技能匹配，必须遵守）

description 是用户找到此技能的唯一语义桥梁——用户说一句话，系统靠 description 判断是否匹配此技能。必须按以下规范写：

1. **场景式描述**：描述"用户什么场景下需要它"，不是"它内部怎么实现"
2. **覆盖常见问法**：把用户可能用的口语化表达、同义词都自然融入 description
   - 用户可能说"导出"而非"迁移"；"清理"而非"清洗"；"拆分"而非"分割"
   - 在 description 里把这些口语词都带上，让用户怎么问都能匹配到
3. **一句话写全**：场景 + 动作 + 同义词，不要只写一个技术术语

示例（对比）：
- ❌ "在不同数据源之间迁移数据，支持列名转换、列删除、列添加及基本数据处理"（技术语言，用户说"导出"匹配不上）
- ✅ "把数据从源表导出/迁移/同步到另一个数据源或文件（Excel/CSV），支持导入、导出、搬数据、列名转换、空值填充等处理"

- ❌ "对数据表进行批量清洗和去重"（用户说"清理脏数据"匹配不上）
- ✅ "清洗/清理数据表的脏数据、空值、重复行，支持去重、删空行、去重复"

## 输出格式（严格遵守）
你必须在一次回复中输出完整的 Skill 包内容。使用以下分隔符：

```yaml
---
name: skill-name
description: 技能描述（按上述 description 写作规范写，覆盖用户常见问法）
skill_type: processing    # processing=数据处理 / analysis=数据分析（只查不改用 analysis）
---
```

## 示例 Skill 包

用户需求："按朝代筛选文物数据"

===SKILL_MD===
---
name: filter-by-dynasty
description: 按朝代筛选/过滤/查找文物数据，支持单朝代和多朝代筛选，可用于查询特定朝代的文物记录
version: "1.0.0"
skill_type: processing
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
    ds_id = call_tool("list_user_datasources", by_name=datasource_name)["id"]
    if not ds_id:
        raise ValueError(f"找不到数据源: {datasource_name}")
    result = call_tool("query_table_data", datasource_id=ds_id, table_name=table_name)
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
===SCRIPT_END===

（可选）如果该技能是数据处理类（skill_type: processing）且需要额外检查规则，输出技能专属规则文件。规则编号用 `SKILL-STD-`/`SKILL-DQ-`/`SKILL-SEC-` 前缀，与全局规则区分。

**重要：数据检查规则必须写到 rules.md（自然语言规则），不要在脚本代码里写检查逻辑。** 脚本只负责数据处理（提取/清洗/转换/写入），检查由 DataInspector 通过 rules.md 执行。如果用户要求加检查规则，输出或修改 rules.md，不要改脚本。

===RULES_MD===
### SKILL-STD-001 文物编号格式
- 适用字段: serial_no,文物编号
- 格式正则: ^GW-\d{6}$
- 严重等级: error

### SKILL-DQ-001 国家级文物编号必填
- 适用字段: serial_no
- 检查逻辑: protection_level 为"国家级"时 serial_no 不能为空
- 阈值: 0
- 严重等级: critical

### SKILL-SEC-001 修复后手机号必须脱敏
- 分类: PII
- 适用字段: phone,contact_phone
- 检测正则: ^1[3-9]\d{9}$
- 检测逻辑: 未脱敏的明文手机号
- 严重等级: critical
===RULES_MD_END===

> rules.md 是可选的：只读分析类技能（skill_type: analysis）不需要；数据处理类技能在需要额外检查（全局规则覆盖不到的）时才输出。无则省略整个 ===RULES_MD=== 段落。
"""


async def generate_skill(prompt: str, datasource_info: str = "", lessons: str = "") -> Dict[str, Any]:
    """根据自然语言描述生成完整 Skill 包"""
    await llm_manager.initialize()

    ds_section = ""
    if datasource_info:
        ds_section = f"""

## 当前用户的数据源
{datasource_info}

请在脚本中使用上述真实的数据源名称和表名，使用 call_tool("list_user_datasources", by_name="数据源名称")["id"] 获取数据源ID。
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
1. SKILL.md（包含 YAML front matter + Markdown 内容，front matter 必须包含 skill_type 字段）
2. scripts/main.py（核心处理脚本）
3. 如果必要，scripts/ 下可以有更多脚本
4. 如果有参考资料，输出 references/
5. （可选）数据处理类技能如需额外检查规则，输出 rules.md（用 ===RULES_MD=== / ===RULES_MD_END=== 包裹）

**skill_type 判定**：该技能执行后是否修改了源数据？只查不改（查询/统计/分析/可视化/生成报告）用 `analysis`，要修改数据（清洗/转换/写入）用 `processing`。

使用以下格式输出：

===SKILL_MD===
（SKILL.md 完整内容）
===SKILL_MD_END===

===SCRIPT:main.py===
（脚本内容）
===SCRIPT_END===

（如有其他脚本，继续用 ===SCRIPT:文件名.py=== 格式）

（可选，仅数据处理类技能且需额外检查时输出）
===RULES_MD===
（rules.md 内容，规则编号用 SKILL-STD-/SKILL-DQ-/SKILL-SEC- 前缀）
===RULES_MD_END===
"""

    try:
        raw_response = await llm_manager.chat_with_messages(
            messages=[
                {"role": "system", "content": SKILL_CREATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=llm_manager._default,
            temperature=0.3,
            max_tokens=8000,
        )
    except Exception as e:
        logger.error(f"Skill Creator 生成失败: {e}")
        raise

    return _parse_creator_response(raw_response)


def _parse_creator_response(raw: str) -> Dict[str, Any]:
    """解析 Skill Creator 的原始输出

    支持两种脚本格式：
    - 完整脚本：===SCRIPT:main.py=== ... ===SCRIPT_END===
    - 脚本补丁：===SCRIPT_PATCH:main.py=== <<<OLD ... >>>NEW ... ===PATCH_END===
      补丁格式输出到 result["script_patches"][filename] = [{old_string, new_string}, ...]
    """
    result = {
        "skill_md": "",
        "scripts": {},
        "script_patches": {},
        "front_matter": {},
        "rules_md": "",
    }

    sections = raw.split("===SKILL_MD===")
    if len(sections) > 1:
        md_part = sections[1].split("===SKILL_MD_END===")[0].strip()
        result["skill_md"] = md_part
        parsed = parse_skill_md(md_part)
        result["front_matter"] = parsed["front_matter"]

    # 解析可选的 rules.md 段落
    rules_sections = raw.split("===RULES_MD===")
    if len(rules_sections) > 1:
        result["rules_md"] = rules_sections[1].split("===RULES_MD_END===")[0].strip()

    # 解析完整脚本（===SCRIPT:xxx=== ... ===SCRIPT_END===）
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

    # 解析脚本补丁（===SCRIPT_PATCH:xxx=== <<<OLD ... >>>NEW ... ===PATCH_END===）
    patch_sections = raw.split("===SCRIPT_PATCH:")
    for i in range(1, len(patch_sections)):
        section = patch_sections[i]
        name_end = section.find("===")
        if name_end == -1:
            continue
        filename = section[:name_end].strip()
        body = section[name_end + 3:]
        # 截到 ===PATCH_END===
        patch_end = body.find("===PATCH_END===")
        if patch_end != -1:
            body = body[:patch_end]

        # 一个文件可能有多个 <<<OLD/>>>NEW 补丁
        patches = []
        old_parts = body.split("<<<OLD")
        for old_part in old_parts[1:]:
            new_split = old_part.split(">>>NEW")
            if len(new_split) != 2:
                continue
            old_str = new_split[0].strip("\n")
            new_str = new_split[1].strip("\n")
            # 去掉可能的尾部空白
            if old_str and new_str is not None:
                patches.append({"old_string": old_str, "new_string": new_str})

        if patches:
            result["script_patches"][filename] = patches

    return result


def create_skill_on_disk(skill_path: Path, skill_md: str, scripts: Dict[str, str], rules_md: str = ""):
    """在磁盘上创建 Skill 文件夹结构"""
    skill_path.mkdir(parents=True, exist_ok=True)

    (skill_path / "SKILL.md").write_text(skill_md, encoding="utf-8")

    scripts_dir = skill_path / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    for filename, content in scripts.items():
        (scripts_dir / filename).write_text(content, encoding="utf-8")

    # 技能专属检查规则（可选）
    if rules_md and rules_md.strip():
        (skill_path / "rules.md").write_text(rules_md, encoding="utf-8")

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

请在脚本中使用上述真实的数据源名称和表名，使用 call_tool("list_user_datasources", by_name="数据源名称")["id"] 获取数据源ID。
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
1. SKILL.md（包含 YAML front matter + Markdown 内容，front matter 必须包含 skill_type 字段）
2. scripts/main.py（核心处理脚本）
3. 如果必要，scripts/ 下可以有更多脚本
4. 如果有参考资料，输出 references/
5. （可选）数据处理类技能如需额外检查规则，输出 rules.md（用 ===RULES_MD=== / ===RULES_MD_END=== 包裹）

**skill_type 判定**：该技能执行后是否修改了源数据？只查不改（查询/统计/分析/可视化/生成报告）用 `analysis`，要修改数据（清洗/转换/写入）用 `processing`。

使用以下格式输出：

===SKILL_MD===
（SKILL.md 完整内容）
===SKILL_MD_END===

===SCRIPT:main.py===
（脚本内容）
===SCRIPT_END===

（如有其他脚本，继续用 ===SCRIPT:文件名.py=== 格式）

（可选，仅数据处理类技能且需额外检查时输出）
===RULES_MD===
（rules.md 内容，规则编号用 SKILL-STD-/SKILL-DQ-/SKILL-SEC- 前缀）
===RULES_MD_END===
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


async def modify_skill_stream(
    current_md: str,
    instruction: str,
    existing_scripts: Dict[str, str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """流式修改 Skill 包（SKILL.md + scripts），复用 generate_skill_stream 的输出格式。

    与 generate_skill_stream 共用 system prompt（命中 prefix cache）；区别在 user prompt：
    生成是「从零创建」，修改是「基于现有内容改用户要求的部分」。
    LLM 输出完整 Skill 包（===SKILL_MD=== + ===SCRIPT:xxx===），端点负责落盘。
    """
    logger.info("[modify_skill] ====== 进入了 skill_creator.modify_skill_stream ======")
    await llm_manager.initialize()

    scripts_section = ""
    if existing_scripts:
        script_parts = []
        for name, content in existing_scripts.items():
            script_parts.append(f"### {name}\n```python\n{content}\n```")
        scripts_section = "\n\n## 现有脚本\n\n" + "\n\n".join(script_parts)

    user_prompt = f"""以下是现有的 Skill 内容：

## 现有 SKILL.md

```markdown
{current_md}
```
{scripts_section}

请根据以下要求修改这个 Skill：
{instruction}

## 输出格式

### SKILL.md（必须输出完整内容）

===SKILL_MD===
（修改后的 SKILL.md 完整内容）
===SKILL_MD_END===

### 脚本修改（禁止输出完整脚本！必须用补丁格式！）

脚本修改必须使用补丁格式，只输出修改的部分，禁止输出完整脚本内容：

===SCRIPT_PATCH:main.py===
<<<OLD
（要替换的原始代码片段，从现有脚本中逐字复制，至少 3 行上下文使其唯一）
>>>NEW
（替换后的新代码片段）
===PATCH_END===

如果有多个修改点，输出多个补丁块：

===SCRIPT_PATCH:main.py===
<<<OLD
（第二处修改的原始代码片段）
>>>NEW
（第二处修改后的新代码片段）
===PATCH_END===

### 重要规则
1. 脚本无需修改时不输出任何脚本部分
2. 脚本需要修改时必须用补丁格式（<<<OLD / >>>NEW），禁止输出 ===SCRIPT:main.py=== 完整脚本
3. old_string 必须从现有脚本中逐字复制（包括缩进和空格），不能凭记忆重写
4. 如果只修改文档说明，不输出脚本部分
5. 数据检查规则必须写到 rules.md（自然语言规则），不要在脚本代码里写检查逻辑。如果用户要求加检查规则，输出 ===RULES_MD=== / ===RULES_MD_END=== 段落，不要改脚本

===RULES_MD===
### SKILL-STD-001 规则名称
- 适用字段: field_name
- 格式正则: ^正则表达式$
- 严重等级: error
===RULES_MD_END===
"""

    from app.services.prompt_docs import PLATFORM_CONVENTIONS_DOC
    _modify_system = "你是 DataCrab Skill 修改助手。你修改现有 Skill 包，不创建新技能。\n\n脚本修改必须用补丁格式（===SCRIPT_PATCH:文件名.py=== + <<<OLD / >>>NEW + ===PATCH_END===），只输出修改的部分，禁止输出完整脚本。old_string 必须从现有脚本中逐字复制。\n\nSKILL.md 可以输出完整内容（用 ===SKILL_MD=== / ===SKILL_MD_END=== 包裹）。\n\n" + PLATFORM_CONVENTIONS_DOC
    logger.info(f"[modify_skill] service进入, instruction={instruction[:100]}")
    logger.info(f"[modify_skill] system_prompt={_modify_system}")
    logger.info(f"[modify_skill] user_prompt_len={len(user_prompt)} SCRIPT_PATCH_in_prompt={'SCRIPT_PATCH' in user_prompt}")
    logger.info(f"[modify_skill] user_prompt前500字符={user_prompt[:500]}")
    full_response = ""
    _progress_sent = set()
    try:
        async for chunk in llm_manager.chat_stream_with_thinking(
            messages=[
                {"role": "system", "content": _modify_system},
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
                yield {"type": "content", "content": chunk["content"]}

                if "===SKILL_MD===" in full_response and "===SKILL_MD_END===" not in full_response:
                    if "skill_md" not in _progress_sent:
                        _progress_sent.add("skill_md")
                        yield {"type": "progress", "message": "正在修改 SKILL.md..."}

                for marker in ["===SCRIPT:", "===SCRIPT_PATCH:"]:
                    if marker in full_response:
                        last_script_start = full_response.rfind(marker)
                        remaining = full_response[last_script_start:]
                        end_marker = "===SCRIPT_END===" if marker == "===SCRIPT:" else "===PATCH_END==="
                        if end_marker not in remaining:
                            script_name_match = remaining[len(marker):].split("===")
                            if script_name_match:
                                skey = f"script_{script_name_match[0]}"
                                if skey not in _progress_sent:
                                    _progress_sent.add(skey)
                                    yield {"type": "progress", "message": f"正在修改脚本 {script_name_match[0]}..."}

    except Exception as e:
        logger.error(f"Skill Creator 流式修改失败: {e}")
        yield {"type": "error", "content": str(e)}
        return

    parsed = _parse_creator_response(full_response)

    if not parsed.get("skill_md"):
        yield {"type": "error", "content": "LLM 未生成有效的 SKILL.md，请重试"}
        return

    # 脚本语法验证
    import ast as _ast
    for _sname, _scontent in parsed.get("scripts", {}).items():
        try:
            _ast.parse(_scontent)
        except SyntaxError as _se:
            yield {"type": "error", "content": f"脚本 {_sname} 语法错误（第{_se.lineno}行）: {_se.msg}"}
            return

    yield {"type": "done", "data": parsed}