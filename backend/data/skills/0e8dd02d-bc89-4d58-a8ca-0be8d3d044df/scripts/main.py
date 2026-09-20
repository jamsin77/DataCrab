import re
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# 本脚本兼容当前环境中的真实数据源：
# 文物列表(excel)、文物库(postgresql)、交易数据(excel)、凭证库(generic_file)、
# 凭证检索库(postgresql)、培训视频(generic_file)、培训知识库(chroma)、
# 聊天上传数据(generic_file: 交易数据_20260904_080023.png,
# 交易数据_验证_20260908_20260909_015320.xlsx, WPS表格工作表_20260915_081545.xls)
# 所有数据源均通过 call_tool("list_user_datasources", by_name=...) 动态解析，不硬编码 ID。

CHINESE_CHAR_RE = re.compile(r'[\u4e00-\u9fff]')
NON_LANGUAGE_RE = re.compile(r'^[\d\s\-–—:：.,，。%￥$€£<>\[\]()（）/\\|@#&*+=\'"]+$')


def _resolve_datasource_id(datasource_name: str) -> str:
    """根据数据源名称解析数据源 ID"""
    ds = call_tool("list_user_datasources", by_name=datasource_name)
    if not ds or not ds.get("id"):
        raise ValueError(f"找不到数据源: {datasource_name}")
    ds_id = ds["id"]
    print(f"[数据源] 已定位: {datasource_name} (ID: {ds_id})")
    return ds_id


def _load_source_data(datasource_id: str, table_name: str) -> pd.DataFrame:
    """分页读取源表全量数据，首选 iter_table_data，失败时回退 query_table_data"""
    print(f"[读取] 开始读取 {table_name} 全量数据...")
    all_rows = []
    columns = None
    page = 1
    page_size = 10000

    while True:
        result = call_tool(
            "iter_table_data",
            datasource_id=datasource_id,
            table_name=table_name,
            page=page,
            page_size=page_size,
        )
        # iter_table_data 返回 {"columns": [...], "rows": [...], "page": int, "total": int, "has_next": bool}
        if not result.get("columns"):
            if page == 1:
                return _load_source_data_by_query(datasource_id, table_name)
            break

        if columns is None:
            columns = result["columns"]

        rows = result.get("rows") or []
        all_rows.extend(rows)
        total = result.get("total", len(all_rows))
        print(f"[读取] 第 {page} 页完成: +{len(rows)} 行，累计 {len(all_rows)}/{total}")

        if not result.get("has_next", False) or not rows:
            break
        page += 1

    if columns is None:
        raise RuntimeError(f"读取 {table_name} 失败：未获取到列信息")

    df = pd.DataFrame(all_rows, columns=columns)
    print(f"[读取] 完成: 共 {len(df)} 行")
    return df


def _load_source_data_by_query(datasource_id: str, table_name: str) -> pd.DataFrame:
    """回退方案：用 query_table_data 读取（适用于小表或不支持分页的数据源）"""
    print(f"[读取] iter_table_data 不可用，改用 query_table_data ...")
    result = call_tool(
        "query_table_data",
        datasource_id=datasource_id,
        table_name=table_name,
        limit=50000,
    )
    if not result.get("success"):
        raise RuntimeError(f"读取 {table_name} 失败: {result.get('message')}")

    df = pd.DataFrame(result.get("data") or [], columns=result.get("columns") or [])
    if df.empty and not result.get("columns"):
        raise RuntimeError(f"读取 {table_name} 失败：无数据且无列信息")
    print(f"[读取] 完成: 共 {len(df)} 行")
    return df


def _needs_translation(text: Any) -> bool:
    """判断文本是否需要翻译成中文：不含中文且不是纯数字/符号的自然语言文本"""
    if not isinstance(text, str):
        return False
    text = text.strip()
    if not text:
        return False
    if CHINESE_CHAR_RE.search(text):
        return False  # 含中文，视为中文数据，保留
    if NON_LANGUAGE_RE.fullmatch(text):
        return False  # 纯数字/标点/符号，不是自然语言
    return True


def _translate_text(text: str) -> str:
    """调用 LLM 翻译单条文本"""
    resp = call_tool(
        "llm_generate",
        prompt=f"请将以下文本翻译成简体中文，只输出翻译结果，不要加解释：\n{text}",
        system_prompt="你是专业翻译助手，精通多语言到中文的翻译。",
        temperature=0.3,
        max_tokens=2000,
    )
    content = (resp.get("content") or "").strip()
    if not content:
        raise RuntimeError(f"翻译返回空内容: {text[:50]}")
    return content


def _translate_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """对 DataFrame 非中文文本列进行翻译，其他内容保持原样，返回 (df, 翻译单元格数)"""
    if df.empty:
        return df, 0

    print("[翻译] 开始检测非中文文本...")
    object_cols = [c for c in df.columns if df[c].dtype == object]
    if not object_cols:
        print("[翻译] 无文本列，跳过翻译")
        return df, 0

    # 收集需要翻译的唯一值（去重以提高效率）
    to_translate = []
    for col in object_cols:
        for v in df[col]:
            if isinstance(v, str) and _needs_translation(v):
                to_translate.append(v)

    unique_values = list(dict.fromkeys(to_translate))
    if not unique_values:
        print("[翻译] 检测完成: 无需翻译的非中文文本")
        return df, 0

    print(f"[翻译] 检测到 {len(unique_values)} 个唯一非中文文本，开始翻译...")
    translation_map = {}
    fail_count = 0

    if len(unique_values) <= 3:
        # 少量文本直接串行翻译
        for i, v in enumerate(unique_values, 1):
            print(f"[翻译] 正在翻译 {i}/{len(unique_values)}: {v[:60]}...")
            try:
                translation_map[v] = _translate_text(v)
            except Exception as e:
                fail_count += 1
                log("warn", f"翻译失败: {v[:60]} - {e}")
                translation_map[v] = v  # 保留原文
    else:
        # 批量并发翻译，控制并发为 4，避免限流
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_translate_text, v): v for v in unique_values}
            done = 0
            for fut in as_completed(futures):
                v = futures[fut]
                done += 1
                try:
                    translation_map[v] = fut.result()
                except Exception as e:
                    fail_count += 1
                    log("warn", f"翻译失败: {v[:60]} - {e}")
                    translation_map[v] = v  # 保留原文
                if done % 10 == 0 or done == len(unique_values):
                    print(f"[翻译] 进度: {done}/{len(unique_values)}，失败 {fail_count}")

    if fail_count == len(unique_values):
        raise RuntimeError(f"全部 {len(unique_values)} 个文本翻译失败，可能 LLM 未配置或网络异常")

    # 回填翻译结果，统计实际翻译单元格数
    translated_cells = 0
    for col in object_cols:
        mask = df[col].apply(lambda v: isinstance(v, str) and v in translation_map)
        translated_cells += int(mask.sum())
        df[col] = df[col].apply(
            lambda v: translation_map.get(v, v) if isinstance(v, str) and v in translation_map else v
        )

    print(f"[翻译] 完成: 翻译了 {len(translation_map)} 个唯一文本，回填 {translated_cells} 个单元格")
    return df, translated_cells


def _write_data(
    df: pd.DataFrame,
    target_ds_id: str,
    target_table: str,
    if_table_exists: str,
    batch_size: int,
) -> int:
    """分批写入数据，返回写入行数"""
    records = df.to_dict(orient="records")
    total = len(records)
    if total == 0:
        print("[写入] 无数据，跳过写入")
        return 0

    print(f"[写入] 开始写入 {total} 行到 {target_table}（策略: {if_table_exists}，批次: {batch_size}）...")
    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    written = 0

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        # 第一批用原策略（如 replace/overwrite 清空重建），后续批次追加
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"

        result = call_tool(
            "write_table_data",
            datasource_id=target_ds_id,
            table_name=target_table,
            records=batch,
            if_table_exists=current_strategy,
        )
        if not result.get("success"):
            raise RuntimeError(f"写入失败: {result.get('message')}")

        written += result.get("rows_written", len(batch))
        print(f"[写入] 第 {batch_num} 批完成: +{len(batch)} 行，累计 {written}/{total}")

    print(f"[写入] 完成: 共写入 {written} 行")
    return written


def migrate_data(
    source_datasource_name: str,
    source_table_name: str,
    target_datasource_name: str,
    target_table_name: Optional[str] = None,
    translate_non_chinese: bool = True,
    if_table_exists: str = "replace",
    batch_size: int = 1000,
) -> Dict[str, Any]:
    """主业务函数：从源数据源迁移数据到目标数据源，非中文文本自动翻译成中文"""
    # 1. 解析数据源 ID
    source_ds_id = _resolve_datasource_id(source_datasource_name)
    target_ds_id = _resolve_datasource_id(target_datasource_name)
    target_table = target_table_name or source_table_name
    print(f"[迁移] 源: {source_datasource_name}.{source_table_name} → 目标: {target_datasource_name}.{target_table}")

    # 2. 加载源数据
    df = _load_source_data(source_ds_id, source_table_name)

    # 3. 翻译非中文文本（如启用）
    translated_cells = 0
    if translate_non_chinese:
        df, translated_cells = _translate_dataframe(df)

    # 4. 写入目标
    written = _write_data(df, target_ds_id, target_table, if_table_exists, batch_size)

    # 5. 返回结果
    return {
        "success": True,
        "migrated_rows": written,
        "translated_cells": translated_cells,
        "columns": list(df.columns),
        "source_table": source_table_name,
        "source_datasource": source_datasource_name,
        "target_table": target_table,
        "target_datasource": target_datasource_name,
    }


def main(**kwargs):
    """主入口，兼容参数别名，系统注入用户参数"""
    param_map = {
        "source_datasource_name": ["source_datasource_name", "source_datasource", "source_datasource_id", "datasource_name"],
        "source_table_name": ["source_table_name", "source_table", "table_name"],
        "target_datasource_name": ["target_datasource_name", "target_datasource", "target_datasource_id", "target_ds"],
        "target_table_name": ["target_table_name", "target_table"],
        "translate_non_chinese": ["translate_non_chinese", "translate"],
        "if_table_exists": ["if_table_exists", "write_strategy"],
        "batch_size": ["batch_size"],
    }

    params = {}
    for standard, aliases in param_map.items():
        for alias in aliases:
            if alias in kwargs and kwargs[alias] is not None:
                params[standard] = kwargs[alias]
                break

    params.setdefault("target_table_name", None)
    params.setdefault("translate_non_chinese", True)
    params.setdefault("if_table_exists", "replace")
    params.setdefault("batch_size", 1000)

    return migrate_data(**params)