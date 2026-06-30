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

            if not quality_dimensions or "completeness" in quality_dimensions:
                for col in df.columns:
                    null_rate = df[col].isna().mean()
                    if null_rate > 0.1:
                        issues.append({
                            "dimension": "completeness",
                            "rule_id": "DQ-COM-003",
                            "column": col,
                            "severity": "error" if null_rate > 0.3 else "warning",
                            "description": f"列 '{col}' 空值率 {null_rate:.1%}",
                            "suggestion": "建议填充默认值或删除空值行",
                        })

            if not quality_dimensions or "uniqueness" in quality_dimensions:
                dupe_count = total - len(df.drop_duplicates())
                if dupe_count > 0:
                    issues.append({
                        "dimension": "uniqueness",
                        "rule_id": "DQ-UNI-003",
                        "severity": "error",
                        "description": f"存在 {dupe_count} 条完全重复的行（{dupe_count/total:.1%}）",
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
                                if outlier_count > 0:
                                    issues.append({
                                        "dimension": "validity",
                                        "rule_id": "DQ-VAL-004",
                                        "column": col,
                                        "severity": "warning",
                                        "description": f"列 '{col}' 存在 {outlier_count} 个异常极值（IQR方法检测）",
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
                    {"id": "SEC-PII-001", "name": "身份证号明文", "regex": r'[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]', "severity": "critical"},
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
