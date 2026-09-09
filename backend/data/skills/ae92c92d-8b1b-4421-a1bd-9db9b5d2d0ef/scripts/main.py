from pathlib import Path
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

# 注：pandas 由平台内置提供（变量名 pd），无需 import

# 强制 stdout 实时刷新，避免管道全缓冲导致平台误判「无输出超时」
_print = print


def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _print(*args, **kwargs)


# 标准规则表字段，按顺序输出
STANDARD_COLUMNS = [
    "rule_code",
    "rule_name",
    "category",
    "applicable_fields",
    "format_regex",
    "check_logic",
    "severity",
    "description",
    "source_document",
    "updated_at",
]

DEFAULT_TARGET_DATASOURCE = "通用知识库"
DEFAULT_TARGET_TABLE = "电网知识"

# 数据源名称 -> UUID 内置映射，避免调用 list_user_datasources 时阻塞
_DATASOURCE_UUID_MAP = {
    "文物列表": "ee824f38-36da-46a7-9018-9176a4632745",
    "文物库": "3c55f752-191c-46c4-a5a9-1c959c3438bc",
    "交易数据": "ea913362-567c-4ffa-94b5-33d018c33959",
    "凭证库": "39eedc33-4749-4f7f-84ad-38b6066b4dc0",
    "凭证检索库": "e5f3fffa-b88d-45e9-9f1b-2210024a54af",
    "聊天上传数据": "86e3ba97-4482-4164-9a1f-1b6397e159d1",
    "培训视频": "142dc039-06a8-4050-9b68-715bb34b030c",
    "培训知识库": "e02c6af7-1ba4-4bd2-b677-3c8f82e1fbdf",
    "通用知识库": "e02c6af7-1ba4-4bd2-b677-3c8f82e1fbdf",
    "电网数据": "e270806b-7244-40e7-b66e-11ef9423f158",
}

# 知识库多表存储结构：category -> 子表名。
# 主表（target_table_name，默认「电网知识」）存放综述/范围/术语等「其他」类条目；
# 其余按业务类别分表，便于结构化检索（状态量/评价标准/试验要求是六张表格的主要归宿）。
_CATEGORY_TABLE_SUFFIX = {
    "检修策略": "检修策略",
    "检修项目": "检修策略",
    "状态量": "状态量",
    "评价标准": "评价标准",
    "试验要求": "试验要求",
    "缺陷判断": "缺陷判断",
    "安全要求": "安全要求",
}


def _category_to_table(category: str, main_table: str) -> str:
    """将条目分类映射到目标集合（表）名。主表存放「其他」未分类条目。"""
    suffix = _CATEGORY_TABLE_SUFFIX.get(category)
    if suffix:
        return f"{main_table}_{suffix}"
    return main_table


def _get_datasource_id(name: str) -> str:
    """根据数据源名称获取数据源 ID（优先内置映射，缺失时再查）"""
    print(f"正在查找数据源: {name}", flush=True)
    if name in _DATASOURCE_UUID_MAP:
        ds_id = _DATASOURCE_UUID_MAP[name]
        print(f"数据源已找到(内置映射): {name} (id={ds_id})", flush=True)
        return ds_id
    ds = call_tool("list_user_datasources", by_name=name)
    if not ds or not isinstance(ds, dict) or not ds.get("id"):
        raise ValueError(f"找不到数据源: {name}")
    print(f"数据源已找到: {name} (id={ds['id']})", flush=True)
    return ds["id"]


def _extract_text_from_pdf(path: str) -> str:
    """从 PDF 文件提取全文：调用平台 read_file 工具（主进程解析，不受沙箱限制）。

    不在此处自行解析 PDF，完全依赖平台工具；任何解析失败都如实抛出，不吞异常。
    """
    print(f"  调用平台 read_file 解析 PDF: {path}")
    res = call_tool("read_file", path=path)
    if not isinstance(res, dict):
        raise RuntimeError(f"read_file 返回类型异常（期望 dict）: {res!r}")
    if "error" in res:
        raise RuntimeError(f"read_file 解析 PDF 失败: {res['error']}")
    if "content" not in res:
        raise RuntimeError(f"read_file 未返回 content 字段: {res!r}")
    text = str(res["content"])
    if not text.strip():
        raise RuntimeError(f"read_file 提取的 PDF 文本为空: {path}")
    return text


def _extract_text_from_docx(path: str) -> str:
    """从 Word (.docx) 文件提取全文，包括段落和表格"""
    try:
        import docx
    except ImportError:
        res = call_tool("read_file", path=path)
        if isinstance(res, dict) and res.get("content"):
            return str(res["content"])
        raise ImportError("缺少 Word 解析库 (python-docx)，请安装")

    document = docx.Document(path)
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def _extract_text_from_file(path: str) -> str:
    """根据文件扩展名选择解析方式提取文本"""
    print(f"开始提取文件文本: {path}")
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        text = _extract_text_from_pdf(path)
    elif ext == ".docx":
        text = _extract_text_from_docx(path)
    elif ext in [".txt", ".md", ".csv"]:
        res = call_tool("read_file", path=path)
        if not isinstance(res, dict) or "content" not in res:
            raise RuntimeError(f"read_file 未返回有效内容: {res}")
        text = str(res["content"])
    else:
        # 其他格式尝试使用 read_file 读取文本
        res = call_tool("read_file", path=path)
        if isinstance(res, dict) and "content" in res:
            text = str(res["content"])
        else:
            raise RuntimeError(f"不支持的文件格式或无法读取文件: {path}")
    if not text or not text.strip():
        raise RuntimeError(f"文件内容为空: {path}")
    print(f"文本提取完成，长度 {len(text)} 字符")
    return text


def _split_text(text: str, max_chunk: int = 6000, overlap: int = 1500) -> List[str]:
    """将长文本按最大长度切分为多个片段，尽量在换行或句号处断开。

    采用滑动窗口 + 重叠区（overlap）：相邻片段间保留 overlap 字符的重叠，
    确保跨页/跨段的大表格即使落在切分边界附近，也会被相邻片段完整覆盖。
    """
    if len(text) <= max_chunk:
        return [text]
    if overlap >= max_chunk:
        overlap = max_chunk // 3
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chunk
        if end >= len(text):
            chunks.append(text[start:])
            break
        # 优先在换行符处断开（表格行之间通常以换行分隔，换行处最安全）
        split_pos = text.rfind("\n", start, end)
        if split_pos == -1 or split_pos < start + max_chunk // 2:
            # 其次在句号处断开
            split_pos = text.rfind("。", start, end)
        if split_pos == -1 or split_pos < start + max_chunk // 2:
            split_pos = end
        chunks.append(text[start:split_pos + 1])
        # 下一段起点回退 overlap，形成重叠，避免大表格在边界被切断
        start = max(start + 1, split_pos + 1 - overlap)
    return chunks


def _parse_llm_json(text: str) -> List[Dict[str, Any]]:
    """尝试从 LLM 返回文本中解析 JSON 数组；解析失败时抛异常传递原始片段"""
    # 优先提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    json_str = m.group(1) if m else text
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as first_err:
        # 尝试从第一个 [ 到最后一个 ] 提取
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError as second_err:
                # 容错：LLM 输出常因 max_tokens 截断而缺少结尾，尝试解析数组中
                # 已完整生成的若干对象，仅丢弃最后一条残缺对象。
                repaired = _repair_truncated_json_array(text)
                if repaired:
                    return repaired
                raise RuntimeError(
                    f"LLM 返回内容无法解析为 JSON 数组（原错误: {first_err}；二次提取错误: {second_err}）"
                ) from second_err
        else:
            repaired = _repair_truncated_json_array(text)
            if repaired:
                return repaired
            raise RuntimeError(
                f"LLM 返回内容中未找到 JSON 数组（原错误: {first_err}；返回内容前 300 字符: {text[:300]!r}）"
            ) from first_err
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise RuntimeError(f"LLM 返回内容不是 JSON 数组或对象: {type(data).__name__}")


def _repair_truncated_json_array(text: str) -> List[Dict[str, Any]]:
    """容错解析被截断的 JSON 数组：用 raw_decode 逐个解析对象，丢弃尾部残缺对象。

    仅当解析出至少 1 个完整对象时返回列表；否则返回空列表，由调用方继续抛错。
    """
    def _skip_ws(s: str, i: int) -> int:
        while i < len(s) and s[i] in " \t\r\n":
            i += 1
        return i

    start = text.find("[")
    if start == -1:
        return []
    decoder = json.JSONDecoder()
    idx = _skip_ws(text, start + 1)
    objs = []
    while True:
        idx = _skip_ws(text, idx)
        if idx >= len(text) or text[idx] == "]":
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            # 尾部被截断的残缺对象：丢弃并停止
            break
        objs.append(obj)
        idx = _skip_ws(text, end)
        if idx < len(text) and text[idx] == ",":
            idx += 1
        else:
            break
    # 仅保留 dict 对象，过滤异常类型
    return [o for o in objs if isinstance(o, dict)]


def _extract_outline(text: str, max_len: int = 8000) -> str:
    """抽取文档章节标题 + 每节首段要点，生成精简大纲，供 LLM 设计表结构。

    PDF 纯文本提取后无分页标记，但标准文档（DL/T 1684）有明确条款编号，
    据此抽取「编号 + 标题 + 节首要点」，得到远小于全文的大纲文本。
    """
    heading_re = re.compile(r"^\s*(\d+(?:\.\d+){0,3})\s*[、.．\s]+\s*(\S.*)$")
    lines = text.split("\n")
    parts: List[str] = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = heading_re.match(s)
        if not m or len(s) >= 80:
            continue
        # 收集标题后的前几行作为该节要点（表格文字常紧随其后）
        following = []
        for j in range(i + 1, min(i + 8, len(lines))):
            t = lines[j].strip()
            if not t:
                continue
            following.append(t)
            if len(following) >= 4:
                break
        parts.append(f"{m.group(1)} {m.group(2)}：{' '.join(following)[:180]}")
    outline = "\n".join(parts)
    if len(outline) > max_len:
        outline = outline[:max_len]
    return outline


def _analyze_document_structure(text: str) -> Dict[str, Any]:
    """通读文档大纲，为知识库设计合适的多表结构（需求3：先设计表结构，再提取）。

    返回 schema_plan：
      {
        "main_table": 主表名（存综述/范围/术语等）,
        "tables": [ {"name": 子表名, "description": 表用途, "keywords": [匹配关键词...]}, ... ]
      }
    """
    outline = _extract_outline(text)
    if not outline.strip():
        print("  [结构分析] 未抽取到章节大纲，使用默认多表结构")
        return {
            "main_table": "其他",
            "tables": [
                {"name": "检修策略", "description": "检修分类/周期/策略", "keywords": ["检修策略", "检修周期", "检修项目"]},
                {"name": "状态量", "description": "状态量及检测", "keywords": ["状态量", "监测量", "检测"]},
                {"name": "评价标准", "description": "状态评价/判据", "keywords": ["评价", "判据", "分级"]},
                {"name": "试验要求", "description": "试验/检测要求", "keywords": ["试验", "测试", "检测"]},
                {"name": "缺陷判断", "description": "缺陷/异常判断", "keywords": ["缺陷", "异常", "故障"]},
                {"name": "安全要求", "description": "安全防护", "keywords": ["安全", "防护", "禁止"]},
            ],
        }

    prompt = f"""你是电力行业标准文档结构化专家。请通读下面这份《DL/T 1684 油浸式变压器(电抗器)状态检修导则》的章节大纲，为知识库设计合适的表结构。

要求：
1. 文档中约有六张核心表格，是检修规则的重点；请围绕这些表格及对应章节设计子表。
2. 每个子表对应一类知识（如状态量、评价标准、试验要求、检修策略、缺陷判断、安全要求等），不要只设计一张大表。
3. 综述、范围、术语、引用文件等归入主表「其他」。

必须只输出一个 JSON 对象（不要 Markdown 代码围栏、不要解释），结构如下：
{{
  "main_table": "其他",
  "tables": [
    {{"name": "子表名", "description": "该表存放哪类知识", "keywords": ["关键词1", "关键词2"]}}
  ]
}}

文档大纲如下：
---
{outline}
---"""
    for attempt, cfg in enumerate([
        {"temperature": 0.0, "max_tokens": 2000},
        {"temperature": 0.2, "max_tokens": 4000},
    ], 1):
        try:
            response = call_tool(
                "llm_generate",
                prompt=prompt,
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
            )
            if not isinstance(response, dict):
                raise RuntimeError(f"llm_generate 返回非 dict: {response!r}")
            if "error" in response:
                raise RuntimeError(f"llm_generate 失败: {response['error']}")
            content = str(response.get("content") or "").strip()
            if not content:
                raise RuntimeError("llm_generate 返回空 content")
            parsed = _parse_llm_json(content)
            if parsed and isinstance(parsed[0], dict) and "tables" in parsed[0]:
                data = parsed[0]
                print(
                    f"  [结构分析] 设计出 {len(data.get('tables') or [])} 张子表: "
                    f"{[t.get('name') for t in (data.get('tables') or [])]}"
                )
                return data
            raise RuntimeError(f"结构分析结果缺少 tables 字段: {content[:200]!r}")
        except Exception as e:
            print(f"  [结构分析] 第 {attempt} 次失败: {e}")
            if attempt == 2:
                print("  [结构分析] 分析失败，使用默认多表结构兜底")
    # 兜底：默认多表结构
    return {
        "main_table": "其他",
        "tables": [
            {"name": "检修策略", "description": "检修分类/周期/策略", "keywords": ["检修策略", "检修周期", "检修项目"]},
            {"name": "状态量", "description": "状态量及检测", "keywords": ["状态量", "监测量", "检测"]},
            {"name": "评价标准", "description": "状态评价/判据", "keywords": ["评价", "判据", "分级"]},
            {"name": "试验要求", "description": "试验/检测要求", "keywords": ["试验", "测试", "检测"]},
            {"name": "缺陷判断", "description": "缺陷/异常判断", "keywords": ["缺陷", "异常", "故障"]},
            {"name": "安全要求", "description": "安全防护", "keywords": ["安全", "防护", "禁止"]},
        ],
    }


def _extract_rules_from_text(
    text: str,
    max_workers: int = 3,
    schema_plan: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """使用 LLM 并发从文本提取关键知识/规则条目（每条含 title/content/category 等）

    提取是 LLM I/O 密集型任务，使用多路并发提速；切片更细（3000 字符），
    避免表格与规则细节因跨段截断而丢失。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 先做一次轻量探测：推理型(reasoning)模型下 llm_generate 的 content 恒为空，
    # 此时直接走规则切分，避免 9 次空转 + 单次 180s 超时叠加导致 300s 卡死。
    probe = call_tool(
        "llm_generate",
        prompt="只回复两个字：正常",
        temperature=0.0,
        max_tokens=50,
    )
    probe_content = ""
    if isinstance(probe, dict) and "error" not in probe:
        probe_content = str(probe.get("content") or "").strip()
    if not probe_content:
        raise RuntimeError(
            "LLM 提取不可用：llm_generate 探测调用返回空 content（当前可能为推理型模型，"
            "其输出进入 reasoning_content 而 content 为空）。"
            "未提取到任何知识，按「一条也提取不出来即报错退出」策略终止。"
        )
    print("  [探测] llm_generate 正常返回，继续 LLM 并发提取。")

    chunks = _split_text(text, max_chunk=6000, overlap=1500)
    total = len(chunks)
    print(f"  [LLM提取] 文本共 {total} 段（6000字符/段，重叠1500），并发 {max_workers} 路提取...")

    def _build_prompt(chunk: str) -> str:
        schema_block = ""
        main_table = "其他"
        if schema_plan:
            tables = schema_plan.get("tables") or []
            main_table = schema_plan.get("main_table") or "其他"
            rows = [f"- 主表「{main_table}」：综述、范围、术语、引用文件等综合内容"]
            for t in tables:
                kw = "、".join(t.get("keywords") or [])
                rows.append(
                    f"- 子表「{t.get('name')}」：{t.get('description')}"
                    + (f"（关键词：{kw}）" if kw else "")
                )
            schema_block = "【知识库表结构】\n" + "\n".join(rows) + "\n\n"

        return f"""请从以下电力设备检修导则文档片段中提取关键知识和规则，直接从正文输出结果，不要输出任何思考过程或推理文字。

对每条知识/规则输出一个 JSON 对象，字段如下：
- title: 条目标题（简短，概括本条知识/规则；若原文有条款编号如 5.1.2.3 请保留在标题里）
- content: 条目完整内容（保留原文关键表述、数值、阈值、周期、判据，不要遗漏细节）
- category: 分类，可选：检修策略/状态量/评价标准/检修项目/试验要求/缺陷判断/安全要求/其他
- table: 本条归属的表名（从下方【知识库表结构】中选择最匹配的一个表名；无法判断时填主表名「{main_table}」）
- tags: 关键词，多个用逗号分隔
- severity: 重要程度，可选：high/medium/low

{schema_block}【表格复原要求（非常重要）】
正文中混有表格内容，且表格常被转置（行列互换）。提取时：
1. 先识别表头和单元格边界，还原「表头字段 + 对应取值」的行列对应关系；
2. 转置表格要还原为「每行一个设备/项目，每列一个属性」的形式；
3. 表格中每一行（每一组完整对应关系）必须作为一条独立规则提取，字段名作为关键词；
4. 不得因表格文字被纵向堆叠而丢弃可识别内容；
5. 若表格跨页/跨段，请结合上下文把被截断的行补全，不要漏行。

要求：
- 每段最多提取 50 条，只保留有实质内容的条目，忽略目录、前言、引用文件清单、过渡性语句。
- 表格行是核心知识，必须逐行提取，不得整列合并、不得因为内容相似就跳过某行。
- 相近但字段不同的表格行不要合并，宁可多提不可漏提。
- 内容用简体中文精炼转述，但关键数值、阈值、周期、判据必须逐字保留。

必须只输出一个 JSON 数组（以 [ 开头、以 ] 结尾），不要输出 Markdown 代码围栏、解释或任何其他文字。

文档片段如下：
---
{chunk}
---"""

    # 重试参数阶梯：提取失败时逐级调大 max_tokens、微调 temperature，
    # 以应对「输出被 max_tokens 截断 / JSON 解析失败 / 空 content」等不同失败原因。
    RETRY_CONFIGS = [
        {"temperature": 0.0, "max_tokens": 8192},
        {"temperature": 0.1, "max_tokens": 8192},
        {"temperature": 0.2, "max_tokens": 12000},
    ]

    def _call_once(idx: int, chunk: str, attempt: int, cfg: Dict[str, Any]):
        """对单个切片发起一次 LLM 调用。

        返回:
          - "ok"      : (标记, parsed列表) 成功
          - "timeout" : (标记, None) 平台调用超时（原地重试无效，应立即细切）
          - "fail"    : (标记, None) 其他失败（可换参数重试）
        """
        prompt = _build_prompt(chunk)
        try:
            response = call_tool(
                "llm_generate",
                prompt=prompt,
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
            )
        except Exception as e:
            msg = str(e).lower()
            if "timed out" in msg or "timeout" in msg:
                print(f"    [超时] 第 {idx} 段第 {attempt} 次调用超时，立即转入细切...")
                return "timeout", None
            print(f"    [重试] 第 {idx} 段第 {attempt} 次调用异常: {e}，换参数重试...")
            return "fail", None
        if not isinstance(response, dict):
            print(f"    [重试] 第 {idx} 段第 {attempt} 次返回非 dict: {response!r}")
            return "fail", None
        if "error" in response:
            print(f"    [重试] 第 {idx} 段第 {attempt} 次调用失败: {response['error']}")
            return "fail", None
        content = str(response.get("content") or "").strip()
        if not content:
            print(f"    [重试] 第 {idx} 段第 {attempt} 次返回空 content")
            return "fail", None
        try:
            parsed = _parse_llm_json(content)
        except Exception as e:
            print(f"    [重试] 第 {idx} 段第 {attempt} 次 JSON 解析失败: {e}（返回前200字符: {content[:200]!r}）")
            return "fail", None
        if not parsed:
            print(f"    [重试] 第 {idx} 段第 {attempt} 次解析结果为空列表")
            return "fail", None
        return "ok", parsed

    def _process_with_refinement(idx: int, chunk: str):
        """对一段文本提取知识：先原片多参数重试；遇超时或仍失败则细切（较小窗口+重叠）
        后再逐个提取，尽量不丢失跨页/跨段的大表格内容（需求1/2）。"""
        last_err = "原片 "
        # 第一层：原片多参数重试（遇 timeout 立即停止原地重试，转入细切）
        for attempt, cfg in enumerate(RETRY_CONFIGS, 1):
            status, parsed = _call_once(idx, chunk, attempt, cfg)
            if status == "ok":
                return idx, parsed
            if status == "timeout":
                last_err = f"原片第 {attempt} 次超时"
                break
            last_err = f"原片 {len(RETRY_CONFIGS)} 次重试均失败"
        # 第二层：小切片重切再提取（针对跨页大表格/长段落：更小窗口更易命中完整行）
        print(f"    [细切重试] 第 {idx} 段失败（{last_err}），改为 1800 字符/重叠 600 细切后重试...")
        sub_chunks = _split_text(chunk, max_chunk=1800, overlap=600)
        all_parsed: List[Dict[str, Any]] = []
        sub_ok = 0
        for s_idx, sub in enumerate(sub_chunks, 1):
            got = None
            for attempt, cfg in enumerate(RETRY_CONFIGS, 1):
                status, got = _call_once(s_idx, sub, attempt, cfg)
                if status == "ok":
                    break
                if status == "timeout":
                    break  # 细切片再超时也放弃该片，不再空转
            if got is not None:
                all_parsed.extend(got)
                sub_ok += 1
        if not all_parsed:
            raise RuntimeError(f"第 {idx} 段原片与细切片重试均失败。{last_err}")
        print(f"    [细切成功] 第 {idx} 段细切 {len(sub_chunks)} 片，{sub_ok} 片成功，共 {len(all_parsed)} 条")
        return idx, all_parsed

    results_by_idx = {}
    errors = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_with_refinement, idx, chunk): idx for idx, chunk in enumerate(chunks, 1)}
        done = 0
        for fut in as_completed(futures):
            idx = futures[fut]
            done += 1
            try:
                _, parsed = fut.result()
                results_by_idx[idx] = parsed
                print(f"    [进度 {done}/{total}] 第 {idx} 段提取到 {len(parsed)} 条")
            except Exception as e:
                errors.append((idx, str(e)))
                print(f"    [错误] 第 {idx}/{total} 段处理失败: {e}")

    if errors and not results_by_idx:
        # 全部失败：直接报错退出，不再降级（一条都提取不出来即终止）
        raise RuntimeError(
            f"LLM 提取全部失败（{len(errors)} 段），未提取到任何知识/规则: {errors}"
        )
    if errors:
        # 部分失败：使用成功部分，但明确警告（不吞异常）
        print(f"  [警告] LLM 提取有 {len(errors)} 段失败（已跳过）: {errors}")

    # 按切片原始顺序拼接
    all_entries = []
    for idx in sorted(results_by_idx):
        all_entries.extend(results_by_idx[idx])

    # 仅去除「标题与内容均完全相同」的条目。
    # 表格中不同行即使 title 相同（例如同为「状态量限值」），content 必然不同，
    # 必须全部保留，不能按 title 合并，否则 30 行表格会被压成 1 行。
    unique = {}
    for e in all_entries:
        title = str(e.get("title") or "").strip()
        content = str(e.get("content") or "").strip()
        if not title or not content:
            continue
        key = (title, content)
        if key not in unique:
            unique[key] = e
    return list(unique.values())


def _chapter_based_extract(text: str) -> List[Dict[str, Any]]:
    """LLM 不可用时的降级提取：按章节/条款号切分标准文档，生成知识条目。

    适用于 DL/T 1684 等标准文件（章节编号形如 1、4.1、5.2.1）。
    不依赖 LLM，纯规则切分；超长章节按段落再切分，保证单条知识块大小适中。
    """
    CATEGORY_KEYWORDS = [
        ("检修策略", ["检修策略", "检修周期", "状态检修", "检修项目", "检修分类", "A类检修", "B类检修", "C类检修", "D类检修"]),
        ("试验要求", ["试验", "测试", "检验", "检测", "测量"]),
        ("状态量", ["状态量", "监测量", "检测量", "在线监测", "带电检测"]),
        ("评价标准", ["评价", "评估", "判据", "分级", "等级", "状态评价", "正常状态", "注意状态", "异常状态", "严重状态"]),
        ("缺陷判断", ["缺陷", "异常", "故障", "危急", "严重", "一般"]),
        ("安全要求", ["安全", "危险", "防护", "警告", "注意", "禁止", "严禁"]),
    ]

    def _guess_category(title: str, content: str) -> str:
        blob = title + " " + content[:300]
        for cat, kws in CATEGORY_KEYWORDS:
            if any(kw in blob for kw in kws):
                return cat
        return "其他"

    heading_re = re.compile(r"^\s*(\d+(?:\.\d+){0,3})\s*[、.．\s]\s*(\S.*)$")

    entries = []
    current_title = None
    current_lines = []

    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        m = heading_re.match(s)
        is_heading = bool(m) and len(s) < 80
        if is_heading:
            if current_title:
                content = "\n".join(current_lines).strip()
                if len(content) >= 15:
                    entries.append({
                        "title": current_title,
                        "content": content,
                        "category": _guess_category(current_title, content),
                        "tags": "",
                        "severity": "medium",
                    })
            current_title = f"{m.group(1)} {m.group(2)}".strip()
            current_lines = []
        else:
            if current_title:
                current_lines.append(s)
            elif s:
                current_lines.append(s)

    if current_title:
        content = "\n".join(current_lines).strip()
        if len(content) >= 15:
            entries.append({
                "title": current_title,
                "content": content,
                "category": _guess_category(current_title, content),
                "tags": "",
                "severity": "medium",
            })

    # 超长章节（>3000 字）按段落再切分
    final = []
    for e in entries:
        if len(e["content"]) <= 3000:
            final.append(e)
            continue
        paras = [p for p in re.split(r"\n+", e["content"]) if p.strip()]
        buf = ""
        part = 0
        for p in paras:
            if buf and len(buf) + len(p) > 3000:
                part += 1
                final.append({
                    "title": f"{e['title']}({part})",
                    "content": buf.strip(),
                    "category": e["category"],
                    "tags": e["tags"],
                    "severity": e["severity"],
                })
                buf = p
            else:
                buf = (buf + "\n" + p).strip()
        if buf:
            final.append({
                "title": f"{e['title']}({part + 1})" if part else e["title"],
                "content": buf.strip(),
                "category": e["category"],
                "tags": e["tags"],
                "severity": e["severity"],
            })
    return final


def _to_chroma_records(entries: List[Dict[str, Any]], source_document: str) -> List[Dict[str, Any]]:
    """将提取的条目转换为 ChromaDB 写入所需的记录结构 (id/document/metadata)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []
    seen = set()
    for e in entries:
        title = str(e.get("title") or "").strip()
        content = str(e.get("content") or "").strip()
        if not title or not content:
            continue
        category = str(e.get("category") or "其他").strip()
        table_assign = str(e.get("table") or "").strip()  # LLM 判定的表归属（需求3）
        tags = str(e.get("tags") or "").strip()
        severity = str(e.get("severity") or "medium").strip()
        # 生成稳定唯一 id：标题清洗 + 序号
        base_id = "".join(ch if ch.isalnum() else "_" for ch in title)[:60]
        cid = f"dl1684_{base_id}"
        seq = 0
        while cid in seen:
            seq += 1
            cid = f"dl1684_{base_id}_{seq}"
        seen.add(cid)
        document = f"【{category}】{title}\n{content}"
        if tags:
            document += f"\n关键词：{tags}"
        records.append({
            "id": cid,
            "document": document,
            "metadata": {
                "title": title,
                "category": category,
                "table": table_assign,
                "tags": tags,
                "severity": severity,
                "source_document": source_document,
                "updated_at": now,
            },
        })
    return records


def _partition_records_by_table(records: List[Dict[str, Any]], main_table: str) -> Dict[str, List[Dict[str, Any]]]:
    """将记录路由到不同集合（表）。

    优先级：条目若带 LLM 判定的 table 归属（需求3，与设计出的表结构匹配），
    则直接写入对应子表；否则回退按 category 映射路由；「其他」/主表判定写入主表。
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        meta = r.get("metadata") or {}
        tbl_assign = str(meta.get("table") or "").strip()
        if tbl_assign and tbl_assign != "其他" and tbl_assign != main_table:
            # LLM 明确指定了子表名：规范化为 主表_子表 形式
            tbl = tbl_assign if tbl_assign.startswith(main_table) else f"{main_table}_{tbl_assign}"
        else:
            cat = str(meta.get("category") or "其他").strip()
            tbl = _category_to_table(cat, main_table)
        groups.setdefault(tbl, []).append(r)
    return groups


def _write_chroma(ds_id: str, table_name: str, records: List[Dict[str, Any]], if_table_exists: str = "replace") -> int:
    """分批并发写入 ChromaDB 集合，返回写入总条数。

    首批用传入策略（如 replace 清空重建）串行写入，确保清空/建表先于追加完成；
    其余批次用 append 策略并发写入（每条记录带唯一 id，并发 append 幂等）。
    """
    if not records:
        return 0
    from concurrent.futures import ThreadPoolExecutor, as_completed

    batch_size = 400
    batches = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
    total = len(records)
    batch_total = len(batches)
    print(f"开始写入知识库集合 {table_name}，共 {total} 条，分 {batch_total} 批（并发 append）")

    # 首批用传入策略串行写（须先于并发 append 完成）
    first = batches[0]
    print(f"  正在写入第 1/{batch_total} 批 ({len(first)} 条，strategy={if_table_exists})...")
    result = call_tool(
        "write_table_data",
        datasource_id=ds_id,
        table_name=table_name,
        records=first,
        if_table_exists=if_table_exists,
    )
    if not result.get("success"):
        raise RuntimeError(f"写入数据失败: {result.get('message')}")

    # 剩余批次并发 append
    rest = batches[1:]
    if rest:
        def _append(batch_num: int, batch: List[Dict[str, Any]]) -> int:
            print(f"  正在写入第 {batch_num}/{batch_total} 批 ({len(batch)} 条，strategy=append)...")
            r = call_tool(
                "write_table_data",
                datasource_id=ds_id,
                table_name=table_name,
                records=batch,
                if_table_exists="append",
            )
            if not r.get("success"):
                raise RuntimeError(f"写入数据失败(第 {batch_num} 批): {r.get('message')}")
            return len(batch)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_append, i + 2, b): i + 2 for i, b in enumerate(rest)}
            for fut in as_completed(futures):
                fut.result()  # 传播异常，不吞

    print(f"写入完成: {total} 条")
    return total


def extract_rules_to_kb(
    document_paths: str,
    target_datasource_name: str = DEFAULT_TARGET_DATASOURCE,
    target_table_name: str = DEFAULT_TARGET_TABLE,
    if_table_exists: str = "replace",
) -> Dict[str, Any]:
    """主业务函数：解析文档 -> LLM 提取规则 -> 合并写入知识库表"""
    # 1. 解析并校验文档路径
    paths = [p.strip() for p in document_paths.split(",") if p.strip()]
    if not paths:
        raise ValueError("document_paths 参数不能为空，请提供至少一个 PDF/Word 文件路径")

    # 2. 获取目标数据源 ID
    target_ds_id = _get_datasource_id(target_datasource_name)

    # 3. 逐个文档：先通读大纲设计多表结构，再提取关键知识与规则
    all_entries = []
    schema_plan: Optional[Dict[str, Any]] = None
    for idx, path in enumerate(paths, 1):
        print(f"[{idx}/{len(paths)}] 处理文档: {path}")
        text = _extract_text_from_file(path)
        print(f"  文档文本总长 {len(text)} 字符")

        # 需求3：先通读文档大纲，为知识库设计合适的多表结构
        schema_plan = _analyze_document_structure(text)
        main_tbl = schema_plan.get("main_table") or "其他"
        sub_tbls = [t.get("name") for t in (schema_plan.get("tables") or [])]
        print(f"  [表结构] 主表「{main_tbl}」+ {len(sub_tbls)} 张子表: {sub_tbls}")

        entries = _extract_rules_from_text(text, schema_plan=schema_plan)
        for e in entries:
            e["source_document"] = Path(path).name
        all_entries.extend(entries)
        print(f"  从 {Path(path).name} 提取到 {len(entries)} 条知识/规则")

    if not all_entries:
        raise RuntimeError(
            "未提取到任何知识/规则：LLM 提取返回空，请检查文档文本内容与 LLM 服务是否正常"
        )

    print(f"共提取到 {len(all_entries)} 条知识/规则，准备写入知识库")

    # 4. 转换为 ChromaDB 记录结构 (id/document/metadata)
    source_doc = Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} 个文档"
    records = _to_chroma_records(all_entries, source_doc)
    if not records:
        raise RuntimeError(
            f"转换后无有效记录：共 {len(all_entries)} 条条目，但均缺少有效 title/content，无法写入知识库。"
        )

    # 5. 按分类将记录路由到不同集合（多表存储）
    grouped = _partition_records_by_table(records, target_table_name)
    print("知识库多表存储方案：")
    for tbl, recs in grouped.items():
        print(f"  - 集合「{tbl}」: {len(recs)} 条")

    # 6. 并发写入多个集合（每个集合内部也分批并发 append）。
    #    每个集合独立写，集合间互不依赖，可并发提速。
    from concurrent.futures import ThreadPoolExecutor, as_completed

    written_total = 0
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_write_chroma, target_ds_id, tbl, recs, if_table_exists): tbl
            for tbl, recs in grouped.items()
        }
        for fut in as_completed(futures):
            tbl = futures[fut]
            n = fut.result()  # 传播异常，不吞
            written_total += n
            print(f"  [完成] 集合「{tbl}」写入 {n} 条")

    return {
        "success": True,
        "extracted_rules": len(all_entries),
        "total_rules_written": written_total,
        "target_table": target_table_name,
        "target_datasource": target_datasource_name,
        "tables_written": {tbl: len(recs) for tbl, recs in grouped.items()},
    }


def main(**params: Any) -> Dict[str, Any]:
    """入口函数：支持参数别名映射"""
    param_aliases = {
        "document_paths": ["document_paths", "file_paths", "files", "paths"],
        "target_datasource_name": ["target_datasource_name", "target_datasource", "output_datasource"],
        "target_table_name": ["target_table_name", "target_table", "output_table"],
        "if_table_exists": ["if_table_exists", "write_strategy"],
    }

    def get_param(key: str, default: Any = None) -> Any:
        for alias in param_aliases.get(key, [key]):
            if alias in params and params[alias] is not None:
                return params[alias]
        return default

    document_paths = get_param("document_paths")
    target_ds = get_param("target_datasource_name", DEFAULT_TARGET_DATASOURCE)
    target_table = get_param("target_table_name", DEFAULT_TARGET_TABLE)
    if_table_exists = get_param("if_table_exists", "replace")

    if not document_paths:
        raise ValueError("缺少必填参数 document_paths：请提供 PDF/Word 文件路径，多个用逗号分隔")

    return extract_rules_to_kb(
        document_paths=document_paths,
        target_datasource_name=target_ds,
        target_table_name=target_table,
        if_table_exists=if_table_exists,
    )