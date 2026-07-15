import pandas as pd
import json
from typing import Dict, Any, Optional, List


# ============================================================
# 筛选条件处理
# ============================================================

def _resolve_column(df: pd.DataFrame, col_name: str) -> str:
    """模糊匹配列名，返回实际列名"""
    if col_name in df.columns:
        return col_name
    candidates = [c for c in df.columns if col_name.lower() in c.lower()]
    if candidates:
        return candidates[0]
    raise ValueError(f"列 '{col_name}' 不存在，可用列: {list(df.columns)}")


def _apply_filter(df: pd.DataFrame, condition: str) -> pd.Series:
    """
    应用筛选条件，返回布尔掩码。
    支持: 列名==值, 列名!=值, 列名 contains 值, 自然语言条件
    """
    if not condition or not condition.strip():
        return pd.Series([True] * len(df), index=df.index)

    condition = condition.strip()

    # 支持 == 操作符
    if "==" in condition:
        col, val = condition.split("==", 1)
        col = _resolve_column(df, col.strip())
        val = val.strip().strip('"\'')
        return df[col].astype(str).str.strip() == val

    # 支持 != 操作符
    if "!=" in condition:
        col, val = condition.split("!=", 1)
        col = _resolve_column(df, col.strip())
        val = val.strip().strip('"\'')
        return df[col].astype(str).str.strip() != val

    # 支持 contains 操作符
    lower_cond = condition.lower()
    if " contains " in lower_cond:
        idx = lower_cond.index(" contains ")
        col = condition[:idx].strip()
        val = condition[idx + len(" contains "):].strip().strip('"\'')
        col = _resolve_column(df, col)
        return df[col].astype(str).str.contains(val, case=False, na=False)

    # 支持 > < >= <= 操作符（数值比较）
    for op in [">=", "<=", ">", "<"]:
        if op in condition:
            col, val = condition.split(op, 1)
            col = _resolve_column(df, col.strip())
            val = val.strip().strip('"\'')
            try:
                return pd.to_numeric(df[col], errors="coerce") >= float(val) if op == ">=" else \
                       pd.to_numeric(df[col], errors="coerce") <= float(val) if op == "<=" else \
                       pd.to_numeric(df[col], errors="coerce") > float(val) if op == ">" else \
                       pd.to_numeric(df[col], errors="coerce") < float(val)
            except ValueError:
                pass

    # 自然语言条件：用 LLM 判断
    log("info", f"使用 LLM 解析自然语言条件: {condition}")
    return _apply_nl_filter(df, condition)


def _apply_nl_filter(df: pd.DataFrame, condition: str) -> pd.Series:
    """使用 LLM 应用自然语言筛选条件"""
    mask = pd.Series([False] * len(df), index=df.index)

    # 分批发送给 LLM
    chunk_size = 50
    for start in range(0, len(df), chunk_size):
        chunk = df.iloc[start:start + chunk_size]
        records = chunk.to_dict(orient="records")
        sample_str = json.dumps(records, ensure_ascii=False, default=str)

        prompt = f"""请根据筛选条件，从数据中找出满足条件的行。

筛选条件: {condition}

数据（全局索引从 {start} 开始）:
{sample_str}

请返回满足条件的行的全局索引列表。以 JSON 格式返回: {{"indices": [{start}, {start + 1}]}}
只返回 JSON，不要其他内容。"""

        result = llm_chat(prompt, temperature=0.1, max_tokens=2000)

        try:
            result = result.strip()
            if result.startswith("```"):
                lines = result.split("\n")
                result = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0]
            parsed = json.loads(result)
            indices = parsed.get("indices", [])
            for idx in indices:
                if start <= idx < start + len(chunk):
                    mask.iloc[idx] = True
        except Exception as e:
            log("warn", f"LLM 条件解析失败 (批次 {start}): {e}")

    matched = int(mask.sum())
    log("info", f"自然语言条件匹配到 {matched} 条")
    return mask


# ============================================================
# 语义匹配
# ============================================================

def _build_match_prompt(batch_items: List[tuple], target_values: List[str]) -> str:
    """构造 LLM 语义匹配 prompt"""
    source_list = "\n".join([f'{i + 1}. "{val}"' for i, (_, val) in enumerate(batch_items)])
    target_list = "\n".join([f'{i + 1}. "{val}"' for i, val in enumerate(target_values)])

    return f"""请将以下源数据中的每一条，在目标数据中找到语义最相似（指代同一实体或同一事物）的匹配项。

源数据：
{source_list}

目标数据：
{target_list}

匹配规则：
1. 只有语义上确实指代同一实体/事物时才匹配（如"唐三彩马"与"唐代三彩陶马"可匹配）
2. 如果没有合适的匹配项，target 设为 null
3. 每个源数据最多匹配一个目标
4. 目标数据可被多个源数据匹配

请以 JSON 格式返回：
{{"matches": [{{"source": 1, "target": 3}}, {{"source": 2, "target": null}}]}}

只返回 JSON，不要其他内容。"""


def _parse_match_result(result: str, source_count: int, target_count: int) -> List[Optional[int]]:
    """解析 LLM 返回的匹配结果，返回每个源数据对应的目标位置（0-based），None 表示无匹配"""
    try:
        result = result.strip()
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0].strip("`")

        parsed = json.loads(result)
        matches = parsed.get("matches", [])

        result_list: List[Optional[int]] = [None] * source_count
        for m in matches:
            src = m.get("source")
            tgt = m.get("target")
            if src is not None and 1 <= src <= source_count:
                if tgt is not None and 1 <= tgt <= target_count:
                    result_list[src - 1] = tgt - 1
                else:
                    result_list[src - 1] = None
        return result_list
    except Exception as e:
        log("warn", f"解析匹配结果失败: {e}")
        return [None] * source_count


def _semantic_match(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    merge_field: str,
    llm_batch_size: int = 20
) -> Dict[int, Optional[int]]:
    """
    使用 LLM 进行语义匹配。
    返回 {源DataFrame索引: 目标DataFrame索引或None}
    """
    target_values = target_df[merge_field].astype(str).str.strip().tolist()
    target_indices = list(target_df.index)

    mapping: Dict[int, Optional[int]] = {}
    source_items = list(source_df[merge_field].astype(str).str.strip().items())

    total_batches = (len(source_items) + llm_batch_size - 1) // llm_batch_size

    for batch_num in range(total_batches):
        start = batch_num * llm_batch_size
        end = min(start + llm_batch_size, len(source_items))
        batch = source_items[start:end]

        log("info", f"语义匹配批次 {batch_num + 1}/{total_batches} ({len(batch)} 条源数据 vs {len(target_values)} 条目标数据)...")

        prompt = _build_match_prompt(batch, target_values)
        system_prompt = "你是一个数据匹配专家。请根据语义相似性将源数据匹配到最合适的目标数据。只返回 JSON。"

        result = llm_chat(prompt, system_prompt=system_prompt, temperature=0.1, max_tokens=3000)
        matches = _parse_match_result(result, len(batch), len(target_values))

        for i, match_pos in enumerate(matches):
            src_idx = batch[i][0]
            if match_pos is not None and 0 <= match_pos < len(target_indices):
                mapping[src_idx] = target_indices[match_pos]
            else:
                mapping[src_idx] = None

        # 打印批次匹配结果
        matched_in_batch = sum(1 for m in matches if m is not None)
        print(f"  批次 {batch_num + 1}: 匹配 {matched_in_batch}/{len(batch)}")

    return mapping


# ============================================================
# 归并执行
# ============================================================

def _execute_merge(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    merge_mapping: Dict[int, Optional[int]],
    merge_strategy: str
) -> tuple:
    """
    执行归并操作。
    返回 (result_df, merged_count, unmatched_indices)
    """
    merged_count = 0
    unmatched_indices = []

    for src_idx, tgt_idx in merge_mapping.items():
        if tgt_idx is not None:
            if merge_strategy == "merge_fields":
                # 将源记录中目标记录缺失的字段补入
                for col in source_df.columns:
                    if col not in target_df.columns:
                        continue
                    tgt_val = target_df.loc[tgt_idx, col]
                    src_val = source_df.loc[src_idx, col]
                    tgt_empty = pd.isna(tgt_val) or str(tgt_val).strip() == ""
                    src_has = not pd.isna(src_val) and str(src_val).strip() != ""
                    if tgt_empty and src_has:
                        target_df.loc[tgt_idx, col] = src_val
            merged_count += 1
        else:
            unmatched_indices.append(src_idx)

    # 保留未匹配的源数据
    if unmatched_indices:
        unmatched_df = source_df.loc[unmatched_indices].copy()
        result_df = pd.concat([target_df, unmatched_df], ignore_index=True)
    else:
        result_df = target_df.reset_index(drop=True)

    return result_df, merged_count, unmatched_indices


# ============================================================
# 分批写入
# ============================================================

def _write_records(
    records: List[dict],
    ds_id: str,
    table_name: str,
    if_table_exists: str,
    batch_size: int = 1000
) -> None:
    """分批写入数据：第一批用原策略，后续批次用 append"""
    clearing_strategies = {"overwrite", "replace", "truncate"}
    total = len(records)

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"
        write_table_data(ds_id, table_name, records=batch, if_table_exists=current_strategy)
        print(f"  写入批次 {batch_num}: {len(batch)} 条 (策略: {current_strategy})")


# ============================================================
# 主业务函数
# ============================================================

def semantic_merge_data(
    datasource_name: str,
    table_name: str,
    filter_condition: str,
    merge_field: str,
    output_table_name: Optional[str] = None,
    if_table_exists: str = "overwrite",
    merge_strategy: str = "keep_target",
    batch_size: int = 1000,
    llm_batch_size: int = 20,
) -> Dict[str, Any]:
    """
    语义归并结构化数据。

    Args:
        datasource_name: 数据源名称
        table_name: 表名
        filter_condition: 筛选条件，指定要归并的源数据
        merge_field: 用于语义匹配的字段名
        output_table_name: 输出表名（默认同 table_name）
        if_table_exists: 写入策略
        merge_strategy: 归并策略 (keep_target / merge_fields)
        batch_size: 数据写入批次大小
        llm_batch_size: LLM 语义匹配批次大小

    Returns:
        包含 success 和归并统计信息的字典
    """
    # 1. 获取数据源 ID
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        return {"success": False, "error": f"找不到数据源: {datasource_name}"}

    # 2. 读取全表数据
    log("info", f"读取数据源 '{datasource_name}' 表 '{table_name}'...")
    result = query_table_data(ds_id, table_name, limit=100000)
    if not result.get("success"):
        return {"success": False, "error": f"读取数据失败: {result.get('error', '未知错误')}"}

    columns = result.get("columns", [])
    data = result.get("data", [])
    original_count = len(data)

    if original_count == 0:
        return {"success": False, "error": "表为空，无需归并"}

    df = pd.DataFrame(data, columns=columns)
    print(f"原始数据: {original_count} 条, 列: {list(df.columns)}")

    # 3. 检查 merge_field 是否存在
    actual_merge_field = merge_field
    if merge_field not in df.columns:
        candidates = [c for c in df.columns if merge_field.lower() in c.lower()]
        if candidates:
            actual_merge_field = candidates[0]
            print(f"模糊匹配字段: '{merge_field}' → '{actual_merge_field}'")
        else:
            return {
                "success": False,
                "error": f"字段 '{merge_field}' 不存在，可用列: {list(df.columns)}"
            }

    # 4. 筛选源数据
    try:
        source_mask = _apply_filter(df, filter_condition)
    except Exception as e:
        return {"success": False, "error": f"筛选条件应用失败: {str(e)}"}

    source_df = df[source_mask].copy()
    target_df = df[~source_mask].copy()

    print(f"源数据（待归并）: {len(source_df)} 条")
    print(f"目标数据: {len(target_df)} 条")

    if len(source_df) == 0:
        return {"success": False, "error": "筛选条件未匹配到任何源数据，无需归并"}

    if len(target_df) == 0:
        return {"success": False, "error": "没有目标数据可归并（所有数据都被筛选为源数据）"}

    # 5. 语义匹配
    log("info", "开始语义匹配...")
    merge_mapping = _semantic_match(source_df, target_df, actual_merge_field, llm_batch_size)

    matched_count = sum(1 for v in merge_mapping.values() if v is not None)
    print(f"\n语义匹配完成: {matched_count}/{len(source_df)} 条源数据找到匹配")

    # 6. 执行归并
    result_df, merged_count, unmatched_indices = _execute_merge(
        source_df, target_df, merge_mapping, merge_strategy
    )

    final_count = len(result_df)
    reduced_count = original_count - final_count

    print(f"\n{'='*50}")
    print(f"归并结果:")
    print(f"  原始数据:   {original_count} 条")
    print(f"  源数据:     {len(source_df)} 条")
    print(f"  目标数据:   {len(target_df)} 条")
    print(f"  成功归并:   {merged_count} 条")
    print(f"  未匹配保留: {len(unmatched_indices)} 条")
    print(f"  最终数据:   {final_count} 条 (减少 {reduced_count} 条)")
    print(f"{'='*50}")

    # 7. 校验
    log("info", "执行归并校验...")

    if final_count > original_count:
        return {
            "success": False,
            "error": f"校验失败: 归并后数据增多 ({original_count} → {final_count})",
            "original_count": original_count,
            "final_count": final_count
        }

    if reduced_count > len(source_df):
        return {
            "success": False,
            "error": f"校验失败: 减少条数({reduced_count})超过源数据条数({len(source_df)})",
            "original_count": original_count,
            "final_count": final_count,
            "source_count": len(source_df)
        }

    log("info", "校验通过 ✓")

    # 8. 写入结果
    output_table = output_table_name or table_name
    records = result_df.to_dict(orient="records")

    # 清理 NaN 值
    for record in records:
        for key, val in record.items():
            if pd.isna(val):
                record[key] = None

    log("info", f"写入表 '{output_table}' (策略: {if_table_exists})...")
    _write_records(records, ds_id, output_table, if_table_exists, batch_size)

    log("info", "归并完成！")

    return {
        "success": True,
        "original_count": original_count,
        "final_count": final_count,
        "source_count": len(source_df),
        "target_count": len(target_df),
        "merged_count": merged_count,
        "unmatched_count": len(unmatched_indices),
        "reduced_count": reduced_count,
        "merge_field": actual_merge_field,
        "merge_strategy": merge_strategy,
        "output_table": output_table,
        "columns": list(result_df.columns),
    }


# ============================================================
# 入口函数
# ============================================================

def main(**kwargs):
    """主入口，系统注入用户参数"""
    param_aliases = {
        'datasource_name': ['datasource_name', 'datasource', 'source_datasource_name', 'source_datasource'],
        'table_name': ['table_name', 'source_table_name', 'source_table'],
        'filter_condition': ['filter_condition', 'condition', 'filter'],
        'merge_field': ['merge_field', 'match_field', 'semantic_field', 'field'],
        'output_table_name': ['output_table_name', 'output_table', 'target_table_name', 'target_table'],
        'if_table_exists': ['if_table_exists', 'write_strategy', 'if_exists'],
        'merge_strategy': ['merge_strategy', 'strategy'],
        'batch_size': ['batch_size', 'write_batch_size'],
        'llm_batch_size': ['llm_batch_size', 'match_batch_size'],
    }

    params = {}
    for target_key, aliases in param_aliases.items():
        for alias in aliases:
            if alias in kwargs:
                params[target_key] = kwargs[alias]
                break

    # 设置默认值
    params.setdefault('output_table_name', None)
    params.setdefault('if_table_exists', 'overwrite')
    params.setdefault('merge_strategy', 'keep_target')
    params.setdefault('batch_size', 1000)
    params.setdefault('llm_batch_size', 20)

    return semantic_merge_data(**params)