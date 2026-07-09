import json
from datetime import datetime
from typing import Dict, Any, Optional, List

# ============================================================
# 文档类型模板
# ============================================================
DOC_TEMPLATES = {
    "id_card": {
        "name": "身份证",
        "fields": ["姓名", "性别", "民族", "出生日期", "住址", "身份证号", "签发机关", "有效期限"],
        "instruction": (
            "请识别这张身份证图片中的信息，提取以下字段："
            "姓名、性别、民族、出生日期、住址、身份证号、签发机关、有效期限。"
        ),
    },
    "business_license": {
        "name": "营业执照",
        "fields": [
            "统一社会信用代码", "企业名称", "企业类型", "法定代表人",
            "注册资本", "成立日期", "营业期限", "经营范围", "住所",
        ],
        "instruction": (
            "请识别这张营业执照图片中的信息，提取以下字段："
            "统一社会信用代码、企业名称、企业类型、法定代表人、注册资本、"
            "成立日期、营业期限、经营范围、住所。"
        ),
    },
    "auto": {
        "name": "自动识别",
        "fields": [],
        "instruction": "请自动判断图片中的文档类型，并提取所有可见的关键信息字段。",
    },
}


# ============================================================
# 构建提取 prompt
# ============================================================
def _build_extraction_prompt(image_url: str, doc_type: str) -> str:
    """根据文档类型构建 LLM 提取 prompt。

    Args:
        image_url: 图片URL或路径。
        doc_type: 文档类型（id_card / business_license / auto）。

    Returns:
        完整的 prompt 字符串。
    """
    template = DOC_TEMPLATES.get(doc_type, DOC_TEMPLATES["auto"])
    fields = template["fields"]

    if fields:
        fields_example = ", ".join([f'"{f}": "值或null"' for f in fields])
        prompt = f"""请仔细识别以下图片中的关键信息。

任务要求：
1. 识别图片类型（{template["name"]}）
2. 提取以下字段：{"、".join(fields)}
3. 如果某个字段无法识别，将其值设为 null
4. 如果整张图片模糊不清或无法识别，返回 confidence 为 0.0

请严格以 JSON 格式返回，不要包含任何其他文字或解释：
{{
  "doc_type": "{template["name"]}",
  "fields": {{
    {fields_example}
  }},
  "confidence": 0.0
}}

图片：
![image]({image_url})
"""
    else:
        prompt = f"""请仔细识别以下图片中的所有关键信息。

任务要求：
1. 自动判断图片类型（身份证、营业执照、其他证件等）
2. 提取图片中所有可见的关键信息字段
3. 如果某个字段无法识别，将其值设为 null
4. 如果整张图片模糊不清或无法识别，返回 confidence 为 0.0

请严格以 JSON 格式返回，不要包含任何其他文字或解释：
{{
  "doc_type": "文档类型",
  "fields": {{
    "字段名": "字段值"
  }},
  "confidence": 0.0
}}

图片：
![image]({image_url})
"""
    return prompt


# ============================================================
# 解析 LLM 返回的 JSON
# ============================================================
def _parse_llm_response(response: str) -> Optional[Dict[str, Any]]:
    """从 LLM 文本回复中解析 JSON。

    Args:
        response: LLM 的原始文本回复。

    Returns:
        解析后的字典，解析失败返回 None。
    """
    if not response:
        return None

    # 尝试直接解析
    try:
        return json.loads(response)
    except (json.JSONDecodeError, TypeError):
        pass

    # 尝试从 ```json ... ``` 代码块中提取
    for marker in ("```json", "```"):
        if marker in response:
            start = response.find(marker) + len(marker)
            end = response.find("```", start)
            if end > start:
                try:
                    return json.loads(response[start:end].strip())
                except (json.JSONDecodeError, TypeError):
                    pass

    # 尝试提取第一个 { ... } 块
    first_brace = response.find("{")
    last_brace = response.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(response[first_brace:last_brace + 1])
        except (json.JSONDecodeError, TypeError):
            pass

    return None


# ============================================================
# 分批写入
# ============================================================
def _write_records(
    records: List[Dict[str, Any]],
    target_ds: str,
    table_name: str,
    if_table_exists: str,
    batch_size: int = 500,
) -> None:
    """分批写入记录到目标表。

    第一批使用原始写入策略（如 overwrite/replace/truncate），
    后续批次自动切换为 append，避免清空已写入数据。

    Args:
        records: 待写入的记录列表。
        target_ds: 目标数据源 ID。
        table_name: 目标表名。
        if_table_exists: 写入策略。
        batch_size: 每批大小。
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
            target_ds,
            table_name,
            records=batch,
            if_table_exists=current_strategy,
        )
        written = min(i + batch_size, total)
        print(f"  已写入第 {batch_num} 批: {len(batch)} 条 (累计 {written}/{total})")


# ============================================================
# 核心业务函数
# ============================================================
def extract_image_info(
    source_datasource_name: str,
    source_table_name: str,
    target_datasource_name: str,
    target_table_name: str,
    image_column: str,
    doc_type: str = "auto",
    if_table_exists: str = "fail",
    batch_size: int = 500,
) -> Dict[str, Any]:
    """从图片中提取关键信息并写入目标数据源。

    读取源表中图片URL列，调用多模态LLM识别图片内容，
    将提取结果写入目标表。识别失败的记录标记为"待人工审核"。

    Args:
        source_datasource_name: 源数据源名称。
        source_table_name: 源表名。
        target_datasource_name: 目标数据源名称。
        target_table_name: 目标表名。
        image_column: 图片URL/路径列名。
        doc_type: 文档类型（id_card / business_license / auto）。
        if_table_exists: 写入策略。
        batch_size: 分批写入批次大小。

    Returns:
        包含 success、total_rows、extracted、failed 等字段的字典。
    """
    # ---- 1. 获取数据源 ID ----
    log("info", f"获取源数据源 ID: {source_datasource_name}")
    source_ds = get_datasource_id_by_name(source_datasource_name)
    if not source_ds:
        return {
            "success": False,
            "error": f"找不到源数据源: {source_datasource_name}",
            "message": "数据源名称校验失败",
        }

    log("info", f"获取目标数据源 ID: {target_datasource_name}")
    target_ds = get_datasource_id_by_name(target_datasource_name)
    if not target_ds:
        return {
            "success": False,
            "error": f"找不到目标数据源: {target_datasource_name}",
            "message": "数据源名称校验失败",
        }

    # ---- 2. 读取源数据 ----
    log("info", f"读取源表数据: {source_table_name}")
    result = query_table_data(source_ds, source_table_name, limit=100000)
    if not result.get("success"):
        return {
            "success": False,
            "error": f"读取源数据失败: {result.get('error', '未知错误')}",
            "message": "数据读取失败",
        }

    columns = result.get("columns", [])
    data = result.get("data", [])

    if not data:
        log("warn", "源表无数据")
        return {
            "success": True,
            "total_rows": 0,
            "extracted": 0,
            "failed": 0,
            "message": "源表无数据，无需处理",
        }

    print(f"源数据: {len(data)} 条, 列: {columns}")

    # ---- 3. 检查图片列 ----
    if image_column not in columns:
        # 尝试模糊匹配
        matched = [c for c in columns if image_column.lower() in str(c).lower()]
        if matched:
            image_column = matched[0]
            print(f"图片列模糊匹配成功: {image_column}")
        else:
            return {
                "success": False,
                "error": f"图片列 '{image_column}' 不存在，现有列: {columns}",
                "message": "参数校验失败",
            }

    # ---- 4. 逐条处理 ----
    template = DOC_TEMPLATES.get(doc_type, DOC_TEMPLATES["auto"])
    log("info", f"文档类型: {template['name']}，开始逐条提取...")

    extracted_records: List[Dict[str, Any]] = []
    success_count = 0
    failed_count = 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for idx, row in enumerate(data):
        # 将行数据转为字典
        if isinstance(row, (list, tuple)):
            row_dict = dict(zip(columns, row))
        elif isinstance(row, dict):
            row_dict = dict(row)
        else:
            row_dict = {"value": str(row)}

        image_url = str(row_dict.get(image_column, "")).strip()

        # 构建输出记录（保留原始数据 + 提取结果）
        record: Dict[str, Any] = {}
        for k, v in row_dict.items():
            record[k] = v
        record["原始图片"] = image_url
        record["提取状态"] = ""
        record["审核标记"] = ""
        record["处理时间"] = now_str

        # ---- 无图片 URL ----
        if not image_url or image_url in ("None", "nan", "null", ""):
            record["提取状态"] = "无图片"
            record["审核标记"] = "待人工审核"
            failed_count += 1
            print(f"  [{idx + 1}/{len(data)}] 无图片URL，标记待审核")
            extracted_records.append(record)
            continue

        # ---- 调用 LLM 提取 ----
        prompt = _build_extraction_prompt(image_url, doc_type)

        try:
            llm_response = llm_chat(
                prompt=prompt,
                system_prompt=(
                    "你是一个专业的OCR信息提取助手，擅长从身份证、营业执照等"
                    "证件图片中提取结构化信息。请只返回JSON格式数据，不要包含其他文字。"
                ),
                temperature=0.1,
                max_tokens=2000,
            )

            parsed = _parse_llm_response(llm_response)

            if parsed is None:
                record["提取状态"] = "解析失败"
                record["审核标记"] = "待人工审核"
                record["LLM原始返回"] = (llm_response or "")[:500]
                failed_count += 1
                print(f"  [{idx + 1}/{len(data)}] LLM返回解析失败，标记待审核")
            else:
                confidence = float(parsed.get("confidence", 0.5))
                fields = parsed.get("fields", {})
                detected_type = parsed.get("doc_type", template["name"])

                record["识别文档类型"] = detected_type
                record["置信度"] = confidence

                # 将提取的字段平铺到记录中
                for field_name, field_value in fields.items():
                    safe_name = str(field_name).replace(" ", "_").replace(".", "_")
                    record[f"提取_{safe_name}"] = field_value

                # 判断是否需要人工审核
                has_valid_fields = any(
                    v is not None and str(v).strip() not in ("", "null", "None")
                    for v in fields.values()
                )

                if confidence < 0.5 or not has_valid_fields:
                    record["提取状态"] = "识别不全"
                    record["审核标记"] = "待人工审核"
                    failed_count += 1
                    print(
                        f"  [{idx + 1}/{len(data)}] 置信度低({confidence:.2f})，"
                        f"标记待审核"
                    )
                else:
                    record["提取状态"] = "成功"
                    record["审核标记"] = ""
                    success_count += 1
                    print(
                        f"  [{idx + 1}/{len(data)}] 提取成功 "
                        f"(类型: {detected_type}, 置信度: {confidence:.2f})"
                    )

        except Exception as e:
            record["提取状态"] = f"异常: {str(e)[:100]}"
            record["审核标记"] = "待人工审核"
            failed_count += 1
            print(f"  [{idx + 1}/{len(data)}] 处理异常: {e}")

        extracted_records.append(record)

    # ---- 5. 写入目标表 ----
    log("info", f"写入目标表: {target_table_name} (策略: {if_table_exists})")
    try:
        _write_records(
            extracted_records, target_ds, target_table_name,
            if_table_exists, batch_size,
        )
    except Exception as e:
        return {
            "success": False,
            "error": f"写入目标表失败: {str(e)}",
            "message": "数据写入异常",
            "total_rows": len(data),
            "extracted": success_count,
            "failed": failed_count,
        }

    # ---- 6. 汇总结果 ----
    all_fields: set = set()
    for r in extracted_records:
        all_fields.update(r.keys())

    log("info", f"处理完成: 共 {len(data)} 条, 成功 {success_count}, 待审核 {failed_count}")

    return {
        "success": True,
        "total_rows": len(data),
        "extracted": success_count,
        "failed": failed_count,
        "target_table": target_table_name,
        "columns": sorted(list(all_fields)),
        "sample": extracted_records[:3],
    }


# ============================================================
# 主入口
# ============================================================
def main(**kwargs) -> Dict[str, Any]:
    """主入口函数，系统注入用户参数。

    支持多种参数名别名映射，兼容不同调用方式。

    Returns:
        包含 success 及处理结果的字典。
    """
    param_aliases = {
        "source_datasource_name": [
            "source_datasource_name", "source_datasource",
            "datasource_name", "datasource", "源数据源",
        ],
        "source_table_name": [
            "source_table_name", "source_table",
            "table_name", "源表名",
        ],
        "target_datasource_name": [
            "target_datasource_name", "target_datasource",
            "目标数据源",
        ],
        "target_table_name": [
            "target_table_name", "target_table",
            "output_table", "目标表名",
        ],
        "image_column": [
            "image_column", "image_url_column",
            "image_field", "图片列", "图片列名",
        ],
        "doc_type": [
            "doc_type", "document_type", "类型", "文档类型",
        ],
        "if_table_exists": [
            "if_table_exists", "write_strategy", "strategy", "写入策略",
        ],
        "batch_size": [
            "batch_size", "batch", "批次大小",
        ],
    }

    params: Dict[str, Any] = {}
    for target_key, aliases in param_aliases.items():
        for alias in aliases:
            if alias in kwargs:
                params[target_key] = kwargs[alias]
                break

    # 设置默认值
    params.setdefault("doc_type", "auto")
    params.setdefault("if_table_exists", "fail")
    params.setdefault("batch_size", 500)

    # 校验必填参数
    required = [
        "source_datasource_name", "source_table_name",
        "target_datasource_name", "target_table_name", "image_column",
    ]
    missing = [r for r in required if r not in params or not params[r]]
    if missing:
        return {
            "success": False,
            "error": f"缺少必填参数: {', '.join(missing)}",
            "message": "参数校验失败",
        }

    return extract_image_info(**params)