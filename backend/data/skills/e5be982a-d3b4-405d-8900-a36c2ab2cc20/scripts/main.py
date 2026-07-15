import re
from datetime import datetime
from typing import Dict, Any, List, Optional

# ============================================================
# 省份提取
# ============================================================
PROVINCE_SHORT = [
    ("北京", "北京市"), ("天津", "天津市"), ("上海", "上海市"), ("重庆", "重庆市"),
    ("河北", "河北省"), ("山西", "山西省"), ("辽宁", "辽宁省"), ("吉林", "吉林省"),
    ("黑龙江", "黑龙江省"), ("江苏", "江苏省"), ("浙江", "浙江省"), ("安徽", "安徽省"),
    ("福建", "福建省"), ("江西", "江西省"), ("山东", "山东省"), ("河南", "河南省"),
    ("湖北", "湖北省"), ("湖南", "湖南省"), ("广东", "广东省"), ("海南", "海南省"),
    ("四川", "四川省"), ("贵州", "贵州省"), ("云南", "云南省"), ("陕西", "陕西省"),
    ("甘肃", "甘肃省"), ("青海", "青海省"), ("台湾", "台湾省"),
    ("内蒙古", "内蒙古自治区"), ("广西", "广西壮族自治区"),
    ("西藏", "西藏自治区"), ("宁夏", "宁夏回族自治区"),
    ("新疆", "新疆维吾尔自治区"),
    ("香港", "香港特别行政区"), ("澳门", "澳门特别行政区"),
]

def extract_province(address: str) -> str:
    """从地址中提取省份。

    Args:
        address: 文物地址字符串。

    Returns:
        省份名称，无法识别返回空字符串。
    """
    if not address or not isinstance(address, str):
        return ""
    addr = address.strip()
    for short, province in PROVINCE_SHORT:
        if addr.startswith(short):
            return province
    return ""


# ============================================================
# 列名映射（中文→英文）
# ============================================================
COLUMN_MAPPING = {
    "批次": "batch",
    "年度": "year",
    "序号": "sequence_no",
    "编号": "code",
    "名称": "name",
    "时代": "era",
    "地址": "address",
    "类型": "type",
    "备注": "remark",
}

COLUMN_REMARKS = {
    "id": "唯一标识，8位数字零补齐",
    "batch": "公布批次",
    "year": "公布年度",
    "sequence_no": "序号",
    "code": "文物编号",
    "name": "文物名称",
    "era": "文物时代",
    "address": "文物地址",
    "type": "文物类型",
    "remark": "备注",
    "province": "省份（从地址中提取）",
    "timestamp": "数据导入时间戳",
}


# ============================================================
# 分批写入
# ============================================================
def _write_records(records: List[Dict[str, Any]], target_ds: str, table_name: str,
                   if_table_exists: str, batch_size: int = 500,
                   table_remark: str = "", column_remarks: Optional[Dict[str, str]] = None) -> None:
    """分批写入记录到目标表。

    第一批使用原始写入策略，后续批次自动切换为 append。

    Args:
        records: 待写入的记录列表。
        target_ds: 目标数据源 ID。
        table_name: 目标表名。
        if_table_exists: 写入策略。
        batch_size: 每批大小。
        table_remark: 表备注。
        column_remarks: 列备注字典。
    """
    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    total = len(records)

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"

        write_table_data(
            target_ds, table_name,
            records=batch,
            if_table_exists=current_strategy,
            table_remark=table_remark,
            column_remarks=column_remarks,
        )
        written = min(i + batch_size, total)
        print(f"  已写入第 {batch_num} 批: {len(batch)} 条 (累计 {written}/{total})")


# ============================================================
# 核心业务函数
# ============================================================
def migrate_relic_data(
    source_datasource_name: str,
    source_table_name: str,
    target_datasource_name: str,
    target_table_name: str = "national_key_relics",
    if_table_exists: str = "replace",
    batch_size: int = 500,
) -> Dict[str, Any]:
    """从源表读取全国重点文物数据，加工后写入目标表。

    自动生成英文表名和列名，添加 ID（8位零补齐）、时间戳、省份列。
    省份从地址字段中提取。表和列的备注使用中文。

    Args:
        source_datasource_name: 源数据源名称。
        source_table_name: 源表名。
        target_datasource_name: 目标数据源名称。
        target_table_name: 目标表名（英文）。
        if_table_exists: 写入策略。
        batch_size: 分批写入批次大小。

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
    row_count = result.get("row_count", len(data))

    if not data:
        return {"success": False, "error": "源表无数据", "message": f"源表 {source_table_name} 返回空数据"}

    print(f"源数据读取成功: {len(data)} 条, 列: {source_columns}")

    # ---- 3. 数据加工 ----
    log("info", "开始数据加工: 列名映射、添加ID/时间戳/省份...")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    processed_records: List[Dict[str, Any]] = []
    province_empty_count = 0

    for idx, row in enumerate(data):
        if isinstance(row, (list, tuple)):
            row_dict = dict(zip(source_columns, row))
        elif isinstance(row, dict):
            row_dict = dict(row)
        else:
            row_dict = {"value": str(row)}

        # 构建新记录（英文列名）
        record: Dict[str, Any] = {}
        record["id"] = f"{idx + 1:08d}"

        for cn_name, en_name in COLUMN_MAPPING.items():
            val = row_dict.get(cn_name, "")
            record[en_name] = "" if val is None else val

        # 提取省份
        address = str(row_dict.get("地址", "")).strip()
        province = extract_province(address)
        if not province:
            province_empty_count += 1
        record["province"] = province

        # 时间戳
        record["timestamp"] = now_str

        processed_records.append(record)

    print(f"数据加工完成: {len(processed_records)} 条")
    print(f"  省份提取: 成功 {len(processed_records) - province_empty_count} 条, 未识别 {province_empty_count} 条")

    # ---- 4. 写入目标表 ----
    table_remark = "全国重点文物保护单位名录"
    log("info", f"写入目标表: {target_table_name} (策略: {if_table_exists})")

    try:
        _write_records(
            processed_records, target_ds, target_table_name,
            if_table_exists, batch_size,
            table_remark=table_remark,
            column_remarks=COLUMN_REMARKS,
        )
    except Exception as e:
        return {"success": False, "error": f"写入目标表失败: {str(e)}", "message": "数据写入异常"}

    log("info", f"处理完成: 共 {len(processed_records)} 条数据已写入 {target_table_name}")

    return {
        "success": True,
        "total_rows": len(processed_records),
        "target_table": target_table_name,
        "columns": list(COLUMN_REMARKS.keys()),
        "province_extracted": len(processed_records) - province_empty_count,
        "province_empty": province_empty_count,
        "sample": processed_records[:3],
    }


# ============================================================
# 主入口
# ============================================================
def main(**kwargs) -> Dict[str, Any]:
    """主入口函数，系统注入用户参数。

    Returns:
        包含 success 及处理结果的字典。
    """
    param_aliases = {
        "source_datasource_name": ["source_datasource_name", "source_datasource", "datasource_name", "datasource", "源数据源"],
        "source_table_name": ["source_table_name", "source_table", "table_name", "源表名"],
        "target_datasource_name": ["target_datasource_name", "target_datasource", "目标数据源"],
        "target_table_name": ["target_table_name", "target_table", "output_table", "目标表名"],
        "if_table_exists": ["if_table_exists", "write_strategy", "strategy", "写入策略"],
        "batch_size": ["batch_size", "batch", "批次大小"],
    }

    params: Dict[str, Any] = {}
    for target_key, aliases in param_aliases.items():
        for alias in aliases:
            if alias in kwargs:
                params[target_key] = kwargs[alias]
                break

    params.setdefault("target_table_name", "national_key_relics")
    params.setdefault("if_table_exists", "replace")
    params.setdefault("batch_size", 500)

    required = ["source_datasource_name", "source_table_name", "target_datasource_name"]
    missing = [r for r in required if r not in params or not params[r]]
    if missing:
        return {"success": False, "error": f"缺少必填参数: {', '.join(missing)}", "message": "参数校验失败"}

    return migrate_relic_data(**params)