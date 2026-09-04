import os
import re
import difflib
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed


# ===== 模块级并行 worker 函数（供 ProcessPoolExecutor 使用，必须是模块级可 pickle）=====

def _match_chunk_worker(args):
    """模块级模糊匹配 worker：Jaccard + 包含匹配（CPU 密集，绕过 GIL）"""
    chunk_items, target_values, target_index_map, target_lower_map, target_char_sets = args
    chunk_mapping = {}
    for src_idx, name in chunk_items:
        if not name or not name.strip():
            chunk_mapping[src_idx] = None
            continue
        name = name.strip()
        name_lower = name.lower().strip()

        # 1. 精确匹配（不区分大小写）
        if name_lower in target_lower_map:
            chunk_mapping[src_idx] = target_index_map[target_lower_map[name_lower]]
            continue

        # 2. 包含匹配（双向）
        found = False
        for i, v in enumerate(target_values):
            if name in v or v in name:
                chunk_mapping[src_idx] = target_index_map[i]
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
            chunk_mapping[src_idx] = target_index_map[best_i]
        else:
            chunk_mapping[src_idx] = None
    return chunk_mapping


def _build_merge_pairs_worker(args):
    """模块级 merge pair 构建 worker：比较源行和目标行各列差异"""
    chunk_items, src_cols, src_rows_dict, tgt_rows_dict, name_col = args
    pairs = []
    for src_idx, tgt_idx in chunk_items:
        merge_parts = []
        src_row = src_rows_dict[src_idx]
        tgt_row = tgt_rows_dict.get(tgt_idx, {})
        for col in src_cols:
            src_val = src_row.get(col)
            if src_val is None or str(src_val).strip() == "":
                continue
            src_str = str(src_val).strip()
            if col in tgt_row:
                tgt_val = tgt_row[col]
                if tgt_val is not None and str(tgt_val).strip() == src_str:
                    continue
            merge_parts.append(f"{col}: {src_str}")
        if merge_parts:
            src_info = "；".join(merge_parts)
            src_name = str(src_row.get(name_col, "")).strip()
            pairs.append((tgt_idx, src_info, src_name))
    return pairs


def _extract_target_names(source_df, source_field, llm_batch_size=20):
    """从源数据的 source_field 列中提取目标实体名称，优先用向量化正则，无法匹配的用 LLM"""
    extracted = {idx: None for idx in source_df.index}

    # ===== 向量化正则提取（一次性处理整列，比逐行 .loc 快 10-100 倍）=====
    vals = source_df[source_field].astype(str).str.strip()
    vals = vals.where(vals != 'nan', '')

    # 4 个正则模式按优先级顺序，用 str.extract 向量化
    m1 = vals.str.extract(r'归入(.+)', expand=False)
    m2 = vals.str.extract(r'与(.+?)合并', expand=False)
    m3 = vals.str.extract(r'并入(.+)', expand=False)
    m4 = vals.str.extract(r'合并[到入](.+)', expand=False)

    # 按优先级组合：m1 → m2 → m3 → m4
    result = m1.where(m1.notna() & (m1 != ''),
             m2.where(m2.notna() & (m2 != ''),
             m3.where(m3.notna() & (m3 != ''),
             m4)))

    # 清理："名称：..." 等后缀
    result = result.str.replace(r'名称[：:].*', '', regex=True).str.strip()
    result = result.where(result != '', None)

    # 标记匹配成功的行
    matched_mask = result.notna() & (vals != '')
    for idx in source_df.index[matched_mask]:
        extracted[idx] = result[idx]

    unmatched_indices = [idx for idx in source_df.index if not matched_mask[idx]]
    print(f"正则匹配成功: {matched_mask.sum()}/{len(source_df)}, 未匹配: {len(unmatched_indices)}")

    # ===== 对正则无法匹配的记录用 LLM（并行，返回结果而非副作用）=====
    if unmatched_indices:
        print(f"正则未匹配 {len(unmatched_indices)} 条，使用 LLM 并行提取...")
        chunk_size = llm_batch_size
        chunks = []
        for start in range(0, len(unmatched_indices), chunk_size):
            chunk_indices = unmatched_indices[start:start + chunk_size]
            items = []
            for idx in chunk_indices:
                val = str(source_df.loc[idx, source_field]).strip()
                name = str(source_df.loc[idx, 'name']).strip() if 'name' in source_df.columns else ''
                items.append((idx, name, val))
            chunks.append(items)

        def _llm_extract_chunk(items):
            """返回 {actual_idx: target_name}，不修改共享状态"""
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
            result = call_tool("llm_generate", prompt=prompt, temperature=0.1, max_tokens=2000)["content"]
            chunk_results = {}
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
                        chunk_results[actual_idx] = target_name
            except Exception as e:
                print(f"LLM 提取失败: {e}")
            return chunk_results

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = {executor.submit(_llm_extract_chunk, items): i for i, items in enumerate(chunks)}
            for future in as_completed(futures):
                try:
                    chunk_results = future.result()
                    extracted.update(chunk_results)
                except Exception as e:
                    print(f"LLM 提取批次 {futures[future]} 异常: {e}")

    return extracted


def _fuzzy_match_names(
    extracted_names,
    target_df,
    target_field,
    match_workers=8,
):
    """将提取的名称与目标数据的 target_field 列进行模糊匹配（ProcessPoolExecutor，绕过 GIL）"""
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

    # 将 extracted_names 拆分为多个 chunk，用 ProcessPoolExecutor 并行匹配
    items = list(extracted_names.items())
    if len(items) <= 100:
        chunk_size = len(items)
    else:
        chunk_size = max(1, len(items) // match_workers)
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    mapping = {}
    if len(chunks) == 1:
        mapping = _match_chunk_worker((chunks[0], target_values, target_index_map, target_lower_map, target_char_sets))
    else:
        # CPU 密集型：用 ProcessPoolExecutor 绕过 GIL
        args_list = [(chunk, target_values, target_index_map, target_lower_map, target_char_sets) for chunk in chunks]
        with ProcessPoolExecutor(max_workers=min(match_workers, len(chunks), os.cpu_count() or 4)) as executor:
            futures = [executor.submit(_match_chunk_worker, args) for args in args_list]
            for future in as_completed(futures):
                mapping.update(future.result())

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
        'output_datasource_name': ['output_datasource_name', 'output_datasource', 'target_datasource'],
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
    output_datasource_name = params.get('output_datasource_name')
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
        print(f"数据源参数为UUID，直接使用: {ds_id}")
    else:
        _r = call_tool("list_user_datasources", by_name=datasource_name)
        ds_id = _r.get("id") if isinstance(_r, dict) else None
        if not ds_id:
            return {"success": False, "error": f"找不到数据源: {datasource_name}"}
        print(f"通过名称找到数据源: {datasource_name} -> {ds_id}")

    # 确定输出数据源：Excel 类型不支持 write_table_data 创建新表，需回退到 PostgreSQL
    write_ds_id = ds_id  # 默认同源写入
    if output_datasource_name:
        _r2 = call_tool("list_user_datasources", by_name=output_datasource_name)
        output_ds_id = _r2.get("id") if isinstance(_r2, dict) else None
        if output_ds_id:
            write_ds_id = output_ds_id
            print(f"使用指定输出数据源: {output_datasource_name} -> {write_ds_id}")
        else:
            print(f"输出数据源 '{output_datasource_name}' 未找到，将尝试同源写入")

    # 读取数据（分块读取，避免漏行）
    all_rows = []
    columns = None
    page = 1
    while True:
        chunk = call_tool("iter_table_data", datasource_id=ds_id, table_name=table_name, page=page, page_size=20000)
        if not columns:
            columns = chunk.get("columns", [])
        all_rows.extend(chunk.get("rows", []))
        if not chunk.get("has_next", False):
            break
        page += 1
    if not all_rows:
        return {"success": True, "message": "无数据", "count": 0}
    df = pd.DataFrame(all_rows, columns=columns)

    print(f"总数据量: {len(df)} 行")
    print(f"列名: {list(df.columns)}")

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
                print(f"筛选列 '{col}' 不存在，将使用关键词搜索")
        elif '!=' in filter_condition:
            col, val = filter_condition.split('!=', 1)
            col, val = col.strip(), val.strip()
            if col in df.columns:
                source_mask = df[col].astype(str) != val
                filter_used = True
            else:
                print(f"筛选列 '{col}' 不存在，将使用关键词搜索")
        elif 'contains' in filter_condition:
            # 支持 "col contains val1 or col contains val2" 语法
            # 也支持 "col contains val1|val2" 语法
            similar_keywords = ['归并', '合并', '归入', '并入', '合并到', '合并入', '归并入', '并入到']

            if re.search(r'\s+or\s+', filter_condition, re.IGNORECASE):
                # 解析多个 "col contains val" 子句，用 or 连接
                clauses = re.split(r'\s+or\s+', filter_condition, flags=re.IGNORECASE)
                for clause in clauses:
                    clause = clause.strip()
                    if 'contains' in clause:
                        parts = clause.split('contains', 1)
                        col = parts[0].strip()
                        val = parts[1].strip()
                        if col in df.columns:
                            # "类似语义" 展开为同义关键词列表
                            if '类似语义' in val:
                                vals = similar_keywords
                            else:
                                vals = [v.strip() for v in val.split('|')]
                            pattern = '|'.join(re.escape(v) for v in vals)
                            col_mask = df[col].astype(str).str.contains(pattern, na=False)
                            source_mask = source_mask | col_mask
                            filter_used = True
                        else:
                            print(f"筛选列 '{col}' 不存在")
            else:
                parts = filter_condition.split('contains', 1)
                col = parts[0].strip()
                val = parts[1].strip()
                if col in df.columns:
                    vals = [v.strip() for v in val.split('|')]
                    pattern = '|'.join(re.escape(v) for v in vals)
                    source_mask = df[col].astype(str).str.contains(pattern, na=False)
                    filter_used = True
                else:
                    print(f"筛选列 '{col}' 不存在，将使用关键词搜索")

    if not filter_used:
        # 关键词搜索：在所有文本列中搜索归并/合并相关关键词（向量化批量 str.contains）
        keywords = ['归并', '合并', '归入', '并入']
        pattern = '|'.join(re.escape(kw) for kw in keywords)
        print(f"在所有列中搜索关键词: {keywords}")
        for col in df.columns:
            try:
                col_mask = df[col].astype(str).str.contains(pattern, na=False, regex=True)
                source_mask = source_mask | col_mask
            except:
                pass

    source_df = df[source_mask].copy()
    target_df = df[~source_mask].copy()
    print(f"源数据(待归并): {len(source_df)} 行, 目标数据: {len(target_df)} 行")

    if source_df.empty:
        return {"success": True, "message": "无源数据需要归并", "count": len(df)}

    # 确定归并字段（备注列）—— 使用智能列名解析（支持中英文翻译匹配）
    actual_merge_field = merge_field
    if actual_merge_field not in source_df.columns:
        actual_merge_field = _resolve_column_smart(source_df, merge_field)
        if actual_merge_field:
            print(f"归并字段 '{merge_field}' 解析为: {actual_merge_field}")
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

    print(f"使用 '{actual_merge_field}' 提取目标名称，用 '{name_col}' 匹配目标记录")

    extracted = _extract_target_names(source_df, actual_merge_field, llm_batch_size)
    matched = _fuzzy_match_names(extracted, target_df, name_col)

    matched_count = sum(1 for v in matched.values() if v is not None)
    print(f"匹配成功: {matched_count}/{len(source_df)}")

    # 合并逻辑：把被合并行各列信息用 LLM 组织成通顺文字，放入目标行备注列
    # 预提取 source_df 和 target_df 为 dict（避免 ProcessPoolExecutor 中 .loc 的 GIL 开销）
    src_cols = list(source_df.columns)
    tgt_cols = list(target_df.columns)
    common_cols = [c for c in src_cols if c in tgt_cols]
    # 预构建索引→行数据的 dict，加速 ProcessPoolExecutor 中的行访问
    src_rows_dict = {idx: source_df.loc[idx].to_dict() for idx in source_df.index}
    tgt_rows_dict = {idx: target_df.loc[idx].to_dict() for idx in target_df.index}
    has_name_col = name_col in source_df.columns

    matched_items = [(src_idx, tgt_idx) for src_idx, tgt_idx in matched.items() if tgt_idx is not None]
    merge_pairs = []  # [(tgt_idx, src_info_str, src_name), ...]
    if matched_items:
        if len(matched_items) <= 200:
            merge_pairs = _build_merge_pairs_worker(
                (matched_items, src_cols, src_rows_dict, tgt_rows_dict, name_col if has_name_col else "")
            )
        else:
            chunk_size = max(1, len(matched_items) // max(1, (os.cpu_count() or 4) * 2))
            item_chunks = [matched_items[i:i + chunk_size] for i in range(0, len(matched_items), chunk_size)]
            args_list = [(c, src_cols, src_rows_dict, tgt_rows_dict, name_col if has_name_col else "") for c in item_chunks]
            # 字典查找+字符串比较，用 ThreadPoolExecutor 避免 ProcessPool 的 pickle 序列化开销
            with ThreadPoolExecutor(max_workers=min(len(item_chunks), 16)) as executor:
                futures = [executor.submit(_build_merge_pairs_worker, args) for args in args_list]
                for future in as_completed(futures):
                    merge_pairs.extend(future.result())

    print(f"需要生成归并描述: {len(merge_pairs)} 条")

    # 用 LLM 批量生成通顺文字（并行）
    merge_texts = {}  # tgt_idx -> 通顺描述文字
    if merge_pairs:
        chunk_size = llm_batch_size
        chunks = []
        for start in range(0, len(merge_pairs), chunk_size):
            chunks.append(merge_pairs[start:start + chunk_size])

        def _llm_generate_descriptions(chunk):
            items_text = "\n".join([
                f'{i + 1}. 被合并文物名称: "{p[2]}", 主要信息: {p[1]}'
                for i, p in enumerate(chunk)
            ])
            prompt = f"""请将以下每条被合并文物的主要信息，组织成通顺、完整的中文描述文字。

要求：
1. 每条描述应包含该文物的名称、年代、地址、分类等所有可用信息
2. 语言通顺自然，像一段完整的说明文字
3. 信息尽量全面，不要遗漏任何字段
4. 每条描述以"该文物原为"开头，说明其原始信息

数据：
{items_text}

请以 JSON 格式返回：
{{"results": [{{"index": 1, "description": "该文物原为XXX，年代为XXX，位于XXX..."}}, ...]}}

只返回 JSON，不要其他内容。"""
            try:
                result = call_tool("llm_generate", prompt=prompt, temperature=0.3, max_tokens=4000)["content"]
                result = result.strip()
                if result.startswith("```"):
                    lines = result.split("\n")
                    result = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0].strip("`")
                parsed = json.loads(result)
                results = parsed.get("results", [])
                chunk_results = {}
                for r in results:
                    idx_pos = r.get("index")
                    desc = r.get("description", "")
                    if idx_pos is not None and 1 <= idx_pos <= len(chunk):
                        tgt_idx = chunk[idx_pos - 1][0]
                        chunk_results[tgt_idx] = desc
                return chunk_results
            except Exception as e:
                print(f"LLM 生成描述失败: {e}")
                # 降级：用原始拼接
                return {p[0]: f"【已归并信息】{p[1]}" for p in chunk}

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(_llm_generate_descriptions, chunk): i for i, chunk in enumerate(chunks)}
            completed = 0
            for future in as_completed(futures):
                try:
                    chunk_results = future.result()
                    merge_texts.update(chunk_results)
                    completed += len(chunk_results)
                    if completed % 100 == 0 or completed == len(merge_pairs):
                        print(f"已生成 {completed}/{len(merge_pairs)} 条归并描述")
                except Exception as e:
                    print(f"LLM 生成描述批次 {futures[future]} 异常: {e}")

    # 将生成的描述批量写入目标行备注列（向量化操作，避免逐行 .loc）
    if merge_texts:
        # 构建批量更新数据
        merge_indices = list(merge_texts.keys())
        merge_texts_list = [f"【已归并信息】{merge_texts[idx]}" for idx in merge_indices]
        existing_remarks = target_df.loc[merge_indices, actual_merge_field]
        new_remarks = []
        for i, idx in enumerate(merge_indices):
            existing = existing_remarks.loc[idx] if idx in existing_remarks.index else ""
            if pd.isna(existing) or str(existing).strip() == "":
                new_remarks.append(merge_texts_list[i])
            else:
                new_remarks.append(f"{str(existing).strip()}{merge_texts_list[i]}")
        target_df.loc[merge_indices, actual_merge_field] = new_remarks
        print(f"批量更新 {len(merge_indices)} 行备注列完成")

    # 修复列名：将 'ID' 转为 snake_case 的 'id'
    if 'ID' in target_df.columns:
        target_df = target_df.rename(columns={'ID': 'id'})
        print("列名 'ID' 已重命名为 'id' (snake_case)")

    output_table = output_table_name or f"{table_name}_merged"
    records = target_df.to_dict(orient="records")

    # 分批写入：第一批用 replace 彻底重建表结构（避免旧列名残留），后续用 append 追加
    clearing_strategies = {"overwrite", "replace", "truncate"}
    for i in range(0, len(records), batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"
        elif batch_num == 1 and if_table_exists == "overwrite":
            # overwrite 不清除旧列结构，改用 replace 确保列名干净
            current_strategy = "replace"
        write_result = call_tool("write_table_data", datasource_id=ds_id, table_name=output_table, records=batch, if_table_exists=current_strategy)
        if not write_result.get("success"):
            return {"success": False, "error": f"写入失败(批次{batch_num}): {write_result.get('message', write_result)}"}
        print(f"批次 {batch_num} 写入成功: {len(batch)} 行 (策略={current_strategy})")

    print(f"归并完成: {len(df)} → {len(target_df)} 行，写入表: {output_table}")
    return {
        "success": True,
        "original_count": len(df),
        "source_count": len(source_df),
        "merged_count": matched_count,
        "final_count": len(target_df),
        "target_table": output_table,
        "target_datasource": output_datasource_name or datasource_name,
    }


def _resolve_column_smart(df, name):
    """智能解析列名：先精确/模糊匹配，找不到则用LLM翻译后匹配
    
    Args:
        df: DataFrame
        name: 用户指定的列名（可能是中文、英文或别名）
    
    Returns:
        str: 匹配到的实际列名，或 None
    """
    # 1. 先用 difflib 精确/模糊匹配
    if name in df.columns:
        col = name
    else:
        matches = difflib.get_close_matches(name, [str(c) for c in df.columns], n=1, cutoff=0.6)
        col = matches[0] if matches else None
    if col:
        return col
    
    # 2. 用 LLM 翻译列名，再匹配
    actual_cols = list(df.columns)
    prompt = f"""用户想要处理名为 "{name}" 的列，但表中实际列名为：{actual_cols}

请找出与 "{name}" 语义最相近的列名。考虑中英文翻译关系（如"备注"="remarks"="remark"="notes"，"名称"="name"="title"）。

只返回最匹配的列名（必须是上面列表中的一个），如果没有匹配的返回 null。只返回列名本身，不要其他内容。"""
    
    try:
        result = call_tool("llm_generate", prompt=prompt, temperature=0.1, max_tokens=100)["content"]
        result = result.strip().strip('"').strip("'").strip()
        
        if result and result.lower() != 'null' and result in actual_cols:
            print(f"列名 '{name}' 通过翻译匹配到 '{result}'")
            return result
    except Exception as e:
        print(f"翻译匹配列名失败: {e}")
    
    print(f"无法找到与 '{name}' 匹配的列，可用列: {actual_cols}")
    return None