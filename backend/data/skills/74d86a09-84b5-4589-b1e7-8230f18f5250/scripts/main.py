import re

def _extract_target_names(source_df: pd.DataFrame, source_field: str, llm_batch_size: int = 20) -> Dict[int, Optional[str]]:
    """从源数据的 source_field 列中提取目标实体名称，优先用正则，无法匹配的用 LLM"""
    extracted: Dict[int, Optional[str]] = {}
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
    extracted_names: Dict[int, Optional[str]],
    target_df: pd.DataFrame,
    target_field: str
) -> Dict[int, Optional[int]]:
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

    mapping: Dict[int, Optional[int]] = {}
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