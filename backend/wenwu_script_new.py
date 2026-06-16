import pandas as pd
import re


def _strip_dynasty_suffix(name):
    return re.sub(r"(代|朝|时期|时代)$", "", name)


def search_wenwu_by_epoch(epoch_name, count=100, datasource_name="文物测试数据"):
    """
    根据指定年代查询文物数据（模糊匹配）

    参数:
    epoch_name (str): 年代名称，如"隋代"、"汉代"、"唐"等
    count (int): 返回数量，默认100
    datasource_name (str): 数据源名称，默认"文物测试数据"

    返回:
    pandas.DataFrame
    """
    print(f"\n正在查询 {epoch_name} 的文物数据...")

    try:
        datasource_id = get_datasource_id_by_name(datasource_name)
        print(f"数据源: {datasource_name} ({datasource_id[:8]}...)")
    except RuntimeError as e:
        print(f"数据源错误: {e}")
        return None

    try:
        df = query_table_data(
            datasource_id=datasource_id,
            table_name="文物",
            limit=5000,
        )

        if df.empty:
            print(f"数据源为空")
            return None

        if "时代" not in df.columns:
            print("数据源中缺少'时代'列")
            return None

        core = _strip_dynasty_suffix(epoch_name)
        keywords = [epoch_name]
        if core != epoch_name and len(core) >= 1:
            keywords.append(core)

        pattern = "|".join(keywords)
        print(f"匹配模式: {pattern}")

        filtered_df = df[df["时代"].str.contains(pattern, na=False, case=False, regex=True)]

        if len(filtered_df) == 0:
            print(f"未找到匹配 {epoch_name} 的文物数据")
            return None

        if "名称" in filtered_df.columns:
            filtered_df = filtered_df.sort_values(by="名称")

        result_df = filtered_df.head(count)

        print(f"\n找到 {len(result_df)} 个 {epoch_name} 文物:")
        print("=" * 80)

        for i, (_, row) in enumerate(result_df.iterrows()):
            print(f"{i+1:3d}. {row.get('名称', '未知')}")
            print(f"    时代: {row.get('时代', '未知')}")
            print(f"    地址: {row.get('地址', '未知')}")
            print(f"    批次: {row.get('批次', '未知')}")
            for col in row.index:
                if col not in ["名称", "时代", "地址", "批次", "id"] and pd.notna(row[col]):
                    val = str(row[col]).strip()
                    if val:
                        print(f"    {col}: {val}")
            print()

        print("=" * 80)
        print(f"共显示 {len(result_df)} 个文物")

        return result_df

    except Exception as e:
        print(f"查询过程中发生错误: {e}")
        return None


def display_history_timeline():
    """显示中国历史年代表"""
    timeline = [
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
        ("中华人民共和国", "1949年至今"),
    ]

    print("\n中国历史年代表:")
    print("=" * 50)
    for era, period in timeline:
        print(f"  {era:<12} {period}")
    print("=" * 50)


def main():
    while True:
        print("\n文物查询系统")
        print("1. 查询汉代文物")
        print("2. 查询指定年代的文物")
        print("3. 查看历史年代表")
        print("4. 退出")

        choice = input("\n请选择 (1-4): ").strip()

        if choice == "1":
            try:
                count = int(input("数量 (默认100): ").strip() or "100")
            except ValueError:
                count = 100
            search_wenwu_by_epoch("汉代", count)

        elif choice == "2":
            name = input("年代 (如: 隋代, 唐代): ").strip()
            if not name:
                print("请输入有效年代名称")
                continue
            try:
                count = int(input("数量 (默认100): ").strip() or "100")
            except ValueError:
                count = 100
            search_wenwu_by_epoch(name, count)

        elif choice == "3":
            display_history_timeline()

        elif choice == "4":
            print("再见！")
            break
        else:
            print("无效选择")


if __name__ == "__main__":
    main()