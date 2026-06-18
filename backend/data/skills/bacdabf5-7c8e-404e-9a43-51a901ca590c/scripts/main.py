"""
数据表分割导出技能主脚本

用法:
    python main.py --datasource_name <数据源名称> --table_name <表名> --split_column <列名> --output_filename <输出文件名> [--mapping_instruction <映射指令>]

示例 - 必选参数:
    python main.py --datasource_name "文物测试数据库" --table_name "文物信息表" --split_column "区县" --output_filename "文物按区县分类"

示例 - 全部参数:
    python main.py --datasource_name "文物测试数据库" --table_name "文物信息表" --split_column "区县" --output_filename "文物按地级市分类" --mapping_instruction "请判断以下区县属于哪个地级市"
"""

import argparse
import json
import pandas as pd
import os
from typing import Optional, Dict, List

def get_ai_category_mapping(values: List[str], instruction: str) -> Dict[str, str]:
    """
    AI分类映射函数（模拟实现）
    
    Args:
        values: 需要映射的原始值列表
        instruction: 映射指令描述
    
    Returns:
        映射字典 {原值: 新分类}
    """
    # 模拟映射逻辑 - 实际应用中应调用LLM API
    # 这里使用简单的规则匹配作为示例
    mapping = {}
    for val in values:
        # 简单示例：根据关键词判断
        if "海淀" in str(val) or "朝阳" in str(val) or "东城" in str(val) or "西城" in str(val):
            mapping[val] = "北京市"
        elif "浦东" in str(val) or "黄浦" in str(val) or "徐汇" in str(val):
            mapping[val] = "上海市"
        elif "天河" in str(val) or "越秀" in str(val) or "荔湾" in str(val):
            mapping[val] = "广州市"
        elif "南山" in str(val) or "福田" in str(val) or "罗湖" in str(val):
            mapping[val] = "深圳市"
        else:
            mapping[val] = "其他"
    
    print(f"AI映射结果: {mapping}")
    return mapping

def export_split_excel(
    df: pd.DataFrame, 
    split_column: str, 
    output_filename: str, 
    mapping_instruction: Optional[str] = None
) -> str:
    """
    核心处理函数：根据分割列或AI映射结果将DataFrame分割并写入Excel的不同Sheet。
    
    Args:
        df (pd.DataFrame): 待处理的源数据表。
        split_column (str): 用于分割的列名。
        output_filename (str): 输出文件名（不含扩展名）。
        mapping_instruction (Optional[str]): AI映射指令，如为空则直接按列值分割。
    
    Returns:
        str: 生成的文件路径。
    """
    if df.empty:
        print("输入数据为空，无法执行分割操作。")
        return ""
    
    if split_column not in df.columns:
        print(f"错误：数据表中不存在列 '{split_column}'")
        return ""

    print(f"开始处理数据，总行数: {len(df)}")
    
    if mapping_instruction:
        print(f"检测到映射指令: '{mapping_instruction}'，正在启用AI辅助分类...")
        unique_values = df[split_column].dropna().unique().tolist()
        category_map = get_ai_category_mapping(unique_values, mapping_instruction)
        df['__split_category__'] = df[split_column].apply(
            lambda x: category_map.get(x, "未分类") if pd.notna(x) else "未分类"
        )
        group_column = '__split_category__'
    else:
        print(f"直接按列 '{split_column}' 的值进行分割...")
        group_column = split_column

    grouped = df.groupby(group_column, dropna=False)
    file_path = f"{output_filename}.xlsx"
    
    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            for category, group_df in grouped:
                sheet_name = str(category)[:31].replace(':', '').replace('\\', '').replace('/', '').replace('?', '').replace('*', '').replace('[', '').replace(']', '')
                print(f"正在写入 Sheet: {sheet_name} (行数: {len(group_df)})")
                export_df = group_df.drop(columns=['__split_category__'], errors='ignore')
                export_df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        print(f"导出完成: {file_path}")
        return file_path
    except Exception as e:
        print(f"导出失败: {e}")
        return ""

def main():
    parser = argparse.ArgumentParser(description='数据表分割导出技能')
    parser.add_argument('--datasource_name', required=True, help='数据源名称')
    parser.add_argument('--table_name', required=True, help='数据表名称')
    parser.add_argument('--split_column', required=True, help='分割列名')
    parser.add_argument('--output_filename', required=True, help='输出文件名（不含扩展名）')
    parser.add_argument('--mapping_instruction', default=None, help='AI映射指令（可选）')
    
    args = parser.parse_args()
    
    # 模拟数据 - 实际应用中应从数据源读取
    # 示例数据
    df = pd.DataFrame({
        '区县': ['海淀区', '朝阳区', '东城区', '浦东新区', '黄浦区', '天河区', '南山区'],
        '文物名称': ['故宫', '颐和园', '天坛', '东方明珠', '外滩建筑群', '陈家祠', '锦绣中华'],
        '级别': ['世界遗产', '世界遗产', '世界遗产', '5A景区', '4A景区', '4A景区', '5A景区']
    })
    
    print(f"参数: datasource_name={args.datasource_name}, table_name={args.table_name}, split_column={args.split_column}, output_filename={args.output_filename}")
    
    export_split_excel(
        df=df,
        split_column=args.split_column,
        output_filename=args.output_filename,
        mapping_instruction=args.mapping_instruction
    )

if __name__ == '__main__':
    main()
