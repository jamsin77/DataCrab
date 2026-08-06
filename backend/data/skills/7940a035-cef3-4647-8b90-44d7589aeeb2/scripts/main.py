import re


def _extract_target_names(source_df, source_field, llm_batch_size=20):
    """从源数据的 source_field 列中提取目标实体名称，优先用正则，无法匹配的用 LLM"""
    extracted = {}
    unmatched_indices = []

    # 正则模式
    patterns = [
        (r'归入(.+)', '归入'),
        (r'与(.+?)合并', '与...合并'),
        (r'并入(.+)', '并入'),
        (r'合并[到入](.+)', '合并到/入'),
    ]

    for idx, row in source_df.iterrows():
        val = str(row[source_field]).strip()
        if not val or val == 'nan':
            extracted[idx] = None
            continue

        matched = False
        for pattern, label in patterns:
            m = re.search(pattern, val)
            if m:
                name = m.group(1).strip()
                # 去掉可能的"名称："等后缀
                name = re.sub(r'名称[：:].*', '', name).strip()
                if name:
                    extracted[idx] = name
                    matched = True
                    break
        if not matched:
            unmatched_indices.append(idx)
            extracted[idx] = None

    # 对正则无法匹配的记录用 LLM
    if unmatched_indices:
        log("info", f"正则未匹配 {len(unmatched_indices)} 条，使用 LLM 提取...")
        chunk_size = llm_batch_size
        for start in range(0, len(unmatched_indices), chunk_size):
            chunk_indices = unmatched_indices[start:start + chunk_size]
            items = []
            for idx in chunk_indices:
                val = str(source_df.loc[idx, source_field]).strip()
                name = str(source_df.loc[idx, 'name']).strip() if 'name' in source_df.columns else ''
                items.append((idx, name, val))

            source_list = "\n".join([
                f'{i + 1}. 名称: "{name}", 备注: "{val}"'
                for i, (_, name, val) in enumerate(items)
            ])

            prompt = f"""请从以下每条数据的"备注"中提取它要归并到的目标实体名称。

数据：
{source_list}

提取规则：
1. "归入XXX" → 提取 "XXX"
2. "与XXX合并名称：YYY" → 提取 "XXX"
3. "与XXX合并" → 提取 "XXX"
4. 如果备注中没有明确的目标实体名称，返回 null

请以 JSON 格式返回：
{{"results": [{{"index": 1, "target_name": "清远楼"}}, {{"index": 2, "target_name": null}}]}}

只返回 JSON，不要其他内容。"""

            result = llm_chat(prompt, temperature=0.1, max_tokens=2000)

            try:
                result = result.strip()
                if result.startswith("```"):
                    lines = result.split("\n")
                    result = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0].strip("`")
                parsed = json.loads(result)
                results = parsed.get("results", [])
                for r in results:
                    idx_pos = r.get("index")
                    target_name = r.get("target_name")
                    if idx_pos is not None and 1 <= idx_pos <= len(items):
                        actual_idx = items[idx_pos - 1][0]
                        extracted[actual_idx] = target_name
            except Exception as e:
                log("warn", f"LLM 提取失败 (批次 {start}): {e}")

    return extracted


def _fuzzy_match_names(
    extracted_names,
    target_df,
    target_field,
):
    """将提取的名称与目标数据的 target_field 列进行模糊匹配（优化性能版）"""
    target_values = target_df[target_field].astype(str).str.strip().tolist()
    target_index_map = list(target_df.index)

    # 预构建目标名称的小写索引，加速精确匹配
    target_lower_map = {}
    for i, v in enumerate(target_values):
        key = v.lower().strip()
        if key not in target_lower_map:
            target_lower_map[key] = i

    # 预计算目标值的字符集合（用于 Jaccard 相似度）
    target_char_sets = [set(v) for v in target_values]

    mapping = {}
    for src_idx, name in extracted_names.items():
        if not name or not name.strip():
            mapping[src_idx] = None
            continue

        name = name.strip()
        name_lower = name.lower().strip()

        # 1. 精确匹配（不区分大小写）
        if name_lower in target_lower_map:
            mapping[src_idx] = target_index_map[target_lower_map[name_lower]]
            continue

        # 2. 包含匹配（双向）
        found = False
        for i, v in enumerate(target_values):
            if name in v or v in name:
                mapping[src_idx] = target_index_map[i]
                found = True
                break
        if found:
            continue

        # 3. Jaccard 相似度匹配（阈值 0.5）
        name_chars = set(name)
        best_score = 0.0
        best_i = -1
        for i, tcs in enumerate(target_char_sets):
            if not name_chars and not tcs:
                continue
            overlap = len(name_chars & tcs)
            union = len(name_chars | tcs)
            score = overlap / union if union > 0 else 0
            if score > best_score:
                best_score = score
                best_i = i

        if best_score >= 0.5 and best_i >= 0:
            mapping[src_idx] = target_index_map[best_i]
        else:
            mapping[src_idx] = None

    return mapping


def main(input_data=None, **kwargs):
    """主入口，系统注入用户参数"""
    # 参数别名映射
    param_aliases = {
        'datasource_name': ['datasource_name', 'source_datasource_name', 'source_datasource', 'datasource', 'db', 'source_db'],
        'table_name': ['table_name', 'source_table_name', 'source_table'],
        'filter_condition': ['filter_condition', 'filter', 'condition'],
        'merge_field': ['merge_field', 'match_field', 'field'],
        'output_table_name': ['output_table_name', 'output_table', 'target_table'],
        'if_table_exists': ['if_table_exists', 'write_strategy'],
        'merge_strategy': ['merge_strategy', 'strategy'],
        'batch_size': ['batch_size'],
        'llm_batch_size': ['llm_batch_size'],
    }

    params = {}
    for canonical, aliases in param_aliases.items():
        for alias in aliases:
            if alias in kwargs:
                params[canonical] = kwargs[alias]
                break

    if isinstance(input_data, dict):
        for canonical, aliases in param_aliases.items():
            if canonical not in params:
                for alias in aliases:
                    if alias in input_data:
                        params[canonical] = input_data[alias]
                        break

    datasource_name = params.get('datasource_name')
    table_name = params.get('table_name')
    filter_condition = params.get('filter_condition', '')
    merge_field = params.get('merge_field', '备注')
    output_table_name = params.get('output_table_name')
    if_table_exists = params.get('if_table_exists', 'overwrite')
    merge_strategy = params.get('merge_strategy', 'merge_fields')
    batch_size = params.get('batch_size', 1000)
    llm_batch_size = params.get('llm_batch_size', 20)

    if not datasource_name:
        return {"success": False, "error": "缺少必填参数: datasource_name", "message": "请提供数据源名称"}
    if not table_name:
        return {"success": False, "error": "缺少必填参数: table_name", "message": "请提供表名"}

    # 判断是否已经是UUID，如果是则直接使用，否则通过名称查找
    import re as _re
    uuid_pattern = _re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', _re.IGNORECASE)
    if uuid_pattern.match(str(datasource_name)):
        ds_id = datasource_name
        log("info", f"数据源参数为UUID，直接使用: {ds_id}")
    else:
        ds_id = get_datasource_id_by_name(datasource_name)
        if not ds_id:
            return {"success": False, "error": f"找不到数据源: {datasource_name}"}
        log("info", f"通过名称找到数据源: {datasource_name} -> {ds_id}")

    # 读取数据（分块读取，避免漏行）
    all_rows = []
    columns = None
    for chunk in iter_table_data(ds_id, table_name, chunk_size=5000):
        if not columns:
            columns = chunk.get("columns", [])
        all_rows.extend(chunk.get("rows", []))
    if not all_rows:
        return {"success": True, "message": "无数据", "count": 0}
    df = pd.DataFrame(all_rows, columns=columns)

    log("info", f"总数据量: {len(df)} 行")
    log("info", f"列名: {list(df.columns)}")

    # 解析筛选条件，支持 ==, !=, contains（含 | 分隔的多值OR）
    source_mask = pd.Series([False] * len(df), index=df.index)
    filter_used = False

    if filter_condition:
        if '==' in filter_condition:
            col, val = filter_condition.split('==', 1)
            col, val = col.strip(), val.strip()
            if col in df.columns:
                source_mask = df[col].astype(str) == val
                filter_used = True
            else:
                log("warn", f"筛选列 '{col}' 不存在，将使用关键词搜索")
        elif '!=' in filter_condition:
            col, val = filter_condition.split('!=', 1)
            col, val = col.strip(), val.strip()
            if col in df.columns:
                source_mask = df[col].astype(str) != val
                filter_used = True
            else:
                log("warn", f"筛选列 '{col}' 不存在，将使用关键词搜索")
        elif 'contains' in filter_condition:
            parts = filter_condition.split('contains', 1)
            col = parts[0].strip()
            val = parts[1].strip()
            if col in df.columns:
                vals = [v.strip() for v in val.split('|')]
                source_mask = df[col].astype(str).apply(lambda x: any(v in str(x) for v in vals))
                filter_used = True
            else:
                log("warn", f"筛选列 '{col}' 不存在，将使用关键词搜索")

    if not filter_used:
        # 关键词搜索：在所有文本列中搜索归并/合并相关关键词
        keywords = ['归并', '合并', '归入', '并入']
        log("info", f"在所有列中搜索关键词: {keywords}")
        for col in df.columns:
            try:
                col_mask = df[col].astype(str).apply(lambda x: any(kw in str(x) for kw in keywords))
                source_mask = source_mask | col_mask
            except:
                pass

    source_df = df[source_mask].copy()
    target_df = df[~source_mask].copy()
    log("info", f"源数据(待归并): {len(source_df)} 行, 目标数据: {len(target_df)} 行")

    if source_df.empty:
        return {"success": True, "message": "无源数据需要归并", "count": len(df)}

    # 确定归并字段（备注列）—— 使用智能列名解析（支持中英文翻译匹配）
    actual_merge_field = merge_field
    if actual_merge_field not in source_df.columns:
        actual_merge_field = _resolve_column_smart(source_df, merge_field)
        if actual_merge_field:
            log("info", f"归并字段 '{merge_field}' 解析为: {actual_merge_field}")
        else:
            return {"success": False, "error": f"归并字段 '{merge_field}' 不存在，现有列: {list(source_df.columns)}"}

    # 确定名称列（用于匹配目标记录，优先 name/名称）
    name_col = None
    for candidate in ['name', '名称', '标题', 'title', '文物名称', 'Name']:
        if candidate in target_df.columns:
            name_col = candidate
            break
    if not name_col:
        for col in target_df.columns:
            if target_df[col].dtype == object:
                name_col = col
                break
    if not name_col:
        name_col = actual_merge_field

    log("info", f"使用 '{actual_merge_field}' 提取目标名称，用 '{name_col}' 匹配目标记录")

    extracted = _extract_target_names(source_df, actual_merge_field, llm_batch_size)
    matched = _fuzzy_match_names(extracted, target_df, name_col)

    matched_count = sum(1 for v in matched.values() if v is not None)
    log("info", f"匹配成功: {matched_count}/{len(source_df)}")

    # 合并逻辑：把被合并行各列信息尽可能都放到备注列
    for src_idx, tgt_idx in matched.items():
        if tgt_idx is not None:
            # 收集源行所有非空列信息
            merge_parts = []
            for col in source_df.columns:
                src_val = source_df.loc[src_idx, col]
                if pd.isna(src_val) or str(src_val).strip() == "":
                    continue
                src_str = str(src_val).strip()
                # 跳过与目标行完全相同的值（避免冗余）
                if col in target_df.columns:
                    tgt_val = target_df.loc[tgt_idx, col]
                    if not pd.isna(tgt_val) and str(tgt_val).strip() == src_str:
                        continue
                merge_parts.append(f"{col}: {src_str}")

            if merge_parts:
                # 将所有信息拼接到备注列
                merge_text = "；".join(merge_parts)
                existing_remark = target_df.loc[tgt_idx, actual_merge_field]
                if pd.isna(existing_remark) or str(existing_remark).strip() == "":
                    target_df.loc[tgt_idx, actual_merge_field] = f"【已归并信息】{merge_text}"
                else:
                    target_df.loc[tgt_idx, actual_merge_field] = f"{existing_remark}【已归并信息】{merge_text}"
                log("info", f"行 {tgt_idx} 备注列已追加归并信息: {merge_text[:80]}...")

    output_table = output_table_name or f"{table_name}_merged"
    records = target_df.to_dict(orient="records")

    # 分批写入：第一批用 overwrite 清空重建，后续用 append 追加
    clearing_strategies = {"overwrite", "replace", "truncate"}
    for i in range(0, len(records), batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"
        write_result = write_table_data(ds_id, output_table, records=batch, if_table_exists=current_strategy)
        if not write_result.get("success"):
            return {"success": False, "error": f"写入失败(批次{batch_num}): {write_result.get('message', write_result)}"}
        log("info", f"批次 {batch_num} 写入成功: {len(batch)} 行 (策略={current_strategy})")

    log("info", f"归并完成: {len(df)} → {len(target_df)} 行，写入表: {output_table}")
    return {
        "success": True,
        "original_count": len(df),
        "source_count": len(source_df),
        "merged_count": matched_count,
        "final_count": len(target_df),
        "output_table": output_table,
    }


def _resolve_column_smart(df, name):
    """智能解析列名：先精确/模糊匹配，找不到则用LLM翻译后匹配
    
    Args:
        df: DataFrame
        name: 用户指定的列名（可能是中文、英文或别名）
    
    Returns:
        str: 匹配到的实际列名，或 None
    """
    # 1. 先用内置 resolve_column（精确→忽略大小写→模糊→翻译匹配）
    col = resolve_column(df, name)
    if col:
        return col
    
    # 2. 用 LLM 翻译列名，再匹配
    actual_cols = list(df.columns)
    prompt = f"""用户想要处理名为 "{name}" 的列，但表中实际列名为：{actual_cols}

请找出与 "{name}" 语义最相近的列名。考虑中英文翻译关系（如"备注"="remarks"="remark"="notes"，"名称"="name"="title"）。

只返回最匹配的列名（必须是上面列表中的一个），如果没有匹配的返回 null。只返回列名本身，不要其他内容。"""
    
    try:
        result = llm_chat(prompt, temperature=0.1, max_tokens=100)
        result = result.strip().strip('"').strip("'").strip()
        
        if result and result.lower() != 'null' and result in actual_cols:
            log("info", f"列名 '{name}' 通过翻译匹配到 '{result}'")
            return result
    except Exception as e:
        log("warn", f"翻译匹配列名失败: {e}")
    
    log("warn", f"无法找到与 '{name}' 匹配的列，可用列: {actual_cols}")
    return None