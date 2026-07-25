import re
from datetime import datetime
from typing import Dict, Any, List, Optional

# ============================================================
# 甯歌鍑瘉鎷奸煶鈫掍腑鏂囨槧灏勮〃
# ============================================================
PINYIN_DOC_MAP = {
    "yingyezhizhao": "钀ヤ笟鎵х収",
    "shenfenzheng": "韬唤璇?,
    "shenfenzhengzhengmian": "韬唤璇侊紙姝ｉ潰锛?,
    "shenfenzhengbeimian": "韬唤璇侊紙鑳岄潰锛?,
    "danweicunkuanzhengmingshenqingshu": "鍗曚綅瀛樻璇佹槑鐢宠涔?,
    "gerensuodeshuiwanshuipingzheng": "涓汉鎵€寰楃◣瀹岀◣鍑瘉",
    "kaihuxukezheng": "寮€鎴疯鍙瘉",
    "zuzhijigoudaimazheng": "缁勭粐鏈烘瀯浠ｇ爜璇?,
    "shuiwudengjizheng": "绋庡姟鐧昏璇?,
    "gongshangdengjizheng": "宸ュ晢鐧昏璇?,
    "yinhangliushui": "閾惰娴佹按",
    "cunkuanzhengming": "瀛樻璇佹槑",
    "zizhizhengshu": "璧勮川璇佷功",
    "hetong": "鍚堝悓",
    "fapiao": "鍙戠エ",
    "baodan": "淇濆崟",
    "xukezheng": "璁稿彲璇?,
    "zhixingzheng": "鎵ц璇?,
    "chuchanghegezheng": "鍑哄巶鍚堟牸璇?,
    "jiancebaogao": "妫€娴嬫姤鍛?,
    "zhiliangrenzhengzhengshu": "璐ㄩ噺璁よ瘉璇佷功",
    "anquanxukezheng": "瀹夊叏璁稿彲璇?,
    "yingyezhizhaofuben": "钀ヤ笟鎵х収锛堝壇鏈級",
    "yingyezhizhaozhengben": "钀ヤ笟鎵х収锛堟鏈級",
}

# ============================================================
# 鍒楀畾涔夛紙鑻辨枃鍒楀悕 + 涓枃澶囨敞锛?# ============================================================
COLUMN_REMARKS = {
    "id": "鍞竴鏍囪瘑锛?浣嶆暟瀛楅浂琛ラ綈",
    "file_name": "鏂囦欢鍚嶇О",
    "file_path": "鏂囦欢璺緞",
    "extension": "鏂囦欢鎵╁睍鍚?,
    "size_bytes": "鏂囦欢澶у皬锛堝瓧鑺傦級",
    "size_human": "鏂囦欢澶у皬锛堝彲璇绘牸寮忥級",
    "modified_time": "鏂囦欢淇敼鏃堕棿",
    "parent_dir": "鏂囦欢鎵€鍦ㄧ洰褰?,
    "doc_type": "鍑瘉绫诲瀷锛堜粠鏂囦欢鍚嶆彁鍙栵級",
    "doc_type_pinyin": "鍑瘉绫诲瀷鎷奸煶",
    "extraction_status": "鎻愬彇鐘舵€?,
    "extracted_info": "OCR鎻愬彇鐨勫叧閿俊鎭紙JSON鏍煎紡锛?,
    "review_note": "瀹℃牳澶囨敞",
    "timestamp": "鏁版嵁瀵煎叆鏃堕棿鎴?,
}

TABLE_REMARK = "鍑瘉鍥剧墖鍏抽敭淇℃伅鎻愬彇缁撴灉"


# ============================================================
# 浠庢枃浠跺悕鎻愬彇鎷奸煶鍓嶇紑
# ============================================================
def extract_pinyin_prefix(file_name: str) -> str:
    """浠庢枃浠跺悕涓彁鍙栨嫾闊冲墠缂€锛圲UID涔嬪墠鐨勯儴鍒嗭級銆?
    Args:
        file_name: 鏂囦欢鍚嶏紝濡?danweicunkuanzhengmingshenqingshu_50fc3589-xxx.jpg

    Returns:
        鎷奸煶鍓嶇紑锛屽 danweicunkuanzhengmingshenqingshu
    """
    if not file_name:
        return ""
    # 鍘绘帀鎵╁睍鍚?    base = re.sub(r'\.[^.]+$', '', file_name)
    # 鎸?UUID 妯″紡鍒嗗壊锛?-4-4-4-12 鏍煎紡锛?    parts = re.split(r'_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', base)
    prefix = parts[0].strip('_') if parts else base
    return prefix


# ============================================================
# 鎵归噺缈昏瘧鏈煡鎷奸煶鍓嶇紑
# ============================================================
def batch_translate_pinyin(unknown_pinyins: List[str]) -> Dict[str, str]:
    """浣跨敤 LLM 鎵归噺缈昏瘧鏈煡鎷奸煶鍓嶇紑涓轰腑鏂囷紝鍚?娆￠噸璇曘€?
    Args:
        unknown_pinyins: 鏈湪鏄犲皠琛ㄤ腑鎵惧埌鐨勬嫾闊冲墠缂€鍒楄〃銆?
    Returns:
        鎷奸煶鈫掍腑鏂囩殑鏄犲皠瀛楀吀銆?    """
    if not unknown_pinyins:
        return {}

    result_map: Dict[str, str] = {}
    # 姣忔澶勭悊鏈€澶?10 涓?    for i in range(0, len(unknown_pinyins), 10):
        batch = unknown_pinyins[i:i + 10]
        pinyin_list = "\n".join(f"{idx+1}. {p}" for idx, p in enumerate(batch))
        prompt = f"""浠ヤ笅鏄腑鍥藉嚟璇?璇佷欢鏂囦欢鍚嶇殑鎷奸煶鍓嶇紑锛岃灏嗘瘡涓嫾闊崇炕璇戜负瀵瑰簲鐨勪腑鏂囪瘉浠跺悕绉般€?鍙繑鍥炵炕璇戠粨鏋滐紝姣忚涓€涓紝鏍煎紡涓猴細鎷奸煶=涓枃
涓嶈鏈夊浣欒В閲娿€?
{pinyin_list}"""

        # 鏈€澶氶噸璇?2 娆★紙鍒濇 + 1 娆￠噸璇曪級
        for attempt in range(2):
            try:
                resp = llm_chat(prompt, temperature=0.1, max_tokens=500)
                for line in resp.strip().split("\n"):
                    line = line.strip()
                    if "=" in line:
                        parts = line.split("=", 1)
                        py = parts[0].strip().lstrip("0123456789. ")
                        cn = parts[1].strip()
                        if py and cn:
                            result_map[py] = cn
                break  # 鎴愬姛鍒欒烦鍑洪噸璇曞惊鐜?            except Exception as e:
                log("warn", f"LLM缈昏瘧鎷奸煶澶辫触 (灏濊瘯 {attempt+1}/2): {e}")
                if attempt == 0:
                    log("info", "閲嶈瘯涓?..")

    return result_map


# ============================================================
# 鍒嗘壒鍐欏叆
# ============================================================
def _write_records(records: List[Dict[str, Any]], target_ds: str, table_name: str,
                   if_table_exists: str, batch_size: int = 500,
                   table_remark: str = "", column_remarks: Optional[Dict[str, str]] = None) -> None:
    """鍒嗘壒鍐欏叆璁板綍鍒扮洰鏍囪〃銆?
    绗竴鎵逛娇鐢ㄥ師濮嬪啓鍏ョ瓥鐣ワ紝鍚庣画鎵规鑷姩鍒囨崲涓?append銆?    浠呬娇鐢?records 鍙傛暟鍐欏叆锛屼笉浣跨敤 DataFrame 鏂瑰紡銆?
    Args:
        records: 寰呭啓鍏ョ殑璁板綍鍒楄〃銆?        target_ds: 鐩爣鏁版嵁婧?ID銆?        table_name: 鐩爣琛ㄥ悕銆?        if_table_exists: 鍐欏叆绛栫暐銆?        batch_size: 姣忔壒澶у皬銆?        table_remark: 琛ㄥ娉ㄣ€?        column_remarks: 鍒楀娉ㄥ瓧鍏搞€?
    Raises:
        RuntimeError: 褰?write_table_data 杩斿洖澶辫触鎴栨姏鍑哄紓甯告椂銆?    """
    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    total = len(records)

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"

        write_result = None
        try:
            write_result = write_table_data(
                target_ds, table_name,
                records=batch,
                if_table_exists=current_strategy,
                table_remark=table_remark,
                column_remarks=column_remarks,
            )
            print(f"  [DEBUG] write_table_data 杩斿洖: {write_result}")
        except Exception as we:
            raise RuntimeError(f"write_table_data 寮傚父 (鎵规 {batch_num}): {we}")

        if isinstance(write_result, dict) and not write_result.get("success", True):
            err_msg = write_result.get("error", write_result.get("message", str(write_result)))
            # 濡傛灉 fail 绛栫暐鍥犺〃宸插瓨鍦ㄥけ璐ワ紝鑷姩閲嶈瘯 truncate
            if current_strategy == "fail" and "宸插瓨鍦? in str(err_msg):
                log("warn", f"琛ㄥ凡瀛樺湪锛宖ail 绛栫暐澶辫触锛岃嚜鍔ㄥ垏鎹负 truncate 閲嶈瘯...")
                try:
                    write_result = write_table_data(
                        target_ds, table_name,
                        records=batch,
                        if_table_exists="truncate",
                        table_remark=table_remark,
                        column_remarks=column_remarks,
                    )
                    print(f"  [DEBUG] truncate 閲嶈瘯杩斿洖: {write_result}")
                except Exception as we2:
                    raise RuntimeError(f"truncate 閲嶈瘯涔熷け璐?(鎵规 {batch_num}): {we2}")
                if isinstance(write_result, dict) and not write_result.get("success", True):
                    raise RuntimeError(f"truncate 閲嶈瘯杩斿洖澶辫触 (鎵规 {batch_num}): {write_result}")
            else:
                raise RuntimeError(f"write_table_data 杩斿洖澶辫触 (鎵规 {batch_num}): {err_msg}")

        written = min(i + batch_size, total)
        print(f"  宸插啓鍏ョ {batch_num} 鎵? {len(batch)} 鏉?(绱 {written}/{total})")


# ============================================================
# 鏍稿績涓氬姟鍑芥暟
# ============================================================
def extract_image_info(
    source_datasource_name: str = "",
    source_table_name: str = "",
    target_datasource_name: str = "",
    target_table_name: str = "credential_extracted_info",
    image_column: str = "file_path",
    doc_type: str = "auto",
    if_table_exists: str = "truncate",
    batch_size: int = 500,
    enable_vectorization: bool = False,
    vector_datasource_name: str = "",
    vector_table_name: str = "",
    enable_translation: bool = False,
    translation_target_lang: str = "",
    **kwargs,
) -> Dict[str, Any]:
    # 澶勭悊骞冲彴鍙兘浼犲叆鐨勫埆鍚嶅弬鏁?    if not source_datasource_name and kwargs.get("datasource"):
        source_datasource_name = kwargs["datasource"]
    if not source_table_name and kwargs.get("table_name"):
        source_table_name = kwargs["table_name"]
    if not source_datasource_name and kwargs.get("source_datasource"):
        source_datasource_name = kwargs["source_datasource"]
    if not source_table_name and kwargs.get("source_table"):
        source_table_name = kwargs["source_table"]
    if not target_datasource_name and kwargs.get("target_datasource"):
        target_datasource_name = kwargs["target_datasource"]
    if not target_table_name or target_table_name == "credential_extracted_info":
        if kwargs.get("target_table"):
            target_table_name = kwargs["target_table"]
    """浠庡嚟璇佸簱璇诲彇鍥剧墖鏂囦欢鍒楄〃锛屼娇鐢∣CR鎻愬彇鍏抽敭淇℃伅锛屽啓鍏ュ嚟璇佹绱㈠簱銆?
    浠庢枃浠跺悕涓彁鍙栧嚟璇佺被鍨嬶紙鎷奸煶鈫掍腑鏂囷級锛屼娇鐢?llm_vision 瀵规瘡寮犲浘鐗囪繘琛孫CR璇嗗埆锛?    鎻愬彇鍏抽敭淇℃伅銆傚啓鍏ョ洰鏍囪〃鏃惰嚜鍔ㄧ敓鎴愯嫳鏂囧垪鍚嶅拰涓枃澶囨敞锛?    娣诲姞 ID锛?浣嶉浂琛ラ綈锛夊拰鏃堕棿鎴冲垪銆?
    Args:
        source_datasource_name: 婧愭暟鎹簮鍚嶇О銆?        source_table_name: 婧愯〃鍚嶃€?        target_datasource_name: 鐩爣鏁版嵁婧愬悕绉般€?        target_table_name: 鐩爣琛ㄥ悕銆?        image_column: 鍥剧墖璺緞鍒楀悕銆?        doc_type: 鏂囨。绫诲瀷锛坅uto/id_card/business_license锛夈€?        if_table_exists: 鍐欏叆绛栫暐銆?        batch_size: 鍒嗘壒鍐欏叆鎵规澶у皬銆?        enable_vectorization: 鏄惁鍚敤鍥剧墖鍚戦噺鍖栥€?        vector_datasource_name: 鍚戦噺搴撴暟鎹簮鍚嶇О銆?        vector_table_name: 鍚戦噺搴撹〃鍚嶃€?        enable_translation: 鏄惁鍚敤缈昏瘧銆?        translation_target_lang: 缈昏瘧鐩爣璇█銆?
    Returns:
        鍖呭惈 success銆乼otal_rows銆乧olumns 绛夊瓧娈电殑瀛楀吀銆?    """
    # ---- 1. 鑾峰彇鏁版嵁婧?ID ----
    log("info", f"鑾峰彇婧愭暟鎹簮 ID: {source_datasource_name}")
    source_ds = get_datasource_id_by_name(source_datasource_name)
    if not source_ds:
        return {"success": False, "error": f"鎵句笉鍒版簮鏁版嵁婧? {source_datasource_name}", "message": "鏁版嵁婧愬悕绉版牎楠屽け璐?}

    log("info", f"鑾峰彇鐩爣鏁版嵁婧?ID: {target_datasource_name}")
    target_ds = get_datasource_id_by_name(target_datasource_name)
    if not target_ds:
        return {"success": False, "error": f"鎵句笉鍒扮洰鏍囨暟鎹簮: {target_datasource_name}", "message": "鏁版嵁婧愬悕绉版牎楠屽け璐?}

    # ---- 2. 璇诲彇婧愭暟鎹?----
    log("info", f"璇诲彇婧愯〃鏁版嵁: {source_table_name}")
    result = query_table_data(source_ds, source_table_name, limit=10000)
    if not isinstance(result, dict) or not result.get("success"):
        return {"success": False, "error": f"璇诲彇婧愯〃澶辫触: {result}", "message": "鏁版嵁璇诲彇寮傚父"}

    data = result.get("data", [])
    source_columns = result.get("columns", [])

    if not data:
        return {"success": False, "error": "婧愯〃鏃犳暟鎹?, "message": f"婧愯〃 {source_table_name} 杩斿洖绌烘暟鎹?}

    print(f"婧愭暟鎹鍙栨垚鍔? {len(data)} 鏉? 鍒? {source_columns}")

    # ---- 3. 鎻愬彇鎵€鏈夋嫾闊冲墠缂€锛屾壒閲忕炕璇戞湭鐭ョ被鍨?----
    log("info", "浠庢枃浠跺悕鎻愬彇鍑瘉绫诲瀷...")
    all_pinyins = set()
    for row in data:
        if isinstance(row, (list, tuple)):
            row_dict = dict(zip(source_columns, row))
        elif isinstance(row, dict):
            row_dict = dict(row)
        else:
            row_dict = {}
        file_name = str(row_dict.get("file_name", ""))
        prefix = extract_pinyin_prefix(file_name)
        if prefix:
            all_pinyins.add(prefix)

    # 棰濆鐨勮嫳鏂?鎷奸煶鍓嶇紑鏄犲皠锛圠LM鍙兘缈昏瘧澶辫触锛?    EXTRA_PREFIX_MAP = {
        "institution_basic_information_reporting_form": "鏈烘瀯鍩烘湰淇℃伅鎶ュ憡琛?,
        "yiditongyezhanghukailitongzhishu": "寮傚湴閫氶摱琛岃处鎴峰紑绔嬮€氱煡涔?,
        "yinjianka": "閾剁洃鍗?,
    }

    # 鍖哄垎宸茬煡鍜屾湭鐭?    unknown_pinyins = [p for p in all_pinyins if p not in PINYIN_DOC_MAP and p not in EXTRA_PREFIX_MAP]
    known_count = len(all_pinyins) - len(unknown_pinyins)
    print(f"  鍑瘉绫诲瀷: 宸茬煡 {known_count} 绉? 鏈煡 {len(unknown_pinyins)} 绉?)

    # 鍚堝苟鏄犲皠琛?    full_map = dict(PINYIN_DOC_MAP)
    full_map.update(EXTRA_PREFIX_MAP)
    if unknown_pinyins:
        log("info", f"浣跨敤 LLM 缈昏瘧 {len(unknown_pinyins)} 涓湭鐭ユ嫾闊冲墠缂€...")
        translated = batch_translate_pinyin(unknown_pinyins)
        full_map.update(translated)
        print(f"  LLM 缈昏瘧瀹屾垚: 鎴愬姛 {len(translated)} 涓?)

    # ---- 4. 鏁版嵁鍔犲伐 + OCR鎻愬彇鍏抽敭淇℃伅 ----
    log("info", "寮€濮嬫暟鎹姞宸? 鐢熸垚ID銆佹椂闂存埑銆佸嚟璇佺被鍨嬨€丱CR鎻愬彇鍏抽敭淇℃伅...")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    processed_records: List[Dict[str, Any]] = []
    ocr_success_count = 0
    ocr_fail_count = 0

    for idx, row in enumerate(data):
        if isinstance(row, (list, tuple)):
            row_dict = dict(zip(source_columns, row))
        elif isinstance(row, dict):
            row_dict = dict(row)
        else:
            row_dict = {}

        file_name = str(row_dict.get("file_name", ""))
        file_path = str(row_dict.get("file_path", ""))
        pinyin_prefix = extract_pinyin_prefix(file_name)
        doc_type_cn = full_map.get(pinyin_prefix, pinyin_prefix if pinyin_prefix else "鏈煡鍑瘉绫诲瀷")

        # OCR鎻愬彇鍏抽敭淇℃伅
        extracted_info = ""
        extraction_status = "宸叉彁鍙?
        review_note = ""

        try:
            # 浣跨敤llm_vision鎻愬彇鍏抽敭淇℃伅锛坙lm_vision 绗竴涓弬鏁版槸鍥剧墖璺緞锛屽唴閮ㄨ嚜鍔?base64 缂栫爜锛?            ocr_prompt = (
                f"杩欐槸涓€寮爗doc_type_cn}鐨勫浘鐗囥€傝浠旂粏璇嗗埆骞舵彁鍙栧浘鐗囦腑鎵€鏈夊彲瑙佺殑鏂囧瓧淇℃伅锛?
                f"鍖呮嫭浣嗕笉闄愪簬锛氳瘉浠跺悕绉般€佽瘉浠跺彿鐮併€佹寔鏈変汉/鏈烘瀯鍚嶇О銆佹湁鏁堟湡銆佸彂璇佹満鍏炽€侀噾棰濈瓑鍏抽敭瀛楁銆?
                f"璇蜂互JSON鏍煎紡杩斿洖鎻愬彇鐨勪俊鎭紝涓嶈鏈夊浣欒В閲娿€?
            )
            ocr_result = llm_vision(file_path, ocr_prompt)
            extracted_info = str(ocr_result).strip() if ocr_result else ""

            if extracted_info:
                extraction_status = "宸叉彁鍙?
                ocr_success_count += 1
            else:
                extraction_status = "鎻愬彇澶辫触"
                review_note = "OCR杩斿洖绌虹粨鏋?
                ocr_fail_count += 1
        except Exception as e:
            extraction_status = "鎻愬彇澶辫触"
            err_str = str(e)
            if "Error code:" in err_str or "content.type" in err_str:
                code_match = re.search(r"code['\"]:\s*['\"](\d+)['\"]", err_str)
                error_code = code_match.group(1) if code_match else "鏈煡"
                review_note = f"OCR鏈嶅姟璋冪敤寮傚父锛堥敊璇爜: {error_code}锛?
            else:
                review_note = f"OCR寮傚父: {err_str[:100]}"
            extracted_info = ""
            ocr_fail_count += 1

        # 鏋勫缓鏂拌褰?        record: Dict[str, Any] = {}
        record["id"] = f"{idx + 1:08d}"
        record["file_name"] = file_name
        record["file_path"] = file_path
        record["extension"] = str(row_dict.get("extension", ""))
        raw_size = row_dict.get("size_bytes", 0)
        try:
            record["size_bytes"] = int(raw_size)
        except (ValueError, TypeError):
            record["size_bytes"] = 0
        record["size_human"] = str(row_dict.get("size_human", ""))
        record["modified_time"] = str(row_dict.get("modified_time", ""))
        record["parent_dir"] = str(row_dict.get("parent_dir", ""))
        record["doc_type"] = doc_type_cn
        record["doc_type_pinyin"] = pinyin_prefix
        record["extraction_status"] = extraction_status
        record["extracted_info"] = extracted_info
        record["review_note"] = review_note
        record["timestamp"] = now_str

        processed_records.append(record)

        if (idx + 1) % 10 == 0:
            print(f"  宸插鐞?{idx + 1}/{len(data)} 鏉?(OCR鎴愬姛: {ocr_success_count}, 澶辫触: {ocr_fail_count})")

    print(f"鏁版嵁鍔犲伐瀹屾垚: {len(processed_records)} 鏉?)
    print(f"  OCR鎴愬姛: {ocr_success_count}, OCR澶辫触: {ocr_fail_count}")

    # 缁熻鍑瘉绫诲瀷鍒嗗竷
    type_dist: Dict[str, int] = {}
    for r in processed_records:
        t = r["doc_type"]
        type_dist[t] = type_dist.get(t, 0) + 1
    print(f"  鍑瘉绫诲瀷鍒嗗竷: {type_dist}")

    # ---- 5. 妫€鏌ョ洰鏍囪〃鏄惁瀛樺湪锛岃嚜鍔ㄨ皟鏁村啓鍏ョ瓥鐣?----
    log("info", f"妫€鏌ョ洰鏍囪〃鏄惁瀛樺湪: {target_table_name}")
    table_exists = False
    try:
        schema_result = get_table_schema(target_ds, target_table_name)
        if isinstance(schema_result, dict) and schema_result.get("columns"):
            table_exists = True
    except Exception:
        table_exists = False

    if not table_exists:
        log("warn", f"鐩爣琛?{target_table_name} 涓嶅瓨鍦紝鍐欏叆绛栫暐浠?'{if_table_exists}' 鍒囨崲涓?'fail'锛堣嚜鍔ㄥ缓琛級")
        if_table_exists = "fail"
    else:
        print(f"  鐩爣琛ㄥ凡瀛樺湪, 鍐欏叆绛栫暐: {if_table_exists}")

    # ---- 6. 鍐欏叆鐩爣琛?----
    log("info", f"鍐欏叆鐩爣琛? {target_table_name} (绛栫暐: {if_table_exists})")

    _write_records(
        processed_records, target_ds, target_table_name,
        if_table_exists, batch_size,
        table_remark=TABLE_REMARK,
        column_remarks=COLUMN_REMARKS,
    )

    log("info", f"澶勭悊瀹屾垚: 鍏?{len(processed_records)} 鏉℃暟鎹凡鍐欏叆 {target_table_name}")

    return {
        "success": True,
        "total_rows": len(processed_records),
        "target_table": target_table_name,
        "columns": list(COLUMN_REMARKS.keys()),
        "ocr_success": ocr_success_count,
        "ocr_fail": ocr_fail_count,
        "doc_type_distribution": type_dist,
        "write_method": "write_table_data",
        "sample": processed_records[:3],
    }


# ============================================================
# 涓诲叆鍙?# ============================================================
def main(**kwargs):
    """涓诲叆鍙ｏ紝绯荤粺娉ㄥ叆鐢ㄦ埛鍙傛暟銆?""
    # 鍙傛暟鍒悕鏄犲皠
    param_aliases = {
        'source_datasource_name': ['source_datasource_name', 'source_datasource', 'datasource'],
        'source_table_name': ['source_table_name', 'source_table', 'table_name'],
        'target_datasource_name': ['target_datasource_name', 'target_datasource'],
        'target_table_name': ['target_table_name', 'target_table'],
        'image_column': ['image_column', 'image_path_column'],
        'doc_type': ['doc_type'],
        'if_table_exists': ['if_table_exists', 'write_strategy'],
        'batch_size': ['batch_size'],
        'enable_vectorization': ['enable_vectorization'],
        'vector_datasource_name': ['vector_datasource_name'],
        'vector_table_name': ['vector_table_name'],
        'enable_translation': ['enable_translation'],
        'translation_target_lang': ['translation_target_lang'],
    }
    
    resolved = {}
    for canonical, aliases in param_aliases.items():
        for alias in aliases:
            if alias in kwargs:
                resolved[canonical] = kwargs[alias]
                break
    
    # 榛樿鍊?    resolved.setdefault('source_datasource_name', '鍑瘉搴?)
    resolved.setdefault('source_table_name', '鎵€鏈夌殑鍥剧墖')
    resolved.setdefault('target_datasource_name', '鍑瘉妫€绱㈠簱')
    resolved.setdefault('target_table_name', '鍏抽敭淇℃伅')
    resolved.setdefault('image_column', 'file_path')
    resolved.setdefault('doc_type', 'auto')
    resolved.setdefault('if_table_exists', 'truncate')
    resolved.setdefault('batch_size', 500)
    resolved.setdefault('enable_vectorization', False)
    resolved.setdefault('vector_datasource_name', '')
    resolved.setdefault('vector_table_name', '')
    resolved.setdefault('enable_translation', False)
    resolved.setdefault('translation_target_lang', '')
    
    return extract_image_info(**resolved)


def _probe_ocr_functions():
    """鎺㈡祴娌欑涓彲鐢ㄧ殑OCR/瑙嗚鐩稿叧鍑芥暟"""
    import builtins
    # 鍒楀嚭鎵€鏈夊唴缃叏灞€鍚嶇О
    all_names = dir(builtins)
    # 涔熸鏌ュ叏灞€鍛藉悕绌洪棿
    try:
        g = globals()
        all_names = list(set(all_names + list(g.keys())))
    except:
        pass
    
    ocr_related = []
    for name in sorted(all_names):
        name_lower = name.lower()
        if any(kw in name_lower for kw in ['ocr', 'vision', 'image', 'recognize', 'read', 'llm', 'chat', 'extract']):
            ocr_related.append(name)
    
    print("OCR/瑙嗚鐩稿叧鍑芥暟:", ocr_related)
    print("\n鎵€鏈夐潪涓嬪垝绾垮紑澶寸殑鍏ㄥ眬鍚嶇О:")
    for name in sorted(all_names):
        if not name.startswith('_'):
            print(f"  {name}")
    return {"ocr_related": ocr_related}

_probe_ocr_functions()
