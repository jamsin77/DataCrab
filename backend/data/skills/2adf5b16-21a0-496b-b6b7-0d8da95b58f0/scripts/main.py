import pandas as pd
import json
import re
from typing import Dict, Any, List


def _snake_case_columns(headers: List[str]) -> List[str]:
    """规范化列名：数字开头的年份列改为 snake_case（如 '2025年' -> 'year_2025'），中文列名保留。"""
    result = []
    for h in headers:
        h = str(h).strip() if h is not None else ""
        if not h:
            h = f"col_{len(result) + 1}"
        elif re.match(r"^\d", h):
            m = re.match(r"^(\d{4})\s*年?", h)
            if m:
                h = f"year_{m.group(1)}"
            else:
                h = "col_" + re.sub(r"\s+", "_", h)
        result.append(h)
    return result


def _normalize_table_data(table_data: Dict[str, Any]) -> pd.DataFrame:
    """将表格数据规范化为 DataFrame"""
    headers = _snake_case_columns(table_data["headers"])
    rows = table_data["rows"]
    normalized_rows = []
    for row in rows:
        if not isinstance(row, list):
            row = [row]
        if len(row) < len(headers):
            row = row + [None] * (len(headers) - len(row))
        elif len(row) > len(headers):
            row = row[:len(headers)]
        normalized_rows.append(row)
    df = pd.DataFrame(normalized_rows, columns=headers)
    df = df.dropna(how='all')
    df = df.reset_index(drop=True)
    return df


def _repair_misaligned_rows(df: pd.DataFrame) -> pd.DataFrame:
    """修复图片表格 OCR 提取常见的错位与串行问题。

    1. 剥离引号：视觉模型复述分页内容时常给单元格加首尾引号（垃圾副本行的典型特征）。
    2. 右移行：首列空、后续列整体右移 -> 左移对齐。
    3. 错位行：策略列被数字/百分数侵占（整行右移错位）-> 直接丢弃，正常策略列必是文字。
    4. 串行重复：按首列（基金简称）评分制去重，优先保留「无引号、策略合法、非空列多」的完整行。
    """
    cols = list(df.columns)

    # 定位"策略"列（用模糊匹配，避免列名微调漏配）
    strat_idx = None
    for i, c in enumerate(cols):
        if "策略" in str(c) or "类型" in str(c):
            strat_idx = i
            break

    _QUOTES = "\"'“”‘’「」"

    def _strip_quotes(v):
        if v is None:
            return ""
        s = str(v).strip()
        while len(s) >= 2 and s[0] in _QUOTES and s[-1] in _QUOTES:
            s = s[1:-1].strip()
        return s.strip().strip(_QUOTES).strip()

    def _clean(v):
        if v is None:
            return ""
        s = _strip_quotes(v)
        return "" if s.lower() in ("", "-", "--", "---", "nan", "none", "null", "/", "—", "–", "·") else s

    def _is_strategy_ok(s):
        if not s:
            return True
        # 策略列是数字/百分数/负百分数开头 => 整行右移错位，标记不合法
        return not re.match(r"^[+-]?\d", s)

    repaired = []
    for _, r in df.iterrows():
        raw_vals = [r[c] for c in cols]
        vals = [_clean(v) for v in raw_vals]
        if all(v == "" for v in vals):
            continue
        # 表头重复行过滤：首列等于任一列名（如"基金简称"）即视为表头行，删除
        if vals[0] and vals[0] in set(cols):
            continue
        # 右移修复：首列为空时，找到第一个非空列并整体左移（最多移2列，避免过度修正）
        if vals[0] == "":
            nz = next((i for i, v in enumerate(vals) if v != ""), 0)
            if 0 < nz <= 2:
                vals = vals[nz:] + [""] * nz
        if all(v == "" for v in vals):
            continue
        # 错位行过滤：策略列被数字/百分数侵占 -> 丢弃
        if strat_idx is not None and strat_idx < len(vals) and not _is_strategy_ok(vals[strat_idx]):
            continue
        # 剥离首列（基金简称）前导分隔符，使副本行/正常行可归并为同一键
        vals[0] = re.sub(r"^[\s\-–—•·]+", "", vals[0]).strip()
        if not vals[0]:
            continue
        # 评分：带引号单元格越多越像垃圾副本行，予以扣分
        quoted = 0
        for v in raw_vals:
            if v is None:
                continue
            s = str(v).strip()
            if len(s) >= 2 and s[0] in _QUOTES and s[-1] in _QUOTES:
                quoted += 1
        filled = sum(1 for v in vals if v != "")
        strategy_bonus = 10 if (strat_idx is not None and strat_idx < len(vals) and vals[strat_idx] and _is_strategy_ok(vals[strat_idx])) else 0
        score = filled + strategy_bonus - quoted
        repaired.append({"key": vals[0], "vals": vals, "score": score})

    # 按首列去重，保留得分最高的行
    best = {}
    for item in repaired:
        key = item["key"]
        if item["score"] > best.get(key, (-1e9, None))[0]:
            best[key] = (item["score"], item["vals"])

    return pd.DataFrame([v for _s, v in best.values()], columns=cols)


def _extract_first_column_ground_truth(image_path: str) -> List[str]:
    """用 llm_vision 单独提取第一列完整清单，作为行对齐真值锚点。

    extract_image_table 对长图分页时锚点不可靠，会漏行/幻觉编造行；
    而单独提取一列（约48个名字）单次视觉输出即可完整容纳，可靠性高。
    """
    prompt = ("这是一张基金数据表格图片。请逐行从上到下，只把每一行数据的第一列值完整抄录出来，"
              "每行一个，不要省略、不要合并、不要输出表头、不要输出其他列、不要加编号。")
    try:
        res = call_tool("llm_vision", image_path=image_path, prompt=prompt, max_tokens=4000)
    except Exception as e:
        print(f"[2/3] 提取真值清单失败（跳过对齐）: {e}")
        return []
    text = ""
    if isinstance(res, dict):
        text = res.get("result") or res.get("content") or ""
    if not text:
        return []
    names = []
    for line in str(text).splitlines():
        line = re.sub(r"^\s*\d+[\s\.\)、:：\-]*", "", line).strip()
        if not line:
            continue
        names.append(line)
    seen, uniq = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _align_rows_to_ground_truth(df: pd.DataFrame, ground_truth: List[str]) -> pd.DataFrame:
    """以真实第一列清单为锚点过滤对齐：清单外行（幻觉/编造）丢弃、缺失行补空、按清单顺序排列。"""
    if not ground_truth or df.empty:
        return df
    first_col = df.columns[0]
    row_map = {}
    for _, r in df.iterrows():
        key = str(r[first_col]).strip() if r[first_col] is not None else ""
        if not key:
            continue
        filled = sum(1 for c in df.columns if r[c] not in (None, ""))
        prev = row_map.get(key)
        if prev is None or filled > prev[1]:
            row_map[key] = (r, filled)
    kept = set(row_map.keys())
    aligned = []
    for name in ground_truth:
        name = str(name).strip()
        if name in kept:
            aligned.append(row_map[name][0].to_dict())
        else:
            aligned.append({c: None for c in df.columns})
    if not aligned:
        return df
    return pd.DataFrame(aligned, columns=df.columns)


def _write_to_datasource(
    df: pd.DataFrame,
    target_datasource_name: str,
    target_table_name: str,
    if_table_exists: str,
) -> Dict[str, Any]:
    """将 DataFrame 写入目标数据源"""
    print(f"[3/3] 查询目标数据源: {target_datasource_name}")
    ds_info = call_tool("list_user_datasources", by_name=target_datasource_name)
    if not ds_info or not ds_info.get("id"):
        raise ValueError(f"找不到数据源: {target_datasource_name}")
    ds_id = ds_info["id"]
    print(f"[3/3] 目标数据源 ID: {ds_id}，目标表: {target_table_name}")

    records = df.to_dict(orient="records")
    total_rows = len(records)
    batch_size = 1000
    if total_rows == 0:
        raise ValueError("表格数据为空，不执行写入")

    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    if total_rows > batch_size:
        print(f"[3/3] 开始分批写入，共 {total_rows} 行，每批 {batch_size} 行")
        for i in range(0, total_rows, batch_size):
            batch = records[i:i + batch_size]
            current_strategy = if_table_exists
            if i > 0 and if_table_exists in clearing_strategies:
                current_strategy = "append"
            batch_num = i // batch_size + 1
            total_batches = (total_rows - 1) // batch_size + 1
            print(f"[3/3] 写入批次 {batch_num}/{total_batches}，{len(batch)} 行...")
            result = call_tool(
                "write_table_data",
                datasource_id=ds_id,
                table_name=target_table_name,
                records=batch,
                if_table_exists=current_strategy,
            )
            if not result.get("success"):
                raise RuntimeError(f"写入失败: {result.get('message')}")
    else:
        print(f"[3/3] 写入 {total_rows} 行数据到 {target_datasource_name}.{target_table_name}...")
        result = call_tool(
            "write_table_data",
            datasource_id=ds_id,
            table_name=target_table_name,
            records=records,
            if_table_exists=if_table_exists,
        )
        if not result.get("success"):
            raise RuntimeError(f"写入失败: {result.get('message')}")

    print(f"[3/3] 写入完成: {total_rows} 行")
    return {"target_datasource": target_datasource_name, "target_table": target_table_name}


def main(
    image_path: str = "",
    target_datasource_name: str = "交易数据",
    target_table_name: str = "parsed_image_table",
    if_table_exists: str = "replace",
    max_retries: int = 1,
    page_size: int = 12,
    **kwargs,
) -> Dict[str, Any]:
    """图片表格解析并写入目标数据源。
    调 extract_image_table 工具分页提取表格数据（不截断），再写入目标数据源。
    系统会注入 datasource/datasource_name/table_name（源数据源+源表名），
    如果源表是图片文件记录（含 file_path），自动取 file_path 作为 image_path。
    """
    # 系统注入参数
    source_ds_id = kwargs.get("datasource") or kwargs.get("datasource_id") or ""
    source_ds_name = kwargs.get("datasource_name") or ""
    source_table = kwargs.get("table_name") or kwargs.get("source_table") or ""

    # 如果没有显式传 image_path，从源表数据中查找图片文件路径
    if not image_path and source_ds_id and source_table:
        print(f"[1/3] 从源表 {source_ds_name}.{source_table} 查找图片文件路径...")
        try:
            res = call_tool("query_table_data", datasource_id=source_ds_id, table_name=source_table)
            if isinstance(res, dict) and res.get("data"):
                rows_data = res["data"]
                if rows_data:
                    first_row = rows_data[0] if isinstance(rows_data[0], dict) else dict(zip(res.get("columns", []), rows_data[0]))
                    image_path = first_row.get("file_path") or first_row.get("file_name") or ""
                    if image_path:
                        print(f"[1/3] 从源表获取图片路径: {image_path}")
        except Exception as e:
            print(f"[1/3] 查询源表失败: {e}")

    # 兼容直接传 file_path
    if not image_path:
        image_path = kwargs.get("file_path") or ""

    print(f"[1/3] 开始解析图片: {image_path}")
    if not image_path:
        return {"success": False, "error": "image_path 参数不能为空（请指定图片路径，或确保源表含 file_path 字段）"}

    # 第一步：调 extract_image_table 工具分页提取表格数据
    print("[1/3] 调用 extract_image_table 分页提取表格数据...")
    table_result = call_tool(
        "extract_image_table",
        image_path=image_path,
        max_retries=max_retries,
        page_size=page_size,
    )
    if not isinstance(table_result, dict):
        try:
            table_result = json.loads(table_result) if isinstance(table_result, str) else {}
        except Exception:
            table_result = {}
    if table_result.get("error"):
        return {"success": False, "error": table_result["error"]}
    if not table_result.get("is_table"):
        return {"success": False, "error": table_result.get("error", "图片中未检测到表格")}

    headers = table_result.get("headers", [])
    rows = table_result.get("rows", [])
    print(f"[1/3] 提取完成: {len(rows)} 行, {len(headers)} 列")

    if not rows:
        return {"success": False, "error": "表格数据为空，停止解析"}

    # 第二步：构造 DataFrame
    table_data = {"is_table": True, "headers": headers, "rows": rows}
    df = _normalize_table_data(table_data)
    print(f"[2/3] 数据规范化完成: {len(df)} 行, {len(df.columns)} 列")

    if df.empty:
        return {"success": False, "error": "表格数据为空，不再写入"}

    # 2.5：修复错位串行（右移、占位行、串行重复、表头重复行）
    before = len(df)
    df = _repair_misaligned_rows(df)
    print(f"[2/3] 错位串行修复完成: {before} 行 -> {len(df)} 行")

    # 2.55：提取第一列真值清单，作为对齐锚点过滤幻觉行/补漏行
    ground_truth = _extract_first_column_ground_truth(image_path)
    print(f"[2/3] 第一列真值清单: {len(ground_truth)} 条")
    before = len(df)
    df = _align_rows_to_ground_truth(df, ground_truth)
    print(f"[2/3] 按真值清单对齐完成: {before} 行 -> {len(df)} 行")

    # 2.6：表名带时间戳（若用户未显式指定）
    if not target_table_name or target_table_name == "parsed_image_table":
        ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        target_table_name = f"交易数据_{ts}"
        print(f"[2/3] 目标表名未指定，自动生成带时间戳表名: {target_table_name}")

    # 第三步：写入目标数据源
    if not if_table_exists or if_table_exists == "fail":
        if_table_exists = "replace"
    write_info = _write_to_datasource(df, target_datasource_name, target_table_name, if_table_exists)

    print(f"[3/3] 全部完成: 成功解析并写入 {len(df)} 行")
    return {
        "success": True,
        "rows": len(df),
        "columns": list(df.columns),
        "target_table": write_info["target_table"],
        "target_datasource": write_info["target_datasource"],
        "message": "图片表格解析并写入成功",
    }
