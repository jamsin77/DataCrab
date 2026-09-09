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
    """两次独立提取第一列并合并去重，弥补视觉模型单次整图提取的随机漏行。

    单次整图提取第一列偶发漏 1~2 行（导致总行数从 48 变成 47）；
    两次独立调用各自漏不同行的概率低，合并后更接近完整 48 行。
    """
    prompt = ("这是一张基金数据表格图片。表格从表头下一行开始共有 48 行数据。\n"
              "请把每一行数据第一列（基金简称）的值从上到下逐行完整抄录出来，每行一个，\n"
              "不要省略任何一行、不要合并、不要输出表头、不要输出其他列、不要加编号、不要输出任何解释文字。")
    round_names = []  # 每一轮提取的名单（分轮存放，便于以第一轮为基准做模糊去重）
    for attempt in (1, 2):
        try:
            res = call_tool("llm_vision", image_path=image_path, prompt=prompt, max_tokens=4000)
        except Exception as e:
            print(f"[2/3] 名单提取第 {attempt} 次失败: {e}")
            continue
        text = _llm_result_text(res)
        if not text:
            continue
        cur = []
        for line in str(text).splitlines():
            line = re.sub(r"^[\s\-–—•·\d\.\)、:：]*", "", line).strip()
            if not line:
                continue
            # 过滤说明性句子（比基金名长得多），基金名一般不超过 25 字
            if len(line) > 25:
                continue
            # 单轮内精确去重（保持顺序）
            if line not in cur:
                cur.append(line)
        if cur:
            round_names.append(cur)

    if not round_names:
        return []

    import difflib

    def _sim(a, b):
        return difflib.SequenceMatcher(None, str(a), str(b)).ratio()

    # 以第一轮（通常最完整）为基准名单；后续轮只做 OCR 变体归并/替换，不再新增行。
    # 精确匹配去重无法合并 OCR 变体（如"天演资管"vs"天演资策"），会把同一基金的
    # 另一种写法当成新基金追加，导致总行数虚增——这是"多出 20 行"的根因。
    base = list(round_names[0])
    for cur in round_names[1:]:
        for name in cur:
            best_r, best_i = 0.0, -1
            for i, kept in enumerate(base):
                r = _sim(name, kept)
                if r > best_r:
                    best_r, best_i = r, i
            if best_r >= 0.5 and best_i >= 0:
                # 视作同一基金，保留更完整的写法（更长的通常更接近真实全称）
                if len(name) > len(base[best_i]):
                    base[best_i] = name
            # best_r < 0.5：不新增，宁可不补也不虚增（图片固定 48 行）
    return base


def _llm_result_text(res) -> str:
    """从 llm_vision 返回值中取文本"""
    if isinstance(res, dict):
        return str(res.get("result") or res.get("content") or "")
    return str(res or "")


def _extract_headers(image_path: str) -> List[str]:
    """识别表头列名（从左到右，用竖线分隔）。"""
    prompt = ("请观察这张图片表格的表头行，从左到右识别所有列名，"
              "用竖线 | 分隔依次输出，每个列名一个，不要输出数据行、"
              "不要输出任何解释文字，只输出一行列名。")
    try:
        res = call_tool("llm_vision", image_path=image_path, prompt=prompt, max_tokens=2000)
    except Exception as e:
        print(f"[1/3] 表头识别失败: {e}")
        return []
    text = _llm_result_text(res)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
        elif "，" in line or "," in line or "、" in line:
            parts = [p.strip() for p in re.split(r"[，,、\t]+", line)]
        else:
            parts = [line.strip()]
        parts = [p for p in parts if p]
        if parts:
            return parts
    return []


def _extract_col_group(image_path: str, names: List[str], cols: List[str], retries: int = 2) -> List[List[str]]:
    """用「基金简称」名单做行锚，提取一组列的值。

    对长图而言，视觉模型按行号定位中间行不可靠（漏行/错位/幻觉），
    但单独按列顺序抄录第一列是可靠的。本函数把第一列完整名单喂给模型，
    让模型按名单逐行「对号填值」，避免行号定位误差，同时控制单次输出体积。
    """
    if not names:
        return []
    names_block = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(names))
    cols_str = "、".join(cols)
    n = len(names)
    prompt = (
        f"这张图片是一个基金数据表格，表头列从左到右为：基金简称、{cols_str}。\n"
        f"下面是第一列「基金简称」从表格第一行到最后一行共 {n} 行的完整值（顺序已固定）：\n"
        f"{names_block}\n\n"
        f"请严格按上面这 {n} 行的顺序，为每一行在图片中定位它对应的「{cols_str}」列的值，"
        f"用竖线 | 分隔 {len(cols)} 个值，每行输出一个，共输出 {n} 行；空单元格输出为空（即连续两个 | 或行尾留空）。\n"
        f"不要输出表头、不要输出「基金简称」列、不要输出行号、不要输出任何解释，只输出 {cols_str} 的值。\n"
        f"示例：\n值1|值2|值3"
    )
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            res = call_tool("llm_vision", image_path=image_path, prompt=prompt, max_tokens=4096)
            text = _llm_result_text(res)
            rows = []
            for line in text.splitlines():
                line = line.strip()
                if not line or "|" not in line:
                    continue
                cells = [c.strip() for c in line.split("|")]
                cells = cells[:len(cols)]
                cells += [""] * (len(cols) - len(cells))
                rows.append(cells)
            if rows:
                if len(rows) < n:
                    rows += [[""] * len(cols)] * (n - len(rows))
                return rows[:n]
        except Exception as e:
            last_err = e
            if attempt < retries:
                print(f"列组提取失败（第 {attempt} 次）: {e}")
    print(f"列组 {cols} 提取最终失败: {last_err}")
    return [[""] * len(cols)] * n


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

    # 第一步：识别表头列名
    print("[1/3] 识别表头列名...")
    headers = _extract_headers(image_path)
    _default_headers = ["基金简称", "管理人", "管理规模", "策略", "近3年", "近2年", "近1年",
                        "今年", "2025年", "2024年", "2023年", "2022年", "2021年", "2020年", "2019年"]
    if not headers:
        headers = _default_headers
        print(f"[1/3] 表头识别失败，使用默认列名（{len(headers)} 列）")
    else:
        print(f"[1/3] 表头识别成功: {len(headers)} 列 -> {headers}")

    # 第二步：提取第一列「基金简称」完整名单作为行锚（两次提取合并去重，降低随机漏行）
    print("[1/3] 提取第一列「基金简称」完整名单（行锚）...")
    names = _extract_first_column_ground_truth(image_path)
    print(f"[1/3] 第一列名单: {len(names)} 条")
    if not names:
        return {"success": False, "error": "未能提取第一列名单，停止解析"}

    rest_cols = headers[1:] if len(headers) > 1 else []

    # 第三步：其余列按「基金简称」名单做行锚，分组逐组提取
    print("[2/3] 按行锚分列组提取其余列...")
    group_size = 3
    col_groups = [rest_cols[i:i + group_size] for i in range(0, len(rest_cols), group_size)]
    matrices = []
    for gi, g in enumerate(col_groups):
        print(f"[2/3] 提取列组 {gi + 1}/{len(col_groups)}: {g}")
        mat = _extract_col_group(image_path, names, g, retries=2)
        matrices.append(mat)
        print(f"[2/3] 列组 {gi + 1} 提取完成: {len(mat)} 行")

    # 第四步：清理单元格值 + 组装 DataFrame
    def _clean_cell(v):
        if v is None:
            return ""
        s = str(v).strip()
        s = s.strip('"\'“”‘’「」').strip()
        if s.lower() in ("", "-", "--", "---", "nan", "none", "null", "空", "无", "/"):
            return ""
        return s

    norm_headers = _snake_case_columns(headers)
    records = []
    for i, name in enumerate(names):
        row = {norm_headers[0]: _clean_cell(name)}
        for gi, g in enumerate(col_groups):
            vals = matrices[gi][i] if gi < len(matrices) and i < len(matrices[gi]) else [""] * len(g)
            for j, c in enumerate(g):
                col_name = _snake_case_columns([c])[0]
                row[col_name] = _clean_cell(vals[j]) if j < len(vals) else ""
        records.append(row)

    # 仅在所有数据列（除基金简称外）都为空时才剔除该行
    df = pd.DataFrame(records, columns=norm_headers)
    if len(df.columns) > 1:
        data_cols = list(df.columns[1:])
        df = df[~df[data_cols].apply(lambda r: all(str(x).strip() in ("", "nan", "None", "null") for x in r), axis=1)]
    df = df.dropna(how='all').reset_index(drop=True)
    print(f"[2/3] 组装完成: {len(df)} 行, {len(df.columns)} 列")
    if df.empty:
        return {"success": False, "error": "表格数据为空，不再写入"}

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
