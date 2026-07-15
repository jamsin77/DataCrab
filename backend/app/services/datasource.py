"""数据源连接器基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class BaseConnector(ABC):
    """数据源连接器基类

    抽象方法（必须实现）：connect / test_connection / get_schema /
    get_table_data / get_table_stats / close

    非抽象方法（可选覆盖）：execute_query — 仅结构化数据库型连接器需要实现，
    文件/对象存储等非结构化数据源无需查询，默认返回空 DataFrame。
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._connection = None

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """测试连接"""
        pass

    @abstractmethod
    async def get_schema(self) -> List[Dict[str, Any]]:
        """获取数据源结构"""
        pass

    @abstractmethod
    async def get_table_data(
        self,
        table: str,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict] = None,
        sort: Optional[Dict] = None,
    ) -> "pd.DataFrame":
        """获取表数据"""
        pass

    async def execute_query(
        self,
        query: str,
        params: Optional[Dict] = None,
    ) -> "pd.DataFrame":
        """执行查询（仅数据库型连接器需覆盖此方法；非结构化数据源默认不支持，返回空 DataFrame）"""
        import pandas as pd
        return pd.DataFrame()

    @abstractmethod
    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        """获取表统计信息"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """关闭连接"""
        pass
