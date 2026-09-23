from pathlib import Path
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

# pandas 由平台内置提供（变量名 pd），无需 import

# 强制 stdout 实时刷新，避免管道全缓冲导致平台误判「无输出超时」
_print = print


def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _print(*args, **kwargs)


STANDARD_COLUMNS = [
    "rule_code", "rule_name", "category", "applicable_fields",
    "format_regex", "check_logic", "severity", "description",
    "source_document", "updated_at",
]


# ==================== 数据源查找（动态） ====================

def _get_datasource_id(name: str) -> str:
    print(f"正在查找数据源: {name}")
    ds = call_tool("list_user_datasources", by_name=name)
    if not ds or not isinstance(ds, dict) or not ds.get("id"):
        raise ValueError(f"找不到数据源: {name}")
    print(f"数据源已找到: {name} (id={ds['id']})")
    return ds["id"]


def _is_graph_datasource(name: str) -> bool:
    try:
        ds = call_tool("list_user_datasources", by_name=name)
        if isinstance(ds, dict):
            t = str(ds.get("type") or "").lower()
            return any(k in t for k in ("graph", "neo4j", "nebula", "arangodb", "tigergraph"))
    except Exception:
        pass
    return False


def _is_chroma_datasource(name: str) -> bool:
    try:
        ds = call_tool("list_user_datasources", by_name=name)
        if isinstance(ds, dict):
            t = str(ds.get("type") or "").lower()
            return "chroma" in t or "vector" in t or "vectordb" in t
    except Exception:
        pass
    return False


# ==================== 文件文本提取 ====================

def _load_pdf_text_cached(path: str) -> str:
    p = Path(path)
    try:
        size = p.stat().st_size
    except Exception:
        size = 0
    cache_name = f"{p.stem}.{size}.pdfcache.txt"
    # 优先读带 size 的精确缓存；旧的无 size 缓存可能来自不同版本的文件，仅作兜底
    cache_candidates = [p.with_name(cache_name), p.with_name(f"{p.stem}.pdfcache.txt")]
    for cand in cache_candidates:
        try:
            res = call_tool("read_file", path=str(cand))
            if isinstance(res, dict) and not res.get("error") and res.get("content"):
                cached = str(res["content"])
                if len(cached.strip()) > 200:
                    print(f"  [缓存命中] PDF 文本: {cand.name}")
                    return cached
        except Exception:
            pass
    print("  [提示] 首次解析 PDF，请耐心等待…")
    text = _extract_text_from_pdf(path)
    # 写入带 size 的缓存名（与读取优先级一致），避免后续版本混淆
    cache_path = p.with_name(cache_name)
    try:
        w = call_tool("write_file", path=str(cache_path), data=text, format="text")
        if isinstance(w, dict) and w.get("success"):
            print(f"  [缓存] 已缓存: {cache_path.name}")
    except Exception as e:
        print(f"  [缓存] 写缓存失败(不影响): {e}")
    return text


def _strip_toc_pages(text: str) -> str:
    """过滤 PDF 目录页（目次页）文本。
    
    目录页特征：大量行由「标题文字 + 点引导线 + 页码」组成，
    或连续多行以页码结尾且无实质正文内容。
    通用判据（不依赖具体文档）：
    1. 连续 5+ 行匹配「……数字」模式（点引导线+页码）→ 整段目录删除
    2. 或连续 5+ 行以纯数字结尾且行长短不一（目录索引特征）
    """
    lines = text.split("\n")
    # 标记目录行：匹配「文字……数字」或「文字    数字」模式
    toc_line_re = re.compile(r"[．.·…\s]{2,}\d{1,4}\s*$")
    # 也匹配「标题 数字」结尾（无点线但明显是目录）
    simple_toc_re = re.compile(r"[\u4e00-\u9fff\w]{2,40}\s+\d{1,4}\s*$")
    
    # 找连续目录行段
    i = 0
    result_lines = []
    while i < len(lines):
        # 检查从 i 开始是否有连续 8+ 行匹配目录模式（提高阈值避免误删引用文件列表）
        j = i
        toc_count = 0
        while j < len(lines):
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            if toc_line_re.search(s) or (simple_toc_re.match(s) and len(s) < 50 and not re.search(r"[。；，、]", s)):
                toc_count += 1
                j += 1
            else:
                break
        if toc_count >= 8:
            # 跳过这段目录行
            print(f"  [TOC过滤] 跳过 {toc_count} 行目录页文本（行 {i+1}-{j}）")
            i = j
        else:
            result_lines.append(lines[i])
            i += 1
    return "\n".join(result_lines)


def _extract_text_from_pdf(path: str) -> str:
    print(f"  调用 read_file 解析 PDF: {path}")
    res = call_tool("read_file", path=path)
    if not isinstance(res, dict):
        raise RuntimeError(f"read_file 返回异常: {res!r}")
    if "error" in res:
        raise RuntimeError(f"read_file 失败: {res['error']}")
    text = str(res.get("content") or "")
    if not text.strip():
        raise RuntimeError(f"PDF 文本为空: {path}")
    # 过滤目录页
    text = _strip_toc_pages(text)
    return text


def _extract_text_from_file(path: str) -> str:
    print(f"开始提取文件文本: {path}")
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        text = _load_pdf_text_cached(path)
    elif ext == ".docx":
        try:
            import docx
            doc = docx.Document(path)
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            text = "\n".join(parts)
        except ImportError:
            res = call_tool("read_file", path=path)
            text = str(res.get("content") or "") if isinstance(res, dict) else ""
    else:
        res = call_tool("read_file", path=path)
        text = str(res.get("content") or "") if isinstance(res, dict) else ""
    if not text.strip():
        raise RuntimeError(f"文件内容为空: {path}")
    print(f"文本提取完成，长度 {len(text)} 字符")
    return text


# ==================== 文本切分 ====================

def _split_text(text: str, max_chunk: int = 6000, overlap: int = 1500) -> List[str]:
    if len(text) <= max_chunk:
        return [text]
    if overlap >= max_chunk:
        overlap = max_chunk // 3
    chunks, start = [], 0
    while start < len(text):
        end = start + max_chunk
        if end >= len(text):
            chunks.append(text[start:])
            break
        split_pos = text.rfind("\n", start, end)
        if split_pos == -1 or split_pos < start + max_chunk // 2:
            split_pos = text.rfind("。", start, end)
        if split_pos == -1 or split_pos < start + max_chunk // 2:
            split_pos = end
        chunks.append(text[start:split_pos + 1])
        start = max(start + 1, split_pos + 1 - overlap)
    return chunks


_TABLE_TITLE_PATTERN = re.compile(
    r"^表\s*([A-Za-zÀ-ÿ]?\s*\.?\s*\d+(?:[.．]\d+)?)\s*(?:[（(]\s*续\s*[)）])?\s*[:：]?\s*(.*)$"
)


def _normalize_table_number(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch in "._")).strip()


def _parse_table_title(line: str):
    s = line.strip()
    if len(s) > 80:
        return False, "", "", False
    m = _TABLE_TITLE_PATTERN.match(s)
    if m and s.startswith("表"):
        return True, _normalize_table_number(m.group(1).strip()), m.group(2).strip(), "续" in s
    return False, "", "", False


def _looks_like_table_name(s: str) -> bool:
    s = (s or "").strip()
    if not s or len(s) < 4 or len(s) > 60:
        return False
    if re.match(r"^[0-9IVXivx．.、]", s) or "|" in s:
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", s))


def _split_by_tables(text: str) -> List[Dict[str, str]]:
    lines = text.split("\n")
    blocks, cur_title, cur_number, cur_lines = [], "正文", "", []
    def _flush():
        content = "\n".join(cur_lines).strip()
        if content:
            blocks.append({"title": cur_title, "number": cur_number, "content": content})
    for i, line in enumerate(lines):
        is_title, number, desc, is_cont = _parse_table_title(line)
        if is_title:
            if is_cont:
                cur_lines.append(line)
                continue
            _flush()
            merged_title = desc or f"表{number}"
            if not desc and i + 1 < len(lines) and _looks_like_table_name(lines[i + 1]):
                merged_title = lines[i + 1].strip()
            cur_title, cur_number, cur_lines = merged_title, number, [line]
        else:
            cur_lines.append(line)
    _flush()
    if not blocks:
        for chunk in _split_text(text, 6000, 1500):
            blocks.append({"title": "正文", "number": "", "content": chunk})
    return blocks


def _merge_blocks_by_number(blocks: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged, by_number = [], {}
    for b in blocks:
        number = (b.get("number") or "").strip()
        if not number:
            merged.append(b)
            continue
        if number in by_number:
            idx = by_number[number]
            merged[idx]["content"] += "\n" + b.get("content", "")
            old_title, new_title = merged[idx].get("title") or "", b.get("title") or ""
            if len(new_title) > len(old_title) and new_title != f"表{number}":
                merged[idx]["title"] = new_title
        else:
            by_number[number] = len(merged)
            merged.append(dict(b))
    return merged


# ==================== LLM JSON 解析 ====================

def _parse_llm_json(text: str) -> List[Dict[str, Any]]:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    json_str = m.group(1) if m else text
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                repaired = _repair_truncated_json_array(text)
                if repaired:
                    return repaired
                raise
        else:
            repaired = _repair_truncated_json_array(text)
            if repaired:
                return repaired
            raise
    return data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])


def _repair_truncated_json_array(text: str) -> List[Dict[str, Any]]:
    start = text.find("[")
    if start == -1:
        return []
    decoder = json.JSONDecoder()
    idx = start + 1
    while idx < len(text) and text[idx] in " \t\r\n":
        idx += 1
    objs = []
    while idx < len(text) and text[idx] != "]":
        try:
            obj, end = decoder.raw_decode(text, idx)
            objs.append(obj)
            idx = end
            while idx < len(text) and text[idx] in " \t\r\n":
                idx += 1
            if idx < len(text) and text[idx] == ",":
                idx += 1
            else:
                break
        except json.JSONDecodeError:
            break
    return [o for o in objs if isinstance(o, dict)]


# ==================== 文档结构分析 ====================

def _extract_outline(text: str, max_len: int = 8000) -> str:
    heading_re = re.compile(r"^\s*(\d+(?:\.\d+){0,3})\s*[、.．\s]+\s*(\S.*)$")
    parts = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = heading_re.match(s)
        if not m or len(s) >= 80:
            continue
        following = []
        for j in range(i + 1, min(i + 8, len(lines))):
            t = lines[j].strip()
            if t:
                following.append(t)
            if len(following) >= 4:
                break
        parts.append(f"{m.group(1)} {m.group(2)}：{' '.join(following)[:180]}")
    outline = "\n".join(parts)
    return outline[:max_len] if len(outline) > max_len else outline


def _analyze_document_structure(text: str) -> Dict[str, Any]:
    outline = _extract_outline(text)
    try:
        titles = [b["title"] for b in _split_by_tables(text) if b["title"] != "正文"]
        if titles:
            outline = (outline + "\n\n【检测到的表格标题】\n" + "\n".join(titles)).strip()
    except Exception:
        pass
    if not outline.strip():
        return {"main_table": "正文规则", "tables": []}
    prompt = f"""你是规则文档结构化专家。请通读下面这份规则文档的章节大纲，为规则知识库设计合适的表结构。

要求：
1. 正文内容提取为一张主表；文档中的各个表格可以单独提取成一张表。
2. 每个子表对应一类规则或一个表格，表名根据内容语义自动生成。
3. 综述、范围、术语、引用文件等归入主表。
4. 同一个表格跨越多页时必须识别为同一张表。

只输出一个 JSON 对象（不要代码围栏、不要解释）：
{{"main_table": "主表名", "tables": [{{"name": "子表名", "description": "用途", "keywords": ["关键词"], "table_names": ["表格标题"]}}]}}

文档大纲：
---
{outline}
---"""
    for attempt, cfg in enumerate([{"temperature": 0.0, "max_tokens": 2000}, {"temperature": 0.2, "max_tokens": 4000}], 1):
        try:
            response = call_tool("llm_generate", prompt=prompt, **cfg)
            if not isinstance(response, dict) or "error" in response:
                raise RuntimeError(f"llm_generate 失败: {response!r}")
            content = str(response.get("content") or "").strip()
            if not content:
                raise RuntimeError("空 content")
            parsed = _parse_llm_json(content)
            if parsed and isinstance(parsed[0], dict) and "tables" in parsed[0]:
                data = parsed[0]
                print(f"  [结构分析] 主表「{data.get('main_table', '正文规则')}」+ {len(data.get('tables') or [])} 张子表")
                return data
        except Exception as e:
            print(f"  [结构分析] 第 {attempt} 次失败: {e}")
    return {"main_table": "正文规则", "tables": []}


# ==================== LLM 规则提取 ====================

def _extract_rules_from_text(text: str, max_workers: int = 3, schema_plan: Optional[Dict] = None) -> List[Dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    probe = call_tool("llm_generate", prompt="只回复两个字：正常", temperature=0.0, max_tokens=50)
    if not (isinstance(probe, dict) and str(probe.get("content") or "").strip()):
        raise RuntimeError("LLM 不可用：探测返回空 content")
    print("  [探测] llm_generate 正常")

    chunks = _split_by_tables(text)
    total = len(chunks)
    print(f"  [LLM提取] 切分为 {total} 块，并发 {max_workers} 路提取...")

    def _build_prompt(block: Dict[str, str]) -> str:
        title = block.get("title") or "正文"
        chunk = block.get("content") or ""
        main_table = (schema_plan or {}).get("main_table") or "正文规则"
        schema_block = ""
        if schema_plan:
            rows = [f"- 主表「{main_table}」：综述、范围、术语等"]
            for t in (schema_plan.get("tables") or []):
                row = f"- 子表「{t.get('name')}」：{t.get('description')}"
                kw = "、".join(t.get("keywords") or [])
                if kw:
                    row += f"（关键词：{kw}）"
                rows.append(row)
            schema_block = "【知识库表结构】\n" + "\n".join(rows) + "\n\n"
        return f"""请从以下规则文档片段中提取结构化规则，直接输出结果。

【当前片段所属表格】
{title}

对每条规则输出一个 JSON 对象：
- rule_code: 规则编号。正文条款优先用其章节号（如「4.1」「4.2」「5」「6」「7」，不编流水号）；表格行用其序号列；文档没有编号才留空
- rule_name: 规则名称
- category: 标准或质量或安全
- applicable_fields: 适用字段（逗号分隔）
- format_regex: 格式正则（无则留空）
- check_logic: 检查逻辑（逐条独立成行，不得合并去重）
- severity: info/warn/error/critical
- description: 规则详细解释
- table: 归属表名（从下方结构中选择；无法判断填「{main_table}」）

{schema_block}【表格复原要求】
1. 转置表格还原为每行一个规则，字段名作为 applicable_fields
2. 同一语义被分页拆散的行必须按语义合并
3. 有序号的表格相同序号合并为一行
4. 表头与单元格内容逐字保留，数值阈值不得改写
5. 续表行并入同一张表

要求：
- 正文每个章节条款（X 标题 / X.Y 标题）必须至少提取为一条规则，不得因篇幅跳过
- 规范性引用文件列表中的每个引用标准都应提取为一条规则
- 章节条款的 rule_code 必须填该条款自身的章节号，保持全文编码体系统一（不得混用 RULE_流水号）
- 正文只提取实质规则，忽略目录、前言
- 如果片段内容是目录/目次页（标题+页码格式），直接输出空数组 []
- 当一个条款包含多个并列子类别，必须为每个子类别单独提取一条规则，不得将多个子类别压缩为单条
- 每段最多 50 条
- 关键数值逐字保留
- 禁止输出推理过程、思考草稿、ID编号等非规则内容

只输出 JSON 数组（[ 开头 ] 结尾），不要代码围栏。

文档片段：
---
{chunk}
---"""

    def _call_once(block, cfg):
        try:
            response = call_tool("llm_generate", prompt=_build_prompt(block), **cfg)
            if not isinstance(response, dict) or "error" in response:
                return "fail", None
            content = str(response.get("content") or "").strip()
            if not content:
                return "fail", None
            parsed = _parse_llm_json(content)
            return ("ok", parsed) if parsed else ("fail", None)
        except Exception as e:
            if "timeout" in str(e).lower():
                return "timeout", None
            return "fail", None

    RETRY_CONFIGS = [{"temperature": 0.0, "max_tokens": 8192}, {"temperature": 0.1, "max_tokens": 8192}, {"temperature": 0.2, "max_tokens": 12000}]

    def _process(idx, block):
        title = block.get("title") or "正文"
        content = block["content"]
        for attempt, cfg in enumerate(RETRY_CONFIGS, 1):
            status, parsed = _call_once(block, cfg)
            if status == "ok":
                return idx, parsed
            if status == "timeout":
                break
        sub_chunks = _split_text(content, 2400, 0)
        all_parsed = []
        for s_idx, sub in enumerate(sub_chunks, 1):
            sub_block = {"title": title, "content": sub}
            for cfg in RETRY_CONFIGS:
                status, parsed = _call_once(sub_block, cfg)
                if status == "ok":
                    all_parsed.extend(parsed)
                    break
                if status == "timeout":
                    break
        if not all_parsed:
            raise RuntimeError(f"第 {idx} 段（{title}）提取失败")
        print(f"    [细切] 第 {idx} 段（{title}）细切成功 {len(all_parsed)} 条")
        return idx, all_parsed

    results, errors = {}, []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process, idx, chunk): idx for idx, chunk in enumerate(chunks, 1)}
        done = 0
        for fut in as_completed(futures):
            idx = futures[fut]
            done += 1
            try:
                _, parsed = fut.result()
                results[idx] = parsed
                print(f"    [进度 {done}/{total}] 第 {idx} 段 {len(parsed)} 条")
            except Exception as e:
                errors.append((idx, str(e)))
                print(f"    [错误] 第 {idx}/{total} 段: {e}")
    if errors and not results:
        raise RuntimeError(f"LLM 提取全部失败: {errors}")
    if errors:
        print(f"  [警告] {len(errors)} 段失败（已跳过）")

    all_entries = []
    for idx in sorted(results):
        all_entries.extend(results[idx])
    return _merge_same_code_entries(all_entries)


def _sanitize_rule_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """清洗 LLM 规则提取结果中的字段错位垃圾条目。

    错位行的典型特征（通用，不依赖业务词）：rule_name 字段被严重度词占据
    （info/warn/error/critical），而 rule_code 填入了正文续句——这是 LLM 把
    上一条规则的 description/severity/元数据整体右移一列形成的垃圾行。

    处理策略：把错位行中保存的完整正文（category 列）合并回上一条主行的
    description，回填 severity，然后丢弃该错位行；正文续行同理合并。
    """
    sev_set = {"info", "warn", "warning", "error", "critical"}
    clean = []
    dropped = 0
    for e in entries:
        code = str(e.get("rule_code") or "").strip()
        name = str(e.get("rule_name") or "").strip()
        name_lower = name.lower()
        if name_lower in sev_set:
            # 字段错位行：rule_name 被严重度词占据
            cat = str(e.get("category") or "").strip()
            if clean:
                main = clean[-1]
                # 回填 severity
                sev = "warn" if name_lower == "warning" else name_lower
                if not str(main.get("severity") or "").strip():
                    main["severity"] = sev
                # category 列保存的是完整正文 → 合并回 description
                if cat:
                    desc = str(main.get("description") or "").strip()
                    if cat not in desc:
                        main["description"] = (desc + "\n" + cat).strip() if desc else cat
            dropped += 1
            continue
        clean.append(e)
    if dropped:
        print(f"  [清洗] 丢弃 {dropped} 条字段错位/续行条目（{len(entries)}→{len(clean)}）")
    return clean


def _merge_rule_group(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    base = dict(group[0])
    names = [str(e.get("rule_name") or "").strip() for e in group if str(e.get("rule_name") or "").strip()]
    if names:
        base["rule_name"] = max(set(names), key=len)
    for field in ("check_logic", "description"):
        vals = [str(e.get(field) or "").strip() for e in group if str(e.get(field) or "").strip()]
        if vals and len(set(vals)) == 1:
            base[field] = vals[0]
        elif vals:
            base[field] = "\n".join(dict.fromkeys(vals))
    fields = [str(e.get("applicable_fields") or "").strip() for e in group if str(e.get("applicable_fields") or "").strip()]
    if fields and len(set(fields)) == 1:
        base["applicable_fields"] = fields[0]
    else:
        parts = []
        for val in fields:
            for p in re.split(r"[,，、;；]+", val):
                if p.strip() and p.strip() not in parts:
                    parts.append(p.strip())
        base["applicable_fields"] = ",".join(parts)
    sev_order = {"info": 0, "warn": 1, "error": 2, "critical": 3}
    base_sev = str(base.get("severity") or "warn").strip()
    for e in group[1:]:
        s = str(e.get("severity") or "").strip()
        if sev_order.get(s, 1) > sev_order.get(base_sev, 1):
            base_sev = s
    base["severity"] = base_sev
    return base


def _merge_same_code_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged, used = [], set()
    for i, e in enumerate(entries):
        if i in used:
            continue
        code_i = str(e.get("rule_code") or "").strip()
        table_i = str(e.get("table") or "").strip()
        if not code_i:
            merged.append(e)
            continue
        group = [e]
        for j in range(i + 1, len(entries)):
            if j in used:
                continue
            if str(entries[j].get("rule_code") or "").strip() != code_i:
                continue
            table_j = str(entries[j].get("table") or "").strip()
            if table_i and table_j and table_i != table_j:
                continue
            group.append(entries[j])
            used.add(j)
        merged.append(_merge_rule_group(group) if len(group) > 1 else e)
    return merged


# ==================== 降级提取（无 LLM 时） ====================

def _chapter_based_extract(text: str) -> List[Dict[str, Any]]:
    heading_re = re.compile(r"^\s*(\d+(?:\.\d+){0,3})\s*[、.．\s]\s*(\S.*)$")
    entries, current_title, current_lines = [], None, []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        m = heading_re.match(s)
        if m and len(s) < 80:
            if current_title:
                content = "\n".join(current_lines).strip()
                if len(content) >= 15:
                    entries.append({"rule_code": m.group(1), "rule_name": current_title, "category": "标准", "applicable_fields": "", "format_regex": "", "check_logic": content[:500], "severity": "warn", "description": content})
            current_title = f"{m.group(1)} {m.group(2)}".strip()
            current_lines = []
        elif current_title:
            current_lines.append(s)
    if current_title:
        content = "\n".join(current_lines).strip()
        if len(content) >= 15:
            entries.append({"rule_code": "", "rule_name": current_title, "category": "标准", "applicable_fields": "", "format_regex": "", "check_logic": content[:500], "severity": "warn", "description": content})
    return entries


# ==================== 表格处理工具 ====================

def _sanitize_table_name(name: str) -> str:
    if not name:
        return "未命名表"
    return re.sub(r'[/\\|:*?"<>]+', "_", name).strip().strip("._")


def _table_block_has_data(block: Dict[str, str]) -> bool:
    content = block.get("content") or ""
    data_lines = []
    chapter_heading_count = 0
    total_lines = 0
    for line in content.split("\n"):
        s = line.strip()
        if not s or _parse_table_title(s)[0] or s in ("(续)", "（续）") or len(s) < 3:
            continue
        total_lines += 1
        # 排除章节标题行（如「6 检修内容」）
        if _CHAPTER_HEADING_RE.match(s) and len(s) < 80:
            chapter_heading_count += 1
            continue
        # 真实表格数据行特征：制表符 / 竖线 / 多列空格对齐 / 短序号开头
        if "\t" in s or "|" in s:
            data_lines.append(s)
        elif re.search(r"\s{2,}", s) and len(s) < 80:
            data_lines.append(s)
        elif re.match(r"^\d{1,3}[.、．\s]", s) and len(s) < 60:
            data_lines.append(s)
    # 如果大部分行是章节标题（目录/正文），判定为无表格数据
    if total_lines > 0 and chapter_heading_count >= total_lines * 0.5:
        return False
    return len(data_lines) >= 2


_CHAPTER_HEADING_RE = re.compile(r"^\d{1,3}(?:\.\d+){0,3}\s+\S")


def _block_is_body_not_table(block: Dict[str, str]) -> bool:
    """判断一个「表X」块是否实为正文（表标题后无真实表格数据，紧跟章节正文）。

    通用判据（不依赖具体文档/业务词）：
    1. 块内存在章节标题行（如「6 检修内容」「7 检修类别」，形如 X 标题 / X.Y 标题）；
    2. 且不存在真实表格数据行（制表符分隔、多空格对齐、或短序号开头）。
    满足两者 → 该表标题后实为正文，应归入正文而非表格。
    """
    content = block.get("content") or ""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    chapter_headings = 0
    table_data_lines = 0
    for ln in lines:
        if _parse_table_title(ln)[0] or ln in ("(续)", "（续）"):
            continue
        if _CHAPTER_HEADING_RE.match(ln) and len(ln) < 80:
            chapter_headings += 1
            continue
        # 真实表格数据行特征：制表符 / 2+连续空格对齐 / 短序号开头
        if "\t" in ln:
            table_data_lines += 1
        elif re.search(r"\s{2,}", ln) and len(ln) < 80:
            table_data_lines += 1
        elif re.match(r"^\d{1,3}\s", ln) and len(ln) < 60:
            table_data_lines += 1
    return chapter_headings >= 1 and table_data_lines <= 3


def _split_body_from_table_block(block: Dict[str, str]):
    """把一个「表标题 + 正文」混合块拆成 (表标题块, 正文文本)。

    返回 (table_block_or_None, body_text)。
    表标题块只保留表标题行，用于后续 OCR 补全真实表格数据；
    其余行（章节正文）作为 body_text 归入正文提取。
    """
    content = block.get("content") or ""
    table_lines, body_lines = [], []
    for ln in content.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if not table_lines and _parse_table_title(s)[0]:
            table_lines.append(s)
            continue
        body_lines.append(ln)
    table_block = None
    if table_lines:
        table_block = {"title": block.get("title"), "number": block.get("number"), "content": "\n".join(table_lines)}
    return table_block, "\n".join(body_lines).strip()


def _parse_markdown_table(text: str) -> List[Dict[str, Any]]:
    text = re.sub(r"<[^>]+>", "", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tbl_lines = [ln for ln in lines if "|" in ln]
    if len(tbl_lines) < 2:
        return []
    def _cells(ln):
        s = ln.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]
    all_cells = [_cells(ln) for ln in tbl_lines]
    sep_idx = next((i for i, cells in enumerate(all_cells) if all(re.fullmatch(r"[-=: ]+", c) for c in cells if c)), None)
    header_lines = all_cells[:sep_idx] if sep_idx is not None else all_cells[:1]
    row_start = sep_idx + 1 if sep_idx is not None else 1
    # Use header line column count as canonical ncols (not max of all rows)
    # to avoid creating extra columns from right-shifted/misaligned rows
    header_ncols = max((len(cl) for cl in header_lines), default=0)
    if header_ncols == 0:
        return []
    ncols = header_ncols

    # Detect data rows consumed as header lines (between first header and separator)
    # e.g. LLM returns: | header | ... | / | 1 | data | ... | / | --- | ... | / | 2 | data |
    # The seq=1 row gets consumed as a sub-header line
    data_rows_from_header = []
    if len(header_lines) > 1:
        real_header_lines = [header_lines[0]]
        for hl in header_lines[1:]:
            first_cell = str(hl[0]).strip() if hl else ""
            if re.match(r"^\d{1,4}", first_cell):
                data_rows_from_header.append(hl)
            else:
                real_header_lines.append(hl)
        header_lines = real_header_lines
        if data_rows_from_header:
            print(f"  [解析] 从表头区域恢复 {len(data_rows_from_header)} 行数据（疑似被表头探测吞掉）")

    headers = []
    for ci in range(ncols):
        parts = [(cl[ci] if ci < len(cl) else "").strip() for cl in header_lines]
        parts = [p for p in parts if p]
        headers.append("｜".join(parts) if parts else "")
    if not headers or all(h == "" for h in headers):
        return []
    rows = []
    # Add recovered data rows first
    for cells in data_rows_from_header:
        if not cells or all(c == "" for c in cells):
            continue
        while len(cells) < ncols:
            cells.append("")
        if len(cells) > ncols:
            while len(cells) > ncols and not str(cells[0]).strip():
                cells = cells[1:]
                while len(cells) < ncols:
                    cells.append("")
            if len(cells) > ncols:
                overflow = [str(c).strip() for c in cells[ncols:] if str(c).strip()]
                if overflow:
                    cells[ncols - 1] = (str(cells[ncols - 1]).strip() + "；" + "；".join(overflow)) if str(cells[ncols - 1]).strip() else "；".join(overflow)
                cells = cells[:ncols]
        rows.append(cells[:ncols])
    for cells in all_cells[row_start:]:
        if not cells or all(c == "" for c in cells):
            continue
        while len(cells) < ncols:
            cells.append("")
        if len(cells) > ncols:
            # Right-shift detection: leading empty cells → left-shift
            while len(cells) > ncols and not str(cells[0]).strip():
                cells = cells[1:]
                while len(cells) < ncols:
                    cells.append("")
            if len(cells) > ncols:
                overflow = [str(c).strip() for c in cells[ncols:] if str(c).strip()]
                if overflow:
                    cells[ncols - 1] = (str(cells[ncols - 1]).strip() + "；" + "；".join(overflow)) if str(cells[ncols - 1]).strip() else "；".join(overflow)
                cells = cells[:ncols]
        rows.append(cells[:ncols])
    return [{"headers": headers, "rows": rows}] if rows else []


# ==================== OCR 通道（仅在文本层无数据时使用） ====================

def _scan_pages_for_tables(pdf_path: str, table_numbers: List[str], start_page: int = 1) -> Dict[str, str]:
    """只在文本层无数据时才走 OCR。"""
    from pathlib import Path as _Path
    text_res = call_tool("read_file", path=pdf_path)
    if not isinstance(text_res, dict) or "content" not in text_res:
        raise RuntimeError(f"read_file 获取 PDF 失败: {text_res!r}")
    total_pages = text_res.get("total_pages") or 0
    if not total_pages:
        probe = call_tool("read_file", path=pdf_path, pdf_page_images=[1], dpi=72)
        total_pages = probe.get("total_pages") if isinstance(probe, dict) else 0
    max_pages = min(total_pages or 20, 30)
    print(f"  [OCR] 扫描 {max_pages} 页（总 {total_pages} 页）")

    ocr_prompt = """你是表格 OCR 专家。请把页面上所有表格识别输出，格式：
表X.Y 表格名称
| 列1 | 列2 |
| --- | --- |
| 数据行 |

要求：
1. 每个表格前一行标题（表号 + 名称）
2. 表头列数与数据行一致
3. 数值阈值逐字保留
4. 忽略水印/页眉/页脚
5. 垂直合并单元格的值每行重复输出，尤其是表格第一列的分组列，绝不允许留空导致后续各列整体左移
6. 同序号多档内容用分号合并到同一行
7. 直接输出 Markdown，不要代码围栏
8. 单元格内容必须完整输出，禁止截断
9. 不要使用子序号，同一项目的多个档位保持相同序号
10. 每一列的语义必须与其表头一致，严禁列与列之间串行或错位
11. 同一项目含多个子列时，各列必须按子列顺序一一对应，数量必须相等，不得丢失或错位
12. 合并单元格的父级分组值必须按区段正确回填到分组列，不得把其他列内容填进分组列
13. 行×列交叉的矩阵表保持原结构输出，严禁把行表头/列名混填或整列左移"""

    md_by_number: Dict[str, List[str]] = {num: [] for num in table_numbers}
    batch_size = 5
    for batch_start in range(start_page, max_pages + 1, batch_size):
        batch_pages = list(range(batch_start, min(batch_start + batch_size, max_pages + 1)))
        print(f"  [OCR] 渲染第 {batch_pages[0]}-{batch_pages[-1]} 页…")
        img_res = call_tool("read_file", path=pdf_path, pdf_page_images=batch_pages, dpi=200)
        if not isinstance(img_res, dict) or not img_res.get("success"):
            continue
        image_paths = img_res.get("image_paths") or []
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _ocr_one(pg, img_p):
            for _ in range(3):
                try:
                    vres = call_tool("llm_vision", image_path=img_p, prompt=ocr_prompt)
                    if isinstance(vres, dict) and "error" not in vres:
                        raw = str(vres.get("result") or "").strip()
                        if raw:
                            return pg, raw
                except Exception:
                    pass
            return pg, ""

        page_imgs = {}
        for i, img_path in enumerate(image_paths):
            page_no = batch_pages[i] if i < len(batch_pages) else 0
            src = _Path(str(img_path))
            dst = _Path(pdf_path).parent / f"_dc_ocr_p{page_no}_{src.name}"
            try:
                dst.write_bytes(src.read_bytes())
            except Exception:
                dst = src
            page_imgs[page_no] = str(dst)

        with ThreadPoolExecutor(max_workers=min(5, len(page_imgs))) as ex:
            futs = {ex.submit(_ocr_one, pg, img_p): pg for pg, img_p in page_imgs.items()}
            for fut in as_completed(futs):
                pg, raw = fut.result()
                if raw:
                    for num in table_numbers:
                        target = _filter_md_by_table_number(raw, num)
                        if target:
                            md_by_number[num].append(f"== 第 {pg} 页 ==\n{target}")
                print(f"  [OCR] 第 {pg} 页完成")

    return {num: "\n\n".join(parts) for num, parts in md_by_number.items() if parts}


def _filter_md_by_table_number(md_text: str, table_number: str) -> str:
    """从 OCR 结果中提取目标表格的 Markdown 内容。

    三级匹配：
    1. 精确匹配：表标题行归一化后 == 目标表号
    2. 包含匹配：非 | 行归一化后包含目标表号
    3. 兜底：只有 | 行没有标题行时返回全部（OCR 漏识别标题）
    """
    if not md_text or not table_number:
        return ""
    lines = md_text.split("\n")
    target_norm = _normalize_table_number(table_number)
    if not target_norm:
        return ""

    # 找所有非 | 行（可能的表标题行）
    non_pipe_lines = [(i, ln.strip()) for i, ln in enumerate(lines) if ln.strip() and not ln.strip().startswith("|")]

    # 1. 精确匹配：用 _parse_table_title 解析
    title_indices = []
    for i, s in non_pipe_lines:
        is_title, number, _, _ = _parse_table_title(s)
        if is_title and _normalize_table_number(number) == target_norm:
            title_indices.append(i)

    if title_indices:
        # 收集每个标题到下一个非 | 行之间的所有行
        segments = []
        for idx_pos, start in enumerate(title_indices):
            # end = 下一个非 | 行的位置，或 lines 末尾
            if idx_pos + 1 < len(title_indices):
                end = title_indices[idx_pos + 1]
            else:
                # 找 start 之后第一个非 | 行作为结束
                end = len(lines)
                for j in range(start + 1, len(lines)):
                    js = lines[j].strip()
                    if js and not js.startswith("|"):
                        # 找到下一个标题行（非 | 行），但如果是同一表号的续表行则不截断
                        is_t, n, _, _ = _parse_table_title(js)
                        if is_t:
                            end = j
                            break
            segments.extend(lines[start:end])
        return "\n".join(segments) if segments else ""

    # 2. 包含匹配：归一化后的行文本包含目标表号
    pat = re.compile(r"表\s*" + re.escape(target_norm) + r"(?![0-9A-Za-z.．])")
    for i, s in non_pipe_lines:
        if pat.search(s):
            # 从这行开始收集后续 | 行
            segments = [lines[i]]
            for j in range(i + 1, len(lines)):
                js = lines[j].strip()
                if js.startswith("|"):
                    segments.append(lines[j])
                elif js and not js.startswith("|"):
                    break
            return "\n".join(segments)

    # 3. 兜底：没有标题行但有 | 行 → 返回全部
    pipe_lines = [ln for ln in lines if ln.strip().startswith("|")]
    if len(pipe_lines) >= 2 and not non_pipe_lines:
        return md_text

    return ""


def _detect_truncated_cells(rows: List[List[str]], md_text: str) -> bool:
    """检测 LLM 返回的表格中是否有疑似被截断的单元格。

    只检测明确的截断标记：
    - 单元格以省略号结尾（…、...）
    - 单元格内容含"(原文截断"等标记

    不检测"单个汉字结尾"——数值、状态词等正常内容也可能无标点收尾，
    误判会导致无限重试浪费时间。
    """
    truncation_patterns = [
        re.compile(r'\.{2,}$'),
        re.compile(r'…$'),
        re.compile(r'\(原文截断'),
        re.compile(r'（原文截断'),
    ]
    for row in rows:
        for cell in row:
            val = str(cell).strip() if cell else ""
            if not val or len(val) < 5:
                continue
            for pat in truncation_patterns:
                if pat.search(val):
                    return True
    return False


def _merge_md_once(title: str, number: str, md_text: str) -> Dict[str, Any]:
    base_prompt = f"""你是表格归并专家。下面是表格（表{number} {title}）的 Markdown 分段。请归并为一张最终表格，只输出 Markdown 表格（| 分隔），不要 JSON、不要代码围栏。

要求：
1. 每个序号只保留一行，多档内容用分号并列。合并单元格的子行不要分配新序号，保持原序号
2. 跨页续表：去掉重复表头，数据行续接
3. 合并单元格：父项列连续为空时用上方最近非空值回填
4. 按序号升序，每行必须有实质内容
5. 去掉页眉页脚水印碎片
6. 数值阈值逐字保留，清除 HTML 标签
7. 各列不得互换混填
8. 所有数据行的列数必须与表头列数完全一致，不得多出或少列
9. 保留所有序号的数据行，不得遗漏首行和末行。序号必须连续，不得跳号
10. 如果某行单元格内容比表头多，将多余内容合并到该行最后一列（用分号分隔），不得新增列
11. 单元格内容必须完整输出，禁止截断，不得在中间省略
12. 不要使用子序号，同一项目的多个档位保持相同序号
13. 多级表头必须展平为单行表头，每个子列都有独立列名，不得留空
14. 矩阵型表格保持原结构输出，不要展平为长表
15. 禁止输出推理过程、思考草稿、ID编号等非表格内容。只输出纯表格数据行
16. 禁止在单元格中写入推测内容，如果原文不完整则照原文输出
17. 分组列必须保留合并单元格的父级分组值，不得把其他列内容填入分组列；分组列与其他列必须语义区分，不得重复
18. 各列只保留与该列表头语义一致的值，不得把其他列的内容混入
19. 同一项目的多个档位必须归并为一行：各档值用分号一一对应（数量必须相等），不得按档拆成多行

输出格式：表头行 + 分隔线 + 数据行，直接输出，禁止代码围栏。

分段原文：
---
{md_text}
---"""
    for attempt in range(3):
        try:
            extra_warning = ""
            if attempt > 0:
                extra_warning = "\n\n【重要警告】上一次输出存在单元格内容被截断的问题！请确保每个单元格内容完整输出，不得省略或截断任何文字。不要输出推理过程或ID编号。"
            response = call_tool("llm_generate", prompt=base_prompt + extra_warning, temperature=0.0, max_tokens=32000)
            if not isinstance(response, dict) or "error" in response:
                raise RuntimeError(str(response))
            raw = str(response.get("content") or "").strip()
            if not raw:
                raise RuntimeError("空 content")
            parsed = _parse_markdown_table(raw)
            if parsed:
                data = parsed[0]
                if data.get("headers") and data.get("rows"):
                    # 检测截断
                    if _detect_truncated_cells(data["rows"], md_text):
                        if attempt < 2:
                            print(f"    [截断检测] 第 {attempt + 1}/3 次输出疑似截断，重试")
                            continue
                        else:
                            print(f"    [截断检测] 3次重试后仍有截断，使用最后一次结果")
                    return {"headers": data["headers"], "rows": data["rows"]}
            raise RuntimeError(f"归并无有效表格: {raw[:200]!r}")
        except Exception as e:
            if attempt < 2:
                print(f"    [归并重试] 第 {attempt + 1}/3: {e}")
            else:
                raise
    return {"headers": [], "rows": []}


def _merge_md_tables(title: str, number: str, md_parts: List[str]) -> Dict[str, Any]:
    all_md = "\n\n".join(p for p in md_parts if p and p.strip())
    if not all_md.strip():
        return {"headers": [], "rows": []}
    # 大表分段归并：如果输入超过 8000 字符，按页标记分段，先逐段归并再合并
    if len(all_md) > 8000:
        return _merge_large_md(title, number, all_md)
    return _merge_md_once(title, number, all_md)


def _merge_large_md(title: str, number: str, all_md: str) -> Dict[str, Any]:
    """大表分段归并：按页标记（== 第 N 页 ==）拆分，逐段归并，再合并结果。"""
    # 按 == 第 N 页 == 拆分
    page_parts = re.split(r"(?=== 第 \d+ 页 ==)", all_md)
    page_parts = [p.strip() for p in page_parts if p.strip()]
    if len(page_parts) <= 1:
        return _merge_md_once(title, number, all_md)
    print(f"  [大表分段] 表{number} 输入 {len(all_md)} 字符，拆分为 {len(page_parts)} 段")

    # 逐段归并
    merged_results = []
    for i, part in enumerate(page_parts):
        if not part.strip():
            continue
        print(f"    [大表分段] 归并第 {i+1}/{len(page_parts)} 段（{len(part)} 字符）...")
        result = _merge_md_once(title, number, part)
        if result.get("headers") and result.get("rows"):
            merged_results.append(result)

    if not merged_results:
        return {"headers": [], "rows": []}
    if len(merged_results) == 1:
        return merged_results[0]

    # 合并多段结果：取第一段表头，后续段去掉表头续接
    final_headers = merged_results[0]["headers"]
    final_rows = list(merged_results[0]["rows"])
    for seg in merged_results[1:]:
        seg_rows = seg.get("rows", [])
        for row in seg_rows:
            # 列数对齐
            while len(row) < len(final_headers):
                row.append("")
            if len(row) > len(final_headers):
                overflow = [str(c).strip() for c in row[len(final_headers):] if str(c).strip()]
                if overflow:
                    row[len(final_headers) - 1] = str(row[len(final_headers) - 1]) + "；" + "；".join(overflow)
                row = row[:len(final_headers)]
            final_rows.append(row[:len(final_headers)])
    print(f"  [大表分段] 合并完成：{len(final_rows)} 行")
    return {"headers": final_headers, "rows": final_rows}


def _extract_table_from_ocr(block: Dict[str, str], ocr_md: str) -> Dict[str, Any]:
    title = block.get("title") or "未命名表"
    number = block.get("number") or ""
    merged = _merge_md_tables(title, number, [ocr_md])
    table_name = _sanitize_table_name(f"表{number} {title}".strip() if number and title and title != f"表{number}" else (f"表{number}" if number else title))
    if merged.get("headers") and merged.get("rows"):
        headers = [str(h).strip() for h in merged["headers"]]
        rows = [[("" if c is None else str(c)) for c in r] for r in merged["rows"]]
        result = {"table_name": table_name, "table_number": number, "headers": headers, "rows": rows}
        return result
    parsed = _parse_markdown_table(ocr_md)
    if parsed:
        data = parsed[0]
        headers = [str(x).strip() for x in (data.get("headers") or [])]
        rows = [[("" if c is None else str(c)) for c in r] for r in (data.get("rows") or [])]
        if headers and rows:
            result = {"table_name": table_name, "table_number": number, "headers": headers, "rows": rows}
            return result
    raise RuntimeError(f"表{number} OCR 归并失败")


def _extract_table_literal(block: Dict[str, str]) -> Dict[str, Any]:
    title = block.get("title") or "未命名表"
    number = block.get("number") or ""
    content = block.get("content") or ""
    merged = _merge_md_tables(title, number, [content])
    table_name = _sanitize_table_name(f"表{number} {title}".strip() if number and title and title != f"表{number}" else (f"表{number}" if number else title))
    if merged.get("headers") and merged.get("rows"):
        headers = [str(h).strip() for h in merged["headers"]]
        rows = [[("" if c is None else str(c)) for c in r] for r in merged["rows"]]
        result = {"table_name": table_name, "table_number": number, "headers": headers, "rows": rows}
        return result
    parsed = _parse_markdown_table(content)
    if parsed:
        data = parsed[0]
        headers = [str(x).strip() for x in (data.get("headers") or [])]
        rows = [[("" if c is None else str(c)) for c in r] for r in (data.get("rows") or [])]
        if headers and rows:
            result = {"table_name": table_name, "table_number": number, "headers": headers, "rows": rows}
            return result
    raise RuntimeError(f"表{number} 文本归并失败")


def _merge_rows_by_seq(ti: Dict[str, Any]) -> Dict[str, Any]:
    """如果表格第一列是序号列，按序号进行确定性语义归并：
    - 相同序号的多行合并为一行
    - 子序号（3.1→3）归并到父序号
    - float 序号归一化（3.0→3）
    - 连续同关键列值的行归并（处理LLM给合并单元格子行分配新序号的情况）
    各列差异内容用分号拼接。
    """
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    if not headers or not rows or len(headers) < 2:
        return ti

    first_header = str(headers[0]).strip()
    # 判断第一列是否为序号列：表头含"序号"/"编号"或大部分首单元格为纯数字
    is_seq_col = "序号" in first_header or "编号" in first_header
    if not is_seq_col:
        num_count = sum(1 for r in rows if r and re.match(r"^\d{1,4}(\.\d+)?$", str(r[0]).strip()))
        if num_count < len(rows) * 0.5:
            return ti
        is_seq_col = True

    # 归一化序号值：float "3.0" → "3"
    def _norm_seq(val):
        s = str(val).strip()
        if re.match(r"^\d+\.0+$", s):
            return str(int(float(s)))
        return s

    # 提取父序号： "3.1" → "3", "3" → "3"
    def _parent_seq(val):
        s = _norm_seq(val)
        m = re.match(r"^(\d+)\.\d+$", s)
        return m.group(1) if m else s

    def _merge_into(existing, row):
        """将 row 的内容合并到 existing 行，差异内容用分号拼接"""
        for ci in range(1, len(headers)):
            new_val = str(row[ci]).strip() if ci < len(row) else ""
            old_val = str(existing[ci]).strip() if ci < len(existing) else ""
            if new_val and new_val != old_val:
                if old_val:
                    # 按分号（中英文）拆段去重后拼接，避免同段重复粘贴
                    parts = [p.strip() for p in re.split(r"[；;]", old_val) if p.strip()]
                    for piece in re.split(r"[；;]", new_val):
                        piece = piece.strip()
                        if piece and piece not in parts:
                            parts.append(piece)
                    existing[ci] = "；".join(parts)
                else:
                    existing[ci] = new_val

    # 步骤1: 按父序号分组归并（处理子序号 3.1→3 和完全相同序号）
    merged_rows = []
    seq_map = {}  # parent_seq -> index in merged_rows
    for row in rows:
        raw_seq = str(row[0]).strip() if row else ""
        parent = _parent_seq(raw_seq)
        if parent not in seq_map:
            new_row = list(row)
            new_row[0] = parent  # 归一化序号
            merged_rows.append(new_row)
            seq_map[parent] = len(merged_rows) - 1
        else:
            idx = seq_map[parent]
            _merge_into(merged_rows[idx], row)

    original_count = len(rows)

    if len(merged_rows) < original_count:
        print(f"  [序号归并] {original_count} 行 → {len(merged_rows)} 行（按序号合并）")

    result = dict(ti)
    result["rows"] = merged_rows
    return result


def _filter_polluted_rows(ti: Dict[str, Any]) -> Dict[str, Any]:
    """过滤 LLM 推理草稿污染行。
    污染行特征：
    - 首列含 markdown 标记（**ID、** 等）
    - 首列匹配 '数字.  **ID' 模式（LLM 推理草稿编号）
    - 任意列含推理文本标记（'这可能'、'(原文混合'、'推测为'、'数据提取错误'、'(原文截断'）
    """
    rows = ti.get("rows") or []
    if not rows:
        return ti
    pollution_patterns = [
        re.compile(r'\*\*ID\b', re.IGNORECASE),
        re.compile(r'^\d+\.\s+\*\*'),
        re.compile(r'这可能'),
        re.compile(r'\(原文混合'),
        re.compile(r'推测为'),
        re.compile(r'数据提取错误'),
        re.compile(r'\(原文截断'),
    ]
    clean_rows = []
    removed = 0
    for row in rows:
        is_polluted = False
        for cell in row:
            cell_str = str(cell) if cell else ""
            for pat in pollution_patterns:
                if pat.search(cell_str):
                    is_polluted = True
                    break
            if is_polluted:
                break
        if is_polluted:
            removed += 1
        else:
            clean_rows.append(row)
    if removed > 0:
        print(f"  [过滤] 移除 {removed} 行 LLM 推理草稿污染行（{len(rows)}→{len(clean_rows)}）")
    result = dict(ti)
    result["rows"] = clean_rows
    return result


def _clean_placeholder_cells(ti: Dict[str, Any]) -> Dict[str, Any]:
    """清理单元格中的 LLM 臆测占位文本。"""
    placeholder_patterns = [
        re.compile(r'\(原文截断[^)]*\)'),
        re.compile(r'\(推测[^)]*\)'),
        re.compile(r'\(原文混合[^)]*\)'),
    ]
    rows = ti.get("rows") or []
    cleaned = 0
    for row in rows:
        for ci in range(len(row)):
            val = str(row[ci]) if row[ci] else ""
            for pat in placeholder_patterns:
                new_val = pat.sub("", val).strip()
                if new_val != val:
                    row[ci] = new_val
                    cleaned += 1
    if cleaned > 0:
        print(f"  [清理] 清理 {cleaned} 个占位文本单元格")
    return ti


def _forward_fill_merged_cells(ti: Dict[str, Any]) -> Dict[str, Any]:
    """对合并单元格列（垂直合并）进行前向填充：列值为空时用上方最近非空值补全。"""
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    if not headers or not rows or len(headers) < 2:
        return ti
    fill_cols = []
    for ci in range(len(headers)):
        col_vals = [str(r[ci]).strip() if ci < len(r) else "" for r in rows]
        non_empty = [v for v in col_vals if v]
        if not col_vals:
            continue
        empty_ratio = 1.0 - len(non_empty) / len(col_vals)
        header = str(headers[ci]).strip()
        if "序号" in header or "编号" in header:
            continue
        if 0.1 <= empty_ratio <= 0.9 and non_empty:
            fill_cols.append(ci)
    if not fill_cols:
        return ti
    filled_count = 0
    for ci in fill_cols:
        for row in rows:
            while len(row) <= ci:
                row.append("")
        # 1) 向下填充：空值用上方最近非空值补全
        last_val = ""
        for ri in range(len(rows)):
            val = str(rows[ri][ci]).strip()
            if val:
                last_val = val
            elif last_val:
                rows[ri][ci] = last_val
                filled_count += 1
        # 2) 向上回填：合并单元格段首整段为空（OCR 漏打印父值），
        #    用该列下方第一个非空值回填开头的连续空段
        first_val = ""
        for ri in range(len(rows)):
            v = str(rows[ri][ci]).strip()
            if v:
                first_val = v
                break
        if first_val:
            for ri in range(len(rows)):
                if str(rows[ri][ci]).strip():
                    break
                rows[ri][ci] = first_val
                filled_count += 1
    if filled_count > 0:
        print(f"  [合并单元格] 前向填充 {filled_count} 个空值（{len(fill_cols)} 列）")
    result = dict(ti)
    result["rows"] = rows
    return result


def _merge_duplicate_headers(ti: Dict[str, Any]) -> Dict[str, Any]:
    """合并重复列名：当多个列名相同时（多级表头展平不彻底），将对应列内容按行拼接。"""
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    if not headers:
        return ti
    col_positions = {}
    for ci, h in enumerate(headers):
        h_clean = str(h).strip()
        if h_clean:
            col_positions.setdefault(h_clean, []).append(ci)
    dup_groups = {h: positions for h, positions in col_positions.items() if len(positions) > 1}
    if not dup_groups:
        return ti
    keep_positions = set()
    remove_positions = set()
    for h, positions in dup_groups.items():
        keep_positions.add(positions[0])
        remove_positions.update(positions[1:])
    for ci in range(len(headers)):
        h_clean = str(headers[ci]).strip()
        if h_clean not in dup_groups:
            keep_positions.add(ci)
    new_headers = [headers[ci] for ci in sorted(keep_positions)]
    new_rows = []
    for row in rows:
        new_row = []
        for ci in sorted(keep_positions):
            h_clean = str(headers[ci]).strip() if ci < len(headers) else ""
            same_col_positions = [ci]
            if h_clean in dup_groups:
                same_col_positions = dup_groups[h_clean]
            vals = []
            for pos in same_col_positions:
                if pos < len(row):
                    v = str(row[pos]).strip()
                    if v:
                        vals.append(v)
            new_row.append("；".join(vals) if vals else (row[ci] if ci < len(row) else ""))
        new_rows.append(new_row)
    print(f"  [子列拼接] 合并 {len(dup_groups)} 组重复列名")
    result = dict(ti)
    result["headers"] = new_headers
    result["rows"] = new_rows
    return result


def _normalize_column_count(ti: Dict[str, Any]) -> Dict[str, Any]:
    """确保每行列数与表头列数一致：缺失列补空，多余列合并到最后一列。"""
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    if not headers:
        return ti
    ncols = len(headers)
    normalized = []
    adjusted = 0
    for row in rows:
        while len(row) < ncols:
            row.append("")
            adjusted += 1
        if len(row) > ncols and ncols > 0:
            overflow = [str(c).strip() for c in row[ncols:] if str(c).strip()]
            if overflow:
                last_val = str(row[ncols - 1]).strip() if row[ncols - 1] else ""
                merged = last_val + "；" + "；".join(overflow) if last_val else "；".join(overflow)
                row[ncols - 1] = merged
                adjusted += 1
            row = row[:ncols]
        normalized.append(row)
    if adjusted > 0:
        print(f"  [列数归一] 调整 {adjusted} 行到 {ncols} 列")
    result = dict(ti)
    result["rows"] = normalized
    return result


def _table_rows_to_records(ti: Dict[str, Any], source_document: str) -> List[Dict[str, Any]]:
    ti = _filter_polluted_rows(ti)
    ti = _clean_placeholder_cells(ti)
    ti = _forward_fill_merged_cells(ti)
    ti = _merge_rows_by_seq(ti)
    ti = _merge_duplicate_headers(ti)
    ti = _normalize_column_count(ti)
    # 表头归一化：去除字间空格（如「劣 化 情 况」→「劣化情况」），统一跨表列名
    ti["headers"] = [re.sub(r"\s+", "", str(h)) for h in (ti.get("headers") or [])]
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 确保序号列保持字符串格式（避免 Excel 自动转为数字/浮点）
    seq_header = ""
    if headers:
        first_header = str(headers[0]).strip()
        if "序号" in first_header or "编号" in first_header:
            seq_header = first_header
    records = []
    for row in rows:
        rec = {}
        for ci, h in enumerate(headers):
            val = "" if ci >= len(row) or row[ci] is None else str(row[ci])
            # 序号列强制保持字符串格式
            if h == seq_header and val:
                val = val.strip()
            rec[str(h)] = val
        rec["source_document"] = source_document
        rec["updated_at"] = now
        records.append(rec)
    return records


def _apply_row_col_fixes(grouped: Dict[str, List[Dict]], issues: List[tuple], source_text: str, table_original_titles: Dict[str, str] = None) -> int:
    """按行/列修复 check_skill_rules 发现的问题（不整表重写）。

    根据 rule_id 和 issue 描述定位问题行列，只修有问题的单元格：
    - SKILL-DQ-001 表名问题：用原始表标题替换
    - SKILL-DQ-002 列错位/列数不一致：对齐列数（补空/合并多余列）
    - SKILL-DQ-003 序号未归并：重新执行序号归并
    - SKILL-DQ-004 合并单元格未补全：重新执行前向填充
    - SKILL-DQ-005 子列未拼接：重新执行重复列名合并
    - 内容截断/OCR漏行等确定性修复不了的问题：调 LLM 按行修复（不整表重写）
    返回修复计数。
    """
    fixed_count = 0
    if table_original_titles is None:
        table_original_titles = {}

    # 按表分组问题
    issues_by_tbl = {}
    for tbl, iss in issues:
        issues_by_tbl.setdefault(tbl, []).append(iss)

    for tbl, tbl_issues in issues_by_tbl.items():
        recs = grouped.get(tbl, [])
        if not recs:
            continue
        headers = list(recs[0].keys())
        rule_ids = {iss.get("rule_id", "") for iss in tbl_issues}

        # SKILL-DQ-001: 表名问题 → 用原始表标题替换
        if "SKILL-DQ-001" in rule_ids:
            original_title = table_original_titles.get(tbl, "")
            if original_title and original_title != tbl:
                # 保留 _records_map 的 key 一致性
                old_key = tbl
                new_key = original_title
                # 避免 key 冲突
                if new_key not in grouped:
                    grouped[new_key] = grouped.pop(old_key)
                    if old_key in table_original_titles:
                        table_original_titles[new_key] = table_original_titles.pop(old_key)
                    print(f"  [修复] 表名「{old_key}」→「{new_key}」（原始表标题）")
                    fixed_count += 1
                else:
                    print(f"  [修复] 表名「{old_key}」原始标题「{new_key}」已存在，跳过")
            else:
                for iss in tbl_issues:
                    if iss.get("rule_id") == "SKILL-DQ-001":
                        print(f"  [修复] 表名「{tbl}」无原始标题可用，描述: {str(iss.get('description',''))[:80]}")

        # SKILL-DQ-002: 列数不一致 → 补空/合并多余列
        if "SKILL-DQ-002" in rule_ids:
            _adjusted = 0
            for rec in recs:
                while len(list(rec.values())) < len(headers):
                    rec[f"col_{len(rec)}"] = ""
                    _adjusted += 1
                if len(list(rec.values())) > len(headers):
                    vals = list(rec.values())
                    overflow = vals[len(headers):]
                    last_key = list(rec.keys())[len(headers) - 1]
                    overflow_str = "；".join(str(v) for v in overflow if str(v).strip())
                    if overflow_str:
                        rec[last_key] = str(rec[last_key]) + "；" + overflow_str if rec[last_key] else overflow_str
                    for k in list(rec.keys())[len(headers):]:
                        del rec[k]
                    _adjusted += 1
            if _adjusted:
                print(f"  [修复] 表「{tbl}」SKILL-DQ-002 列数对齐 {_adjusted} 行")
                fixed_count += _adjusted

        # SKILL-DQ-003: 序号未归并 → 重新执行序号归并
        if "SKILL-DQ-003" in rule_ids:
            ti = {"headers": headers, "rows": [[r.get(h, "") for h in headers] for r in recs]}
            ti = _merge_rows_by_seq(ti)
            new_rows = ti.get("rows", [])
            if len(new_rows) < len(recs):
                new_recs = []
                for row in new_rows:
                    rec = {}
                    for ci, h in enumerate(headers):
                        rec[h] = row[ci] if ci < len(row) else ""
                    rec["source_document"] = recs[0].get("source_document", "")
                    rec["updated_at"] = recs[0].get("updated_at", "")
                    new_recs.append(rec)
                grouped[tbl] = new_recs
                print(f"  [修复] 表「{tbl}」SKILL-DQ-003 序号归并 {len(recs)}→{len(new_recs)} 行")
                fixed_count += abs(len(recs) - len(new_recs))

        # SKILL-DQ-004: 合并单元格未补全 → 重新执行前向填充
        if "SKILL-DQ-004" in rule_ids:
            recs = grouped.get(tbl, recs)
            ti = {"headers": headers, "rows": [[r.get(h, "") for h in headers] for r in recs]}
            ti = _forward_fill_merged_cells(ti)
            new_rows = ti.get("rows", [])
            filled = 0
            for ri, rec in enumerate(recs):
                for ci, h in enumerate(headers):
                    new_val = new_rows[ri][ci] if ri < len(new_rows) and ci < len(new_rows[ri]) else ""
                    if new_val and not rec.get(h):
                        rec[h] = new_val
                        filled += 1
            if filled:
                print(f"  [修复] 表「{tbl}」SKILL-DQ-004 前向填充 {filled} 个空值")
                fixed_count += filled

        # SKILL-DQ-005: 子列未拼接 → 重新执行重复列名合并
        if "SKILL-DQ-005" in rule_ids:
            recs = grouped.get(tbl, recs)
            ti = {"headers": headers, "rows": [[r.get(h, "") for h in headers] for r in recs]}
            ti = _merge_duplicate_headers(ti)
            new_headers = ti.get("headers", [])
            new_rows = ti.get("rows", [])
            if len(new_headers) < len(headers):
                new_recs = []
                for row in new_rows:
                    rec = {}
                    for ci, h in enumerate(new_headers):
                        rec[h] = row[ci] if ci < len(row) else ""
                    rec["source_document"] = recs[0].get("source_document", "")
                    rec["updated_at"] = recs[0].get("updated_at", "")
                    new_recs.append(rec)
                grouped[tbl] = new_recs
                print(f"  [修复] 表「{tbl}」SKILL-DQ-005 子列合并 {len(headers)}→{len(new_headers)} 列")
                fixed_count += abs(len(headers) - len(new_headers))

        # 内容截断/OCR漏行等 → 调 LLM 按行修复（不整表重写）
        _llm_fixed = _llm_fix_rows(tbl, recs, tbl_issues, source_text)
        if _llm_fixed:
            fixed_count += _llm_fixed

    return fixed_count


def _llm_fix_rows(tbl: str, recs: List[Dict], tbl_issues: List[Dict], source_text: str) -> int:
    """调 LLM 按行修复确定性处理不了的问题（截断/内容错误/漏行/列错位）。

    把有问题的行 + 上下文行 + 源文档片段给 LLM，让它输出修复后的行。
    LLM 可以输出比原来更多的行（补回丢失的行），按序号插入到正确位置。
    """
    _llm_issues = []
    for iss in tbl_issues:
        desc = str(iss.get("description", ""))
        if any(kw in desc for kw in ["截断", "截", "漏", "缺失", "不完整", "错位", "错配", "矛盾", "丢失", "减少", "消失"]):
            _llm_issues.append(iss)
    if not _llm_issues:
        return 0

    if not recs:
        return 0
    headers = list(recs[0].keys())
    source_doc = recs[0].get("source_document", "")
    updated_at = recs[0].get("updated_at", "")

    # 从 issue 描述中提取行号/序号
    import re as _re
    target_rows = set()
    for iss in _llm_issues:
        desc = str(iss.get("description", ""))
        for m in _re.finditer(r"第(\d+)行|序号(\d+)|(\d+)行", desc):
            for g in m.groups():
                if g:
                    target_rows.add(int(g) - 1)
    if not target_rows:
        target_rows = set(range(min(5, len(recs))))

    # 准备 LLM 输入：有问题的行 + 上下文（前后各1行）
    _rows_for_llm = []
    for ri in sorted(target_rows):
        if ri < 0 or ri >= len(recs):
            continue
        context = []
        if ri > 0:
            context.append({"row": ri, "context": True, "values": {h: str(recs[ri - 1].get(h, ""))[:50] for h in headers}})
        context.append({"row": ri + 1, "issue": True, "values": {h: str(recs[ri].get(h, ""))[:100] for h in headers}})
        if ri + 1 < len(recs):
            context.append({"row": ri + 2, "context": True, "values": {h: str(recs[ri + 1].get(h, ""))[:50] for h in headers}})
        _rows_for_llm.extend(context)

    issue_descs = "\n".join(f"- [{i.get('rule_id','')}] {str(i.get('description',''))[:150]}" for i in _llm_issues)

    # 找到序号列（如果有）
    seq_col = -1
    for ci, h in enumerate(headers):
        if "序号" in str(h) or "编号" in str(h):
            seq_col = ci
            break

    prompt = f"""请修复以下表格中有问题的行。可以输出比原来更多的行（补回丢失的数据行）。

表名: {tbl}
列: {" | ".join(headers)}

问题:
{issue_descs}

有问题的行及上下文:
"""
    prompt += "| " + " | ".join(headers) + " |\n"
    prompt += "| " + " | ".join("---" for _ in headers) + " |\n"
    for r in _rows_for_llm:
        vals = r.get("values", {})
        cells = [str(vals.get(h, ""))[:80] for h in headers]
        tag = "←问题行" if r.get("issue") else ""
        prompt += f"| {' | '.join(cells)} | {tag}\n"

    prompt += f"""

源文档片段（供参考）:
{source_text[:3000]}

请输出修复后的行（Markdown 表格行格式，含表头行和分隔行）。
- 如果需要补行，直接在正确位置插入新行
- 如果需要修改已有行，输出修改后的完整行
- 不要输出没有问题的行
- 不要输出解释"""

    try:
        _resp = call_tool("llm_generate", prompt=prompt, temperature=0.0, max_tokens=8000)
        content = _resp.get("content", "") if isinstance(_resp, dict) else ""
        if not content:
            return 0
        parsed = _parse_markdown_table(content)
        if not parsed:
            return 0
        fixed_data = parsed[0]
        fixed_rows = fixed_data.get("rows", [])
        if not fixed_rows:
            return 0

        # 把 LLM 输出的行转成 dict
        fixed_recs = []
        for row in fixed_rows:
            rec = {}
            for ci, h in enumerate(headers):
                rec[h] = str(row[ci])[:200] if ci < len(row) else ""
            rec["source_document"] = source_doc
            rec["updated_at"] = updated_at
            fixed_recs.append(rec)

        # 合并修复后的行到原数据
        # 策略：按序号匹配替换，没有匹配的按位置插入
        _fixed_count = 0
        _added_count = 0

        if seq_col >= 0:
            # 有序号列：按序号匹配
            existing_seqs = {}
            for ri, rec in enumerate(recs):
                seq = str(rec.get(headers[seq_col], "")).strip()
                if seq:
                    existing_seqs[seq] = ri

            used_indices = set()
            for fr in fixed_recs:
                seq = str(fr.get(headers[seq_col], "")).strip()
                if seq and seq in existing_seqs:
                    # 替换已有行
                    ri = existing_seqs[seq]
                    _changed = False
                    for h in headers:
                        new_val = str(fr.get(h, ""))
                        old_val = str(recs[ri].get(h, ""))
                        if new_val and new_val != old_val:
                            recs[ri][h] = new_val
                            _changed = True
                    if _changed:
                        _fixed_count += 1
                    used_indices.add(ri)
                else:
                    # 新行——按序号插入到正确位置
                    insert_pos = len(recs)
                    if seq:
                        # 找到比它大的最小序号位置
                        for ri, rec in enumerate(recs):
                            cur_seq = str(rec.get(headers[seq_col], "")).strip()
                            try:
                                if cur_seq and float(cur_seq) > float(seq):
                                    insert_pos = ri
                                    break
                            except (ValueError, TypeError):
                                continue
                    recs.insert(insert_pos, fr)
                    _added_count += 1
        else:
            # 无序号列：按行号替换
            sorted_targets = sorted(target_rows)
            for idx, fr in enumerate(fixed_recs):
                if idx < len(sorted_targets) and sorted_targets[idx] < len(recs):
                    ri = sorted_targets[idx]
                    _changed = False
                    for h in headers:
                        new_val = str(fr.get(h, ""))
                        old_val = str(recs[ri].get(h, ""))
                        if new_val and new_val != old_val:
                            recs[ri][h] = new_val
                            _changed = True
                    if _changed:
                        _fixed_count += 1
                else:
                    # 多出的行追加到末尾
                    recs.append(fr)
                    _added_count += 1

        if _fixed_count or _added_count:
            print(f"  [修复] 表「{tbl}」LLM 修复 {_fixed_count} 行 + 补 {_added_count} 行")
        return _fixed_count + _added_count
    except Exception as e:
        print(f"  [修复] 表「{tbl}」LLM 按行修复失败: {e}")
        return 0


def _to_rule_records(entries: List[Dict[str, Any]], source_document: str) -> List[Dict[str, Any]]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records, seq = [], 0
    for e in entries:
        rule_code = str(e.get("rule_code") or "").strip()
        rule_name = str(e.get("rule_name") or "").strip()
        if not rule_name:
            continue
        if rule_code and re.fullmatch(r"\d+\.0+", rule_code):
            rule_code = rule_code.split(".")[0]
        if not rule_code:
            seq += 1
            rule_code = f"RULE_{seq:04d}"
        records.append({
            "rule_code": rule_code, "rule_name": rule_name,
            "category": str(e.get("category") or "标准").strip(),
            "applicable_fields": str(e.get("applicable_fields") or "").strip(),
            "format_regex": str(e.get("format_regex") or "").strip(),
            "check_logic": str(e.get("check_logic") or "").strip(),
            "severity": str(e.get("severity") or "warn").strip(),
            "description": str(e.get("description") or "").strip(),
            "source_document": source_document, "updated_at": now,
            "_table_assign": str(e.get("table") or "").strip(),
        })
    return records


def _to_chroma_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for i, r in enumerate(records):
        doc_parts = []
        for key, label in [("rule_name", "规则名称"), ("applicable_fields", "适用字段"), ("check_logic", "检查逻辑"), ("description", "规则说明")]:
            val = str(r.get(key) or "").strip()
            if val:
                doc_parts.append(f"{label}：{val}")
        result.append({
            "id": f"{r.get('rule_code', 'rule')}_{i+1}",
            "document": "；".join(doc_parts) if doc_parts else r.get("rule_name", " "),
            "metadata": {k: r.get(k, "") for k in STANDARD_COLUMNS},
        })
    return result


def _to_graph_records(records: List[Dict[str, Any]], source_document: str) -> Dict[str, List]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nodes, edges, cat_nodes, seq = [], [], {}, 0
    for r in records:
        cat = str(r.get("category") or "标准").strip()
        if cat not in cat_nodes:
            cat_nodes[cat] = f"cat_{cat}"
            nodes.append({"node_id": f"cat_{cat}", "node_label": "Category", "name": cat, "properties": json.dumps({"category": cat}, ensure_ascii=False), "source_document": source_document, "updated_at": now})
        node_id = f"rule_{r.get('rule_code', '')}"
        nodes.append({"node_id": node_id, "node_label": "Rule", "name": r.get("rule_name", ""), "properties": json.dumps({k: r.get(k, "") for k in STANDARD_COLUMNS if k != "source_document" and k != "updated_at"}, ensure_ascii=False), "source_document": source_document, "updated_at": now})
        seq += 1
        edges.append({"edge_id": f"e{seq:06d}", "source_node_id": node_id, "target_node_id": cat_nodes[cat], "relation_type": "HAS_CATEGORY", "source_document": source_document, "updated_at": now})
    return {"nodes": nodes, "edges": edges}


def _translate_table_name(table: str) -> str:
    import re as _re
    if _re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', table):
        return table
    for attempt in range(3):
        try:
            response = call_tool("llm_generate", prompt=f"把中文表名翻译成英文 snake_case，只输出英文名：\n{table}", temperature=0.0, max_tokens=500)
            if isinstance(response, dict) and "error" not in response:
                en = _re.sub(r'[^a-zA-Z0-9._-]+', '_', str(response.get("content") or "").strip().strip("`\"'")).strip("._-")
                if en and _re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', en):
                    return en
        except Exception:
            pass
    raise RuntimeError(f"表名翻译失败: {table}")


def _write_records(ds_id: str, table_name: str, records: List[Dict], if_table_exists: str = "replace") -> int:
    if not records:
        return 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    batch_size = 400
    batches = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
    total, batch_total = len(records), len(batches)
    print(f"写入表 {table_name}，共 {total} 条，分 {batch_total} 批")
    print(f"  正在写入第 1/{batch_total} 批 ({len(batches[0])} 条，strategy={if_table_exists})...")
    result = call_tool("write_table_data", datasource_id=ds_id, table_name=table_name, records=batches[0], if_table_exists=if_table_exists)
    if not result.get("success"):
        raise RuntimeError(f"写入失败(表 {table_name}): {result.get('message') or result.get('error') or result}")
    if len(batches) > 1:
        def _append(batch_num, batch):
            print(f"  正在写入第 {batch_num}/{batch_total} 批 ({len(batch)} 条)...")
            r = call_tool("write_table_data", datasource_id=ds_id, table_name=table_name, records=batch, if_table_exists="append")
            if not r.get("success"):
                raise RuntimeError(f"写入失败(表 {table_name} 第 {batch_num} 批): {r.get('message') or r.get('error')}")
            return len(batch)
        # Excel 引擎不支持对同一文件的并发 append（会触发 Permission denied），改为串行
        for i, b in enumerate(batches[1:]):
            _append(i + 2, b)
    print(f"写入完成: {total} 条")
    return total


def _partition_records(records: List[Dict], main_table: str, schema_plan: Optional[Dict] = None) -> Dict[str, List[Dict]]:
    groups, sub_tables = {}, {}
    if schema_plan:
        for t in (schema_plan.get("tables") or []):
            if t.get("name"):
                sub_tables[t["name"]] = t
    for r in records:
        tbl_assign = r.pop("_table_assign", "")
        tbl = main_table
        if tbl_assign and tbl_assign not in ("其他", main_table):
            tbl = tbl_assign if tbl_assign.startswith(main_table) else f"{main_table}_{tbl_assign}"
        elif sub_tables:
            blob = f"{r.get('rule_name', '')} {r.get('description', '')} {r.get('check_logic', '')}"
            best_match, best_score = None, 0
            for name, info in sub_tables.items():
                score = sum(1 for kw in (info.get("keywords") or []) if kw in blob) + sum(2 for tn in (info.get("table_names") or []) if tn and tn in blob)
                if score > best_score:
                    best_score, best_match = score, name
            if best_match and best_score > 0:
                tbl = best_match if best_match.startswith(main_table) else f"{main_table}_{best_match}"
        groups.setdefault(tbl, []).append({k: v for k, v in r.items() if not k.startswith("_")})
    return groups


# ==================== 主函数 ====================

def extract_rules_to_kb(document_paths: str, target_datasource_name: str, target_table_name: str, if_table_exists: str = "replace") -> Dict[str, Any]:
    if isinstance(document_paths, (list, tuple)):
        paths = [str(p).strip() for p in document_paths if str(p).strip()]
    elif isinstance(document_paths, str):
        paths = [p.strip() for p in document_paths.split(",") if p.strip()]
    else:
        raise ValueError(f"document_paths 必须是 str 或 list")
    if not paths:
        raise ValueError("document_paths 不能为空")
    if not target_datasource_name:
        raise ValueError("缺少 target_datasource_name")
    if not target_table_name:
        raise ValueError("缺少 target_table_name")

    # 解析文件路径：如果路径不是绝对路径或不在授权目录内，
    # 通过 list_user_file_links 查找文件链接目录，拼接完整路径
    resolved_paths = []
    for p in paths:
        pp = Path(p)
        if pp.is_absolute() and pp.exists():
            resolved_paths.append(p)
            continue
        # 尝试在文件链接目录中查找
        found = False
        links_res = call_tool("list_user_file_links")
        if isinstance(links_res, dict):
            for link in links_res.get("file_links", []):
                link_path = Path(link.get("path", ""))
                candidate = link_path / p
                if candidate.exists():
                    resolved_paths.append(str(candidate))
                    found = True
                    break
        if not found:
            # 保留原始路径，让后续 read_file 报错给出明确信息
            resolved_paths.append(p)
    paths = resolved_paths

    target_ds_id = _get_datasource_id(target_datasource_name)
    is_graph = _is_graph_datasource(target_datasource_name)
    print(f"目标数据源: {target_datasource_name} (id={target_ds_id}, 图数据库={is_graph})")

    all_entries, table_records_map, schema_plan = [], {}, None
    source_text_by_path: Dict[str, str] = {}
    _table_original_titles: Dict[str, str] = {}

    for idx, path in enumerate(paths, 1):
        print(f"[{idx}/{len(paths)}] 处理文档: {path}")
        text = _extract_text_from_file(path)
        source_text_by_path[path] = text
        print(f"  文档文本总长 {len(text)} 字符")

        blocks = _merge_blocks_by_number(_split_by_tables(text))
        print(f"  [切分] 共 {len(blocks)} 个块")

        # 只对文本层无数据的表格走 OCR
        ocr_blocks = [b for b in blocks if (b.get("title") or "正文") != "正文" and not _table_block_has_data(b)]
        ocr_md_cache = {}
        if ocr_blocks and ocr_blocks[0].get("number"):
            print(f"  [OCR] {len(ocr_blocks)} 个表格文本层无数据，需要 OCR")
            ocr_md_cache = _scan_pages_for_tables(path, [b["number"] for b in ocr_blocks if b.get("number")])
        else:
            print(f"  [OCR] 所有表格文本层有数据，跳过 OCR")

        body_parts, table_blocks = [], []
        for b in blocks:
            if (b.get("title") or "正文") == "正文":
                body_parts.append(b.get("content") or "")
            elif _block_is_body_not_table(b):
                # 表标题后无真实表格数据、紧跟章节正文 → 拆成表标题块(触发OCR) + 正文
                tbl_block, body_text = _split_body_from_table_block(b)
                if tbl_block:
                    table_blocks.append(tbl_block)
                    print(f"  [归类] 「表{b.get('number')} {b.get('title')}」拆出表标题块(待OCR) + 正文")
                if body_text:
                    body_parts.append(body_text)
            else:
                table_blocks.append(b)

        def _process_table(b):
            number = b.get("number") or ""
            try:
                if number in ocr_md_cache:
                    ti = _extract_table_from_ocr(b, ocr_md_cache[number])
                else:
                    ti = _extract_table_literal(b)
                if ti.get("headers") and ti.get("rows"):
                    pass
                return {"table_name": ti["table_name"], "records": _table_rows_to_records(ti, Path(path).name), "title": b.get("title"), "number": number}
            except Exception as e:
                print(f"  [表格] 表{number} 提取失败: {e}")
                return {"table_name": _sanitize_table_name(f"表{number} {b.get('title', '')}".strip()), "records": [], "title": b.get("title"), "number": number}

        if table_blocks:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            print(f"  [表格] 并发还原 {len(table_blocks)} 张表...")
            results_by_idx = {}
            with ThreadPoolExecutor(max_workers=8) as executor:
                futs = {executor.submit(_process_table, b): i for i, b in enumerate(table_blocks)}
                for fut in as_completed(futs):
                    i = futs[fut]
                    r = fut.result()
                    results_by_idx[i] = r
                    print(f"  [表格] 完成 {len(results_by_idx)}/{len(table_blocks)}: 「{r['table_name']}」{len(r['records'])} 行")
            for i in range(len(table_blocks)):
                r = results_by_idx[i]
                table_records_map.setdefault(r["table_name"], []).extend(r["records"])
                # 记录原始表标题（供自检修复表名用）
                _orig_title = ""
                if r.get("number") and r.get("title"):
                    _orig_title = f"表{r['number']} {r['title']}".strip()
                elif r.get("title"):
                    _orig_title = r["title"]
                if _orig_title and _orig_title != r["table_name"]:
                    _table_original_titles[r["table_name"]] = _orig_title

        body_text = "\n".join(p for p in body_parts if p.strip()).strip()
        if body_text:
            schema_plan = _analyze_document_structure(body_text)
            main_tbl = schema_plan.get("main_table") or "正文规则"
            print(f"  [表结构] 主表「{main_tbl}」+ {len(schema_plan.get('tables') or [])} 张子表")
            entries = _extract_rules_from_text(body_text, schema_plan=schema_plan)
            for e in entries:
                e["source_document"] = Path(path).name
            all_entries.extend(entries)
            print(f"  从 {Path(path).name} 正文提取到 {len(entries)} 条规则")

    if not all_entries and not table_records_map:
        raise RuntimeError("未提取到任何规则或表格数据")

    print(f"共提取到 {len(all_entries)} 条正文规则、{len(table_records_map)} 张表格")
    source_doc = Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} 个文档"
    records = _to_rule_records(all_entries, source_doc)

    if is_graph:
        print("目标为图数据库，按图模型存储...")
        graph = _to_graph_records(records, source_doc)
        nodes_table = f"{target_table_name}_nodes"
        edges_table = f"{target_table_name}_edges"
        from concurrent.futures import ThreadPoolExecutor, as_completed
        write_results = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            f_nodes = executor.submit(_write_records, target_ds_id, nodes_table, graph["nodes"], if_table_exists)
            f_edges = executor.submit(_write_records, target_ds_id, edges_table, graph["edges"], if_table_exists)
            for fut in as_completed([f_nodes, f_edges]):
                if fut is f_nodes:
                    write_results["nodes"] = fut.result()
                else:
                    write_results["edges"] = fut.result()
        print(f"  节点 {write_results.get('nodes', 0)} 条，边 {write_results.get('edges', 0)} 条")
        return {"success": True, "extracted_rules": len(all_entries), "total_rules_written": write_results.get("nodes", 0), "graph_model": True, "nodes_table": nodes_table, "edges_table": edges_table, "target_table": nodes_table, "target_datasource": target_datasource_name, "tables_written": {nodes_table: write_results.get("nodes", 0), edges_table: write_results.get("edges", 0)}}

    grouped = _partition_records(records, target_table_name, schema_plan)
    for tbl_name, trecs in table_records_map.items():
        dest = tbl_name
        while dest in grouped:
            dest = f"{tbl_name}_表格明细"
        grouped[dest] = trecs

    # 过滤空壳占位表：schema_plan 生成的英文子表如果只有1-2行且无实质内容，跳过写入
    tables_to_remove = []
    for tbl, recs in grouped.items():
        if len(recs) <= 2 and tbl != target_table_name:
            if re.match(r'^[a-zA-Z_]', tbl) and tbl.startswith(target_table_name + "_"):
                has_substance = False
                for r in recs:
                    cl = str(r.get("check_logic") or "").strip()
                    desc = str(r.get("description") or "").strip()
                    if len(cl) > 20 or len(desc) > 20:
                        has_substance = True
                        break
                if not has_substance:
                    tables_to_remove.append(tbl)
                    print(f"  [过滤] 跳过空壳占位表「{tbl}」（{len(recs)} 行，无实质内容）")
    for tbl in tables_to_remove:
        del grouped[tbl]

    # 写入数据（先写入，用户能看到实际数据）
    _src_text = source_text_by_path.get(paths[0], "") if paths else ""
    print("规则知识库多表存储方案：")
    for tbl, recs in grouped.items():
        print(f"  - 表「{tbl}」: {len(recs)} 条")

    is_chroma = _is_chroma_datasource(target_datasource_name)
    if is_chroma:
        print("  [向量库] 转换为 ChromaDB 格式...")
        grouped = {tbl: _to_chroma_records(recs) for tbl, recs in grouped.items()}
        print("  [向量库] 翻译表名...")
        grouped = {_translate_table_name(tbl): recs for tbl, recs in grouped.items()}

    grouped = {tbl: [{k: ("" if v is None else v) for k, v in r.items()} for r in recs] for tbl, recs in grouped.items()}

    # Excel 数据源不支持并发写（多个 xlsx 文件同时写入会触发 Permission denied 文件锁冲突），
    # 改为逐表串行写入，保证每个表独占写入完成后再写下一个。
    written_total = 0
    _tbl_idx = 0
    _tbl_count = len(grouped)
    for tbl, recs in grouped.items():
        _tbl_idx += 1
        print(f"  [进度] 正在写入第 {_tbl_idx}/{_tbl_count} 个表「{tbl}」...")
        n = _write_records(target_ds_id, tbl, recs, if_table_exists)
        written_total += n
        print(f"  [完成] 表「{tbl}」写入 {n} 条")

    # 写入后自检：不限轮数，直到无问题或超过 10 轮，每轮修复后重新写入修改过的表
    _check_round = 0
    _all_check_issues = []
    while _check_round < 5:
        _check_round += 1
        _all_check_issues = []
        for tbl, recs in list(grouped.items()):
            if not recs:
                continue
            headers = list(recs[0].keys())
            rows = [[r.get(h, "") for h in headers] for r in recs]
            _result = call_tool("check_skill_rules", headers=headers, rows=rows, source_text=_src_text, table_name=tbl)
            if isinstance(_result, dict) and _result.get("issues"):
                for _iss in _result["issues"]:
                    if _iss.get("rule_id") == "SKILL-DQ-001":
                        continue
                    if str(_iss.get("severity", "")).strip().lower() not in ("error", "critical"):
                        continue
                    _all_check_issues.append((tbl, _iss))
        if not _all_check_issues:
            print(f"[自检] 第{_check_round}轮检查通过")
            break
        print(f"[自检] 第{_check_round}轮发现 {len(_all_check_issues)} 个问题")
        for tbl, iss in _all_check_issues:
            print(f"  [{iss.get('severity','?')}] {iss.get('rule_id','')} 表「{tbl}」: {iss.get('description','')[:80]}")
        # 按行/列修复
        _fixed_count = _apply_row_col_fixes(grouped, _all_check_issues, _src_text, _table_original_titles)
        print(f"[自检] 按行/列修复 {_fixed_count} 处")
        # 修复后重新写入修改过的表
        _modified_tables = set()
        for tbl, _ in _all_check_issues:
            _modified_tables.add(tbl)
        if _modified_tables:
            for tbl in _modified_tables:
                recs = grouped.get(tbl, [])
                if recs:
                    print(f"[自检] 重新写入表「{tbl}」({len(recs)} 条)")
                    _write_records(target_ds_id, tbl, recs, "overwrite")
    else:
        print(f"[自检] {_check_round}轮修复后仍有 {len(_all_check_issues)} 个问题，停止")

    # 自检未通过则报错，Inspector 不会接管
    if _all_check_issues:
        print(f"[自检] 发现 {len(_all_check_issues)} 个问题，请手动检查：")
        for tbl, iss in _all_check_issues:
            print(f"  [{iss.get('severity','?')}] {iss.get('rule_id','')} 表「{tbl}」: {iss.get('description','')[:100]}")
        _issue_summary = "; ".join(f"[{iss.get('rule_id','')}] 表「{tbl}」: {iss.get('description','')[:60]}" for tbl, iss in _all_check_issues[:10])
        return {"success": False, "error": f"自检发现 {len(_all_check_issues)} 个问题，数据已写入但未通过质量检查。请查看数据源中的实际数据并手动修复。问题：{_issue_summary}", "extracted_rules": len(all_entries), "total_rules_written": written_total, "target_table": target_table_name, "target_datasource": target_datasource_name, "tables_written": {tbl: len(recs) for tbl, recs in grouped.items()}}

    print("[自检] 检查通过")
    return {"success": True, "extracted_rules": len(all_entries), "total_rules_written": written_total, "target_table": target_table_name, "target_datasource": target_datasource_name, "tables_written": {tbl: len(recs) for tbl, recs in grouped.items()}}


def main(**params: Any) -> Dict[str, Any]:
    param_aliases = {
        "document_paths": ["document_paths", "file_paths", "files", "paths"],
        "target_datasource_name": ["target_datasource_name", "target_datasource", "output_datasource"],
        "target_table_name": ["target_table_name", "target_table", "output_table"],
        "if_table_exists": ["if_table_exists", "write_strategy"],
    }
    def get_param(key, default=None):
        for alias in param_aliases.get(key, [key]):
            if alias in params and params[alias] is not None:
                return params[alias]
        return default

    document_paths = get_param("document_paths")
    if not document_paths:
        raise ValueError("缺少必填参数 document_paths")
    return extract_rules_to_kb(
        document_paths=document_paths,
        target_datasource_name=get_param("target_datasource_name"),
        target_table_name=get_param("target_table_name"),
        if_table_exists=get_param("if_table_exists", "replace"),
    )