"""
元数据同步与AI增强技能
功能：跨多个数据源收集表元数据，使用AI增强描述/标签/分类，检测跨数据源关系并写入元数据注册表
"""
from datetime import datetime
from typing import Dict, Any, List, Optional


# ============================================================================
# 默认数据源配置（用户实际数据源和表名）
# ============================================================================
DEFAULT_DATASOURCE_CONFIGS = {
    "文物列表": {
        "type": "excel",
        "tables": [
            "national_key_cultural_relic_protection_units",
            "national_key_cultural_relic_protection_units_merged",
            "split_result",
            "split_result_第七批",
            "split_result_第三批",
            "split_result_第二批",
            "split_result_第五批",
            "split_result_第五批增补",
            "split_result_第六批",
            "split_result_第四批",
            "全国文物",
            "全国重点文物",
            "全国重点文物保护单位",
            "全国重点文物保护单位合并表",
            "全国重点文物保护单位名单",
            "全国重点文物保护单位（合并）",
        ],
    },
    "文物库": {
        "type": "postgresql",
        "tables": [
            "relic",
            "national_key_relic",
            "national_key_cultural_relic_protection_units_merged",
            "national_relic",
            "national_key_cultural_relic_protection_units",
        ],
    },
    "交易数据": {
        "type": "excel",
        "tables": [
            "三一报价_FOB报价单_加价10%",
            "三一报价_对比表",
            "三一报价_对比表_三一vs中联对比",
            "三一报价_询价单_上浮2%",
            "中联重科价格差异对比表",
            "中联重科价格差异对比表_人民币价格对比",
            "中联重科报价_FOB及价格差异对比",
            "中联重科报价_FOB及价格差异对比_中联价格对比表",
            "中联重科报价单_FOB美元",
            "中联重科报价单_美元转换",
            "印尼工程机械采购报价表_2026",
            "印尼工程机械采购报价表_2026_履带吊报价明细",
            "印尼工程机械采购报价表_2026_汽车吊报价明细",
            "印尼工程机械采购报价表_2026_伸缩臂履带吊报价明细",
            "印尼工程机械采购报价表_2026_平板车&配套车辆报价明细",
            "印尼工程机械采购报价表_2026_税费计算说明",
            "印尼工程机械采购询价单",
            "印尼工程机械采购询价单_已填报",
            "印尼工程机械采购询价单（三一）",
        ],
    },
    "凭证库": {
        "type": "generic_file",
        "tables": ["file_list"],
    },
    "凭证检索库": {
        "type": "postgresql",
        "tables": [
            "关键信息",
            "credential_ocr_results_20260730_150051",
            "credential_ocr_results_20260729_141025",
            "credential_ocr_results_20260730_103421",
            "credential_ocr_results_20260730_152012",
            "credential_ocr_results_20260730_160028",
            "credential_ocr_results_20260730_165350",
            "credential_ocr_results_20260730_170109",
            "credential_ocr_results_20260728_174652",
            "credential_ocr_results_20260729_141653",
            "credential_ocr_results_20260730_110553",
            "credential_ocr_results_20260730_150231",
            "credential_ocr_results_20260730_154830",
            "credential_ocr_results_20260729_094952",
            "credential_ocr_results_20260729_142923",
            "credential_ocr_results_20260730_113153",
            "credential_ocr_results_20260730_151211",
            "credential_ocr_results_20260730_154910",
            "credential_ocr_results_20260730_161148",
            "credential_ocr_results_20260730_165442",
            "credential_ocr_results_20260728_104029",
            "credential_ocr_results_20260729_114549",
            "credential_ocr_results_20260729_153338",
            "credential_ocr_results_20260730_113236",
            "credential_ocr_results_20260730_151412",
            "credential_ocr_results_20260730_155543",
            "credential_ocr_results_20260730_162012",
            "credential_ocr_results_20260730_170029",
        ],
    },
}


# ============================================================================
# 步骤1：元数据收集
# ============================================================================

def _collect_table_metadata(
    datasource_name: str,
    datasource_type: str,
    table_name: str,
    sample_size: int = 5,
) -> Optional[Dict[str, Any]]:
    """收集单个表的元数据：表结构 + 样本数据

    Args:
        datasource_name: 数据源名称
        datasource_type: 数据源类型（excel/postgresql/generic_file等）
        table_name: 表名
        sample_size: 采样行数

    Returns:
        包含表元数据的字典，失败返回 None
    """
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        log("warn", f"找不到数据源: {datasource_name}")
        return None

    # 获取表结构
    column_infos: List[Dict[str, str]] = []
    try:
        schema = get_table_schema(ds_id, table_name)
        if schema and isinstance(schema, list):
            for col in schema:
                if isinstance(col, dict):
                    col_name = (
                        col.get("name")
                        or col.get("column_name")
                        or col.get("field", "")
                    )
                    col_type = (
                        col.get("type")
                        or col.get("data_type")
                        or col.get("dtype", "")
                    )
                    column_infos.append({"name": str(col_name), "type": str(col_type)})
                elif isinstance(col, str):
                    column_infos.append({"name": col, "type": ""})
    except Exception as e:
        log("warn", f"获取表 {table_name} 结构失败: {e}")

    # 获取样本数据
    sample_data: List[Dict] = []
    columns: List[str] = []
    row_count: int = 0
    try:
        result = query_table_data(ds_id, table_name, limit=sample_size)
        if result and result.get("success"):
            sample_data = result.get("data", [])[:sample_size]
            columns = result.get("columns", [])
            row_count = result.get("row_count", 0)
        else:
            err = result.get("error", "未知错误") if result else "返回为空"
            log("warn", f"读取表 {table_name} 数据失败: {err}")
    except Exception as e:
        log("warn", f"查询表 {table_name} 异常: {e}")

    # 如果 schema 没拿到列信息，用 query 结果的 columns 补充
    if not column_infos and columns:
        column_infos = [{"name": str(c), "type": ""} for c in columns]

    return {
        "datasource_name": datasource_name,
        "datasource_type": datasource_type,
        "table_name": table_name,
        "column_count": len(column_infos),
        "row_count": row_count,
        "columns_info": json.dumps(column_infos, ensure_ascii=False),
        "sample_data": json.dumps(sample_data, ensure_ascii=False),
    }


def _collect_all_metadata(
    ds_configs: Dict[str, Dict[str, Any]],
    sample_size: int = 5,
) -> List[Dict[str, Any]]:
    """收集所有数据源所有表的元数据

    Args:
        ds_configs: 数据源配置字典 {名称: {type, tables}}
        sample_size: 每张表采样行数

    Returns:
        元数据列表，每个元素是一张表的元数据
    """
    all_metadata: List[Dict[str, Any]] = []
    total_tables = sum(len(cfg["tables"]) for cfg in ds_configs.values())
    processed = 0

    for ds_name, cfg in ds_configs.items():
        ds_type = cfg.get("type", "unknown")
        tables = cfg.get("tables", [])
        log("info", f"开始收集数据源 [{ds_name}] ({ds_type}) 的元数据，共 {len(tables)} 张表")

        for table_name in tables:
            processed += 1
            print(f"  [{processed}/{total_tables}] 收集表: {table_name}")
            meta = _collect_table_metadata(ds_name, ds_type, table_name, sample_size)
            if meta:
                all_metadata.append(meta)
            else:
                log("warn", f"跳过表: {ds_name}.{table_name}")

    log("info", f"元数据收集完成: {len(all_metadata)}/{total_tables} 张表")
    return all_metadata


# ============================================================================
# 步骤2：AI增强元数据
# ============================================================================

def _enhance_batch_with_ai(
    batch: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """用AI批量增强元数据

    Args:
        batch: 一批表的元数据列表（建议5张以内）

    Returns:
        AI增强结果列表，每个元素包含 description/column_descriptions/tags/data_category/quality_notes
    """
    # 构造表描述文本
    tables_desc = []
    for i, t in enumerate(batch):
        sample_str = t["sample_data"][:800] if len(t["sample_data"]) > 800 else t["sample_data"]
        cols_str = t["columns_info"][:500] if len(t["columns_info"]) > 500 else t["columns_info"]
        tables_desc.append(
            f"表{i+1}: {t['table_name']}\n"
            f"  数据源: {t['datasource_name']} ({t['datasource_type']})\n"
            f"  列信息: {cols_str}\n"
            f"  样本数据: {sample_str}\n"
        )

    prompt = f"""请分析以下{len(batch)}个数据表的元数据，为每个表生成增强描述信息。

{"".join(tables_desc)}

请以JSON格式返回，格式如下：
{{
  "tables": [
    {{
      "table_name": "表名（与输入一致）",
      "description": "表的中文描述，50字以内",
      "column_descriptions": {{"列名": "中文描述", ...}},
      "tags": ["标签1", "标签2"],
      "data_category": "数据分类，如：文物管理/交易报价/凭证OCR/文件管理等",
      "quality_notes": "数据质量观察，30字以内"
    }}
  ]
}}

注意：
1. 只返回JSON，不要其他文字
2. table_name 必须与输入的表名完全一致
3. column_descriptions 只包含能从样本数据推断出含义的列
4. 如果多个表结构相同（如OCR结果表），描述可以类似但 table_name 必须各自对应"""

    try:
        result = llm_chat(
            prompt,
            system_prompt="你是数据治理专家，擅长分析数据表结构、内容和业务含义。请严格按JSON格式输出。",
            temperature=0.3,
            max_tokens=4000,
        )
        # 解析JSON
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(result[start:end])
            return parsed.get("tables", [])
        else:
            log("warn", "AI返回中未找到JSON内容")
    except json.JSONDecodeError as e:
        log("warn", f"AI返回JSON解析失败: {e}")
    except Exception as e:
        log("warn", f"AI增强调用失败: {e}")

    return []


def _enhance_all_metadata(
    metadata_list: List[Dict[str, Any]],
    batch_size: int = 5,
) -> Dict[str, Dict[str, Any]]:
    """分批AI增强所有元数据

    Args:
        metadata_list: 全部表元数据列表
        batch_size: 每批处理的表数量

    Returns:
        增强结果映射: {"数据源名::表名": {description, column_descriptions, tags, ...}}
    """
    enhancements: Dict[str, Dict[str, Any]] = {}
    total = len(metadata_list)
    if total == 0:
        return enhancements

    total_batches = (total + batch_size - 1) // batch_size

    for i in range(0, total, batch_size):
        batch = metadata_list[i: i + batch_size]
        batch_num = i // batch_size + 1
        log("info", f"AI增强批次 {batch_num}/{total_batches}（{len(batch)} 张表）")

        batch_results = _enhance_batch_with_ai(batch)

        # 匹配回原始元数据
        matched = 0
        for item in batch_results:
            table_name = item.get("table_name", "")
            for meta in batch:
                if meta["table_name"] == table_name:
                    key = f"{meta['datasource_name']}::{table_name}"
                    enhancements[key] = item
                    matched += 1
                    break

        print(f"  批次 {batch_num} 完成: 增强 {matched}/{len(batch)} 张表")

    log("info", f"AI增强完成: {len(enhancements)}/{total} 张表")
    return enhancements


# ============================================================================
# 步骤3：跨数据源关系检测
# ============================================================================

def _detect_cross_source_relations(
    metadata_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """用AI检测跨数据源的表间关系

    Args:
        metadata_list: 全部表元数据列表

    Returns:
        关系列表，每个元素包含 source_datasource/source_table/target_datasource/target_table/relation_type/relation_description
    """
    if len(metadata_list) < 2:
        log("info", "表数量不足，跳过跨源关系检测")
        return []

    # 构造表清单（控制长度）
    table_lines = []
    for m in metadata_list:
        cols = json.loads(m["columns_info"]) if m["columns_info"] else []
        col_names = [c["name"] for c in cols[:10]]
        table_lines.append(
            f"- {m['datasource_name']} ({m['datasource_type']}): "
            f"{m['table_name']} [{m['column_count']}列, {m['row_count']}行] "
            f"(列: {', '.join(col_names)})"
        )

    prompt = f"""请分析以下跨数据源的表清单，识别存在关联关系的表对。

表清单（共{len(table_lines)}张表）：
{chr(10).join(table_lines)}

请识别以下类型的关系：
1. same_data: 同一数据在不同数据源中的副本（表名相同或数据内容相同）
2. complementary: 互补数据（如主表和明细表、报价单和对比表）
3. similar_structure: 结构相似（如同一批次的OCR结果表、同一模板的不同批次数据）
4. reference: 引用关系（如一个表的列引用另一个表的数据）

请以JSON格式返回：
{{
  "relations": [
    {{
      "source_datasource": "源数据源名",
      "source_table": "源表名",
      "target_datasource": "目标数据源名",
      "target_table": "目标表名",
      "relation_type": "same_data|complementary|similar_structure|reference",
      "relation_description": "关系描述（30字以内）"
    }}
  ]
}}

只返回JSON，不要其他文字。只报告确实存在关系的表对，最多返回30条。"""

    try:
        result = llm_chat(
            prompt,
            system_prompt="你是数据架构专家，擅长分析跨数据源的数据关系。请严格按JSON格式输出。",
            temperature=0.3,
            max_tokens=3000,
        )
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(result[start:end])
            relations = parsed.get("relations", [])
            log("info", f"AI检测到 {len(relations)} 条跨源关系")
            return relations
        else:
            log("warn", "跨源关系AI返回中未找到JSON")
    except json.JSONDecodeError as e:
        log("warn", f"跨源关系JSON解析失败: {e}")
    except Exception as e:
        log("warn", f"跨源关系检测失败: {e}")

    return []


# ============================================================================
# 步骤4：构建记录并写入
# ============================================================================

def _build_metadata_records(
    metadata_list: List[Dict[str, Any]],
    enhancements: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建最终元数据记录（合并原始元数据 + AI增强结果）

    Args:
        metadata_list: 原始元数据列表
        enhancements: AI增强结果映射

    Returns:
        可写入的记录列表（list[dict]）
    """
    records: List[Dict[str, Any]] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for i, m in enumerate(metadata_list):
        key = f"{m['datasource_name']}::{m['table_name']}"
        enh = enhancements.get(key, {})

        record = {
            "id": f"{i+1:06d}",
            "datasource_name": m["datasource_name"],
            "datasource_type": m["datasource_type"],
            "table_name": m["table_name"],
            "column_count": m["column_count"],
            "row_count": m["row_count"],
            "columns_info": m["columns_info"],
            "sample_data": m["sample_data"],
            "table_description": enh.get("description", ""),
            "column_descriptions": json.dumps(
                enh.get("column_descriptions", {}), ensure_ascii=False
            ),
            "tags": ", ".join(enh.get("tags", [])),
            "data_category": enh.get("data_category", ""),
            "quality_notes": enh.get("quality_notes", ""),
            "enhanced_at": now if enh else "",
        }
        records.append(record)

    return records


def _write_in_batches(
    records: List[Dict[str, Any]],
    target_ds_id: str,
    target_table: str,
    if_table_exists: str,
    batch_size: int = 500,
    table_remark: str = "",
    column_remarks: Optional[Dict[str, str]] = None,
) -> int:
    """分批写入数据到目标表

    第一批使用原始策略（如 replace/overwrite），后续批次自动切换为 append。
    避免后续批次清空前面批次的数据。

    Args:
        records: 待写入记录列表
        target_ds_id: 目标数据源ID
        target_table: 目标表名
        if_table_exists: 写入策略
        batch_size: 每批最大行数
        table_remark: 表备注（仅第一批生效）
        column_remarks: 列备注字典（仅第一批生效）

    Returns:
        总写入行数
    """
    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    total_written = 0

    for i in range(0, len(records), batch_size):
        batch_num = i // batch_size + 1
        batch = records[i: i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"

        result = write_table_data(
            target_ds_id,
            target_table,
            records=batch,
            if_table_exists=current_strategy,
            table_remark=table_remark if batch_num == 1 else "",
            column_remarks=column_remarks if batch_num == 1 else None,
        )
        if not result.get("success"):
            raise ValueError(
                f"写入批次 {batch_num} 失败: {result.get('message', '未知错误')}"
            )
        total_written += len(batch)
        print(f"  写入批次 {batch_num}: {len(batch)} 条 (累计 {total_written})")

    return total_written


# ============================================================================
# 步骤5：汇总报告
# ============================================================================

def _generate_summary(
    metadata_list: List[Dict[str, Any]],
    enhancements: Dict[str, Dict[str, Any]],
    relations: List[Dict[str, Any]],
    metadata_written: int,
    relations_written: int,
) -> Dict[str, Any]:
    """生成汇总报告

    Args:
        metadata_list: 原始元数据列表
        enhancements: AI增强结果映射
        relations: 跨源关系列表
        metadata_written: 已写入元数据条数
        relations_written: 已写入关系条数

    Returns:
        汇总信息字典
    """
    # 按数据源统计
    by_datasource: Dict[str, Dict[str, int]] = {}
    for m in metadata_list:
        ds = m["datasource_name"]
        if ds not in by_datasource:
            by_datasource[ds] = {"tables": 0, "total_rows": 0, "enhanced": 0}
        by_datasource[ds]["tables"] += 1
        by_datasource[ds]["total_rows"] += m["row_count"]
        key = f"{ds}::{m['table_name']}"
        if key in enhancements:
            by_datasource[ds]["enhanced"] += 1

    # 按数据分类统计
    by_category: Dict[str, int] = {}
    for enh in enhancements.values():
        cat = enh.get("data_category", "未分类")
        by_category[cat] = by_category.get(cat, 0) + 1

    # 按关系类型统计
    by_relation_type: Dict[str, int] = {}
    for r in relations:
        rt = r.get("relation_type", "unknown")
        by_relation_type[rt] = by_relation_type.get(rt, 0) + 1

    return {
        "total_tables": len(metadata_list),
        "total_enhanced": len(enhancements),
        "metadata_records_written": metadata_written,
        "cross_source_relations": len(relations),
        "relations_written": relations_written,
        "by_datasource": by_datasource,
        "by_category": by_category,
        "by_relation_type": by_relation_type,
    }


# ============================================================================
# 主业务函数
# ============================================================================

def sync_and_enhance_metadata(
    datasource_names: str = "",
    target_datasource_name: str = "文物库",
    metadata_table_name: str = "metadata_sync",
    relations_table_name: str = "metadata_cross_source_relations",
    enable_ai_enhancement: bool = True,
    enable_cross_source_analysis: bool = True,
    sample_size: int = 5,
    ai_batch_size: int = 5,
    write_batch_size: int = 500,
    if_table_exists: str = "replace",
) -> Dict[str, Any]:
    """主业务函数：跨数据源元数据同步与AI增强

    编排流程：收集元数据 → AI增强 → 跨源关系检测 → 写入注册表 → 生成汇总

    Args:
        datasource_names: 要处理的数据源名称，逗号分隔；空则处理全部
        target_datasource_name: 元数据写入的目标数据源
        metadata_table_name: 元数据注册表名
        relations_table_name: 跨源关系表名
        enable_ai_enhancement: 是否启用AI增强
        enable_cross_source_analysis: 是否启用跨源关系检测
        sample_size: 每张表采样行数
        ai_batch_size: AI增强每批表数
        write_batch_size: 写入批次大小
        if_table_exists: 写入策略

    Returns:
        包含 success/summary/写入信息的结果字典
    """
    log("info", "=== 元数据同步与AI增强 开始 ===")

    # ---- 1. 确定要处理的数据源 ----
    if datasource_names:
        names = [n.strip() for n in datasource_names.split(",") if n.strip()]
        ds_configs = {
            name: DEFAULT_DATASOURCE_CONFIGS[name]
            for name in names
            if name in DEFAULT_DATASOURCE_CONFIGS
        }
        missing = set(names) - set(DEFAULT_DATASOURCE_CONFIGS.keys())
        if missing:
            log("warn", f"未知数据源（已忽略）: {missing}")
    else:
        ds_configs = dict(DEFAULT_DATASOURCE_CONFIGS)

    if not ds_configs:
        return {"success": False, "error": "没有可处理的数据源"}

    total_tables = sum(len(cfg["tables"]) for cfg in ds_configs.values())
    log("info", f"待处理数据源: {list(ds_configs.keys())}，共 {total_tables} 张表")

    # ---- 2. 收集元数据 ----
    log("info", "--- 步骤1: 收集元数据 ---")
    metadata_list = _collect_all_metadata(ds_configs, sample_size)
    if not metadata_list:
        return {"success": False, "error": "未收集到任何元数据，请检查数据源连接"}

    # ---- 3. AI增强 ----
    enhancements: Dict[str, Dict[str, Any]] = {}
    if enable_ai_enhancement:
        log("info", "--- 步骤2: AI增强元数据 ---")
        enhancements = _enhance_all_metadata(metadata_list, ai_batch_size)
    else:
        log("info", "跳过AI增强（已禁用）")

    # ---- 4. 跨源关系检测 ----
    relations: List[Dict[str, Any]] = []
    if enable_cross_source_analysis:
        log("info", "--- 步骤3: 跨数据源关系检测 ---")
        relations = _detect_cross_source_relations(metadata_list)
    else:
        log("info", "跳过跨源关系分析（已禁用）")

    # ---- 5. 写入元数据表 ----
    log("info", "--- 步骤4: 写入元数据注册表 ---")
    records = _build_metadata_records(metadata_list, enhancements)

    target_ds_id = get_datasource_id_by_name(target_datasource_name)
    if not target_ds_id:
        return {"success": False, "error": f"找不到目标数据源: {target_datasource_name}"}

    # 写入元数据表
    try:
        metadata_written = _write_in_batches(
            records,
            target_ds_id,
            metadata_table_name,
            if_table_exists,
            write_batch_size,
            table_remark="元数据同步表 - 存储所有数据源的表结构、AI增强描述和分类信息",
            column_remarks={
                "id": "序号",
                "datasource_name": "数据源名称",
                "datasource_type": "数据源类型",
                "table_name": "表名",
                "column_count": "列数",
                "row_count": "行数",
                "columns_info": "列信息JSON",
                "sample_data": "样本数据JSON",
                "table_description": "AI生成的表描述",
                "column_descriptions": "AI生成的列描述JSON",
                "tags": "标签",
                "data_category": "数据分类",
                "quality_notes": "数据质量观察",
                "enhanced_at": "增强时间",
            },
        )
        log("info", f"元数据表写入完成: {metadata_written} 条 → {target_datasource_name}.{metadata_table_name}")
    except ValueError as e:
        return {"success": False, "error": str(e), "message": "元数据表写入失败"}

    # 写入跨源关系表
    relations_written = 0
    if relations:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        relation_records = []
        for i, r in enumerate(relations):
            relation_records.append({
                "id": f"{i+1:06d}",
                "source_datasource": r.get("source_datasource", ""),
                "source_table": r.get("source_table", ""),
                "target_datasource": r.get("target_datasource", ""),
                "target_table": r.get("target_table", ""),
                "relation_type": r.get("relation_type", ""),
                "relation_description": r.get("relation_description", ""),
                "detected_at": now,
            })

        try:
            relations_written = _write_in_batches(
                relation_records,
                target_ds_id,
                relations_table_name,
                if_table_exists,
                write_batch_size,
                table_remark="跨数据源关系表 - AI检测的表间关联关系",
                column_remarks={
                    "id": "序号",
                    "source_datasource": "源数据源",
                    "source_table": "源表名",
                    "target_datasource": "目标数据源",
                    "target_table": "目标表名",
                    "relation_type": "关系类型",
                    "relation_description": "关系描述",
                    "detected_at": "检测时间",
                },
            )
            log("info", f"跨源关系表写入完成: {relations_written} 条 → {target_datasource_name}.{relations_table_name}")
        except ValueError as e:
            log("warn", f"跨源关系表写入失败: {e}")

    # ---- 6. 生成汇总 ----
    summary = _generate_summary(
        metadata_list, enhancements, relations, metadata_written, relations_written
    )

    # 打印汇总报告
    print("\n" + "=" * 60)
    print("                    汇总报告")
    print("=" * 60)
    print(f"  总表数:       {summary['total_tables']}")
    print(f"  AI增强:       {summary['total_enhanced']}")
    print(f"  元数据写入:   {summary['metadata_records_written']} 条")
    print(f"  跨源关系:     {summary['cross_source_relations']} 条")
    print("-" * 60)
    print("  按数据源:")
    for ds, stats in summary["by_datasource"].items():
        print(f"    {ds}: {stats['tables']}表, {stats['total_rows']}行, 增强{stats['enhanced']}表")
    if summary["by_category"]:
        print("-" * 60)
        print("  按数据分类:")
        for cat, count in summary["by_category"].items():
            print(f"    {cat}: {count}表")
    if summary["by_relation_type"]:
        print("-" * 60)
        print("  按关系类型:")
        for rt, count in summary["by_relation_type"].items():
            print(f"    {rt}: {count}条")
    print("=" * 60)

    log("info", "=== 元数据同步与AI增强 完成 ===")

    return {
        "success": True,
        "summary": summary,
        "metadata_table": f"{target_datasource_name}.{metadata_table_name}",
        "relations_table": f"{target_datasource_name}.{relations_table_name}" if relations_written > 0 else None,
        "total_tables_processed": len(metadata_list),
        "total_enhanced": len(enhancements),
        "total_relations": len(relations),
    }


def main(**kwargs):
    """主入口，系统注入用户参数

    支持参数别名映射，兼容系统注入的不同参数名。
    """
    param_aliases = {
        "datasource_names": [
            "datasource_names", "datasources", "source_datasources",
            "datasource_name", "source_datasource_name",
        ],
        "target_datasource_name": [
            "target_datasource_name", "target_datasource", "output_datasource",
        ],
        "metadata_table_name": [
            "metadata_table_name", "metadata_table", "output_table",
        ],
        "relations_table_name": [
            "relations_table_name", "relations_table",
        ],
        "enable_ai_enhancement": [
            "enable_ai_enhancement", "ai_enhancement", "enable_ai",
        ],
        "enable_cross_source_analysis": [
            "enable_cross_source_analysis", "cross_source_analysis",
            "enable_cross_source",
        ],
        "sample_size": ["sample_size", "sample_rows"],
        "ai_batch_size": ["ai_batch_size", "batch_size"],
        "write_batch_size": ["write_batch_size", "write_batch"],
        "if_table_exists": ["if_table_exists", "write_strategy"],
    }

    params: Dict[str, Any] = {}
    for canonical, aliases in param_aliases.items():
        for alias in aliases:
            if alias in kwargs:
                params[canonical] = kwargs[alias]
                break

    return sync_and_enhance_metadata(**params)