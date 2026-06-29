"""
数据迁移脚本
在不同数据源之间迁移数据，支持列名转换、列删除、列添加及基本数据处理
支持自动翻译列名为英文，并设置中文备注
"""

import sys
import io
import inspect
import re
import time
import traceback
import pandas as pd
from typing import Dict, List, Optional, Any

# 修复 Windows 环境下 GBK 编码无法输出 emoji 等特殊字符的问题
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ============================================================
# 内置函数延迟加载（不在模块级调用，避免加载时崩溃）
# ============================================================
def _get_builtin_func(name: str):
    """自动适配带 _dc_ 前缀和不带前缀的内置函数"""
    g = globals()
    if name in g:
        return g[name]
    prefixed_name = f"_dc_{name}"
    if prefixed_name in g:
        return g[prefixed_name]
    # 如果都找不到，返回一个会报错的占位函数，而不是在加载时崩溃
    def _not_found(*args, **kwargs):
        raise NameError(f"内置函数 '{name}' (或 '{prefixed_name}') 不存在，请检查运行环境是否正确注入")
    _not_found.__name__ = f"_not_found_{name}"
    return _not_found


# ============================================================
# 常用中文→英文翻译词典（用于自动生成英文列名/表名）
# ============================================================
COMMON_CN_EN = {
    "编号": "code", "序号": "serial_no", "名称": "name", "名字": "name",
    "类型": "type", "类别": "category", "分类": "classification",
    "年代": "era", "时期": "period", "朝代": "dynasty", "时代": "era",
    "年度": "year", "年份": "year", "月份": "month",
    "地点": "location", "地址": "address", "位置": "position",
    "描述": "description", "简介": "introduction", "说明": "description",
    "备注": "remark", "注释": "annotation", "标记": "mark",
    "状态": "status", "级别": "level", "数量": "quantity",
    "日期": "date", "时间": "time", "价格": "price", "金额": "amount",
    "作者": "author", "来源": "source", "图片": "image", "照片": "photo",
    "经度": "longitude", "纬度": "latitude", "面积": "area",
    "标题": "title", "标签": "tag", "内容": "content", "详情": "details",
    "省份": "province", "城市": "city", "区县": "district",
    "乡镇": "town", "村庄": "village", "街道": "street",
    "社区": "community", "区域": "region", "国家": "country",
    "高度": "height", "宽度": "width", "长度": "length",
    "深度": "depth", "直径": "diameter", "半径": "radius",
    "创建时间": "created_at", "更新时间": "updated_at",
    "操作": "operation", "管理": "management", "负责": "responsible",
    "联系": "contact", "电话": "phone", "邮箱": "email",
    "网站": "website", "链接": "link", "网址": "url",
    "文物": "relic", "保护": "protection", "单位": "unit",
    "全国": "national", "重点": "key", "省级": "provincial",
    "市级": "municipal", "县级": "county", "公布": "published",
    "批次": "batch", "所属": "belonging", "材质": "material",
    "尺寸": "size", "重量": "weight", "颜色": "color",
    "用途": "purpose", "功能": "function", "发现": "discovery",
    "发掘": "excavation", "出土": "unearthed", "收藏": "collection",
    "展览": "exhibition", "修复": "restoration", "保存": "preservation",
    "现状": "condition", "建成": "construction",
    "文物名称": "relic_name", "文物编号": "relic_code",
    "文物类型": "relic_type", "文物级别": "relic_level",
    "保护单位": "protection_unit", "公布批次": "published_batch",
    "所在省份": "province", "所在城市": "city",
    "所在区县": "district", "详细地址": "detailed_address",
    "建成年代": "construction_era", "所属朝代": "dynasty",
    "全国重点": "national_key", "文物保护单位": "cultural_relic_protection_unit",
    "全国重点文物保护单位": "national_key_cultural_relic_protection_units",
    "记录时间戳": "record_timestamp", "时间戳": "timestamp",
}


def _smart_translate(text: str) -> str:
    """智能翻译中文为英文列名/表名"""
    text = str(text).strip()
    if text in COMMON_CN_EN:
        return COMMON_CN_EN[text]

    result_parts = []
    remaining = text
    has_translation = False
    while remaining:
        matched = False
        for length in range(len(remaining), 0, -1):
            substr = remaining[:length]
            if substr in COMMON_CN_EN:
                result_parts.append(COMMON_CN_EN[substr])
                remaining = remaining[length:]
                matched = True
                has_translation = True
                break
        if not matched:
            char = remaining[0]
            try:
                from pypinyin import pinyin, Style
                py = pinyin(char, style=Style.NORMAL)
                if py and py[0] and py[0][0]:
                    result_parts.append(py[0][0])
            except ImportError:
                result_parts.append(char)
            remaining = remaining[1:]
    if has_translation:
        return '_'.join(result_parts)

    try:
        from pypinyin import pinyin, Style
        clean_text = re.sub(r'[^\u4e00-\u9fa5]', '', text)
        if not clean_text:
            return re.sub(r'\s+', '_', text.lower())
        result = pinyin(clean_text, style=Style.NORMAL)
        return '_'.join([item[0] for item in result])
    except ImportError:
        return re.sub(r'\s+', '_', text.lower())


def _is_english_identifier(name: str) -> bool:
    if not name:
        return False
    name = str(name)
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))


def _sanitize_identifier(name: str, fallback: str = "col") -> str:
    name = str(name).strip()
    if not name:
        return fallback
    if _is_english_identifier(name):
        return name
    translated = _smart_translate(name)
    translated = re.sub(r'[^a-zA-Z0-9_]', '_', translated)
    translated = re.sub(r'_+', '_', translated).strip('_')
    if translated and translated[0].isdigit():
        translated = f"_{translated}"
    if not translated:
        translated = fallback
    return translated


# ============================================================
# 列转换工具函数
# ============================================================

def _batch_translate(values: List[str], source_lang: str, target_lang: str) -> List[str]:
    """批量翻译文本列表，使用 llm_chat 调用大模型。"""
    if not values:
        return values
    try:
        llm_chat_func = _get_builtin_func('llm_chat')
    except Exception:
        print("  ⚠️ llm_chat 函数不可用，跳过翻译")
        return values

    lang_map = {"zh": "中文", "en": "英文"}
    src_name = lang_map.get(source_lang, source_lang)
    tgt_name = lang_map.get(target_lang, target_lang)

    batch_limit = 50
    results = []
    for i in range(0, len(values), batch_limit):
        batch = values[i:i + batch_limit]
        batch_num = i // batch_limit + 1
        lines = [f"{idx + 1}. {val}" for idx, val in enumerate(batch)]
        prompt = f"请将以下{src_name}文本翻译为{tgt_name}，只输出翻译结果，每行一条，保持编号格式。\n\n{chr(10).join(lines)}\n\n要求：\n1. 每行格式为 \"编号. 翻译结果\"\n2. 只输出翻译结果，不要添加任何额外说明\n3. 保持原文的含义，翻译要准确自然"
        system_prompt = f"你是一个专业的{src_name}到{tgt_name}翻译助手。请准确翻译，保持编号格式。"
        try:
            print(f"    🌐 翻译批次 {batch_num} ({len(batch)} 条)...")
            reply = llm_chat_func(prompt, system_prompt=system_prompt, temperature=0.3)
            translated_batch = _parse_translation_reply(reply, len(batch))
            if len(translated_batch) == len(batch):
                results.extend(translated_batch)
            else:
                print(f"    ⚠️ 批量解析失败，回退逐条翻译...")
                for val in batch:
                    single_prompt = f"请将以下{src_name}文本翻译为{tgt_name}，只输出翻译结果：\n{val}"
                    single_reply = llm_chat_func(single_prompt, system_prompt=system_prompt, temperature=0.3)
                    results.append(single_reply.strip())
        except Exception as e:
            print(f"    ⚠️ 翻译批次 {batch_num} 失败: {e}，使用原文")
            results.extend(batch)
    return results


def _parse_translation_reply(reply: str, expected_count: int) -> List[str]:
    lines = reply.strip().split('\n')
    results = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = re.match(r'^\d+[\.\、]\s*(.*)$', line)
        if match:
            results.append(match.group(1).strip())
        else:
            results.append(line)
    if len(results) != expected_count:
        return []
    return results


def apply_column_transform(df: pd.DataFrame, column: str, rule: Dict[str, Any]) -> pd.DataFrame:
    """对 DataFrame 中指定列应用转换规则。"""
    if column not in df.columns:
        print(f"  ⚠️ 列 '{column}' 不存在，跳过转换")
        return df

    transform_type = rule.get("type")

    if transform_type == "trim":
        mask = df[column].notna()
        df.loc[mask, column] = df.loc[mask, column].astype(str).str.strip()
    elif transform_type == "upper":
        mask = df[column].notna()
        df.loc[mask, column] = df.loc[mask, column].astype(str).str.upper()
    elif transform_type == "lower":
        mask = df[column].notna()
        df.loc[mask, column] = df.loc[mask, column].astype(str).str.lower()
    elif transform_type == "fill_na":
        fill_value = rule.get("value", "")
        df[column] = df[column].fillna(fill_value)
    elif transform_type == "to_int":
        df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
    elif transform_type == "to_float":
        df[column] = pd.to_numeric(df[column], errors="coerce")
        if "round" in rule:
            df[column] = df[column].round(int(rule["round"]))
    elif transform_type == "to_str":
        mask = df[column].notna()
        df.loc[mask, column] = df.loc[mask, column].astype(str)
    elif transform_type == "to_date":
        date_format = rule.get("format")
        df[column] = pd.to_datetime(df[column], format=date_format, errors="coerce")
    elif transform_type == "prefix":
        prefix_value = str(rule.get("value", ""))
        mask = df[column].notna()
        df.loc[mask, column] = prefix_value + df.loc[mask, column].astype(str)
    elif transform_type == "suffix":
        suffix_value = str(rule.get("value", ""))
        mask = df[column].notna()
        df.loc[mask, column] = df.loc[mask, column].astype(str) + suffix_value
    elif transform_type == "replace":
        old_val = str(rule.get("old", ""))
        new_val = str(rule.get("new", ""))
        mask = df[column].notna()
        df.loc[mask, column] = df.loc[mask, column].astype(str).str.replace(old_val, new_val, regex=False)
    elif transform_type == "translate":
        source_lang = rule.get("source_lang", "zh")
        target_lang = rule.get("target_lang", "en")
        print(f"    🌐 翻译列 '{column}': {source_lang} → {target_lang}")
        mask = df[column].notna()
        values_to_translate = df.loc[mask, column].astype(str).tolist()
        if values_to_translate:
            print(f"    📝 共 {len(values_to_translate)} 条需要翻译")
            translated_values = _batch_translate(values_to_translate, source_lang, target_lang)
            df.loc[mask, column] = translated_values
    else:
        print(f"  ⚠️ 未知的转换类型 '{transform_type}'，跳过")
    return df


# ============================================================
# 核心迁移函数
# ============================================================

def migrate_data(
    source_datasource_name: Optional[str] = None,
    source_table_name: Optional[str] = None,
    target_datasource_name: Optional[str] = None,
    target_table_name: Optional[str] = None,
    column_mapping: Optional[Dict[str, str]] = None,
    column_transforms: Optional[Dict[str, Dict[str, Any]]] = None,
    drop_columns: Optional[List[str]] = None,
    add_columns: Optional[Dict[str, Any]] = None,
    batch_size: int = 1000,
    limit: int = 10000,
    output_dir: Optional[str] = None,
    auto_translate: bool = False,
    table_remark: Optional[str] = None,
    column_remarks: Optional[Dict[str, str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """在不同数据源之间迁移数据，支持列名转换和简单数据处理。"""

    # 延迟加载内置函数
    get_datasource_id_by_name = _get_builtin_func('get_datasource_id_by_name')
    query_table_data = _get_builtin_func('query_table_data')
    write_table_data = _get_builtin_func('write_table_data')

    # 兼容系统自动注入的参数
    if not source_datasource_name and 'datasource' in kwargs:
        source_datasource_name = kwargs.get('datasource')
    if not source_datasource_name and 'source_datasource' in kwargs:
        source_datasource_name = kwargs.get('source_datasource')
    if not source_table_name and 'table_name' in kwargs:
        source_table_name = kwargs.get('table_name')
    if not target_datasource_name and 'target_datasource' in kwargs:
        target_datasource_name = kwargs.get('target_datasource')

    column_mapping = column_mapping or {}
    column_transforms = column_transforms or {}
    drop_columns = drop_columns or []

    # 修复点：兼容 add_columns 传入列表的情况
    if isinstance(add_columns, list):
        temp_add = {}
        for item in add_columns:
            if isinstance(item, dict) and 'name' in item:
                temp_add[item['name']] = item.get('value')
            elif isinstance(item, str):
                temp_add[item] = None
        add_columns = temp_add
    if add_columns is None:
        add_columns = {}

    column_remarks = column_remarks or {}

    if not all([source_datasource_name, source_table_name, target_datasource_name]):
        msg = "缺少必要的迁移参数 (源数据源名, 源表名, 目标数据源名)。"
        print(f"⚠️ {msg}")
        print(f"   source_datasource_name={source_datasource_name}")
        print(f"   source_table_name={source_table_name}")
        print(f"   target_datasource_name={target_datasource_name}")
        return {"success": False, "error": msg, "message": "参数校验失败"}

    print("=" * 60)
    print("🚀 数据迁移开始")
    print(f"  源:   {source_datasource_name} → {source_table_name}")
    print(f"  目标: {target_datasource_name} → {target_table_name or '(自动生成)'}")
    print(f"  自动翻译: {auto_translate}")
    print("=" * 60)

    # 探测 write_table_data 签名
    print("\n🔍 探测 write_table_data 函数签名...")
    write_supported_params = set()
    try:
        sig = inspect.signature(write_table_data)
        print(f"  {sig}")
        write_supported_params = set(sig.parameters.keys())
    except Exception as e:
        print(f"  无法获取签名: {e}")

    # 步骤1: 获取数据源 ID
    print("\n📡 步骤1: 获取数据源信息...")
    source_ds_id = get_datasource_id_by_name(source_datasource_name)
    if not source_ds_id:
        raise ValueError(f"找不到源数据源: '{source_datasource_name}'")
    print(f"  ✅ 源数据源 ID: {source_ds_id}")

    target_ds_id = get_datasource_id_by_name(target_datasource_name)
    if not target_ds_id:
        raise ValueError(f"找不到目标数据源: '{target_datasource_name}'")
    print(f"  ✅ 目标数据源 ID: {target_ds_id}")

    # 步骤2: 读取源表数据
    print(f"\n📊 步骤2: 从源表 '{source_table_name}' 读取数据 (limit={limit})...")
    result = query_table_data(source_ds_id, source_table_name, limit=limit)
    if not result.get("success"):
        error_msg = result.get("error") or result.get("message", "未知错误")
        raise ValueError(f"读取源表数据失败: {error_msg}")

    data = result.get("data", [])
    columns = result.get("columns", [])
    row_count = result.get("row_count", 0)
    print(f"  ✅ 读取到 {row_count} 行, {len(columns)} 列")
    print(f"  📋 原始列名: {columns}")

    if not data or row_count == 0:
        print("  ⚠️ 源表无数据，迁移结束")
        return {"success": True, "migrated_rows": 0, "columns": [], "message": "源表无数据"}

    # 步骤3: 数据预处理
    print(f"\n📈 步骤3: 数据预处理 (共 {len(data)} 行)...")
    df = pd.DataFrame(data, columns=columns)

    # 自动翻译逻辑
    if auto_translate:
        print("\n  🌐 [自动翻译] 根据中文含义生成英文表名和列名...")
        if not target_table_name:
            target_table_name = _smart_translate(source_table_name)
            print(f"    📋 表名自动生成: '{source_table_name}' → '{target_table_name}'")
        if not table_remark:
            table_remark = source_table_name
            print(f"    📝 表备注: '{table_remark}'")
        for col in df.columns:
            if col not in column_mapping:
                en_name = _smart_translate(col)
                column_mapping[col] = en_name
                column_remarks[en_name] = col
                print(f"    📋 列名: '{col}' → '{en_name}'  (备注: {col})")

    if not target_table_name:
        target_table_name = source_table_name

    # 3.1 删除指定列
    if drop_columns:
        print(f"\n  🗑️  [3.1] 删除指定列...")
        existing_drop = [c for c in drop_columns if c in df.columns]
        if existing_drop:
            df = df.drop(columns=existing_drop)
            print(f"    ✅ 已删除: {existing_drop}")

    # 3.2 应用列转换
    if column_transforms:
        print(f"\n  🔧 [3.2] 应用列转换规则 ({len(column_transforms)} 条)...")
        for col, rule in column_transforms.items():
            df = apply_column_transform(df, col, rule)

    # 3.3 列名映射
    if column_mapping:
        print(f"\n  📝 [3.3] 应用列名映射 ({len(column_mapping)} 条)...")
        valid_mapping = {k: v for k, v in column_mapping.items() if k in df.columns}
        if valid_mapping:
            df = df.rename(columns=valid_mapping)
            print(f"    ✅ 列名映射完成")

    # 3.4 添加新列（自动添加"记录时间戳"列）
    print(f"\n  ➕ [3.4] 添加新列...")

    # === 修复点：自动添加"记录时间戳"列 ===
    # 检查是否已存在时间戳相关的列（中文名或英文名）
    _has_timestamp_col = any(
        "时间戳" in str(c) or "timestamp" in str(c).lower()
        for c in df.columns
    )
    if not _has_timestamp_col:
        # 如果用户 add_columns 中也没有指定时间戳列，自动添加
        _user_has_timestamp = any(
            "时间戳" in str(k) or "timestamp" in str(k).lower()
            for k in (add_columns or {}).keys()
        )
        if not _user_has_timestamp:
            if add_columns is None:
                add_columns = {}
            add_columns["记录时间戳"] = None
            print(f"    🕐 自动添加「记录时间戳」列")

    if add_columns:
        for col_name, col_value in add_columns.items():
            if col_name not in df.columns:
                # 如果列名包含"时间戳"/"timestamp"且值为 None 或空字符串，自动填充当前时间
                is_timestamp_col = (
                    "时间戳" in str(col_name) or
                    "timestamp" in str(col_name).lower()
                )
                if is_timestamp_col and (col_value is None or str(col_value).strip() == ""):
                    col_value = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
                df[col_name] = col_value
                print(f"    ✅ 已添加列: {col_name} = {col_value}")

    # 3.5 强制标识符规范化
    print(f"\n  🔒 [3.5] 标识符合法性检查...")
    if not _is_english_identifier(target_table_name):
        original_table_name = target_table_name
        target_table_name = _sanitize_identifier(target_table_name, "migrated_table")
        if not table_remark:
            table_remark = original_table_name
        print(f"    🔄 表名自动翻译: '{original_table_name}' → '{target_table_name}'")
        if table_remark:
            print(f"    📝 表备注: '{table_remark}'")
    else:
        print(f"    ✅ 目标表名 '{target_table_name}' 合法")

    col_rename_map = {}
    has_chinese_cols = False
    for col in df.columns:
        if not _is_english_identifier(col):
            has_chinese_cols = True
            en_col = _sanitize_identifier(col, "column")
            col_rename_map[col] = en_col
            if en_col not in column_remarks:
                column_remarks[en_col] = col
    if has_chinese_cols:
        df = df.rename(columns=col_rename_map)
        print(f"    🔄 部分列名已自动翻译:")
        for old, new in col_rename_map.items():
            print(f"       '{old}' → '{new}'  (备注: {old})")
    else:
        print(f"    ✅ 所有列名均为合法英文标识符")

    print(f"\n  📊 预处理完成: 最终列名: {list(df.columns)}")
    if column_remarks:
        print(f"  📝 列备注: {column_remarks}")

    # 步骤4: 写入目标数据源
    print(f"\n✏️  步骤4: 写入目标表 '{target_table_name}'...")
    write_extra_kwargs = {}
    if "table_remark" in write_supported_params and table_remark:
        write_extra_kwargs["table_remark"] = table_remark
    if "column_remarks" in write_supported_params and column_remarks:
        write_extra_kwargs["column_remarks"] = column_remarks
    if write_extra_kwargs:
        print(f"  📝 附加写入参数: {list(write_extra_kwargs.keys())}")

    def _write_records(records, t_name):
        total_written = 0
        for i in range(0, len(records), batch_size):
            batch_num = i // batch_size + 1
            batch = records[i:i + batch_size]
            print(f"  📦 批次 {batch_num}: 写入 {len(batch)} 行...")
            write_result = write_table_data(
                target_ds_id, t_name, records=batch, **write_extra_kwargs
            )
            if not write_result.get("success"):
                error_msg = write_result.get("error") or write_result.get("message", "未知错误")
                raise ValueError(f"写入目标表失败 (批次 {batch_num}): {error_msg}")
            batch_count = write_result.get("row_count", len(batch))
            total_written += batch_count
        return total_written

    # 准备写入数据
    df_write = df.copy()
    for col in df_write.columns:
        if pd.api.types.is_datetime64_any_dtype(df_write[col]):
            df_write[col] = df_write[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        elif df_write[col].dtype == 'object':
            mask = df_write[col].notna()
            df_write.loc[mask, col] = df_write.loc[mask, col].astype(str)
    df_write = df_write.where(pd.notna(df_write), None)
    records = df_write.to_dict(orient="records")

    try:
        total_written = _write_records(records, target_table_name)
    except Exception as e:
        err_str = str(e)
        # 检测是否为结构不兼容（如字段不存在），如果是则尝试自动创建新表写入
        if "不存在" in err_str or "does not exist" in err_str.lower() or "no such column" in err_str.lower():
            print(f"  ⚠️ 写入失败: {e}")
            print(f"  💡 可能是目标表已存在且结构不兼容。尝试使用新表名自动创建并写入...")
            target_table_name = f"{target_table_name}_{int(time.time())}"
            print(f"  🔄 新表名: '{target_table_name}'")
            total_written = _write_records(records, target_table_name)
        else:
            print(f"  ⚠️ 首次写入失败: {e}")
            print(f"  🔄 尝试将所有数据转为字符串后重试...")
            df_str = df.copy()
            for col in df_str.columns:
                if pd.api.types.is_datetime64_any_dtype(df_str[col]):
                    df_str[col] = df_str[col].dt.strftime('%Y-%m-%d %H:%M:%S')
                mask = df_str[col].notna()
                df_str.loc[mask, col] = df_str.loc[mask, col].astype(str)
            df_str = df_str.where(pd.notna(df_str), None)
            records_str = df_str.to_dict(orient="records")
            total_written = _write_records(records_str, target_table_name)

    print(f"\n🎉 迁移完成! 共写入 {total_written} 行")
    return {
        "success": True,
        "migrated_rows": total_written,
        "columns": list(df.columns),
        "target_table": target_table_name,
        "table_remark": table_remark,
        "column_remarks": column_remarks
    }


# ============================================================
# 自测逻辑与入口
# ============================================================

def _test_column_transform():
    """测试列转换函数的正确性"""
    print("=" * 60)
    print("🧪 自测：列转换逻辑验证")
    print("=" * 60)
    test_df = pd.DataFrame({"name": ["  Alice  ", None]})
    test_df = apply_column_transform(test_df, "name", {"type": "trim"})
    assert test_df["name"].iloc[0] == "Alice"
    assert pd.isna(test_df["name"].iloc[1])
    print("  ✅ trim 测试通过\n")

    print("🧪 自测：智能翻译验证")
    tests = [
        ("全国重点文物保护单位", "national_key_cultural_relic_protection_units"),
        ("名称", "name"),
        ("编号", "code"),
        ("文物类型", "relic_type"),
        ("年度", "year"),
        ("记录时间戳", "record_timestamp"),
    ]
    for cn, expected in tests:
        result = _smart_translate(cn)
        status = "✅" if result == expected else "⚠️"
        print(f"  {status} '{cn}' → '{result}' (期望: '{expected}')")
    print()

    print("🧪 自测：标识符规范化验证")
    id_tests = [
        ("年度", True, "year"),
        ("name", False, "name"),
        ("文物名称", True, "relic_name"),
        ("123abc", True, "_123abc"),
    ]
    for name, should_change, expected in id_tests:
        is_valid = _is_english_identifier(name)
        sanitized = _sanitize_identifier(name)
        status = "✅" if sanitized == expected else "⚠️"
        print(f"  {status} '{name}' → valid={is_valid}, sanitized='{sanitized}' (期望: '{expected}')")
    print()
    return True


def main(**kwargs):
    """
    主入口函数。
    系统会注入用户参数，直接传递给 migrate_data 执行迁移。
    如果无参数，则运行自测。
    """
    print(f"\n{'=' * 60}")
    print(f"📥 main() 被调用，收到参数: {kwargs}")
    print(f"{'=' * 60}\n")

    try:
        # 如果有业务参数，执行数据迁移
        has_migration_params = any(
            kwargs.get(k) for k in [
                'source_datasource_name', 'source_table_name', 'target_datasource_name',
                'datasource', 'table_name', 'source_datasource', 'target_datasource'
            ]
        )

        if has_migration_params:
            print("🚀 检测到迁移参数，开始执行数据迁移...")
            return migrate_data(**kwargs)
        else:
            # 无参数时运行自测
            print("🧪 无迁移参数，运行自测验证...")
            _test_column_transform()
            return {"success": True, "message": "自测通过"}

    except Exception as e:
        print(f"\n❌❌❌ 执行失败 ❌❌❌")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        print(f"\n完整堆栈:")
        print(traceback.format_exc())
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


if __name__ == "__main__":
    main()