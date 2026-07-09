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
        df = await connector.get_table_data(table_name, page=1, page_size=page_size)
        await connector.close()
        return df

    async def profile_data(self, datasource_id: str, table_name: str, db: AsyncSession) -> dict:
        try:
            df = await self._load_data(datasource_id, table_name, db)
            profile = {
                "row_count": len(df),
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

            null_thr = _thr("DQ-COM-003", 0.1)          # 空值率阈值
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

            return {"dimension": "security", "passed": len(issues) == 0, "issues": issues}
        except Exception as e:
            logger.error(f"check_data_security 失败: {e}")
            return {"dimension": "security", "passed": False, "issues": [{"severity": "error", "description": str(e)}]}


inspector_tools = DataInspectorTools()
