from pathlib import Path
import re
import json
import time
import threading
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

_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(str(s)))

def _get_datasource_id(name: str) -> str:
    if _is_uuid(name):
        return name
    print(f"正在查找数据源: {name}")
    ds = call_tool("list_user_datasources", by_name=name)
    if not ds or not isinstance(ds, dict) or not ds.get("id"):
        raise ValueError(f"找不到数据源: {name}")
    print(f"数据源已找到: {name} (id={ds['id']})")
    return ds["id"]


def _is_graph_datasource(name: str) -> bool:
    if _is_uuid(name):
        return False
    try:
        ds = call_tool("list_user_datasources", by_name=name)
        if isinstance(ds, dict):
            t = str(ds.get("type") or "").lower()
            return any(k in t for k in ("graph", "neo4j", "nebula", "arangodb", "tigergraph"))
    except Exception:
        pass
    return False


def _is_chroma_datasource(name: str) -> bool:
    if _is_uuid(name):
        return False
    try:
        ds = call_tool("list_user_datasources", by_name=name)
        if isinstance(ds, dict):
            t = str(ds.get("type") or "").lower()
            return "chroma" in t or "vector" in t or "vectordb" in t
    except Exception:
        pass
    return False


# ==================== 文件文本提取 ====================

_CACHE_MAX_AGE = 86400  # 缓存有效期 24 小时，超时自动失效重新提取


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
            _cf = Path(str(cand))
            if _cf.exists():
                _age = time.time() - _cf.stat().st_mtime
                if _age > _CACHE_MAX_AGE:
                    print(f"  [缓存] {cand.name} 已过期（{_age/3600:.1f}h），重新提取")
                    continue
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


def _normalize_pdf_text(text: str) -> str:
    """合并 PDF 文本提取产生的行内软换行，避免句子被换行拆散后被下游截断。

    只合并「上一行末字符和下一行首字符都是中文」且「上一行行末无句末标点」的软换行；
    空行和句末标点结尾的行保留换行，段落/条款分隔不受影响。
    """
    if not text:
        return text
    _sentence_enders = "。！？；：…"
    lines = text.split("\n")
    out = []
    for line in lines:
        s = line.rstrip()
        if not s:
            out.append("")
            continue
        if out and out[-1]:
            prev = out[-1]
            if (prev[-1] not in _sentence_enders
                    and "\u4e00" <= prev[-1] <= "\u9fff"
                    and "\u4e00" <= s[0] <= "\u9fff"):
                out[-1] = prev + s
                continue
        out.append(s)
    return "\n".join(out)


_TABLE_TITLE_PATTERN = re.compile(
    r"^(?:表格|图表|表|Table|Figure|Fig)\s*\.?\s*([A-Za-zÀ-ÿ]?\s*\.?\s*\d+(?:[.．]\d+)?)\s*(?:[（(]\s*续\s*[)）])?\s*[:：]?\s*(.*)$",
    re.IGNORECASE
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
    if m and re.match(r"^(?:表格|图表|表|Table|Figure|Fig)", s, re.IGNORECASE):
        return True, _normalize_table_number(m.group(1).strip()), m.group(2).strip(), bool(re.search(r"[（(]\s*续\s*[)）]", s))
    return False, "", "", False


def _looks_like_table_name(s: str) -> bool:
    s = (s or "").strip()
    if not s or len(s) < 4 or len(s) > 60:
        return False
    if re.match(r"^[0-9IVXivx．.、]", s) or "|" in s:
        return False
    if not re.search(r"[\u4e00-\u9fff]", s):
        return False
    # 过滤水印特征：含 >> 或 （系统入口 或 知识共享 或 管理平台
    _WM_KEYWORDS = ("系统入口", "知识共享", "管理平台", ">>", "资产域", "创新管理")
    if any(kw in s for kw in _WM_KEYWORDS):
        return False
    return True


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
            if not desc:
                # 向下扫描找真正的表名（跳过空行和水印行）
                for j in range(i + 1, min(i + 5, len(lines))):
                    _next = lines[j].strip()
                    if not _next:
                        continue
                    if _looks_like_table_name(_next):
                        merged_title = _next
                        break
                    # 遇到非表名的内容行就停止（表名不会隔太远）
                    if _next and not _next.startswith("表"):
                        break
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

    chunks = _split_by_tables(text)
    # 正文大块按字符数细切（防单次 llm_generate 过长触发超时）；_process 内有进度 print 保活
    _MAX_BLOCK = 6000
    _flat_chunks = []
    for b in chunks:
        content = b.get("content") or ""
        if len(content) <= _MAX_BLOCK:
            _flat_chunks.append(b)
        else:
            for i, sub in enumerate(_split_text(content, _MAX_BLOCK, 300), 1):
                _flat_chunks.append({"title": (b.get("title") or "正文") + f"(分段{i})", "number": b.get("number") or "", "content": sub})
    chunks = _flat_chunks
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
- check_logic: 检查逻辑（逐条独立成行，不得合并去重；**完整复制原文条款内容，禁止截断、禁止省略号、禁止概括压缩——长条款也要一字不落全部放入**）
- severity: info/warn/error/critical
- description: 规则详细解释（同样完整保留原文，不得截断）
- table: 归属表名（从下方结构中选择；无法判断填「{main_table}」）

{schema_block}【表格复原要求】
1. 转置表格还原为每行一个规则，字段名作为 applicable_fields
2. 同一语义被分页拆散的行必须按语义合并
3. 表头与单元格内容逐字保留，数值阈值不得改写
4. 续表行并入同一张表

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

    # 截断检测：长文本字段以非终结词结尾（逗号/顿号/"的"/"和"等）→ 句子不完整，内容被截断
    _TRUNC_ENDINGS = ("，", "、", "；", "：", "的", "和", "与", "或", "及", "等", "中", "在", "由", "被", "...", "…")

    def _has_truncated_field(entries: List[Dict[str, Any]]) -> bool:
        for e in entries:
            for field in ("check_logic", "description"):
                val = str(e.get(field) or "").strip()
                if len(val) >= 30 and val.endswith(_TRUNC_ENDINGS):
                    return True
        return False

    def _process(idx, block):
        title = block.get("title") or "正文"
        content = block["content"]
        print(f"    [提取] 开始第 {idx} 段（{title}，{len(content)} 字符）", flush=True)
        for attempt, cfg in enumerate(RETRY_CONFIGS, 1):
            print(f"    [提取] 第 {idx} 段 第{attempt}次调用 llm_generate...", flush=True)
            status, parsed = _call_once(block, cfg)
            if status == "ok":
                # 截断检测：字段以非终结词结尾 → 视为失败重试（不把截断数据当成功）
                if _has_truncated_field(parsed):
                    print(f"    [提取] 第 {idx} 段 第{attempt}次输出存在截断字段（句子不完整），重试...", flush=True)
                    continue
                return idx, parsed
            if status == "timeout":
                break
        sub_chunks = _split_text(content, 2400, 0)
        all_parsed = []
        print(f"    [提取] 第 {idx} 段 整块失败，细切为 {len(sub_chunks)} 块", flush=True)
        for s_idx, sub in enumerate(sub_chunks, 1):
            sub_block = {"title": title, "content": sub}
            for cfg in RETRY_CONFIGS:
                print(f"    [提取] 第 {idx} 段 细切{s_idx}/{len(sub_chunks)} 调用...", flush=True)
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
    import threading as _threading_mod
    _hb_stop = _threading_mod.Event()
    _hb_done = [0]
    def _heartbeat():
        _cnt = 0
        while not _hb_stop.wait(20):
            _cnt += 1
            print(f"    [心跳] 正文提取中... 已完成 {_hb_done[0]}/{total}", flush=True)
    _hb_thread = _threading_mod.Thread(target=_heartbeat, daemon=True)
    _hb_thread.start()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process, idx, chunk): idx for idx, chunk in enumerate(chunks, 1)}
        done = 0
        for fut in as_completed(futures):
            idx = futures[fut]
            done += 1
            _hb_done[0] = done
            try:
                _, parsed = fut.result()
                results[idx] = parsed
                print(f"    [进度 {done}/{total}] 第 {idx} 段 {len(parsed)} 条")
            except Exception as e:
                errors.append((idx, str(e)))
                print(f"    [错误] 第 {idx}/{total} 段: {e}")
    _hb_stop.set()
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
                    entries.append({"rule_code": m.group(1), "rule_name": current_title, "category": "标准", "applicable_fields": "", "format_regex": "", "check_logic": content, "severity": "warn", "description": content})
            current_title = f"{m.group(1)} {m.group(2)}".strip()
            current_lines = []
        elif current_title:
            current_lines.append(s)
    if current_title:
        content = "\n".join(current_lines).strip()
        if len(content) >= 15:
            entries.append({"rule_code": "", "rule_name": current_title, "category": "标准", "applicable_fields": "", "format_regex": "", "check_logic": content, "severity": "warn", "description": content})
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
    short_value_lines = 0
    for line in content.split("\n"):
        s = line.strip()
        if not s or _parse_table_title(s)[0] or s in ("(续)", "（续）") or len(s) < 2:
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
        # fitz 格式：每行一个字段值（短行），无分隔符但行数多
        # 表格数据行特征：短行（<80字符）且含中文/数字/罗马数字/特殊符号
        elif len(s) < 80 and re.search(r"[\u4e00-\u9fff0-9IVXivx～~≥≤<>%μ]", s):
            short_value_lines += 1
    # 如果大部分行是章节标题（目录/正文），判定为无表格数据
    if total_lines > 0 and chapter_heading_count >= total_lines * 0.5:
        return False
    # fitz 格式：短字段值行 ≥3 行 → 有数据（表格行列被展平为逐行文本）
    if short_value_lines >= 3:
        return True
    return len(data_lines) >= 2


_CHAPTER_HEADING_RE = re.compile(r"^\d{1,3}(?:\.\d+){0,3}\s+\S")


def _block_is_body_not_table(block: Dict[str, str]) -> bool:
    """判断一个「表X」块是否实为正文（表标题后无真实表格数据，紧跟章节正文）。

    通用判据（不依赖具体文档/业务词）：
    1. 块内存在章节标题行（如「6 XX内容」「7 XX类别」，形如 X 标题 / X.Y 标题）；
    2. 且不存在真实表格数据行（制表符分隔、多空格对齐、或短序号开头、或 fitz 格式短字段值行）。
    满足两者 → 该表标题后实为正文，应归入正文而非表格。
    """
    content = block.get("content") or ""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    chapter_headings = 0
    table_data_lines = 0
    short_value_lines = 0
    for ln in lines:
        if _parse_table_title(ln)[0] or ln in ("(续)", "（续）"):
            continue
        if _CHAPTER_HEADING_RE.match(ln) and len(ln) < 80:
            chapter_headings += 1
            continue
        if "|" in ln or "\t" in ln:
            table_data_lines += 1
        elif re.search(r"\s{2,}", ln) and len(ln) < 80:
            table_data_lines += 1
        elif re.match(r"^\d{1,3}\s", ln) and len(ln) < 60:
            table_data_lines += 1
        elif len(ln) < 80 and re.search(r"[\u4e00-\u9fff0-9IVXivx～~≥≤<>%μ]", ln):
            short_value_lines += 1
    return chapter_headings >= 1 and table_data_lines <= 3 and short_value_lines < 3


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

_OCR_PROMPT = """你是表格 OCR 专家。请把页面上**实际存在的**表格识别输出为 Markdown。
不要编造页面上不存在的表格。如果页面上没有表格，直接输出空内容。

## 输出格式
每个表格前一行标题（表号 + 名称），紧跟 Markdown 表格：
表X.Y 表格名称
| 列1 | 列2 | 列3 |
| --- | --- | --- |
| 数据 | 数据 | 数据 |

## 核心要求

### 1. 多级表头应该合并
多级表头应该按照子表头分开，父表头内容拼接入子表头。

合并前：
| 序号 |    状态量         |
|      | 分类 | 状态量名称 |
| --- | --- | --- |
| 1运行 | 红外测温 |

合并后：
| 序号 | 状态量 分类 | 状态量 状态量名称 |
| --- | --- | --- |
| 1 | 运行 | 红外测温 |

### 2. 合并单元格必须回填
垂直合并单元格的值，每一行都要重复输出，绝不能留空。

处理前：
| 序号 | 状态量 分类 | 状态量 状态量名称 | 劣化状态 |
| --- | --- | --- | --- |
| 1 |      | SF6压力表 | I~II |
|  | 运行 |           | II~IV |
| 2 |      | SF6压力器 | I~II |
|  |      |           | II~IV |
| 3 | 检修 | 锈蚀 | I~II |

处理后：
| 序号 | 状态量 分类 | 状态量 状态量名称 | 劣化状态 |
| --- | --- | --- | --- |
| 1 | 运行 | SF6压力表 | I~II |
| 1 | 运行 | SF6压力表 | II~IV |
| 2 | 运行 | SF6压力器 | I~II |
| 2 | 运行 | SF6压力器 | II~IV |
| 3 | 检修 | 锈蚀 | I~II |

### 3. 子列要进行拼接
表头列下嵌套的子列，子列值要与父级值拼接为一个单元格（父级值+子列值）。
父级值跨行合并时，每一行都要拼接并重复输出，不得留空。
**特别注意：状态量名称下的子项绝不能填进"分类"列——分类列只放"运行/检修试验/其他"这类大分类。**

处理前（子列嵌套在状态量名称下；常见错误：第一个子项"外观/压力表"被错填进分类列）：
| 序号 | 状态量 分类 | 状态量 状态量名称 | 劣化程度 | 劣化情况 | 检修内容和类别 |
| --- | --- | --- | --- | --- | --- |
| 1 | 检修试验 | SF6气体分解物 | H2S含量 | II~III | 不小于1μL/L，但小于2μL/L | 情况一：未明确... |
|  |  |  | SO2含量 | II~III | 不小于1μL/L，但小于2μL/L | 情况二：... |
| 8 | 检修试验 | 汇控柜或机构箱 | 密封 | I | 密封不良 | D类检修：... |
|  |  |  | 锈蚀 | II | 加热器装置损坏 |  |
|  |  |  | 损坏 | II | 接触器锈蚀 | B类检修：... |
| 20 | 外观 | SF6压力表及密度继电器 | III | 外观有破损 | D类检修：更换 |
|  | 压力表 |  | IV | 压力表指示异常 | B类检修：更换 |
|  | 密封 |  | IV | 表有渗漏油 | B类检修：处理漏气 |

处理后（父级值+子列值拼接成完整状态量名称；分类列保持"运行/检修试验"这类大分类，子项留在名称里拼接）：
| 序号 | 状态量 分类 | 状态量 状态量名称 | 劣化程度 | 劣化情况 | 检修内容和类别 |
| --- | --- | --- | --- | --- | --- |
| 1 | 检修试验 | SF6气体分解物H2S含量 | II~III | 不小于1μL/L，但小于2μL/L | 情况一：未明确... |
| 1 | 检修试验 | SF6气体分解物SO2含量 | II~III | 不小于1μL/L，但小于2μL/L | 情况二：... |
| 8 | 检修试验 | 汇控柜或机构箱密封 | I | 密封不良 | D类检修：... |
| 8 | 检修试验 | 汇控柜或机构箱锈蚀 | II | 加热器装置损坏 |  |
| 8 | 检修试验 | 汇控柜或机构箱损坏 | II | 接触器锈蚀 | B类检修：... |
| 20 | 运行 | SF6压力表及密度继电器外观 | III | 外观有破损 | D类检修：更换 |
| 20 | 运行 | SF6压力表及密度继电器压力表 | IV | 压力表指示异常 | B类检修：更换 |
| 20 | 运行 | SF6压力表及密度继电器密封 | IV | 表有渗漏油 | B类检修：处理漏气 |

### 4. 矩阵表保持原结构
行×列交叉的决策表，行表头在第一列，列表头各占一列，不要混填。

处理前：
| 设备状态 | 推荐检修时间 |
| --- | --- |
| 推荐检修时间 | 正常周期 |

处理后：
| 设备状态 | 正常状态 | 注意状态 | 异常状态 | 严重状态 |
| --- | --- | --- | --- | --- |
| 推荐检修时间 | 正常周期或延长一年 | 不大于正常周期 | 适时安排 | 尽快安排 |

### 5. 其他要求
- 只识别页面上实际存在的表格，不要编造不存在的表格
- 数值阈值逐字保留，不得改写
- 每行列数必须与表头一致
- 单元格内容完整输出，禁止截断
- 忽略水印/页眉/页脚/封面信息
- 直接输出 Markdown，不要代码围栏
- 不要输出解释文字"""


def _ocr_has_table(md_text: str) -> bool:
    """检测 OCR 结果是否包含 Markdown 表格（至少 2 行含 |）。"""
    if not md_text or not md_text.strip():
        return False
    pipe_lines = [ln for ln in md_text.split("\n") if ln.strip().startswith("|") and ln.strip().endswith("|")]
    return len(pipe_lines) >= 2


def _ocr_table_on_demand(pdf_path: str, table_number: str, table_title: str) -> str:
    """Per-table 按需 OCR：只扫描可能含该表的页，不预扫全部 image_pages。

    策略：
    1. read_file 获取 total_pages + image_pages + page_texts
    2. 从 page_texts 中搜索表号出现的页号（文本层有表标题但可能无表格数据）
    3. image_pages + 表号所在页 合并去重 → ocr_pages
    4. 无 image_pages 且无表号匹配 → 可能是纯扫描件，扫全部页
    5. 复用提取阶段的页级磁盘缓存（_ocr_cache_p{N}.md）
    """
    from pathlib import Path as _Path
    text_res = call_tool("read_file", path=pdf_path)
    if not isinstance(text_res, dict) or "content" not in text_res:
        return ""
    total_pages = text_res.get("total_pages") or 0
    if not total_pages:
        probe = call_tool("read_file", path=pdf_path, pdf_page_images=[1], dpi=72)
        total_pages = probe.get("total_pages") if isinstance(probe, dict) else 0
    if not total_pages:
        return ""

    image_pages = text_res.get("image_pages") or []
    page_texts = text_res.get("page_texts") or []
    
    # 从 page_texts 中搜索表号出现的页号
    table_text_pages = []
    if table_number and page_texts:
        _tbl_pat = re.compile(r"表\s*" + re.escape(table_number) + r"\b", re.IGNORECASE)
        for pi, pt in enumerate(page_texts):
            if pt and _tbl_pat.search(pt):
                table_text_pages.append(pi + 1)  # page_texts 是 0-indexed，页号是 1-indexed
    
    # 合并 image_pages + 表号所在页，去重排序
    ocr_pages = sorted(set(image_pages + table_text_pages))[:30]
    if not ocr_pages:
        ocr_pages = list(range(1, min(total_pages, 30) + 1))

    # 页级磁盘缓存（与提取阶段共用）
    _pdf_p = _Path(pdf_path)
    try:
        _size_tag = _pdf_p.stat().st_size
    except Exception:
        _size_tag = 0
    _cache_dir = _pdf_p.parent / "_ocr_cache"
    try:
        _cache_dir.mkdir(exist_ok=True)
    except Exception:
        _cache_dir = _pdf_p.parent

    def _cache_path(pg):
        return _cache_dir / f"{_pdf_p.stem}[_{_size_tag}]_p{pg}.md"

    def _cache_load(pg):
        try:
            _f = _cache_path(pg)
            if _f.exists():
                _age = time.time() - _f.stat().st_mtime
                if _age > _CACHE_MAX_AGE:
                    return ""
                _c = _f.read_text(encoding="utf-8").strip()
                if _c:
                    return _c
        except Exception:
            pass
        return ""

    def _cache_write(pg, raw):
        try:
            _cache_path(pg).write_text(raw, encoding="utf-8")
        except Exception:
            pass

    # 先吃缓存（加锁：检查缓存 → 拿到锁 → 再检查一次 → OCR → 写缓存 → 释放锁）
    cached_mds = []
    pages_to_ocr = []
    for pg in ocr_pages:
        cached = _cache_load(pg)
        if cached:
            cached_mds.append((pg, cached))
        else:
            pages_to_ocr.append(pg)

    if cached_mds:
        print(f"  [OCR] 缓存命中 {len(cached_mds)}/{len(ocr_pages)} 页", flush=True)

    # 只扫未缓存的页
    if pages_to_ocr:
        print(f"  [OCR] 需扫描 {len(pages_to_ocr)} 页: {pages_to_ocr[:10]}", flush=True)
        batch_size = 5
        for bi in range(0, len(pages_to_ocr), batch_size):
            batch_pages = pages_to_ocr[bi:bi + batch_size]
            print(f"  [OCR] 渲染第 {batch_pages} 页...", flush=True)
            try:
                img_res = call_tool("read_file", path=pdf_path, pdf_page_images=batch_pages, dpi=200)
                if not isinstance(img_res, dict) or not img_res.get("success"):
                    continue
                image_paths = img_res.get("image_paths") or []
            except Exception:
                continue

            from concurrent.futures import ThreadPoolExecutor, as_completed
            def _ocr_one(pg, img_p):
                for _ in range(3):
                    try:
                        vres = call_tool("llm_vision", image_path=img_p, prompt=_OCR_PROMPT)
                        if isinstance(vres, dict) and "error" not in vres:
                            raw = str(vres.get("result") or "").strip()
                            if raw:
                                _cache_write(pg, raw)
                                return pg, raw
                    except Exception:
                        pass
                return pg, ""

            page_imgs = {}
            for i, img_path in enumerate(image_paths):
                page_no = batch_pages[i] if i < len(batch_pages) else 0
                page_imgs[page_no] = str(img_path)

            with ThreadPoolExecutor(max_workers=5) as ex:
                futs = {ex.submit(_ocr_one, pg, img_p): pg for pg, img_p in page_imgs.items()}
                for fut in as_completed(futs):
                    pg, raw = fut.result()
                    if raw:
                        _cache_write(pg, raw)
                        cached_mds.append((pg, raw))
                    print(f"  [OCR] 第 {pg} 页完成", flush=True)

    # 从所有 OCR 结果中过滤出该表的数据
    target_mds = []
    for pg, raw in cached_mds:
        # 跳过纯图片页（无表格的示意图/流程图/照片等）
        if not _ocr_has_table(raw):
            print(f"  [OCR] 第 {pg} 页无表格（纯图片/示意图），跳过", flush=True)
            continue
        if table_number:
            target = _filter_md_by_table_number(raw, table_number)
            if target:
                target_mds.append(f"== 第 {pg} 页 ==\n{target}")
                _TABLE_PAGE_MAP.setdefault(table_number, []).append(pg)
        else:
            target_mds.append(f"== 第 {pg} 页 ==\n{raw}")

    if not target_mds:
        print(f"  [OCR] 表{table_number} 未在 {len(cached_mds)} 页中匹配到表格数据", flush=True)
        return ""

    return "\n\n".join(target_mds)


def _scan_pages_for_tables(pdf_path: str, table_numbers: List[str], start_page: int = 1) -> Dict[str, str]:
    """批量按页 OCR：每页只 OCR 一次，返回 {页号: MD}。

    OCR 只负责识别，不做表号分类。按表号分类是后处理的事。
    页来源 = image_pages（含嵌入图片的页）∪ table_text_pages（page_texts 中提到表号的页）。
    """
    from pathlib import Path as _Path
    text_res = call_tool("read_file", path=pdf_path)
    if not isinstance(text_res, dict) or "content" not in text_res:
        raise RuntimeError(f"read_file 获取 PDF 失败: {text_res!r}")
    total_pages = text_res.get("total_pages") or 0
    if not total_pages:
        probe = call_tool("read_file", path=pdf_path, pdf_page_images=[1], dpi=72)
        total_pages = probe.get("total_pages") if isinstance(probe, dict) else 0

    image_pages = text_res.get("image_pages") or []
    page_texts = text_res.get("page_texts") or []

    # 从 page_texts 中搜索表号出现的页号（归一化匹配：Á→A 等重音字符）
    import unicodedata as _ud
    def _strip_accents(s):
        """只去掉拉丁字母的重音符号，保留中文和其他字符"""
        return "".join(c for c in _ud.normalize("NFKD", s) if not _ud.combining(c))
    table_text_pages = []
    if page_texts and table_numbers:
        for num in table_numbers:
            if not num:
                continue
            _num_norm = _strip_accents(num)
            _tbl_pat = re.compile(r"表\s*" + re.escape(_num_norm) + r"\b", re.IGNORECASE)
            for pi, pt in enumerate(page_texts):
                if not pt:
                    continue
                if _tbl_pat.search(_strip_accents(pt)):
                    table_text_pages.append(pi + 1)

    # 合并 image_pages + 表号所在页，去重排序
    ocr_pages = sorted(set(image_pages + table_text_pages))
    ocr_pages = [p for p in ocr_pages if start_page <= p and p <= (total_pages or 999)]

    if not ocr_pages:
        print(f"  [OCR] 无需扫描的页（无图片页且无表号匹配），跳过 OCR", flush=True)
        return {}

    _src_parts = []
    if image_pages:
        _src_parts.append(f"图片页 {len(image_pages)} 页")
    if table_text_pages:
        _src_parts.append(f"表号文本页 {len(set(table_text_pages))} 页")
    print(f"  [OCR] 需扫描 {len(ocr_pages)} 页（{' + '.join(_src_parts)}，去重后）: {ocr_pages[:15]}", flush=True)

    ocr_prompt = _OCR_PROMPT

    # 每页 OCR 结果：{页号: MD}，不按表号拆分，OCR 只负责识别
    md_by_page: Dict[int, str] = {}

    # ===== OCR 页级落盘缓存 =====
    # 每页 OCR 成功立即落盘 _ocr_cache_p{N}.md；
    # 重跑（超时被杀/迭代调试）直接复用缓存页，不再重新 OCR——
    # 全页 OCR 一次 10-27 分钟，缓存命中后秒级恢复进度。
    _pdf_p = _Path(pdf_path)
    try:
        _size_tag = _pdf_p.stat().st_size
    except Exception:
        _size_tag = 0
    _cache_dir = _pdf_p.parent / "_ocr_cache"
    try:
        _cache_dir.mkdir(exist_ok=True)
    except Exception:
        _cache_dir = _pdf_p.parent

    def _cache_path(pg: int) -> _Path:
        return _cache_dir / f"{_pdf_p.stem}[_{_size_tag}]_p{pg}.md"

    def _cache_write(pg: int, raw: str):
        try:
            _cache_path(pg).write_text(raw, encoding="utf-8")
        except Exception as _e:
            print(f"  [OCR] 第 {pg} 页缓存写入失败(不影响): {_e}", flush=True)

    def _cache_load(pg: int) -> str:
        try:
            _f = _cache_path(pg)
            if _f.exists():
                _c = _f.read_text(encoding="utf-8").strip()
                if _c:
                    return _c
        except Exception:
            pass
        return ""

    # 先吃缓存：已缓存的页直接用，未缓存的进 OCR 队列
    _pages_to_ocr = []
    _cache_hit = 0
    for _pg in ocr_pages:
        _cached = _cache_load(_pg)
        if _cached:
            _cache_hit += 1
            if _ocr_has_table(_cached):
                md_by_page[_pg] = _cached
                _target_rows = _count_md_data_rows(_cached)
                print(f"  [OCR] 第 {_pg} 页 提取 {_target_rows} 行数据（缓存）", flush=True)
            else:
                print(f"  [OCR] 第 {_pg} 页无表格（缓存），跳过", flush=True)
        else:
            _pages_to_ocr.append(_pg)
    print(f"  [OCR] 缓存命中 {_cache_hit}/{len(ocr_pages)} 页，需 OCR {_pages_to_ocr} 页", flush=True)

    batch_size = 5
    for bi in range(0, len(_pages_to_ocr), batch_size):
        batch_pages = _pages_to_ocr[bi:bi + batch_size]
        print(f"  [OCR] 渲染第 {batch_pages} 页…", flush=True)
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
                            _cache_write(pg, raw)
                            return pg, raw
                except Exception:
                    pass
            return pg, ""

        page_imgs = {}
        for i, img_path in enumerate(image_paths):
            page_no = batch_pages[i] if i < len(batch_pages) else 0
            page_imgs[page_no] = str(img_path)

        _ocr_done = 0
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(_ocr_one, pg, img_p): pg for pg, img_p in page_imgs.items()}
            for fut in as_completed(futs):
                pg, raw = fut.result()
                _ocr_done += 1
                if raw:
                    _cache_write(pg, raw)
                    if not _ocr_has_table(raw):
                        print(f"  [OCR] 第 {pg} 页无表格（纯图片/示意图），跳过", flush=True)
                    else:
                        md_by_page[pg] = raw
                        _target_rows = _count_md_data_rows(raw)
                        print(f"  [OCR] 第 {pg} 页 提取 {_target_rows} 行数据", flush=True)
                else:
                    print(f"  [OCR] 第 {pg} 页 OCR 返回空", flush=True)
                print(f"  [OCR] 第 {pg} 页完成（{_ocr_done}/{len(page_imgs)}）", flush=True)

    return {str(pg): md for pg, md in sorted(md_by_page.items())}


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

    # 3. 兜底：没有标题行但有 | 行 → 不返回（避免编造数据匹配到错误表号）
    # 旧版兜底返回全部 | 行，但新版 prompt 带例子后 Vision 模型可能在无表页面也输出 | 行

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


def _count_md_data_rows(md_text: str) -> int:
    """统计 Markdown 表格中的数据行数（去掉表头行和分隔线行）。"""
    if not md_text:
        return 0
    lines = [ln.strip() for ln in md_text.splitlines() if ln.strip()]
    tbl_lines = [ln for ln in lines if "|" in ln]
    if not tbl_lines:
        return 0
    sep_idx = None
    for i, ln in enumerate(tbl_lines):
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if all(re.fullmatch(r"[-=: ]+", c) for c in cells if c):
            sep_idx = i
            break
    if sep_idx is not None:
        return len(tbl_lines) - sep_idx - 1
    return max(len(tbl_lines) - 1, 0)


def _merge_md_tables(title: str, number: str, md_parts: List[str]) -> Dict[str, Any]:
    """确定性归并：用 _parse_markdown_table 解析 + 去重复表头 + 合并多段。

    不调 LLM——OCR 返回的 Markdown 表格本身就是结构化的（| 分隔），
    确定性操作即可归并，LLM 归并会丢行/改写/不稳定。
    """
    all_md = "\n\n".join(p for p in md_parts if p and p.strip())
    if not all_md.strip():
        return {"headers": [], "rows": []}

    # 按 == 第 N 页 == 拆分多段
    page_parts = re.split(r"(?=== 第 \d+ 页 ==)", all_md)
    page_parts = [p.strip() for p in page_parts if p.strip()]

    all_headers = None
    all_rows = []
    for part in page_parts:
        parsed = _parse_markdown_table(part)
        if not parsed:
            continue
        data = parsed[0]
        headers = data.get("headers") or []
        rows = data.get("rows") or []
        if not headers or not rows:
            continue
        if all_headers is None:
            all_headers = headers
        else:
            # 去掉续表重复表头（第一行与表头一致时跳过）
            if rows and len(rows[0]) == len(all_headers):
                _first_row = [str(c).strip().lower() for c in rows[0]]
                _header_cmp = [str(h).strip().lower() for h in all_headers]
                if _first_row == _header_cmp:
                    rows = rows[1:]
            # 列数对齐到第一段表头
            for row in rows:
                while len(row) < len(all_headers):
                    row.append("")
                if len(row) > len(all_headers):
                    overflow = [str(c).strip() for c in row[len(all_headers):] if str(c).strip()]
                    if overflow:
                        row[len(all_headers) - 1] = str(row[len(all_headers) - 1]) + "；" + "；".join(overflow)
                    row[:] = row[:len(all_headers)]
        all_rows.extend(rows)

    if all_headers is None:
        # 没有页标记拆分，直接解析整段
        parsed = _parse_markdown_table(all_md)
        if parsed and parsed[0].get("headers") and parsed[0].get("rows"):
            return {"headers": parsed[0]["headers"], "rows": parsed[0]["rows"]}
        return {"headers": [], "rows": []}

    print(f"  [确定性归并] 表{number} {len(all_rows)} 行 × {len(all_headers)} 列（{len(page_parts)} 段）", flush=True)
    return {"headers": all_headers, "rows": all_rows}


def _extract_table_from_ocr(block: Dict[str, str], ocr_md_by_page: Dict[str, str]) -> Dict[str, Any]:
    """从多页 OCR MD 中提取目标表格，按表号过滤后拼接合并。

    ocr_md_by_page: {页号: MD} —— OCR 只负责识别，按表号过滤是后处理。
    表名优先从 OCR MD 里的表标题行提取（比 _split_by_tables 的 title 更准确）。
    """
    number = block.get("number") or ""
    # 按表号从所有页 MD 中过滤出该表的 MD 片段
    target_mds = []
    ocr_title = ""
    for pg_str, md in sorted(ocr_md_by_page.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        target = _filter_md_by_table_number(md, number)
        if target:
            target_mds.append(f"== 第 {pg_str} 页 ==\n{target}")
            _TABLE_PAGE_MAP.setdefault(number, []).append(int(pg_str) if pg_str.isdigit() else 0)
            # 从 OCR MD 里提取表名（表标题行格式：表X.Y 表名）
            if not ocr_title:
                _title_re = re.compile(r"表\s*" + re.escape(number) + r"\s*[:：]?\s*(.+)")
                for line in target.split("\n"):
                    s = line.strip()
                    if s.startswith("|") or not s:
                        continue
                    m = _title_re.match(s)
                    if m:
                        _desc = m.group(1).strip()
                        if _desc and not _desc.startswith("(续)") and not _desc.startswith("（续）"):
                            ocr_title = _desc
                            break
    if not target_mds:
        raise RuntimeError(f"表{number} 在所有 OCR 页中未匹配到表格数据")
    ocr_md = "\n\n".join(target_mds)
    _ocr_rows = _count_md_data_rows(ocr_md)
    print(f"  [阶段日志] 表{number} OCR输入: {_ocr_rows} 行数据（{len(target_mds)} 页）", flush=True)
    merged = _merge_md_tables(ocr_title or number, number, [ocr_md])
    _merged_rows = len(merged.get("rows") or [])
    _merged_cols = len(merged.get("headers") or [])
    print(f"  [阶段日志] 表{number} 确定性归并输出: {_merged_rows} 行 × {_merged_cols} 列", flush=True)
    if _ocr_rows > 0 and _merged_rows < _ocr_rows:
        print(f"  [阶段日志] 表{number} ⚠️ 归并丢行: OCR {_ocr_rows} 行 → 归并 {_merged_rows} 行", flush=True)
    # 表名从 OCR MD 提取，没有则标记表名缺失
    table_name = _sanitize_table_name(f"表{number} {ocr_title}".strip()) if ocr_title else _sanitize_table_name(f"表{number} 表名缺失")
    if merged.get("headers") and merged.get("rows"):
        headers = [str(h).strip() for h in merged["headers"]]
        rows = [[("" if c is None else str(c)) for c in r] for r in merged["rows"]]
        return {"table_name": table_name, "table_number": number, "headers": headers, "rows": rows}
    parsed = _parse_markdown_table(ocr_md)
    if parsed:
        data = parsed[0]
        headers = [str(x).strip() for x in (data.get("headers") or [])]
        rows = [[("" if c is None else str(c)) for c in r] for r in (data.get("rows") or [])]
        if headers and rows:
            return {"table_name": table_name, "table_number": number, "headers": headers, "rows": rows}
    raise RuntimeError(f"表{number} OCR 归并失败")


def _split_long_md(md_text: str, max_chars: int = 6000) -> List[str]:
    if len(md_text) <= max_chars:
        return [md_text]
    lines = md_text.split("\n")
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for ln in lines:
        add = len(ln) + 1
        if cur and cur_len + add > max_chars and not ln.strip().startswith("|"):
            chunks.append("\n".join(cur))
            cur = [ln]
            cur_len = add
        else:
            cur.append(ln)
            cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def _table_to_markdown(headers: List[str], rows: List[List[str]]) -> str:
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for r in rows:
        cells = ["" if c is None else str(c).replace("|", "\\|") for c in r]
        while len(cells) < len(headers):
            cells.append("")
        lines.append("| " + " | ".join(cells[:len(headers)]) + " |")
    return "\n".join(lines)


def _reconstruct_md_from_text_block(title: str, number: str, content: str, pdf_path: str = "") -> str:
    if not content or not content.strip():
        return ""

    # 文本还原 MD 落盘缓存（与 OCR 缓存同目录，按表号命名）
    _cache_dir = None
    _cache_file = None
    if pdf_path:
        _pdf_p = Path(pdf_path)
        try:
            _size_tag = _pdf_p.stat().st_size
        except Exception:
            _size_tag = 0
        _cache_dir = _pdf_p.parent / "_ocr_cache"
        try:
            _cache_dir.mkdir(exist_ok=True)
        except Exception:
            _cache_dir = None
        if _cache_dir:
            _cache_file = _cache_dir / f"{_pdf_p.stem}[_{_size_tag}]_text_t{number}.md"
            try:
                if _cache_file.exists():
                    _cached = _cache_file.read_text(encoding="utf-8").strip()
                    if _cached:
                        print(f"  [文字还原] 表{number} 缓存命中", flush=True)
                        return _cached
            except Exception:
                pass

    chunks = _split_long_md(content, 6000) if len(content) > 6000 else [content]
    md_parts: List[str] = []
    for ci, ch in enumerate(chunks, 1):
        prompt = f"""你是标准规范类文档表格识别专家。下面是表格（表{number} {title}）从 PDF 文本层抽取出的文字片段，可能因转置、跨页、翻转页而错乱。请只做忠实还原，把片段还原成一段 Markdown 表格（| 分隔），不要 JSON、不要解释、不要代码围栏。
还原要求：
1. 先还原「表头字段 + 对应取值」的行列对应关系，表头列数与每行单元格数一致；
2. 有多少行就保持多少行，不删除、不合并、不新增序号或行；跨页拆分的内容补齐为一行；
3. 表头以片段中实际出现的表头文字为准，不预设列数、不套用模板；多级表头（父项-子项）按「父项｜子项」拼成完整列名；
4. 单元格内容逐字保留，数值、阈值、判据不得改写；看不清的保持原样，宁可保留空缺也不要臆测填充；
5. 忽略水印文字、页眉、页脚、页码；
6. 直接输出 Markdown 表格本身，第二行是分隔线（| --- | --- |），禁止 ``` 围栏。
文字片段如下：
---
{ch}
---"""
        for attempt in range(1, 4):
            try:
                response = call_tool("llm_generate", prompt=prompt, temperature=0.0, max_tokens=16000)
                if not isinstance(response, dict) or "error" in response:
                    raise RuntimeError(f"llm_generate 失败: {response!r}")
                raw = str(response.get("content") or "").strip()
                if not raw:
                    raise RuntimeError("llm_generate 返回空 content")
                parsed = _parse_markdown_table(raw)
                if not parsed:
                    raise RuntimeError(f"还原未输出可解析的 Markdown 表格: {raw[:300]!r}")
                md_parts.append(_table_to_markdown(
                    [str(x).strip() for x in (parsed[0].get("headers") or [])],
                    [[("" if c is None else str(c)) for c in r] for r in (parsed[0].get("rows") or [])],
                ))
                print(f"  [文字还原] 表{number} {title} 分段 {ci}/{len(chunks)} 完成")
                break
            except Exception as e:
                print(f"  [文字还原] 表{number} {title} 分段 {ci}/{len(chunks)} 第{attempt}/3 次失败: {e}")
                if attempt == 3:
                    return ""
    _result = "\n\n".join(md_parts)
    # 落盘缓存
    if _cache_file and _result:
        try:
            _cache_file.write_text(_result, encoding="utf-8")
            print(f"  [文字还原] 表{number} 缓存已落盘: {_cache_file.name}", flush=True)
        except Exception:
            pass
    return _result


def _extract_table_literal(block: Dict[str, str], pdf_path: str = "") -> Dict[str, Any]:
    title = block.get("title") or "未命名表"
    number = block.get("number") or ""
    content = block.get("content") or ""
    print(f"  [阶段日志] 表{number} 文本层输入: {len(content)} 字符", flush=True)
    # LLM 从文本还原 Markdown 表格（处理翻转/水印/乱序）
    md = _reconstruct_md_from_text_block(title, number, content, pdf_path=pdf_path)
    if not md:
        raise RuntimeError(f"表{number} 文本还原失败（LLM 返回空）")
    merged = _merge_md_tables(title, number, [md])
    _merged_rows = len(merged.get("rows") or [])
    _merged_cols = len(merged.get("headers") or [])
    print(f"  [阶段日志] 表{number} 确定性归并输出: {_merged_rows} 行 × {_merged_cols} 列", flush=True)
    table_name = _sanitize_table_name(f"表{number} {title}".strip() if number and title and title != f"表{number}" else (f"表{number}" if number else title))
    if merged.get("headers") and merged.get("rows"):
        headers = [str(h).strip() for h in merged["headers"]]
        rows = [[("" if c is None else str(c)) for c in r] for r in merged["rows"]]
        return {"table_name": table_name, "table_number": number, "headers": headers, "rows": rows}
    parsed = _parse_markdown_table(md)
    if parsed:
        data = parsed[0]
        headers = [str(x).strip() for x in (data.get("headers") or [])]
        rows = [[("" if c is None else str(c)) for c in r] for r in (data.get("rows") or [])]
        if headers and rows:
            return {"table_name": table_name, "table_number": number, "headers": headers, "rows": rows}
    raise RuntimeError(f"表{number} 文本归并失败")


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
        # 跳过纯数字列（序号/编号列），不做前向填充
        if _is_numeric_column(rows, ci):
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


def _split_stuck_headers(ti: Dict[str, Any]) -> Dict[str, Any]:
    """通用拆分多级表头展平时粘连的相邻列。

    LLM 展平两级表头时，经常把相邻列名黏成一列（如「AB」「CD」
    拼成「ABCD」）。这些粘连列导致列错位。

    本函数用通用算法检测并拆分粘连表头，不依赖具体业务词：
    1. 重复词粘连：表头含重复子串（如"ABABC"→去掉重复得到"ABC"）
    2. 数字+中文粘连：单元格值形如"1运行""3 某某"→拆为序号列+名称列
    3. 中文边界分割：连续中文中按已知表头片段匹配拆分
    """
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    if not headers or not rows:
        return ti

    def _dedup_repeated(h: str) -> str:
        """去掉表头中的重复子串：如"ABABC"→"ABC"。"""
        h = h.strip()
        if len(h) < 4:
            return h
        for prefix_len in range(2, len(h) // 2 + 1):
            prefix = h[:prefix_len]
            rest = h[prefix_len:]
            if rest.startswith(prefix):
                return prefix + rest[len(prefix):]
        return h

    def _find_stuck_pair(h: str, other_headers: list) -> list:
        """检测粘连表头能否拆为两个已知列名。

        在 other_headers 中找两个相邻列名拼起来等于 h 的情况。
        返回 [left, right] 或 None。
        """
        h = h.strip()
        for left in other_headers:
            left = str(left).strip()
            if not left or left == h:
                continue
            for right in other_headers:
                right = str(right).strip()
                if not right or right == left or right == h:
                    continue
                if left + right == h:
                    return [left, right]
        return None

    def _detect_number_prefix(cell: str) -> tuple:
        """检测单元格值是否以数字开头：如"1运行"→("1","运行")，"3 某某"→("3","某某")。"""
        cell = str(cell).strip()
        m = re.match(r"^(\d{1,4})[\s.．、]*([^.]*)$", cell)
        if m and m.group(2) and m.group(2).strip():
            return m.group(1), m.group(2).strip()
        return None

    new_headers = list(headers)
    new_rows = [list(r) for r in rows]
    split_count = 0

    for ci in range(len(new_headers) - 1, -1, -1):
        h = str(new_headers[ci]).strip()
        if not h or len(h) < 3:
            continue

        # 1) 去重复词粘连
        deduped = _dedup_repeated(h)
        if deduped != h:
            new_headers[ci] = deduped
            continue

        # 2) 检测数字+中文粘连：看数据行该列是否大量以数字开头
        if ci < len(new_rows) and new_rows:
            num_prefix_count = 0
            samples = []
            for row in new_rows[:min(10, len(new_rows))]:
                cell = str(row[ci]).strip() if ci < len(row) else ""
                result = _detect_number_prefix(cell)
                if result:
                    num_prefix_count += 1
                    samples.append(result)
            if num_prefix_count >= min(3, len(new_rows)):
                # 多数行以数字开头 → 拆为 序号列 + 名称列
                seq_name = "序号"
                name_name = h
                # 如果表头本身含中文前缀，用前缀做 seq_name
                _m = re.match(r"^([\u4e00-\u9fff]{1,4})(.*)", h)
                if _m and _m.group(2):
                    seq_name = _m.group(1)
                    name_name = _m.group(2)
                new_headers[ci] = seq_name
                new_headers.insert(ci + 1, name_name)
                for row in new_rows:
                    while len(row) < ci:
                        row.append("")
                    cell = str(row[ci]).strip() if ci < len(row) else ""
                    result = _detect_number_prefix(cell)
                    if result:
                        seq_val, name_val = result
                        row[ci] = seq_val
                        row.insert(ci + 1, name_val)
                    else:
                        row.insert(ci + 1, "")
                split_count += 1
                continue

        # 3) 在其他表头中找配对拆分
        other_headers = [str(x).strip() for j, x in enumerate(new_headers) if j != ci]
        pair = _find_stuck_pair(h, other_headers)
        if pair:
            left, right = pair
            new_headers[ci] = left
            new_headers.insert(ci + 1, right)
            for row in new_rows:
                cell = str(row[ci]).strip() if ci < len(row) else ""
                if left and cell.startswith(left):
                    row[ci] = left
                    row.insert(ci + 1, cell[len(left):].strip())
                else:
                    row.insert(ci + 1, "")
            split_count += 1

    if split_count > 0:
        print(f"  [表头拆分] 通用检测拆分 {split_count} 个粘连列（{len(new_rows)} 行）")
    result = dict(ti)
    result["headers"] = new_headers
    result["rows"] = new_rows
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
            # 右移检测：前导空列 → 左移（子列被拆成两列，前面多出空列导致后续整体右移）
            while len(row) > ncols and not str(row[0]).strip():
                row = row[1:]
                while len(row) < ncols:
                    row.append("")
                adjusted += 1
            if len(row) > ncols:
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


def _detect_transposed_table(ti: Dict[str, Any]) -> bool:
    """检测转置表格：第一行是纯数字递增序列（1, 2, 3, ...）。

    转置表格特征：原表头（字段名）在第一列，数据在后续列，
    第一行是编号 1 2 3 4 5... 对应原始行号。
    """
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    if not headers or not rows or len(rows) < 2 or len(headers) < 3:
        return False
    first_row = rows[0]
    nums = []
    for ci in range(len(first_row)):
        cell = str(first_row[ci]).strip() if ci < len(first_row) else ""
        try:
            nums.append(int(cell))
        except ValueError:
            return False
    if len(nums) < 3:
        return False
    # 第一行是 1 2 3 ... 递增序列
    return nums == list(range(1, len(nums) + 1))


def _transpose_table(ti: Dict[str, Any]) -> Dict[str, Any]:
    """转置表格：第一列变为新表头，其余行列互换。

    原表:
      [1, 2, 3]          原始行号
      [字段A, val1, val2]  ← 字段名在第一列
      [字段B, val3, val4]
    转置后:
      headers = [字段A, 字段B]
      rows = [[val1, val3], [val2, val4]]
    """
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    if not rows:
        return ti
    # 新表头 = 第一列各行值（跳过第一行的编号行）
    new_headers = []
    for ri in range(1, len(rows)):
        val = str(rows[ri][0]).strip() if rows[ri] and len(rows[ri]) > 0 else ""
        new_headers.append(val)
    # 新行 = 原第一行编号之后的每列变成一行
    new_rows = []
    for ci in range(1, len(headers)):
        new_row = []
        for ri in range(1, len(rows)):
            new_row.append(str(rows[ri][ci]).strip() if ci < len(rows[ri]) else "")
        new_rows.append(new_row)
    print(f"  [转置] {len(rows)}行×{len(headers)}列 → {len(new_rows)}行×{len(new_headers)}列", flush=True)
    return {
        "headers": new_headers,
        "rows": new_rows,
        "table_name": ti.get("table_name", ""),
        "table_number": ti.get("table_number", ""),
    }


def _is_numeric_column(rows: list, ci: int, min_ratio: float = 0.6) -> bool:
    """检测某列是否为纯数字列（序号/编号列）。"""
    if not rows:
        return False
    num_count = 0
    total = 0
    for row in rows[:20]:
        if ci >= len(row):
            continue
        total += 1
        cell = str(row[ci]).strip()
        try:
            int(cell)
            num_count += 1
        except ValueError:
            pass
    return total > 0 and num_count / total >= min_ratio


def _table_rows_to_records(ti: Dict[str, Any], source_document: str) -> List[Dict[str, Any]]:
    _in_rows = len(ti.get("rows") or [])
    _in_cols = len(ti.get("headers") or [])
    _tbl_num = ti.get("table_number") or ""
    print(f"  [阶段日志] 表{_tbl_num} 后处理输入: {_in_rows} 行 × {_in_cols} 列", flush=True)
    ti = _filter_polluted_rows(ti)
    _after_filter = len(ti.get("rows") or [])
    if _after_filter < _in_rows:
        print(f"  [阶段日志] 表{_tbl_num} ⚠️ _filter_polluted_rows 丢行: {_in_rows} → {_after_filter}", flush=True)
    ti = _clean_placeholder_cells(ti)
    ti = _forward_fill_merged_cells(ti)
    ti = _split_stuck_headers(ti)
    ti = _merge_duplicate_headers(ti)
    _after_merge = len(ti.get("rows") or [])
    _after_merge_cols = len(ti.get("headers") or [])
    if _after_merge != _after_filter or _after_merge_cols != _in_cols:
        print(f"  [阶段日志] 表{_tbl_num} 前填充/表头拆分/子列合并后: {_after_merge} 行 × {_after_merge_cols} 列", flush=True)
    ti = _normalize_column_count(ti)
    # 转置检测：第一行是 1 2 3... 递增序列且行数 < 列数 → 行列互换
    if _detect_transposed_table(ti):
        ti = _transpose_table(ti)
    # 表头归一化：去除字间空格（如「劣 化 情 况」→「劣化情况」），统一跨表列名
    ti["headers"] = [re.sub(r"\s+", "", str(h)) for h in (ti.get("headers") or [])]
    headers = ti.get("headers") or []
    rows = ti.get("rows") or []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 检测数字列（序号/编号列），保持字符串格式避免 Excel 自动转数字
    numeric_col_indices = set()
    for ci in range(len(headers)):
        if _is_numeric_column(rows, ci):
            numeric_col_indices.add(ci)
    records = []
    for row in rows:
        rec = {}
        for ci, h in enumerate(headers):
            val = "" if ci >= len(row) or row[ci] is None else str(row[ci])
            # 数字列强制保持字符串格式
            if ci in numeric_col_indices and val:
                val = val.strip()
            rec[str(h)] = val
        rec["source_document"] = source_document
        rec["updated_at"] = now
        records.append(rec)
    return records


def _apply_row_col_fixes(grouped: Dict[str, List[Dict]], issues: List[tuple], source_text: str, table_original_titles: Dict[str, str] = None, pdf_path: str = "") -> int:
    """按行/列修复 check_skill_rules 发现的问题（不整表重写）。

    根据 rule_id 和 issue 描述定位问题行列，只修有问题的单元格：
    - SKILL-DQ-001 不得丢失行和列：列数归一（补空/合并多余列）+ Vision 重新 OCR 补行
    - SKILL-DQ-003 合并单元格补全：重新执行前向填充
    - SKILL-DQ-004 子列拼接：重新执行重复列名合并
    - SKILL-DQ-005 列值与表头语义一致：Vision 重新 OCR 整页后按行回填
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

        # SKILL-DQ-001: 不得丢失行和列 → 列数归一（补空/合并多余列）+ LLM 补丢失列
        if "SKILL-DQ-001" in rule_ids:
            _adjusted = 0
            ncols = len(headers)
            for rec in recs:
                while len(list(rec.keys())) < ncols:
                    rec[f"col_{len(rec)}"] = ""
                    _adjusted += 1
                if len(list(rec.keys())) > ncols:
                    all_keys = list(rec.keys())
                    overflow_keys = all_keys[ncols:]
                    overflow_vals = [str(rec[k]).strip() for k in overflow_keys if str(rec.get(k, "")).strip()]
                    if overflow_vals:
                        last_key = headers[ncols - 1]
                        old_val = str(rec.get(last_key, ""))
                        rec[last_key] = old_val + "；" + "；".join(overflow_vals) if old_val else "；".join(overflow_vals)
                    for k in overflow_keys:
                        del rec[k]
                    _adjusted += 1
            if _adjusted:
                print(f"  [修复] 表「{tbl}」SKILL-DQ-001 列数归一 {_adjusted} 行")
                fixed_count += _adjusted
            # 列数归一处理不了"丢失整列"的情况，统一在循环末尾调 LLM 修复（每表每轮仅一次）

        # SKILL-DQ-003: 合并单元格补全 → 直接对 issue 指定列做前向填充
        # 不调 _forward_fill_merged_cells（它有 10% 空值率下限，check_rules 5% 就报问题，阈值不匹配导致修复 0 处）
        if "SKILL-DQ-003" in rule_ids:
            recs = grouped.get(tbl, recs)
            fix_cols = set()
            for iss in tbl_issues:
                if iss.get("rule_id") == "SKILL-DQ-003":
                    col = iss.get("column", "")
                    if col:
                        fix_cols.add(col)
            filled = 0
            for col in fix_cols:
                if col not in headers:
                    continue
                last_val = ""
                for rec in recs:
                    val = str(rec.get(col, "")).strip()
                    if val:
                        last_val = val
                    elif last_val:
                        rec[col] = last_val
                        filled += 1
            if filled:
                print(f"  [修复] 表「{tbl}」SKILL-DQ-003 前向填充 {filled} 个空值")
                fixed_count += filled

        # SKILL-DQ-004: 子列拼接 → 重新执行重复列名合并
        if "SKILL-DQ-004" in rule_ids:
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
                print(f"  [修复] 表「{tbl}」SKILL-DQ-004 子列合并 {len(headers)}→{len(new_headers)} 列")
                fixed_count += abs(len(headers) - len(new_headers))

        # SKILL-DQ-005（列错位）与 SKILL-DQ-001（丢行）调同通道 LLM 重新还原后按行回填。
        # 收敛保护：问题数 ≥5 的表只修一次（LLM 修复大概率引入新问题，反复修不如保留）
        if ("SKILL-DQ-005" in rule_ids or "SKILL-DQ-001" in rule_ids) and len(tbl_issues) < 5:
            _llm_fixed = _llm_fix_rows(tbl, recs, tbl_issues, source_text, pdf_path)
            if _llm_fixed:
                fixed_count += _llm_fixed
        elif "SKILL-DQ-005" in rule_ids or "SKILL-DQ-001" in rule_ids:
            print(f"  [修复] 表「{tbl}」问题数 {len(tbl_issues)} ≥5，跳过 LLM 修复（收敛保护）")

    return fixed_count


def _locate_source_snippet(source_text: str, table_name: str, headers: list, max_len: int = 4000) -> str:
    """从源文档全文中提取与目标表对应的片段（供 LLM 按行修复时参考）。

    策略：
    1. 用表名在全文中定位，取表标题前后片段
    2. 找不到表名时，用表头列名关键词在全文中搜索
    3. 都找不到时回退到全文前 3000 字符
    """
    if not source_text:
        return ""
    text = source_text

    tn = str(table_name or "").strip()
    if tn:
        for pattern in [tn, re.sub(r'[/\\|:*?"<>]+', "_", tn)]:
            idx = text.find(pattern)
            if idx >= 0:
                start = max(0, idx - 200)
                end = min(len(text), idx + max_len)
                return text[start:end]

    if headers:
        keywords = [str(h).strip() for h in headers if len(str(h).strip()) >= 2]
        for kw in keywords[:3]:
            idx = text.find(kw)
            if idx >= 0:
                start = max(0, idx - 500)
                end = min(len(text), idx + max_len)
                return text[start:end]

    return text[:3000]


# Vision 重扫结果缓存：同一次运行内多张问题表共享一轮重扫的原始 OCR 结果
_RESUME_OCR_CACHE = {"pdf_path": "", "pages": None, "raw_by_page": {}}

# 表号→页码映射（提取阶段记录，修复阶段用它收窄重扫范围：表A.2 问题只扫 p11-13，不扫全部 17 页）
_TABLE_PAGE_MAP: Dict[str, List[int]] = {}


def _llm_fix_rows(tbl: str, recs: List[Dict], tbl_issues: List[Dict], source_text: str, pdf_path: str = "") -> int:
    """Vision 重新 OCR 整页后按序号对比回填有问题的行。

    方案 1：重新 OCR 表格所在页 → 得到完整正确的 Markdown 表格 →
    按序号/行号逐行对比 → 只替换有差异的单元格，不整表替换。

    比给 LLM 文字描述让它猜准确得多——Vision 直接看图片重新识别。
    """
    if not recs or not pdf_path:
        return 0
    headers = list(recs[0].keys())
    source_doc = recs[0].get("source_document", "")
    updated_at = recs[0].get("updated_at", "")

    _llm_issues = [iss for iss in tbl_issues if str(iss.get("severity", "")).strip().lower() in ("error", "critical")]
    if not _llm_issues:
        return 0

    # 只有"表X.Y"格式的文档表格才做 Vision 重扫；正文规则表（LLM 从正文提取，无对应图片）
    # 重扫全部图片页也匹配不到内容，纯浪费几分钟——直接跳过。
    if not re.search(r"表\s*[A-Za-z]?\s*\.?\s*\d+", tbl):
        print(f"  [修复] 表「{tbl}」非文档表格（正文规则表），跳过 Vision 重扫")
        return 0

    # 找到序号列（数字列）
    seq_col = -1
    for ci, h in enumerate(headers):
        if _is_numeric_column([list(r.values()) for r in recs[:20]], ci):
            seq_col = ci
            break

    # 确定表格在 PDF 哪些页：用提取阶段记录的表号→页码映射收窄
    # 无映射记录时（OCR 通道表未记录页码）用 _ocr_table_on_demand 统一处理（含磁盘缓存）
    tbl_number = ""
    m = re.search(r"表\s*([A-Za-z]?\s*\.?\s*\d+(?:[.．]\d+)?)", tbl)
    if m:
        tbl_number = m.group(1).strip()

    # 用 _ocr_table_on_demand 获取该表的 OCR 数据（复用磁盘缓存，不重复扫）
    print(f"  [修复] 表「{tbl}」按需 OCR（表号 {tbl_number}）...", flush=True)
    ocr_md = _ocr_table_on_demand(pdf_path, tbl_number, tbl)
    if not ocr_md:
        print(f"  [修复] 表「{tbl}」OCR 未提取到表格数据，跳过")
        return 0

    # 确定性归并 OCR 结果
    merged = _merge_md_tables(tbl, tbl_number, [ocr_md])
    new_headers = merged.get("headers") or []
    new_rows = merged.get("rows") or []
    if not new_headers or not new_rows:
        print(f"  [修复] 表「{tbl}」OCR 归并失败")
        return 0

    print(f"  [修复] 表「{tbl}」OCR 得到 {len(new_rows)} 行 × {len(new_headers)} 列")
    # 后处理：前向填充 + 表头拆分 + 子列合并
    ti = {"headers": new_headers, "rows": new_rows}
    ti = _filter_polluted_rows(ti)
    ti = _clean_placeholder_cells(ti)
    ti = _forward_fill_merged_cells(ti)
    ti = _split_stuck_headers(ti)
    ti = _merge_duplicate_headers(ti)
    new_headers = ti.get("headers") or []
    new_rows = ti.get("rows") or []

    # 把新 OCR 结果转成 records
    new_recs = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in new_rows:
        rec = {}
        for ci, h in enumerate(new_headers):
            rec[str(h)] = str(row[ci]) if ci < len(row) else ""
        rec["source_document"] = source_doc
        rec["updated_at"] = now
        new_recs.append(rec)

    # 按序号/行号对比回填：只替换有差异的单元格
    total_fixed = 0
    if seq_col >= 0 and new_headers:
        # 找新数据中的序号列
        new_seq_col = -1
        for ci, h in enumerate(new_headers):
            if str(h) == str(headers[seq_col]):
                new_seq_col = ci
                break
        if new_seq_col >= 0:
            new_by_seq = {}
            for rec in new_recs:
                seq = str(rec.get(new_headers[new_seq_col], "")).strip()
                if seq:
                    new_by_seq[seq] = rec
            for rec in recs:
                seq = str(rec.get(headers[seq_col], "")).strip()
                if seq and seq in new_by_seq:
                    new_rec = new_by_seq[seq]
                    for h in headers:
                        if h in ("source_document", "updated_at"):
                            continue
                        old_val = str(rec.get(h, "")).strip()
                        # 在新数据中找对应列
                        new_val = ""
                        if h in new_rec:
                            new_val = str(new_rec.get(h, "")).strip()
                        elif str(h) in [str(nh) for nh in new_headers]:
                            # 模糊匹配列名
                            for nh in new_headers:
                                if str(nh) == str(h):
                                    new_val = str(new_rec.get(nh, "")).strip()
                                    break
                        if new_val and new_val != old_val:
                            rec[h] = new_val
                            total_fixed += 1
    else:
        # 无序号列：按行号对比
        for ri, new_rec in enumerate(new_recs):
            if ri >= len(recs):
                # 新行，追加
                recs.append(new_rec)
                total_fixed += 1
                continue
            for h in headers:
                if h in ("source_document", "updated_at"):
                    continue
                old_val = str(recs[ri].get(h, "")).strip()
                new_val = str(new_rec.get(h, "")).strip() if h in new_rec else ""
                if new_val and new_val != old_val:
                    recs[ri][h] = new_val
                    total_fixed += 1
        # 新 OCR 有更多行 → 追加
        if len(new_recs) > len(recs):
            for ri in range(len(recs), len(new_recs)):
                recs.append(new_recs[ri])
                total_fixed += 1

    if total_fixed:
        print(f"  [修复] 表「{tbl}」Vision 重新 OCR 后回填 {total_fixed} 处")
    else:
        print(f"  [修复] 表「{tbl}」Vision 重新 OCR 后无差异")
    return total_fixed


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


_TIME_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")


def _cleanup_records(records: List[Dict]) -> List[Dict]:
    """写入前的确定性格式归一化（不做内容级修复）。

    - 去重：LLM 行级修复可能对同一 rule_code+rule_name 产生冗余副本，保留内容最完整的一行；
    - category 众数归一：组内 category 不一致时取出现最多的值（剔除 LLM 幻觉引入的少数派值）；
    - 时间戳串列清理：format_regex/category/applicable_fields 中的纯时间戳值清空，
      check_logic 中的时间戳子串删除（防止 updated_at 串入内容列）。
    """
    if not records:
        return records
    headers = list(records[0].keys())
    key_cols = [h for h in ("rule_code", "rule_name") if h in headers]
    if not key_cols:
        return records

    groups = {}
    order = []
    for rec in records:
        key = tuple(str(rec.get(c, "")).strip() for c in key_cols)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(rec)

    cleaned = []
    for key in order:
        cands = groups[key]
        if "check_logic" in headers:
            best = max(cands, key=lambda r: len(str(r.get("check_logic", ""))))
        else:
            best = max(cands, key=lambda r: len(json.dumps(r, ensure_ascii=False, default=str)))
        rec = {k: best.get(k, "") for k in headers}
        if "category" in headers:
            cats = [str(r.get("category", "")).strip() for r in cands if str(r.get("category", "")).strip()]
            if cats:
                rec["category"] = max(set(cats), key=cats.count)
        for h in headers:
            val = str(rec.get(h, ""))
            if not val:
                continue
            if h in ("format_regex", "category", "applicable_fields"):
                if _TIME_TS_RE.fullmatch(val.strip()):
                    rec[h] = ""
            elif h == "check_logic":
                rec[h] = _TIME_TS_RE.sub("", val).strip()
        cleaned.append(rec)
    if len(cleaned) != len(records):
        print(f"  [清理] 去重 {len(records)} → {len(cleaned)} 行")
    return cleaned


def _write_records(ds_id: str, table_name: str, records: List[Dict], if_table_exists: str = "replace") -> int:
    records = _cleanup_records(records)
    if not records:
        return 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    batch_size = 400
    batches = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
    total, batch_total = len(records), len(batches)
    print(f"写入表 {table_name}，共 {total} 条，分 {batch_total} 批")
    print(f"  正在写入第 1/{batch_total} 批 ({len(batches[0])} 条，strategy={if_table_exists})...")
    result = call_tool("write_data", datasource_id=ds_id, table_name=table_name, records=batches[0], if_table_exists=if_table_exists)
    if not result.get("success"):
        raise RuntimeError(f"写入失败(表 {table_name}): {result.get('message') or result.get('error') or result}")
    if len(batches) > 1:
        def _append(batch_num, batch):
            print(f"  正在写入第 {batch_num}/{batch_total} 批 ({len(batch)} 条)...")
            r = call_tool("write_data", datasource_id=ds_id, table_name=table_name, records=batch, if_table_exists="append")
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
    # 总耗时硬保护：沙箱硬上限 1800s，预留 120s 写结果，剩余时间不够跑完一轮自检+修复就提前收尾
    _t0 = time.time()
    _TIME_BUDGET = 1680  # 1800 - 120s 余量

    def _elapsed() -> int:
        return int(time.time() - _t0)

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

        # fitz 提取纯文本（字符顺序正确，不依赖 pdfplumber）
        _pdf_res = call_tool("read_file", path=path)
        if not isinstance(_pdf_res, dict):
            _pdf_res = {}
        text = str(_pdf_res.get("content") or "")
        page_texts = _pdf_res.get("page_texts") or []
        source_text_by_path[path] = text
        print(f"  文档文本总长 {len(text)} 字符")

        # 统一文本切分：按表标题切分文本块，合并续表
        blocks = _merge_blocks_by_number(_split_by_tables(text))
        print(f"  [切分] 共 {len(blocks)} 个块")

        # 分类：正文 vs 表格块（所有表块统一走 OCR 通道）
        body_parts, table_blocks = [], []
        for b in blocks:
            if (b.get("title") or "正文") == "正文":
                body_parts.append(b.get("content") or "")
            else:
                table_blocks.append(b)

        # 所有表块走 OCR 通道（每页只 OCR 一次，结果落盘缓存）
        _table_numbers = [b.get("number") for b in table_blocks if b.get("number")]
        if _table_numbers:
            print(f"  [OCR] {len(table_blocks)} 张表，批量扫描所需页...", flush=True)
            _ocr_md_cache = _scan_pages_for_tables(path, _table_numbers)
        else:
            _ocr_md_cache = {}

        _failed_tables = []
        def _process_table(b):
            number = b.get("number") or ""
            try:
                if _ocr_md_cache:
                    ti = _extract_table_from_ocr(b, _ocr_md_cache)
                else:
                    print(f"  [表格] 表{number} OCR 缓存为空，跳过", flush=True)
                    ti = {"table_name": _sanitize_table_name(f"表{number} {b.get('title', '')}".strip()), "headers": [], "rows": []}
                return {"table_name": ti["table_name"], "records": _table_rows_to_records(ti, Path(path).name), "title": b.get("title"), "number": number}
            except Exception as e:
                import traceback as _tb
                _full_err = _tb.format_exc()
                print(f"  [表格] 表{number} 提取失败: {e}\n{_full_err}", flush=True)
                _failed_tables.append((number, str(e)))
                return {"table_name": _sanitize_table_name(f"表{number} {b.get('title', '')}".strip()), "records": [], "title": b.get("title"), "number": number}

        if table_blocks:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            print(f"  [表格] 并发还原 {len(table_blocks)} 张表...")
            results_by_idx = {}
            with ThreadPoolExecutor(max_workers=3) as executor:
                futs = {executor.submit(_process_table, b): i for i, b in enumerate(table_blocks)}
                for fut in as_completed(futs):
                    i = futs[fut]
                    r = fut.result()
                    if r is None:
                        continue
                    results_by_idx[i] = r
                    print(f"  [表格] 完成 {len(results_by_idx)}/{len(table_blocks)}: 「{r['table_name']}」{len(r['records'])} 行")
            for i in range(len(table_blocks)):
                r = results_by_idx.get(i)
                if not r:
                    continue
                _tbl_name = r["table_name"]
                _new_recs = r["records"]
                if _tbl_name in table_records_map:
                    _existing = table_records_map[_tbl_name]
                    _seen_keys = set()
                    for rec in _existing:
                        _key = tuple(str(v or "") for v in rec.values())
                        _seen_keys.add(_key)
                    _deduped = []
                    for rec in _new_recs:
                        _key = tuple(str(v or "") for v in rec.values())
                        if _key not in _seen_keys:
                            _seen_keys.add(_key)
                            _deduped.append(rec)
                    if _deduped:
                        _existing.extend(_deduped)
                        print(f"  [去重] 表「{_tbl_name}」续表合并：已有 {len(_existing) - len(_deduped)} 行，新增 {len(_deduped)} 行（去重 {len(_new_recs) - len(_deduped)} 行）")
                else:
                    table_records_map[_tbl_name] = _new_recs
                _orig_title = ""
                if r.get("number") and r.get("title"):
                    _orig_title = f"表{r['number']} {r['title']}".strip()
                elif r.get("title"):
                    _orig_title = r["title"]
                if _orig_title and _orig_title != r["table_name"]:
                    _table_original_titles[r["table_name"]] = _orig_title

        body_text = "\n".join(p for p in body_parts if p.strip()).strip()
        # 合并 PDF 提取产生的行内软换行，避免句末被换行拆散导致提取内容截断
        body_text = _normalize_pdf_text(body_text)
        if body_text and _elapsed() <= _TIME_BUDGET - 600:
            schema_plan = _analyze_document_structure(body_text)
            main_tbl = schema_plan.get("main_table") or "正文规则"
            print(f"  [表结构] 主表「{main_tbl}」+ {len(schema_plan.get('tables') or [])} 张子表")
            try:
                entries = _extract_rules_from_text(body_text, schema_plan=schema_plan)
            except Exception as _e:
                # 正文 LLM 提取超时/失败不阻塞核心结果（附录表格）落盘，
                # 保留空正文规则，正文规则可后续单独补齐。
                print(f"  [警告] 正文规则提取失败，跳过（附录表格不受影响）: {_e}", flush=True)
                entries = []
            for e in entries:
                e["source_document"] = Path(path).name
            all_entries.extend(entries)
            print(f"  从 {Path(path).name} 正文提取到 {len(entries)} 条规则")
        elif body_text:
            print(f"  [跳过正文提取] 已用时 {_elapsed()}s，剩余时间不足 600s，优先落盘附录表格", flush=True)

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

    # ===== 写入后自检（单轮终态：检查 → 确定性修复 → 重写修过的表 → 返回，不再循环重跑） =====
    # 设计变更：不再做「自检→修复→再自检」多轮循环和 Vision 重扫修复——
    # 1) 多轮重检 + Vision 重扫（豆包 3-4 分钟/页）在 1800s 沙箱预算内跑不完
    # 2) 脚本返回 success=False 会让 Agent 外层把整个 main 再跑一遍（反复执行打转的根源）
    # 3) OCR 质量提升后结构性错误已少，确定性修复（秒级）足够处理列数/前向填充类问题
    # 残留问题以 warnings 带出，success=True 终态返回。
    _src_text_check = _src_text or ""
    _all_check_issues = []
    _tables_to_check = {t for t in grouped.keys() if re.search(r"表\s*[A-Za-z]?\s*\.?\s*\d+", t)}
    print(f"[自检] 待检查 {len(_tables_to_check)} 张文档表格（跳过 {len(grouped) - len(_tables_to_check)} 张正文规则表）")

    def _check_one(tbl):
        # 从实际写入的数据源读回数据检查（不检查内存中的 grouped，避免内存与实际写入不一致）
        print(f"[自检] 开始检查「{tbl}」...", flush=True)
        _qr = call_tool("query_data", datasource_id=target_ds_id, table_name=tbl)
        if not isinstance(_qr, dict) or not _qr.get("data"):
            print(f"[自检] 「{tbl}」读回数据为空，跳过", flush=True)
            return tbl, []
        _data = _qr["data"]
        headers = list(_data[0].keys()) if _data else []
        rows = [[str(r.get(h, "") or "") for h in headers] for r in _data]
        print(f"[自检] 「{tbl}」读回 {len(rows)} 行 × {len(headers)} 列", flush=True)
        _src_snippet = _locate_source_snippet(_src_text_check, tbl, headers) if _src_text_check else ""
        # 直接调 check_rules（本地函数，不走 call_tool HTTP）
        _issues = []
        try:
            _raw_issues = check_rules(headers, rows, _src_snippet, tbl)
            for _iss in _raw_issues:
                if str(_iss.get("severity", "")).strip().lower() in ("error", "critical"):
                    _issues.append((tbl, _iss))
        except Exception as _ce:
            print(f"[自检] 「{tbl}」check_rules 调用异常: {_ce}", flush=True)
        print(f"[自检] 「{tbl}」检查完成：{len(_issues)} 个问题", flush=True)
        return tbl, _issues

    if _tables_to_check and _elapsed() <= _TIME_BUDGET - 300:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        _check_done = 0
        with ThreadPoolExecutor(max_workers=4) as _cex:
            _cfuts = {_cex.submit(_check_one, t): t for t in _tables_to_check}
            for _cfut in as_completed(_cfuts):
                _tbl_checked, _tbl_issues = _cfut.result()
                _check_done += 1
                _all_check_issues.extend(_tbl_issues)
                print(f"[自检] 进度 {_check_done}/{len(_tables_to_check)}", flush=True)
    elif _tables_to_check:
        print(f"[自检] 剩余时间不足（已用 {_elapsed()}s / 预算 {_TIME_BUDGET}s），跳过自检直接收尾", flush=True)

    _warnings = []
    if _all_check_issues:
        print(f"[自检] 发现 {len(_all_check_issues)} 个问题：")
        for tbl, iss in _all_check_issues:
            print(f"  [{iss.get('severity','?')}] {iss.get('rule_id','')} 表「{tbl}」: {iss.get('description','')}")
        # 从数据源读回实际数据修复（不操作内存 grouped，避免与实际写入不一致）
        _fix_budget = _TIME_BUDGET - _elapsed()
        _modified_tables = {tbl for tbl, _ in _all_check_issues}
        if _fix_budget < 300:
            print(f"[自检] 剩余 {_fix_budget}s 不足 LLM 修复，仅做确定性修复", flush=True)
            _fixed_count = _apply_row_col_fixes(grouped, _all_check_issues, _src_text, _table_original_titles, "")
        else:
            _fixed_count = _apply_row_col_fixes(grouped, _all_check_issues, _src_text, _table_original_titles, paths[0] if paths else "")
        print(f"[自检] 修复 {_fixed_count} 处")
        # 修复后只重写修过的表（一次，不再重新检查）
        if _fixed_count > 0:
            for tbl in _modified_tables:
                recs = grouped.get(tbl, [])
                if recs:
                    print(f"[自检] 重新写入表「{tbl}」({len(recs)} 条)")
                    _write_records(target_ds_id, tbl, recs, "overwrite")
        # 残留问题 → warnings（不再作为 success=False 触发外层 Agent 重跑）
        _warnings = [f"[{iss.get('rule_id','')}] 表「{tbl}」: {iss.get('description','')}" for tbl, iss in _all_check_issues[:10]]

    print("[自检] 完成")
    if _failed_tables:
        _fail_warnings = [f"表「{num}」提取失败: {err}" for num, err in _failed_tables]
        _warnings = (_warnings or []) + _fail_warnings
        print(f"[警告] {len(_failed_tables)} 张表提取失败: {[num for num, _ in _failed_tables]}", flush=True)
    return {"success": not _failed_tables, "warnings": _warnings, "extracted_rules": len(all_entries), "total_rules_written": written_total, "target_table": target_table_name, "target_datasource": target_datasource_name, "tables_written": {tbl: len(recs) for tbl, recs in grouped.items()}}


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


# ==================== 技能专属规则检查（确定性） ====================
# 自检和 Inspector 的 check_skill_rules 工具都调这个函数
# rules.md 定义的 4 条 SKILL-DQ 规则全部确定性检查，不走 LLM 主观判断

def check_rules(headers: List[str], rows: List[List[str]], source_text: str = "", table_name: str = "") -> List[Dict[str, Any]]:
    """技能专属规则检查（确定性）。

    Args:
        headers: 表头列表
        rows: 数据行列表（每行是 List[str]，与 headers 列数对齐）
        source_text: 源文档文本（可选，用于行数对比）
        table_name: 表名

    Returns:
        issues 列表，每条含 rule_id/severity/column/row/description/suggestion
    """
    issues = []
    if not headers or not rows:
        return issues

    ncols = len(headers)

    # SKILL-DQ-001: 不得丢失行和列
    # 1a. 列数不一致
    for ri, row in enumerate(rows):
        if len(row) != ncols:
            issues.append({
                "rule_id": "SKILL-DQ-001",
                "severity": "error",
                "column": "",
                "row": ri + 1,
                "description": f"第 {ri+1} 行列数 {len(row)} 与表头列数 {ncols} 不一致",
                "suggestion": "检查该行是否有多余或缺失的子列",
            })

    # 1b. 截断检测：单元格以省略号/非终结词结尾
    _TRUNC_ENDINGS = ("…", "...", "，", "、", "；", "：", "的", "和", "与", "或", "及", "等")
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            val = str(val or "").strip()
            if len(val) >= 30 and val.endswith(_TRUNC_ENDINGS):
                issues.append({
                    "rule_id": "SKILL-DQ-001",
                    "severity": "error",
                    "column": headers[ci] if ci < ncols else f"col_{ci}",
                    "row": ri + 1,
                    "description": f"第 {ri+1} 行列 '{headers[ci]}' 疑似内容截断（以'{val[-3:]}'结尾）",
                    "suggestion": "对照源文档补齐完整内容",
                })

    # SKILL-DQ-003: 合并单元格列必须补全列值
    # 严肃规则表格不允许空值——非数字列只要有 1 个空值就报
    for ci in range(ncols):
        col_vals = [str(row[ci]).strip() if ci < len(row) else "" for row in rows]
        non_empty = [v for v in col_vals if v]
        if not non_empty or len(rows) < 3:
            continue
        empty_ratio = 1.0 - len(non_empty) / len(col_vals)
        if empty_ratio <= 0:
            continue
        # 跳过纯数字列（序号/编号列）
        num_count = sum(1 for v in non_empty if v.replace(".", "").replace("-", "").isdigit())
        if non_empty and num_count / len(non_empty) > 0.8:
            continue
        empty_rows = [ri + 1 for ri, v in enumerate(col_vals) if not v]
        issues.append({
            "rule_id": "SKILL-DQ-003",
            "severity": "error",
            "column": headers[ci] if ci < ncols else f"col_{ci}",
            "row": empty_rows[0] if empty_rows else 0,
            "description": f"列 '{headers[ci]}' 有 {len(empty_rows)} 个空值（空值率 {empty_ratio*100:.0f}%），疑似合并单元格未回填。空值行: {empty_rows[:10]}",
            "suggestion": "对该列执行前向填充：空值用上方最近非空值补全",
        })

    # SKILL-DQ-004: 子列必须按行拼接（重复列名检测）
    col_positions = {}
    for ci, h in enumerate(headers):
        h_clean = str(h).strip()
        if h_clean:
            col_positions.setdefault(h_clean, []).append(ci)
    dup_groups = {h: positions for h, positions in col_positions.items() if len(positions) > 1}
    for h, positions in dup_groups.items():
        issues.append({
            "rule_id": "SKILL-DQ-004",
            "severity": "error",
            "column": h,
            "row": 0,
            "description": f"列名 '{h}' 重复 {len(positions)} 次（列号: {positions}），子列未拼接",
            "suggestion": "将重复列内容按行用分号拼接合并为一列",
        })

    # SKILL-DQ-005: 列数结构一致性（与 DQ-001 列数检查相同，单独标记）
    for ri, row in enumerate(rows):
        if len(row) != ncols:
            issues.append({
                "rule_id": "SKILL-DQ-005",
                "severity": "error",
                "column": "",
                "row": ri + 1,
                "description": f"第 {ri+1} 行列数 {len(row)} 与表头列数 {ncols} 不一致",
                "suggestion": "补空列或合并多余列到最后一列",
            })

    return issues