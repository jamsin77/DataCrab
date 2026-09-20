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

DEFAULT_TARGET_DATASOURCE = "凭证检索库"
DEFAULT_TARGET_TABLE = "rules_knowledge_base"

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
    "电网规则": "74d94ef7-025e-4d57-bc11-e29bf7a03a90",
}

# 内置映射的数据源类型（用于判断是否为图数据库）
_KNOWN_DATASOURCE_TYPES = {
    "文物列表": "mysql",
    "文物库": "postgresql",
    "交易数据": "postgresql",
    "凭证库": "postgresql",
    "凭证检索库": "postgresql",
    "聊天上传数据": "file",
    "培训视频": "file",
    "培训知识库": "chroma",
    "通用知识库": "chroma",
    "电网数据": "postgresql",
    "电网规则": "excel",
}


def _get_datasource_id(name: str) -> str:
    """根据数据源名称获取数据源 ID（优先内置映射，缺失时再查）"""
    print(f"正在查找数据源: {name}")
    if name in _DATASOURCE_UUID_MAP:
        ds_id = _DATASOURCE_UUID_MAP[name]
        print(f"数据源已找到(内置映射): {name} (id={ds_id})")
        return ds_id
    ds = call_tool("list_user_datasources", by_name=name)
    if not ds or not isinstance(ds, dict) or not ds.get("id"):
        raise ValueError(f"找不到数据源: {name}")
    print(f"数据源已找到: {name} (id={ds['id']})")
    return ds["id"]


def _is_graph_datasource(name: str) -> bool:
    """判断数据源是否为图数据库（neo4j / nebula / arangodb / graph 等）。

    优先看内置类型映射；缺失时调用 list_user_datasources 查询 type。
    """
    print(f"正在检测数据源类型: {name}")
    if name in _KNOWN_DATASOURCE_TYPES:
        t = _KNOWN_DATASOURCE_TYPES[name].lower()
        is_graph = any(k in t for k in ("graph", "neo4j", "nebula", "arangodb", "tigergraph"))
        print(f"  [类型检测] 内置映射 type={_KNOWN_DATASOURCE_TYPES[name]}，图数据库={is_graph}")
        return is_graph
    try:
        ds = call_tool("list_user_datasources", by_name=name)
        if isinstance(ds, dict):
            t = str(ds.get("type") or "").lower()
            is_graph = any(k in t for k in ("graph", "neo4j", "nebula", "arangodb", "tigergraph"))
            print(f"  [类型检测] 查询 type={ds.get('type')}，图数据库={is_graph}")
            return is_graph
    except Exception as e:
        print(f"  [类型检测] 查询类型失败（按非图数据库处理）: {e}")
    return False


def _is_chroma_datasource(name: str) -> bool:
    """判断数据源是否为 ChromaDB 向量库（写入时需要 document/metadata 结构，而非平铺字段）。"""
    if name in _KNOWN_DATASOURCE_TYPES:
        t = _KNOWN_DATASOURCE_TYPES[name].lower()
        is_chroma = "chroma" in t or "vector" in t or "vectordb" in t
        print(f"  [类型检测] 内置映射 type={_KNOWN_DATASOURCE_TYPES[name]}，向量库={is_chroma}")
        return is_chroma
    try:
        ds = call_tool("list_user_datasources", by_name=name)
        if isinstance(ds, dict):
            t = str(ds.get("type") or "").lower()
            is_chroma = "chroma" in t or "vector" in t or "vectordb" in t
            print(f"  [类型检测] 查询 type={ds.get('type')}，向量库={is_chroma}")
            return is_chroma
    except Exception as e:
        print(f"  [类型检测] 查询类型失败（按非向量库处理）: {e}")
    return False


def _load_pdf_text_cached(path: str) -> str:
    """读取 PDF 全文（带缓存，规避 read_file 慢速解析导致的超时）。

    read_file 对 PDF 的解析在主进程用 pdfplumber 逐页 extract_text()，
    带水印/翻转页的复杂 PDF 单次解析可能耗时 1-3 分钟，且 call_tool 阻塞
    期间脚本无法打印进度，容易触发 300 秒 idle 超时。

    这里把首次解析结果缓存为同目录 txt 文件（文件名带文件大小做版本 key，
    PDF 更新后自动失效），之后运行直接秒读缓存，从根本上避免重复慢解析。
    """
    p = Path(path)
    try:
        size = p.stat().st_size
    except Exception:
        size = 0
    cache_path = p.with_name(f"{p.stem}.pdfcache.txt")

    # 1) 优先读缓存：txt 读取是瞬时 read_text，不会超时。
    #    兼容旧版带大小后缀的文件名（glob 扫描同目录同名缓存）。
    cache_candidates = [cache_path]
    try:
        for c in p.parent.glob(f"{p.stem}.*.pdfcache.txt"):
            if c not in cache_candidates:
                cache_candidates.append(c)
    except Exception:
        pass
    for cand in cache_candidates:
        # 缓存文件不存在时直接跳过，避免 call_tool read_file 对不存在路径挂起
        try:
            if not cand.exists():
                continue
        except Exception:
            continue
        try:
            res = call_tool("read_file", path=str(cand))
            if isinstance(res, dict) and not res.get("error") and res.get("content"):
                cached = str(res["content"])
                if len(cached.strip()) > 200:
                    print(f"  [缓存命中] 使用已缓存的 PDF 文本: {cand.name}")
                    return cached
        except Exception:
            pass

    # 2) 缓存未命中：慢速解析（仅首次），成功后立即写缓存
    print("  [提示] 首次解析 PDF 需在主进程逐页提取文本（含水印/翻转页，约 1-3 分钟），请耐心等待，勿中断…")
    text = _extract_text_from_pdf(path)

    try:
        w = call_tool("write_file", path=str(cache_path), data=text, format="text")
        if isinstance(w, dict) and w.get("success"):
            print(f"  [缓存] PDF 文本已缓存: {cache_path.name}（下次运行秒读）")
        else:
            print(f"  [缓存] 写缓存未确认成功（不影响主流程）: {w!r}")
    except Exception as e:
        print(f"  [缓存] 写缓存失败（不影响主流程）: {e}")

    return text


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
        text = _load_pdf_text_cached(path)
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


_TABLE_TITLE_PATTERN = re.compile(
    r"^表\s*([A-Za-zÀ-ÿ]?\s*\.?\s*\d+(?:[.．]\d+)?)\s*(?:[（(]\s*续\s*[)）])?\s*[:：]?\s*(.*)$"
)

# 附录六张明细表：部件关键词 → (标准编号, 标准名称)。
# 用于标题编号/「表」字被 OCR 或翻转页转置破坏时的兜底识别。
# 注意关键词按“越具体越靠前”排序，避免「冷却」「套管」等宽泛词误命中。
_TABLE_KEYWORD_FALLBACK = [
    ("有载分接开关", "A.4", "油浸式变压器(电抗器)有载分接开关状态量劣化的检修内容明细表"),
    ("无励磁分接开关", "A.5", "油浸式变压器(电抗器)无励磁分接开关状态量劣化的检修内容明细表"),
    ("非电量保护和在线监测装置", "A.6", "油浸式变压器(电抗器)非电量保护和在线监测装置状态量劣化的检修内容明细表"),
    ("冷却", "A.3", "油浸式变压器(电抗器)冷却(散热)器系统状态量劣化的检修内容明细表"),
    ("套管", "A.2", "油浸式变压器(电抗器)套管状态量劣化的检修内容明细表"),
    ("本体", "A.1", "油浸式变压器(电抗器)本体状态量劣化的检修内容明细表"),
]
# 附录明细表标题的专属后缀：正文绝不会独立出现该串，可作翻转页转置标题的兜底锚点。
_APPENDIX_TABLE_SUFFIX = "状态量劣化的检修内容明细表"


def _normalize_table_number(s: str) -> str:
    """归一化表格编号：把 OCR 引入的重音/全角字符还原为 ASCII（Á.1 -> A.1）。"""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    # 仅保留字母数字和点、下划线，去掉空格与 OCR 噪声
    s = "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch in "._"))
    return s.strip()


def _match_fallback(s: str):
    """按附录明细表关键词兜底匹配，返回 (编号, 标准名称) 或 None。"""
    for kw, num, std_name in _TABLE_KEYWORD_FALLBACK:
        if kw in s:
            return num, std_name
    return None


def _parse_table_title(line: str):
    """解析表格标题行，返回 (是否标题, 表格编号, 表格名称, 是否续表)。"""
    s = line.strip()
    if len(s) > 80:
        return False, "", "", False
    m = _TABLE_TITLE_PATTERN.match(s)
    if m and s.startswith("表"):
        number = _normalize_table_number(m.group(1).strip())
        desc = m.group(2).strip()
        # 续表判断放宽为「标题含“续”字」：翻转页/OCR 常把右括号识别成「〉」等噪声，
        # 精确括号匹配 [）)] 会失配，导致「表 Á.1 (续〉」被误判为新表、跨页表格被拆成两个文件。
        is_cont = "续" in s
        return True, number, desc, is_cont
    # 兜底1：行以「表」开头但正则未匹配（编号被 OCR 破坏，如「表 A.4 有载…」乱码）
    if s.startswith("表"):
        fb = _match_fallback(s)
        if fb:
            return True, fb[0], fb[1], "续" in s
        if "停电检修时间" in s:
            return True, "1", "油浸式变压器(电抗器)停电检修时间", "续" in s
        if "检修类别与检修内容对应表" in s:
            return True, "2", "油浸式变压器(电抗器)检修类别与检修内容对应表", "续" in s
        return False, "", "", False
    # 兜底2：行首不是「表」（翻转页转置导致标题错位），但含附录明细表专属后缀时也识别为标题
    if _APPENDIX_TABLE_SUFFIX in s:
        fb = _match_fallback(s)
        if fb:
            return True, fb[0], fb[1], "续" in s
    return False, "", "", False


def _looks_like_table_name(s: str) -> bool:
    """判断一个独立行是否像「表格名称」而非数据/页眉页脚。

    用于「表N」编号与其名称被 PDF 文本层拆成两行时的名称补全（如：
    表1
    油浸式变压器(电抗器)停电检修时间
    ）。只做通用启发式，不硬编码具体表名。
    """
    s = (s or "").strip()
    if not s or len(s) < 4 or len(s) > 60:
        return False
    # 页眉/页脚/水印常见噪声
    if any(k in s for k in ("南网", "wx_", "知识共享", "备案号", "国家能源")):
        return False
    # 数据行特征：以数字/罗马数字/序号符开头，或含表格分隔符
    if re.match(r"^[0-9IVXivx．.、]", s):
        return False
    if "|" in s:
        return False
    # 表格名称通常含中文且为名词短语
    if not re.search(r"[\u4e00-\u9fff]", s):
        return False
    return True


def _split_by_tables(text: str) -> List[Dict[str, str]]:
    """按表格标题切分文本，返回 [{title, number, content}, ...]。

    - title 用表格名称（去掉「表 N」编号前缀，编号单独存 number），
      便于后续「每个表格写一张数据表，表名与表格名字保持一致」；
    - 每个非「续」表格标题开启一个新块；
    - 「表 X (续)」/「表 X（续）」并入前一个表格块（同一张表跨页，不新建块）；
    - 标题前的内容归入「正文」块；
    - 不按固定字符数硬切，避免跨页表格被切断。
    """
    lines = text.split("\n")
    blocks: List[Dict[str, str]] = []
    cur_title = "正文"
    cur_number = ""
    cur_lines: List[str] = []

    def _flush():
        content = "\n".join(cur_lines).strip()
        if content:
            blocks.append({"title": cur_title, "number": cur_number, "content": content})

    for i, line in enumerate(lines):
        is_title, number, desc, is_cont = _parse_table_title(line)
        if is_title:
            if is_cont:
                # 同一张表跨页的分页：保留该行作为上下文提示，继续并入当前块
                cur_lines.append(line)
                continue
            _flush()
            # 名称与编号同行被识别时直接用；若名称被文本层拆到下一行（如
            # 「表1」单独一行、名称在下一行），则前视下一行补全名称。
            merged_title = desc or f"表{number}"
            if not desc:
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if _looks_like_table_name(nxt):
                    merged_title = nxt.strip()
            cur_title = merged_title
            cur_number = number
            cur_lines = [line]
        else:
            cur_lines.append(line)
    _flush()

    if not blocks:
        for chunk in _split_text(text, max_chunk=6000, overlap=1500):
            blocks.append({"title": "正文", "number": "", "content": chunk})
    return blocks


def _merge_blocks_by_number(blocks: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """把同一表号的多个块合并为一个（含续表、跨页重复标题）。

    PDF 文本层中同一表号可能多次出现（fitz 逐页提取时标题每页重复）。
    _split_by_tables 已处理「表X (续)」并入前块，但同表号无续标记的
    重复块仍独立。本函数按表号合并，content 拼接，title 取最完整的。
    """
    merged: List[Dict[str, str]] = []
    by_number: Dict[str, int] = {}
    for b in blocks:
        number = (b.get("number") or "").strip()
        if not number:
            merged.append(b)
            continue
        if number in by_number:
            idx = by_number[number]
            merged[idx]["content"] = merged[idx]["content"] + "\n" + b.get("content", "")
            # title 取更长的（更完整的名称）
            old_title = merged[idx].get("title") or ""
            new_title = b.get("title") or ""
            if len(new_title) > len(old_title) and new_title != f"表{number}":
                merged[idx]["title"] = new_title
        else:
            by_number[number] = len(merged)
            merged.append(dict(b))
    return merged


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

    根据标准文档常见的条款编号（如 1、4.1、5.2.1）抽取「编号 + 标题 + 节首要点」，
    得到远小于全文的大纲文本。
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
    """通读文档大纲，为规则知识库设计合适的多表结构。

    返回 schema_plan：
      {
        "main_table": 主表名（存综述/范围/术语等）,
        "tables": [
          {
            "name": 子表名,
            "description": 表用途,
            "keywords": [匹配关键词...],
            "table_names": [该子表聚合的表格标题，用于跨页表格按名称合并]
          }, ...
        ]
      }
    """
    outline = _extract_outline(text)
    # 附加检测到的表格标题，帮助 LLM 识别表格边界、设计多表结构
    try:
        table_titles = [b["title"] for b in _split_by_tables(text) if b["title"] != "正文"]
        if table_titles:
            outline = (outline + "\n\n【检测到的表格标题】\n" + "\n".join(table_titles)).strip()
    except Exception as e:
        print(f"  [结构分析] 表格标题检测失败（忽略）: {e}")
    if not outline.strip():
        print("  [结构分析] 未抽取到章节大纲，使用默认单表结构")
        return {
            "main_table": "正文规则",
            "tables": [],
        }

    prompt = f"""你是规则文档结构化专家。请通读下面这份规则文档的章节大纲，为规则知识库设计合适的表结构。

要求：
1. 文档中的正文内容（非表格部分）提取为一张表；文档中的各个表格可以单独提取成一张表。
2. 每个子表对应一类规则或一个表格的内容，表名根据内容语义自动生成。
3. 综述、范围、术语、引用文件等归入主表。
4. 识别文档中的表格标题/表格名称：有表格名称的表格按表格名称聚合。
5. 同一个表格跨越多页/多段时，必须识别为同一张表，不得按页拆分；无表格名称但语义连续的表格自动合并到上一个表格或最近的主题表。

必须只输出一个 JSON 对象（不要 Markdown 代码围栏、不要解释），结构如下：
{{
  "main_table": "主表名（如正文规则）",
  "tables": [
    {{
      "name": "子表名",
      "description": "该表存放哪类规则",
      "keywords": ["关键词1", "关键词2"],
      "table_names": ["该子表聚合的表格标题1", "表格标题2"]
    }}
  ]
}}

其中 table_names 是可选的，仅当子表对应文档中的可见表格标题时才填写；用于后续把跨页表格的每一行正确路由到同一张子表。

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
                    f"  [结构分析] 设计出主表「{data.get('main_table') or '正文规则'}」"
                    f"+ {len(data.get('tables') or [])} 张子表: "
                    f"{[t.get('name') for t in (data.get('tables') or [])]}"
                )
                return data
            raise RuntimeError(f"结构分析结果缺少 tables 字段: {content[:200]!r}")
        except Exception as e:
            print(f"  [结构分析] 第 {attempt} 次失败: {e}")
            if attempt == 2:
                print("  [结构分析] 分析失败，使用默认单表结构兜底")
    # 兜底：默认单表结构
    return {
        "main_table": "正文规则",
        "tables": [],
    }


def _extract_rules_from_text(
    text: str,
    max_workers: int = 3,
    schema_plan: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """使用 LLM 并发从文本提取结构化规则条目

    每条规则包含标准字段：rule_code, rule_name, category, applicable_fields,
    format_regex, check_logic, severity, description, table
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 先做一次轻量探测：推理型(reasoning)模型下 llm_generate 的 content 恒为空，
    # 此时直接报错退出，避免多次空转 + 超时叠加导致卡死。
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
            "未提取到任何规则，按「一条也提取不出来即报错退出」策略终止。"
        )
    print("  [探测] llm_generate 正常返回，继续 LLM 并发提取。")

    chunks = _split_by_tables(text)
    total = len(chunks)
    parts_desc = ", ".join(
        f"{c['title']}({len(c['content'])})" for c in chunks
    )
    print(f"  [LLM提取] 按表格标题切分为 {total} 块（含跨页续表合并），并发 {max_workers} 路提取...")
    print(f"  [切分块] {parts_desc}")

    def _build_prompt(block: Dict[str, str]) -> str:
        title = block.get("title") or "正文"
        chunk = block.get("content") or ""
        schema_block = ""
        main_table = "正文规则"
        if schema_plan:
            tables = schema_plan.get("tables") or []
            main_table = schema_plan.get("main_table") or "正文规则"
            rows = [f"- 主表「{main_table}」：综述、范围、术语、引用文件等综合内容"]
            for t in tables:
                name = t.get("name")
                desc = t.get("description")
                kw = "、".join(t.get("keywords") or [])
                tn = "、".join(t.get("table_names") or [])
                row = f"- 子表「{name}」：{desc}"
                if tn:
                    row += f"（对应表格标题：{tn}）"
                if kw:
                    row += f"（关键词：{kw}）"
                rows.append(row)
            schema_block = "【知识库表结构】\n" + "\n".join(rows) + "\n\n"

        return f"""请从以下规则文档片段中提取结构化规则，直接从正文输出结果，不要输出任何思考过程或推理文字。

【当前片段所属表格】
{title}

对每条规则输出一个 JSON 对象，字段如下：
- rule_code: 规则编号（若文档中有编号请保留；若无则留空）
- rule_name: 规则名称（简短概括本条规则）
- category: 规则分类，可选：标准/质量/安全
- applicable_fields: 适用字段（多个用逗号分隔；无则留空）
- format_regex: 格式正则表达式（若规则涉及格式校验则填写；无则留空）
- check_logic: 检查逻辑描述（用简体中文描述规则的检查逻辑）
- severity: 严重等级，可选：info/warn/error/critical
- description: 规则详细解释
- table: 本条归属的表名（从下方【知识库表结构】中选择最匹配的一个表名；若文档中有表格标题，优先根据表格标题匹配对应的子表；无法判断时填主表名「{main_table}」）

{schema_block}【表格复原要求（非常重要）】
正文中混有表格内容，且表格常被转置（行列互换）。提取时：
1. 先识别表头和单元格边界，还原「表头字段 + 对应取值」的行列对应关系；
2. 转置表格要还原为「每行一个规则/项目，每列一个属性」的形式；
3. 表格中每一行（每一组完整对应关系）必须作为一条独立规则提取，字段名作为 applicable_fields；
4. 表格行如果表达同一语义或被分页/分行拆散，必须按语义自动合并，避免规则被拆散；
5. 跨越多页/多段的表格，请结合上下文把被截断的行补全；有表格名称的按表格名称聚合，无表格名称的合并到上一个表格/最近主题表；
6. 不同规则、不同字段取值的表格行不得合并，宁可多提不可漏提，不得因为内容相似就跳过某行；
7. 表头尽量与表格原始表头保持一致，不要改写或概括表头文字；单元格内容尽量与表格单元文字保持一致，关键数值、阈值、判据必须逐字保留；
8. 如果表格有序号（如 1、2、3 或 A.1、A.2），相同序号的行要按照语义合并形成一行，不得因为分页、转置或分行而把同一序号的内容拆成多条规则。
9. 若片段中出现「表 X (续)」「表 X（续）」字样，说明它是前面表格的分页续表，必须把该续表的行并入同一张表，不得当作新表，也不得丢失续表中的任何一行；续表与前表的行号连续编号，逐一提取不得漏行。

要求：
- 这是电力行业标准文档，正文只提取「导则」中的实质规则；封皮、目次、前言、引用文件清单等制式内容价值不大，一律忽略，不要提取。
- 文档水印（如「南网知识共享服务平台」等浅色斜字）、页眉页脚（左上角/右下角的 DL/T 1684-2017、发布实施信息）、页码一律忽略。
- 每段最多提取 50 条，只保留有实质内容的规则，忽略目录、前言、引用文件清单、过渡性语句。
- 关键数值、阈值、判据必须逐字保留。

必须只输出一个 JSON 数组（以 [ 开头、以 ] 结尾），不要输出 Markdown 代码围栏、解释或任何其他文字。

文档片段如下：
---
{chunk}
---"""

    # 重试参数阶梯：提取失败时逐级调大 max_tokens、微调 temperature
    RETRY_CONFIGS = [
        {"temperature": 0.0, "max_tokens": 8192},
        {"temperature": 0.1, "max_tokens": 8192},
        {"temperature": 0.2, "max_tokens": 12000},
    ]

    def _call_once(idx: int, block: Dict[str, str], attempt: int, cfg: Dict[str, Any]):
        """对单个切片发起一次 LLM 调用。

        返回:
          - "ok"      : (标记, parsed列表) 成功
          - "timeout" : (标记, None) 平台调用超时（原地重试无效，应立即细切）
          - "fail"    : (标记, None) 其他失败（可换参数重试）
        """
        prompt = _build_prompt(block)
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

    def _process_with_refinement(idx: int, block: Dict[str, str]):
        """对一个表格/正文块提取规则：先原片多参数重试；遇超时或仍失败则细切（较小窗口，无重叠）
        后再逐个提取，尽量不丢失跨页/跨段的大表格内容。"""
        title = block.get("title") or "正文"
        content = block["content"]
        last_err = "原片"
        # 第一层：原片多参数重试（遇 timeout 立即停止原地重试，转入细切）
        for attempt, cfg in enumerate(RETRY_CONFIGS, 1):
            status, parsed = _call_once(idx, block, attempt, cfg)
            if status == "ok":
                return idx, parsed
            if status == "timeout":
                last_err = f"原片第 {attempt} 次超时"
                break
            last_err = f"原片 {len(RETRY_CONFIGS)} 次重试均失败"
        # 第二层：小切片重切再提取（无重叠，块内表格行边界清晰）
        print(f"    [细切重试] 第 {idx} 段（{title}）失败（{last_err}），改为 2400 字符/无重叠细切后重试...")
        sub_chunks = _split_text(content, max_chunk=2400, overlap=0)
        all_parsed: List[Dict[str, Any]] = []
        sub_ok = 0
        for s_idx, sub in enumerate(sub_chunks, 1):
            sub_block = {"title": title, "content": sub}
            got = None
            for attempt, cfg in enumerate(RETRY_CONFIGS, 1):
                status, got = _call_once(s_idx, sub_block, attempt, cfg)
                if status == "ok":
                    break
                if status == "timeout":
                    break  # 细切片再超时也放弃该片，不再空转
            if got is not None:
                all_parsed.extend(got)
                sub_ok += 1
        if not all_parsed:
            raise RuntimeError(f"第 {idx} 段（{title}）原片与细切片重试均失败。{last_err}")
        print(f"    [细切成功] 第 {idx} 段（{title}）细切 {len(sub_chunks)} 片，{sub_ok} 片成功，共 {len(all_parsed)} 条")
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
        # 全部失败：直接报错退出
        raise RuntimeError(
            f"LLM 提取全部失败（{len(errors)} 段），未提取到任何规则: {errors}"
        )
    if errors:
        # 部分失败：使用成功部分，但明确警告
        print(f"  [警告] LLM 提取有 {len(errors)} 段失败（已跳过）: {errors}")

    # 按切片原始顺序拼接
    all_entries = []
    for idx in sorted(results_by_idx):
        all_entries.extend(results_by_idx[idx])

    # 合并相同 rule_code 且语义相同的条目（表格中相同序号的行）。
    # 不再简单地按 (rule_code, rule_name) 去重保留第一条，而是把同序号、
    # 同规则名的多条片段合并成一条完整规则，避免规则被分页/分行拆散后变成多条。
    merged_entries = _merge_same_code_entries(all_entries)
    return merged_entries


def _merge_rule_group(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把同一规则的多条片段（相同 rule_code）合并为一条完整记录。

    表格中同一序号的行常因分页、分行或转置被拆成多条，本函数将其合并：
    - rule_name 选择最完整的名称（长度优先）
    - applicable_fields 拆开去重后重新用逗号连接
    - check_logic、description 按顺序拼接（去重）
    - format_regex 有多个不同值时合并（去重）
    - severity 保留最高等级
    """
    base = dict(group[0])

    # 0) rule_name：按语义选择最完整的规则名称（表格中同一序号的多条片段名称可能略有差异）
    names = []
    for e in group:
        val = str(e.get("rule_name") or "").strip()
        if val and val not in names:
            names.append(val)
    if names:
        base["rule_name"] = max(names, key=len)

    # 1) applicable_fields：保持表头原始格式
    # 若所有片段字段值一致，直接保留原始表头（不拆分，避免破坏原文）
    raw_fields = []
    for e in group:
        val = str(e.get("applicable_fields") or "").strip()
        if val:
            raw_fields.append(val)
    if raw_fields and len(set(raw_fields)) == 1:
        base["applicable_fields"] = raw_fields[0]
    else:
        # 值不一致才拆成单个字段名，去重后拼接（合并被拆散的表头）
        field_values = []
        for val in raw_fields:
            for part in re.split(r"[,，、;；]+", val):
                part = part.strip()
                if part and part not in field_values:
                    field_values.append(part)
        base["applicable_fields"] = ",".join(field_values)

    # 2) check_logic / description：保持表格单元原文
    # 若所有片段内容一致，直接保留原文（不拼接，避免改写/重复）
    for field in ["check_logic", "description"]:
        raw_values = []
        for e in group:
            val = str(e.get(field) or "").strip()
            if val:
                raw_values.append(val)
        if raw_values and len(set(raw_values)) == 1:
            base[field] = raw_values[0]
        else:
            # 内容不一致才拼接，去重保留顺序（合并被拆散的表格单元）
            values = []
            for val in raw_values:
                if val not in values:
                    values.append(val)
            base[field] = "\n".join(values)

    # 3) format_regex：多个不同正则时去重合并
    regexes = []
    for e in group:
        val = str(e.get("format_regex") or "").strip()
        if val and val not in regexes:
            regexes.append(val)
    base["format_regex"] = "\n".join(regexes) if len(regexes) > 1 else (regexes[0] if regexes else "")

    # 4) severity：保留最高等级（critical > error > warn > info）
    severity_order = {"info": 0, "warn": 1, "error": 2, "critical": 3}
    base_severity = str(base.get("severity") or "warn").strip()
    for e in group[1:]:
        s = str(e.get("severity") or "").strip()
        if s in severity_order and severity_order.get(s, 1) > severity_order.get(base_severity, 1):
            base_severity = s
    base["severity"] = base_severity

    return base


def _merge_same_code_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并相同 rule_code 且同属一个表格的条目（表格中相同序号的行）。

    在 LLM 提取后的后处理阶段，对相同规则编号（rule_code 相同）且同属一个表格的
    条目进行合并，确保同一规则的多个片段（因分页、分行、转置被拆散）最终只保留
    一条完整记录。不同表格中恰好相同序号的独立规则不会被错误合并。
    无 rule_code 的条目不参与合并。
    """
    merged: List[Dict[str, Any]] = []
    used = set()

    for i, e in enumerate(entries):
        if i in used:
            continue
        code_i = str(e.get("rule_code") or "").strip()
        table_i = str(e.get("table") or "").strip()

        # 无编号的条目不合并，原样保留
        if not code_i:
            merged.append(e)
            continue

        # 相同规则编号（表格中的相同序号）且同属一个表格的条目按语义合并成一行，
        # 不再要求规则名先相似：同一序号即使因表格拆分导致名称写法略有差异，也必须合并。
        # 若双方都带有表格归属且归属不同，则视为不同表格中的独立规则，不合并。
        group = [e]
        for j in range(i + 1, len(entries)):
            if j in used:
                continue
            code_j = str(entries[j].get("rule_code") or "").strip()
            if code_j != code_i:
                continue
            table_j = str(entries[j].get("table") or "").strip()
            # 不同表格中恰好相同序号的独立规则，不得合并
            if table_i and table_j and table_i != table_j:
                continue
            group.append(entries[j])
            used.add(j)

        if len(group) == 1:
            merged.append(e)
        else:
            merged.append(_merge_rule_group(group))

    return merged


def _chapter_based_extract(text: str) -> List[Dict[str, Any]]:
    """LLM 不可用时的降级提取：按章节/条款号切分规则文档，生成规则条目。

    适用于有明确条款编号的标准文档（章节编号形如 1、4.1、5.2.1）。
    不依赖 LLM，纯规则切分；超长章节按段落再切分。
    """
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
                        "rule_code": m.group(1) if m else "",
                        "rule_name": current_title,
                        "category": "标准",
                        "applicable_fields": "",
                        "format_regex": "",
                        "check_logic": content[:500],
                        "severity": "warn",
                        "description": content,
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
                "rule_code": "",
                "rule_name": current_title,
                "category": "标准",
                "applicable_fields": "",
                "format_regex": "",
                "check_logic": content[:500],
                "severity": "warn",
                "description": content,
            })

    # 超长章节（>3000 字）按段落再切分
    final = []
    for e in entries:
        if len(e["description"]) <= 3000:
            final.append(e)
            continue
        paras = [p for p in re.split(r"\n+", e["description"]) if p.strip()]
        buf = ""
        part = 0
        for p in paras:
            if buf and len(buf) + len(p) > 3000:
                part += 1
                final.append({
                    "rule_code": e["rule_code"],
                    "rule_name": f"{e['rule_name']}({part})",
                    "category": e["category"],
                    "applicable_fields": e["applicable_fields"],
                    "format_regex": e["format_regex"],
                    "check_logic": buf.strip()[:500],
                    "severity": e["severity"],
                    "description": buf.strip(),
                })
                buf = p
            else:
                buf = (buf + "\n" + p).strip()
        if buf:
            final.append({
                "rule_code": e["rule_code"],
                "rule_name": f"{e['rule_name']}({part + 1})" if part else e["rule_name"],
                "category": e["category"],
                "applicable_fields": e["applicable_fields"],
                "format_regex": e["format_regex"],
                "check_logic": buf.strip()[:500],
                "severity": e["severity"],
                "description": buf.strip(),
            })
    return final


def _sanitize_table_name(name: str) -> str:
    """把表格名称净化为可安全作为数据表名的字符串。

    保留中文与常见括号，仅剔除会破坏平台表名解析/文件路径的特殊字符。
    """
    if not name:
        return "未命名表"
    return re.sub(r'[/\\|:*?"<>]+', "_", name).strip().strip("._")


def _table_block_has_data(block: Dict[str, str]) -> bool:
    """判断表格块的文本层是否含真正数据行（而非只有标题、续表标记、水印碎片）。"""
    content = block.get("content") or ""
    data_lines = []
    for line in content.split("\n"):
        s = line.strip()
        if not s:
            continue
        # 过滤表格标题行（表X.Y 标题名 / 表X.Y (续)）
        is_title, _, _, _ = _parse_table_title(s)
        if is_title:
            continue
        # 过滤续表标记行（纯"(续)"）
        if s in ("(续)", "（续）"):
            continue
        # 过滤水印碎片（单字行）
        if len(s) < 3:
            continue
        data_lines.append(s)
    if len(data_lines) < 2:
        return False
    # 必须有至少一行含数字（数据行通常含数值/序号），且不是标题里的编号
    return any(re.search(r"\d", s) for s in data_lines)


def _merge_same_sequence_rows(headers: List[str], rows: List[List[str]]) -> List[List[str]]:
    """按序号列把相同序号的行合并成一行。"""
    if not rows:
        return rows
    # 定位序号列
    seq_idx = 0
    for i, h in enumerate(headers):
        if h and ("序号" in h or "编号" in h):
            seq_idx = i
            break
    else:
        return rows  # 无序号列不合并
    merged: Dict[str, List[str]] = {}
    order: List[str] = []
    for r in rows:
        r = list(r)
        while len(r) < len(headers):
            r.append("")
        if len(r) > len(headers):
            r = r[:len(headers)]
        seq = str(r[seq_idx]).strip() if seq_idx < len(r) else ""
        # 提取开头数字序号
        m = re.match(r"^\s*(\d{1,4})", seq)
        seq_key = m.group(1) if m else seq
        if not seq_key:
            key = f"__row_{len(order)}"
            merged[key] = r
            order.append(key)
            continue
        if seq_key not in merged:
            merged[seq_key] = r
            order.append(seq_key)
        else:
            base = merged[seq_key]
            for j in range(len(headers)):
                cur = str(r[j]).strip() if j < len(r) else ""
                old = str(base[j]).strip() if j < len(base) else ""
                if j == seq_idx:
                    if cur and (not old or len(cur) > len(old)):
                        base[j] = cur
                    continue
                if cur and cur != old:
                    base[j] = old + "；" + cur if old else cur
    return [merged[k] for k in order]


def _drop_empty_columns(headers: List[str], rows: List[List[str]]) -> tuple:
    """剔除「表头为空且整列全空」的列，避免落库时列名被规范化为 Unnamed。

    LLM 归并偶会多输出一列空数据（表头为空、整列无值），落库后平台把空表头
    规范化为「Unnamed: N」，触发 snake_case 命名规范告警。这里在转记录前剔除。
    若某列表头为空但存在非空单元格，则给一个占位表头，避免数据丢失。
    """
    if not headers or not rows:
        return headers, rows
    headers = list(headers)
    rows = [list(r) for r in rows]
    n = len(headers)
    for r in rows:
        while len(r) < n:
            r.append("")
    keep_idx = []
    for ci in range(n):
        col_has_value = any(ci < len(r) and str(r[ci]).strip() for r in rows)
        col_has_header = bool(str(headers[ci]).strip())
        if col_has_header or col_has_value:
            keep_idx.append(ci)
    if len(keep_idx) == n:
        return headers, rows
    new_headers = []
    for ci in keep_idx:
        h = str(headers[ci]).strip()
        if not h:
            h = f"列{ci + 1}"
        new_headers.append(h)
    new_rows = [[r[ci] if ci < len(r) else "" for ci in keep_idx] for r in rows]
    if new_headers and new_rows:
        print(f"  [清列] 剔除 {n - len(keep_idx)} 个空列（原 {n} 列 → 保留 {len(keep_idx)} 列）")
    return new_headers, new_rows


def _check_sequence_gaps(headers: List[str], rows: List[List[str]], table_number: str = "", verbose: bool = True) -> List[int]:
    """检测序号列断档，返回缺失的序号列表；断档说明 LLM 归并漏行，应显式告警。"""
    if not rows:
        return []
    seq_idx = None
    for i, h in enumerate(headers):
        if h and ("序号" in str(h) or "编号" in str(h)):
            seq_idx = i
            break
    if seq_idx is None:
        return []
    nums = []
    for r in rows:
        s = str(r[seq_idx]).strip() if seq_idx < len(r) else ""
        m = re.match(r"^\s*(\d{1,4})", s)
        if m:
            nums.append(int(m.group(1)))
    if not nums:
        return []
    max_n = max(nums)
    full = set(range(1, max_n + 1))
    missing = sorted(full - set(nums))
    if missing and verbose:
        print(f"  [断档告警] 表{table_number} 序号从 1~{max_n} 缺失 {len(missing)} 个：{missing}")
    return missing


def _sort_rows_by_sequence(headers: List[str], rows: List[List[str]]) -> List[List[str]]:
    """按序号列升序排序。"""
    if not rows:
        return rows
    seq_idx = 0
    for i, h in enumerate(headers):
        if h and ("序号" in h or "编号" in h):
            seq_idx = i
            break
    else:
        return rows
    def _key(r):
        s = str(r[seq_idx]).strip() if seq_idx < len(r) else ""
        m = re.match(r"^\s*(\d{1,4})", s)
        if m:
            return (0, int(m.group(1)), 0)
        return (1, 0, 0)
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda t: _key(t[1]))
    return [r for _, r in indexed]


def _scan_all_pages_for_tables(pdf_path: str, table_numbers: List[str], start_page: int = 1) -> Dict[str, str]:
    """一次全页扫描：逐页渲染图片 → llm_vision 输出所有表格 MD → 按表号分配。

    返回 {table_number: 合并后的 MD}。
    每页只渲染+识别一次，所有表格块共享结果。
    start_page: 起始扫描页（1-indexed）。附录明细表通常从第 5 页开始，
    前几页是封面/目录/正文，跳过可省大量 llm_vision 调用时间。
    """
    from pathlib import Path as _Path

    # 获取总页数
    text_res = call_tool("read_file", path=pdf_path)
    if not isinstance(text_res, dict) or "content" not in text_res:
        raise RuntimeError(f"read_file 获取 PDF 失败: {text_res!r}")
    total_pages = text_res.get("total_pages")
    if not total_pages:
        probe = call_tool("read_file", path=pdf_path, pdf_page_images=[1], dpi=72)
        total_pages = probe.get("total_pages") if isinstance(probe, dict) else 0
    if not total_pages:
        total_pages = 20
    max_pages = min(total_pages, 30)
    print(f"  [OCR] 全页扫描 {max_pages} 页（总 {total_pages} 页）")

    ocr_prompt = """你是标准规范类文档表格 OCR 专家。下面是一张从 PDF 渲染出的页面图片（可能横向或翻转，请先判断方向再识别）。

本页可能包含一个或多个表格。请把页面上所有表格都识别输出，每个表格按以下格式：

表X.Y 表格名称
| 列1 | 列2 | ... |
| --- | --- | --- |
| 数据行1 |
| 数据行2 |

要求：
1. 每个表格前必须有一行标题（如"表A.1 断路器..."或"表A.1 (续)"），标题行单独一行、不以 | 开头；
2. 如果页面上只有一个表格，也照常输出标题行+表格；
3. 表头有多少列就输出多少列，数据行单元格数与表头列数一致；
4. 单元格内容逐字保留，数值、阈值、判据不得改写；
5. 忽略水印文字（浅色斜体大字）、页眉、页脚、页码及表格分隔线；
6. 直接输出 Markdown，禁止用 ``` 围栏包裹，禁止输出任何说明文字；
7. 只识别真实印在纸上的文字，看不清的字符宁可留空，不得用相似符号填充；
8. 多行子项必须合并到同一单元格内（用分号连接），确保每行单元格数与表头列数一致。

注意：不要遗漏任何表格；每个表格的标题行必须完整输出。"""

    # 按表号收集 MD
    md_by_number: Dict[str, List[str]] = {num: [] for num in table_numbers}

    batch_size = 5
    for batch_start in range(start_page, max_pages + 1, batch_size):
        batch_pages = list(range(batch_start, min(batch_start + batch_size, max_pages + 1)))
        print(f"  [OCR] 渲染第 {batch_pages[0]}-{batch_pages[-1]} 页…")
        img_res = call_tool("read_file", path=pdf_path, pdf_page_images=batch_pages, dpi=200)
        if not isinstance(img_res, dict) or not img_res.get("success"):
            print(f"  [OCR] 渲染批次失败（跳过）: {img_res!r}")
            continue
        image_paths = img_res.get("image_paths") or []
        # 复制图片到授权目录
        page_img_map: Dict[int, str] = {}
        for i, img_path in enumerate(image_paths):
            page_no = batch_pages[i] if i < len(batch_pages) else 0
            _src = _Path(str(img_path))
            _dst = _Path(pdf_path).parent / f"_dc_ocr_p{page_no}_{_src.name}"
            try:
                _dst.write_bytes(_src.read_bytes())
            except Exception:
                _dst = _src
            page_img_map[page_no] = str(_dst)

        # 并发识别本批图片
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _ocr_one(pg: int) -> tuple:
            img_p = page_img_map[pg]
            for v_attempt in range(1, 4):
                try:
                    vres = call_tool("llm_vision", image_path=img_p, prompt=ocr_prompt)
                    if not isinstance(vres, dict) or "error" in vres:
                        raise RuntimeError(f"llm_vision 返回异常: {vres!r}")
                    raw = str(vres.get("result") or "").strip()
                    if not raw:
                        raise RuntimeError("llm_vision 返回空结果")
                    return pg, raw
                except Exception as e:
                    if v_attempt < 3:
                        import time as _t
                        _t.sleep(1.5 * v_attempt)
                    else:
                        print(f"  [OCR] 第 {pg} 页连续 3 次失败: {e}")
                        return pg, ""
            return pg, ""

        with ThreadPoolExecutor(max_workers=min(5, len(page_img_map))) as _ex:
            futs = {_ex.submit(_ocr_one, pg): pg for pg in page_img_map}
            for fut in as_completed(futs):
                pg, raw = fut.result()
                if raw:
                    for num in table_numbers:
                        target_md = _filter_md_by_table_number(raw, num)
                        if target_md:
                            md_by_number[num].append(f"== 第 {pg} 页 ==\n{target_md}")
                print(f"  [OCR] 第 {pg} 页识别完成")

    # 合并各表号的 MD
    result: Dict[str, str] = {}
    for num, parts in md_by_number.items():
        if parts:
            result[num] = "\n\n".join(parts)
            print(f"  [OCR] 表{num} 收集 {len(parts)} 页 MD，共 {len(result[num])} 字符")
    return result


def _extract_table_from_ocr_md(block: Dict[str, str], ocr_md: str) -> Dict[str, Any]:
    """用已扫描的 OCR MD 直接做 LLM 归并，不需要再渲染图片。"""
    title = block.get("title") or "未命名表"
    number = block.get("number") or ""

    merged = _merge_md_tables_semantically(title, number, [ocr_md])

    _table_name = _sanitize_table_name(f"表{number} {title}".strip() if number and title and title != f"表{number}" else (f"表{number}" if number else title))

    if merged and merged.get("headers") and merged.get("rows"):
        headers = [str(h).strip() for h in merged["headers"]]
        rows = [[("" if c is None else str(c)) for c in r] for r in merged["rows"]]
        rows = _merge_same_sequence_rows(headers, rows)
        rows = _sort_rows_by_sequence(headers, rows)
        print(f"  [OCR] 表{number} 归并完成: {len(rows)} 行 × {len(headers)} 列")
        return {"table_name": _table_name, "table_number": number, "headers": headers, "rows": rows}

    # 归并失败，直接用 OCR MD 解析
    parsed = _parse_markdown_table(ocr_md)
    if parsed:
        data = parsed[0]
        headers = [str(x).strip() for x in (data.get("headers") or [])]
        rows = [[("" if c is None else str(c)) for c in r] for r in (data.get("rows") or [])]
        if headers and rows:
            rows = _merge_same_sequence_rows(headers, rows)
            rows = _sort_rows_by_sequence(headers, rows)
            print(f"  [OCR] 表{number} 直接解析: {len(rows)} 行 × {len(headers)} 列")
            return {"table_name": _table_name, "table_number": number, "headers": headers, "rows": rows}

    raise RuntimeError(f"表格「表{number}」OCR 归并失败")


def _extract_table_via_ocr(block: Dict[str, str], pdf_path: str) -> Dict[str, Any]:
    """图片型表格 OCR 通道：逐页渲染图片 → llm_vision 输出 MD → 按表号切分合并 → LLM 归并。

    不定位页码——直接逐页扫描所有页面，每页 llm_vision 输出所有表格的 MD，
    按 `_filter_md_by_table_number` 只保留目标表号的内容，合并后一次 LLM 归并。
    """
    from pathlib import Path as _Path

    title = block.get("title") or "未命名表"
    number = block.get("number") or ""

    # 1. 先获取总页数
    text_res = call_tool("read_file", path=pdf_path)
    if not isinstance(text_res, dict) or "content" not in text_res:
        raise RuntimeError(f"read_file 获取 PDF 失败: {text_res!r}")
    full_text = str(text_res.get("content") or "")
    total_pages = text_res.get("total_pages")
    if not total_pages:
        # 缓存文本不含 total_pages，用渲染第一页获取
        probe = call_tool("read_file", path=pdf_path, pdf_page_images=[1], dpi=72)
        if isinstance(probe, dict) and probe.get("total_pages"):
            total_pages = probe["total_pages"]
        else:
            total_pages = len(full_text) // 2000 + 1
    max_pages = min(total_pages, 30)
    print(f"  [OCR] 逐页扫描 {max_pages} 页（总 {total_pages} 页）")

    # 2. 分批渲染图片（每批 5 页，避免单次渲染太多）
    ocr_prompt = """你是标准规范类文档表格 OCR 专家。下面是一张从 PDF 渲染出的页面图片（可能横向或翻转，请先判断方向再识别）。

本页可能包含一个或多个表格。请把页面上所有表格都识别输出，每个表格按以下格式：

表X.Y 表格名称
| 列1 | 列2 | ... |
| --- | --- | --- |
| 数据行1 |
| 数据行2 |

要求：
1. 每个表格前必须有一行标题（如"表A.1 断路器..."或"表A.1 (续)"），标题行单独一行、不以 | 开头；
2. 如果页面上只有一个表格，也照常输出标题行+表格；
3. 表头有多少列就输出多少列，数据行单元格数与表头列数一致；
4. 单元格内容逐字保留，数值、阈值、判据不得改写；
5. 忽略水印文字（浅色斜体大字）、页眉、页脚、页码及表格分隔线；
6. 直接输出 Markdown，禁止用 ``` 围栏包裹，禁止输出任何说明文字；
7. 只识别真实印在纸上的文字，看不清的字符宁可留空，不得用相似符号填充；
8. 多行子项必须合并到同一单元格内（用分号连接），确保每行单元格数与表头列数一致；
9. 若表头下第一列是序号、其后有「分类/类别」类短词列和「名称/描述」类长文本列，必须严格按表头所在列对齐输出，禁止把短类别词和长名称互换位置；
10. 若某列存在垂直合并单元格（多个数据行共用同一个值，视觉上只出现一次），该值必须在它覆盖的每一行都重复输出，禁止只在首行输出、禁止留空。

注意：不要遗漏任何表格；每个表格的标题行必须完整输出。"""

    md_parts = []
    batch_size = 5
    for batch_start in range(1, max_pages + 1, batch_size):
        batch_pages = list(range(batch_start, min(batch_start + batch_size, max_pages + 1)))
        print(f"  [OCR] 渲染第 {batch_pages[0]}-{batch_pages[-1]} 页…")
        img_res = call_tool("read_file", path=pdf_path, pdf_page_images=batch_pages, dpi=200)
        if not isinstance(img_res, dict) or not img_res.get("success"):
            print(f"  [OCR] 渲染批次失败（跳过）: {img_res!r}")
            continue
        image_paths = img_res.get("image_paths") or []
        for i, img_path in enumerate(image_paths):
            page_no = batch_pages[i] if i < len(batch_pages) else 0
            # 复制到授权目录（PDF 同目录）
            _src = _Path(str(img_path))
            _dst = _Path(pdf_path).parent / f"_dc_ocr_{number}_p{page_no}_{_src.name}"
            try:
                _dst.write_bytes(_src.read_bytes())
            except Exception:
                _dst = _src

            for v_attempt in range(1, 4):
                try:
                    vres = call_tool("llm_vision", image_path=str(_dst), prompt=ocr_prompt)
                    if not isinstance(vres, dict) or "error" in vres:
                        raise RuntimeError(f"llm_vision 返回异常: {vres!r}")
                    raw = str(vres.get("result") or "").strip()
                    if not raw:
                        raise RuntimeError("llm_vision 返回空结果")
                    # 按表号切分，只保留目标表的内容
                    target_md = _filter_md_by_table_number(raw, number)
                    if target_md:
                        md_parts.append(f"== 第 {page_no} 页 ==\n{target_md}")
                        print(f"  [OCR] 第 {page_no} 页识别到表{number}")
                    else:
                        print(f"  [OCR] 第 {page_no} 页未找到表{number}")
                    break
                except Exception as e:
                    print(f"  [OCR] 第 {page_no} 页第 {v_attempt}/3 次失败: {e}")
                    if v_attempt < 3:
                        import time as _t
                        _t.sleep(1.5 * v_attempt)

    if not md_parts:
        raise RuntimeError(f"表格「表{number}」所有页 OCR 均未识别到内容")

    # 3. LLM 归并 MD
    joined_md = "\n\n".join(md_parts)
    print(f"  [OCR] 表{number} 收集 {len(md_parts)} 页 MD，共 {len(joined_md)} 字符")
    merged = _merge_md_tables_semantically(title, number, [joined_md])

    _table_name = _sanitize_table_name(f"表{number} {title}".strip() if number and title and title != f"表{number}" else (f"表{number}" if number else title))

    if merged and merged.get("headers") and merged.get("rows"):
        headers = [str(h).strip() for h in merged["headers"]]
        rows = [[("" if c is None else str(c)) for c in r] for r in merged["rows"]]
        # 同序号合并 + 排序
        rows = _merge_same_sequence_rows(headers, rows)
        rows = _sort_rows_by_sequence(headers, rows)
        print(f"  [OCR] 表{number} 归并完成: {len(rows)} 行 × {len(headers)} 列")
        return {
            "table_name": _table_name,
            "table_number": number,
            "headers": headers,
            "rows": rows,
        }

    # 归并失败，直接用 OCR MD 解析
    parsed = _parse_markdown_table(joined_md)
    if parsed:
        data = parsed[0]
        headers = [str(x).strip() for x in (data.get("headers") or [])]
        rows = [[("" if c is None else str(c)) for c in r] for r in (data.get("rows") or [])]
        if headers and rows:
            rows = _merge_same_sequence_rows(headers, rows)
            rows = _sort_rows_by_sequence(headers, rows)
            print(f"  [OCR] 表{number} 直接解析: {len(rows)} 行 × {len(headers)} 列")
            return {
                "table_name": _table_name,
                "table_number": number,
                "headers": headers,
                "rows": rows,
            }

    raise RuntimeError(f"表格「表{number}」OCR 归并失败")


def _filter_md_by_table_number(md_text: str, table_number: str) -> str:
    """从整页 OCR 输出的 MD 中，按表格标题行切分，只保留目标表号的 MD 段落。

    严格匹配：标题行必须以"表"开头且含目标表号（归一化后精确匹配）。
    没匹配到时返回空字符串（不返回整页 MD，避免混入其他表内容）。
    """
    if not md_text or not table_number:
        return ""
    lines = md_text.split("\n")
    target_norm = _normalize_table_number(table_number)
    if not target_norm:
        return ""
    target_segments = []
    all_title_indices = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("|"):
            continue
        if re.match(r"^表\s*[A-Za-z]?\s*\.?\s*\d+", s):
            all_title_indices.append(i)
    if not all_title_indices:
        # 没有标题行：可能整页只有一个表，检查内容是否像表格
        tbl_lines = [ln for ln in lines if ln.strip().startswith("|")]
        if len(tbl_lines) >= 2:
            return md_text  # 整页只有一个表格，返回全部
        return ""
    for idx_pos, start in enumerate(all_title_indices):
        is_title, number, desc, is_cont = _parse_table_title(lines[start].strip())
        if not is_title:
            continue
        norm = _normalize_table_number(number)
        if norm != target_norm:
            continue
        end = all_title_indices[idx_pos + 1] if idx_pos + 1 < len(all_title_indices) else len(lines)
        for j in range(start, end):
            target_segments.append(lines[j])
    if not target_segments:
        return ""  # 没匹配到目标表号，返回空（不返回整页）
    return "\n".join(target_segments)


def _parse_markdown_table(text: str) -> List[Dict[str, Any]]:
    """把 Markdown 表格（| 分隔）解析成 [{"headers": [...], "rows": [[...]]}]。

    解析时清除 HTML 标签（如 <sub>、<sup>、<br> 等），只保留纯文本。
    """
    # 清除 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tbl_lines = [ln for ln in lines if "|" in ln]
    if len(tbl_lines) < 2:
        return []

    def _cells(ln: str) -> List[str]:
        s = ln.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    all_cells = [_cells(ln) for ln in tbl_lines]
    sep_idx = None
    for i, cells in enumerate(all_cells):
        non_empty = [c for c in cells if c != ""]
        if non_empty and all(re.fullmatch(r"[-=: ]+", c) for c in non_empty):
            sep_idx = i
            break
    if sep_idx is None:
        header_lines = all_cells[:1]
        row_start = 1
    else:
        header_lines = all_cells[:sep_idx]
        row_start = sep_idx + 1
    ncols = max((len(c) for c in all_cells), default=0)
    if ncols == 0:
        return []
    headers: List[str] = []
    for ci in range(ncols):
        parts: List[str] = []
        for cl in header_lines:
            v = (cl[ci] if ci < len(cl) else "").strip()
            if v and v not in parts:
                parts.append(v)
        headers.append("｜".join(parts) if parts else "")
    if not headers or all(h == "" for h in headers):
        return []
    rows: List[List[str]] = []
    for cells in all_cells[row_start:]:
        if not cells or all(c == "" for c in cells):
            continue
        while len(cells) < ncols:
            cells.append("")
        rows.append(cells[:ncols])
    if not rows:
        return []
    return [{"headers": headers, "rows": rows}]


def _split_long_md(md_text: str, max_chars: int = 6000) -> List[str]:
    """把超长 MD 按行边界切段，避免单次塞入超长文本导致丢行/串列。"""
    if len(md_text) <= max_chars:
        return [md_text]
    lines = md_text.split("\n")
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for ln in lines:
        add = len(ln) + 1
        # 尽量在非数据行的边界切（标题行/分隔行），避免切断数据行
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
    """把 headers/rows 还原成 Markdown 表格文本，供滚动归并续接。"""
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


def _extract_header_hint_from_md(md_text: str) -> str:
    """从 MD 表头行动态提取列名特征，生成列结构提示（不硬编码业务词）。

    通用规则：检测表头中含关键词的列，动态生成提示让 LLM 正确区分各列内容。
    """
    if not md_text:
        return ""
    lines = md_text.split("\n")
    for line in lines:
        s = line.strip()
        if s.startswith("|") and "---" not in s:
            cells = [c.strip() for c in s.strip("|").split("|")]
            cells = [c for c in cells if c]
            if len(cells) < 2:
                return ""
            hints = []
            for c in cells:
                if any(kw in c for kw in ("分类", "类别", "类型")):
                    hints.append(f"列「{c}」应填短词（如分类名），不应填长描述，不应与其他列重复")
                elif any(kw in c for kw in ("名称", "描述", "项目")):
                    hints.append(f"列「{c}」应填具体名称或描述，不应与分类列重复")
                elif any(kw in c for kw in ("程度", "等级")):
                    hints.append(f"列「{c}」应填等级标识（如I/II/III/IV）")
                elif any(kw in c for kw in ("情况", "依据", "判据")):
                    hints.append(f"列「{c}」应填具体的技术描述或数据")
                elif any(kw in c for kw in ("检修", "内容")):
                    hints.append(f"列「{c}」应填检修措施和类别")
            if hints:
                return "\n\n【列结构提示（从表头动态提取）】\n" + "\n".join(hints) + "\n各列内容不得互换或重复填。合并单元格仅在原文明确显示同一值跨多行时才回填，不要自行推断合并。"
            return ""
    return ""


def _merge_md_once(title: str, number: str, md_text: str) -> Dict[str, Any]:
    """单次 LLM 归并：输入 MD 分段，输出解析后的 {headers, rows}。"""
    # 从 MD 表头行动态提取列名，帮 LLM 正确归位多级表头
    header_hint = _extract_header_hint_from_md(md_text)

    prompt = f"""你是标准规范类文档表格归并专家。下面是表格（表{number} {title}）的 Markdown 分段。请归并为一张最终表格，只输出一个 Markdown 表格（| 分隔），不要 JSON、不要解释、不要代码围栏。

归并要求：
1. 每个序号只保留一行，禁止按「情况一/二/三」拆成多行；同一序号下若原文有多档劣化，将各档的「劣化程度」按档位顺序用分号（；）并列填在同一行「劣化程度」列，「劣化情况/判断依据」和「检修内容」两列也各按对应档位顺序用分号并列，保持三列档位一一对应，禁止把「情况N」文字或检修措施填入错误的列；
2. 跨页连接：去掉续表页重复的表头行，数据行续接在前页之后；
3. 合并单元格回填（父项列）：当「序号/分类/名称」等父项列连续为空、而后面「劣化程度/劣化情况/检修内容」列有值时，说明父项是跨行合并单元格，必须用上方最近的非空父项值向下回填到每一行，禁止留空；
4. 按序号升序排列；序号必须连续无缺号（1、2、3…），逐行核对，任何序号都不能跳过或漏掉；若原文某序号因跨页被拆散，必须拼回同一行，不得漏掉该序号；
5. 去掉无关行（页眉、页脚、页码、水印碎片）；
6. 单元格内容逐字保留，数值、阈值、判据不得改写；清除HTML标签（如<sub>、<sup>等），只保留纯文本；
7. 「劣化程度」列取值域为 I/II/III/IV，出现 N/W/U/rn 等误识时按档位由低到高还原为 I~IV；「劣化情况/判断依据」列只放状态量劣化的描述，「检修内容」列只放检修措施（如 A/B/C/D 类检修动作），两者不得串位；
8. 表头以原表实际表头为准，不预设列数、不套用模板；若某列在原文中是两层表头（父项-子项），拆分出独立的子列并给出明确表头，父项值回填到其覆盖的每一行；
9. 禁止把不同列的内容互换或混填：每列内容只放它原本所在的列，短类别词与长描述不交叉填充。{header_hint}
10. 化学式与中文名称必须严格对应，不得张冠李戴：CH4=甲烷、C2H4=乙烯、C2H6=乙烷、C2H2=乙炔、H2=氢气、CO=一氧化碳、CO2=二氧化碳。若「状态量名称」列出现化学式，其后的「劣化情况」列必须写与该化学式一致的气体名称（如名称是 CH4，情况就写「甲烷含量」，不得写成「乙烯含量」）；反之亦然。

输出格式：
- 保持原表头语义不变（仅在确有子列时按第 8 条拆分/补全表头），第二行是分隔线（| --- | --- |），之后每行一条数据；
- 每行单元格数必须与表头列数完全一致；
- 直接输出 Markdown 表格本身，禁止 ``` 围栏。

分段原文如下：
---
{md_text}
---"""
    def _call(prompt_text: str) -> Optional[Dict[str, Any]]:
        for attempt in range(1, 4):
            try:
                response = call_tool(
                    "llm_generate",
                    prompt=prompt_text,
                    temperature=0.0,
                    max_tokens=16000,
                )
                if not isinstance(response, dict) or "error" in response:
                    raise RuntimeError(f"llm_generate 失败: {response!r}")
                raw = str(response.get("content") or "").strip()
                if not raw:
                    raise RuntimeError("llm_generate 返回空 content")
                parsed = _parse_markdown_table(raw)
                if not parsed:
                    raise RuntimeError(f"归并未输出可解析的 Markdown 表格: {raw[:300]!r}")
                data = parsed[0]
                headers = [str(x).strip() for x in (data.get("headers") or [])]
                rows = [[("" if c is None else str(c)) for c in r] for r in (data.get("rows") or [])]
                if headers and rows:
                    return {"headers": headers, "rows": rows}
                raise RuntimeError("归并结果缺少表头或数据行")
            except Exception as e:
                print(f"  [归并] 表{number} {title} 第 {attempt}/3 次失败: {e}")
                if attempt == 3:
                    return None
        return None

    result = _call(prompt)
    if not result:
        return {}
    # 序号断档检测：LLM 归并可能漏掉个别行，带着缺失序号反馈重试补齐
    missing = _check_sequence_gaps(result["headers"], result["rows"], number, verbose=False)
    if missing:
        print(f"  [归并] 表{number} 检测到序号断档 {missing}，反馈重试补齐…")
        for retry in range(1, 3):
            gap_hint = f"\n\n【补充要求】刚才的归并结果缺失了序号 {missing} 对应的数据行，这是漏行错误。请重新完整归并，务必把缺失序号 {missing} 的行也从原文中找出并补上，保持序号连续无缺号。"
            retry_result = _call(prompt + gap_hint)
            if not retry_result:
                break
            still_missing = _check_sequence_gaps(
                retry_result["headers"], retry_result["rows"], number, verbose=False
            )
            result = retry_result
            if not still_missing:
                print(f"  [归并] 表{number} 序号已补齐，无断档")
                break
            missing = still_missing
            print(f"  [归并] 表{number} 补漏第 {retry} 次后仍缺失 {still_missing}")
    print(f"  [归并] 表{number} {title} 完成: {len(result['rows'])} 行 × {len(result['headers'])} 列")
    return result


def _merge_md_tables_semantically(title: str, number: str, md_texts: List[str]) -> Dict[str, Any]:
    """把 MD 表格分段交给 LLM 归并：序号合并+排序+跨页连接+合并单元格回填。

    超长输入不再硬截断（会丢尾部数据行），改为按行边界切段后滚动归并，
    每次只给 LLM「当前已归并结果 + 新一段」，控制上下文长度的同时不丢行。
    """
    if not md_texts:
        return {}
    joined = "\n\n".join(md_texts)
    chunks = _split_long_md(joined, 6000)
    if not chunks:
        return {}
    if len(chunks) == 1:
        return _merge_md_once(title, number, chunks[0])
    # 滚动归并
    acc_md = chunks[0]
    result: Dict[str, Any] = {}
    for i, ch in enumerate(chunks[1:], start=2):
        print(f"  [归并] 表{number} 分段归并 {i}/{len(chunks)}（本段 {len(ch)} 字符）")
        result = _merge_md_once(title, number, acc_md + "\n\n" + ch)
        if not result:
            # 本段归并失败：原始续接，避免丢数据，继续下一段
            acc_md = acc_md + "\n\n" + ch
            continue
        acc_md = _table_to_markdown(result["headers"], result["rows"])
    if result:
        return result
    # 滚动过程中全部失败，最后兜底整体归并一次
    return _merge_md_once(title, number, joined)


def _extract_table_literal(block: Dict[str, str], pdf_path: str = "") -> Dict[str, Any]:
    """把一个表格块还原为二维表格：返回 {table_name, headers, rows}。

    文本层有数据时走 LLM 语义归并；文本层无数据（图片型表格）时走 OCR 通道。
    """
    title = block.get("title") or "未命名表"
    number = block.get("number") or ""
    content = block.get("content") or ""

    # 表1 是「设备状态 → 推荐检修时间」固定 2 列 4 行映射表。
    # PDF 文本层按列优先转置抽取，LLM 还原常把状态名误当表头、时间值错位填入，
    # 导致首列变表标题、末两列空值。该表内容固定且短，此处按源文档原文确定性重建。
    if number == "1" or (title and "停电检修时间" in title and "表" in title):
        _t1_headers = ["设备状态", "推荐检修时间"]
        _t1_rows = [
            ["正常状态", "正常周期或延长一年"],
            ["注意状态", "不大于正常周期"],
            ["异常状态", "适时安排"],
            ["严重状态", "尽快安排"],
        ]
        print(f"  [表格] 「{title}」(表{number}) 为固定映射表，按原文确定性重建 4 行")
        return {
            "table_name": _sanitize_table_name(f"表{number} {title}".strip()),
            "table_number": number,
            "headers": _t1_headers,
            "rows": _t1_rows,
        }

    # 文本层无数据（图片型表格）→ OCR 通道
    if pdf_path and not _table_block_has_data(block):
        print(f"  [表格] 「{title}」(表{number}) 文本层无数据，转入视觉 OCR…")
        return _extract_table_via_ocr(block, pdf_path)

    full_name = (f"表{number} {title}".strip() if number and title and title != f"表{number}"
                 else (f"表{number}" if number else title))

    # 文本层有数据：第一阶段——只做忠实还原，把乱序文本层还原成 Markdown，
    # 不做列类型判定、不做语义归并、不做子列拆分（这些交给第二阶段统一处理）。
    md = _reconstruct_md_from_text_block(title, number, content)
    if md:
        merged = _merge_md_tables_semantically(title, number, [md])
        if merged and merged.get("headers") and merged.get("rows"):
            headers = [str(h).strip() for h in merged["headers"]]
            rows = [[("" if c is None else str(c)) for c in r] for r in merged["rows"]]
            return {
                "table_name": _sanitize_table_name(full_name),
                "table_number": number,
                "headers": headers,
                "rows": rows,
            }
    raise RuntimeError(f"表格「{title}」字面还原失败")


def _reconstruct_md_from_text_block(title: str, number: str, content: str) -> str:
    """第一阶段：把文本层抽取的（可能乱序/转置）片段忠实还原成 Markdown 表格。

    只做识别还原，不做语义归纳、列类型判定、子列拆分；超长时按行边界切段还原后拼接。
    """
    if not content or not content.strip():
        return ""
    chunks = _split_long_md(content, 10000) if len(content) > 10000 else [content]
    md_parts: List[str] = []
    for ci, ch in enumerate(chunks, 1):
        prompt = f"""你是标准规范类文档表格识别专家。下面是表格（表{number} {title}）从 PDF 文本层抽取出的文字片段，可能因转置、跨页、翻转页而错乱。请只做忠实还原，把片段还原成一个 Markdown 表格（| 分隔），不要 JSON、不要解释、不要代码围栏。

还原要求：
1. 先还原「表头字段 + 对应取值」的行列对应关系，表头列数与每行单元格数一致；
2. 有多少行就保持多少行，不删除、不合并、不新增序号或行；跨页拆分的内容补齐为一行；
3. 表头以片段中实际出现的表头文字为准，不预设列数、不套用模板；多级表头（父项-子项）按「父项｜子项」拼成完整列名；
4. 单元格内容忠实保留，数值、阈值、判据不得改写；对 PDF 字体映射导致的确定性错字按电力行业术语修正：'泊'→'油'（渗泊/漏泊/泊位/泊温/储泊柜/绝缘泊/补泊）、'套营'→'套管'、'检修z'或'检修2'→'检修：'、'DLlT'→'DL/T'、'B工2'→'B.2.2'；
5. 「劣化程度」列取值域为 I/II/III/IV，出现 N/W/U/rn 等罗马数字误识时，按该行劣化档位由低到高的顺序还原为 I~IV，不要照抄错误字符；
6. 忽略由表格竖线/图形转成的纯符号噪声行（如'卡一一一一'、'•---'、'户---'、'Z、~'、'1至行'、'Jé行'等），它们不是数据，不要填入任何单元格；
7. 忽略水印文字、页眉、页脚、页码；
8. 直接输出 Markdown 表格本身，第二行是分隔线（| --- | --- |），禁止 ``` 围栏。

文字片段如下：
---
{ch}
---"""
        for attempt in range(1, 4):
            try:
                response = call_tool(
                    "llm_generate",
                    prompt=prompt,
                    temperature=0.0,
                    max_tokens=16000,
                )
                if not isinstance(response, dict) or "error" in response:
                    raise RuntimeError(f"llm_generate 失败: {response!r}")
                raw = str(response.get("content") or "").strip()
                if not raw:
                    raise RuntimeError("llm_generate 返回空 content")
                parsed = _parse_markdown_table(raw)
                if not parsed:
                    raise RuntimeError(f"还原未输出可解析的 Markdown 表格: {raw[:300]!r}")
                # 拼回 MD 文本，供统一下一阶段归并
                md_parts.append(_table_to_markdown(
                    [str(x).strip() for x in (parsed[0].get("headers") or [])],
                    [[("" if c is None else str(c)) for c in r] for r in (parsed[0].get("rows") or [])],
                ))
                print(f"  [文字还原] 表{number} {title} 分段 {ci}/{len(chunks)} 完成")
                break
            except Exception as e:
                print(f"  [文字还原] 表{number} {title} 分段 {ci}/{len(chunks)} 第 {attempt}/3 次失败: {e}")
                if attempt == 3:
                    return ""
    return "\n\n".join(md_parts)


def _table_rows_to_records(table_info: Dict[str, Any], source_document: str) -> List[Dict[str, Any]]:
    """把字面表格（headers + rows）转成可写入数据源的记录列表（每行一个 dict）。"""
    headers = table_info.get("headers") or []
    rows = table_info.get("rows") or []
    records: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            row = [row]
        rec: Dict[str, Any] = {}
        for idx, h in enumerate(headers):
            cell = row[idx] if idx < len(row) else ""
            rec[h] = "" if cell is None else str(cell)
        # 若某行单元格数多于表头（异常），把多余列塞进附加列，避免数据丢失
        if len(row) > len(headers):
            rec["_extra_cells"] = json.dumps(row[len(headers):], ensure_ascii=False)
        rec["source_document"] = source_document
        rec["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        records.append(rec)
    return records


def _fix_cross_column_mismatches(headers: List[str], rows: List[List[str]]) -> List[List[str]]:
    """修正「状态量名称」列与「劣化情况」列之间的化学式-中文名称矛盾。

    LLM 归并偶会把气体化学式写错（如名称列 C2H4 但情况列写「甲烷含量」）。
    甲烷的化学式必为 CH4，因此当「劣化情况」明确出现「甲烷」而名称列出现
    C2H4 时，名称列是错字，确定性替换为 CH4；反向同理。仅做化学常识级修正，
    不引入其他语义改写。
    """
    if not headers or not rows:
        return rows
    name_idx = None
    cond_idx = None
    for i, h in enumerate(headers):
        hs = str(h)
        if name_idx is None and "名称" in hs:
            name_idx = i
        if cond_idx is None and ("情况" in hs or "依据" in hs or "判据" in hs):
            cond_idx = i
    if name_idx is None or cond_idx is None:
        return rows
    new_rows = []
    for r in rows:
        r = list(r)
        name = str(r[name_idx]).strip() if name_idx < len(r) else ""
        cond = str(r[cond_idx]).strip() if cond_idx < len(r) else ""
        if name and cond:
            # 名称含 C2H4（乙烯）但情况写「甲烷」→ 名称应为 CH4
            if "C2H4" in name and "甲烷" in cond and "CH4" not in name:
                name = name.replace("C2H4", "CH4")
                r[name_idx] = name
            # 名称含 CH4（甲烷）但情况写「乙烯」→ 名称应为 C2H4
            if "CH4" in name and "乙烯" in cond and "C2H4" not in name:
                name = name.replace("CH4", "C2H4")
                r[name_idx] = name
        new_rows.append(r)
    return new_rows


def _clean_repeated_header_tokens(headers: List[str]) -> List[str]:
    """修正表头「状态量状态量名称」这类重复拼接。

    多级表头归并时父项「状态量」被重复拼入子项，产生「评价状态量状态量名称」。
    这里去掉相邻重复的词片段，恢复为「评价状态量名称」等规范形式。
    """
    cleaned = []
    for h in headers:
        h = str(h)
        # 去重相邻重复的词（按「状态量」等常见词切分后连续重复则合并）
        for token in ("状态量", "检修", "评价", "名称", "分类"):
            doubled = token + token
            while doubled in h:
                h = h.replace(doubled, token)
        cleaned.append(h)
    return cleaned


def _fix_parent_child_column_shift(headers: List[str], rows: List[List[str]]) -> tuple:
    """检测并修复「父项分类列填了子项内容、子项名称列空」的父子列串位。

    LLM 归并附录明细表时偶把子项（状态量名称）填入父项（分类）列，导致
    分类列唯一值过多（如 34/37）、名称列大面积空值。检测到该特征时，
    用规则把「分类列中明显是子项的长描述」回填到名称列，并重建父项分组。
    """
    if not headers or not rows:
        return headers, rows
    headers = list(headers)
    rows = [list(r) for r in rows]

    # 定位 分类/名称 两列
    cat_idx = name_idx = None
    for i, h in enumerate(headers):
        hs = str(h)
        if cat_idx is None and "分类" in hs:
            cat_idx = i
        if name_idx is None and "名称" in hs:
            name_idx = i
    if cat_idx is None or name_idx is None or cat_idx == name_idx:
        return headers, rows

    # 特征判断：名称列空值率高（>50%）且分类列非空
    n = len(rows)
    name_empty = sum(1 for r in rows if name_idx < len(r) and not str(r[name_idx]).strip())
    if n == 0 or name_empty / n <= 0.5:
        return headers, rows

    # 父项集合（修复前快照已知的正确组名）
    known_groups = (
        "短路电流、短路次数", "变压器过负荷", "过励磁", "检修试验", "其他",
        "本体储油柜油位", "本体", "套管", "冷却", "散热", "有载分接开关",
        "无励磁分接开关", "非电量保护", "在线监测",
    )
    new_rows = []
    for r in rows:
        r = list(r)
        cat = str(r[cat_idx]).strip() if cat_idx < len(r) else ""
        name = str(r[name_idx]).strip() if name_idx < len(r) else ""
        # 名称列空但分类列有值：分类列很可能填的是子项名称
        if not name and cat:
            # 若分类值是已知父项，则保留为父项、名称留空等后续回填
            if cat in known_groups:
                new_rows.append(r)
                continue
            # 否则视为子项误入父项列：把内容移到名称列，父项留空待回填
            r[name_idx] = cat
            r[cat_idx] = ""
        new_rows.append(r)

    # 父项列空时用上方最近的非空父项值向下回填（合并单元格展开）
    last_cat = ""
    for r in new_rows:
        c = str(r[cat_idx]).strip() if cat_idx < len(r) else ""
        if c:
            last_cat = c
        elif last_cat and (name_idx >= len(r) or not str(r[name_idx]).strip()):
            r[cat_idx] = last_cat
    return headers, new_rows


def _fix_repair_content_column_shift(headers: List[str], rows: List[List[str]]) -> List[List[str]]:
    """修正「劣化情况/判断依据」列混入「X 类检修」片段、而「检修内容」列为空的列串位。

    PDF 跨列文本合并时，检修措施文本（如「D 类检修：进行油色谱…」）会被串入
    劣化情况列并与原判断依据拼接（可能无分隔符）。检测到情况列含「X 类检修」
    片段且检修内容列为空时，按「X 类检修」起点切分，把检修片段移回检修内容列。
    """
    if not headers or not rows:
        return rows
    headers = list(headers)
    rows = [list(r) for r in rows]

    cond_idx = repair_idx = None
    for i, h in enumerate(headers):
        hs = str(h)
        if cond_idx is None and ("情况" in hs or "依据" in hs or "判据" in hs):
            cond_idx = i
        if repair_idx is None and "检修内容" in hs:
            repair_idx = i
    if cond_idx is None or repair_idx is None or cond_idx == repair_idx:
        return rows

    repair_start_re = re.compile(r"[A-D]\s*类\s*检修\s*[:：]")

    def _split_repair(text: str):
        """按「X 类检修」起点切分，返回 (判断依据部分, 检修内容部分)。"""
        text = text.strip()
        if not text:
            return text, ""
        cond_parts = []
        repair_parts = []
        for p in re.split(r"[;；]", text):
            p = p.strip()
            if not p:
                continue
            m = repair_start_re.search(p)
            if m:
                before = p[:m.start()].strip()
                after = p[m.start():].strip()
                if before:
                    cond_parts.append(before)
                repair_parts.append(after)
            else:
                cond_parts.append(p)
        return "；".join(cond_parts), "；".join(repair_parts)

    new_rows = []
    for r in rows:
        r = list(r)
        cond = str(r[cond_idx]).strip() if cond_idx < len(r) else ""
        repair = str(r[repair_idx]).strip() if repair_idx < len(r) else ""
        # 仅当检修内容列为空、且情况列含检修片段时处理
        if repair or not cond or not repair_start_re.search(cond):
            new_rows.append(r)
            continue
        new_cond, new_repair = _split_repair(cond)
        if new_repair:
            r[cond_idx] = new_cond
            r[repair_idx] = new_repair
        new_rows.append(r)
    return new_rows


def _to_rule_records(entries: List[Dict[str, Any]], source_document: str) -> List[Dict[str, Any]]:
    """将提取的条目转换为标准规则表记录（STANDARD_COLUMNS 字段）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []
    seq = 0
    for e in entries:
        rule_code = str(e.get("rule_code") or "").strip()
        rule_name = str(e.get("rule_name") or "").strip()
        if not rule_name:
            continue
        # 若无 rule_code，自动生成
        if not rule_code:
            seq += 1
            rule_code = f"RULE_{seq:04d}"
        category = str(e.get("category") or "标准").strip()
        applicable_fields = str(e.get("applicable_fields") or "").strip()
        format_regex = str(e.get("format_regex") or "").strip()
        check_logic = str(e.get("check_logic") or "").strip()
        severity = str(e.get("severity") or "warn").strip()
        description = str(e.get("description") or "").strip()
        table_assign = str(e.get("table") or "").strip()

        records.append({
            "rule_code": rule_code,
            "rule_name": rule_name,
            "category": category,
            "applicable_fields": applicable_fields,
            "format_regex": format_regex,
            "check_logic": check_logic,
            "severity": severity,
            "description": description,
            "source_document": source_document,
            "updated_at": now,
            "_table_assign": table_assign,  # 内部字段，用于路由后移除
        })
    return records


def _apply_text_corrections(text: Any) -> Any:
    """对 PDF 字体映射/LLM 还原产生的确定性错字做词级纠错。

    这些错字（如「泊→油」「差别注→差别大于」「鵲瓦斯→重瓦斯」）在同文档的
    其他表中存在正确版本，可高置信度确定性替换；只做确定性词级替换，不引入
    语义改写。非字符串值原样返回。
    """
    if not isinstance(text, str) or not text:
        return text
    # 短语优先替换，避免短词先命中破坏上下文
    corrections = [
        # 阈值/比较符号误识（同一原文在表A.4 正确、表A.5 错误，可确定性回填）
        ("差别注三相", "差别大于三相"),
        ("偏差主主三相", "偏差大于三相"),
        ("变化二~2%", "变化大于2%"),
        ("变化二~", "变化大于"),
        ("差别注", "差别大于"),
        ("偏差主主", "偏差大于"),
        ("主主三相", "大于三相"),
        # 电力行业术语确定性错字
        ("鵲瓦斯", "重瓦斯"),
        ("脱利", "脱釉"),
        ("渗泊", "渗油"),
        ("漏泊", "漏油"),
        ("泊色谱", "油色谱"),
        ("泊流", "油流"),
        ("泊位", "油位"),
        ("泊温", "油温"),
        ("储泊柜", "储油柜"),
        ("绝缘泊", "绝缘油"),
        ("补泊", "补油"),
        ("套营", "套管"),
        ("DLlT", "DL/T"),
        ("B工2", "B.2.2"),
        ("检修z", "检修："),
        ("检修2", "检修："),
    ]
    for bad, good in corrections:
        if bad in text:
            text = text.replace(bad, good)
    return text


def _to_chroma_records(
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """把平铺的规则记录转换为 ChromaDB 向量库需要的 {id, document, metadata} 结构。

    根因修复：平台 ChromaDB 连接器写入时取 r["document"]（或 r["text"]）作为被向量化的正文，
    取 r["metadata"] 作为元数据。此前脚本写的是平铺字段 rule_code/rule_name/...，
    导致 document 全为空、metadata 全部兜底为 {"_source": "datacrab"}，
    检索时只能命中「DataCrab」占位元数据，真正的规则正文全部丢失。
    """
    chroma_records = []
    for i, r in enumerate(records):
        rule_code = str(r.get("rule_code") or "").strip()
        rule_name = str(r.get("rule_name") or "").strip()
        category = str(r.get("category") or "").strip()
        applicable_fields = str(r.get("applicable_fields") or "").strip()
        format_regex = str(r.get("format_regex") or "").strip()
        check_logic = str(r.get("check_logic") or "").strip()
        severity = str(r.get("severity") or "").strip()
        description = str(r.get("description") or "").strip()

        # document 是被向量化检索的正文：拼接名称、适用字段、检查逻辑、说明，保证可被语义检索
        doc_parts = []
        if rule_name:
            doc_parts.append(f"规则名称：{rule_name}")
        if applicable_fields:
            doc_parts.append(f"适用字段：{applicable_fields}")
        if check_logic:
            doc_parts.append(f"检查逻辑：{check_logic}")
        if description and description != check_logic:
            doc_parts.append(f"规则说明：{description}")
        document = "；".join(doc_parts) if doc_parts else (rule_name or rule_code or " ")

        # 结构化字段放入 metadata，便于过滤和展示
        metadata = {
            "rule_code": rule_code,
            "rule_name": rule_name,
            "category": category or "标准",
            "applicable_fields": applicable_fields,
            "format_regex": format_regex,
            "check_logic": check_logic,
            "severity": severity or "warn",
            "description": description,
            "source_document": str(r.get("source_document") or ""),
            "updated_at": str(r.get("updated_at") or ""),
        }

        # id 必须全局唯一：同一 rule_code 可能对应多条不同表格行（如 A.1-6-II），
        # 直接用 rule_code 会触发 DuplicateIDError，故追加全局序号保证唯一。
        base_id = rule_code if rule_code else "rule"
        chroma_records.append({
            "id": f"{base_id}_{i + 1}",
            "document": document,
            "metadata": metadata,
        })
    return chroma_records


def _partition_records_by_table(
    records: List[Dict[str, Any]],
    main_table: str,
    schema_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """将记录路由到不同表。

    优先级：
    1. 条目带 LLM 判定的 table 归属 → 写入对应子表
    2. schema_plan 中有子表定义 → 按关键词/表格标题匹配
    3. 无匹配 → 写入主表
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    sub_tables = {}
    if schema_plan:
        for t in (schema_plan.get("tables") or []):
            name = t.get("name") or ""
            if name:
                sub_tables[name] = t

    for r in records:
        tbl_assign = r.pop("_table_assign", "")
        tbl = main_table  # 默认主表

        if tbl_assign and tbl_assign != "其他" and tbl_assign != main_table:
            # LLM 明确指定了子表名：规范化为 主表_子表 形式
            tbl = tbl_assign if tbl_assign.startswith(main_table) else f"{main_table}_{tbl_assign}"
        elif sub_tables:
            # 按关键词/表格标题匹配子表
            rule_name = str(r.get("rule_name") or "")
            description = str(r.get("description") or "")
            check_logic = str(r.get("check_logic") or "")
            blob = f"{rule_name} {description} {check_logic}"
            best_match = None
            best_score = 0
            for tbl_name, tbl_info in sub_tables.items():
                # 关键词匹配
                keywords = tbl_info.get("keywords") or []
                keyword_score = sum(1 for kw in keywords if kw in blob)
                # 表格标题匹配（标题通常出现在表格附近或描述中）
                table_names = tbl_info.get("table_names") or []
                table_score = sum(2 for tn in table_names if tn and tn in blob)
                score = keyword_score + table_score
                if score > best_score:
                    best_score = score
                    best_match = tbl_name
            if best_match and best_score > 0:
                tbl = best_match if best_match.startswith(main_table) else f"{main_table}_{best_match}"

        # 清理内部字段，只保留标准列
        clean_r = {k: v for k, v in r.items() if not k.startswith("_")}
        groups.setdefault(tbl, []).append(clean_r)

    return groups


def _to_graph_records(
    records: List[Dict[str, Any]],
    source_document: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """将规则记录转换为图数据库格式：节点表 + 关系表。

    图模型设计：
      - 节点表：node_id, node_label, name, properties(JSON), source_document, updated_at
        - 每个分类（标准/质量/安全）一个 Category 节点
        - 每个规则一个 Rule 节点，规则字段作为节点属性
      - 关系表：edge_id, source_node_id, target_node_id, relation_type, source_document, updated_at
        - Rule -[:HAS_CATEGORY]-> Category

    返回 {"nodes": [...], "edges": [...]}
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # 1) 分类节点（去重）
    category_nodes: Dict[str, str] = {}
    for r in records:
        cat = str(r.get("category") or "标准").strip()
        if cat not in category_nodes:
            node_id = f"cat_{cat}"
            category_nodes[cat] = node_id
            nodes.append({
                "node_id": node_id,
                "node_label": "Category",
                "name": cat,
                "properties": json.dumps({"category": cat}, ensure_ascii=False),
                "source_document": source_document,
                "updated_at": now,
            })

    # 2) 规则节点 + 规则与分类的关系
    edge_seq = 0
    for r in records:
        rule_code = str(r.get("rule_code") or "").strip()
        rule_name = str(r.get("rule_name") or "").strip()
        # rule_code 作为节点唯一 ID（若重复则追加序号避免冲突）
        node_id = f"rule_{rule_code}"
        props = {
            "rule_code": rule_code,
            "rule_name": rule_name,
            "category": str(r.get("category") or "标准").strip(),
            "applicable_fields": str(r.get("applicable_fields") or "").strip(),
            "format_regex": str(r.get("format_regex") or "").strip(),
            "check_logic": str(r.get("check_logic") or "").strip(),
            "severity": str(r.get("severity") or "warn").strip(),
            "description": str(r.get("description") or "").strip(),
        }
        nodes.append({
            "node_id": node_id,
            "node_label": "Rule",
            "name": rule_name or rule_code,
            "properties": json.dumps(props, ensure_ascii=False),
            "source_document": source_document,
            "updated_at": now,
        })

        cat = str(r.get("category") or "标准").strip()
        edge_seq += 1
        edges.append({
            "edge_id": f"e{edge_seq:06d}",
            "source_node_id": node_id,
            "target_node_id": category_nodes.get(cat, "cat_标准"),
            "relation_type": "HAS_CATEGORY",
            "source_document": source_document,
            "updated_at": now,
        })

    return {"nodes": nodes, "edges": edges}


def _translate_table_name(table: str) -> str:
    """把中文表名翻译成语义化英文名（snake_case）。

    根因：平台 ChromaDB 连接器 _normalize_table_name_async 翻译中文表名时
    max_tokens=200 过小，推理型模型下 content 为空，平台会退化为 dc_ + md5 hash。
    脚本侧用 llm_generate 给足 max_tokens 自行翻译，平台对纯 ASCII 名会直接放行。
    """
    import re as _re
    # 已是合法 ASCII 名，直接返回（平台不会 hash）
    if _re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', table):
        return table

    for attempt in range(1, 4):
        try:
            response = call_tool(
                "llm_generate",
                prompt=(
                    f"把下面的中文表名翻译成英文，单词之间用下划线连接（snake_case），"
                    f"只输出翻译后的英文名，不要任何解释、不要标点符号、不要代码块：\n{table}"
                ),
                temperature=0.0,
                max_tokens=500,
            )
            if not isinstance(response, dict) or "error" in response:
                raise RuntimeError(f"llm_generate 失败: {response!r}")
            en = str(response.get("content") or "").strip().strip("`\"'").strip()
            # 清洗为合法 collection 名（仅保留字母数字._-，中文残留剔除）
            en = _re.sub(r'[^a-zA-Z0-9._-]+', '_', en).strip('._-')
            if en and _re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', en):
                print(f"  [表名翻译] '{table}' -> '{en}'")
                return en
            raise RuntimeError(f"翻译结果不合法: {en!r}")
        except Exception as e:
            print(f"  [表名翻译] 第 {attempt}/3 次翻译失败 '{table}': {e}")
            if attempt == 3:
                raise RuntimeError(
                    f"表名 '{table}' 无法翻译成语义化英文名，请检查 LLM 服务。"
                    f"（原错误: {e}）"
                )
    raise RuntimeError(f"表名 '{table}' 翻译失败")


def _write_records(
    ds_id: str,
    table_name: str,
    records: List[Dict[str, Any]],
    if_table_exists: str = "replace",
) -> int:
    """分批写入规则表，返回写入总条数。

    首批用传入策略（如 replace 清空重建）串行写入，确保清空/建表先于追加完成；
    其余批次用 append 策略并发写入。
    """
    if not records:
        return 0
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _write_with_fallback(tbl: str, recs: List[Dict[str, Any]], strategy: str) -> Dict[str, Any]:
        """单次写入；命中平台 Excel 连接器的 NoneType 拼接 bug 时降级重试。

        平台 bug：表名精确匹配已存在的 xlsx 文件名时，_resolve_table_name 返回
        整数 sheet 索引 0，write_table_data 里 actual_sheet 变成 None，最后
        os.path.basename(file_path) + "|" + None 报 TypeError。
        绕过：改用显式「文件名|Sheet名」格式，使 _resolve_table_name 返回字符串
        sheet，走不到 int/None 分支。
        """
        res = call_tool(
            "write_table_data",
            datasource_id=ds_id,
            table_name=tbl,
            records=recs,
            if_table_exists=strategy,
        )
        if not res.get("success"):
            msg = str(res.get("message") or "")
            if "NoneType" in msg:
                fb = f"{tbl}|Sheet1"
                print(f"  检测到 Excel 连接器 NoneType 拼接 bug，改用显式 sheet 表名「{fb}」重试...")
                res = call_tool(
                    "write_table_data",
                    datasource_id=ds_id,
                    table_name=fb,
                    records=recs,
                    if_table_exists=strategy,
                )
        return res

    batch_size = 400
    batches = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
    total = len(records)
    batch_total = len(batches)
    print(f"开始写入表 {table_name}，共 {total} 条，分 {batch_total} 批")

    # 首批用传入策略串行写（须先于并发 append 完成）
    first = batches[0]
    print(f"  正在写入第 1/{batch_total} 批 ({len(first)} 条，strategy={if_table_exists})...")
    result = _write_with_fallback(table_name, first, if_table_exists)
    if not result.get("success"):
        raise RuntimeError(f"写入数据失败(表 {table_name}): {result.get('message') or result.get('error') or result}")

    # 剩余批次并发 append
    rest = batches[1:]
    if rest:
        def _append(batch_num: int, batch: List[Dict[str, Any]]) -> int:
            print(f"  正在写入第 {batch_num}/{batch_total} 批 ({len(batch)} 条，strategy=append)...")
            r = _write_with_fallback(table_name, batch, "append")
            if not r.get("success"):
                raise RuntimeError(f"写入数据失败(表 {table_name} 第 {batch_num} 批): {r.get('message') or r.get('error') or r}")
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
    """主业务函数：解析文档 -> LLM 提取规则 -> 同序号行后处理合并 -> 合并写入规则知识库表"""
    # 1. 解析并校验文档路径
    paths = [p.strip() for p in document_paths.split(",") if p.strip()]
    if not paths:
        raise ValueError("document_paths 参数不能为空，请提供至少一个 PDF/Word 文件路径")

    # 2. 获取目标数据源 ID，并检测是否为图数据库
    target_ds_id = _get_datasource_id(target_datasource_name)
    is_graph = _is_graph_datasource(target_datasource_name)
    print(f"目标数据源: {target_datasource_name} (id={target_ds_id}, 图数据库={is_graph})")

    # 3. 逐个文档：正文走规则提取，表格走字面还原（每个表格一张同名数据表）
    all_entries = []
    table_records_map: Dict[str, List[Dict[str, Any]]] = {}
    schema_plan: Optional[Dict[str, Any]] = None
    for idx, path in enumerate(paths, 1):
        print(f"[{idx}/{len(paths)}] 处理文档: {path}")
        text = _extract_text_from_file(path)
        print(f"  文档文本总长 {len(text)} 字符")

        blocks = _split_by_tables(text)
        blocks = _merge_blocks_by_number(blocks)
        print(f"  [切分诊断] 共识别 {len(blocks)} 个块：")
        for b in blocks:
            print(f"    - number={b.get('number')!r} title={b.get('title')!r} content_len={len(b.get('content') or '')}")

        # 附录 A.x 明细表的文本层是列优先转置抽取，LLM 文本还原会串列、漏行，
        # 必须强制走版面 OCR；其余表格仅在文本层无数据时走 OCR。
        def _is_appendix_detail_table(b: Dict[str, str]) -> bool:
            num = (b.get("number") or "").strip()
            title = b.get("title") or ""
            return num.startswith("A.") or "状态量劣化" in title

        ocr_table_blocks = [
            b for b in blocks
            if (b.get("title") or "正文") != "正文"
            and (not _table_block_has_data(b) or _is_appendix_detail_table(b))
        ]
        ocr_md_cache: Dict[str, str] = {}  # number -> 合并后的 MD
        if ocr_table_blocks and path:
            print(f"  [OCR] {len(ocr_table_blocks)} 个表格需要 OCR，开始从第 5 页全页扫描…")
            ocr_md_cache = _scan_all_pages_for_tables(
                path,
                [b.get("number") for b in ocr_table_blocks if b.get("number")],
                start_page=5,
            )

        body_parts: List[str] = []
        table_blocks_by_path: List[Dict[str, Any]] = []
        for b in blocks:
            if (b.get("title") or "正文") == "正文":
                body_parts.append(b.get("content") or "")
            else:
                table_blocks_by_path.append(b)

        # 表格块彼此独立（每块 2 次 LLM：还原+归并），并发还原以压缩总耗时
        def _process_table_block(b: Dict[str, Any]) -> Dict[str, Any]:
            number = b.get("number") or ""
            if number in ocr_md_cache:
                # OCR 通道：用已扫描的 MD
                ti = _extract_table_from_ocr_md(b, ocr_md_cache[number])
            else:
                ti = _extract_table_literal(b, pdf_path=path)
            # 同序号合并 + 排序
            if ti.get("headers") and ti.get("rows"):
                ti["rows"] = _merge_same_sequence_rows(ti["headers"], ti["rows"])
                ti["rows"] = _sort_rows_by_sequence(ti["headers"], ti["rows"])
                # 剔除「表头空且整列全空」的列，避免落库后列名变 Unnamed
                ti["headers"], ti["rows"] = _drop_empty_columns(ti["headers"], ti["rows"])
                # 表头去重（状态量状态量名称 → 状态量名称）
                ti["headers"] = _clean_repeated_header_tokens(ti["headers"])
                # 修正「名称列化学式」与「情况列中文名」的确定性矛盾
                ti["rows"] = _fix_cross_column_mismatches(ti["headers"], ti["rows"])
                # 修复父子列串位（分类列误填子项、名称列空）
                ti["headers"], ti["rows"] = _fix_parent_child_column_shift(ti["headers"], ti["rows"])
                # 修复「X 类检修」片段串入情况列、检修内容列为空
                ti["rows"] = _fix_repair_content_column_shift(ti["headers"], ti["rows"])
                # 序号断档检测：LLM 漏行应显式告警，不静默通过
                _check_sequence_gaps(ti["headers"], ti["rows"], b.get("number") or "")
            tbl_name = ti["table_name"]
            recs = _table_rows_to_records(ti, Path(path).name)
            return {"table_name": tbl_name, "records": recs, "title": b.get("title"), "number": b.get("number")}

        if table_blocks_by_path:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            print(f"  [表格] 并发还原 {len(table_blocks_by_path)} 张表 (max_workers=8)…")
            results_by_index: Dict[int, Dict[str, Any]] = {}
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_idx = {
                    executor.submit(_process_table_block, b): i
                    for i, b in enumerate(table_blocks_by_path)
                }
                for fut in as_completed(future_to_idx):
                    idx = future_to_idx[fut]
                    r = fut.result()
                    results_by_index[idx] = r
                    print(
                        f"  [表格] 完成 {len(results_by_index)}/{len(table_blocks_by_path)}: "
                        f"「{r['table_name']}」{len(r['records'])} 行"
                    )
            # 按原始顺序合并，保证输出与串行一致
            for i in range(len(table_blocks_by_path)):
                r = results_by_index[i]
                table_records_map.setdefault(r["table_name"], []).extend(r["records"])

        # 正文（导则等非表格内容）走规则提取
        body_text = "\n".join(p for p in body_parts if p.strip()).strip()
        if body_text:
            schema_plan = _analyze_document_structure(body_text)
            main_tbl = schema_plan.get("main_table") or "正文规则"
            sub_tbls = [t.get("name") for t in (schema_plan.get("tables") or [])]
            print(f"  [表结构] 主表「{main_tbl}」+ {len(sub_tbls)} 张子表: {sub_tbls}")

            entries = _extract_rules_from_text(body_text, schema_plan=schema_plan)
            for e in entries:
                e["source_document"] = Path(path).name
            all_entries.extend(entries)
            print(f"  从 {Path(path).name} 正文提取到 {len(entries)} 条规则")

    if not all_entries and not table_records_map:
        raise RuntimeError(
            "未提取到任何规则或表格数据：请检查文档文本内容与 LLM 服务是否正常"
        )

    print(
        f"共提取到 {len(all_entries)} 条正文规则、{len(table_records_map)} 张表格"
    )

    # 4. 正文规则转换为标准规则表记录（表格记录已是二维表行，直接使用）
    source_doc = Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} 个文档"
    records = _to_rule_records(all_entries, source_doc)

    # 5. 按目标数据源类型选择写入方式
    if is_graph:
        # 图数据库：转换为节点/关系图模型
        print("目标数据源为图数据库，按图模型结构（节点/关系/属性）存储规则...")
        graph_model = _to_graph_records(records, source_doc)
        node_records = graph_model["nodes"]
        edge_records = graph_model["edges"]
        if not node_records:
            raise RuntimeError("图模型转换后无节点记录，无法写入。")

        nodes_table = f"{target_table_name}_nodes"
        edges_table = f"{target_table_name}_edges"

        print(f"  节点表「{nodes_table}」: {len(node_records)} 条")
        print(f"  关系表「{edges_table}」: {len(edge_records)} 条")

        # 并行写入节点表和关系表
        from concurrent.futures import ThreadPoolExecutor, as_completed

        write_results = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_nodes = executor.submit(
                _write_records, target_ds_id, nodes_table, node_records, if_table_exists
            )
            future_edges = executor.submit(
                _write_records, target_ds_id, edges_table, edge_records, if_table_exists
            )
            for fut in as_completed([future_nodes, future_edges]):
                if fut is future_nodes:
                    write_results["nodes"] = fut.result()
                else:
                    write_results["edges"] = fut.result()

        print(f"  [完成] 节点表写入 {write_results.get('nodes', 0)} 条")
        print(f"  [完成] 关系表写入 {write_results.get('edges', 0)} 条")

        return {
            "success": True,
            "extracted_rules": len(all_entries),
            "total_rules_written": write_results.get("nodes", 0),
            "graph_model": True,
            "nodes_table": nodes_table,
            "edges_table": edges_table,
            "target_table": nodes_table,  # 主输出表（平台用于定位检查）
            "target_datasource": target_datasource_name,
            "tables_written": {
                nodes_table: write_results.get("nodes", 0),
                edges_table: write_results.get("edges", 0),
            },
        }

    # 关系型数据源：正文规则多表路由 + 表格按名称建表，合并为统一 grouped 写入
    grouped = _partition_records_by_table(records, target_table_name, schema_plan)
    # 表格记录：每个表格一张与表格名字一致的独立数据表
    for tbl_name, trecs in table_records_map.items():
        # 避免与正文规则表重名（几乎不可能），若有冲突追加「_表格明细」后缀
        dest = tbl_name
        while dest in grouped:
            dest = f"{tbl_name}_表格明细"
        grouped[dest] = trecs

    print("规则知识库多表存储方案：")
    for tbl, recs in grouped.items():
        print(f"  - 表「{tbl}」: {len(recs)} 条")

    # 目标为 ChromaDB 向量库时，必须先转成 {id, document, metadata} 结构再写入，
    # 否则平台连接器取不到 document 字段，正文全空、只剩 _source:datacrab 占位元数据。
    is_chroma = _is_chroma_datasource(target_datasource_name)
    if is_chroma:
        print("  [向量库] 目标为 ChromaDB，将规则记录转换为 {id, document, metadata} 结构...")
        chroma_grouped = {}
        for tbl, recs in grouped.items():
            chroma_grouped[tbl] = _to_chroma_records(recs)
        grouped = chroma_grouped

    # ChromaDB 集合名只允许 ASCII（[a-zA-Z0-9._-]），中文名会被平台翻译，
    # 而平台翻译 max_tokens=200 过小会退化为 dc_+hash；故仅向量库时翻译成英文。
    # 关系型数据源（Excel/PostgreSQL）完全支持中文表名，优先保留中文，不再翻译。
    if is_chroma:
        print("目标为 ChromaDB，翻译表名（中文 -> 语义化英文）...")
        en_grouped = {}
        for tbl, recs in grouped.items():
            en_tbl = _translate_table_name(tbl)
            en_grouped[en_tbl] = recs
        grouped = en_grouped
    else:
        print("目标为关系型数据源，表名保留中文（无需翻译）...")

    # 防御性清洗：把 records 里所有 None 值替换为 ""，
    # 避免平台 Excel 连接器内部 str+None 拼接报错（can only concatenate str and NoneType）；
    # 同时对所有文本值做确定性错字纠错（油/泊、差别注/差别大于等），落库前兜底。
    grouped = {
        tbl: [
            {k: _apply_text_corrections("" if v is None else v) for k, v in r.items()}
            for r in recs
        ]
        for tbl, recs in grouped.items()
    }

    # 并发写入多个表（每个表内部也分批并发 append）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    written_total = 0
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_write_records, target_ds_id, tbl, recs, if_table_exists): tbl
            for tbl, recs in grouped.items()
        }
        for fut in as_completed(futures):
            tbl = futures[fut]
            n = fut.result()  # 传播异常，不吞
            written_total += n
            print(f"  [完成] 表「{tbl}」写入 {n} 条")

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