"""
自然语言数据处理CLI演示工具

使用方法:
    python nl_data_cli.py --data data.csv --query "选择姓名和年龄列"
    python nl_data_cli.py --data data.xlsx --query "筛选销售额大于1000的记录"
    python nl_data_cli.py --demo

示例:
    --data: CSV/Excel/JSON数据文件路径
    --query: 自然语言描述
    --demo: 运行交互式演示
"""

import asyncio
import argparse
import pandas as pd
from pathlib import Path
import sys
import os

# 添加backend路径
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.services.nl_data_processor import (
    NaturalLanguageDataProcessor,
    DataProcessingRequest,
    DataProcessingResponse
)
from app.services.skill_library import skill_library


class NLDataCLI:
    """自然语言数据处理CLI"""

    def __init__(self):
        self.processor = NaturalLanguageDataProcessor()

    async def process_file(
        self,
        file_path: str,
        query: str,
        output_path: str = None
    ) -> DataProcessingResponse:
        """处理文件"""
        # 加载数据
        print(f"\n📂 加载文件: {file_path}")
        df = self._load_file(file_path)
        print(f"   数据形状: {df.shape[0]}行 x {df.shape[1]}列")
        print(f"   列名: {list(df.columns)}")

        # 显示数据预览
        print("\n📊 数据预览:")
        print(df.head(5).to_string())

        # 构建请求
        request = DataProcessingRequest(
            natural_language=query,
            input_data=df,
            session_id="cli_session",
            context={"mode": "cli"}
        )

        # 处理
        print(f"\n🤖 处理请求: \"{query}\"")
        print("-" * 50)

        result = await self.processor.process(request)

        # 显示结果
        self._display_result(result)

        # 保存输出
        if output_path and result.output_data:
            self._save_output(result.output_data, output_path)

        return result

    async def interactive_demo(self):
        """交互式演示"""
        print("\n" + "=" * 60)
        print("  自然语言数据处理演示")
        print("=" * 60)
        print("\n这个工具让你可以用自然语言描述数据处理需求，")
        print("系统会自动理解你的意图并执行相应操作。")
        print("\n支持的操作:")
        print("  - 列选择: '选择姓名和年龄列'")
        print("  - 数据过滤: '筛选销售额大于1000的记录'")
        print("  - 分组聚合: '按地区统计销售总额'")
        print("  - 数据排序: '按销售额降序排列'")
        print("  - 空值处理: '删除空值行' 或 '用0填充空值'")
        print("  - 组合操作: '选择姓名列，按年龄升序排序'")
        print("-" * 60)

        # 先初始化技能库
        print("\n⚙️ 初始化技能库...")
        await skill_library.initialize()
        print(f"✅ 已加载 {len(skill_library.skills)} 个技能")

        # 加载示例数据
        demo_df = self._create_demo_data()

        print("\n📊 示例数据:")
        print(demo_df.head(10).to_string())
        print(f"\n列名: {list(demo_df.columns)}")

        # 交互循环
        while True:
            print("\n" + "-" * 50)
            print("请输入你的数据处理需求 (输入 'quit' 退出):")

            try:
                query = input("\n> ").strip()

                if query.lower() in ['quit', 'exit', 'q']:
                    print("\n再见! 👋")
                    break

                if not query:
                    print("请输入有效的查询")
                    continue

                # 处理
                request = DataProcessingRequest(
                    natural_language=query,
                    input_data=demo_df,
                    session_id="demo_session",
                    context={"mode": "demo"}
                )

                print(f"\n🤖 正在处理...")
                result = await self.processor.process(request)

                self._display_result(result)

                # 如果成功，更新demo数据供后续使用
                if result.success and result.output_data:
                    demo_df = result.output_data
                    print(f"\n📊 当前数据已更新，形状: {demo_df.shape}")

            except KeyboardInterrupt:
                print("\n\n再见! 👋")
                break
            except Exception as e:
                print(f"\n❌ 错误: {e}")

    def _load_file(self, file_path: str) -> pd.DataFrame:
        """加载文件"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if path.suffix == '.csv':
            return pd.read_csv(path)
        elif path.suffix in ['.xlsx', '.xls']:
            return pd.read_excel(path)
        elif path.suffix == '.json':
            return pd.read_json(path)
        else:
            raise ValueError(f"不支持的文件格式: {path.suffix}")

    def _display_result(self, result: DataProcessingResponse):
        """显示处理结果"""
        if result.success:
            print("\n✅ 处理成功!")
            print(f"\n📝 执行流程: {result.explanation}")
            print(f"⏱️ 耗时: {result.execution_time:.3f}秒")

            if result.steps:
                print("\n📋 执行步骤:")
                for i, step in enumerate(result.steps, 1):
                    print(f"   {i}. {step.get('skill_name', 'unknown')}")
                    if step.get('parameters'):
                        print(f"      参数: {step.get('parameters')}")

            if result.output_data:
                print(f"\n📊 输出数据 (形状: {result.output_data.shape}):")
                # 显示前10行
                preview_rows = min(10, len(result.output_data))
                print(result.output_data.head(preview_rows).to_string())

                if len(result.output_data) > 10:
                    print(f"... 还有 {len(result.output_data) - 10} 行")

        else:
            print(f"\n❌ 处理失败: {result.error}")
            if result.logs:
                print("\n📋 日志:")
                for log in result.logs:
                    print(f"   {log}")

    def _save_output(self, df: pd.DataFrame, output_path: str):
        """保存输出"""
        path = Path(output_path)
        if path.suffix == '.csv':
            df.to_csv(path, index=False)
        elif path.suffix in ['.xlsx', '.xls']:
            df.to_excel(path, index=False)
        elif path.suffix == '.json':
            df.to_json(path, orient='records', indent=2)
        else:
            df.to_csv(path, index=False)

        print(f"\n💾 输出已保存到: {output_path}")

    def _create_demo_data(self) -> pd.DataFrame:
        """创建示例数据"""
        import random

        # 销售数据示例
        regions = ['华北', '华东', '华南', '华中', '西南', '西北']
        products = ['产品A', '产品B', '产品C', '产品D']
        names = ['张三', '李四', '王五', '赵六', '钱七', '孙八', '周九', '吴十']

        data = []
        for i in range(50):
            data.append({
                '订单号': f'ORD-{1000 + i}',
                '销售员': random.choice(names),
                '地区': random.choice(regions),
                '产品': random.choice(products),
                '销售额': random.randint(100, 5000),
                '数量': random.randint(1, 20),
                '日期': f'2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}'
            })

        # 添加一些空值
        for i in range(5):
            data[i]['销售额'] = None

        return pd.DataFrame(data)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='自然语言数据处理工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--data', '-d', help='数据文件路径 (CSV/Excel/JSON)')
    parser.add_argument('--query', '-q', help='自然语言处理请求')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--demo', action='store_true', help='运行交互式演示')

    args = parser.parse_args()

    cli = NLDataCLI()

    if args.demo:
        await cli.interactive_demo()
    elif args.data and args.query:
        await cli.process_file(args.data, args.query, args.output)
    else:
        parser.print_help()
        print("\n快速演示:")
        print("  python nl_data_cli.py --demo")


if __name__ == '__main__':
    asyncio.run(main())