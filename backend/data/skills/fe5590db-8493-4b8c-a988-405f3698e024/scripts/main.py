from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


def _parse_table_specs(table_specs: str) -> List[Tuple[str, str]]:
    """解析表规范列表，返回 [(数据源名, 表名), ...]

    Args:
        table_specs: 格式 "数据源名.表名" 的逗号分隔字符串

    Returns:
        [(数据源名, 表名), ...]

    Raises:
        ValueError: 格式不正确或存在重复表
    """
    if not table_specs or not table_specs.strip():
        raise ValueError("table_specs 不能为空")

    specs = []
    seen = set()
    for part in table_specs.split(","):
        part = part.strip()
        if not part:
            continue
        if "." not in part:
            raise ValueError(f"表规范格式错误（应为 '数据源名.表名'）: {part}")
        ds_name, table_name = part.split(".", 1)
        ds_name = ds_name.strip()
        table_name = table_name.strip()
        if not ds_name or not table_name:
            raise ValueError(f"表规范格式错误（数据源名和表名不能为空）: {part}")
        key = (ds_name, table_name)
        if key in seen:
            raise ValueError(f"重复的表规范: {part}")
        seen.add(key)
        specs.append(key)
    return specs


def _load_table_data(ds_name: str, table_name: str) -> pd.DataFrame:
    """加载单个表的数据，并添加 _source 列标识来源

    Args:
        ds_name: 数据源名称
        table_name: 表名

    Returns:
        包含数据及 _source 列的 DataFrame

    Raises:
        ValueError: 数据源不存在或查询失败
    """
    ds_id = get_datasource_id_by_name(ds_name)
    if not ds_id:
        raise ValueError(f"找不到数据源: {ds_name}")

    result = query_table_data(ds_id, table_name, limit=50000)
    if not result.get("success"):
        raise ValueError(f"读取表 '{table_name}' 失败: {result.get('error')}")

    data = result.get("data") or []
    columns = result.get("columns") or []
    df = pd.DataFrame(data, columns=columns)
    if df.empty:
        print(f"  - {ds_name}.{table_name}: 0 行（跳过）")
        return pd.DataFrame()

    df["_source"] = f"{ds_name}.{table_name}"
    print(f"  - {ds_name}.{table_name}: {len(df)} 行")
    return df


def _load_all_tables(specs: List[Tuple[str, str]]) -> pd.DataFrame:
    """并发加载所有表的数据并合并

    Args:
        specs: [(数据源名, 表名), ...]

    Returns:
        合并后的 DataFrame，包含 _source 列

    Raises:
        ValueError: 所有表加载失败
    """
    print(f"开始并发加载 {len(specs)} 张表...")
    dfs = []
    with ThreadPoolExecutor(max_workers=min(8, len(specs))) as executor:
        futures = {
            executor.submit(_load_table_data, ds, table): (ds, table)
            for ds, table in specs
        }
        for future in as_completed(futures):
            ds, table = futures[future]
            try:
                df = future.result()
                if df is not None and not df.empty:
                    dfs.append(df)
            except Exception as e:
                print(f"  ✗ 加载 {ds}.{table} 失败: {e}")

    if not dfs:
        raise ValueError("所有表加载失败或无数据")

    combined = pd.concat(dfs, ignore_index=True, sort=False)
    print(f"合并完成，共 {len(combined)} 行，{len(combined.columns) - 1} 个数据列")
    log("info", f"跨表匹配：合并 {len(specs)} 张表后共 {len(combined)} 行")
    return combined


def _resolve_match_columns(df: pd.DataFrame, match_columns: str) -> List[str]:
    """解析匹配列的用户语义名称到实际列名

    Args:
        df: 合并后的 DataFrame（不含 _source 列）
        match_columns: 逗号分隔的匹配列名

    Returns:
        实际存在的列名列表

    Raises:
        ValueError: 某列不存在
    """
    existing = df.columns.tolist()
    resolved = []
    for col_name in match_columns.split(","):
        col_name = col_name.strip()
        if not col_name:
            continue
        if col_name in existing:
            resolved.append(col_name)
            continue
        # 使用 resolve_column 模糊匹配
        found = resolve_column(df, col_name)
        if found and found in existing:
            resolved.append(found)
            print(f"  列 '{col_name}' 解析为实际列 '{found}'")
        else:
            raise ValueError(
                f"匹配列 '{col_name}' 不存在于合并后的表中。可用列: {existing}"
            )
    if not resolved:
        raise ValueError("match_columns 不能为空")
    return resolved


def _detect_duplicates(
    df: pd.DataFrame, match_cols: List[str]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """检测重复记录

    Args:
        df: 合并后的 DataFrame
        match_cols: 实际匹配列列表

    Returns:
        (重复记录 DataFrame, 统计信息)
    """
    # 匹配列全为空的行不参与重复检测
    valid_mask = df[match_cols].notna().any(axis=1)
    valid_df = df[valid_mask].copy()

    if valid_df.empty:
        return pd.DataFrame(), {"total_rows": len(df), "matched_rows": 0, "groups": 0}

    # 生成重复组ID
    valid_df["_duplicate_group"] = valid_df.groupby(match_cols, dropna=False).ngroup()
    valid_df["_duplicate_flags"] = valid_df.duplicated(
        subset=match_cols, keep=False
    )

    duplicates = valid_df[valid_df["_duplicate_flags"]].copy()
    if duplicates.empty:
        return pd.DataFrame(), {"total_rows": len(df), "matched_rows": 0, "groups": 0}

    groups = duplicates["_duplicate_group"].nunique()
    matched_rows = len(duplicates)
    stats = {
        "total_rows": len(df),
        "matched_rows": matched_rows,
        "unique_rows": len(df) - matched_rows,
        "groups": groups,
    }
    print(
        f"检测结果: 总 {stats['total_rows']} 行, "
        f"匹配 {stats['matched_rows']} 行, "
        f"唯一 {stats['unique_rows']} 行, "
        f"重复组 {stats['groups']} 组"
    )
    log(
        "info",
        f"跨表匹配完成: 匹配 {matched_rows} 行 / 共 {len(df)} 行, "
        f"重复组 {groups} 个",
    )
    return duplicates, stats


def _deduplicate_data(
    df: pd.DataFrame, match_cols: List[str], keep: str = "first"
) -> Tuple[pd.DataFrame, int]:
    """去重数据

    Args:
        df: 合并后的 DataFrame
        match_cols: 实际匹配列列表
        keep: 保留策略 first/last

    Returns:
        (去重后 DataFrame, 移除行数)
    """
    original_rows = len(df)
    # 匹配列全部为空的行保留（无法判断重复）
    null_mask = df[match_cols].isna().all(axis=1)
    null_rows = df[null_mask].copy()
    non_null = df[~null_mask].copy()

    if non_null.empty:
        return df, 0

    deduped_non_null = non_null.drop_duplicates(
        subset=match_cols, keep=keep
    ).copy()

    result = pd.concat([deduped_non_null, null_rows], ignore_index=True, sort=False)
    removed = original_rows - len(result)
    print(
        f"去重完成: {original_rows} 行 → {len(result)} 行 "
        f"(移除 {removed} 行重复)"
    )
    log("info", f"去重完成: 移除 {removed} 行重复")
    return result, removed


def _mark_duplicates(df: pd.DataFrame, match_cols: List[str]) -> pd.DataFrame:
    """为所有记录添加重复标记

    Args:
        df: 合并后的 DataFrame
        match_cols: 实际匹配列列表

    Returns:
        添加 is_duplicate 和 duplicate_group 列的 DataFrame
    """
    result = df.copy()
    # 匹配列全为空的行为非重复
    null_mask = result[match_cols].isna().all(axis=1)
    result.loc[null_mask, "_is_duplicate"] = False
    result.loc[null_mask, "_duplicate_group"] = -1

    non_null = result[~null_mask].copy()
    if not non_null.empty:
        non_null["_is_duplicate"] = non_null.duplicated(
            subset=match_cols, keep=False
        )
        non_null["_duplicate_group"] = non_null.groupby(
            match_cols, dropna=False
        ).ngroup()
        non_null.loc[~non_null["_is_duplicate"], "_duplicate_group"] = -1
        result.update(non_null, overwrite=True)

    # 重命名列
    result = result.rename(
        columns={
            "_is_duplicate": "is_duplicate",
            "_duplicate_group": "duplicate_group",
        }
    )
    dup_count = int(
        result["is_duplicate"].sum() if "is_duplicate" in result.columns else 0
    )
    print(f"标记完成: 共 {len(result)} 行, 其中重复标记 {dup_count} 行")
    return result


def _write_records(
    records: List[Dict[str, Any]],
    output_datasource: str,
    output_table: str,
    if_table_exists: str = "replace",
    batch_size: int = 1000,
) -> int:
    """分批写入记录

    Args:
        records: 记录列表
        output_datasource: 输出数据源名
        output_table: 输出表名
        if_table_exists: 写入策略
        batch_size: 每批大小

    Returns:
        写入总行数

    Raises:
        ValueError: 写入失败
    """
    ds_id = get_datasource_id_by_name(output_datasource)
    if not ds_id:
        raise ValueError(f"找不到输出数据源: {output_datasource}")

    total = len(records)
    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]
        batch_num = i // batch_size + 1
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"
        result = write_table_data(
            ds_id, output_table, records=batch, if_table_exists=current_strategy
        )
        if not result.get("success"):
            raise ValueError(
                f"写入第 {batch_num} 批失败: {result.get('message')}"
            )
        print(f"  已写入第 {batch_num} 批: {len(batch)} 行")

    print(f"共写入 {total} 行到 {output_datasource}.{output_table}")
    return total


def match_records(
    table_specs: str,
    match_columns: str,
    action: str = "detect",
    output_datasource: Optional[str] = None,
    output_table: Optional[str] = None,
    keep: str = "first",
) -> Dict[str, Any]:
    """跨表匹配与去重主业务函数

    Args:
        table_specs: 表规范列表 "数据源名.表名,..."
        match_columns: 匹配列，逗号分隔
        action: 操作 detect/export/deduplicate/mark
        output_datasource: 输出数据源
        output_table: 输出表名
        keep: deduplicate 保留策略

    Returns:
        执行结果字典

    Raises:
        ValueError: 参数校验失败或执行失败
    """
    # ---- 参数校验 ----
    action = (action or "detect").lower().strip()
    valid_actions = {"detect", "export", "deduplicate", "mark"}
    if action not in valid_actions:
        raise ValueError(f"无效的 action: {action}，可选: {valid_actions}")

    if action in {"export", "deduplicate", "mark"}:
        if not output_datasource or not output_table:
            raise ValueError(
                f"action={action} 时必须指定 output_datasource 和 output_table"
            )

    keep = (keep or "first").lower().strip()
    if keep not in {"first", "last"}:
        raise ValueError(f"keep 只能为 first 或 last，当前: {keep}")

    # ---- 解析表规范 ----
    specs = _parse_table_specs(table_specs)
    print(f"表规范解析: {len(specs)} 张表")
    for ds, table in specs:
        print(f"  - {ds}.{table}")

    # ---- 加载数据 ----
    combined = _load_all_tables(specs)
    if combined.empty:
        return {"success": True, "message": "无数据", "count": 0}

    # ---- 解析匹配列 ----
    df_no_source = combined.drop(columns=["_source"])
    match_cols = _resolve_match_columns(df_no_source, match_columns)
    print(f"匹配列: {match_cols}")

    # ---- 处理操作 ----
    if action == "detect":
        duplicates, stats = _detect_duplicates(combined, match_cols)
        if duplicates.empty:
            return {
                "success": True,
                "action": "detect",
                "stats": stats,
                "message": "未检测到重复记录",
                "data": [],
            }
        # 移除 _source 列用于返回
        result_df = duplicates.drop(columns=["_source", "_duplicate_flags"], errors="ignore")
        return {
            "success": True,
            "action": "detect",
            "stats": stats,
            "columns": result_df.columns.tolist(),
            "data": result_df.head(20).to_dict(orient="records"),
            "preview_only": len(result_df) > 20,
        }

    if action == "export":
        duplicates, stats = _detect_duplicates(combined, match_cols)
        if duplicates.empty:
            return {
                "success": True,
                "action": "export",
                "stats": stats,
                "message": "未检测到重复记录，无需导出",
                "written_rows": 0,
            }
        export_df = duplicates.drop(columns=["_duplicate_flags"], errors="ignore")
        export_df = export_df.rename(columns={"_duplicate_group": "duplicate_group"})
        records = export_df.to_dict(orient="records")
        written = _write_records(records, output_datasource, output_table)
        return {
            "success": True,
            "action": "export",
            "stats": stats,
            "written_rows": written,
            "target_table": f"{output_datasource}.{output_table}",
        }

    if action == "deduplicate":
        deduped, removed = _deduplicate_data(combined, match_cols, keep)
        deduped = deduped.drop(columns=["_source"], errors="ignore")
        records = deduped.to_dict(orient="records")
        written = _write_records(records, output_datasource, output_table)
        return {
            "success": True,
            "action": "deduplicate",
            "removed_rows": removed,
            "kept_rows": written,
            "target_table": f"{output_datasource}.{output_table}",
        }

    if action == "mark":
        marked = _mark_duplicates(combined, match_cols)
        marked = marked.drop(columns=["_source"], errors="ignore")
        records = marked.to_dict(orient="records")
        written = _write_records(records, output_datasource, output_table)
        dup_count = int(
            marked["is_duplicate"].sum() if "is_duplicate" in marked.columns else 0
        )
        return {
            "success": True,
            "action": "mark",
            "written_rows": written,
            "duplicate_count": dup_count,
            "target_table": f"{output_datasource}.{output_table}",
        }

    # 不应到达
    raise ValueError(f"未处理的操作: {action}")


def main(**params: Any) -> Dict[str, Any]:
    """主入口，系统注入用户参数"""
    param_aliases = {
        "table_specs": ["table_specs", "tables", "source_tables", "table_spec", "table_list"],
        "match_columns": ["match_columns", "match_cols", "key_columns", "keys", "match_by"],
        "action": ["action", "operation", "op"],
        "output_datasource": ["output_datasource", "target_datasource", "output_ds"],
        "output_table": ["output_table", "target_table", "output_tbl"],
        "keep": ["keep", "keep_strategy"],
    }

    def _get_param(alias_list: List[str]) -> Any:
        for alias in alias_list:
            if alias in params and params[alias] is not None:
                return params[alias]
        return None

    table_specs = _get_param(param_aliases["table_specs"])
    match_columns = _get_param(param_aliases["match_columns"])
    action = _get_param(param_aliases["action"]) or "detect"
    output_datasource = _get_param(param_aliases["output_datasource"])
    output_table = _get_param(param_aliases["output_table"])
    keep = _get_param(param_aliases["keep"]) or "first"

    return match_records(
        table_specs=table_specs,
        match_columns=match_columns,
        action=action,
        output_datasource=output_datasource,
        output_table=output_table,
        keep=keep,
    )