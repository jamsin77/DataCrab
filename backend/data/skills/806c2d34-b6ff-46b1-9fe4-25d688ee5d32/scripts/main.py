#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据清洗和去重主处理脚本
"""

import pandas as pd
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

def clean_and_deduplicate_data(
    df: pd.DataFrame,
    cleaning_options: Optional[Dict[str, Any]] = None,
    table_name: str = "unknown"
) -> pd.DataFrame:
    """
    清洗和去重处理函数
    
    Args:
        df: 输入的数据DataFrame
        cleaning_options: 清洗选项配置
        table_name: 表名（用于日志记录）
        
    Returns:
        清洗后的DataFrame
    """
    # 初始化日志
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(f"DataCleaner_{table_name}")
    logger.info(f"开始处理表: {table_name}")
    logger.info(f"原始数据形状: {df.shape}")
    
    # 默认清洗选项
    if cleaning_options is None:
        cleaning_options = {
            "remove_empty": True,
            "deduplicate_columns": None,
            "convert_types": {}
        }
    
    # 记录原始数据质量
    logger.info(f"原始数据缺失值统计:\n{df.isnull().sum()}")
    
    # 1. 空值处理
    if cleaning_options.get("remove_empty", True):
        original_count = len(df)
        df = df.dropna(how='all')  # 删除全为空的行
        df = df.dropna(subset=cleaning_options.get("deduplicate_columns", []))  # 在去重列中删除空值
        logger.info(f"删除全空行后数据形状: {df.shape} (删除了 {original_count - len(df)} 行)")
    
    # 2. 数据类型转换
    type_conversions = cleaning_options.get("convert_types", {})
    for column, dtype in type_conversions.items():
        if column in df.columns:
            try:
                if dtype == 'datetime':
                    df[column] = pd.to_datetime(df[column])
                elif dtype == 'numeric':
                    df[column] = pd.to_numeric(df[column], errors='coerce')
                else:
                    df[column] = df[column].astype(dtype)
                logger.info(f"列 {column} 已转换为 {dtype} 类型")
            except Exception as e:
                logger.warning(f"列 {column} 类型转换失败: {str(e)}")
    
    # 3. 去重处理
    deduplicate_columns = cleaning_options.get("deduplicate_columns")
    if deduplicate_columns:
        if not isinstance(deduplicate_columns, list):
            deduplicate_columns = [deduplicate_columns]
        
        # 检查指定的列是否存在
        existing_columns = [col for col in deduplicate_columns if col in df.columns]
        if not existing_columns:
            logger.warning("指定的去重列不存在，跳过去重操作")
        else:
            original_count = len(df)
            df = df.drop_duplicates(subset=existing_columns, keep='first')
            logger.info(f"去重后数据形状: {df.shape} (删除了 {original_count - len(df)} 重复行)")
            logger.info(f"基于列 {existing_columns} 进行去重")
    
    # 记录最终数据质量
    logger.info(f"处理后数据缺失值统计:\n{df.isnull().sum()}")
    logger.info(f"处理完成，最终数据形状: {df.shape}")
    
    return df

def process_tables(
    datasource_id: str,
    table_names: List[str],
    cleaning_options: Optional[Dict[str, Any]] = None,
    output_log: Optional[str] = None
) -> Dict[str, pd.DataFrame]:
    """
    处理多个数据表的主函数
    
    Args:
        datasource_id: 数据源ID
        table_names: 数据表名称列表
        cleaning_options: 清洗选项配置
        output_log: 日志输出路径
        
    Returns:
        处理后的数据表字典 {表名: DataFrame}
    """
    # 配置日志输出
    if output_log:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(output_log),
                logging.StreamHandler()
            ]
        )
    else:
        logging.basicConfig(level=logging.INFO)
    
    logger = logging.getLogger("MainProcessor")
    logger.info(f"开始处理数据源: {datasource_id}")
    logger.info(f"待处理表: {', '.join(table_names)}")
    
    results = {}
    
    for table_name in table_names:
        try:
            logger.info(f"正在处理表: {table_name}")
            
            # 查询表数据
            df = query_table_data(datasource_id, table_name)
            
            # 获取表结构
            schema = get_table_schema(datasource_id, table_name)
            logger.info(f"表结构: {schema}")
            
            # 执行清洗和去重
            cleaned_df = clean_and_deduplicate_data(
                df=df,
                cleaning_options=cleaning_options,
                table_name=table_name
            )
            
            # 保存结果
            results[table_name] = cleaned_df
            
            logger.info(f"表 {table_name} 处理完成")
            
        except Exception as e:
            logger.error(f"处理表 {table_name} 时发生错误: {str(e)}")
            continue
    
    logger.info(f"所有表处理完成，共处理 {len(results)} 个表")
    return results

def main():
    """
    主函数，用于命令行执行
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="数据清洗和去重工具")
    parser.add_argument("--datasource", required=True, help="数据源名称")
    parser.add_argument("--tables", nargs="+", required=True, help="要处理的表名列表")
    parser.add_argument("--output-log", help="日志输出路径")
    
    # 清洗选项参数
    parser.add_argument("--no-remove-empty", action="store_false", dest="remove_empty", 
                       help="不删除空值记录")
    parser.add_argument("--deduplicate-columns", nargs="+", 
                       help="用于去重的列名列表")
    parser.add_argument("--convert-types", nargs="*", 
                       help="数据类型转换，格式: 列名1:类型1,列名2:类型2")
    
    args = parser.parse_args()
    
    # 获取数据源ID
    datasource_id = get_datasource_id_by_name(args.datasource)
    if not datasource_id:
        print(f"错误: 未找到数据源 {args.datasource}")
        return
    
    # 解析清洗选项
    cleaning_options = {
        "remove_empty": args.remove_empty if hasattr(args, 'remove_empty') else True
    }
    
    if args.deduplicate_columns:
        cleaning_options["deduplicate_columns"] = args.deduplicate_columns
    
    if args.convert_types:
        type_mapping = {}
        for item in args.convert_types:
            if ":" in item:
                col, dtype = item.split(":", 1)
                type_mapping[col] = dtype
        cleaning_options["convert_types"] = type_mapping
    
    # 处理表
    results = process_tables(
        datasource_id=datasource_id,
        table_names=args.tables,
        cleaning_options=cleaning_options,
        output_log=args.output_log
    )
    
    # 输出处理结果摘要
    print("\n处理结果摘要:")
    for table_name, df in results.items():
        print(f"表 {table_name}: {df.shape[0]} 行, {df.shape[1]} 列")
    
    return results

if __name__ == "__main__":
    main()