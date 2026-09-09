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

DEFAULT_TARGET_DATASOURCE = "培训知识库"
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
    "电网数据": "e270806b-7244-40e7-b66e-11ef9423f158",
}


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


def _split_text(text: str, max_chunk: int = 6000) -> List[str]:
    """将长文本按最大长度切分为多个片段，尽量在换行或句号处断开"""
    if len(text) <= max_chunk:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chunk
        if end >= len(text):
            chunks.append(text[start:])
            break
        # 优先在换行符处断开
        split_pos = text.rfind("\n", start, end)
        if split_pos == -1 or split_pos < start + max_chunk // 2:
            # 其次在句号处断开
            split_pos = text.rfind("。", start, end)
        if split_pos == -1 or split_pos < start + max_chunk // 2:
            split_pos = end
        chunks.append(text[start:split_pos])
        start = split_pos
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


def _extract_rules_from_text(text: str, max_workers: int = 2) -> List[Dict[str, Any]]:
    """使用 LLM 并发从文本提取关键知识/规则条目（每条含 title/content/category 等）

    推理型(reasoning)模型并发能力差、单次思考久，并发过高会互相拖慢并叠加 180s 超时，
    这里控制为 2 路；切片约 2 段时 2 路正好完全并行。
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

    chunks = _split_text(text, max_chunk=6000)
    total = len(chunks)
    print(f"  [LLM提取] 文本共 {total} 段，并发 {max_workers} 路提取...")

    def _process(idx: int, chunk: str) -> tuple:
        prompt = f"""请从以下电力设备检修导则文档片段中提取关键知识和规则，直接从正文输出结果，不要输出任何思考过程或推理文字。

对每条知识/规则输出一个 JSON 对象，字段如下：
- title: 条目标题（简短，概括本条知识/规则；若原文有条款编号如 5.1.2 请保留在标题里）
- content: 条目完整内容（保留原文关键表述、数值、阈值、周期、判据，不要遗漏细节）
- category: 分类，可选：检修策略/状态量/评价标准/检修项目/试验要求/缺陷判断/安全要求/其他
- tags: 关键词，多个用逗号分隔
- severity: 重要程度，可选：high/medium/low

要求：
- 每段最多提取 4 条，只保留有实质内容的条目，忽略目录、前言、引用文件清单、过渡性语句。
- 相近的表述合并为一条，避免重复。
- 内容用简体中文精炼转述，但关键数值、阈值、周期、判据必须逐字保留。

必须只输出一个 JSON 数组（以 [ 开头、以 ] 结尾），不要输出 Markdown 代码围栏、解释或任何其他文字。

文档片段如下：
---
{chunk}
---"""
        last_err = ""
        for attempt in range(1, 4):
            response = call_tool(
                "llm_generate",
                prompt=prompt,
                temperature=0.0,
                max_tokens=4096,
            )
            if not isinstance(response, dict):
                raise RuntimeError(f"llm_generate 返回非 dict: {response!r}")
            if "error" in response:
                raise RuntimeError(f"llm_generate 调用失败: {response['error']}")
            content = str(response.get("content") or "").strip()
            if content:
                return idx, content
            last_err = f"第 {attempt} 次调用返回空 content（响应: {str(response)[:300]!r}）"
            if attempt < 3:
                print(f"    [重试] 第 {idx} 段 {last_err}，稍后重试...", flush=True)
        raise RuntimeError(
            f"{last_err}。当前模型为推理型（reasoning）模型，输出进入 reasoning_content 而 content 为空，"
            "建议在平台配置中改用非推理（non-reasoning）模型后重试。"
        )

    results_by_idx = {}
    errors = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process, idx, chunk): idx for idx, chunk in enumerate(chunks, 1)}
        done = 0
        for fut in as_completed(futures):
            idx = futures[fut]
            done += 1
            try:
                _, content = fut.result()
                parsed = _parse_llm_json(content)
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

    # 按 title 去重，保留 content 更完整的条目
    unique = {}
    for e in all_entries:
        title = str(e.get("title") or "").strip()
        if not title:
            continue
        cur_len = len(str(e.get("content") or ""))
        old_len = len(str(unique.get(title, {}).get("content") or ""))
        if title not in unique or cur_len > old_len:
            unique[title] = e
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
                "tags": tags,
                "severity": severity,
                "source_document": source_document,
                "updated_at": now,
            },
        })
    return records


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

    # 3. 逐个文档提取关键知识与规则
    all_entries = []
    for idx, path in enumerate(paths, 1):
        print(f"[{idx}/{len(paths)}] 处理文档: {path}")
        text = _extract_text_from_file(path)
        print(f"  文档文本总长 {len(text)} 字符")
        entries = _extract_rules_from_text(text)
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

    # 5. 写入目标集合
    written = _write_chroma(target_ds_id, target_table_name, records, if_table_exists)

    return {
        "success": True,
        "extracted_rules": len(all_entries),
        "total_rules_written": written,
        "target_table": target_table_name,
        "target_datasource": target_datasource_name,
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