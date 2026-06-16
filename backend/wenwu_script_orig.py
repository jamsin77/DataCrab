import pandas as pd
import re
from datetime import datetime

def search_wenwu_by_epoch(epoch_name, count=100, datasource_id="2e134cd5-7764-4a5c-a237-4bd79a51892d"):
    """
    根据指定年代查询文物数据
    
    参数:
    epoch_name (str): 要查询的年代（如"汉代"、"唐代"等）
    count (int): 要返回的文物数量，默认为100
    datasource_id (str): 文物数据源的UUID
    
    返回:
    pandas.DataFrame: 查询结果的DataFrame
    """
    
    print(f"\n正在查询 {epoch_name} 的文物数据...")
    
    try:
        # 查询文物数据表的所有数据
        df = query_table_data(
            datasource_id=datasource_id,
            table_name="文物",
            limit=2000  # 增加查询数量，确保能找到足够的数据
        )
        
        if df.empty:
            print(f"未找到 {epoch_name} 的文物数据，数据源可能为空")
            return None
            
        # 根据年代筛选数据
        # 检查'时代'列是否存在
        if '时代' not in df.columns:
            print("数据源中缺少'时代'列")
            return None
            
        # 构建匹配模式，支持多个关键词
        keywords = [epoch_name]
        
        # 根据历史年代表添加相关关键词
        if epoch_name == "汉代":
            keywords.extend(["东汉", "西汉", "汉"])
        elif epoch_name == "唐代":
            keywords.extend(["唐"])
        elif epoch_name == "宋代":
            keywords.extend(["北宋", "南宋", "宋"])
        elif epoch_name == "元代":
            keywords.extend(["元"])
        elif epoch_name == "明代":
            keywords.extend(["明"])
        elif epoch_name == "清代":
            keywords.extend(["清"])
            
        # 构建正则表达式模式
        pattern = '|'.join(keywords)
        filtered_df = df[df['时代'].str.contains(pattern, na=False, case=False, regex=True)]
        
        if len(filtered_df) == 0:
            print(f"未找到 {epoch_name} 的文物数据")
            return None
            
        # 按名称排序
        if '名称' in filtered_df.columns:
            filtered_df = filtered_df.sort_values(by='名称')
        
        # 限制返回数量
        result_df = filtered_df.head(count)
        
        print(f"\n找到 {len(result_df)} 个 {epoch_name} 文物:")
        print("=" * 100)
        
        # 打印结果
        for idx, row in result_df.iterrows():
            print(f"{idx+1:3d}. {row.get('名称', '未知名称')}")
            print(f"    时代: {row.get('时代', '未知')}")
            print(f"    地址: {row.get('地址', '未知')}")
            print(f"    批次: {row.get('批次', '未知')}")
            
            # 打印其他列（如果有）
            for col in row.index:
                if col not in ['名称', '时代', '地址', '批次', 'id'] and pd.notna(row[col]):
                    if isinstance(row[col], str) and row[col].strip():
                        print(f"    {col}: {row[col]}")
            print()
        
        print("=" * 100)
        print(f"共显示 {len(result_df)} 个文物")
        
        return result_df
        
    except Exception as e:
        print(f"查询过程中发生错误: {e}")
        return None

def search_specific_epoch(epoch_name, count=100):
    """
    查询特定年代的文物
    
    参数:
    epoch_name (str): 要查询的年代（如"汉代"、"唐代"等）
    count (int): 要返回的文物数量，默认为100
    """
    # 中国历史年代表
    chinese_history_timeline = [
        ("旧石器时代", "约300万年前-1万年前"),
        ("新石器时代", "约1万年前-公元前2070年"),
        ("夏代", "约公元前2070年-公元前1600年"),
        ("商代", "约公元前1600年-公元前1046年"),
        ("西周", "公元前1046年-公元前771年"),
        ("东周", "公元前771年-公元前256年"),
        ("春秋时期", "公元前770年-公元前476年"),
        ("战国时期", "公元前475年-公元前221年"),
        ("秦代", "公元前221年-公元前207年"),
        ("汉代", "公元前202年-公元220年"),
        ("三国时期", "220年-280年"),
        ("晋代", "265年-420年"),
        ("南北朝", "420年-589年"),
        ("隋代", "581年-618年"),
        ("唐代", "618年-907年"),
        ("五代十国", "907年-979年"),
        ("宋代", "960年-1279年"),
        ("辽代", "907年-1125年"),
        ("金代", "1115年-1234年"),
        ("西夏", "1038年-1227年"),
        ("元代", "1271年-1368年"),
        ("明代", "1368年-1644年"),
        ("清代", "1644年-1912年"),
        ("民国", "1912年-1949年"),
        ("中华人民共和国", "1949年至今")
    ]
    
    print(f"\n正在查询 {epoch_name} 的文物数据...")
    
    try:
        # 查询文物数据表
        df = query_table_data(
            datasource_id="2e134cd5-7764-4a5c-a237-4bd79a51892d",
            table_name="文物",
            limit=2000
        )
        
        if df.empty:
            print(f"未找到 {epoch_name} 的文物数据")
            return None
            
        # 按年代筛选数据
        filtered_df = df[df['时代'].str.contains(epoch_name, na=False, case=False)]
        
        if len(filtered_df) == 0:
            print(f"未找到 {epoch_name} 的文物数据")
            return None
            
        # 按名称排序
        if '名称' in filtered_df.columns:
            filtered_df = filtered_df.sort_values(by='名称')
        
        # 限制返回数量
        result_df = filtered_df.head(count)
        
        print(f"\n找到 {len(result_df)} 个 {epoch_name} 文物:")
        print("=" * 100)
        
        # 打印结果
        for idx, row in result_df.iterrows():
            print(f"{idx+1:3d}. {row.get('名称', '未知名称')}")
            print(f"    时代: {row.get('时代', '未知')}")
            print(f"    地址: {row.get('地址', '未知')}")
            print(f"    批次: {row.get('批次', '未知')}")
            
            # 打印其他列
            for col in row.index:
                if col not in ['名称', '时代', '地址', '批次', 'id'] and pd.notna(row[col]):
                    if isinstance(row[col], str) and row[col].strip():
                        print(f"    {col}: {row[col]}")
            print()
        
        print("=" * 100)
        print(f"共显示 {len(result_df)} 个文物")
        
        return result_df
        
    except Exception as e:
        print(f"查询过程中发生错误: {e}")
        return None

def display_history_timeline():
    """显示中国历史年代表"""
    chinese_history_timeline = [
        ("旧石器时代", "约300万年前-1万年前"),
        ("新石器时代", "约1万年前-公元前2070年"),
        ("夏代", "约公元前2070年-公元前1600年"),
        ("商代", "约公元前1600年-公元前1046年"),
        ("西周", "公元前1046年-公元前771年"),
        ("东周", "公元前771年-公元前256年"),
        ("春秋时期", "公元前770年-公元前476年"),
        ("战国时期", "公元前475年-公元前221年"),
        ("秦代", "公元前221年-公元前207年"),
        ("汉代", "公元前202年-公元220年"),
        ("三国时期", "220年-280年"),
        ("晋代", "265年-420年"),
        ("南北朝", "420年-589年"),
        ("隋代", "581年-618年"),
        ("唐代", "618年-907年"),
        ("五代十国", "907年-979年"),
        ("宋代", "960年-1279年"),
        ("辽代", "907年-1125年"),
        ("金代", "1115年-1234年"),
        ("西夏", "1038年-1227年"),
        ("元代", "1271年-1368年"),
        ("明代", "1368年-1644年"),
        ("清代", "1644年-1912年"),
        ("民国", "1912年-1949年"),
        ("中华人民共和国", "1949年至今")
    ]
    
    print("\n中国历史年代表:")
    print("=" * 60)
    for era, period in chinese_history_timeline:
        print(f"{era:<15} ({period})")
    print("=" * 60)

def main():
    """主程序"""
    while True:
        print("\n文物查询系统")
        print("1. 查询汉代文物（推荐）")
        print("2. 查询指定年代的文物")
        print("3. 查看历史年代表")
        print("4. 退出")
        
        choice = input("\n请选择操作 (1-4): ").strip()
        
        if choice == "1":
            # 专门查询汉代文物
            try:
                count = int(input("请输入要显示的汉代文物数量 (默认100): ").strip() or "100")
            except ValueError:
                count = 100
            
            result = search_specific_epoch("汉代", count)
            
        elif choice == "2":
            # 查询指定年代
            epoch_name = input("请输入要查询的年代 (如: 汉代, 唐代): ").strip()
            if not epoch_name:
                print("请输入有效的年代名称")
                continue
                
            try:
                count = int(input("请输入要显示的文物数量 (默认100): ").strip() or "100")
            except ValueError:
                count = 100
            
            result = search_wenwu_by_epoch(epoch_name, count)
            
        elif choice == "3":
            display_history_timeline()
            
        elif choice == "4":
            print("感谢使用，再见！")
            break
            
        else:
            print("无效的选择，请重新输入")

if __name__ == "__main__":
    print("文物查询系统")
    print("注意：此脚本需要连接到文物数据源")
    print("使用的数据库: 文物测试数据")
    print("=" * 50)
    main()