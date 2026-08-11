import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 常见凭证拼音→中文映射表
# ============================================================
PINYIN_DOC_MAP = {
    "yingyezhizhao": "营业执照",
    "shenfenzheng": "身份证",
    "shenfenzhengzhengmian": "身份证（正面）",
    "shenfenzhengbeimian": "身份证（背面）",
    "danweicunkuanzhengmingshenqingshu": "单位存款证明申请书",
    "gerensuodeshuiwanshuipingzheng": "个人所得税完税凭证",
    "kaihuxukezheng": "开户许可证",
    "zuzhijigoudaimazheng": "组织机构代码证",
    "shuiwudengjizheng": "税务登记证",
    "gongshangdengjizheng": "工商登记证",
    "yinhangliushui": "银行流水",
    "cunkuanzhengming": "存款证明",
    "zizhizhengshu": "资质证书",
    "hetong": "合同",
    "fapiao": "发票",
    "baodan": "保单",
    "xukezheng": "许可证",
    "zhixingzheng": "执行证",
    "chuchanghegezheng": "出厂合格证",
    "jiancebaogao": "检测报告",
    "zhiliangrenzhengzhengshu": "质量认证证书",
    "anquanxukezheng": "安全许可证",
    "yingyezhizhaofuben": "营业执照（副本）",
    "yingyezhizhaozhengben": "营业执照（正本）",
}

# ============================================================
# 列定义（英文列名 + 中文备注）
# ============================================================
COLUMN_REMARKS = {
    "id": "唯一标识，8位数字零补齐",
    "file_name": "文件名称",
    "file_path": "文件路径",
    "extension": "文件扩展名",
    "size_bytes": "文件大小（字节）",
    "size_human": "文件大小（可读格式）",
    "modified_time": "文件修改时间",
    "parent_dir": "文件所在目录",
    "doc_type": "凭证类型（从文件名提取）",
    "doc_type_pinyin": "凭证类型拼音",
    "extraction_status": "提取状态",
    "extracted_info": "OCR提取的关键信息（JSON格式）",
    "review_note": "审核备注",
    "timestamp": "数据导入时间戳",
}

TABLE_REMARK = "凭证图片关键信息提取结果"


# ============================================================
# 从文件名提取拼音前缀
# ============================================================
def extract_pinyin_prefix(file_name: str) -> str:
    """从文件名中提取拼音前缀（UUID之前的部分）。

    Args:
        file_name: 文件名，如 danweicunkuanzhengmingshenqingshu_50fc3589-xxx.jpg

    Returns:
        拼音前缀，如 danweicunkuanzhengmingshenqingshu
    """
    if not file_name:
        return ""
    # 去掉扩展名
    base = re.sub(r'\.[^.]+$', '', file_name)
    # 按 UUID 模式分割（8-4-4-4-12 格式）
    parts = re.split(r'_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', base)
    prefix = parts[0].strip('_') if parts else base
    return prefix


# ============================================================
# 批量翻译未知拼音前缀
# ============================================================
def batch_translate_pinyin(unknown_pinyins: List[str]) -> Dict[str, str]:
    """使用 LLM 批量翻译未知拼音前缀为中文，含1次重试。

    Args:
        unknown_pinyins: 未在映射表中找到的拼音前缀列表。

    Returns:
        拼音→中文的映射字典。
    """
    if not unknown_pinyins:
        return {}

    result_map: Dict[str, str] = {}
    # 每次处理最多 10 个
    for i in range(0, len(unknown_pinyins), 10):
        batch = unknown_pinyins[i:i + 10]
        pinyin_list = "\n".join(f"{idx+1}. {p}" for idx, p in enumerate(batch))
        prompt = f"""以下是中国凭证/证件文件名的拼音前缀，请将每个拼音翻译为对应的中文证件名称。
只返回翻译结果，每行一个，格式为：拼音=中文
不要有多余解释。

{pinyin_list}"""

        # 最多重试 2 次（初次 + 1 次重试）
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
                break  # 成功则跳出重试循环
            except Exception as e:
                log("warn", f"LLM翻译拼音失败 (尝试 {attempt+1}/2): {e}")
                if attempt == 0:
                    log("info", "重试中...")

    return result_map


# ============================================================
# 分批写入
# ============================================================
def _write_records(records: List[Dict[str, Any]], target_ds: str, table_name: str,
                   if_table_exists: str, batch_size: int = 500,
                   table_remark: str = "", column_remarks: Optional[Dict[str, str]] = None) -> None:
    """分批写入记录到目标表。

    第一批使用原始写入策略，后续批次自动切换为 append。
    仅使用 records 参数写入，不使用 DataFrame 方式。

    Args:
        records: 待写入的记录列表。
        target_ds: 目标数据源 ID。
        table_name: 目标表名。
        if_table_exists: 写入策略。
        batch_size: 每批大小。
        table_remark: 表备注。
        column_remarks: 列备注字典。

    Raises:
        RuntimeError: 当 write_table_data 返回失败或抛出异常时。
    """
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
            print(f"  [DEBUG] write_table_data 返回: {write_result}")
        except Exception as we:
            raise RuntimeError(f"write_table_data 异常 (批次 {batch_num}): {we}")

        if isinstance(write_result, dict) and not write_result.get("success", True):
            err_msg = write_result.get("error", write_result.get("message", str(write_result)))
            # 如果 fail 策略因表已存在失败，自动重试 truncate
            err_str = str(err_msg)
            if current_strategy == "fail" and any(kw in err_str for kw in ["已存在", "already exists", "exists", "表已存在", "table"]):
                log("warn", f"表已存在，fail 策略失败，自动切换为 replace 重试...")
                try:
                    write_result = write_table_data(
                        target_ds, table_name,
                        records=batch,
                        if_table_exists="replace",
                        table_remark=table_remark,
                        column_remarks=column_remarks,
                    )
                    print(f"  [DEBUG] truncate 重试返回: {write_result}")
                except Exception as we2:
                    raise RuntimeError(f"truncate 重试也失败 (批次 {batch_num}): {we2}")
                if isinstance(write_result, dict) and not write_result.get("success", True):
                    raise RuntimeError(f"truncate 重试返回失败 (批次 {batch_num}): {write_result}")
            else:
                raise RuntimeError(f"write_table_data 返回失败 (批次 {batch_num}): {err_msg}")

        written = min(i + batch_size, total)
        print(f"  已写入第 {batch_num} 批: {len(batch)} 条 (累计 {written}/{total})")


# ============================================================
# 核心业务函数
# ============================================================
def extract_image_info(
    source_datasource_name: str = "",
    source_table_name: str = "",
    target_datasource_name: str = "",
    target_table_name: str = "",
    image_column: str = "file_path",
    doc_type: str = "auto",
    if_table_exists: str = "replace",
    batch_size: int = 500,
    enable_vectorization: bool = False,
    vector_datasource_name: str = "",
    vector_table_name: str = "",
    enable_translation: bool = False,
    translation_target_lang: str = "",
    **kwargs,
) -> Dict[str, Any]:
    # 处理平台可能传入的别名参数
    if not source_datasource_name and kwargs.get("datasource"):
        source_datasource_name = kwargs["datasource"]
    if not source_table_name and kwargs.get("table_name"):
        source_table_name = kwargs["table_name"]
    if not source_datasource_name and kwargs.get("source_datasource"):
        source_datasource_name = kwargs["source_datasource"]
    if not source_table_name and kwargs.get("source_table"):
        source_table_name = kwargs["source_table"]
    if not target_datasource_name and kwargs.get("target_datasource"):
        target_datasource_name = kwargs["target_datasource"]
    if not target_table_name or target_table_name == "*":
        if kwargs.get("target_table") and kwargs["target_table"] != "*":
            target_table_name = kwargs["target_table"]

    # 兜底默认值（防止 main() 未被调用时参数为空，* 表示自动生成）
    if not source_datasource_name or source_datasource_name == "*":
        source_datasource_name = "凭证库"
    if not source_table_name or source_table_name == "*":
        source_table_name = "所有的图片"
    if not target_datasource_name or target_datasource_name == "*":
        target_datasource_name = "凭证检索库"
    # 目标表名自动生成：根据处理时间生成唯一表名，避免与源表同名
    if not target_table_name or target_table_name == "*":
        target_table_name = "credential_ocr_results_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    # 安全检查：目标表名不能与源表名相同（即使源表名是通配符或自动值也要避免冲突）
    if target_table_name == source_table_name:
        target_table_name = "credential_ocr_results_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    if not image_column or image_column == "*":
        image_column = "file_path"
    """从凭证库读取图片文件列表，使用OCR提取关键信息，写入凭证检索库。

    从文件名中提取凭证类型（拼音→中文），使用 llm_vision 对每张图片进行OCR识别，
    提取关键信息。写入目标表时自动生成英文列名和中文备注，
    添加 ID（8位零补齐）和时间戳列。

    Args:
        source_datasource_name: 源数据源名称。
        source_table_name: 源表名。
        target_datasource_name: 目标数据源名称。
        target_table_name: 目标表名。
        image_column: 图片路径列名。
        doc_type: 文档类型（auto/id_card/business_license）。
        if_table_exists: 写入策略。
        batch_size: 分批写入批次大小。
        enable_vectorization: 是否启用图片向量化。
        vector_datasource_name: 向量库数据源名称。
        vector_table_name: 向量库表名。
        enable_translation: 是否启用翻译。
        translation_target_lang: 翻译目标语言。

    Returns:
        包含 success、total_rows、columns 等字段的字典。
    """
    # ---- 1. 获取数据源 ID ----
    log("info", f"获取源数据源 ID: {source_datasource_name}")
    source_ds = get_datasource_id_by_name(source_datasource_name)
    if not source_ds:
        return {"success": False, "error": f"找不到源数据源: {source_datasource_name}", "message": "数据源名称校验失败"}

    log("info", f"获取目标数据源 ID: {target_datasource_name}")
    target_ds = get_datasource_id_by_name(target_datasource_name)
    if not target_ds:
        return {"success": False, "error": f"找不到目标数据源: {target_datasource_name}", "message": "数据源名称校验失败"}

    # ---- 2. 读取源数据（分块读取避免超时）----
    log("info", f"读取源表数据: {source_table_name}")
    data = []
    source_columns = []
    try:
        for chunk in iter_table_data(source_ds, source_table_name, chunk_size=2000):
            chunk_rows = chunk.get("rows", chunk.get("data", []))
            if not source_columns:
                source_columns = chunk.get("columns", [])
            data.extend(chunk_rows)
            print(f"  已读取 {len(data)} 条...")
        if not source_columns and data:
            if isinstance(data[0], dict):
                source_columns = list(data[0].keys())
    except Exception as e:
        log("warn", f"分块读取失败，尝试单次小批量读取: {e}")
        result = query_table_data(source_ds, source_table_name, limit=2000)
        if not isinstance(result, dict) or not result.get("success"):
            return {"success": False, "error": f"读取源表失败: {result}", "message": "数据读取异常"}
        data = result.get("data", [])
        source_columns = result.get("columns", [])

    if not data:
        return {"success": False, "error": "源表无数据", "message": f"源表 {source_table_name} 返回空数据"}

    print(f"源数据读取成功: {len(data)} 条, 列: {source_columns}")

    # ---- 2.5 动态解析列名（适配不同数据源结构）----
    df_source = pd.DataFrame(data, columns=source_columns) if source_columns else pd.DataFrame(data)

    def _resolve_col(candidates):
        """尝试多个候选列名，返回第一个匹配的实际列名"""
        for c in candidates:
            if not c or c == "*":
                continue
            col = resolve_column(df_source, c)
            if col:
                return col
        return None

    # 图片路径列（最关键，必须找到）
    img_candidates = [image_column, "file_path", "图片", "image", "path", "路径", "照片",
                      "文件路径", "image_path", "img", "图片路径", "文件", "picture", "photo",
                      "图片链接", "url", "图片地址"]
    resolved_image_col = _resolve_col(img_candidates)

    if not resolved_image_col:
        return {"success": False, "error": f"在源表列 {source_columns} 中找不到图片路径列",
                "message": "无法确定图片路径列，请通过 image_column 参数指定包含图片路径的列名"}

    log("info", f"图片路径列解析为: {resolved_image_col}")

    # 文件名列（可选，找不到则从路径推导）
    resolved_name_col = _resolve_col(["file_name", "文件名", "filename", "名称", "name", "title"])
    if resolved_name_col:
        log("info", f"文件名列解析为: {resolved_name_col}")
    else:
        log("info", "文件名列未找到，将从图片路径推导")

    # 其他元数据列（可选）
    resolved_ext_col = _resolve_col(["extension", "扩展名", "ext", "格式"])
    resolved_size_col = _resolve_col(["size_bytes", "文件大小", "size", "大小", "字节"])
    resolved_size_human_col = _resolve_col(["size_human", "文件大小可读", "大小可读"])
    resolved_mtime_col = _resolve_col(["modified_time", "修改时间", "mtime", "更新时间"])
    resolved_dir_col = _resolve_col(["parent_dir", "目录", "dir", "所在目录"])

    # ---- 3. 提取所有拼音前缀，批量翻译未知类型 ----
    log("info", "从文件名提取凭证类型...")
    all_pinyins = set()
    for row in data:
        if isinstance(row, (list, tuple)):
            row_dict = dict(zip(source_columns, row))
        elif isinstance(row, dict):
            row_dict = dict(row)
        else:
            row_dict = {}
        file_name = str(row_dict.get(resolved_name_col, "")) if resolved_name_col else ""
        prefix = extract_pinyin_prefix(file_name)
        if prefix:
            all_pinyins.add(prefix)

    # 额外的英文/拼音前缀映射（LLM可能翻译失败）
    EXTRA_PREFIX_MAP = {
        "institution_basic_information_reporting_form": "机构基本信息报告表",
        "yiditongyezhanghukailitongzhishu": "异地通银行账户开立通知书",
        "yinjianka": "银监卡",
    }

    # 区分已知和未知
    unknown_pinyins = [p for p in all_pinyins if p not in PINYIN_DOC_MAP and p not in EXTRA_PREFIX_MAP]
    known_count = len(all_pinyins) - len(unknown_pinyins)
    print(f"  凭证类型: 已知 {known_count} 种, 未知 {len(unknown_pinyins)} 种")

    # 合并映射表
    full_map = dict(PINYIN_DOC_MAP)
    full_map.update(EXTRA_PREFIX_MAP)
    if unknown_pinyins:
        log("info", f"使用 LLM 翻译 {len(unknown_pinyins)} 个未知拼音前缀...")
        translated = batch_translate_pinyin(unknown_pinyins)
        full_map.update(translated)
        print(f"  LLM 翻译完成: 成功 {len(translated)} 个")

    # ---- 4. 数据加工 + OCR提取关键信息（并发处理）----
    log("info", "开始数据加工: 生成ID、时间戳、凭证类型、OCR提取关键信息...")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    processed_records: List[Dict[str, Any]] = []
    ocr_success_count = 0
    ocr_fail_count = 0
    platform_warnings = []  # 收集平台错误（LLM/OCR服务异常等），供 RunTime 感知

    # 预处理：解析所有行，构建任务列表
    tasks = []  # (idx, file_path, doc_type_cn, row_dict, file_name, pinyin_prefix)
    for idx, row in enumerate(data):
        if isinstance(row, (list, tuple)):
            row_dict = dict(zip(source_columns, row))
        elif isinstance(row, dict):
            row_dict = dict(row)
        else:
            row_dict = {}
        file_name = str(row_dict.get(resolved_name_col, "")) if resolved_name_col else ""
        file_path = str(row_dict.get(resolved_image_col, ""))
        if not file_name and file_path:
            file_name = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if "/" in file_path or "\\" in file_path else file_path
        pinyin_prefix = extract_pinyin_prefix(file_name)
        doc_type_cn = full_map.get(pinyin_prefix, pinyin_prefix if pinyin_prefix else "未知凭证类型")
        tasks.append((idx, file_path, doc_type_cn, row_dict, file_name, pinyin_prefix))

    print(f"  预处理完成，共 {len(tasks)} 条记录，开始并发OCR提取...")

    # 并发OCR处理函数
    def _ocr_task(idx, file_path, doc_type_cn, row_dict, file_name, pinyin_prefix):
        extracted_info = ""
        extraction_status = "已提取"
        review_note = ""
        try:
            if not file_path or file_path == "None":
                raise ValueError("图片路径为空，无法进行OCR")
            ocr_prompt = f"提取这张{doc_type_cn}图片中的所有文字信息，以JSON格式返回。"
            ocr_result = llm_vision(file_path, ocr_prompt, max_tokens=1000)
            extracted_info = str(ocr_result).strip() if ocr_result else ""
            if extracted_info:
                extraction_status = "已提取"
            else:
                extraction_status = "提取失败"
                review_note = "OCR返回空结果"
        except Exception as e:
            extraction_status = "提取失败"
            err_str = str(e)
            if "Error code:" in err_str or "content.type" in err_str:
                code_match = re.search(r"code['\"]:\s*['\"](\d+)['\"]", err_str)
                error_code = code_match.group(1) if code_match else "未知"
                review_note = f"OCR服务调用异常（错误码: {error_code}）"
                platform_warnings.append(f"llm_vision 调用失败（错误码: {error_code}）: {err_str[:200]}")
            else:
                review_note = f"OCR异常: {err_str[:100]}"
                platform_warnings.append(f"llm_vision 调用异常: {err_str[:200]}")
            extracted_info = ""

        # PII脱敏
        if extracted_info:
            extracted_info = _sanitize_pii(extracted_info)

        # 数据质量验证与修复
        if extracted_info:
            extracted_info, validation_note = _validate_extracted_data(extracted_info)
            if validation_note:
                review_note = (review_note + "; " + validation_note).strip("; ") if review_note else validation_note

        return idx, extracted_info, extraction_status, review_note

    # 使用线程池并发执行OCR（I/O密集型，适合ThreadPool）
    max_workers = 8
    results_map = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for task in tasks:
            idx, file_path, doc_type_cn, row_dict, file_name, pinyin_prefix = task
            fut = executor.submit(_ocr_task, idx, file_path, doc_type_cn, row_dict, file_name, pinyin_prefix)
            futures[fut] = idx

        completed = 0
        total = len(tasks)
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                idx, extracted_info, extraction_status, review_note = fut.result()
                results_map[idx] = (extracted_info, extraction_status, review_note)
            except Exception as e:
                results_map[idx] = ("", "提取失败", f"并发执行异常: {str(e)[:100]}")
            completed += 1
            if completed % 5 == 0 or completed == total:
                print(f"  OCR进度: {completed}/{total} ({completed*100//total}%)")

    # 按原始顺序构建最终记录
    for idx, file_path, doc_type_cn, row_dict, file_name, pinyin_prefix in tasks:
        extracted_info, extraction_status, review_note = results_map.get(idx, ("", "提取失败", "未找到结果"))
        if extraction_status == "已提取":
            ocr_success_count += 1
        else:
            ocr_fail_count += 1

        record: Dict[str, Any] = {}
        record["id"] = f"{idx + 1:08d}"
        record["file_name"] = _sanitize_pii(file_name)
        record["file_path"] = file_path
        record["extension"] = str(row_dict.get(resolved_ext_col, "")) if resolved_ext_col else ""
        raw_size = row_dict.get(resolved_size_col, 0) if resolved_size_col else 0
        try:
            record["size_bytes"] = int(raw_size)
        except (ValueError, TypeError):
            record["size_bytes"] = 0
        record["size_human"] = str(row_dict.get(resolved_size_human_col, "")) if resolved_size_human_col else ""
        record["modified_time"] = str(row_dict.get(resolved_mtime_col, "")) if resolved_mtime_col else ""
        record["parent_dir"] = _sanitize_pii(str(row_dict.get(resolved_dir_col, ""))) if resolved_dir_col else ""
        record["doc_type"] = _sanitize_pii(doc_type_cn)
        record["doc_type_pinyin"] = _sanitize_pii(pinyin_prefix)
        record["extraction_status"] = extraction_status
        record["extracted_info"] = extracted_info
        record["review_note"] = review_note
        record["timestamp"] = now_str
        processed_records.append(record)

    print(f"数据加工完成: {len(processed_records)} 条")
    print(f"  OCR成功: {ocr_success_count}, OCR失败: {ocr_fail_count}")

    # 统计凭证类型分布
    type_dist: Dict[str, int] = {}
    for r in processed_records:
        t = r["doc_type"]
        type_dist[t] = type_dist.get(t, 0) + 1
    print(f"  凭证类型分布: {type_dist}")

    # ---- 5. 检查目标表是否存在，自动调整写入策略 ----
    log("info", f"检查目标表是否存在: {target_table_name}")
    table_exists = False
    try:
        schema_result = get_table_schema(target_ds, target_table_name)
        # get_table_schema 可能返回 list 或 dict
        if isinstance(schema_result, list) and len(schema_result) > 0:
            table_exists = True
        elif isinstance(schema_result, dict) and schema_result.get("columns"):
            table_exists = True
    except Exception:
        table_exists = False

    if not table_exists:
        log("warn", f"目标表 {target_table_name} 不存在，写入策略从 '{if_table_exists}' 切换为 'fail'（自动建表）")
        if_table_exists = "fail"
    else:
        print(f"  目标表已存在, 写入策略: {if_table_exists}")

    # ---- 6. 写入目标表 ----
    log("info", f"写入目标表: {target_table_name} (策略: {if_table_exists})")

    _write_records(
        processed_records, target_ds, target_table_name,
        if_table_exists, batch_size,
        table_remark=TABLE_REMARK,
        column_remarks=COLUMN_REMARKS,
    )

    log("info", f"处理完成: 共 {len(processed_records)} 条数据已写入 {target_table_name}")

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
        "warnings": platform_warnings if platform_warnings else None,
    }


# ============================================================
# 主入口
# ============================================================
def main(**kwargs):
    """主入口，系统注入用户参数。"""
    # 参数别名映射
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
    
    # 默认值（空字符串也视为缺失，使用默认值；* 表示自动生成）
    defaults = {
        'source_datasource_name': '凭证库',
        'source_table_name': '所有的图片',
        'target_datasource_name': '凭证检索库',
        'target_table_name': 'credential_ocr_results_' + datetime.now().strftime("%Y%m%d_%H%M%S"),
        'image_column': 'file_path',
        'doc_type': 'auto',
        'if_table_exists': 'replace',
        'batch_size': 500,
        'enable_vectorization': False,
        'vector_datasource_name': '',
        'vector_table_name': '',
        'enable_translation': False,
        'translation_target_lang': '',
    }
    for key, val in defaults.items():
        if key not in resolved or resolved[key] is None or resolved[key] == '' or resolved[key] == '*':
            resolved[key] = val

    # 安全检查：目标表名不能与源表名相同
    if resolved.get('target_table_name') == resolved.get('source_table_name'):
        resolved['target_table_name'] = 'credential_ocr_results_' + datetime.now().strftime("%Y%m%d_%H%M%S")

    return extract_image_info(**resolved)


def _probe_ocr_functions():
    """探测沙箱中可用的OCR/视觉相关函数"""
    import builtins
    # 列出所有内置全局名称
    all_names = dir(builtins)
    # 也检查全局命名空间
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
    
    print("OCR/视觉相关函数:", ocr_related)
    print("\n所有非下划线开头的全局名称:")
    for name in sorted(all_names):
        if not name.startswith('_'):
            print(f"  {name}")
    return {"ocr_related": ocr_related}

_probe_ocr_functions()


def _sanitize_pii(text: str) -> str:
    """对文本中的PII信息进行脱敏处理。

    - 手机号: 保留前3后4，中间用**** (如 138****0081)
    - UUID: 将UUID中的数字替换为*，保留字母部分
    - 银行卡号/账号(13位及以上连续数字): 仅保留后4位，前面用*号
    - 带分隔符的银行卡号(如 1234-5678-9012-3456): 脱敏为 ****-****-****-3456
    - 邮箱: 保留首字符与域名 (如 x***@qq.com)
    """
    if not text:
        return text
    text = str(text)

    # 1. 手机号脱敏: 1[3-9]开头共11位数字
    text = re.sub(r'1[3-9]\d{9}', lambda m: m.group()[:3] + '****' + m.group()[-4:], text)

    # 2. UUID脱敏: 将UUID中的数字部分替换为*，保留字母部分
    #    UUID格式: 8-4-4-4-12 hex字符，如 50fc3589-1234-5678-9abc-def012345678
    def _mask_uuid_digits(m):
        return re.sub(r'\d', '*', m.group())
    text = re.sub(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        _mask_uuid_digits, text
    )

    # 3. 带分隔符的银行卡号脱敏: 4-4-4-4 或 4-4-4-4-4 格式 (如 1234-5678-9012-3456 或 1234 5678 9012 3456)
    def _mask_separated_number(m):
        digits = re.sub(r'[-\s]', '', m.group())
        return '****-****-****-' + digits[-4:]
    text = re.sub(r'\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}([-\s]\d{1,4})?', _mask_separated_number, text)

    # 4. 银行卡号/长数字序列脱敏: 13位及以上连续数字，仅保留后4位
    #    使用 (?<!\d) 和 (?!\d) 替代 \b，以正确处理下划线等非空白分隔符
    def _mask_long_number(m):
        num = m.group()
        if len(num) <= 4:
            return num
        return '*' * (len(num) - 4) + num[-4:]
    text = re.sub(r'(?<!\d)\d{13,}(?!\d)', _mask_long_number, text)

    # 5. 邮箱脱敏: 保留首字符与域名
    def _mask_email(m):
        email = m.group()
        at_idx = email.index('@')
        return email[0] + '***' + email[at_idx:]
    text = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', _mask_email, text)

    return text


def _validate_extracted_data(extracted_info: str) -> tuple:
    """验证并修复提取数据的质量问题。

    返回 (修复后的extracted_info, 审核备注字符串)。

    检查项:
    - 统一社会信用代码格式合规性 (标准: 2位登记码+6位行政区划码+10位主体标识码)
    - 日期范围一致性（开始日期不晚于截止日期）

    修复策略:
    - 日期颠倒: 自动交换开始/截止日期值，在JSON中添加_dq_flags标记
    - USCC格式不合规: 在JSON中添加_dq_flags标记为待人工复核
    """
    notes = []
    if not extracted_info:
        return extracted_info, ""

    # 尝试解析JSON
    info_dict = None
    json_match = None
    try:
        json_match = re.search(r'\{.*\}', extracted_info, re.DOTALL)
        if json_match:
            info_dict = json.loads(json_match.group())
    except (json.JSONDecodeError, ValueError):
        info_dict = None

    dq_flags = []

    # 1. 验证统一社会信用代码格式
    uscc_pattern = re.compile(r'^[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}$')
    uscc_candidates = re.findall(r'[A-Z0-9]{18}', extracted_info)
    for uscc in uscc_candidates:
        if not uscc_pattern.match(uscc):
            notes.append(
                f"统一社会信用代码 {uscc} 格式不合规（第3-8位应为6位数字行政区划码），疑似OCR识别异常，待人工复核"
            )
            # 在JSON中标记该字段为待人工复核
            if info_dict and isinstance(info_dict, dict):
                for key, val in info_dict.items():
                    if isinstance(val, str) and uscc in val:
                        dq_flags.append({
                            "field": key,
                            "value": uscc,
                            "issue": "格式不合规（第3-8位应为6位数字行政区划码），疑似OCR识别异常",
                            "status": "pending_review"
                        })
                        break

    # 2. 验证日期范围一致性
    if info_dict and isinstance(info_dict, dict):
        date_fields = {}  # key -> (normalized_date, original_value)
        for key, val in info_dict.items():
            if isinstance(val, str):
                # 匹配 YYYY年MM月DD日 格式
                m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', val)
                if m:
                    date_fields[key] = (f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", val)
                    continue
                # 匹配 YYYY-MM-DD 格式
                m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', val)
                if m:
                    date_fields[key] = (f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", val)
                    continue
                # 匹配 YYYY/MM/DD 格式
                m = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', val)
                if m:
                    date_fields[key] = (f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", val)

        # 查找开始/截止日期对
        start_keywords = ['开始', '起始', 'start', 'from', '签发', '发证']
        end_keywords = ['截止', '到期', 'end', 'until', '结束', '失效']

        start_keys = [k for k in date_fields if any(w in k.lower() for w in start_keywords)]
        end_keys = [k for k in date_fields if any(w in k.lower() for w in end_keywords)]

        for sk in start_keys:
            for ek in end_keys:
                if date_fields[sk][0] > date_fields[ek][0]:
                    # 自动交换日期值（OCR识别颠倒）
                    info_dict[sk], info_dict[ek] = info_dict[ek], info_dict[sk]
                    notes.append(
                        f"日期范围异常: {sk}({date_fields[sk][0]})晚于{ek}({date_fields[ek][0]})，已自动交换日期，待人工复核确认"
                    )
                    dq_flags.append({
                        "field": f"{sk}/{ek}",
                        "issue": f"开始日期({date_fields[sk][0]})晚于截止日期({date_fields[ek][0]})，已自动交换",
                        "status": "auto_corrected"
                    })

    # 如果有数据质量标记，更新JSON
    if dq_flags and info_dict and isinstance(info_dict, dict):
        info_dict["_dq_flags"] = dq_flags
        fixed_json = json.dumps(info_dict, ensure_ascii=False)
        if json_match:
            extracted_info = extracted_info[:json_match.start()] + fixed_json + extracted_info[json_match.end():]
        else:
            extracted_info = fixed_json

    return extracted_info, "; ".join(notes) if notes else ""