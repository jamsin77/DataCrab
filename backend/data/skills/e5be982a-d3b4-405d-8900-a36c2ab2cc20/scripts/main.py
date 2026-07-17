import re
from datetime import datetime
from typing import Dict, Any, List, Optional

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
            if current_strategy == "fail" and "已存在" in str(err_msg):
                log("warn", f"表已存在，fail 策略失败，自动切换为 truncate 重试...")
                try:
                    write_result = write_table_data(
                        target_ds, table_name,
                        records=batch,
                        if_table_exists="truncate",
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
    source_datasource_name: str,
    source_table_name: str,
    target_datasource_name: str,
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
) -> Dict[str, Any]:
    """从凭证库读取图片文件列表，提取关键信息，写入凭证检索库。

    从文件名中提取凭证类型（拼音→中文），因沙箱 llm_chat 不支持多模态图片输入，
    所有记录标记为"待人工审核"。写入目标表时自动生成英文列名和中文备注，
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

    # ---- 2. 读取源数据 ----
    log("info", f"读取源表数据: {source_table_name}")
    result = query_table_data(source_ds, source_table_name, limit=10000)
    if not isinstance(result, dict) or not result.get("success"):
        return {"success": False, "error": f"读取源表失败: {result}", "message": "数据读取异常"}

    data = result.get("data", [])
    source_columns = result.get("columns", [])

    if not data:
        return {"success": False, "error": "源表无数据", "message": f"源表 {source_table_name} 返回空数据"}

    print(f"源数据读取成功: {len(data)} 条, 列: {source_columns}")

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
        file_name = str(row_dict.get("file_name", ""))
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

    # ---- 4. 数据加工 ----
    log("info", "开始数据加工: 生成ID、时间戳、凭证类型...")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    processed_records: List[Dict[str, Any]] = []
    pending_review_count = 0

    for idx, row in enumerate(data):
        if isinstance(row, (list, tuple)):
            row_dict = dict(zip(source_columns, row))
        elif isinstance(row, dict):
            row_dict = dict(row)
        else:
            row_dict = {}

        file_name = str(row_dict.get("file_name", ""))
        pinyin_prefix = extract_pinyin_prefix(file_name)
        doc_type_cn = full_map.get(pinyin_prefix, pinyin_prefix if pinyin_prefix else "未知凭证类型")

        # 构建新记录
        record: Dict[str, Any] = {}
        record["id"] = f"{idx + 1:08d}"
        record["file_name"] = file_name
        record["file_path"] = str(row_dict.get("file_path", ""))
        record["extension"] = str(row_dict.get("extension", ""))
        record["size_bytes"] = row_dict.get("size_bytes", 0)
        record["size_human"] = str(row_dict.get("size_human", ""))
        record["modified_time"] = str(row_dict.get("modified_time", ""))
        record["parent_dir"] = str(row_dict.get("parent_dir", ""))
        record["doc_type"] = doc_type_cn
        record["doc_type_pinyin"] = pinyin_prefix
        record["extraction_status"] = "待人工审核"
        record["review_note"] = "沙箱环境不支持图片OCR，需人工查看图片提取关键信息"
        record["timestamp"] = now_str

        processed_records.append(record)
        pending_review_count += 1

    print(f"数据加工完成: {len(processed_records)} 条")
    print(f"  待人工审核: {pending_review_count} 条")

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
        if isinstance(schema_result, dict) and schema_result.get("columns"):
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
        "pending_review": pending_review_count,
        "doc_type_distribution": type_dist,
        "write_method": "write_table_data",
        "sample": processed_records[:3],
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
    
    # 默认值
    resolved.setdefault('source_datasource_name', '凭证库')
    resolved.setdefault('source_table_name', '所有的图片')
    resolved.setdefault('target_datasource_name', '凭证检索库')
    resolved.setdefault('target_table_name', '关键信息')
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