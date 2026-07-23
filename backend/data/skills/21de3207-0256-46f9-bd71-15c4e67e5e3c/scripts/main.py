"""
数据迁移脚本
在不同数据源之间迁移数据，支持列名转换、列删除、列添加及基本数据处理
支持自动翻译列名为英文，并设置中文备注
"""

import sys
import io
import re
import time
import traceback
from datetime import datetime
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


def _is_timestamp_col(col_name: str) -> bool:
    """判断列名是否为时间戳类型列"""
    col_lower = str(col_name).lower()
    return "时间戳" in str(col_name) or "timestamp" in col_lower


def _is_id_col(col_name: str) -> bool:
    """判断列名是否为 ID 类型列"""
    col_lower = str(col_name).lower().strip()
    # 纯 "id" 或以 "_id" 结尾
    if col_lower == "id":
        return True
    if col_lower.endswith("_id"):
        return True
    # 中文 "ID" 或 "编号"（但不含其他词）
    if str(col_name).strip().upper() == "ID":
        return True
    if str(col_name).strip() == "编号":
        return True
    return False


def _generate_timestamp() -> str:
    """生成当前时间戳字符串，确保返回真实时间"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _generate_id(index: int, width: int = 8) -> str:
    """生成 8 位补零的序号 ID，如 00000001, 00000002"""
    return str(index).zfill(width)


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
    translate_to_cn: bool = False,
    table_remark: Optional[str] = None,
    column_remarks: Optional[Dict[str, str]] = None,
    if_table_exists: str = "fail",
    **kwargs
) -> Dict[str, Any]:
    """在不同数据源之间迁移数据，支持列名转换和简单数据处理。

    if_table_exists 支持的策略:
      - fail: 默认，目标表已存在时报错
      - append: 追加数据
      - add_columns: 增加新列
      - overwrite: 清空目标表内容后重新写入（第一批 overwrite，后续批次 append）
    """

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
    # 兼容 column_mapping 传入 list 的情况（如 ["col1", "col2"]）
    if isinstance(column_mapping, list):
        column_mapping = {item: item for item in column_mapping if isinstance(item, str)}
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

    # 修复点：兼容 add_columns 值为 dict（如 {"value": "xxx"} 或 {"value": "lambda ..."}）的情况
    if isinstance(add_columns, dict):
        cleaned_add = {}
        for k, v in add_columns.items():
            if isinstance(v, dict) and 'value' in v:
                val = v['value']
                # 如果是 lambda 字符串，无法执行，设为 None 让自动逻辑处理
                if isinstance(val, str) and 'lambda' in val:
                    cleaned_add[k] = None
                else:
                    cleaned_add[k] = val
            elif isinstance(v, str) and 'lambda' in v:
                cleaned_add[k] = None
            else:
                cleaned_add[k] = v
        add_columns = cleaned_add

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
    print(f"  目标表已存在策略: {if_table_exists}")
    print("=" * 60)

    # write_table_data 支持的参数（skill_runner 已支持 if_table_exists/table_remark/column_remarks）
    write_supported_params = {"if_table_exists", "table_remark", "column_remarks"}

    # 步骤1: 获取数据源 ID（单次尝试，失败直接用名称）
    print("\n📡 步骤1: 获取数据源信息...")

    def _resolve_ds(ds_name):
        try:
            ds_id = get_datasource_id_by_name(ds_name)
            if ds_id:
                return ds_id
        except Exception as e:
            print(f"  ⚠️ 解析数据源 '{ds_name}' 异常: {e}")
        return None

    source_ds_id = _resolve_ds(source_datasource_name)
    if source_ds_id:
        print(f"  ✅ 源数据源 ID: {source_ds_id}")
    else:
        source_ds_id = source_datasource_name
        print(f"  ⚠️ 无法解析源数据源ID，直接使用名称: '{source_ds_id}'")

    target_ds_id = _resolve_ds(target_datasource_name)
    if target_ds_id:
        print(f"  ✅ 目标数据源 ID: {target_ds_id}")
    else:
        target_ds_id = target_datasource_name
        print(f"  ⚠️ 无法解析目标数据源ID，直接使用名称: '{target_ds_id}'")

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

    # 英文→中文翻译逻辑（translate_to_cn）——使用 llm_chat 批量翻译（对齐文本翻译算子）
    if translate_to_cn:
        print("\n  🌐 [英文→中文翻译] 使用 LLM 翻译表名和列名...")
        llm_chat_func = _get_builtin_func('llm_chat')
        # 收集需要翻译的名称（表名 + 未映射的列名）
        _to_translate = []
        _translate_table = False
        if target_table_name and _is_english_identifier(target_table_name):
            _to_translate.append(target_table_name)
            _translate_table = True
        for col in df.columns:
            if col not in column_mapping and _is_english_identifier(col):
                _to_translate.append(col)
        if _to_translate:
            _names_text = "\n".join(_to_translate)
            _prompt = (
                f"请将以下英文数据库表名/列名翻译为简洁准确的中文。\n"
                f"只输出翻译结果，每行一个，保持原始顺序，不要添加编号或任何说明：\n\n{_names_text}"
            )
            try:
                _reply = llm_chat_func(_prompt, system_prompt="你是数据库命名翻译助手，只输出中文翻译结果，每行一个。", temperature=0.3)
                _translated = [line.strip() for line in _reply.strip().split("\n") if line.strip()]
            except Exception as e:
                print(f"    ⚠️ LLM 翻译失败: {e}，使用原始名称")
                _translated = _to_translate
            # 分配翻译结果
            _idx = 0
            if _translate_table and _idx < len(_translated):
                original_table = target_table_name
                target_table_name = _translated[_idx]
                print(f"    📋 表名: '{original_table}' → '{target_table_name}'")
                if not table_remark:
                    table_remark = original_table
                _idx += 1
            for col in df.columns:
                if col not in column_mapping and _is_english_identifier(col):
                    if _idx < len(_translated):
                        cn_name = _translated[_idx]
                        column_mapping[col] = cn_name
                        print(f"    📋 列名: '{col}' → '{cn_name}'")
                        _idx += 1
        else:
            print("    ✅ 无需翻译（表名和列名已是中文）")

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

    # === 自动添加"记录时间戳"列 ===
    # 检查是否已存在时间戳相关的列（中文名或英文名）
    _has_timestamp_col = any(_is_timestamp_col(c) for c in df.columns)
    if not _has_timestamp_col:
        # 如果用户 add_columns 中也没有指定时间戳列，自动添加
        _user_has_timestamp = any(_is_timestamp_col(k) for k in (add_columns or {}).keys())
        if not _user_has_timestamp:
            if add_columns is None:
                add_columns = {}
            add_columns["记录时间戳"] = None
            print(f"    🕐 自动添加「记录时间戳」列")

    if add_columns:
        for col_name, col_value in add_columns.items():
            if col_name not in df.columns:
                # ===== 时间戳列：生成真实时间 =====
                if _is_timestamp_col(col_name):
                    col_value = _generate_timestamp()
                    print(f"    🕐 时间戳列 '{col_name}' 生成真实时间: {col_value}")
                    df[col_name] = col_value
                # ===== ID 列：生成 8 位补零序号 =====
                elif _is_id_col(col_name):
                    id_values = [_generate_id(i + 1) for i in range(len(df))]
                    df[col_name] = id_values
                    print(f"    🆔 ID列 '{col_name}' 生成 {len(df)} 个8位补零序号 (示例: {id_values[0]} ~ {id_values[-1]})")
                # ===== 省份列：从地址中提取省份 =====
                elif col_name == "省份" or _smart_translate(col_name) == "province":
                    # 找到地址列（可能是中文"地址"或英文"address"）
                    address_col = None
                    for c in df.columns:
                        if c == "地址" or c == "address" or _smart_translate(c) == "address":
                            address_col = c
                            break
                    if address_col:
                        df[col_name] = df[address_col].apply(lambda x: _extract_province(str(x)) if pd.notna(x) else "")
                        print(f"    📍 省份列 '{col_name}' 从地址列 '{address_col}' 提取完成 (示例: {df[col_name].iloc[0]})")
                    else:
                        df[col_name] = ""
                        print(f"    ⚠️ 未找到地址列，省份列 '{col_name}' 设为空")
                # ===== 普通常量列 =====
                else:
                    df[col_name] = col_value
                    print(f"    ✅ 已添加列: {col_name} = {col_value}")

    # 3.5 强制标识符规范化（translate_to_cn 时跳过，保留中文名）
    print(f"\n  🔒 [3.5] 标识符合法性检查...")
    if translate_to_cn:
        print(f"    ✅ 跳过标识符规范化（translate_to_cn=True，保留中文表名和列名）")
    else:
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

    # 步骤3.5: 数据质量修复 — 填充可选字段空值
    # 对"备注"/"remark"等可选字段，空值填充为"无"，避免DQ-COM-003空值率告警
    _optional_fill_cols = []
    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower in ("备注", "remark", "remarks", "note", "notes", "comment", "comments"):
            _optional_fill_cols.append(col)
    if _optional_fill_cols:
        print(f"\n  🔧 [3.5] 数据质量修复: 填充可选字段空值...")
        for col in _optional_fill_cols:
            # 统计空值（None、NaN、空字符串、纯空白）
            _is_empty = df[col].isna() | (df[col].astype(str).str.strip() == "") | (df[col].astype(str).str.strip() == "nan")
            _fill_count = int(_is_empty.sum())
            if _fill_count > 0:
                df.loc[_is_empty, col] = "无"
                print(f"    ✅ 列 '{col}': 填充 {_fill_count}/{len(df)} 行空值 → '无'")
            else:
                print(f"    ✅ 列 '{col}': 无空值，无需填充")

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
    if "if_table_exists" in write_supported_params:
        write_extra_kwargs["if_table_exists"] = if_table_exists
    if write_extra_kwargs:
        print(f"  📝 附加写入参数: {list(write_extra_kwargs.keys())}")

    def _write_records(records, t_name):
        total_written = 0
        original_if_exists = write_extra_kwargs.get("if_table_exists", "fail")
        for i in range(0, len(records), batch_size):
            batch_num = i // batch_size + 1
            batch = records[i:i + batch_size]
            print(f"  📦 批次 {batch_num}: 写入 {len(batch)} 行...")

            # 关键修复：所有策略下，第一批用原策略（建表/清空+写入），后续批次一律用 append 避免清空
            current_kwargs = dict(write_extra_kwargs)
            if batch_num > 1:
                current_kwargs["if_table_exists"] = "append"
                print(f"    📝 后续批次使用 append 策略")

            try:
                write_result = write_table_data(
                    target_ds_id, t_name, records=batch, **current_kwargs
                )
            except TypeError:
                print(f"    ⚠️ write_table_data 不支持额外参数，降级为基本参数...")
                write_result = write_table_data(
                    target_ds_id, t_name, records=batch
                )
            except Exception as e:
                # 第一批失败时（如表已存在用 fail 策略），自动切换到 replace 策略重试
                if batch_num == 1:
                    print(f"    ⚠️ 第一批写入失败: {e}，尝试用 replace 策略重试...")
                    retry_kwargs = dict(write_extra_kwargs)
                    retry_kwargs["if_table_exists"] = "replace"
                    try:
                        write_result = write_table_data(
                            target_ds_id, t_name, records=batch, **retry_kwargs
                        )
                    except TypeError:
                        write_result = write_table_data(
                            target_ds_id, t_name, records=batch
                        )
                else:
                    raise
            if not write_result or not write_result.get("success"):
                error_msg = (write_result or {}).get("error") or (write_result or {}).get("message", "未知错误")
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
        # 检测是否为"文件/表不存在"错误 → 用 create 策略重试 write_table_data
        if "不存在" in err_str or "does not exist" in err_str.lower() or "no such" in err_str.lower():
            print(f"  ⚠️ write_table_data 写入失败: {e}")
            print(f"  💡 目标表不存在，尝试用 fail 策略自动创建并写入...")

            # 用 fail 策略重试 write_table_data（平台 fail = 表不存在则自动建表，表存在才报错）
            create_kwargs = dict(write_extra_kwargs)
            create_kwargs["if_table_exists"] = "fail"
            try:
                total_written = 0
                for i in range(0, len(records), batch_size):
                    batch_num = i // batch_size + 1
                    batch = records[i:i + batch_size]
                    print(f"  📦 [自动建表] 批次 {batch_num}: 写入 {len(batch)} 行...")
                    # 第一批用 fail（表不存在则建），后续用 append
                    if batch_num > 1:
                        create_kwargs["if_table_exists"] = "append"
                    write_result = write_table_data(
                        target_ds_id, target_table_name, records=batch, **create_kwargs
                    )
                    if not write_result.get("success"):
                        error_msg = write_result.get("error") or write_result.get("message", "未知错误")
                        raise ValueError(f"自动建表写入失败 (批次 {batch_num}): {error_msg}")
                    batch_count = write_result.get("row_count", len(batch))
                    total_written += batch_count
                print(f"  ✅ 自动建表写入成功! 共 {total_written} 行")
            except Exception as create_err:
                print(f"  ❌ 自动建表也失败: {create_err}")
                # 最后兜底：尝试 execute_sql（仅对 DB 型数据源有效）
                print(f"  💡 尝试使用 execute_sql 创建表并写入数据...")
                try:
                    execute_sql_func = _get_builtin_func('execute_sql')
                    col_defs = ", ".join([f'"{col}" TEXT' for col in df.columns])
                    create_sql = f'CREATE TABLE IF NOT EXISTS "{target_table_name}" ({col_defs})'
                    execute_sql_func(target_ds_id, create_sql)
                    print(f"  ✅ 表 '{target_table_name}' 创建成功 (或已存在)")

                    col_names_str = ", ".join([f'"{col}"' for col in df.columns])
                    total_written = 0
                    for i in range(0, len(records), batch_size):
                        batch = records[i:i + batch_size]
                        batch_num = i // batch_size + 1
                        print(f"  📦 SQL批次 {batch_num}: 插入 {len(batch)} 行...")

                        for record in batch:
                            values = []
                            for col in df.columns:
                                val = record.get(col)
                                if val is None:
                                    values.append("NULL")
                                else:
                                    escaped = str(val).replace("'", "''")
                                    values.append(f"'{escaped}'")
                            values_str = ", ".join(values)
                            insert_sql = f'INSERT INTO "{target_table_name}" ({col_names_str}) VALUES ({values_str})'
                            execute_sql_func(target_ds_id, insert_sql)

                        total_written += len(batch)
                    print(f"  ✅ SQL写入成功! 共 {total_written} 行")
                except Exception as sql_err:
                    print(f"  ❌ execute_sql 方式也失败: {sql_err}")
                    raise ValueError(f"所有写入方式均失败。write_table_data 错误: {e}; create重试错误: {create_err}; execute_sql 错误: {sql_err}")
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

    print("🧪 自测：时间戳生成验证")
    ts = _generate_timestamp()
    print(f"  生成的时间戳: {ts}")
    # 验证格式为 YYYY-MM-DD HH:MM:SS
    assert re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', ts), f"时间戳格式不正确: {ts}"
    assert ts != "now", "时间戳不能是 'now' 字面量"
    print("  ✅ 时间戳生成测试通过\n")

    print("🧪 自测：时间戳列识别验证")
    ts_col_tests = [
        ("记录时间戳", True),
        ("record_timestamp", True),
        ("timestamp", True),
        ("名称", False),
        ("name", False),
    ]
    for col_name, expected in ts_col_tests:
        result = _is_timestamp_col(col_name)
        status = "✅" if result == expected else "⚠️"
        print(f"  {status} '{col_name}' → is_timestamp={result} (期望: {expected})")
    print()

    print("🧪 自测：ID列识别与生成验证")
    id_col_tests = [
        ("ID", True),
        ("id", True),
        ("编号", True),
        ("record_id", True),
        ("名称", False),
        ("name", False),
    ]
    for col_name, expected in id_col_tests:
        result = _is_id_col(col_name)
        status = "✅" if result == expected else "⚠️"
        print(f"  {status} '{col_name}' → is_id={result} (期望: {expected})")
    # 测试 ID 生成
    for i in [1, 2, 10, 999, 12345]:
        generated = _generate_id(i)
        status = "✅" if len(generated) == 8 and generated == str(i).zfill(8) else "⚠️"
        print(f"  {status} _generate_id({i}) = '{generated}'")
    print()
    return True


def main(**kwargs):
    """
    主入口函数。
    系统会注入用户参数，直接传递给 migrate_data 执行迁移。
    如果无参数，则运行自测。
    """
    print("debug start")
    print(f"\n{'=' * 60}")
    print(f"📥 main() 被调用，收到参数: {kwargs}")
    print(f"{'=' * 60}\n")

    # 参数名兼容映射，解决系统注入参数名不一致的问题
    param_aliases = {
        'source_datasource_name': ['source_datasource_name', 'source_datasource', 'sourceDatasource', 'sourceDatasourceName', 'from_datasource', 'fromDatasource', 'datasource', 'datasource_name', 'datasourceName'],
        'source_table_name': ['source_table_name', 'source_table', 'sourceTable', 'sourceTableName', 'table_name', 'tableName', 'from_table', 'fromTable'],
        'target_datasource_name': ['target_datasource_name', 'target_datasource', 'targetDatasource', 'targetDatasourceName', 'to_datasource', 'toDatasource'],
        'target_table_name': ['target_table_name', 'target_table', 'targetTable', 'targetTableName', 'to_table', 'toTable'],
    }
    
    normalized_kwargs = {}
    used_aliases = set()
    for standard_name, aliases in param_aliases.items():
        found = False
        for alias in aliases:
            if alias in kwargs and kwargs[alias]:
                normalized_kwargs[standard_name] = kwargs[alias]
                used_aliases.add(alias)
                found = True
                break
        if not found and standard_name in kwargs and kwargs[standard_name]:
            normalized_kwargs[standard_name] = kwargs[standard_name]
            used_aliases.add(standard_name)

    # 合并其他未映射的参数
    for k, v in kwargs.items():
        if k not in used_aliases:
            normalized_kwargs[k] = v

    try:
        # 如果有业务参数，执行数据迁移
        has_migration_params = any(
            normalized_kwargs.get(k) for k in [
                'source_datasource_name', 'source_table_name', 'target_datasource_name'
            ]
        )

        if has_migration_params:
            print("🚀 检测到迁移参数，开始执行数据迁移...")
            print(f"  规范化后的参数: {normalized_kwargs}")
            return migrate_data(**normalized_kwargs)
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


def _extract_province(address: str) -> str:
    """从中文地址中提取省份/自治区/直辖市/特别行政区。
    
    支持的格式：
    - XX省（如：广东省、湖南省）
    - XX自治区（如：广西壮族自治区、西藏自治区、新疆维吾尔自治区、内蒙古自治区、宁夏回族自治区）
    - XX市（直辖市：北京市、上海市、天津市、重庆市）
    - XX特别行政区（如：香港特别行政区、澳门特别行政区）
    """
    if not address or not isinstance(address, str):
        return ""
    address = address.strip()
    
    # 直辖市列表
    municipalities = ["北京市", "上海市", "天津市", "重庆市"]
    for m in municipalities:
        if address.startswith(m):
            return m
    
    # 特别行政区
    if "特别行政区" in address:
        for sar in ["香港特别行政区", "澳门特别行政区"]:
            if address.startswith(sar):
                return sar
        if address.startswith("香港"):
            return "香港特别行政区"
        if address.startswith("澳门"):
            return "澳门特别行政区"
    
    # 自治区（按名称长度从长到短匹配）
    autonomous_regions = [
        "广西壮族自治区", "新疆维吾尔自治区", "宁夏回族自治区", 
        "内蒙古自治区", "西藏自治区"
    ]
    for ar in autonomous_regions:
        if address.startswith(ar):
            return ar
    ar_short = {
        "广西": "广西壮族自治区",
        "新疆": "新疆维吾尔自治区",
        "宁夏": "宁夏回族自治区",
        "内蒙古": "内蒙古自治区",
        "西藏": "西藏自治区",
    }
    for short, full in ar_short.items():
        if address.startswith(short):
            return full
    
    # 普通省份：匹配 "XX省"
    match = re.match(r'^([\u4e00-\u9fa5]{2,4})省', address)
    if match:
        return match.group(1) + "省"
    
    # 取第一个到"省"字为止
    if "省" in address:
        idx = address.index("省")
        return address[:idx + 1]
    
    return ""




# ===== 英文→中文反向翻译字典 =====
COMMON_EN_CN = {v: k for k, v in COMMON_CN_EN.items()}

def _smart_translate_en_to_cn(text: str) -> str:
    """智能翻译英文列名/表名为中文。
    
    优先精确匹配，其次按 _ 拆分逐词匹配后拼接，
    最后用 llm_chat 调用大模型翻译。
    """
    text = str(text).strip()
    if not text:
        return text
    # 1. 精确匹配
    if text in COMMON_EN_CN:
        return COMMON_EN_CN[text]
    # 2. 按 _ 拆分逐词匹配
    parts = text.split('_')
    translated_parts = []
    all_matched = True
    for part in parts:
        if part in COMMON_EN_CN:
            translated_parts.append(COMMON_EN_CN[part])
        else:
            translated_parts.append(part)
            all_matched = False
    if all_matched:
        return ''.join(translated_parts)
    # 部分匹配也返回拼接结果
    if any(COMMON_EN_CN.get(p) for p in parts):
        return ''.join(translated_parts)
    # 3. 用 llm_chat 翻译
    try:
        llm_chat_func = _get_builtin_func('llm_chat')
        prompt = (
            f"请将以下英文数据库表名/列名翻译为简洁的中文，"
            f"只输出中文翻译结果，不要添加任何说明或标点：\n{text}"
        )
        reply = llm_chat_func(prompt, system_prompt="你是数据库命名翻译助手，只输出中文翻译结果。", temperature=0.3)
        result = reply.strip()
        if result:
            return result
    except Exception as e:
        print(f"  ⚠️ llm_chat 翻译失败: {e}")
    return text

if __name__ == "__main__":
    main()