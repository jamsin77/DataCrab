"""数据库连接器实现"""

from typing import List, Dict, Any, Optional
import os
import io
from urllib.parse import urljoin

import pandas as pd
import httpx
from loguru import logger

from app.services.datasource import BaseConnector


class PostgreSQLConnector(BaseConnector):
    """PostgreSQL连接器"""

    async def connect(self) -> bool:
        try:
            import asyncpg
            self._connection = await asyncpg.connect(
                host=self.config.get("host", "localhost"),
                port=self.config.get("port", 5432),
                database=self.config.get("database"),
                user=self.config.get("user"),
                password=self.config.get("password"),
            )
            return True
        except Exception as e:
            logger.error(f"PostgreSQL连接失败: {e}")
            return False

    async def test_connection(self) -> bool:
        try:
            conn = await self.connect()
            if conn and self._connection:
                await self._connection.execute("SELECT 1")
                await self.close()
                return True
            return False
        except Exception as e:
            logger.error(f"PostgreSQL测试连接失败: {e}")
            return False

    async def get_schema(self) -> List[Dict[str, Any]]:
        if not self._connection:
            await self.connect()
        tables = await self._connection.fetch(
            "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = 'public'"
        )
        return [dict(t) for t in tables]

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        if not self._connection:
            await self.connect()
        offset = (page - 1) * page_size
        rows = await self._connection.fetch(
            f"SELECT * FROM {table} LIMIT {page_size} OFFSET {offset}"
        )
        return pd.DataFrame([dict(r) for r in rows])

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        if not self._connection:
            await self.connect()
        rows = await self._connection.fetch(query)
        return pd.DataFrame([dict(r) for r in rows])

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        if not self._connection:
            await self.connect()
        count = await self._connection.fetchval(f"SELECT COUNT(*) FROM {table}")
        return {"row_count": count}

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None


class MySQLConnector(BaseConnector):
    """MySQL连接器"""

    async def connect(self) -> bool:
        try:
            import aiomysql
            self._connection = await aiomysql.connect(
                host=self.config.get("host", "localhost"),
                port=self.config.get("port", 3306),
                db=self.config.get("database"),
                user=self.config.get("user"),
                password=self.config.get("password"),
            )
            return True
        except ImportError:
            logger.warning("aiomysql未安装, MySQL连接器不可用")
            return False
        except Exception as e:
            logger.error(f"MySQL连接失败: {e}")
            return False

    async def test_connection(self) -> bool:
        try:
            result = await self.connect()
            if result and self._connection:
                await self._connection.ping()
                await self.close()
            return result
        except Exception as e:
            logger.error(f"MySQL测试连接失败: {e}")
            return False

    async def get_schema(self) -> List[Dict[str, Any]]:
        if not self._connection:
            await self.connect()
        if not self._connection:
            return []
        async with self._connection.cursor() as cur:
            await cur.execute("SHOW TABLES")
            rows = await cur.fetchall()
        return [{"table_name": r[0], "table_type": "TABLE"} for r in rows]

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        if not self._connection:
            await self.connect()
        if not self._connection:
            return pd.DataFrame()
        offset = (page - 1) * page_size
        async with self._connection.cursor() as cur:
            await cur.execute(f"SELECT * FROM `{table}` LIMIT {page_size} OFFSET {offset}")
            rows = await cur.fetchall()
            cols = [desc[0] for desc in cur.description]
        return pd.DataFrame(rows, columns=cols)

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        if not self._connection:
            await self.connect()
        if not self._connection:
            return pd.DataFrame()
        async with self._connection.cursor() as cur:
            await cur.execute(query)
            rows = await cur.fetchall()
            cols = [desc[0] for desc in cur.description]
        return pd.DataFrame(rows, columns=cols)

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        if not self._connection:
            await self.connect()
        if not self._connection:
            return {}
        async with self._connection.cursor() as cur:
            await cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            count = (await cur.fetchone())[0]
        return {"row_count": count}

    async def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None


class CSVConnector(BaseConnector):
    """CSV文件连接器"""

    async def connect(self) -> bool:
        return True

    async def test_connection(self) -> bool:
        return os.path.exists(self.config.get("file_path", ""))

    async def get_schema(self) -> List[Dict[str, Any]]:
        file_path = self.config.get("file_path", "")
        if not os.path.exists(file_path):
            return []
        return [{"table_name": os.path.basename(file_path), "table_type": "csv"}]

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        file_path = self.config.get("file_path", "")
        df = pd.read_csv(file_path)
        offset = (page - 1) * page_size
        return df.iloc[offset:offset + page_size]

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        file_path = self.config.get("file_path", "")
        df = pd.read_csv(file_path)
        return {"row_count": len(df), "column_count": len(df.columns)}

    async def close(self) -> None:
        pass


class ExcelConnector(BaseConnector):
    """Excel文件连接器"""

    async def connect(self) -> bool:
        return True

    async def test_connection(self) -> bool:
        return os.path.exists(self.config.get("file_path", ""))

    async def get_schema(self) -> List[Dict[str, Any]]:
        file_path = self.config.get("file_path", "")
        if not os.path.exists(file_path):
            return []
        try:
            xl = pd.ExcelFile(file_path)
            return [{"table_name": s, "table_type": "excel_sheet"} for s in xl.sheet_names]
        except Exception:
            return [{"table_name": os.path.basename(file_path), "table_type": "excel"}]

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        file_path = self.config.get("file_path", "")
        sheet_name = table if table else self.config.get("sheet_name", 0)
        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        except Exception:
            df = pd.read_excel(file_path, sheet_name=0)
        offset = (page - 1) * page_size
        return df.iloc[offset:offset + page_size]

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        file_path = self.config.get("file_path", "")
        sheet_name = table if table else self.config.get("sheet_name", 0)
        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        except Exception:
            df = pd.read_excel(file_path, sheet_name=0)
        return {"row_count": len(df), "column_count": len(df.columns)}

    async def close(self) -> None:
        pass


class OBSConnector(BaseConnector):
    """华为云OBS对象存储连接器 (支持S3兼容API)"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._client = None

    async def connect(self) -> bool:
        try:
            from minio import Minio
            endpoint = self.config.get("endpoint", "")
            access_key = self.config.get("access_key", "")
            secret_key = self.config.get("secret_key", "")
            secure = self.config.get("secure", True)
            region = self.config.get("region")

            if not endpoint or not access_key or not secret_key:
                logger.error("OBS配置缺少必要参数: endpoint, access_key, secret_key")
                return False

            self._client = Minio(
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
                region=region,
            )
            return True
        except ImportError:
            logger.warning("minio库未安装, OBS连接器不可用")
            return False
        except Exception as e:
            logger.error(f"OBS连接失败: {e}")
            return False

    async def test_connection(self) -> bool:
        try:
            connected = await self.connect()
            if connected and self._client:
                bucket = self.config.get("bucket", "")
                if bucket:
                    self._client.bucket_exists(bucket)
                else:
                    self._client.list_buckets()
                return True
            return False
        except Exception as e:
            logger.error(f"OBS测试连接失败: {e}")
            return False

    async def get_schema(self) -> List[Dict[str, Any]]:
        if not self._client:
            await self.connect()
        if not self._client:
            return []

        bucket = self.config.get("bucket", "")
        prefix = self.config.get("prefix", "")

        try:
            if bucket:
                objects = self._client.list_objects(bucket, prefix=prefix)
                return [
                    {
                        "table_name": obj.object_name,
                        "table_type": "obs_object",
                        "size": obj.size,
                        "last_modified": str(obj.last_modified),
                    }
                    for obj in objects
                ]
            else:
                buckets = self._client.list_buckets()
                return [
                    {"table_name": b.name, "table_type": "obs_bucket",
                     "creation_date": str(b.creation_date)}
                    for b in buckets
                ]
        except Exception as e:
            logger.error(f"OBS获取结构失败: {e}")
            return []

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        if not self._client:
            await self.connect()
        if not self._client:
            return pd.DataFrame()

        bucket = self.config.get("bucket", "")
        try:
            response = self._client.get_object(bucket, table)
            content = response.read()
            response.close()
            response.release_conn()

            if table.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(content))
            elif table.endswith((".xls", ".xlsx")):
                df = pd.read_excel(io.BytesIO(content))
            elif table.endswith(".json"):
                df = pd.read_json(io.BytesIO(content))
            else:
                df = pd.DataFrame({"content": [content.decode("utf-8", errors="replace")]})

            offset = (page - 1) * page_size
            return df.iloc[offset:offset + page_size]
        except Exception as e:
            logger.error(f"OBS读取数据失败: {e}")
            return pd.DataFrame()

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        if not self._client:
            await self.connect()
        if not self._client:
            return {}

        bucket = self.config.get("bucket", "")
        try:
            stat = self._client.stat_object(bucket, table)
            return {
                "row_count": 0,
                "size_bytes": stat.size,
                "last_modified": str(stat.last_modified),
            }
        except Exception as e:
            logger.error(f"OBS获取统计失败: {e}")
            return {}

    async def close(self) -> None:
        self._client = None


class HadoopHDFSConnector(BaseConnector):
    """Hadoop HDFS连接器 (通过WebHDFS REST API)"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._client = None
        self._base_url = ""

    async def connect(self) -> bool:
        try:
            host = self.config.get("host", "localhost")
            port = self.config.get("port", 9870)
            user = self.config.get("user", "hadoop")
            secure = self.config.get("secure", False)

            protocol = "https" if secure else "http"
            self._base_url = f"{protocol}://{host}:{port}/webhdfs/v1"
            self._user = user

            self._client = httpx.AsyncClient(timeout=30.0)
            return True
        except Exception as e:
            logger.error(f"Hadoop HDFS连接失败: {e}")
            return False

    async def test_connection(self) -> bool:
        try:
            connected = await self.connect()
            if not connected or not self._client:
                return False

            params = {"op": "GETFILESTATUS", "user.name": self._user}
            base_path = self.config.get("base_path", "/")
            url = f"{self._base_url}{base_path}"
            resp = await self._client.get(url, params=params)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Hadoop HDFS测试连接失败: {e}")
            return False

    async def get_schema(self) -> List[Dict[str, Any]]:
        if not self._client:
            await self.connect()
        if not self._client:
            return []

        base_path = self.config.get("base_path", "/")
        try:
            params = {"op": "LISTSTATUS", "user.name": self._user}
            url = f"{self._base_url}{base_path}"
            resp = await self._client.get(url, params=params)
            if resp.status_code != 200:
                return []

            data = resp.json()
            items = data.get("FileStatuses", {}).get("FileStatus", [])
            return [
                {
                    "table_name": item.get("pathSuffix", ""),
                    "table_type": "hdfs_directory" if item.get("type") == "DIRECTORY" else "hdfs_file",
                    "size": item.get("length", 0),
                    "modification_time": item.get("modificationTime", ""),
                }
                for item in items
            ]
        except Exception as e:
            logger.error(f"Hadoop HDFS获取结构失败: {e}")
            return []

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        if not self._client:
            await self.connect()
        if not self._client:
            return pd.DataFrame()

        base_path = self.config.get("base_path", "/")
        file_path = f"{base_path.rstrip('/')}/{table.lstrip('/')}"

        try:
            params = {"op": "OPEN", "user.name": self._user}
            url = f"{self._base_url}{file_path}"
            resp = await self._client.get(url, params=params)
            if resp.status_code != 200:
                return pd.DataFrame()

            content = resp.content
            if table.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(content))
            elif table.endswith((".xls", ".xlsx")):
                df = pd.read_excel(io.BytesIO(content))
            elif table.endswith(".json"):
                df = pd.read_json(io.BytesIO(content))
            else:
                return pd.DataFrame({"raw_content": [content.decode("utf-8", errors="replace")]})

            offset = (page - 1) * page_size
            return df.iloc[offset:offset + page_size]
        except Exception as e:
            logger.error(f"Hadoop HDFS读取数据失败: {e}")
            return pd.DataFrame()

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        if not self._client:
            await self.connect()
        if not self._client:
            return {}

        base_path = self.config.get("base_path", "/")
        file_path = f"{base_path.rstrip('/')}/{table.lstrip('/')}"

        try:
            params = {"op": "GETFILESTATUS", "user.name": self._user}
            url = f"{self._base_url}{file_path}"
            resp = await self._client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("FileStatus", {})
                return {
                    "size_bytes": status.get("length", 0),
                    "modification_time": status.get("modificationTime", ""),
                }
            return {}
        except Exception as e:
            logger.error(f"Hadoop HDFS获取统计失败: {e}")
            return {}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


CONNECTOR_REGISTRY: Dict[str, type] = {
    "postgresql": PostgreSQLConnector,
    "mysql": MySQLConnector,
    "csv": CSVConnector,
    "excel": ExcelConnector,
    "obs": OBSConnector,
    "hadoop": HadoopHDFSConnector,
}


def get_connector(datasource_type: str, config: Dict[str, Any]) -> BaseConnector:
    """获取连接器实例"""
    connector_class = CONNECTOR_REGISTRY.get(datasource_type)
    if not connector_class:
        raise ValueError(f"不支持的数据源类型: {datasource_type}")
    return connector_class(config)


class ConnectorManager:
    """连接器管理器 - 为技能沙箱提供数据源访问能力"""

    def __init__(self, session):
        self._session = session

    async def query_table(
        self,
        datasource_id: str,
        table_name: str,
        limit: int = 1000,
        offset: int = 0,
        order_by: str = None,
    ):
        from sqlalchemy import select as sa_select
        from app.models.datasource import DataSource
        from uuid import UUID as UUIDType

        try:
            ds_uuid = UUIDType(datasource_id) if isinstance(datasource_id, str) else datasource_id
        except (ValueError, AttributeError):
            ds_uuid = datasource_id

        result = await self._session.execute(
            sa_select(DataSource).where(DataSource.id == ds_uuid)
        )
        ds = result.scalar_one_or_none()
        if not ds:
            raise ValueError(f"数据源不存在: {datasource_id}")

        page = (offset // limit) + 1 if limit > 0 else 1
        connector = get_connector(ds.type, ds.connection_config or {})
        try:
            df = await connector.get_table_data(table_name, page=page, page_size=limit)
            if order_by and not df.empty:
                col = order_by.lstrip("-")
                ascending = not order_by.startswith("-")
                if col in df.columns:
                    df = df.sort_values(by=col, ascending=ascending)
            return df
        finally:
            await connector.close()

    async def get_table_schema(self, datasource_id: str, table_name: str):
        from sqlalchemy import select as sa_select
        from app.models.datasource import DataSource
        from uuid import UUID as UUIDType

        try:
            ds_uuid = UUIDType(datasource_id) if isinstance(datasource_id, str) else datasource_id
        except (ValueError, AttributeError):
            ds_uuid = datasource_id

        result = await self._session.execute(
            sa_select(DataSource).where(DataSource.id == ds_uuid)
        )
        ds = result.scalar_one_or_none()
        if not ds:
            raise ValueError(f"数据源不存在: {datasource_id}")

        connector = get_connector(ds.type, ds.connection_config or {})
        try:
            stats = await connector.get_table_stats(table_name)
            df = await connector.get_table_data(table_name, page=1, page_size=1)
            columns = [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]
            return {
                "columns": columns,
                "row_count": stats.get("row_count", 0),
                "column_count": len(columns),
            }
        finally:
            await connector.close()

    async def list_datasources(self):
        from sqlalchemy import select as sa_select
        from app.models.datasource import DataSource

        result = await self._session.execute(
            sa_select(DataSource).where(DataSource.is_active == True)
        )
        sources = result.scalars().all()
        return [
            {
                "id": str(s.id),
                "name": s.name,
                "type": s.type,
            }
            for s in sources
        ]


def get_connector_manager(session):
    """获取连接器管理器实例"""
    return ConnectorManager(session)
