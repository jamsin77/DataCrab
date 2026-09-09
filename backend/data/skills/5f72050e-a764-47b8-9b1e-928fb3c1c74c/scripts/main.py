import pandas as pd
from typing import Dict, Any, Optional, List

def _resolve_col(df: pd.DataFrame, col_name: Optional[str]) -> Optional[str]:
    """解析列名，支持自然语言到实际列名的映射。"""
    if col_name is None:
        return None
    resolved = resolve_column(df, col_name)
    if resolved is None:
        raise ValueError(f"列 '{col_name}' 在表中不存在，可用列: {list(df.columns)}")
    return resolved

def _load_data(datasource_name: str, table_name: str) -> pd.DataFrame:
    """加载数据表，返回 DataFrame。"""
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        # 如果按名称找不到，说明传入的已经是 UUID（系统自动解析），直接使用
        ds_id = datasource_name
    result = query_table_data(ds_id, table_name)
    if not result.get("success"):
        raise ValueError(f"读取数据失败: {result.get('error')}")
    df = pd.DataFrame(result["data"], columns=result["columns"])
    print(f"已加载表 {table_name}，共 {len(df)} 行，{len(df.columns)} 列")
    return df

def _do_sort(df: pd.DataFrame, sort_column: str, sort_order: str) -> pd.DataFrame:
    """按指定列排序，返回全表。"""
    col = _resolve_col(df, sort_column)
    ascending = sort_order.lower() == "asc"
    sorted_df = df.sort_values(col, ascending=ascending).reset_index(drop=True)
    print(f"按 {col} 排序完成，方向: {'升序' if ascending else '降序'}")
    return sorted_df

def _do_topk(df: pd.DataFrame, sort_column: str, sort_order: str, top_k: int) -> pd.DataFrame:
    """按指定列排序，返回前 top_k 行。"""
    col = _resolve_col(df, sort_column)
    ascending = sort_order.lower() == "asc"
    sorted_df = df.sort_values(col, ascending=ascending).head(top_k).reset_index(drop=True)
    print(f"按 {col} 排序，取前 {top_k} 条，方向: {'升序' if ascending else '降序'}")
    return sorted_df

def _do_groupby(df: pd.DataFrame, groupby_column: str, agg_column: str, agg_func: str) -> pd.DataFrame:
    """分组聚合。"""
    group_col = _resolve_col(df, groupby_column)
    agg_col = _resolve_col(df, agg_column)
    # 聚合函数映射
    func_map = {
        "sum": "sum",
        "mean": "mean",
        "max": "max",
        "min": "min",
        "count": "count",
    }
    func = func_map.get(agg_func)
    if not func:
        raise ValueError(f"不支持的聚合函数: {agg_func}，可选: {list(func_map.keys())}")
    grouped = df.groupby(group_col)[agg_col].agg(func).reset_index()
    grouped.columns = [group_col, f"{agg_func}_{agg_col}"]
    print(f"按 {group_col} 分组，对 {agg_col} 执行 {agg_func} 聚合，结果 {len(grouped)} 行")
    return grouped

def _do_value_counts(df: pd.DataFrame, column: str, top_k: Optional[int] = None) -> pd.DataFrame:
    """频次统计，返回计数表。"""
    col = _resolve_col(df, column)
    counts = df[col].value_counts().reset_index()
    counts.columns = [col, "count"]
    if top_k and top_k > 0:
        counts = counts.head(top_k)
    print(f"对 {col} 进行频次统计，输出 {len(counts)} 行")
    return counts

def _do_describe(df: pd.DataFrame) -> pd.DataFrame:
    """描述统计，只对数值列。"""
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    if not numeric_cols:
        raise ValueError("表中没有数值列，无法进行描述统计")
    desc = df[numeric_cols].describe().reset_index()
    print(f"对 {len(numeric_cols)} 个数值列进行描述统计")
    return desc

def _do_summary(df: pd.DataFrame) -> pd.DataFrame:
    """综合摘要：行数、列数、类型、缺失值、示例值等。"""
    summary_rows = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        null_count = df[col].isna().sum()
        null_pct = round(null_count / len(df) * 100, 2) if len(df) > 0 else 0
        unique_count = df[col].nunique()
        # 取前三个非空值作为示例
        sample_values = df[col].dropna().head(3).tolist()
        summary_rows.append({
            "column": col,
            "dtype": dtype,
            "null_count": null_count,
            "null_pct": null_pct,
            "unique_count": unique_count,
            "sample_values": str(sample_values),
        })
    summary_df = pd.DataFrame(summary_rows)
    total_rows = len(df)
    total_cols = len(df.columns)
    print(f"表摘要：{total_rows} 行 × {total_cols} 列，缺失值总计 {summary_df['null_count'].sum()} 个")
    return summary_df

def table_stats(
    datasource_name: str,
    table_name: str,
    stat_type: str,
    sort_column: Optional[str] = None,
    sort_order: str = "desc",
    top_k: int = 10,
    groupby_column: Optional[str] = None,
    agg_column: Optional[str] = None,
    agg_func: str = "count",
    output_table: Optional[str] = None,
    if_table_exists: str = "replace",
) -> Dict[str, Any]:
    """主业务函数：根据统计类型执行操作。"""
    # 校验 stat_type
    valid_types = {"sort", "topk", "groupby", "value_counts", "describe", "summary"}
    if stat_type not in valid_types:
        raise ValueError(f"不支持的统计类型: {stat_type}，可选: {valid_types}")

    # 加载数据
    df = _load_data(datasource_name, table_name)
    if df.empty:
        return {"success": True, "message": "表无数据", "stat_type": stat_type}

    # 根据类型执行统计
    if stat_type == "sort":
        if not sort_column:
            raise ValueError("排序操作需要指定 sort_column")
        result_df = _do_sort(df, sort_column, sort_order)
    elif stat_type == "topk":
        if not sort_column:
            raise ValueError("TopK 操作需要指定 sort_column")
        result_df = _do_topk(df, sort_column, sort_order, top_k)
    elif stat_type == "groupby":
        if not groupby_column or not agg_column:
            raise ValueError("分组聚合需要指定 groupby_column 和 agg_column")
        result_df = _do_groupby(df, groupby_column, agg_column, agg_func)
    elif stat_type == "value_counts":
        if not groupby_column:
            raise ValueError("频次统计需要指定 groupby_column（作为计数列）")
        result_df = _do_value_counts(df, groupby_column, top_k)
    elif stat_type == "describe":
        result_df = _do_describe(df)
    elif stat_type == "summary":
        result_df = _do_summary(df)
    else:
        # 理论上不会到这里，但保留保护
        raise ValueError(f"未知统计类型: {stat_type}")

    # 写入或返回
    if output_table:
        ds_id = get_datasource_id_by_name(datasource_name)
        write_result = write_table_data(
            ds_id, output_table,
            records=result_df.to_dict(orient="records"),
            if_table_exists=if_table_exists,
        )
        if not write_result.get("success"):
            raise ValueError(f"写入失败: {write_result.get('message')}")
        return {
            "success": True,
            "stat_type": stat_type,
            "rows": len(result_df),
            "output_table": output_table,
        }
    else:
        return {
            "success": True,
            "stat_type": stat_type,
            "rows": len(result_df),
            "columns": list(result_df.columns),
            "data": result_df.head(100).to_dict(orient="records"),
        }

def _to_num(s):
    """将收益率字符串转为数值，失败返回 None。"""
    if s is None:
        return None
    if isinstance(s, float) and pd.isna(s):
        return None
    t = str(s).strip().replace("%", "").replace("％", "").replace(",", "").strip()
    if t in ("", "-", "--", "nan", "None", "N/A"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _analyze_trade(df: pd.DataFrame) -> Dict[str, Any]:
    """针对交易数据表的专项分析（含列错位校正说明）。"""
    print("=" * 70)
    print("交易数据专项分析")
    print("=" * 70)
    n = len(df)
    print(f"基金产品总数: {n}")

    # 1. 列结构与错位说明
    print("\n[1] 列结构（注意：存在列错位）")
    for c in df.columns:
        print(f"  {c}: 非空 {int(df[c].notna().sum())}/{n}")
    print("\n  说明: '管理人'列全空；'管理规模'列实际存的是管理人名称；")
    print("        '策略'列实际存的是管理规模档位 → 数据整体左移一列，真实'策略'信息已丢失。")

    # 2. 数值化主要收益列
    for c in ["近3年", "近2年", "近1年", "今年"]:
        df[c + "_num"] = df[c].apply(_to_num)

    # 3. 各期收益统计
    stats_rows = []
    for c in ["近3年", "近2年", "近1年", "今年"]:
        s = df[c + "_num"].dropna()
        if len(s) == 0:
            continue
        stats_rows.append({
            "区间": c,
            "样本数": int(len(s)),
            "平均%": round(float(s.mean()), 2),
            "中位数%": round(float(s.median()), 2),
            "最高%": round(float(s.max()), 2),
            "最低%": round(float(s.min()), 2),
            "正收益占比%": round(float((s > 0).mean() * 100), 1),
        })
    stats_df = pd.DataFrame(stats_rows)
    print("\n[2] 各期收益率统计")
    print(stats_df.to_string(index=False))

    # 4. 收益 Top10
    for c in ["近3年", "近2年", "近1年", "今年"]:
        top = df.sort_values(c + "_num", ascending=False).head(10)
        print(f"\n[3] {c} 收益 Top10")
        print(top[["基金简称", c]].to_string(index=False))

    # 5. 管理规模档位分布（取自'策略'列，保留含'亿'或'以上'的档位）
    print("\n[4] 管理规模档位分布（含'亿'或'以上'的档位）")
    scale = df["策略"].astype(str).str.strip()
    scale_filtered = scale[scale.str.contains("亿|以上", na=False)]
    print(scale_filtered.value_counts().to_string())

    # 6. 管理人频次（取自'管理规模'列）
    print("\n[5] '管理规模'列（实为管理人）取值频次 Top20")
    mgr_all = df["管理规模"].astype(str).str.strip()
    mgr_all = mgr_all[mgr_all != ""]
    print(mgr_all.value_counts().head(20).to_string())

    print("\n" + "=" * 70)
    print("分析完成")
    print("=" * 70)

    return {
        "success": True,
        "rows": n,
        "columns": list(df.columns),
        "收益统计": stats_rows,
    }


def main(**params):
    """主入口，系统注入参数，进行别名映射。"""
    datasource_name = params.get("datasource_name") or params.get("datasource")
    table_name = params.get("table_name")

    if not datasource_name or not table_name:
        raise ValueError("需要 datasource_name 和 table_name 参数")

    df = _load_data(datasource_name, table_name)
    if df.empty:
        return {"success": True, "message": "表无数据"}

    # 交易数据表走专项分析
    if "交易数据" in str(table_name):
        return _analyze_trade(df)

    # 其余表走通用统计
    stat_type = params.get("stat_type", "summary")
    sort_column = params.get("sort_column") or params.get("sort_by")
    sort_order = params.get("sort_order", "desc")
    top_k = params.get("top_k", 10)
    groupby_column = params.get("groupby_column") or params.get("group_by")
    agg_column = params.get("agg_column") or params.get("agg_target")
    agg_func = params.get("agg_func", "count")
    output_table = params.get("output_table") or params.get("output")
    if_table_exists = params.get("if_table_exists", "replace")

    return table_stats(
        datasource_name=datasource_name,
        table_name=table_name,
        stat_type=stat_type,
        sort_column=sort_column,
        sort_order=sort_order,
        top_k=top_k,
        groupby_column=groupby_column,
        agg_column=agg_column,
        agg_func=agg_func,
        output_table=output_table,
        if_table_exists=if_table_exists,
    )