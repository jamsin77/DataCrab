import pandas as pd
import json
import re
from typing import Dict, Any, Optional, List


def _build_header_prompt() -> str:
    """第一步：识别表头列名（从左到右）与估算数据行总数。"""
    return """请观察这张表格图片。请识别表头行的所有列名（从左到右顺序），并估算表格中数据行的总数（不含表头行）。严格按以下 JSON 返回，不要输出任何其他文字：
{"headers": ["列1", "列2", ...], "total_rows": 50}"""


def _build_rows_prompt(headers: List[str], start: int, end: int, last_key: str = "") -> str:
    """分页提取数据行提示词：紧凑竖线分隔格式 + 末行锚点定位，减少 token 消耗、提高定位可靠性。"""
    header_line = "、".join(str(h) for h in headers)
    ncols = len(headers)
    if last_key:
        locate = (
            f"第 1 到第 {start - 1} 行此前已经提取完成，最后一条记录的第一列值是「{last_key}」。"
            f"请从「{last_key}」所在行的下一行开始，向下提取 {end - start + 1} 行数据。"
        )
    else:
        locate = f"请从表格第一行数据（第一条记录）开始，向下提取 {end - start + 1} 行数据。"
    return (
        "这张图片是一个数据表格。表头列从左到右依次为："
        f"{header_line}（共 {ncols} 列）。\n"
        f"{locate}\n"
        "每一行输出该行全部单元格的值，单元格之间用竖线 | 分隔，一行写一条记录，空单元格输出为空字符串。\n"
        "不要输出表头、不要输出行号、不要输出任何解释文字，只输出数据行。\n"
        "格式示例：\n"
        "值1|值2|值3|值4\n"
        "值1|值2|值3|值4"
    )


def _parse_llm_response(response_text: str) -> Dict[str, Any]:
    """从 LLM 回复中提取 JSON 对象（容忍 markdown 代码块包裹）。"""
    if not response_text or not response_text.strip():
        raise ValueError("视觉模型返回为空")
    text = response_text.strip()
    # 去掉 ```json ... ``` 代码块包裹
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 提取第一个 {...} 包裹的 JSON
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法从视觉模型回复中解析 JSON，回复前200字符: {text[:200]}")


def _vision(image_path: str, prompt: str, max_tokens: int = 8000, max_retries: int = 2) -> Dict[str, Any]:
    """调用 llm_vision 并解析 JSON，失败自动重试。"""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            result = call_tool(
                "llm_vision",
                image_path=image_path,
                prompt=prompt,
                max_tokens=max_tokens,
            )
            if not isinstance(result, dict) or "result" not in result:
                raise RuntimeError(f"llm_vision 返回格式异常: {result}")
            response_text = result["result"]
            print(f"    视觉模型返回长度: {len(response_text)} 字符")
            return _parse_llm_response(response_text)
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                print(f"    识别/解析失败，重试 ({attempt}/{max_retries}): {e}")
            else:
                raise RuntimeError(f"视觉识别失败，已重试 {max_retries} 次: {last_err}") from last_err


def _parse_rows_text(response_text: str) -> List[List[str]]:
    """解析紧凑竖线分隔格式的数据行，去除 markdown 代码块和表头说明行。"""
    if not response_text or not response_text.strip():
        return []
    text = response_text.strip()
    fenced = re.search(r"```(?:text|txt|plain)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳过多余的说明文字行（无竖线分隔符且不像数据行）
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        rows.append(cells)
    return rows


def _vision_text(image_path: str, prompt: str, max_tokens: int = 8000, max_retries: int = 2) -> str:
    """调用 llm_vision 返回原始文本，失败自动重试。"""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            result = call_tool(
                "llm_vision",
                image_path=image_path,
                prompt=prompt,
                max_tokens=max_tokens,
            )
            if not isinstance(result, dict) or "result" not in result:
                raise RuntimeError(f"llm_vision 返回格式异常: {result}")
            response_text = result["result"]
            print(f"    视觉模型返回长度: {len(response_text)} 字符")
            return response_text
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                print(f"    识别失败，重试 ({attempt}/{max_retries}): {e}")
            else:
                raise RuntimeError(f"视觉识别失败，已重试 {max_retries} 次: {last_err}") from last_err


def _row_key(row: List[Any], n: int = 2) -> str:
    """用行前 n 个非空单元格生成去重键。"""
    parts = [str(c).strip() for c in (row or [])[:n] if c is not None and str(c).strip() != ""]
    if not parts:
        parts = [str(c).strip() for c in (row or []) if c is not None]
    return "|".join(parts)


def _validate_table_data(table_data: Dict[str, Any]) -> bool:
    """验证表格数据结构"""
    if not table_data.get("is_table"):
        return False
    headers = table_data.get("headers")
    rows = table_data.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise ValueError(f"表格数据格式错误：headers/rows 必须是数组，实际 headers={type(headers)}, rows={type(rows)}")
    if len(headers) == 0:
        raise ValueError("表格数据异常：表头为空")
    return True


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
    """将 LLM 返回的表格数据规范化为 DataFrame"""
    headers = _snake_case_columns(table_data["headers"])
    rows = table_data["rows"]
    normalized_rows = []
    for row in rows:
        if not isinstance(row, list):
            row = [row]
        # 列数对齐
        if len(row) < len(headers):
            row = row + [None] * (len(headers) - len(row))
        elif len(row) > len(headers):
            row = row[:len(headers)]
        normalized_rows.append(row)
    df = pd.DataFrame(normalized_rows, columns=headers)
    # 删除所有值都为空的行
    df = df.dropna(how='all')
    # 重置索引
    df = df.reset_index(drop=True)
    return df


def _write_to_datasource(
    df: pd.DataFrame,
    target_datasource_name: str,
    target_table_name: str,
    if_table_exists: str,
) -> Dict[str, Any]:
    """将 DataFrame 写入目标数据源"""
    print(f"[3/4] 查询目标数据源: {target_datasource_name}")
    ds_info = call_tool("list_user_datasources", by_name=target_datasource_name)
    if not ds_info or not ds_info.get("id"):
        raise ValueError(f"找不到数据源: {target_datasource_name}")
    ds_id = ds_info["id"]
    print(f"[3/4] 目标数据源 ID: {ds_id}，目标表: {target_table_name}")

    records = df.to_dict(orient="records")
    total_rows = len(records)
    batch_size = 1000
    if total_rows == 0:
        raise ValueError("表格数据为空，不执行写入")

    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    if total_rows > batch_size:
        print(f"[3/4] 开始分批写入，共 {total_rows} 行，每批 {batch_size} 行")
        for i in range(0, total_rows, batch_size):
            batch = records[i:i + batch_size]
            current_strategy = if_table_exists
            if i > 0 and if_table_exists in clearing_strategies:
                current_strategy = "append"  # 后续批次追加，避免清空前面批次
            batch_num = i // batch_size + 1
            total_batches = (total_rows - 1) // batch_size + 1
            print(f"[3/4] 写入批次 {batch_num}/{total_batches}，{len(batch)} 行...")
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
        print(f"[3/4] 写入 {total_rows} 行数据到 {target_datasource_name}.{target_table_name}...")
        result = call_tool(
            "write_table_data",
            datasource_id=ds_id,
            table_name=target_table_name,
            records=records,
            if_table_exists=if_table_exists,
        )
        if not result.get("success"):
            raise RuntimeError(f"写入失败: {result.get('message')}")

    print(f"[3/4] 写入完成: {total_rows} 行")
    return {"target_datasource": target_datasource_name, "target_table": target_table_name}


def image_table_to_excel(
    image_path: str,
    target_datasource_name: str = "交易数据",
    target_table_name: str = "parsed_image_table",
    if_table_exists: str = "fail",
    max_retries: int = 2,
) -> Dict[str, Any]:
    """主业务函数：图片表格解析并写入目标数据源"""
    print(f"[1/3] 开始解析图片: {image_path}")
    if not image_path:
        return {"success": False, "error": "image_path 参数不能为空"}

    # 第一步：识别表头 + 估算总行数
    print("[1/3] 识别表头与表格规模...")
    header_data = _vision(image_path, _build_header_prompt(), max_retries=max_retries)
    headers = (header_data or {}).get("headers")
    if not isinstance(headers, list) or len(headers) == 0:
        return {"success": False, "error": "未能识别表格表头"}
    headers = [str(h).strip() for h in headers]
    total_rows_est = int((header_data or {}).get("total_rows", 0) or 0)
    print(f"[1/3] 表头 ({len(headers)} 列): {headers}")
    print(f"[1/3] 估算数据行数: {total_rows_est}")

    # 第二步：分页提取数据行（紧凑格式 + 末行锚点定位 + 动态缩页）
    ncols = len(headers)
    page_size = 8
    upper_bound = max(total_rows_est, 1) + 60  # 留裕量，防止估算偏小
    all_rows: List[List[str]] = []
    seen_keys = set()
    hdr_norm = [str(h).strip() for h in headers]
    # 视觉模型单次输出约 1024 token 上限，截断时返回长度通常 > 1900 字符
    TRUNC_THRESHOLD = 1900

    last_key = ""
    page_idx = 0
    while page_idx < 80:
        print(f"[2/3] 提取批次 {page_idx + 1}（每页约 {page_size} 行，锚点: {last_key or '表头'}）...")
        raw = _vision_text(
            image_path,
            _build_rows_prompt(headers, 1, page_size, last_key=last_key),
            max_tokens=8000,
            max_retries=max_retries,
        )
        rows = _parse_rows_text(raw)

        # 过滤表头重复行/空行，并按首列去重
        valid_rows: List[List[str]] = []
        for row in rows:
            # 丢弃明显不完整的末行（因截断导致的残行）
            if len([c for c in row if c]) < 2:
                continue
            norm = ["".join(c.split()) for c in row]
            # 过滤表头行
            if norm == hdr_norm or norm[:ncols] == hdr_norm:
                continue
            valid_rows.append(row)

        added = 0
        last_seen_key = last_key
        for row in valid_rows:
            key = _row_key(row, n=1)
            if key and key not in seen_keys:
                seen_keys.add(key)
                all_rows.append(row)
                last_seen_key = key
                added += 1

        print(f"[2/3] 本批解析 {len(rows)} 行，有效 {len(valid_rows)} 行，新增 {added} 行，累计 {len(all_rows)} 行")

        # 截断判断：返回超长 + 行数不足一页 → 可能被截断，缩页重试
        truncated = len(raw) >= TRUNC_THRESHOLD and len(valid_rows) < page_size
        if truncated and page_size > 2:
            page_size = max(2, page_size // 2)
            print(f"[2/3] 疑似输出截断，缩页为每页 {page_size} 行重试...")
            continue

        # 正常收尾：返回行数不足一页，说明已到末尾
        if len(valid_rows) < page_size:
            break

        # 无新增且到达迭代上限，防止死循环
        if added == 0:
            print("[2/3] 本批无新增行，停止提取")
            break

        # 更新锚点为当前已读到的最底部记录第一列
        last_key = last_seen_key
        page_idx += 1

    if not all_rows:
        return {"success": False, "error": "表格数据为空，停止解析"}

    table_data = {"is_table": True, "headers": headers, "rows": all_rows}

    # 构造 DataFrame
    if not _validate_table_data(table_data):
        return {"success": False, "error": "图片中未检测到表格"}

    df = _normalize_table_data(table_data)
    print(f"[2/3] 解析完成: 提取 {len(df)} 行，{len(df.columns)} 列")

    if df.empty:
        return {"success": False, "error": "表格数据为空，不再写入"}

    # 写入目标数据源
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


def main(**params):
    # 源数据源信息（系统注入）：datasource=源数据源id, datasource_name=源数据源名, table_name=源表名
    source_ds_id = params.get("datasource") or params.get("datasource_id")
    source_ds_name = params.get("datasource_name")
    source_table = params.get("table_name") or params.get("source_table")

    # 目标信息
    target_table = (
        params.get("target_table_name")
        or params.get("target_table")
        or params.get("output_table")
    )
    target_ds_name = (
        params.get("target_datasource_name")
        or params.get("target_datasource")
        or source_ds_name
    )
    write_strategy = params.get("if_table_exists") or params.get("write_strategy") or "append"

    if not source_ds_id:
        return {"success": False, "error": "缺少源数据源标识"}
    if not source_table:
        return {"success": False, "error": "缺少源表名"}
    if not target_table:
        return {"success": False, "error": "缺少目标表名"}

    print(f"[1/3] 导出: {source_ds_name or source_ds_id}.{source_table} -> {target_ds_name or '(同源)'}.{target_table}")

    # 解析目标数据源 id（默认与源同源）并确认连接器类型
    target_ds_id = source_ds_id
    target_ds_type = None
    _lookup_name = target_ds_name or source_ds_name
    if _lookup_name:
        target_info = call_tool("list_user_datasources", by_name=_lookup_name)
        if not target_info or not target_info.get("id"):
            return {"success": False, "error": f"找不到目标数据源: {target_ds_name}"}
        target_ds_type = target_info.get("type")
        if target_ds_name and target_ds_name != source_ds_name:
            target_ds_id = target_info["id"]

    # 文件型数据源(generic_file)以文件名作为"表名"，写入时目标表名必须带扩展名
    write_table = str(target_table)
    if target_ds_type == "generic_file" and "." not in write_table:
        write_table = write_table + ".csv"
        print(f"[1/3] 目标为文件型数据源，实际写入文件名: {write_table}")

    # 分页读取源表
    all_columns = None
    all_rows = []
    page = 1
    page_size = 10000
    while True:
        print(f"[2/3] 读取源表第 {page} 页...")
        res = call_tool(
            "iter_table_data",
            datasource_id=source_ds_id,
            table_name=source_table,
            page=page,
            page_size=page_size,
        )
        if not isinstance(res, dict) or not res.get("columns"):
            return {"success": False, "error": f"读取源表失败: {res}"}
        if all_columns is None:
            all_columns = res["columns"]
        all_rows.extend(res.get("rows") or [])
        total = res.get("total", 0)
        has_next = bool(res.get("has_next", False))
        print(f"[2/3] 已读取 {len(all_rows)}/{total} 行")
        if not has_next:
            break
        page += 1

    if not all_columns:
        return {"success": False, "error": "源表没有列，无法导出"}
    if not all_rows:
        return {"success": False, "error": "源表数据为空，无法导出"}

    records = [dict(zip(all_columns, row)) for row in all_rows]
    total = len(records)
    print(f"[2/3] 读取完成: {total} 行, {len(all_columns)} 列")

    # 写入目标表（分批）
    batch_size = 1000
    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    if total > batch_size:
        for i in range(0, total, batch_size):
            batch = records[i:i + batch_size]
            strategy = write_strategy
            if i > 0 and write_strategy in clearing_strategies:
                strategy = "append"  # 后续批次追加，避免清空前面批次
            batch_num = i // batch_size + 1
            total_batches = (total - 1) // batch_size + 1
            print(f"[3/3] 写入批次 {batch_num}/{total_batches}，{len(batch)} 行...")
            wres = call_tool(
                "write_table_data",
                datasource_id=target_ds_id,
                table_name=target_table,
                records=batch,
                if_table_exists=strategy,
            )
            if not wres.get("success"):
                return {"success": False, "error": f"写入失败: {wres.get('message') or wres.get('error')}"}
    else:
        print(f"[3/3] 写入 {total} 行到目标表 {write_table}...")
        wres = call_tool(
            "write_table_data",
            datasource_id=target_ds_id,
            table_name=write_table,
            records=records,
            if_table_exists=write_strategy,
        )
        if not wres.get("success"):
            return {"success": False, "error": f"写入失败: {wres.get('message') or wres.get('error')}"}

    print(f"[3/3] 导出完成: {total} 行 -> {target_table}")
    return {
        "success": True,
        "rows": total,
        "columns": all_columns,
        "target_table": target_table,
        "target_datasource": target_ds_name or target_ds_id,
        "message": "表导出成功",
    }