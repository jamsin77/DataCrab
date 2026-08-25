"""DataInspector 数据检查智能体 - 检查工具实现"""

from __future__ import annotations

import re
import uuid as _uuid
import warnings
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.models.datasource import DataSource
from app.services.connectors import get_connector


def _load_quality_rules() -> Dict[str, Dict]:
    """解析 data_quality_rules.md 为 {rule_id: rule_dict}，失败返回空 dict。"""
    try:
        from app.services.standards_parser import parse_quality_rules
        return {r["id"]: r for r in parse_quality_rules()}
    except Exception:
        return {}


def _load_security_rules() -> Dict[str, Dict]:
    """解析 data_security_rules.md 为 {rule_id: rule_dict}，失败返回空 dict。"""
    try:
        from app.services.standards_parser import parse_security_rules
        return {r["id"]: r for r in parse_security_rules()}
    except Exception:
        return {}


def _dq_severity(rule_id: str, default: str = "warning") -> str:
    """从数据质量规则库读取 severity，失败回退 default。"""
    return _load_quality_rules().get(rule_id, {}).get("severity", default)


def _sec_severity(rule_id: str, default: str = "warning") -> str:
    """从数据安全规则库读取 severity，失败回退 default。"""
    return _load_security_rules().get(rule_id, {}).get("severity", default)


class DataInspectorTools:
    _cache: dict = {}

    @staticmethod
    def _extract_samples(df, mask, columns=None, max_samples=5):
        """从布尔 mask 中提取样本行（行号+值），供检查报告展示明细。

        Args:
            df: DataFrame
            mask: 布尔 Series，标记问题行
            columns: 要展示的列名列表，None 则展示所有列
            max_samples: 最多提取几条样本
        Returns:
            list[dict]: [{"row": 行号(1-based), "values": {列名: 值}}]
        """
        import pandas as pd
        if mask is None or not mask.any():
            return []
        problem_indices = df.index[mask][:max_samples]
        samples = []
        cols = columns if columns else list(df.columns)[:6]
        for idx in problem_indices:
            row_data = {}
            for col in cols:
                if col in df.columns:
                    val = df.loc[idx, col]
                    if pd.isna(val):
                        row_data[col] = "(空)"
                    else:
                        row_data[str(val)] = None if pd.isna(val) else str(val)[:80]
            samples.append({"row": int(idx) + 1, "values": {c: str(df.loc[idx, c])[:80] if not pd.isna(df.loc[idx, c]) else "(空)" for c in cols}})
        return samples

    async def _load_data(self, datasource_id: str, table_name: str, db: AsyncSession, page_size: int = 50000, use_cache: bool = True) -> pd.DataFrame:
        cache_key = f"{datasource_id}:{table_name}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        result = await db.execute(
            select(DataSource).where(DataSource.id == _uuid.UUID(datasource_id))
        )
        datasource = result.scalar_one_or_none()
        if not datasource:
            raise ValueError(f"数据源不存在: {datasource_id}")

        connector = get_connector(datasource.type, datasource.connection_config or {})
        try:
            df = await connector.get_table_data(table_name, page=1, page_size=page_size)
            if use_cache:
                self._cache[cache_key] = df
            return df
        except Exception as e:
            err_msg = str(e)
            if "不存在" in err_msg or "does not exist" in err_msg or "no such table" in err_msg.lower():
                resolved = await self._resolve_table_name(connector, table_name)
                if resolved and resolved != table_name:
                    logger.info(f"Inspector 表名模糊匹配: '{table_name}' -> '{resolved}'")
                    df = await connector.get_table_data(resolved, page=1, page_size=page_size)
                    if use_cache:
                        self._cache[cache_key] = df
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
                _sev = _dq_severity("DQ-VAL-001", "warning")
                for col in df.columns:
                    if not re.match(r'^[a-z][a-z0-9_]*$', col) and not re.match(r'^[\u4e00-\u9fff]', col):
                        suggestion = re.sub(r'([A-Z])', r'_\1', col).lower()
                        issues.append({
                            "dimension": "naming_convention",
                            "rule_id": "DQ-VAL-001",
                            "column": col,
                            "severity": _sev,
                            "description": f"列名 '{col}' 不符合 snake_case 命名规范",
                            "suggestion": f"建议重命名为 '{suggestion}'",
                        })

            # 类型一致性
            if not standard_rules or "type_consistency" in standard_rules:
                _sev = _dq_severity("DQ-CON-003", "warning")
                for col in df.columns:
                    non_null = df[col].dropna()
                    if len(non_null) > 0:
                        types = non_null.apply(type).nunique()
                        if types > 1:
                            issues.append({
                                "dimension": "type_consistency",
                                "rule_id": "DQ-CON-003",
                                "column": col,
                                "severity": _sev,
                                "description": f"列 '{col}' 存在混合类型（{types}种）",
                                "suggestion": "建议统一数据类型",
                            })

            # 编码检查
            if not standard_rules or "encoding_check" in standard_rules:
                _sev = _dq_severity("DQ-VAL-001", "warning")
                for col in df.columns:
                    if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == 'object':
                        sample = df[col].dropna().head(100).astype(str)
                        garbled = sample.str.contains(r'[\ufffd\uffef\u00bf]', na=False, regex=True)
                        if garbled.any():
                            issues.append({
                                "dimension": "encoding_check",
                                "rule_id": "DQ-VAL-001",
                                "column": col,
                                "severity": _sev,
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
                                    "severity": _dq_severity("DQ-VAL-003", "warning"),
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
                            "rule_id": "DQ-VAL-003", "column": col, "severity": _dq_severity("DQ-VAL-003", "warning"),
                            "description": f"列 '{col}' 经度超出范围(-180~180)",
                            "suggestion": "修正经度值",
                        })
                    elif cl in ("latitude", "lat") and ((non_null < -90) | (non_null > 90)).any():
                        issues.append({
                            "dimension": "numeric_constraint", "standard_id": "STD-LOC-004",
                            "rule_id": "DQ-VAL-003", "column": col, "severity": _dq_severity("DQ-VAL-003", "warning"),
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
                            "rule_id": "DQ-VAL-003", "column": col, "severity": _dq_severity("DQ-VAL-003", "warning"),
                            "description": f"列 '{col}' 有 {int(invalid.sum())} 条不符合 Unix 时间戳范围",
                            "suggestion": "检查时间戳值是否合理(1970~2100)",
                        })

            # 地址检查（STD-LOC-001）
            if not standard_rules or "address_check" in (standard_rules or []):
                _sev = _dq_severity("DQ-VAL-003", "warning")
                for col in match_columns(columns, ["address", "addr", "detail_address"]):
                    non_null = df[col].dropna().astype(str)
                    if len(non_null) == 0:
                        continue
                    short = non_null[non_null.str.len() < 5]
                    if len(short) > 0:
                        issues.append({
                            "dimension": "address_check", "standard_id": "STD-LOC-001",
                            "rule_id": "DQ-VAL-003", "column": col, "severity": _sev,
                            "description": f"列 '{col}' 有 {len(short)} 条地址长度不足5字符",
                            "suggestion": "补全地址信息",
                        })
                    has_newline = non_null.str.contains(r'\n', regex=True).sum()
                    if has_newline > 0:
                        issues.append({
                            "dimension": "address_check", "standard_id": "STD-LOC-001",
                            "rule_id": "DQ-VAL-003", "column": col, "severity": _sev,
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
                            "severity": _dq_severity("DQ-CON-001", "error"),
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

            dq_rules = _load_quality_rules()

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
                    _null_mask = df[col].isna()
                    if df[col].dtype == object:
                        _null_mask = _null_mask | (df[col].astype(str).str.strip() == "")
                    null_rate = _null_mask.mean()
                    if null_rate > null_thr:
                        issues.append({
                            "dimension": "completeness",
                            "rule_id": "DQ-COM-003",
                            "column": col,
                            "severity": _dq_severity("DQ-COM-003", "warning"),
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
                            "severity": _dq_severity("DQ-UNI-001", "error"),
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
                        "severity": _dq_severity("DQ-UNI-003", "warning"),
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
                                        "severity": _dq_severity("DQ-VAL-004", "warning"),
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
                                    "severity": _dq_severity("DQ-CON-003", "warning"),
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
                                "severity": _dq_severity("DQ-CON-001", "error"),
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
                                "severity": _dq_severity("DQ-CON-001", "error"),
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
                        _null_mask = df[col].isna()
                        if df[col].dtype == object:
                            _null_mask = _null_mask | (df[col].astype(str).str.strip() == "")
                        null_count = int(_null_mask.sum())
                        if null_count > 0:
                            issues.append({
                                "dimension": "completeness",
                                "rule_id": "DQ-COM-001",
                                "column": col,
                                "severity": _dq_severity("DQ-COM-001", "error"),
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
                            "severity": _dq_severity("DQ-COM-002", "error"),
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
                                "severity": _dq_severity("DQ-UNI-002", "error"),
                                "description": f"业务键列 '{col}' 存在 {dup_count} 个重复值",
                                "suggestion": "排查重复产生原因（重跑、Join 膨胀）",
                            })

            return {"dimension": "quality", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"check_data_quality 失败: {e}")
            return {"dimension": "quality", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}

    async def check_data_security(self, datasource_id: str, table_name: str, db: AsyncSession) -> dict:
        import pandas as pd
        try:
            issues = []
            df = await self._load_data(datasource_id, table_name, db)

            # 引用数据安全规则库做正则检测（确定性执行，标注 SEC-xxx）
            sec_rules = list(_load_security_rules().values())

            # 兜底：若规则库解析失败，用内置 PII 模式
            if not sec_rules:
                sec_rules = [
                    {"id": "SEC-PII-001", "name": "身份证号明文", "regex": r'[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]', "severity": "critical"},
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
                            with warnings.catch_warnings():
                                warnings.simplefilter("ignore", UserWarning)
                                match_count = int(sample.str.contains(sec["regex"], regex=True, na=False).sum())
                        except re.error:
                            continue
                        if match_count > 0:
                            issues.append({
                                "dimension": "security",
                                "rule_id": sec["id"],
                                "column": col,
                                "severity": sec.get("severity", _sec_severity(sec["id"], "warning")),
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
                        "column": col, "severity": _sec_severity("SEC-PII-006", "warning"),
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
                        "column": col, "severity": _sec_severity("SEC-PII-007", "warning"),
                        "description": f"姓名字段 '{col}' 与强 PII 字段({', '.join(_pii_cols[:3])})同表",
                        "suggestion": "评估是否需脱敏；关联强 PII 时按 critical 处置",
                    })

            # SEC-BIZ-001 薪资/收入字段
            for col in df.columns:
                cl = str(col).lower()
                if any(kw in cl for kw in ("salary", "wage", "income", "薪资", "收入", "工资")):
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-BIZ-001",
                        "column": col, "severity": _sec_severity("SEC-BIZ-001", "error"),
                        "description": f"列 '{col}' 含薪资/收入数据，需访问控制+脱敏",
                        "suggestion": "按机密级管控；非授权查询禁止返回明文",
                    })
                # SEC-BIZ-002 医疗健康字段
                if any(kw in cl for kw in ("diagnosis", "medical", "health", "病历", "诊断", "病情")):
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-BIZ-002",
                        "column": col, "severity": _sec_severity("SEC-BIZ-002", "error"),
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
                        "column": _age_col, "severity": _sec_severity("SEC-BIZ-003", "critical"),
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
                            "column": col, "severity": _sec_severity(sid, "warning"),
                            "description": f"列 '{col}' 有 {unmasked_count} 条未脱敏（期望格式如 {example}）",
                            "suggestion": f"按 {sid} 脱敏规则处理",
                        })

            # SEC-CLASS-001 数据分级标注缺失
            try:
                from app.models.datasource import TableMetadata as _TM
                tm_result = await db.execute(
                    select(_TM).where(_TM.datasource_id == _uuid.UUID(datasource_id),
                                      _TM.table_name == table_name)
                )
                tm = tm_result.scalar_one_or_none()
                if tm and not tm.security_level:
                    issues.append({
                        "dimension": "security", "rule_id": "SEC-CLASS-001",
                        "severity": _sec_severity("SEC-CLASS-001", "warning"),
                        "description": f"表 '{table_name}' 缺少数据分级标注（public/internal/confidential/secret）",
                        "suggestion": "补充分级元数据；按分级施加访问控制",
                    })
            except Exception:
                pass  # TableMetadata 模型不存在时跳过

            return {"dimension": "security", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"check_data_security 失败: {e}")
            return {"dimension": "security", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}

    # ==================== 预执行入口（对齐 OpenCode：先执行再分析） ====================

    def _profile_from_df(self, df) -> dict:
        """从 DataFrame 生成数据概览（同步，不加载 DB）"""
        try:
            import pandas as pd
            real_row_count = len(df)
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
            return {"error": str(e)}

    def _check_standards_from_df(self, df, standard_rules=None, skill_rules=None) -> dict:
        """从 DataFrame 执行标准检查（同步，不加载 DB）

        Args:
            skill_rules: 技能专属规则 {"std":[...], "dq":[...], "sec":[...]}，合并到全局规则之外执行
        """
        import pandas as pd
        try:
            issues = []
            columns = list(df.columns)
            # 命名规范
            if not standard_rules or "naming_convention" in standard_rules:
                _sev = _dq_severity("DQ-VAL-001", "warning")
                for col in df.columns:
                    if not re.match(r'^[a-z][a-z0-9_]*$', col) and not re.match(r'^[\u4e00-\u9fff]', col):
                        suggestion = re.sub(r'([A-Z])', r'_\1', col).lower()
                        issues.append({"dimension": "naming_convention", "rule_id": "DQ-VAL-001", "column": col, "severity": _sev, "description": f"列名 '{col}' 不符合 snake_case 命名规范", "suggestion": f"建议重命名为 '{suggestion}'"})
            # 类型一致性
            if not standard_rules or "type_consistency" in standard_rules:
                _sev = _dq_severity("DQ-CON-003", "warning")
                for col in df.columns:
                    non_null = df[col].dropna()
                    if len(non_null) > 0 and non_null.apply(type).nunique() > 1:
                        issues.append({"dimension": "type_consistency", "rule_id": "DQ-CON-003", "column": col, "severity": _sev, "description": f"列 '{col}' 存在混合类型", "suggestion": "建议统一数据类型"})
            # 编码检查
            if not standard_rules or "encoding_check" in standard_rules:
                _sev = _dq_severity("DQ-VAL-001", "warning")
                for col in df.columns:
                    if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == 'object':
                        sample = df[col].dropna().head(100).astype(str)
                        garbled = sample.str.contains(r'[\ufffd\uffef\u00bf]', na=False, regex=True)
                        if garbled.any():
                            issues.append({"dimension": "encoding_check", "rule_id": "DQ-VAL-001", "column": col, "severity": _sev, "description": f"列 '{col}' 疑似包含乱码字符（{garbled.sum()}条）", "suggestion": "建议检查编码格式并转换"})
            # 引用数据标准库做格式正则检查
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
                                issues.append({"dimension": "standard_format", "standard_id": std["id"], "rule_id": "DQ-VAL-001", "column": col, "severity": std.get("severity", "warning"), "description": f"列 '{col}' 有 {invalid_count}/{len(non_null)} 条不符合 {std['id']} {std['name']}", "suggestion": f"按 {std['id']} 格式修正"})
                        except re.error:
                            pass
            except Exception as e:
                logger.warning(f"标准库格式检查失败: {e}")
            # 技能专属标准规则（前缀 SKILL-STD-）
            if skill_rules and skill_rules.get("std"):
                try:
                    from app.services.standards_parser import match_columns as _mc
                    for std in skill_rules["std"]:
                        if not std.get("regex"):
                            continue
                        matched = _mc(columns, std.get("fields", []))
                        for col in matched:
                            non_null = df[col].dropna().astype(str)
                            if len(non_null) == 0:
                                continue
                            try:
                                invalid = ~non_null.str.match(std["regex"])
                                invalid_count = int(invalid.sum())
                                if invalid_count > 0:
                                    issues.append({"dimension": "standard_format", "standard_id": std["id"], "rule_id": "DQ-VAL-001", "column": col, "severity": std.get("severity", "warning"), "description": f"列 '{col}' 有 {invalid_count}/{len(non_null)} 条不符合技能规则 {std['id']} {std['name']}", "suggestion": f"按 {std['id']} 格式修正"})
                            except re.error:
                                pass
                except Exception as e:
                    logger.warning(f"技能标准规则检查失败: {e}")
            return {"dimension": "standards", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"_check_standards_from_df 失败: {e}")
            return {"dimension": "standards", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}

    def _check_quality_from_df(self, df, quality_dimensions=None, skill_rules=None) -> dict:
        """从 DataFrame 执行质量检查（同步，不加载 DB）

        Args:
            skill_rules: 技能专属规则，合并执行 skill_rules["dq"] 中带 regex 的规则
        """
        import pandas as pd
        try:
            issues = []
            total = len(df)
            dq_rules = _load_quality_rules()
            null_thr = 1 - (dq_rules.get("DQ-COM-003", {}).get("threshold_value") or 0.9)
            dupe_thr = dq_rules.get("DQ-UNI-003", {}).get("threshold_value") or 0.01

            # 完整性
            if not quality_dimensions or "completeness" in quality_dimensions:
                for col in df.columns:
                    null_rate = df[col].isna().mean()
                    if null_rate > null_thr:
                        issues.append({"dimension": "completeness", "rule_id": "DQ-COM-003", "column": col, "severity": _dq_severity("DQ-COM-003", "warning"), "description": f"列 '{col}' 空值率 {null_rate:.1%}（阈值 {null_thr:.0%}）", "suggestion": "建议填充默认值或删除空值行", "samples": self._extract_samples(df, df[col].isna(), [col])})

            # 唯一性
            if not quality_dimensions or "uniqueness" in quality_dimensions:
                _id_cols = [c for c in df.columns if str(c).lower().strip() == "id" or str(c).lower().strip().endswith("_id")]
                for col in _id_cols:
                    dup_mask = df[col].dropna().duplicated(keep=False)
                    dup_count = int(dup_mask.sum())
                    if dup_count > 0:
                        dup_vals = df.loc[dup_mask.index[dup_mask], col]
                        issues.append({"dimension": "uniqueness", "rule_id": "DQ-UNI-001", "column": col, "severity": _dq_severity("DQ-UNI-001", "error"), "description": f"主键列 '{col}' 存在 {dup_count} 个重复值", "suggestion": "去重或修正主键生成逻辑", "samples": [{"row": int(idx)+1, "values": {col: str(v)[:80]}} for idx, v in dup_vals.head(5).items()]})
                dupe_mask = df.duplicated(keep=False)
                dupe_count = int(dupe_mask.sum())
                dupe_rate = dupe_count / total if total else 0
                if dupe_count > 0 and dupe_rate > dupe_thr:
                    issues.append({"dimension": "uniqueness", "rule_id": "DQ-UNI-003", "severity": _dq_severity("DQ-UNI-003", "warning"), "description": f"存在 {dupe_count} 条完全重复的行（{dupe_rate:.1%}，阈值 {dupe_thr:.0%}）", "suggestion": "建议执行去重操作", "samples": self._extract_samples(df, dupe_mask)})

            # 有效性
            if not quality_dimensions or "validity" in quality_dimensions:
                for col in df.columns:
                    if pd.api.types.is_numeric_dtype(df[col]):
                        non_null = df[col].dropna()
                        if len(non_null) > 0:
                            q1, q3 = non_null.quantile(0.25), non_null.quantile(0.75)
                            iqr = q3 - q1
                            if iqr > 0:
                                lower, upper = q1 - 3 * iqr, q3 + 3 * iqr
                                outlier_mask = (df[col] < lower) | (df[col] > upper)
                                outlier_count = int(outlier_mask.sum())
                                if outlier_count > 0 and outlier_count / len(non_null) > 0.01:
                                    issues.append({"dimension": "validity", "rule_id": "DQ-VAL-004", "column": col, "severity": _dq_severity("DQ-VAL-004", "warning"), "description": f"列 '{col}' 存在 {outlier_count} 个异常极值（IQR方法，范围[{lower:.2f}, {upper:.2f}]）", "suggestion": "建议检查极值是否合理", "samples": self._extract_samples(df, outlier_mask, [col])})

            # 一致性
            if not quality_dimensions or "consistency" in quality_dimensions:
                cols_low = {str(c).lower(): c for c in df.columns}
                for s_name, e_name in [("start_date", "end_date"), ("start_time", "end_time"), ("begin_date", "end_date"), ("created_at", "updated_at")]:
                    s_col, e_col = cols_low.get(s_name), cols_low.get(e_name)
                    if s_col and e_col:
                        s = pd.to_datetime(df[s_col], errors="coerce")
                        e = pd.to_datetime(df[e_col], errors="coerce")
                        invalid = s.notna() & e.notna() & (e < s)
                        if invalid.any():
                            issues.append({"dimension": "consistency", "rule_id": "DQ-CON-001", "column": f"{s_col}/{e_col}", "severity": _dq_severity("DQ-CON-001", "error"), "description": f"'{e_col}' 早于 '{s_col}' 的记录有 {int(invalid.sum())} 条", "suggestion": "修正结束时间早于开始时间的记录", "samples": self._extract_samples(df, invalid, [s_col, e_col])})

            # 技能专属质量规则（前缀 SKILL-DQ-）：带 regex 的按格式检查，带 legal_values 的按枚举检查
            if skill_rules and skill_rules.get("dq"):
                from app.services.standards_parser import match_columns as _mc
                for rule in skill_rules["dq"]:
                    rid = rule.get("id", "")
                    fields = rule.get("fields") or rule.get("scope_fields") or []
                    matched = _mc(list(df.columns), fields) if fields else []
                    # 枚举合法值检查
                    legal = rule.get("legal_values")
                    if legal:
                        for col in matched:
                            non_null = df[col].dropna().astype(str)
                            if len(non_null) == 0:
                                continue
                            illegal = ~non_null.isin(legal)
                            illegal_count = int(illegal.sum())
                            if illegal_count > 0:
                                issues.append({"dimension": "validity", "rule_id": rid, "column": col, "severity": rule.get("severity", "warning"), "description": f"列 '{col}' 有 {illegal_count}/{len(non_null)} 条不符合技能规则 {rid} {rule.get('name','')} 合法值", "suggestion": f"按 {rid} 修正为合法值"})
                    # 正则格式检查
                    regex = rule.get("regex")
                    if regex:
                        for col in matched:
                            non_null = df[col].dropna().astype(str)
                            if len(non_null) == 0:
                                continue
                            try:
                                invalid = ~non_null.str.match(regex)
                                invalid_count = int(invalid.sum())
                                if invalid_count > 0:
                                    issues.append({"dimension": "validity", "rule_id": rid, "column": col, "severity": rule.get("severity", "warning"), "description": f"列 '{col}' 有 {invalid_count}/{len(non_null)} 条不符合技能规则 {rid} {rule.get('name','')}", "suggestion": f"按 {rid} 格式修正"})
                            except re.error:
                                pass

            return {"dimension": "quality", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"_check_quality_from_df 失败: {e}")
            return {"dimension": "quality", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}

    def _check_security_from_df(self, df, skill_rules=None) -> dict:
        """从 DataFrame 执行安全检查（同步，不加载 DB）

        Args:
            skill_rules: 技能专属规则，合并执行 skill_rules["sec"] 中带 regex 的规则
        """
        import pandas as pd
        try:
            issues = []
            try:
                from app.services.standards_parser import parse_security_rules
                sec_rules = parse_security_rules()
            except Exception:
                sec_rules = []
            if not sec_rules:
                sec_rules = [
                    {"id": "SEC-PII-001", "name": "身份证号明文", "regex": r'[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]', "severity": "critical"},
                    {"id": "SEC-PII-002", "name": "手机号明文", "regex": r'1[3-9]\d{9}', "severity": "critical"},
                    {"id": "SEC-PII-003", "name": "电子邮箱明文", "regex": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', "severity": "error"},
                ]
            # 合并技能专属安全规则
            if skill_rules and skill_rules.get("sec"):
                sec_rules = list(sec_rules) + list(skill_rules["sec"])
            for col in df.columns:
                if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == 'object':
                    sample = df[col].dropna().head(200).astype(str)
                    if len(sample) == 0:
                        continue
                    for sec in sec_rules:
                        if not sec.get("regex"):
                            continue
                        try:
                            with warnings.catch_warnings():
                                warnings.simplefilter("ignore", UserWarning)
                                match_count = int(sample.str.contains(sec["regex"], regex=True, na=False).sum())
                        except re.error:
                            continue
                        if match_count > 0:
                            issues.append({"dimension": "security", "rule_id": sec["id"], "column": col, "severity": sec.get("severity", _sec_severity(sec["id"], "warning")), "description": f"列 '{col}' 疑似包含 {sec['name']}（{match_count}/{len(sample)} 条样本命中）", "suggestion": f"按 {sec['id']} 处置建议脱敏/加密"})
            # 薪资/医疗字段
            for col in df.columns:
                cl = str(col).lower()
                if any(kw in cl for kw in ("salary", "wage", "income", "薪资", "收入", "工资")):
                    issues.append({"dimension": "security", "rule_id": "SEC-BIZ-001", "column": col, "severity": _sec_severity("SEC-BIZ-001", "error"), "description": f"列 '{col}' 含薪资/收入数据，需访问控制+脱敏", "suggestion": "按机密级管控"})
                if any(kw in cl for kw in ("diagnosis", "medical", "health", "病历", "诊断", "病情")):
                    issues.append({"dimension": "security", "rule_id": "SEC-BIZ-002", "column": col, "severity": _sec_severity("SEC-BIZ-002", "error"), "description": f"列 '{col}' 含医疗健康数据，需授权访问", "suggestion": "按机密/秘密级管控"})
            return {"dimension": "security", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"_check_security_from_df 失败: {e}")
            return {"dimension": "security", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}

    async def run_all_checks(self, datasource_id: str, table_name: str, db: AsyncSession, skill_rules=None) -> dict:
        """预执行入口：加载数据1次 → 跑4项检查 → 返回紧凑报告

        Args:
            skill_rules: 技能专属规则 {"std":[...],"dq":[...],"sec":[...]}，合并到全局规则之外执行
        """
        # 清缓存（复查时需要最新数据）
        cache_key = f"{datasource_id}:{table_name}"
        self._cache.pop(cache_key, None)
        
        try:
            df = await self._load_data(datasource_id, table_name, db, use_cache=True)
        except Exception as e:
            return {"error": f"数据加载失败: {e}", "profile": None, "standards": None, "quality": None, "security": None}

        # 同步检查（纯 pandas，共享同一 DataFrame）
        profile = self._profile_from_df(df)
        standards = self._check_standards_from_df(df, skill_rules=skill_rules)
        quality = self._check_quality_from_df(df, skill_rules=skill_rules)
        security = self._check_security_from_df(df, skill_rules=skill_rules)

        return {
            "profile": profile,
            "standards": standards,
            "quality": quality,
            "security": security,
        }

    def format_report(self, results: dict) -> str:
        """格式化检查结果为完整报告（含表格、每条规则详情、样本数据）"""
        lines = []

        if results.get("error"):
            lines.append("## ❌ 检查失败\n%s" % results["error"])
            lines.append("\n（数据加载失败，无法执行检查。请确认数据源和表名是否正确。）")
            return "\n".join(lines)

        # 数据概览
        profile = results.get("profile") or {}
        if "error" in profile:
            lines.append("## 数据概览\n❌ %s" % profile["error"])
        else:
            row_count = profile.get("row_count", 0)
            col_count = profile.get("column_count", 0)
            lines.append("## 数据概览\n总行数: %d, 总列数: %d\n" % (row_count, col_count))
            cols = profile.get("columns", {})
            if cols:
                lines.append("| 列名 | 类型 | 空值数 | 空值率 | 唯一值数 |")
                lines.append("|------|------|--------|--------|----------|")
                for name, info in cols.items():
                    dtype = info.get("dtype", "")
                    null_count = info.get("null_count", 0)
                    null_rate = info.get("null_rate", 0)
                    unique = info.get("unique_count", 0)
                    lines.append("| %s | %s | %d | %.1f%% | %d |" % (name, dtype, null_count, null_rate * 100, unique))

        # 三项检查
        _DIM_RULES = {
            "standards": [
                ("DQ-VAL-001", "命名规范/编码/格式正则"),
                ("DQ-CON-003", "类型一致性"),
                ("DQ-VAL-002", "枚举值合法"),
                ("DQ-VAL-003", "数值范围/约束"),
                ("STD-LOC-001", "地址格式"),
                ("STD-LOC-004", "经纬度范围"),
                ("STD-TIME-003", "Unix时间戳"),
                ("STD-TIME-004", "时间范围一致"),
            ],
            "quality": [
                ("DQ-COM-001", "必填字段空值"),
                ("DQ-COM-002", "主键非空"),
                ("DQ-COM-003", "关键字段完整率"),
                ("DQ-UNI-001", "主键唯一"),
                ("DQ-UNI-002", "业务键唯一"),
                ("DQ-UNI-003", "整行重复"),
                ("DQ-VAL-004", "异常值检测"),
                ("DQ-CON-001", "跨字段逻辑一致"),
            ],
            "security": [
                ("SEC-PII-001", "身份证号明文"),
                ("SEC-PII-002", "手机号明文"),
                ("SEC-PII-003", "电子邮箱明文"),
                ("SEC-PII-004", "银行卡号明文"),
                ("SEC-PII-006", "完整地址明文"),
                ("SEC-PII-007", "姓名字段识别"),
                ("SEC-BIZ-001", "薪资/收入字段"),
                ("SEC-BIZ-002", "医疗健康字段"),
                ("SEC-BIZ-003", "未成年人信息"),
                ("SEC-MASK-001", "手机号脱敏"),
                ("SEC-MASK-002", "身份证脱敏"),
                ("SEC-MASK-003", "邮箱脱敏"),
                ("SEC-MASK-004", "银行卡脱敏"),
                ("SEC-CLASS-001", "数据分级标注"),
            ],
        }
        for dim, label in [("standards", "标准检查"), ("quality", "质量检查"), ("security", "安全检查")]:
            result = results.get(dim) or {}
            issues = result.get("issues", [])
            passed = result.get("passed", len(issues) == 0)
            all_rules = _DIM_RULES.get(dim, [])

            # 按规则 ID 索引 issues
            issues_by_rule = {}
            for issue in issues:
                rid = issue.get("rule_id") or issue.get("standard_id") or ""
                issues_by_rule.setdefault(rid, []).append(issue)

            error_count = sum(1 for i in issues if i.get("severity") in ("error", "critical", "fatal"))
            warning_count = sum(1 for i in issues if i.get("severity") == "warning")

            if passed and not issues:
                lines.append("\n## %s\n✅ 通过（共 %d 项规则）\n" % (label, len(all_rules)))
            elif issues:
                lines.append("\n## %s\n❌ %d 个问题（%d error/critical, %d warning）:\n" % (label, len(issues), error_count, warning_count))

            # 明细表格：列出该维度检查的所有规则及结果
            if all_rules:
                lines.append("| 序号 | 规则ID | 检查项 | 结果 | 说明 |")
                lines.append("|------|--------|--------|------|------|")
                for idx, (rid, rname) in enumerate(all_rules, 1):
                    rule_issues = issues_by_rule.get(rid, [])
                    if not rule_issues:
                        lines.append("| %d | %s | %s | ✅ 通过 | - |" % (idx, rid, rname))
                    else:
                        for ri_idx, ri in enumerate(rule_issues):
                            sev = ri.get("severity", "warning")
                            desc = ri.get("description", "")[:60]
                            col = ri.get("column", "")
                            detail = desc + (f"（列: {col}）" if col else "")
                            mark = {"error": "❌ error", "critical": "❌ critical", "fatal": "⛔ fatal", "warning": "⚠️ warning", "info": "ℹ️ info"}.get(sev, sev)
                            first_col = str(idx) if ri_idx == 0 else ""
                            lines.append("| %s | %s | %s | %s | %s |" % (first_col, rid, rname, mark, detail))
                lines.append("")

            # 有问题时额外列出问题详情（含样本）
            if issues:
                for idx, issue in enumerate(issues, 1):
                    sev = issue.get("severity", "warning")
                    rule_id = issue.get("rule_id") or issue.get("standard_id", "")
                    col = issue.get("column", "")
                    desc = issue.get("description", "")
                    sug = issue.get("suggestion", "")
                    lines.append("### %d. [%s] %s" % (idx, sev.upper(), desc))
                    if rule_id:
                        lines.append("- 规则ID: %s" % rule_id)
                    if col:
                        lines.append("- 列名: %s" % col)
                    if sug:
                        lines.append("- 修复建议: %s" % sug)
                    samples = issue.get("samples", [])
                    if samples:
                        lines.append("- 问题样本（行号→值）:")
                        for s in samples:
                            vals = ", ".join("%s=%s" % (k, v) for k, v in s.get("values", {}).items())
                            lines.append("  - 第%d行: %s" % (s.get("row", 0), vals))
                    lines.append("")

        return "\n".join(lines)


inspector_tools = DataInspectorTools()
