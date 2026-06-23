"""
数据表分割导出技能主脚本
"""

import argparse
import pandas as pd
import os
from typing import Optional, Dict, List

# ==================== 省份名称映射表 ====================
PROVINCE_MAP = {
    "北京": "北京市", "天津": "天津市", "上海": "上海市", "重庆": "重庆市",
    "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
    "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
    "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
    "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
    "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
    "甘肃": "甘肃省", "青海": "青海省", "台湾": "台湾省",
    "内蒙古": "内蒙古自治区", "广西": "广西壮族自治区", "西藏": "西藏自治区",
    "宁夏": "宁夏回族自治区", "新疆": "新疆维吾尔自治区",
    "香港": "香港特别行政区", "澳门": "澳门特别行政区"
}

def get_ai_category_mapping(values: List[str], instruction: str) -> Dict[str, str]:
    """
    简单映射：根据地址字符串前缀或包含的省份名进行映射
    匹配不到则映射为 "其他"
    """
    mapping = {}
    for val in values:
        val_str = str(val).strip()
        matched = False
        
        for prov_key, prov_name in PROVINCE_MAP.items():
            if prov_key in val_str:
                mapping[val] = prov_name
                matched = True
                break
                
        if not matched:
            mapping[val] = "其他"
            
    print(f"映射结果: {mapping}")
    return mapping

def export_split_excel(df: pd.DataFrame, split_column: str, output_filename: str, mapping_instruction: Optional[str] = None, output_dir: Optional[str] = None) -> str:
    """分割数据表并导出为Excel多Sheet"""
    if df.empty:
        print("输入数据为空，无法执行分割操作。")
        return ""
    
    if split_column not in df.columns:
        print(f"错误：数据表中不存在列 '{split_column}'，可用列: {list(df.columns)}")
        return ""

    print(f"开始处理数据，总行数: {len(df)}")
    
    if mapping_instruction:
        print(f"检测到映射指令: '{mapping_instruction}'，正在启用智能辅助分类...")
        unique_values = df[split_column].dropna().unique().tolist()
        category_map = get_ai_category_mapping(unique_values, mapping_instruction)
        df['__split_category__'] = df[split_column].apply(lambda x: category_map.get(x, "其他") if pd.notna(x) else "其他")
        group_column = '__split_category__'
    else:
        print(f"直接按列 '{split_column}' 的值进行分割...")
        group_column = split_column

    grouped = df.groupby(group_column, dropna=False)
    
    base_name = os.path.splitext(os.path.basename(output_filename))[0]
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, f"{base_name}.xlsx")
    else:
        file_path = f"{base_name}.xlsx"
    
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
    parser.add_argument('--datasource', required=True, help='数据源名称或ID')
    parser.add_argument('--tables', nargs='+', required=True, help='数据表名称')
    parser.add_argument('--table_names', nargs='+', help='数据表名称（别名）')
    parser.add_argument('--split_column', required=True, help='分割列名')
    parser.add_argument('--output_filename', required=True, help='输出文件名或路径')
    parser.add_argument('--mapping_instruction', default=None, help='AI映射指令')
    parser.add_argument('--datasource_id', default=None, help='数据源ID')
    parser.add_argument('--output_dir', default=None, help='输出目录')
    
    args = parser.parse_args()
    
    table_name = args.tables[0] if args.tables else (args.table_names[0] if args.table_names else '')
    print(f"参数: datasource={args.datasource}, table={table_name}, split_column={args.split_column}")
    
    ds_id = args.datasource_id or args.datasource
    print(f"正在从数据源 '{ds_id}' 获取表 '{table_name}'...")
    
    try:
        result = query_table_data(ds_id, table_name)
        if result.get("success") and result.get("data"):
            df = pd.DataFrame(result["data"])
            if result.get("columns"):
                df = df[[c for c in result["columns"] if c in df.columns]]
            print(f"成功获取数据，共 {len(df)} 行")
            print(f"数据列: {list(df.columns)}")
        else:
            print(f"查询数据失败: {result}")
            return
    except Exception as e:
        print(f"获取数据失败: {e}")
        return
    
    output_dir = args.output_dir
    output_filename = args.output_filename
    if not output_dir and output_filename:
        parent = os.path.dirname(output_filename)
        if parent:
            output_dir = parent
            output_filename = os.path.basename(output_filename)
    
    export_split_excel(df, args.split_column, output_filename, args.mapping_instruction, output_dir)