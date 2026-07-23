"""DataInspector 数据检查智能体 - 检查工具实现"""

from __future__ import annotations

import re
import uuid as _uuid
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.models.datasource import DataSource
from app.services.connectors import get_connector


class DataInspectorTools:
    async def _load_data(self, datasource_id: str, table_name: str, db: AsyncSession, page_size: int = 5000) -> pd.DataFrame:
        result = await db.execute(
            select(DataSource).where(DataSource.id == _uuid.UUID(datasource_id))
        )
        datasource = result.scalar_one_or_none()
        if not datasource:
            raise ValueError(f"数据源不存在: {datasource_id}")

        connector = get_connector(datasource.type, datasource.connection_config or {})
        try:
            df = await connector.get_table_data(table_name, page=1, page_size=page_size)
            return df
        except Exception as e:
            err_msg = str(e)
            if "不存在" in err_msg or "does not exist" in err_msg or "no such table" in err_msg.lower():
                resolved = await self._resolve_table_name(connector, table_name)
                if resolved and resolved != table_name:
                    logger.info(f"Inspector 表名模糊匹配: '{table_name}' -> '{resolved}'")
                    df = await connector.get_table_data(resolved, page=1, page_size=page_size)
                    return df
            raise
        finally:
            await connector.close()

    async def _resolve_table_name(self, connector, table_name: str) -> str:
        """当目标表名不存在时，从数据源的所有表中查找最相似的表名"""
        try:
            schema = await connector.get_schema()
            all_tables = [t.get("table_name", "") for t in (schema or []) if t.get("table_name")]
            if not all_tables:
                return ""
            for t in all_tables:
                if t.lower() == table_name.lower():
                    return t
            candidates = []
            target_lower = table_name.lower()
            for t in all_tables:
                t_lower = t.lower()
                if target_lower in t_lower or t_lower in target_lower:
                    candidates.append(t)
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                return min(candidates, key=len)
            return ""
        except Exception:
            return ""

    async def profile_data(self, datasource_id: str, table_name: str, db: AsyncSession) -> dict:
        try:
            df = await self._load_data(datasource_id, table_name, db)
            # 用 get_table_stats 取真实行数，避免 page_size 截断导致行数不准
            real_row_count = len(df)
            try:
                result = await db.execute(
                    select(DataSource).where(DataSource.id == _uuid.UUID(datasource_id))
                )
                datasource = result.scalar_one_or_none()
                if datasource:
                    connector = get_connector(datasource.type, datasource.connection_config or {})
                    try:
                        stats = await connector.get_table_stats(table_name)
                        if isinstance(stats.get("row_count"), (int, float)):
                            real_row_count = stats["row_count"]
                    finally:
                        await connector.close()
            except Exception:
                pass  # stats 失败时回退到 len(df)
            profile = {
                "row_count": real_row_count,
                "column_count": len(df.columns),
                "columns": {},
            }
            for col in df.columns:
                non_null = df[col].dropna()
                profile["columns"][col] = {
                    "dtype": str(df[col].dtype),
                    "null_count": int(df[col].isna().sum()),
                    "null_rate": round(float(df[col].isna().mean()), 4),
                    "unique_count": int(df[col].nunique()),
                    "sample_values": non_null.head(5).tolist() if len(non_null) > 0 else [],
                }
            return profile
        except Exception as e:
            logger.error(f"profile_data 失败: {e}")
            return {"error": str(e)}

    async def check_data_standards(
        self, datasource_id: str, table_name: str, db: AsyncSession, standard_rules: list = None
    ) -> dict:
        import pandas as pd
        from app.services.standards_parser import match_columns
        try:
            issues = []
            df = await self._load_data(datasource_id, table_name, db)
            columns = list(df.columns)

            # 命名规范（DQ-VAL-001 / naming_convention）
            if not standard_rules or "naming_convention" in standard_rules:
                for col in df.columns:
                    if not re.match(r'^[a-z][a-z0-9_]*$', col) and not re.match(r'^[\u4e00-\u9fff]', col):
                        suggestion = re.sub(r'([A-Z])', r'_\1', col).lower()
                        issues.append({
                            "dimension": "naming_convention",
                            "rule_id": "DQ-VAL-001",
                            "column": col,
                            "severity": "warning",
                            "description": f"列名 '{col}' 不符合 snake_case 命名规范",
                            "suggestion": f"建议重命名为 '{suggestion}'",
                        })

            # 类型一致性
            if not standard_rules or "type_consistency" in standard_rules:
                for col in df.columns:
                    non_null = df[col].dropna()
                    if len(non_null) > 0:
                        types = non_null.apply(type).nunique()
                        if types > 1:
                            issues.append({
                                "dimension": "type_consistency",
                                "rule_id": "DQ-CON-003",
                                "column": col,
                                "severity": "warning",
                                "description": f"列 '{col}' 存在混合类型（{types}种）",
                                "suggestion": "建议统一数据类型",
                            })

            # 编码检查
            if not standard_rules or "encoding_check" in standard_rules:
                for col in df.columns:
                    if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == 'object':
                        sample = df[col].dropna().head(100).astype(str)
                        garbled = sample.str.contains(r'[\ufffd\uffef\u00bf]', na=False, regex=True)
                        if garbled.any():
                            issues.append({
                                "dimension": "encoding_check",
                                "rule_id": "DQ-VAL-001",
                                "column": col,
                                "severity": "warning",
                                "description": f"列 '{col}' 疑似包含乱码字符（{garbled.sum()}条）",
                                "suggestion": "建议检查编码格式并转换",
                            })

            # 引用数据标准库做格式正则检查（确定性执行，标注 STD-xxx）
            if not standard_rules or "standard_format" in standard_rules or standard_rules is None:
                try:
                    from app.services.standards_parser import parse_standards, match_columns
                    for std in parse_standards():
                        matched = match_columns(columns, std.get("fields", []))
                        for col in matched:
                            non_null = df[col].dropna().astype(str)
                            if len(non_null) == 0:
                                continue
                            try:
                                invalid = ~non_null.str.match(std["regex"])
                                invalid_count = int(invalid.sum())
                                if invalid_count > 0:
                                    issues.append({
                                        "dimension": "standard_format",
                                        "standard_id": std["id"],
                                        "rule_id": "DQ-VAL-001",
                                        "column": col,
                                        "severity": std.get("severity", "warning"),
                                        "description": f"列 '{col}' 有 {invalid_count}/{len(non_null)} 条不符合 {std['id']} {std['name']}",
                                        "suggestion": f"按 {std['id']} 格式修正",
                                    })
                            except re.error:
                                pass
                except Exception as e:
                    logger.warning(f"标准库格式检查失败: {e}")

            # 枚举值检查（STD-ENUM-*, STD-HERITAGE-*）
            if not standard_rules or "enum_check" in (standard_rules or []):
                try:
                    from app.services.standards_parser import parse_standards as _ps, match_columns as _mc
                    for std in _ps():
                        legal = std.get("legal_values", [])
                        if not legal:
                            continue
                        matched = _mc(columns, std.get("fields", []))
                        for col in matched:
                            non_null = df[col].dropna().astype(str)
                            if len(non_null) == 0:
                                continue
                            invalid = ~non_null.isin([str(v) for v in legal])
                            invalid_count = int(invalid.sum())
                            if invalid_count > 0:
                                issues.append({
                                    "dimension": "enum_check",
                                    "standard_id": std["id"],
                                    "rule_id": "DQ-VAL-002",
                                    "column": col,
                                    "severity": std.get("severity", "warning"),
                                    "description": f"列 '{col}' 有 {invalid_count}/{len(non_null)} 条不符合 {std['id']} {std['name']} 合法值",
                                    "suggestion": f"合法值: {', '.join(legal[:10])}",
                                })
                except Exception as e:
                    logger.warning(f"枚举检查失败: {e}")

            # 数值约束检查（STD-NUM-001~004, STD-LOC-004, STD-TIME-003）
            if not standard_rules or "numeric_constraint" in (standard_rules or []):
                _NUM_CHECKS = {
                    "STD-NUM-001": (["amount", "money", "price", "total_price", "fee"], lambda s: (
                        (s < 0).any(), "存在负值",
                        (s.abs() > 9999999999.99).any(), "超出金额上限",
                    )),
                    "STD-NUM-002": (["rate", "percent", "ratio", "discount"], lambda s: (
                        ((s < 0) | (s > 100)).any() if s.max() > 1 else ((s < 0) | (s > 1)).any(),
                        "百分比超出范围(0~100或0~1)",
                        False, "",
                    )),
                    "STD-NUM-003": (["age", "years_old"], lambda s: (
                        ((s < 0) | (s > 150)).any(), "年龄超出范围(0~150)",
                        (s % 1 != 0).any(), "年龄应为整数",
                    )),
                    "STD-NUM-004": (["quantity", "qty", "count", "weight", "volume"], lambda s: (
                        (s < 0).any(), "存在负值",
                        False, "",
                    )),
                }
                for sid, (flds, check_fn) in _NUM_CHECKS.items():
                    matched = match_columns(columns, flds)
                    for col in matched:
                        non_null = pd.to_numeric(df[col], errors="coerce").dropna()
                        if len(non_null) == 0:
                            continue
                        bad1, desc1, bad2, desc2 = check_fn(non_null)
                        for bad, desc in [(bad1, desc1), (bad2, desc2)]:
                            if bad:
                                issues.append({
                                    "dimension": "numeric_constraint",
                                    "standard_id": sid,
                                    "rule_id": "DQ-VAL-003",
                                    "column": col,
                                    "severity": "warning",
                                    "description": f"列 '{col}' 不符合 {sid}: {desc}",
                                    "suggestion": f"按 {sid} 约束修正",
                                })

                # STD-LOC-004 经纬度范围
                for col in columns:
                    cl = col.lower()
                    non_null = pd.to_numeric(df[col], errors="coerce").dropna()
                    if len(non_null) == 0:
                        continue
                    if cl in ("longitude", "lng", "lon") and ((non_null < -180) | (non_null > 180)).any():
                        issues.append({
                            "dimension": "numeric_constraint", "standard_id": "STD-LOC-004",
                            "rule_id": "DQ-VAL-003", "column": col, "severity": "warning",
                            "description": f"列 '{col}' 经度超出范围(-180~180)",
                            "suggestion": "修正经度值",
                        })
                    elif cl in ("latitude", "lat") and ((non_null < -90) | (non_null > 90)).any():
                        issues.append({
                            "dimension": "numeric_constraint", "standard_id": "STD-LOC-004",
                            "rule_id": "DQ-VAL-003", "column": col, "severity": "warning",
                            "description": f"列 '{col}' 纬度超出范围(-90~90)",
                            "suggestion": "修正纬度值",
                        })

                # STD-TIME-003 Unix 时间戳
                for col in match_columns(columns, ["ts", "epoch"]):
                    non_null = pd.to_numeric(df[col], errors="coerce").dropna()
                    if len(non_null) == 0:
                        continue
                    # 10位秒级 or 13位毫秒级，范围 1970~2100
                    valid_range = (946684800, 4133980799)  # 2000~2100
                    is_10digit = non_null.between(946684800, 4133980799)
                    is_13digit = non_null.between(946684800000, 4133980799999)
                    invalid = ~is_10digit & ~is_13digit
                    if invalid.any():
                        issues.append({
                            "dimension": "numeric_constraint", "standard_id": "STD-TIME-003",
                            "rule_id": "DQ-VAL-003", "column": col, "severity": "warning",
                            "description": f"列 '{col}' 有 {int(invalid.sum())} 条不符合 Unix 时间戳范围",
                            "suggestion": "检查时间戳值是否合理(1970~2100)",
                        })

            # 地址检查（STD-LOC-001）
            if not standard_rules or "address_check" in (standard_rules or []):
                for col in match_columns(columns, ["address", "addr", "detail_address"]):
                    non_null = df[col].dropna().astype(str)
                    if len(non_null) == 0:
                        continue
                    short = non_null[non_null.str.len() < 5]
                    if len(short) > 0:
                        issues.append({
                            "dimension": "address_check", "standard_id": "STD-LOC-001",
                            "rule_id": "DQ-VAL-003", "column": col, "severity": "warning",
                            "description": f"列 '{col}' 有 {len(short)} 条地址长度不足5字符",
                            "suggestion": "补全地址信息",
                        })
                    has_newline = non_null.str.contains(r'\n', regex=True).sum()
                    if has_newline > 0:
                        issues.append({
                            "dimension": "address_check", "standard_id": "STD-LOC-001",
                            "rule_id": "DQ-VAL-003", "column": col, "severity": "warning",
                            "description": f"列 '{col}' 有 {has_newline} 条地址含换行符",
                            "suggestion": "去除换行符",
                        })

            # 时间范围一致性（STD-TIME-004）
            if not standard_rules or "time_range_check" in (standard_rules or []):
                _date_pairs = []
                cols_low = {c.lower(): c for c in columns}
                for prefix in ["start", "begin", "from", "create"]:
                    for suffix in ["end", "to", "expire", "finish"]:
                        s_col = cols_low.get(prefix + "_date") or cols_low.get(prefix + "_time") or cols_low.get(prefix + "date")
                        e_col = cols_low.get(suffix + "_date") or cols_low.get(suffix + "_time") or cols_low.get(suffix + "date")
                        if s_col and e_col:
                            _date_pairs.append((s_col, e_col))
                # 也检查 start_date/end_date 直接匹配
                for s_name, e_name in [("start_date", "end_date"), ("start_time", "end_time"), ("begin_date", "end_date"), ("begin_time", "end_time")]:
                    s_col = cols_low.get(s_name)
                    e_col = cols_low.get(e_name)
                    if s_col and e_col and (s_col, e_col) not in _date_pairs:
                        _date_pairs.append((s_col, e_col))
                for s_col, e_col in _date_pairs:
                    s = pd.to_datetime(df[s_col], errors="coerce")
                    e = pd.to_datetime(df[e_col], errors="coerce")
                    both_valid = s.notna() & e.notna()
                    invalid = both_valid & (e < s)
                    if invalid.any():
                        issues.append({
                            "dimension": "time_range_check", "standard_id": "STD-TIME-004",
                            "rule_id": "DQ-CON-001", "column": f"{s_col}/{e_col}",
                            "severity": "error",
                            "description": f"列 '{e_col}' 早于 '{s_col}' 的记录有 {int(invalid.sum())} 条",
                            "suggestion": "修正结束时间早于开始时间的记录",
                        })

            return {"dimension": "standards", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"check_data_standards 失败: {e}")
            return {"dimension": "standards", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}

    async def check_data_quality(
        self, datasource_id: str, table_name: str, db: AsyncSession, quality_dimensions: list = None
    ) -> dict:
        import pandas as pd
        try:
            issues = []
            df = await self._load_data(datasource_id, table_name, db)
            total = len(df)

            # 解析数据质量库 MD，用其中的阈值驱动检查
            try:
                from app.services.standards_parser import parse_quality_rules
                dq_rules = {r["id"]: r for r in parse_quality_rules()}
            except Exception:
                dq_rules = {}

            def _thr(rid: str, default: float) -> float:
                r = dq_rules.get(rid)
                if r and r.get("threshold_value") is not None:
                    return r["threshold_value"]
                return default

            null_thr = 1 - _thr("DQ-COM-003", 0.9)     # DQ-COM-003 阈值是完整率(95%)，转换为空值率阈值(1-0.95=0.05)
            dupe_thr = _thr("DQ-UNI-003", 0.01)         # 重复率阈值
            outlier_thr = _thr("DQ-VAL-004", 0.01)      # 异常值占比阈值

            if not quality_dimensions or "completeness" in quality_dimensions:
                for col in df.columns:
                    null_rate = df[col].isna().mean()
                    if null_rate > null_thr:
                        _sev = "critical" if null_rate >= 1.0 else ("error" if null_rate > null_thr * 3 else "warning")
                        issues.append({
                            "dimension": "completeness",
                            "rule_id": "DQ-COM-003",
                            "column": col,
                            "severity": _sev,
                            "description": f"列 '{col}' 空值率 {null_rate:.1%}（阈值 {null_thr:.0%}）",
                            "suggestion": "建议填充默认值或删除空值行",
                        })

            if not quality_dimensions or "uniqueness" in quality_dimensions:
                # DQ-UNI-001: 主键唯一性检查（确定性，不依赖 LLM，不报不连续）
                _id_cols = [c for c in df.columns
                            if str(c).lower().strip() == "id"
                            or str(c).lower().strip().endswith("_id")]
                for col in _id_cols:
                    dup_count = int(df[col].dropna().duplicated().sum())
                    if dup_count > 0:
                        issues.append({
                            "dimension": "uniqueness",
                            "rule_id": "DQ-UNI-001",
                            "column": col,
                            "severity": "critical",
                            "description": f"主键列 '{col}' 存在 {dup_count} 个重复值",
                            "suggestion": "去重或修正主键生成逻辑",
                        })

                # DQ-UNI-003: 整行重复检查
                dupe_count = total - len(df.drop_duplicates())
                dupe_rate = dupe_count / total if total else 0
                if dupe_count > 0 and dupe_rate > dupe_thr:
                    issues.append({
                        "dimension": "uniqueness",
                        "rule_id": "DQ-UNI-003",
                        "severity": "error",
                        "description": f"存在 {dupe_count} 条完全重复的行（{dupe_rate:.1%}，阈值 {dupe_thr:.0%}）",
                        "suggestion": "建议执行去重操作",
                    })

            if not quality_dimensions or "validity" in quality_dimensions:
                for col in df.columns:
                    if pd.api.types.is_numeric_dtype(df[col]):
                        non_null = df[col].dropna()
                        if len(non_null) > 0:
                            q1 = non_null.quantile(0.25)
                            q3 = non_null.quantile(0.75)
                            iqr = q3 - q1
                            if iqr > 0:
                                lower = q1 - 3 * iqr
                                upper = q3 + 3 * iqr
                                outlier_count = ((non_null < lower) | (non_null > upper)).sum()
                                outlier_rate = outlier_count / len(non_null)
                                if outlier_count > 0 and outlier_rate > outlier_thr:
                                    issues.append({
                                        "dimension": "validity",
                                        "rule_id": "DQ-VAL-004",
                                        "column": col,
                                        "severity": "warning",
                                        "description": f"列 '{col}' 存在 {outlier_count} 个异常极值（{outlier_rate:.1%}，IQR方法）",
                                        "suggestion": "建议检查极值是否合理",
                                    })

            if not quality_dimensions or "consistency" in quality_dimensions:
                for col in df.columns:
                    if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == 'object':
                        non_null = df[col].dropna().astype(str)
                        if len(non_null) > 0:
                            lengths = non_null.str.len()
                            if lengths.max() > lengths.min() * 5 and lengths.min() > 0:
                                issues.append({
                                    "dimension": "consistency",
                                    "rule_id": "DQ-CON-003",
                                    "column": col,
                                    "severity": "warning",
                                    "description": f"列 '{col}' 值长度差异较大（最短{lengths.min()}，最长{lengths.max()}）",
                                    "suggestion": "建议检查格式是否一致",
                                })

                # DQ-CON-001 跨字段逻辑一致（end_date >= start_date）
                cols_low = {str(c).lower(): c for c in df.columns}
                for s_name, e_name in [("start_date", "end_date"), ("start_time", "end_time"),
                                        ("begin_date", "end_date"), ("begin_time", "end_time"),
                                        ("from_date", "to_date"), ("created_at", "updated_at")]:
                    s_col = cols_low.get(s_name)
                    e_col = cols_low.get(e_name)
                    if s_col and e_col:
                        s = pd.to_datetime(df[s_col], errors="coerce")
                        e = pd.to_datetime(df[e_col], errors="coerce")
                        both = s.notna() & e.notna()
                        invalid = both & (e < s)
                        if invalid.any():
                            issues.append({
                                "dimension": "consistency",
                                "rule_id": "DQ-CON-001",
                                "column": f"{s_col}/{e_col}",
                                "severity": "error",
                                "description": f"'{e_col}' 早于 '{s_col}' 的记录有 {int(invalid.sum())} 条",
                                "suggestion": "修正结束时间早于开始时间的记录",
                            })

                # DQ-CON-001 年龄与出生日期一致
                age_col = cols_low.get("age")
                birth_col = cols_low.get("birth_date") or cols_low.get("birthdate") or cols_low.get("birthday")
                if age_col and birth_col:
                    age = pd.to_numeric(df[age_col], errors="coerce")
                    birth = pd.to_datetime(df[birth_col], errors="coerce")
                    both = age.notna() & birth.notna()
                    if both.any():
                        import datetime as _dt
                        calc_age = (_dt.datetime.now().year - birth.dt.year)
                        diff = (age - calc_age).abs()
                        mismatch = both & (diff > 1)
                        if mismatch.any():
                            issues.append({
                                "dimension": "consistency",
                                "rule_id": "DQ-CON-001",
                                "column": f"{age_col}/{birth_col}",
                                "severity": "error",
                                "description": f"'{age_col}' 与 '{birth_col}' 计算年龄不一致的记录有 {int(mismatch.sum())} 条",
                                "suggestion": "核对年龄与出生日期",
                            })

            # DQ-COM-001 必填字段空值率（0%阈值，识别关键字段）
            if not quality_dimensions or "completeness" in quality_dimensions:
                _required_keywords = ["name", "phone", "mobile", "email", "id_card", "id_no",
                                      "amount", "price", "order_no", "address", "身份证", "手机", "姓名"]
                for col in df.columns:
                    cl = str(col).lower()
                    if any(kw in cl for kw in _required_keywords):
                        null_count = int(df[col].isna().sum())
                        if null_count > 0:
                            issues.append({
                                "dimension": "completeness",
                                "rule_id": "DQ-COM-001",
                                "column": col,
                                "severity": "critical",
                                "description": f"必填字段 '{col}' 有 {null_count} 个空值（阈值 0%）",
                                "suggestion": "补充缺失值或回源补数",
                            })

                # DQ-COM-002 主键非空
                _pk_cols = [c for c in df.columns
                            if str(c).lower().strip() == "id"
                            or str(c).lower().strip().endswith("_id")]
                for col in _pk_cols:
                    null_count = int(df[col].isna().sum())
                    if null_count > 0:
                        issues.append({
                            "dimension": "completeness",
                            "rule_id": "DQ-COM-002",
                            "column": col,
                            "severity": "critical",
                            "description": f"主键列 '{col}' 有 {null_count} 个空值",
                            "suggestion": "排查 ETL 是否丢失主键或回源补数",
                        })

            # DQ-UNI-002 业务键唯一
            if not quality_dimensions or "uniqueness" in quality_dimensions:
                _biz_key_keywords = ["order_no", "order_id", "id_card", "id_no", "identity",
                                     "idcard", "sfz", "passport", "bank_card", "card_no",
                                     "订单号", "身份证"]
                for col in df.columns:
                    cl = str(col).lower()
                    if any(kw in cl for kw in _biz_key_keywords):
                        dup_count = int(df[col].dropna().duplicated().sum())
                        if dup_count > 0:
                            issues.append({
                                "dimension": "uniqueness",
                                "rule_id": "DQ-UNI-002",
                                "column": col,
                                "severity": "critical",
                                "description": f"业务键列 '{col}' 存在 {dup_count} 个重复值",
                                "suggestion": "排查重复产生原因（重跑、Join 膨胀）",
                            })

            return {"dimension": "quality", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"check_data_quality 失败: {e}")
            return {"dimension": "quality", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}

    async def check_etl_quality(
        self,
        source_datasource_id: str,
        source_table: str,
        target_datasource_id: str,
        target_table: str,
        db: AsyncSession,
        amount_column: str = None,
    ) -> dict:
        """ETL 过程质量对数检查（确定性执行 DQ-ETL 规则）"""
        import pandas as pd
        try:
            src_df = await self._load_data(source_datasource_id, source_table, db)
            tgt_df = await self._load_data(target_datasource_id, target_table, db)
            src_n = len(src_df)
            tgt_n = len(tgt_df)
            issues = []

            # 解析 ETL 规则阈值
            try:
                from app.services.standards_parser import parse_quality_rules
                dq = {r["id"]: r for r in parse_quality_rules()}
            except Exception:
                dq = {}

            def _thr(rid: str, default: float) -> float:
                r = dq.get(rid)
                if r and r.get("threshold_value") is not None:
                    return r["threshold_value"]
                return default

            growth_thr = _thr("DQ-ETL-001", 0.05)   # 数据量增加阈值
            shrink_thr = _thr("DQ-ETL-002", 0.05)   # 数据量减少阈值
            amount_thr = _thr("DQ-ETL-004", 0.01)   # 金额汇总偏差阈值

            # DQ-ETL-001 数据量不异常增加
            if tgt_n > src_n * (1 + growth_thr):
                issues.append({
                    "dimension": "etl_volume",
                    "rule_id": "DQ-ETL-001",
                    "severity": "error",
                    "description": f"目标表行数 {tgt_n} > 源表 {src_n}×(1+{growth_thr:.0%})，疑似数据膨胀",
                    "suggestion": "检查是否产生笛卡尔积、Join 重复、未去重",
                })

            # DQ-ETL-002 数据量不异常减少
            if tgt_n < src_n * (1 - shrink_thr):
                issues.append({
                    "dimension": "etl_volume",
                    "rule_id": "DQ-ETL-002",
                    "severity": "error",
                    "description": f"目标表行数 {tgt_n} < 源表 {src_n}×(1-{shrink_thr:.0%})，疑似数据丢失",
                    "suggestion": "排查过滤条件过严、关联条件错误、丢失记录",
                })

            # DQ-ETL-003 对数（记录数一致）
            if src_n != tgt_n:
                _diff_rate = abs(src_n - tgt_n) / max(src_n, 1)
                _sev = "critical" if _diff_rate > 0.1 else "error"
                issues.append({
                    "dimension": "etl_reconciliation",
                    "rule_id": "DQ-ETL-003",
                    "severity": _sev,
                    "description": f"记录数不一致：源 {src_n} ≠ 目标 {tgt_n}（差 {abs(src_n - tgt_n)}，偏差 {_diff_rate:.1%}）",
                    "suggestion": "排查过滤条件、丢失记录、重复写入",
                })

            # DQ-ETL-004 对数（金额汇总一致）
            if amount_column:
                if amount_column in src_df.columns and amount_column in tgt_df.columns:
                    src_sum = pd.to_numeric(src_df[amount_column], errors="coerce").sum()
                    tgt_sum = pd.to_numeric(tgt_df[amount_column], errors="coerce").sum()
                    diff = abs(src_sum - tgt_sum)
                    if diff > amount_thr:
                        issues.append({
                            "dimension": "etl_reconciliation",
                            "rule_id": "DQ-ETL-004",
                            "severity": "error",
                            "description": f"金额汇总不一致：源 {src_sum:.2f} ≠ 目标 {tgt_sum:.2f}（差 {diff:.2f}，阈值 {amount_thr}）",
                            "suggestion": "排查金额精度、丢失记录、重复累加",
                        })
                else:
                    issues.append({
                        "dimension": "etl_reconciliation",
                        "rule_id": "DQ-ETL-004",
                        "severity": "info",
                        "description": f"金额列 '{amount_column}' 在源/目标表不存在，跳过金额对数",
                        "suggestion": "确认金额列名",
                    })

            # DQ-ETL-006 检索结果不超总量（目标行数 ≤ 源行数）
            if tgt_n > src_n:
                issues.append({
                    "dimension": "etl_volume",
                    "rule_id": "DQ-ETL-006",
                    "severity": "error",
                    "description": f"目标/检索结果行数 {tgt_n} > 源总量 {src_n}",
                    "suggestion": "检查 Join 是否笛卡尔积、去重逻辑缺失",
                })

            # DQ-ETL-007 目标表字段空值率（阈值 10%）
            etl_null_thr = _thr("DQ-ETL-007", 0.1)
            for col in tgt_df.columns:
                null_rate = tgt_df[col].isna().mean()
                if null_rate > etl_null_thr:
                    issues.append({
                        "dimension": "etl_quality",
                        "rule_id": "DQ-ETL-007",
                        "column": col,
                        "severity": "warning",
                        "description": f"目标表列 '{col}' 空值率 {null_rate:.1%}（阈值 {etl_null_thr:.0%}）",
                        "suggestion": "排查源字段缺失、关联丢失、转换逻辑错误",
                    })

            # DQ-ETL-008 目标表主键唯一性
            _tgt_pk_cols = [c for c in tgt_df.columns
                            if str(c).lower().strip() == "id"
                            or str(c).lower().strip().endswith("_id")]
            for col in _tgt_pk_cols:
                dup_count = int(tgt_df[col].dropna().duplicated().sum())
                if dup_count > 0:
                    issues.append({
                        "dimension": "etl_quality",
                        "rule_id": "DQ-ETL-008",
                        "column": col,
                        "severity": "error",
                        "description": f"目标表主键 '{col}' 存在 {dup_count} 个重复值",
                        "suggestion": "检查 Join 膨胀、去重逻辑、主键生成",
                    })

            # DQ-ETL-009 字段类型一致（源→目标同名列 dtype 对比）
            common_cols = set(src_df.columns) & set(tgt_df.columns)
            for col in common_cols:
                src_dtype = str(src_df[col].dtype)
                tgt_dtype = str(tgt_df[col].dtype)
                if src_dtype != tgt_dtype:
                    issues.append({
                        "dimension": "etl_quality",
                        "rule_id": "DQ-ETL-009",
                        "column": col,
                        "severity": "warning",
                        "description": f"列 '{col}' 类型不一致：源 {src_dtype} → 目标 {tgt_dtype}",
                        "suggestion": "修正 ETL 类型转换",
                    })

            return {"dimension": "etl_quality", "passed": len(issues) == 0, "issues": issues,
                    "source_rows": src_n, "target_rows": tgt_n}
        except Exception as e:
            logger.error(f"check_etl_quality 失败: {e}")
            return {"dimension": "etl_quality", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}

    async def check_data_security(self, datasource_id: str, table_name: str, db: AsyncSession) -> dict:
        import pandas as pd
        try:
            issues = []
            df = await self._load_data(datasource_id, table_name, db)

            # 引用数据安全规则库做正则检测（确定性执行，标注 SEC-xxx）
            try:
                from app.services.standards_parser import parse_security_rules
                sec_rules = parse_security_rules()
            except Exception:
                sec_rules = []

            # 兜底：若规则库解析失败，用内置 PII 模式
            if not sec_rules:
                sec_rules = [
                    {"id": "SEC-PII-001", "name": "身份证号明文", "regex": r'[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]', "severity": "fatal"},
                    {"id": "SEC-PII-002", "name": "手机号明文", "regex": r'1[3-9]\d{9}', "severity": "critical"},
                    {"id": "SEC-PII-003", "name": "电子邮箱明文", "regex": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', "severity": "error"},
                ]

            for col in df.columns:
                if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == 'object':
                    sample = df[col].dropna().head(200).astype(str)
                    if len(sample) == 0:
                        continue
                    for sec in sec_rules:
                        if not sec.get("regex"):
                            continue
                        try:
                            match_count = int(sample.str.contains(sec["regex"], regex=True, na=False).sum())
                        except re.error:
                            continue
                        if match_count > 0:
                            issues.append({
                                "dimension": "security",
                                "rule_id": sec["id"],
                                "column": col,
                                "severity": sec.get("severity", "critical"),
                                "description": f"列 '{col}' 疑似包含 {sec['name']}（{match_count}/{len(sample)} 条样本命中）",
                                "suggestion": f"按 {sec['id']} 处置建议脱敏/加密",
                            })

            # SEC-PII-006 完整地址明文（含省/市/区+路/号）
            _addr_cols = [c for c in df.columns if str(c).lower() in ("address", "addr", "detail_address", "地址")]
            for col in _addr_cols:
                sample = df[col].dropna().head(200).astype(str)
                if len(sample) == 0:
                    continue
                full_addr = sample.str.contains(r'[\u4e00-\u9fff]{2,}[省市].*[\u4e00-\u9fff]{1,}[区县].*[路街道].*\d', regex=True)
                if full_addr.any():
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-PII-006",
                        "column": col, "severity": "warning",
                        "description": f"列 '{col}' 有 {int(full_addr.sum())} 条疑似完整地址明文",
                        "suggestion": "拆分为行政区划+门牌脱敏",
                    })

            # SEC-PII-007 姓名字段识别（与强 PII 同表）
            _name_cols = [c for c in df.columns if str(c).lower() in ("name", "姓名", "user_name", "customer_name", "real_name")]
            _pii_cols = [c for c in df.columns if any(kw in str(c).lower() for kw in ("id_card", "id_no", "phone", "mobile", "身份证"))]
            if _name_cols and _pii_cols:
                for col in _name_cols:
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-PII-007",
                        "column": col, "severity": "warning",
                        "description": f"姓名字段 '{col}' 与强 PII 字段({', '.join(_pii_cols[:3])})同表",
                        "suggestion": "评估是否需脱敏；关联强 PII 时按 critical 处置",
                    })

            # SEC-BIZ-001 薪资/收入字段
            for col in df.columns:
                cl = str(col).lower()
                if any(kw in cl for kw in ("salary", "wage", "income", "薪资", "收入", "工资")):
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-BIZ-001",
                        "column": col, "severity": "error",
                        "description": f"列 '{col}' 含薪资/收入数据，需访问控制+脱敏",
                        "suggestion": "按机密级管控；非授权查询禁止返回明文",
                    })
                # SEC-BIZ-002 医疗健康字段
                if any(kw in cl for kw in ("diagnosis", "medical", "health", "病历", "诊断", "病情")):
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-BIZ-002",
                        "column": col, "severity": "error",
                        "description": f"列 '{col}' 含医疗健康数据，需授权访问",
                        "suggestion": "按机密/秘密级管控；需授权访问",
                    })

            # SEC-BIZ-003 未成年人信息（age < 18 且关联 PII）
            _age_col = next((c for c in df.columns if str(c).lower() in ("age", "年龄")), None)
            if _age_col and _pii_cols:
                ages = pd.to_numeric(df[_age_col], errors="coerce")
                minors = ages[ages < 18]
                if len(minors) > 0:
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-BIZ-003",
                        "column": _age_col, "severity": "critical",
                        "description": f"发现 {len(minors)} 条未成年人记录且关联 PII 字段",
                        "suggestion": "需监护人授权；加强脱敏",
                    })

            # SEC-MASK-001~004 脱敏格式检查（已脱敏的不再报明文）
            _MASK_CHECKS = {
                "SEC-MASK-001": (["phone", "mobile", "手机"], r'^\d{3}\*{4}\d{4}$', "138****5678"),
                "SEC-MASK-002": (["id_card", "id_no", "身份证"], r'^\d{6}\*{8}\d{4}$', "110101********1234"),
                "SEC-MASK-003": (["email", "邮箱"], r'^[a-zA-Z0-9]\*+@', "a***@x.com"),
                "SEC-MASK-004": (["bank_card", "card_no", "银行卡"], r'^\*+\d{4}$', "****5678"),
            }
            for sid, (keywords, masked_pattern, example) in _MASK_CHECKS.items():
                for col in df.columns:
                    cl = str(col).lower()
                    if not any(kw in cl for kw in keywords):
                        continue
                    sample = df[col].dropna().head(100).astype(str)
                    if len(sample) == 0:
                        continue
                    # 如果值是明文格式（不是脱敏格式），报告需要脱敏
                    is_masked = sample.str.match(masked_pattern)
                    unmasked_count = int((~is_masked).sum())
                    if unmasked_count > 0:
                        issues.append({
                            "dimension": "security", "rule_id": sid,
                            "column": col, "severity": "error" if sid != "SEC-MASK-003" else "warning",
                            "description": f"列 '{col}' 有 {unmasked_count} 条未脱敏（期望格式如 {example}）",
                            "suggestion": f"按 {sid} 脱敏规则处理",
                        })

            # SEC-CLASS-001 数据分级标注缺失
            try:
                from app.models.table_metadata import TableMetadata as _TM
                tm_result = await db.execute(
                    select(_TM).where(_TM.datasource_id == _uuid.UUID(datasource_id),
                                      _TM.table_name == table_name)
                )
                tm = tm_result.scalar_one_or_none()
                if tm and not tm.security_level:
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-CLASS-001",
                        "severity": "warning",
                        "description": f"表 '{table_name}' 缺少数据分级标注（public/internal/confidential/secret）",
                        "suggestion": "补充分级元数据；按分级施加访问控制",
                    })
            except Exception:
                pass  # TableMetadata 模型不存在时跳过

            return {"dimension": "security", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"check_data_security 失败: {e}")
            return {"dimension": "security", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}


inspector_tools = DataInspectorTools()
