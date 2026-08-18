#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具函数模块
"""

import pandas as pd
from typing import Dict, Any, Optional

def detect_data_quality(df: pd.DataFrame) -> Dict[str, Any]:
    """
    检测数据质量
    
    Args:
        df: 输入的数据DataFrame
        
    Returns:
        数据质量统计字典
    """
    quality_stats = {
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "missing_values": df.isnull().sum().to_dict(),
        "duplicate_rows": df.duplicated().sum(),
        "data_types": df.dtypes.to_dict(),
        "memory_usage": df.memory_usage(deep=True).sum()
    }
    
    return quality_stats

def generate_report(df: pd.DataFrame, table_name: str, cleaning_actions: list) -> str:
    """
    生成清洗报告
    
    Args:
        df: 清洗后的数据DataFrame
        table_name: 表名
        cleaning_actions: 执行的清洗操作列表
        
    Returns:
        清洗报告字符串
    """
    report = []
    report.append(f"# 数据清洗报告 - {table_name}")
    report.append(f"## 数据概览")
    report.append(f"- 行数: {len(df)}")
    report.append(f"- 列数: {len(df.columns)}")
    report.append(f"## 执行的清洗操作")
    
    for action in cleaning_actions:
        report.append(f"- {action}")
    
    report.append("## 数据质量统计")
    quality_stats = detect_data_quality(df)
    for key, value in quality_stats.items():
        report.append(f"- {key}: {value}")
    
    return "\n".join(report)