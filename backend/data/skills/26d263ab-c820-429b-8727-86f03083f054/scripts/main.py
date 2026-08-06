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
    """从数据源加载表数据（小表用query_table_data一次性加载，大表用分块读取）"""
    ds_id = _resolve_datasource(datasource_name)

    # 先尝试一次性加载（适用于万行以内的表，更快更可靠）
    result = query_table_data(ds_id, table_name, limit=10000)
    if result.get("success") and result.get("data"):
        df = pd.DataFrame(result["data"], columns=result.get("columns"))
        # 如果数据量接近上限，可能还有更多数据，切换到分块读取
        if len(df) < 9500:
            log("info", f"加载完成: {len(df)} 行, {len(df.columns)} 列")
            return df
        log("info", f"数据量较大（{len(df)}行），切换到分块读取")

    # 大表分块读取
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
        "高要", "四会", "兴宁", "陆丰", "阳春", "罗定",
        "英德", "桂平", "北流", "东兴", "凭祥", "合山", "琼海",
        "万宁", "文昌", "五指山", "东方", "都江堰", "彭州", "邛崃",
        "崇州", "广汉", "什邡", "绵竹", "江油", "峨眉山", "阆中",
        "华蓥", "万源", "简阳", "西昌", "会理", "清镇", "赤水",
        "仁怀", "盘州", "兴义", "凯里", "都匀", "福泉",
        "楚雄", "大理", "个旧", "开远", "蒙自", "弥勒",
        "景洪", "瑞丽", "芒市", "香格里拉", "格尔木", "德令哈",
        "玉树", "同仁", "玉门", "敦煌", "临夏", "合作", "灵武",
        "青铜峡", "塔城",
        "阿勒泰", "和田", "喀什", "阿克苏", "库尔勒",
        "昌吉", "阜康", "博乐", "伊宁", "奎屯", "乌苏", "阿图什"
    }
    for m in re.finditer(r'([\u4e00-\u9fa5]{2,6})市', addr):
        city_short = m.group(1)
        if city_short not in county_level_cities:
            return city_short + "市"

    return None


def _post_process_city(city: str) -> str:
    """后处理：清理地级市名称，修正县级市、历史名称、前缀等问题"""
    if not city or city in ("未知", "未分类", "分类失败", ""):
        return city
    city = str(city).strip()

    # 1. 去除省份/自治区前缀（包括被截断的前缀如"疆维吾尔自治区"、"藏自治区"等）
    city = re.sub(r'^[\u4e00-\u9fa5]*省', '', city)
    city = re.sub(r'^[\u4e00-\u9fa5]*自治区', '', city)
    if city.startswith("治区"):
        city = city[2:]

    # 2. 处理"地级市+县级市"模式（如"晋城市高平市"→"晋城市"）
    m = re.match(r'^([\u4e00-\u9fa5]{2,6}市)[\u4e00-\u9fa5]+市$', city)
    if m:
        city = m.group(1)

    # 3. 历史名称→最新名称
    _OLD_NEW = {
        "襄樊市": "襄阳市", "莱芜市": "济南市", "思茅市": "普洱市",
        "海东地区": "海东市", "昌都地区": "昌都市", "山南地区": "山南市",
        "那曲地区": "那曲市", "吐鲁番地区": "吐鲁番市", "哈密地区": "哈密市",
        "日喀则地区": "日喀则市", "巢湖市": "合肥市",
    }
    if city in _OLD_NEW:
        return _OLD_NEW[city]

    # 4. 县级市→地级市/自治州映射
    _COUNTY_MAP = {
        "登封市": "郑州市", "荥阳市": "郑州市", "新郑市": "郑州市", "新密市": "郑州市", "巩义市": "郑州市",
        "偃师市": "洛阳市", "汝州市": "平顶山市", "舞钢市": "平顶山市", "林州市": "安阳市",
        "卫辉市": "新乡市", "辉县市": "新乡市", "沁阳市": "焦作市", "孟州市": "焦作市",
        "禹州市": "许昌市", "长葛市": "许昌市", "义马市": "三门峡市", "灵宝市": "三门峡市",
        "邓州市": "南阳市", "永城市": "商丘市", "项城市": "周口市",
        "章丘市": "济南市", "胶州市": "青岛市", "平度市": "青岛市", "莱西市": "青岛市",
        "滕州市": "枣庄市", "邹城市": "济宁市", "兖州市": "济宁市", "曲阜市": "济宁市",
        "新泰市": "泰安市", "肥城市": "泰安市", "乐陵市": "德州市", "禹城市": "德州市",
        "临清市": "聊城市", "安丘市": "潍坊市", "昌邑市": "潍坊市", "高密市": "潍坊市",
        "青州市": "潍坊市", "诸城市": "潍坊市", "寿光市": "潍坊市",
        "栖霞市": "烟台市", "海阳市": "烟台市", "龙口市": "烟台市", "莱阳市": "烟台市",
        "莱州市": "烟台市", "招远市": "烟台市", "荣成市": "威海市", "乳山市": "威海市",
        "高平市": "晋城市", "介休市": "晋中市", "汾阳市": "吕梁市", "霍州市": "临汾市",
        "孝义市": "吕梁市", "侯马市": "临汾市", "原平市": "忻州市", "河津市": "运城市", "永济市": "运城市",
        "河间市": "沧州市", "任丘市": "沧州市", "霸州市": "廊坊市", "三河市": "廊坊市",
        "迁安市": "唐山市", "遵化市": "唐山市", "武安市": "邯郸市", "南宫市": "邢台市",
        "沙河市": "邢台市", "深州市": "衡水市", "定州市": "保定市", "涿州市": "保定市",
        "泊头市": "沧州市", "黄骅市": "沧州市", "辛集市": "石家庄市",
        "邳州市": "徐州市", "新沂市": "徐州市", "溧阳市": "常州市", "常熟市": "苏州市",
        "张家港市": "苏州市", "昆山市": "苏州市", "太仓市": "苏州市", "启东市": "南通市",
        "如皋市": "南通市", "东台市": "盐城市", "仪征市": "扬州市", "高邮市": "扬州市",
        "扬中市": "镇江市", "句容市": "镇江市", "丹阳市": "镇江市", "兴化市": "泰州市",
        "靖江市": "泰州市", "泰兴市": "泰州市", "江阴市": "无锡市", "宜兴市": "无锡市",
        "慈溪市": "宁波市", "余姚市": "宁波市", "瑞安市": "温州市", "乐清市": "温州市",
        "海宁市": "嘉兴市", "平湖市": "嘉兴市", "桐乡市": "嘉兴市", "诸暨市": "绍兴市",
        "嵊州市": "绍兴市", "兰溪市": "金华市", "义乌市": "金华市", "东阳市": "金华市",
        "永康市": "金华市", "江山市": "衢州市", "温岭市": "台州市", "临海市": "台州市",
        "龙泉市": "丽水市", "建德市": "杭州市",
        "桐城市": "安庆市", "天长市": "滁州市", "明光市": "滁州市", "界首市": "阜阳市", "宁国市": "宣城市",
        "福清市": "福州市", "邵武市": "南平市", "武夷山市": "南平市", "建瓯市": "南平市",
        "永安市": "三明市", "石狮市": "泉州市", "晋江市": "泉州市", "南安市": "泉州市",
        "乐平市": "景德镇市", "瑞昌市": "九江市", "贵溪市": "鹰潭市", "瑞金市": "赣州市",
        "井冈山市": "吉安市", "樟树市": "宜春市", "高安市": "宜春市", "丰城市": "宜春市", "德兴市": "上饶市",
        "枣阳市": "襄阳市", "宜城市": "襄阳市", "老河口市": "襄阳市", "钟祥市": "荆门市",
        "洪湖市": "荆州市", "石首市": "荆州市", "松滋市": "荆州市", "丹江口市": "十堰市",
        "大冶市": "黄石市", "应城市": "孝感市", "安陆市": "孝感市", "汉川市": "孝感市",
        "麻城市": "黄冈市", "武穴市": "黄冈市", "广水市": "随州市",
        "浏阳市": "长沙市", "醴陵市": "株洲市", "湘乡市": "湘潭市", "韶山市": "湘潭市",
        "耒阳市": "衡阳市", "常宁市": "衡阳市", "武冈市": "邵阳市", "临湘市": "岳阳市",
        "汨罗市": "岳阳市", "津市市": "常德市", "沅江市": "益阳市", "资兴市": "郴州市",
        "洪江市": "怀化市", "吉首市": "湘西土家族苗族自治州",
        "连州市": "清远市", "英德市": "清远市", "乐昌市": "韶关市", "南雄市": "韶关市",
        "恩平市": "江门市", "开平市": "江门市", "台山市": "江门市", "鹤山市": "江门市",
        "吴川市": "湛江市", "廉江市": "湛江市", "雷州市": "湛江市", "高州市": "茂名市",
        "化州市": "茂名市", "信宜市": "茂名市", "高要市": "肇庆市", "四会市": "肇庆市",
        "兴宁市": "梅州市", "陆丰市": "汕尾市", "阳春市": "阳江市", "罗定市": "云浮市",
        "桂平市": "贵港市", "北流市": "玉林市", "东兴市": "防城港市", "凭祥市": "崇左市", "合山市": "来宾市",
        "都江堰市": "成都市", "彭州市": "成都市", "邛崃市": "成都市", "崇州市": "成都市",
        "广汉市": "德阳市", "什邡市": "德阳市", "绵竹市": "德阳市", "江油市": "绵阳市",
        "峨眉山市": "乐山市", "阆中市": "南充市", "华蓥市": "广安市", "万源市": "达州市",
        "简阳市": "成都市", "西昌市": "凉山彝族自治州", "会理市": "凉山彝族自治州",
        "清镇市": "贵阳市", "赤水市": "遵义市", "仁怀市": "遵义市", "盘州市": "六盘水市",
        "兴义市": "黔西南布依族苗族自治州", "凯里市": "黔东南苗族侗族自治州",
        "都匀市": "黔南布依族苗族自治州", "福泉市": "黔南布依族苗族自治州",
        "楚雄市": "楚雄彝族自治州", "大理市": "大理白族自治州",
        "个旧市": "红河哈尼族彝族自治州", "开远市": "红河哈尼族彝族自治州",
        "蒙自市": "红河哈尼族彝族自治州", "弥勒市": "红河哈尼族彝族自治州",
        "景洪市": "西双版纳傣族自治州", "瑞丽市": "德宏傣族景颇族自治州",
        "芒市": "德宏傣族景颇族自治州", "香格里拉市": "迪庆藏族自治州", "安宁市": "昆明市",
        "韩城市": "渭南市", "华阴市": "渭南市", "兴平市": "咸阳市",
        "玉门市": "酒泉市", "敦煌市": "酒泉市", "临夏市": "临夏回族自治州", "合作市": "甘南藏族自治州",
        "格尔木市": "海西蒙古族藏族自治州", "德令哈市": "海西蒙古族藏族自治州",
        "玉树市": "玉树藏族自治州", "同仁市": "黄南藏族自治州",
        "灵武市": "银川市", "青铜峡市": "吴忠市",
        "塔城市": "塔城地区", "阿勒泰市": "阿勒泰地区", "和田市": "和田地区",
        "喀什市": "喀什地区", "阿克苏市": "阿克苏地区", "库尔勒市": "巴音郭楞蒙古自治州",
        "昌吉市": "昌吉回族自治州", "阜康市": "昌吉回族自治州", "博乐市": "博尔塔拉蒙古自治州",
        "伊宁市": "伊犁哈萨克自治州", "奎屯市": "伊犁哈萨克自治州", "乌苏市": "塔城地区",
        "阿图什市": "克孜勒苏柯尔克孜自治州",
        "丰镇市": "乌兰察布市", "根河市": "呼伦贝尔市", "满洲里市": "呼伦贝尔市",
        "扎兰屯市": "呼伦贝尔市", "牙克石市": "呼伦贝尔市", "额尔古纳市": "呼伦贝尔市",
        "乌兰浩特市": "兴安盟", "阿尔山市": "兴安盟", "霍林郭勒市": "通辽市",
        "新民市": "沈阳市", "瓦房店市": "大连市", "普兰店市": "大连市", "庄河市": "大连市",
        "海城市": "鞍山市", "东港市": "丹东市", "凤城市": "丹东市", "凌海市": "锦州市",
        "北镇市": "锦州市", "盖州市": "营口市", "大石桥市": "营口市", "灯塔市": "辽阳市",
        "调兵山市": "铁岭市", "开原市": "铁岭市", "北票市": "朝阳市", "凌源市": "朝阳市",
        "榆树市": "长春市", "德惠市": "长春市", "蛟河市": "吉林市", "桦甸市": "吉林市",
        "舒兰市": "吉林市", "磐石市": "吉林市", "双辽市": "四平市", "梅河口市": "通化市",
        "集安市": "通化市", "洮南市": "白城市", "大安市": "白城市", "临江市": "白山市",
        "和龙市": "延边朝鲜族自治州", "珲春市": "延边朝鲜族自治州", "龙井市": "延边朝鲜族自治州",
        "图们市": "延边朝鲜族自治州", "敦化市": "延边朝鲜族自治州",
        "尚志市": "哈尔滨市", "五常市": "哈尔滨市", "讷河市": "齐齐哈尔市",
        "北安市": "黑河市", "五大连池市": "黑河市", "肇东市": "绥化市", "安达市": "绥化市",
        "海伦市": "绥化市", "同江市": "佳木斯市", "富锦市": "佳木斯市", "铁力市": "伊春市",
        "虎林市": "鸡西市", "密山市": "鸡西市", "绥芬河市": "牡丹江市", "海林市": "牡丹江市",
        "宁安市": "牡丹江市", "穆棱市": "牡丹江市", "东宁市": "牡丹江市",
        "琼海市": "海南省直辖", "万宁市": "海南省直辖", "文昌市": "海南省直辖",
        "五指山市": "海南省直辖", "东方市": "海南省直辖",
    }
    if city in _COUNTY_MAP:
        return _COUNTY_MAP[city]

    return city


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
        if is_extraction:
            batch_size = min(50, len(unique_values))
        else:
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

    # ── 5.5 后处理：清理地级市名称（修正县级市、历史名称、前缀等） ──
    if categories_param and len(categories_param.split(",")) == 1:
        cat_name = categories_param.split(",")[0].strip()
        city_keywords = ("地级市", "城市", "市", "行政区划", "行政区域")
        if any(kw in cat_name for kw in city_keywords) or any(kw in target_column for kw in city_keywords):
            value_to_category = {k: _post_process_city(v) for k, v in value_to_category.items()}
            log("info", "已对分类结果进行后处理（清理县级市、历史名称、前缀等）")

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