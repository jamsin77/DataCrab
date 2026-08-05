from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import re


def _resolve_datasource(datasource_name: str) -> str:
    """解析数据源：先按名称查ID，查不到则假定传入的已是UUID/ID，直接使用"""
    ds_id = get_datasource_id_by_name(datasource_name)
    if ds_id:
        return ds_id
    # 传入的可能已经是数据源UUID/ID，直接使用
    return datasource_name


def _load_data(datasource_name: str, table_name: str) -> pd.DataFrame:
    """从数据源加载表数据（分块读取，支持大表）"""
    ds_id = _resolve_datasource(datasource_name)

    chunks = []
    total_rows = 0
    for chunk in iter_table_data(ds_id, table_name, chunk_size=10000):
        chunk_rows = chunk.get("rows", [])
        if chunk_rows:
            chunks.append(pd.DataFrame(chunk_rows))
            total_rows += len(chunk_rows)

    if not chunks:
        raise ValueError(f"表 '{table_name}' 中没有数据")

    df = pd.concat(chunks, ignore_index=True)
    log("info", f"加载完成: {len(df)} 行, {len(df.columns)} 列")
    return df


def _resolve_column_name(df: pd.DataFrame, column_name: str) -> str:
    """解析用户指定的列名，支持模糊匹配"""
    actual_col = resolve_column(df, column_name)
    if actual_col is None:
        raise ValueError(f"列 '{column_name}' 不存在，可用列: {list(df.columns)}")
    return actual_col


def _extract_json(text: str) -> dict:
    """从LLM返回文本中提取JSON对象"""
    text = text.strip()

    # 去除 markdown 代码块
    if "```" in text:
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                json_lines.append(line)
        text = "\n".join(json_lines).strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 尝试从文本中提取 JSON 对象
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text[start:end + 1]
        return json.loads(json_str)

    # JSON 可能被截断（没有闭合的 }），尝试补全
    if start != -1:
        json_str = text[start:]
        # 去掉末尾不完整的行（如 "14": "龙岩）
        lines = json_str.split("\n")
        complete_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 完整的行格式: "数字": "值", 或 "数字": "值"
            if re.match(r'^"\d+":\s*"[^"]*"\s*,?$', line):
                complete_lines.append(line)
            elif re.match(r'^"\d+":\s*"[^"]*"\s*$', line):
                # 最后一行可能没有逗号
                complete_lines.append(line)
            else:
                # 不完整的行，跳过
                break
        if complete_lines:
            # 重新组装 JSON
            json_str = "{\n" + ",\n".join(complete_lines) + "\n}"
            try:
                return json.loads(json_str)
            except Exception:
                pass

    raise ValueError(f"无法从LLM返回中提取JSON，原始文本前200字: {text[:200]}")


def _classify_batch(values: List[str], categories: Optional[str] = None, max_retries: int = 1) -> tuple:
    """
    使用LLM对一批唯一值进行语义分类。

    Returns:
        (value_to_category: dict, detected_categories: str or None)
    """
    import time

    values_text = "\n".join([f"{i + 1}. {v}" for i, v in enumerate(values)])

    is_extraction_target = False
    cat_list = []
    if categories:
        # 判断 categories 是"固定类别列表"还是"提取目标描述"
        cat_list = [c.strip() for c in categories.split(",") if c.strip()]
        is_extraction_target = len(cat_list) == 1 and cat_list[0] not in [
            "是", "否", "男", "女", "高", "低", "大", "小"
        ]

        if is_extraction_target:
            # categories 是提取目标（如"地级市"、"省份"），让 LLM 从每条数据中提取具体值
            system_prompt = (
                "你是一个中国地理信息提取专家，精通中国最新行政区划。请从以下每条地址数据中，提取出对应的"
                f"{cat_list[0]}名称。\n\n"
                "【核心规则】必须按照中国最新的行政区划（2024年）中的地级市进行分类。\n\n"
                "规则：\n"
                f"1. 仔细分析每条地址，提取出它所属的{cat_list[0]}\n"
                f"2. 返回的{cat_list[0]}名称必须为最新行政区划中的标准地级市名称（如\"济南市\"、\"北京市\"、\"西安市\"）\n"
                "3. 如果地址中直接包含地级市名称，直接提取\n"
                "4. 如果地址中只有区县名（如\"历城\"），根据地理知识推断所属地级市（\"历城\"→\"济南市\"）\n"
                "5. 如果地址中只有乡镇/街道名，根据地理知识推断所属地级市\n"
                "6. 【历史地名映射】很多城市因历史原因已改名或合并，必须映射到最新的地级市名称：\n"
                "   - \"沙市\"→\"荆州市\"（沙市已并入荆州）\n"
                "   - \"万县\"/\"万州\"→\"重庆市\"（万县已并入重庆）\n"
                "   - \"涪陵\"→\"重庆市\"（涪陵已并入重庆）\n"
                "   - \"宿县\"/\"宿州\"→\"宿州市\"\n"
                "   - \"巢湖\"→\"合肥市\"（巢湖地级市已撤销，并入合肥等）\n"
                "   - \"莱芜\"→\"济南市\"（莱芜已并入济南）\n"
                "   - \"思茅\"→\"普洱市\"（思茅已改名普洱）\n"
                "   - \"中甸\"→\"香格里拉市\"（属迪庆藏族自治州）\n"
                "   - \"日喀则\"→\"日喀则市\"\n"
                "   - \"昌都\"→\"昌都市\"\n"
                "   - \"林芝\"→\"林芝市\"\n"
                "   - \"山南\"→\"山南市\"\n"
                "   - \"那曲\"→\"那曲市\"\n"
                "   - \"吐鲁番\"→\"吐鲁番市\"\n"
                "   - \"哈密\"→\"哈密市\"\n"
                "   - \"海东\"→\"海东市\"\n"
                "   - 其他历史地名请根据你的地理知识映射到最新的地级市\n"
                "7. 【自治州/地区/盟】对于自治州、地区、盟，返回该自治州/地区/盟的名称（如\"凉山彝族自治州\"、\"大兴安岭地区\"、\"兴安盟\"）\n"
                "8. 【直辖市】北京、上海、天津、重庆的地址，返回直辖市名称（如\"北京市\"、\"上海市\"）\n"
                "9. 如果确实无法判断，返回\"未知\"\n"
                "10. 返回纯JSON，不要包含任何其他文字或解释\n\n"
                '请以JSON格式返回结果，格式为 {"序号": "地级市名称"}，例如：\n'
                '{"1": "济南市", "2": "北京市", "3": "西安市"}'
            )
        else:
            system_prompt = (
                "你是一个数据分类专家。请将以下数据按照语义分类到指定的类别中。\n\n"
                f"可选类别：{categories}\n\n"
                "规则：\n"
                "1. 每条数据必须归入一个类别\n"
                "2. 如果无法确定，归入最接近的类别\n"
                "3. 只能使用提供的类别名称，不要创造新类别\n"
                "4. 返回纯JSON，不要包含任何其他文字或解释\n\n"
                '请以JSON格式返回结果，格式为 {"序号": "类别"}，例如：\n'
                '{"1": "古建筑", "2": "古遗址", "3": "古建筑"}'
            )
    else:
        system_prompt = (
            "你是一个数据分类专家。请根据以下数据的语义内容进行自动分类。\n\n"
            "规则：\n"
            "1. 分析所有数据的语义特征，自动确定合适的分类\n"
            "2. 分类数量控制在3-8个之间\n"
            "3. 类别名称简洁明了（2-6个字）\n"
            "4. 每条数据必须归入一个类别\n"
            "5. 相似内容应归入同一类别\n"
            "6. 返回纯JSON，不要包含任何其他文字或解释\n\n"
            '请以JSON格式返回结果，格式为 {"序号": "类别"}，例如：\n'
            '{"1": "古建筑", "2": "古遗址", "3": "古建筑"}'
        )

    if is_extraction_target:
        prompt = f"请从以下地址数据中提取{cat_list[0]}：\n\n{values_text}"
    else:
        prompt = f"请对以下数据进行语义分类：\n\n{values_text}"

    last_error = ""
    for attempt in range(max_retries):
        if attempt > 0:
            wait_sec = min(2 * attempt, 3)
            log("info", f"等待 {wait_sec}s 后重试（第 {attempt + 1}/{max_retries} 次）")
            time.sleep(wait_sec)

        result = llm_chat(prompt, system_prompt=system_prompt, temperature=0.3, max_tokens=6000)

        # 检查空返回
        if not result or not result.strip():
            log("warn", f"LLM返回空结果（尝试 {attempt + 1}/{max_retries}）")
            last_error = "LLM返回空字符串"
            continue

        try:
            classification = _extract_json(result)

            value_to_category = {}
            used_categories = set()
            for i, v in enumerate(values):
                key = str(i + 1)
                if key in classification:
                    cat = str(classification[key]).strip()
                    value_to_category[v] = cat
                    used_categories.add(cat)
                else:
                    value_to_category[v] = "未分类"

            categories_str = ", ".join(sorted(used_categories)) if used_categories else None
            return value_to_category, categories_str
        except Exception as e:
            last_error = str(e)
            log("warn", f"LLM分类结果解析失败（尝试 {attempt + 1}/{max_retries}）: {e}")
            log("warn", f"原始返回(前300字): {result[:300]}")
            continue

    # 所有重试均失败，尝试将批次拆分为更小的子批次
    if len(values) > 10:
        log("warn", f"全批次重试失败，尝试拆分为更小子批次处理")
        mid = len(values) // 2
        left_result, left_cats = _classify_batch(values[:mid], categories, max_retries=2)
        right_result, right_cats = _classify_batch(values[mid:], categories, max_retries=2)
        merged = {**left_result, **right_result}
        all_cats = []
        if left_cats:
            all_cats.extend(left_cats.split(", "))
        if right_cats:
            all_cats.extend(right_cats.split(", "))
        cats_str = ", ".join(sorted(set(all_cats))) if all_cats else None
        return merged, cats_str

    log("error", f"批次分类彻底失败（已重试 {max_retries} 次），最后错误: {last_error}")
    return {v: "分类失败" for v in values}, None


def _rule_extract_city(address: str) -> Optional[str]:
    """基于规则的地址→地级市提取（正则匹配），无需调用LLM。
    返回地级市名称或 None（无法匹配时）。"""
    if not address:
        return None
    addr = str(address).strip()
    if not addr:
        return None

    # 直辖市
    for short, full in [("北京", "北京市"), ("上海", "上海市"), ("天津", "天津市"), ("重庆", "重庆市")]:
        if short in addr:
            return full

    # 特别行政区
    if "香港" in addr:
        return "香港特别行政区"
    if "澳门" in addr:
        return "澳门特别行政区"

    # 匹配 "XX省XX市" → 提取省后面的第一个市
    m = re.search(r'省([\u4e00-\u9fa5]{2,6}市)', addr)
    if m:
        return m.group(1)

    # 匹配 "XX自治区XX市" → 提取自治区后面的第一个市
    m = re.search(r'自治区([\u4e00-\u9fa5]{2,6}市)', addr)
    if m:
        return m.group(1)

    # 匹配自治州（如"凉山彝族自治州"、"恩施土家族苗族自治州"）
    m = re.search(r'([\u4e00-\u9fa5]{2,12}自治州)', addr)
    if m:
        return m.group(1)

    # 匹配地区（如"大兴安岭地区"）
    m = re.search(r'([\u4e00-\u9fa5]{2,6}地区)', addr)
    if m:
        return m.group(1)

    # 匹配盟（如"兴安盟"、"锡林郭勒盟"）
    m = re.search(r'([\u4e00-\u9fa5]{2,6}盟)', addr)
    if m:
        return m.group(1)

    # 地址以"XX市"开头（无省份前缀，如"济南市历城区..."）
    m = re.match(r'^([\u4e00-\u9fa5]{2,6}市)', addr)
    if m:
        return m.group(1)

    # 匹配地址中任意位置的"XX市"（取第一个，排除常见县级市）
    county_level_cities = {
        "昆山", "江阴", "义乌", "常熟", "张家港", "慈溪", "诸暨", "余姚",
        "太仓", "宜兴", "海门", "丹阳", "温岭", "瑞安", "乐清", "启东",
        "临海", "如皋", "永康", "宁海", "胶州", "平度", "莱西", "即墨",
        "滕州", "邹城", "曲阜", "兖州", "乐陵", "禹城", "临清", "新泰",
        "肥城", "章丘", "胶南", "任丘", "河间", "霸州", "三河", "迁安",
        "遵化", "武安", "南宫", "沙河", "深州", "高平", "介休", "侯马",
        "霍州", "孝义", "汾阳", "根河", "满洲里", "扎兰屯", "牙克石",
        "额尔古纳", "乌兰浩特", "阿尔山", "霍林郭勒", "丰镇", "新民",
        "瓦房店", "普兰店", "庄河", "海城", "东港", "凤城", "凌海",
        "北镇", "盖州", "大石桥", "灯塔", "调兵山", "开原", "北票",
        "凌源", "葫芦岛", "九台", "榆树", "德惠", "蛟河", "桦甸",
        "舒兰", "磐石", "公主岭", "双辽", "梅河口", "集安", "洮南",
        "大安", "临江", "和龙", "珲春", "龙井", "图们", "敦化",
        "尚志", "双城", "五常", "讷河", "北安", "五大连池", "肇东",
        "安达", "海伦", "同江", "富锦", "铁力", "虎林", "密山",
        "绥芬河", "海林", "宁安", "穆棱", "东宁", "江阴", "宜兴",
        "邳州", "新沂", "溧阳", "常熟", "张家港", "昆山", "太仓",
        "启东", "如皋", "海门", "东台", "大丰", "仪征", "高邮",
        "江都", "扬中", "句容", "丹阳", "兴化", "靖江", "泰兴",
        "慈溪", "余姚", "奉化", "瑞安", "乐清", "海宁", "平湖",
        "桐乡", "诸暨", "嵊州", "兰溪", "义乌", "东阳", "永康",
        "江山", "温岭", "临海", "龙泉", "巢湖", "桐城", "天长",
        "明光", "界首", "宁国", "福清", "长乐", "邵武", "武夷山",
        "建瓯", "永安", "石狮", "晋江", "南安", "龙海", "邵武",
        "乐平", "瑞昌", "贵溪", "瑞金", "井冈山", "樟树", "高安",
        "丰城", "德兴", "章丘", "胶州", "胶南", "即墨", "平度",
        "莱西", "滕州", "章丘", "兖州", "邹城", "曲阜", "新泰",
        "肥城", "乐陵", "禹城", "临清", "安丘", "昌邑", "高密",
        "青州", "诸城", "寿光", "栖霞", "海阳", "龙口", "莱阳",
        "莱州", "蓬莱", "招远", "荣成", "乳山", "文登", "荥阳",
        "新郑", "新密", "登封", "巩义", "偃师", "舞钢", "汝州",
        "林州", "卫辉", "辉县", "济源", "沁阳", "孟州", "禹州",
        "长葛", "义马", "灵宝", "邓州", "永城", "项城", "枣阳",
        "宜城", "老河口", "钟祥", "洪湖", "石首", "松滋", "丹江口",
        "大冶", "阳新", "应城", "安陆", "汉川", "麻城", "武穴",
        "广水", "仙桃", "天门", "潜江", "恩施", "利川", "浏阳",
        "醴陵", "湘乡", "韶山", "耒阳", "常宁", "武冈", "临湘",
        "汨罗", "津市", "沅江", "资兴", "洪江", "吉首", "连州",
        "英德", "连州", "乐昌", "南雄", "恩平", "开平", "台山",
        "鹤山", "吴川", "廉江", "雷州", "高州", "化州", "信宜",
        "高要", "四会", "兴宁", "梅州", "陆丰", "阳春", "罗定",
        "英德", "桂平", "北流", "东兴", "凭祥", "合山", "琼海",
        "万宁", "文昌", "五指山", "东方", "都江堰", "彭州", "邛崃",
        "崇州", "广汉", "什邡", "绵竹", "江油", "峨眉山", "阆中",
        "华蓥", "万源", "简阳", "西昌", "会理", "清镇", "赤水",
        "仁怀", "盘州", "兴义", "凯里", "都匀", "福泉", "铜仁",
        "昭通", "楚雄", "大理", "个旧", "开远", "蒙自", "弥勒",
        "景洪", "瑞丽", "芒市", "香格里拉", "格尔木", "德令哈",
        "玉树", "同仁", "玉门", "敦煌", "临夏", "合作", "灵武",
        "青铜峡", "中卫", "石嘴山", "吴忠", "固原", "哈密", "塔城",
        "阿勒泰", "吐鲁番", "和田", "喀什", "阿克苏", "库尔勒",
        "昌吉", "阜康", "博乐", "伊宁", "奎屯", "乌苏", "阿图什"
    }
    for m in re.finditer(r'([\u4e00-\u9fa5]{2,6})市', addr):
        city_short = m.group(1)
        if city_short not in county_level_cities:
            return city_short + "市"

    return None


def _classify_all_values(
    unique_values: List[str],
    categories: Optional[str],
    batch_size: int,
    target_column: str = ""
) -> Dict[str, str]:
    """对所有唯一值进行分批分类，返回 值→类别 映射"""
    value_to_category: Dict[str, str] = {}
    detected_categories = categories

    # ── 规则预过滤：对"地级市"等提取任务，先用正则匹配，减少LLM调用量 ──
    is_extraction = categories and len([c.strip() for c in categories.split(",") if c.strip()]) == 1
    if is_extraction:
        cat_name = categories.split(",")[0].strip()
        city_keywords = ("地级市", "城市", "市", "地级", "prefecture", "city",
                         "行政区划", "行政区域", "地区", "地域", "区域")
        should_rule_filter = any(kw in cat_name for kw in city_keywords) or \
                             any(kw in target_column for kw in city_keywords)
        if should_rule_filter:
            rule_matched = 0
            remaining_values = []
            for v in unique_values:
                city = _rule_extract_city(v)
                if city:
                    value_to_category[v] = city
                    rule_matched += 1
                else:
                    remaining_values.append(v)
            log("info", f"规则预匹配成功 {rule_matched}/{len(unique_values)} 个，剩余 {len(remaining_values)} 个需LLM处理")
            unique_values = remaining_values

            if not unique_values:
                log("info", "所有值已通过规则匹配完成，无需调用LLM")
                return value_to_category

    # ── 自适应批次大小：提取任务每条结果较长，保持较小批次避免JSON截断 ──
    if len(unique_values) > 500 and batch_size < 150:
        old_batch_size = batch_size
        batch_size = min(120, len(unique_values))
        log("info", f"唯一值较多（{len(unique_values)}），批次大小从 {old_batch_size} 调整为 {batch_size}")

    # ── 分批 ──
    batches = [unique_values[i:i + batch_size] for i in range(0, len(unique_values), batch_size)]
    total_batches = len(batches)

    # ── 并发分类（I/O 密集型，用线程池） ──
    # 如果没有预定义类别，需要先串行处理第一批以自动检测类别，再并发处理剩余批次
    if not detected_categories and batches:
        log("info", f"正在分类第 1/{total_batches} 批（{len(batches[0])} 个唯一值）— 串行（用于检测类别）")
        first_result, first_cats = _classify_batch(batches[0], detected_categories)
        value_to_category.update(first_result)
        if first_cats:
            detected_categories = first_cats
            log("info", f"自动检测到分类类别: {detected_categories}")
        parallel_batches = batches[1:]
        parallel_start = 2
    else:
        parallel_batches = batches
        parallel_start = 1

    if parallel_batches:
        max_workers = min(6, len(parallel_batches))
        log("info", f"共 {total_batches} 批，并发处理 {len(parallel_batches)} 批（最多 {max_workers} 并发）")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for idx, batch in enumerate(parallel_batches):
                batch_num = idx + parallel_start
                future = executor.submit(_classify_batch, batch, detected_categories)
                futures[future] = (batch_num, len(batch))

            for future in as_completed(futures):
                batch_num, batch_len = futures[future]
                try:
                    batch_result, _ = future.result()
                    value_to_category.update(batch_result)
                    log("info", f"第 {batch_num}/{total_batches} 批完成（{batch_len} 个唯一值）")
                except Exception as e:
                    log("error", f"第 {batch_num}/{total_batches} 批处理失败: {e}")

    return value_to_category


def _write_result(
    df: pd.DataFrame,
    datasource_name: str,
    table_name: str,
    target_column: str,
    if_table_exists: str
) -> Dict[str, Any]:
    """将分类结果写回数据源（分批写入）"""
    ds_id = _resolve_datasource(datasource_name)

    records = df.to_dict(orient="records")

    # 为新分类列添加列备注
    column_remarks = {target_column: "语义分类结果（由AI自动生成）"}

    batch_size = 1000
    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    total_batches = (len(records) + batch_size - 1) // batch_size

    for i in range(0, len(records), batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"

        log("info", f"写入第 {batch_num}/{total_batches} 批（{len(batch)} 行）")
        result = write_table_data(
            ds_id,
            table_name,
            records=batch,
            if_table_exists=current_strategy,
            column_remarks=column_remarks if batch_num == 1 else None,
        )
        if not result.get("success"):
            raise ValueError(f"写入失败: {result.get('message', '未知错误')}")

    return {"rows_written": len(records)}


def semantic_classify(
    datasource_name: str = "",
    table_name: str = "",
    column_name: str = "",
    target_column: str = "",
    mode: str = "add",
    categories: str = "",
    batch_size: int = 50,
    if_table_exists: str = "replace",
    datasource: str = "",
    table: str = "",
    column: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """
    主业务函数：对指定列进行语义分类并写回数据源。

    Parameters:
        datasource_name: 数据源名称
        table_name: 表名
        column_name: 要分类的列名
        target_column: 分类结果写入的列名（默认自动生成 {column}_分类）
        mode: add=新增列 / update=更新已有列
        categories: 预定义类别（逗号分隔），留空则AI自动检测
        batch_size: LLM每批处理的唯一值数量
        if_table_exists: 写入策略
    """
    # ── 0. 参数别名兼容 ──
    if not datasource_name and datasource:
        datasource_name = datasource
    if not table_name and table:
        table_name = table
    if not column_name and column:
        column_name = column

    # 兼容更多别名
    alias_map = {
        "source_datasource": "datasource_name",
        "source_datasource_name": "datasource_name",
        "source_table": "table_name",
        "source_table_name": "table_name",
        "classify_column": "column_name",
        "source_column": "column_name",
        "output_column": "target_column",
        "result_column": "target_column",
        "new_column_name": "target_column",
        "write_mode": "mode",
        "column_mode": "mode",
        "category_list": "categories",
        "predefined_categories": "categories",
        "llm_batch_size": "batch_size",
        "write_strategy": "if_table_exists",
        "table_exists_strategy": "if_table_exists",
    }
    for alias, canonical in alias_map.items():
        if alias in kwargs:
            val = kwargs[alias]
            if canonical == "datasource_name" and not datasource_name:
                datasource_name = val
            elif canonical == "table_name" and not table_name:
                table_name = val
            elif canonical == "column_name" and not column_name:
                column_name = val
            elif canonical == "target_column" and not target_column:
                target_column = val
            elif canonical == "mode" and not mode:
                mode = val
            elif canonical == "categories" and not categories:
                categories = val
            elif canonical == "batch_size" and not batch_size:
                batch_size = val
            elif canonical == "if_table_exists" and not if_table_exists:
                if_table_exists = val

    if not datasource_name:
        raise ValueError("缺少必需参数: datasource_name（数据源名称）")
    if not table_name:
        raise ValueError("缺少必需参数: table_name（表名）")
    if not column_name:
        raise ValueError("缺少必需参数: column_name（要分类的列名）")

    # ── 1. 加载数据 ──
    log("info", f"从数据源 '{datasource_name}' 加载表 '{table_name}'")
    df = _load_data(datasource_name, table_name)
    log("info", f"加载完成: {len(df)} 行, {len(df.columns)} 列")
    print(f"列名: {list(df.columns)}")

    if df.empty:
        return {"success": True, "message": "表为空，无需分类", "total_rows": 0}

    # ── 2. 解析源列名 ──
    actual_col = _resolve_column_name(df, column_name)
    log("info", f"分类源列: '{actual_col}'")

    # ── 3. 确定目标列名 ──
    if not target_column:
        target_column = f"{actual_col}_分类"

    if mode == "update":
        existing_col = resolve_column(df, target_column)
        if existing_col:
            target_column = existing_col
            log("info", f"更新已有列: '{target_column}'")
        else:
            log("warn", f"目标列 '{target_column}' 不存在，将新建该列")
    else:
        if target_column in df.columns:
            log("warn", f"列 '{target_column}' 已存在，将覆盖该列数据")
        else:
            log("info", f"新增列: '{target_column}'")

    # ── 4. 提取唯一值 ──
    col_series = df[actual_col].astype(str)
    null_markers = {"nan", "none", "null", "", "NaT"}
    unique_values = []
    for v in col_series.unique():
        if v and v.lower() not in null_markers:
            unique_values.append(v)

    if not unique_values:
        return {
            "success": True,
            "message": "分类列无有效数据",
            "total_rows": len(df),
        }

    log("info", f"共 {len(unique_values)} 个唯一值需要分类")

    # ── 5. LLM 分批分类 ──
    # 确保 categories 是字符串
    if categories is None:
        categories = ""
    if isinstance(categories, (list, tuple)):
        categories = ", ".join(str(c) for c in categories)
    categories = str(categories).strip()

    # 确保 batch_size 是整数
    try:
        batch_size = int(batch_size)
    except (ValueError, TypeError):
        batch_size = 50
    if batch_size < 1:
        batch_size = 50

    categories_param = categories if categories else None
    if categories_param:
        log("info", f"使用预定义类别: {categories_param}")

    value_to_category = _classify_all_values(unique_values, categories_param, batch_size, target_column)

    # ── 6. 映射回全表 ──
    def _map_value(v: str) -> str:
        if not v or v.lower() in null_markers:
            return "未分类"
        return value_to_category.get(v, "未分类")

    df[target_column] = col_series.map(_map_value)

    # ── 7. 打印分类统计 ──
    category_counts = df[target_column].value_counts()
    log("info", "分类结果统计:")
    for cat, count in category_counts.items():
        print(f"  {cat}: {count} 条")

    # ── 8. 写回数据源 ──
    log("info", f"写入结果到表 '{table_name}'（策略: {if_table_exists}）")
    write_result = _write_result(df, datasource_name, table_name, target_column, if_table_exists)

    return {
        "success": True,
        "total_rows": len(df),
        "classified_column": actual_col,
        "target_column": target_column,
        "mode": mode,
        "unique_values_classified": len(unique_values),
        "categories_found": list(category_counts.index),
        "category_distribution": {str(k): int(v) for k, v in category_counts.to_dict().items()},
        "rows_written": write_result["rows_written"],
    }


def main(**params) -> Dict[str, Any]:
    """主入口，系统注入用户参数"""
    param_aliases = {
        "datasource_name": ["datasource_name", "datasource", "source_datasource", "source_datasource_name"],
        "table_name": ["table_name", "table", "source_table", "source_table_name"],
        "column_name": ["column_name", "column", "classify_column", "source_column"],
        "target_column": ["target_column", "output_column", "result_column", "new_column_name"],
        "mode": ["mode", "write_mode", "column_mode"],
        "categories": ["categories", "category_list", "predefined_categories"],
        "batch_size": ["batch_size", "llm_batch_size"],
        "if_table_exists": ["if_table_exists", "write_strategy", "table_exists_strategy"],
    }

    resolved: Dict[str, Any] = {}
    for target_key, alias_list in param_aliases.items():
        for alias in alias_list:
            if alias in params:
                resolved[target_key] = params[alias]
                break

    # 填充默认值
    resolved.setdefault("target_column", "")
    resolved.setdefault("mode", "add")
    resolved.setdefault("categories", "")
    resolved.setdefault("batch_size", 50)
    resolved.setdefault("if_table_exists", "replace")

    return semantic_classify(**resolved)