#!/usr/bin/env python3
# -*- coding: utf-8
"""
数据清洗和去重技能 - 主处理脚本
对指定数据表进行批量清洗和去重，直接在原表修改
"""

import pandas as pd
from typing import List, Dict, Any, Optional
import logging
import argparse
import json
import sys
import re


def setup_logging(output_log: Optional[str] = None):
    """配置日志输出"""
    handlers = [logging.StreamHandler(sys.stdout)]
    if output_log:
        try:
            handlers.append(logging.FileHandler(output_log, encoding='utf-8'))
        except:
            pass
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    return logging.getLogger("DataCleaner")


def get_data_accessor():
    """获取数据访问器 - 使用平台注入的函数"""
    # 从全局命名空间获取平台注入的函数
    get_func = globals().get('get_table_data')
    write_func = globals().get('write_table_data')
    
    if get_func and write_func:
        return get_func, write_func
    
    # 尝试从 builtins 获取
    import builtins
    if hasattr(builtins, 'get_table_data') and hasattr(builtins, 'write_table_data'):
        return getattr(builtins, 'get_table_data'), getattr(builtins, 'write_table_data')
    
    return None, None


def query_table_data(datasource: str, table_name: str, logger: logging.Logger = None) -> pd.DataFrame:
    """查询数据表数据"""
    get_func, _ = get_data_accessor()
    
    if get_func is None:
        raise Exception("无法获取数据访问函数，请确保在 DataCrab 平台环境中运行")
    
    try:
        result = get_func(datasource_id=datasource, table_name=table_name)
        if result.get("success"):
            data = result.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                return pd.DataFrame(data)
            elif isinstance(data, pd.DataFrame):
                return data
        raise Exception(result.get('message', '未知错误'))
    except Exception as e:
        raise Exception(f"获取数据失败: {e}")


def write_table_data_back(datasource: str, table_name: str, df: pd.DataFrame, logger: logging.Logger = None) -> Dict[str, Any]:
    """将数据写回原表"""
    _, write_func = get_data_accessor()
    
    if write_func is None:
        raise Exception("无法获取数据写入函数，请确保在 DataCrab 平台环境中运行")
    
    records = df.to_dict(orient='records')
    try:
        result = write_func(
            datasource_id=datasource,
            table_name=table_name,
            data=records,
            if_table_exists="overwrite"
        )
        return result
    except Exception as e:
        raise Exception(f"写入数据失败: {e}")


def clean_data(df: pd.DataFrame, primary_key: str, cleaning_options: Dict[str, bool], logger: logging.Logger) -> pd.DataFrame:
    """执行数据清洗和去重"""
    initial_count = len(df)
    
    remove_empty = cleaning_options.get('remove_empty', True)
    remove_all_empty = cleaning_options.get('remove_all_empty', True)
    deduplicate = cleaning_options.get('deduplicate', True)
    
    # 将空字符串视为空值（CSV 读取后空单元格可能是 "" 而非 NaN）
    df = df.replace('', pd.NA)
    
    # 删除所有列均为空值的行
    if remove_all_empty:
        before = len(df)
        df = df.dropna(how='all')
        logger.info(f"删除全空行: {before - len(df)} 行")
    
    # 基于主键删除空值
    if remove_empty and primary_key and primary_key in df.columns:
        before = len(df)
        df = df.dropna(subset=[primary_key])
        logger.info(f"删除主键空值行: {before - len(df)} 行")
    
    # 基于主键去重
    if deduplicate and primary_key and primary_key in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=[primary_key], keep='first')
        logger.info(f"删除重复行: {before - len(df)} 行")
    
    logger.info(f"总处理结果: 原始 {initial_count} 行 -> 清洗后 {len(df)} 行")
    return df


def format_phone_column(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """将手机号列从 float64 格式化为 11 位数字字符串（STD-TEL-001）"""
    # 使用 resolve_column 查找手机号列
    phone_col = None
    for candidate in ['phone', 'phone_number', 'tel', 'mobile', '手机号', '电话', '手机']:
        resolved = resolve_column(df, candidate)
        if resolved:
            phone_col = resolved
            break

    if phone_col is None:
        logger.info("未检测到手机号列，跳过格式化")
        return df

    logger.info(f"格式化手机号列: {phone_col} (类型: {df[phone_col].dtype})")

    def _format_phone(val):
        if pd.isna(val):
            return val
        try:
            # float64 → int → string
            if isinstance(val, float):
                s = str(int(val))
            else:
                s = str(val).strip().replace(' ', '').replace('-', '')
            # 确保是纯数字且长度为 11
            if s.isdigit() and len(s) == 11:
                return s
            elif s.isdigit() and len(s) < 11:
                logger.warning(f"手机号位数不足 11 位，保留原值: {val}")
                return s
            else:
                logger.warning(f"无法识别的手机号格式，保留原值: {val}")
                return str(val)
        except Exception:
            return str(val)

    df[phone_col] = df[phone_col].apply(_format_phone)
    logger.info(f"手机号格式化完成: {df[phone_col].dtype}")
    return df


def mask_email_column(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """对邮箱列进行脱敏处理（SEC-PII-003）：保留首尾字符，中间用 *** 替换"""
    email_col = None
    for candidate in ['email', 'mail', 'e_mail', '邮箱', '电子邮件', '电子邮箱']:
        resolved = resolve_column(df, candidate)
        if resolved:
            email_col = resolved
            break

    if email_col is None:
        logger.info("未检测到邮箱列，跳过脱敏")
        return df

    logger.info(f"脱敏邮箱列: {email_col}")

    def _mask_email(val):
        if pd.isna(val):
            return val
        s = str(val).strip()
        if '@' not in s:
            return s
        local, domain = s.split('@', 1)
        if len(local) <= 2:
            masked_local = local[0] + '***' if len(local) == 1 else local[0] + '***' + local[-1]
        else:
            masked_local = local[0] + '***' + local[-1]
        return f"{masked_local}@{domain}"

    masked_count = df[email_col].notna().sum()
    df[email_col] = df[email_col].apply(_mask_email)
    logger.info(f"邮箱脱敏完成: {masked_count} 条")
    return df


def main(datasource: str = None, table_names: List[str] = None, primary_key: str = None,
         cleaning_options: Dict[str, bool] = None, output_log: str = None):
    """主处理函数"""
    # 从全局变量获取参数（平台注入方式）
    if datasource is None:
        datasource = globals().get('datasource_id') or globals().get('datasource')
    if table_names is None:
        table_names = globals().get('table_names') or globals().get('tables')
    if primary_key is None:
        primary_key = globals().get('primary_key')
    if cleaning_options is None:
        cleaning_options = globals().get('cleaning_options')
    if output_log is None:
        output_log = globals().get('output_log')
    
    logger = setup_logging(output_log)
    logger.info(f"开始数据清洗，数据源: {datasource}, 表: {table_names}")
    
    if not datasource or not table_names:
        raise ValueError("缺少必要参数: datasource 和 table_names")
    
    if cleaning_options is None:
        cleaning_options = {'remove_empty': True, 'remove_all_empty': True, 'deduplicate': True}
    
    # 确保 table_names 是列表
    if isinstance(table_names, str):
        table_names = [table_names]
    
    results = {'success': True, 'tables_processed': [], 'errors': []}
    
    for table_name in table_names:
        try:
            logger.info(f"处理表: {table_name}")
            df = query_table_data(datasource, table_name, logger)
            logger.info(f"读取数据: {len(df)} 行, {len(df.columns)} 列")
            
            # 确定主键
            pk = primary_key
            if not pk and len(df.columns) > 0:
                pk = df.columns[0]
                logger.info(f"未指定主键，使用第一列 '{pk}' 作为主键")
            
# 执行清洗
            df_cleaned = clean_data(df, pk, cleaning_options, logger)

            # 执行格式化：手机号标准化 + 邮箱脱敏
            df_cleaned = format_phone_column(df_cleaned, logger)
            df_cleaned = mask_email_column(df_cleaned, logger)

            # 写回原表
            write_result = write_table_data_back(datasource, table_name, df_cleaned, logger)
            logger.info(f"写入结果: {write_result}")
            
            if isinstance(write_result, dict) and not write_result.get('success', True):
                raise Exception(f"写入失败: {write_result.get('message', write_result)}")
            
            results['tables_processed'].append({
                'table': table_name,
                'rows_before': len(df),
                'rows_after': len(df_cleaned)
            })
        except Exception as e:
            logger.error(f"处理表 {table_name} 失败: {e}")
            results['errors'].append({'table': table_name, 'error': str(e)})
    
    results['success'] = len(results['errors']) == 0
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='数据清洗和去重')
    parser.add_argument('--datasource', required=True, help='数据源ID')
    parser.add_argument('--tables', required=True, nargs='+', help='表名列表')
    parser.add_argument('--primary-key', default=None, help='主键列名')
    parser.add_argument('--cleaning-options', default='{}', help='清洗选项JSON')
    parser.add_argument('--output-log', default=None, help='日志输出路径')
    
    args = parser.parse_args()
    cleaning_opts = json.loads(args.cleaning_options) if args.cleaning_options else {}
    
    result = main(
        datasource=args.datasource,
        table_names=args.tables,
        primary_key=args.primary_key,
        cleaning_options=cleaning_opts,
        output_log=args.output_log
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))