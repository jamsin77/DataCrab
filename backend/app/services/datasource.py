"""数据源连接器基类"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import pandas as pd


class BaseConnector(ABC):
    """数据源连接器基类"""

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
    ) -> pd.DataFrame:
        """获取表数据"""
        pass

    @abstractmethod
    async def execute_query(
        self,
        query: str,
        params: Optional[Dict] = None,
    ) -> pd.DataFrame:
        """执行查询"""
        pass

    @abstractmethod
    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        """获取表统计信息"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """关闭连接"""
        pass
