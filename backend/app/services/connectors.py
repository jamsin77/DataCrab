"""数据库连接器实现"""

from __future__ import annotations

import re
import asyncio
import glob
from typing import List, Dict, Any, Optional
import os
import io
from urllib.parse import urljoin

import httpx
from loguru import logger

from app.services.datasource import BaseConnector

_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _validate_identifier(name: str) -> str:
    if not name or not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"非法的表名标识符: {name}")
    return name


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
                return True
            return False
        except Exception as e:
            logger.error(f"PostgreSQL测试连接失败: {e}")
            return False
        finally:
            await self.close()

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
        import pandas as pd
        if not self._connection:
            await self.connect()
        _validate_identifier(table)
        offset = (page - 1) * page_size
        rows = await self._connection.fetch(
            f'SELECT * FROM "{table}" LIMIT $1 OFFSET $2', page_size, offset
        )
        return pd.DataFrame([dict(r) for r in rows])

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        import pandas as pd
        if not self._connection:
            await self.connect()
        rows = await self._connection.fetch(query)
        return pd.DataFrame([dict(r) for r in rows])

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        if not self._connection:
            await self.connect()
        _validate_identifier(table)
        count = await self._connection.fetchval(f'SELECT COUNT(*) FROM "{table}"')
        return {"row_count": count}

    async def write_table_data(
        self, table: str, records: List[Dict[str, Any]],
        if_table_exists: str = "fail",
        table_remark: str = "",
        column_remarks: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """写入数据到 PostgreSQL 表。

        if_table_exists 策略:
          - fail:        表已存在则报错（默认）
          - append:      直接追加数据
          - replace:     DROP TABLE 后重建（丢弃索引/约束/序列等）
          - overwrite:   TRUNCATE 清空数据 + 自动补齐缺失列（保留表结构）
          - truncate:    同 overwrite
          - delete_rows:  DELETE FROM 清空数据（保留表结构，不补列）
          - upsert:      按 id 列做 INSERT ON CONFLICT DO UPDATE（无 id 列则退化为 append）
        """
        if not self._connection:
            await self.connect()
        if not self._connection:
            return {"success": False, "message": "数据库连接失败"}
        if not records:
            return {"success": True, "rows_written": 0}
        try:
            _validate_identifier(table)
            columns = list(records[0].keys())
            for col in columns:
                _validate_identifier(col)

            # 检查表是否存在 (asyncpg 用 $1 而非 %s, fetchrow 而非 execute+fetchone)
            row = await self._connection.fetchrow("SELECT to_regclass($1)", table)
            table_exists = row and row[0] is not None

            if table_exists:
                if if_table_exists in ("fail",):
                    return {"success": False, "message": f"表 '{table}' 已存在 (if_table_exists=fail)"}
                elif if_table_exists in ("replace",):
                    await self._connection.execute(f'DROP TABLE "{table}"')
                    col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
                    await self._connection.execute(f'CREATE TABLE "{table}" ({col_defs})')
                elif if_table_exists in ("overwrite", "truncate"):
                    await self._connection.execute(f'TRUNCATE TABLE "{table}"')
                    # 补齐缺失列 (asyncpg 用 fetch 而非 execute+fetchall)
                    col_rows = await self._connection.fetch(
                        "SELECT column_name FROM information_schema.columns WHERE table_name = $1", table
                    )
                    existing_cols = {r[0] for r in col_rows}
                    for col in columns:
                        if col not in existing_cols:
                            await self._connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" TEXT')
                elif if_table_exists in ("delete_rows",):
                    await self._connection.execute(f'DELETE FROM "{table}"')
                elif if_table_exists in ("upsert",):
                    pass  # 在写入阶段用 ON CONFLICT 处理
                else:
                    pass  # append: 直接追加
            else:
                col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
                await self._connection.execute(f'CREATE TABLE "{table}" ({col_defs})')

            # 写入数据
            col_names = ", ".join(f'"{c}"' for c in columns)
            if if_table_exists == "upsert" and table_exists and "id" in columns:
                # upsert: 按 id 做 ON CONFLICT DO UPDATE
                update_cols = [c for c in columns if c != "id"]
                set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols) if update_cols else "id = EXCLUDED.id"
                placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
                insert_sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders}) ON CONFLICT (id) DO UPDATE SET {set_clause}'
            else:
                placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
                insert_sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'

            for record in records:
                values = [str(v) if v is not None else None for v in (record.get(c) for c in columns)]
                await self._connection.execute(insert_sql, *values)

            # 设置表备注
            if table_remark:
                safe_remark = table_remark.replace("'", "''")
                await self._connection.execute(f'COMMENT ON TABLE "{table}" IS \'{safe_remark}\'')

            # 设置列备注
            if column_remarks:
                for col_name, remark in column_remarks.items():
                    if col_name in columns and remark:
                        _validate_identifier(col_name)
                        safe_remark = str(remark).replace("'", "''")
                        await self._connection.execute(f'COMMENT ON COLUMN "{table}"."{col_name}" IS \'{safe_remark}\'')

            # asyncpg 自动提交，无需 commit()
            return {"success": True, "rows_written": len(records)}
        except Exception as e:
            return {"success": False, "message": str(e)}

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
                return True
            return False
        except Exception as e:
            logger.error(f"MySQL测试连接失败: {e}")
            return False
        finally:
            await self.close()

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
        import pandas as pd
        if not self._connection:
            await self.connect()
        if not self._connection:
            return pd.DataFrame()
        _validate_identifier(table)
        offset = (page - 1) * page_size
        async with self._connection.cursor() as cur:
            await cur.execute(f"SELECT * FROM `{table}` LIMIT %s OFFSET %s", (page_size, offset))
            rows = await cur.fetchall()
            cols = [desc[0] for desc in cur.description]
        return pd.DataFrame(rows, columns=cols)

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        import pandas as pd
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
        _validate_identifier(table)
        async with self._connection.cursor() as cur:
            await cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            count = (await cur.fetchone())[0]
        return {"row_count": count}

    async def write_table_data(
        self, table: str, records: List[Dict[str, Any]],
        if_table_exists: str = "fail",
        table_remark: str = "",
        column_remarks: Dict[str, str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """写入数据到 MySQL 表。策略同 PostgreSQL: fail/append/replace/overwrite/truncate/delete_rows/upsert"""
        if not self._connection:
            await self.connect()
        if not self._connection:
            return {"success": False, "message": "数据库连接失败"}
        if not records:
            return {"success": True, "rows_written": 0}
        try:
            _validate_identifier(table)
            columns = list(records[0].keys())
            for col in columns:
                _validate_identifier(col)

            async with self._connection.cursor() as cur:
                await cur.execute(f"SHOW TABLES LIKE %s", (table,))
                table_exists = await cur.fetchone() is not None

                if table_exists:
                    if if_table_exists == "fail":
                        return {"success": False, "message": f"表 '{table}' 已存在 (if_table_exists=fail)"}
                    elif if_table_exists == "replace":
                        await cur.execute(f"DROP TABLE `{table}`")
                        col_defs = ", ".join(f"`{c}` TEXT" for c in columns)
                        await cur.execute(f"CREATE TABLE `{table}` ({col_defs})")
                    elif if_table_exists in ("overwrite", "truncate"):
                        await cur.execute(f"TRUNCATE TABLE `{table}`")
                        await cur.execute(f"SHOW COLUMNS FROM `{table}`")
                        existing_cols = {r[0] for r in await cur.fetchall()}
                        for col in columns:
                            if col not in existing_cols:
                                await cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col}` TEXT")
                    elif if_table_exists == "delete_rows":
                        await cur.execute(f"DELETE FROM `{table}`")
                else:
                    col_defs = ", ".join(f"`{c}` TEXT" for c in columns)
                    await cur.execute(f"CREATE TABLE `{table}` ({col_defs})")

                # 写入数据
                col_names = ", ".join(f"`{c}`" for c in columns)
                placeholders = ", ".join("%s" for _ in columns)
                if if_table_exists == "upsert" and table_exists and "id" in columns:
                    update_cols = [c for c in columns if c != "id"]
                    set_clause = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in update_cols) if update_cols else "`id` = VALUES(`id`)"
                    insert_sql = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {set_clause}"
                else:
                    insert_sql = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders})"

                for record in records:
                    values = [str(v) if v is not None else None for v in (record.get(c) for c in columns)]
                    await cur.execute(insert_sql, values)

                if table_remark:
                    safe_remark = table_remark.replace("'", "\\'")
                    await cur.execute(f"ALTER TABLE `{table}` COMMENT = '{safe_remark}'")

            await self._connection.commit()
            return {"success": True, "rows_written": len(records)}
        except Exception as e:
            return {"success": False, "message": str(e)}

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
        import pandas as pd
        file_path = self.config.get("file_path", "")
        df = pd.read_csv(file_path)
        offset = (page - 1) * page_size
        return df.iloc[offset:offset + page_size]

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        import pandas as pd
        return pd.DataFrame()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        import pandas as pd
        file_path = self.config.get("file_path", "")
        df = pd.read_csv(file_path)
        return {"row_count": len(df), "column_count": len(df.columns)}

    async def write_table_data(self, table: str, records: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        import pandas as pd
        file_path = self.config.get("file_path", "")
        try:
            df_new = pd.DataFrame(records)
            df_new.to_csv(file_path, index=False)
            return {"success": True, "rows_written": len(df_new)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def close(self) -> None:
        pass


class ExcelConnector(BaseConnector):
    """Excel文件连接器 — 支持单文件、多文件、文件夹模式"""

    def _get_excel_files(self) -> List[str]:
        """根据 config 返回所有 Excel 文件路径"""
        mode = self.config.get("mode", "file")
        file_path = self.config.get("file_path", "")
        file_paths = self.config.get("file_paths", [])

        if mode == "folder":
            folder = file_path
            if not folder or not os.path.isdir(folder):
                return []
            files = []
            for ext in ("*.xlsx", "*.xls"):
                files.extend(glob.glob(os.path.join(folder, ext)))
            return sorted(files)
        elif mode == "files" and file_paths:
            return [f for f in file_paths if os.path.exists(f)]
        else:
            if file_path and os.path.exists(file_path):
                return [file_path]
            return []

    def _resolve_table_name(self, table_name: str) -> tuple:
        """解析 table_name 为 (file_path, sheet_name)，用实际文件列表消除歧义。

        文件名本身可能含下划线（如 sales_2024），因此不能简单按最后一个 _
        拆分，而要用已知文件 basename 做最长前缀匹配。
        """
        files = self._get_excel_files()
        bases = []
        for f in files:
            base = os.path.splitext(os.path.basename(f))[0]
            bases.append((base, f))

        # 优先处理 | 分隔符（显式格式）
        if "|" in table_name:
            parts = table_name.split("|", 1)
            file_base, sheet = parts[0], parts[1]
            for base, fpath in bases:
                if base == file_base or os.path.basename(fpath) == file_base:
                    return fpath, sheet
            return file_base, sheet

        # 精确匹配文件名 → 第一个 sheet
        for base, fpath in bases:
            if table_name == base:
                return fpath, 0

        # 最长前缀匹配：table_name = base + "_" + sheet_name
        for base, fpath in sorted(bases, key=lambda x: -len(x[0])):
            prefix = base + "_"
            if table_name.startswith(prefix) and len(table_name) > len(prefix):
                sheet = table_name[len(prefix):]
                return fpath, sheet

        # 兜底：无法匹配，返回原始值
        return table_name, 0

    async def connect(self) -> bool:
        return True

    async def test_connection(self) -> bool:
        files = self._get_excel_files()
        return len(files) > 0

    async def get_schema(self) -> List[Dict[str, Any]]:
        """返回所有文件所有Sheet的列表
        table_name 规则:
          - 文件的第一个Sheet: 文件名(不含扩展名)
          - 文件的其他Sheet: 文件名_Sheet名
        """
        import pandas as pd
        files = self._get_excel_files()
        if not files:
            return []

        result = []
        for fpath in files:
            base = os.path.splitext(os.path.basename(fpath))[0]
            try:
                xl = pd.ExcelFile(fpath)
                for i, sheet in enumerate(xl.sheet_names):
                    if i == 0:
                        table_name = base
                    else:
                        table_name = f"{base}_{sheet}"
                    result.append({
                        "table_name": table_name,
                        "table_type": "excel_sheet",
                        "file_path": fpath,
                        "sheet_name": sheet,
                        "sheet_index": i,
                    })
            except Exception:
                result.append({
                    "table_name": base,
                    "table_type": "excel",
                    "file_path": fpath,
                    "sheet_name": None,
                    "sheet_index": 0,
                })
        return result

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        import pandas as pd
        file_path, sheet_name = self._resolve_table_name(table)

        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        except Exception:
            try:
                df = pd.read_excel(file_path, sheet_name=0)
            except Exception:
                files = self._get_excel_files()
                if files:
                    df = pd.read_excel(files[0], sheet_name=0)
                else:
                    return pd.DataFrame()
        offset = (page - 1) * page_size
        return df.iloc[offset:offset + page_size]

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        import pandas as pd
        return pd.DataFrame()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        import pandas as pd
        file_path, sheet_name = self._resolve_table_name(table)

        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        except Exception:
            try:
                df = pd.read_excel(file_path, sheet_name=0)
            except Exception:
                files = self._get_excel_files()
                if files:
                    df = pd.read_excel(files[0], sheet_name=0)
                else:
                    return {"row_count": 0, "column_count": 0}
        return {"row_count": len(df), "column_count": len(df.columns)}

    async def write_table_data(self, table: str, records: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        import pandas as pd
        file_path, sheet_name = self._resolve_table_name(table)

        try:
            if not os.path.exists(file_path):
                return {"success": False, "message": f"文件不存在: {file_path}"}
            df_new = pd.DataFrame(records)
            xl = pd.ExcelFile(file_path)
            sheets_data = {}
            target_sheet = sheet_name
            if isinstance(target_sheet, int) or target_sheet not in xl.sheet_names:
                target_sheet = xl.sheet_names[target_sheet if isinstance(target_sheet, int) else 0]
            for s in xl.sheet_names:
                if s == target_sheet:
                    sheets_data[s] = df_new
                else:
                    sheets_data[s] = pd.read_excel(xl, sheet_name=s)
            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                for s, df in sheets_data.items():
                    df.to_excel(writer, sheet_name=s, index=False)
            return {"success": True, "rows_written": len(df_new)}
        except Exception as e:
            return {"success": False, "message": str(e)}

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
                    await asyncio.to_thread(self._client.bucket_exists, bucket)
                else:
                    await asyncio.to_thread(self._client.list_buckets)
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
                objects = await asyncio.to_thread(self._client.list_objects, bucket, prefix)
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
                buckets = await asyncio.to_thread(self._client.list_buckets)
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
        import pandas as pd
        if not self._client:
            await self.connect()
        if not self._client:
            return pd.DataFrame()

        bucket = self.config.get("bucket", "")
        try:
            response = await asyncio.to_thread(self._client.get_object, bucket, table)
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
        import pandas as pd
        return pd.DataFrame()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        if not self._client:
            await self.connect()
        if not self._client:
            return {}

        bucket = self.config.get("bucket", "")
        try:
            stat = await asyncio.to_thread(self._client.stat_object, bucket, table)
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
        import pandas as pd
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
        import pandas as pd
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


class ChromaConnector(BaseConnector):
    """ChromaDB 向量库连接器"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._client = None
        self._persist_dir = config.get("persist_directory", "d:/chroma-data")

    def _get_client(self):
        if self._client is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=self._persist_dir)
        return self._client

    async def connect(self) -> bool:
        try:
            client = self._get_client()
            await asyncio.to_thread(client.heartbeat)
            return True
        except Exception as e:
            logger.error(f"ChromaDB连接失败: {e}")
            return False

    async def test_connection(self) -> bool:
        try:
            client = self._get_client()
            await asyncio.to_thread(client.heartbeat)
            return True
        except Exception as e:
            logger.error(f"ChromaDB测试连接失败: {e}")
            return False

    async def get_schema(self) -> List[Dict[str, Any]]:
        client = self._get_client()
        collections = await asyncio.to_thread(client.list_collections)
        return [
            {"table_name": c.name, "table_type": "chroma_collection", "id": str(c.id), "count": c.count()}
            for c in collections
        ]

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        import pandas as pd
        client = self._get_client()
        collection = await asyncio.to_thread(client.get_collection, table)
        offset = (page - 1) * page_size
        result = await asyncio.to_thread(
            collection.get,
            include=["documents", "metadatas"],
            limit=page_size,
            offset=offset,
        )
        rows = []
        for i in range(len(result["ids"])):
            row: Dict[str, Any] = {"id": result["ids"][i]}
            if result.get("documents") and i < len(result["documents"]) and result["documents"][i] is not None:
                row["document"] = result["documents"][i]
            if result.get("metadatas") and i < len(result["metadatas"]) and result["metadatas"][i] is not None:
                for k, v in result["metadatas"][i].items():
                    row[f"meta_{k}"] = v if not isinstance(v, (list, dict)) else str(v)
            rows.append(row)
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        import pandas as pd
        client = self._get_client()
        p = params or {}
        collection_name = p.get("collection")
        if not collection_name:
            return pd.DataFrame()
        collection = await asyncio.to_thread(client.get_collection, collection_name)
        query_texts = p.get("query_texts")
        query_embeddings = p.get("query_embeddings")
        n_results = p.get("n_results", 10)
        if query_texts:
            results = await asyncio.to_thread(
                collection.query,
                query_texts=[query_texts] if isinstance(query_texts, str) else query_texts,
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        elif query_embeddings:
            results = await asyncio.to_thread(
                collection.query,
                query_embeddings=[query_embeddings] if not isinstance(query_embeddings[0], list) else query_embeddings,
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        else:
            return pd.DataFrame()
        rows = []
        for i in range(len(results["ids"][0])):
            row = {"id": results["ids"][0][i]}
            if results.get("documents") and results["documents"][0][i] is not None:
                row["document"] = results["documents"][0][i]
            if results.get("metadatas") and results["metadatas"][0][i] is not None:
                for k, v in results["metadatas"][0][i].items():
                    row[f"meta_{k}"] = v
            if results.get("distances") and results["distances"][0][i] is not None:
                row["distance"] = results["distances"][0][i]
            rows.append(row)
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        client = self._get_client()
        try:
            collection = await asyncio.to_thread(client.get_collection, table)
            return {"row_count": collection.count(), "name": collection.name}
        except Exception:
            return {"row_count": 0}

    async def write_table_data(self, table: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        client = self._get_client()
        collection = await asyncio.to_thread(client.get_or_create_collection, table)
        ids = [r.get("id", str(i)) for i, r in enumerate(records)]
        documents = [r.get("document", r.get("text", "")) for r in records]
        metadatas = [r.get("metadata", r.get("metadatas", {})) for r in records]
        embeddings = [r.get("embedding") for r in records]
        has_embeddings = any(e is not None for e in embeddings)
        kwargs = {"ids": ids, "documents": documents, "metadatas": metadatas}
        if has_embeddings:
            kwargs["embeddings"] = [e for e in embeddings]
        await asyncio.to_thread(collection.upsert, **kwargs)
        return {"success": True, "rows_written": len(ids)}

    async def close(self) -> None:
        self._client = None


class SQLiteConnector(BaseConnector):
    """SQLite连接器"""

    async def connect(self) -> bool:
        try:
            import aiosqlite
            db_path = self.config.get("database", self.config.get("file_path", ""))
            if not db_path:
                logger.error("SQLite配置缺少必要参数: database 或 file_path")
                return False
            self._connection = await aiosqlite.connect(db_path)
            self._connection.row_factory = aiosqlite.Row
            return True
        except Exception as e:
            logger.error(f"SQLite连接失败: {e}")
            return False

    async def test_connection(self) -> bool:
        try:
            conn = await self.connect()
            if conn and self._connection:
                await self._connection.execute("SELECT 1")
                return True
            return False
        except Exception as e:
            logger.error(f"SQLite测试连接失败: {e}")
            return False
        finally:
            await self.close()

    async def get_schema(self) -> List[Dict[str, Any]]:
        if not self._connection:
            await self.connect()
        if not self._connection:
            return []
        async with self._connection.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"table_name": r["name"], "table_type": r["type"]} for r in rows]

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        import pandas as pd
        if not self._connection:
            await self.connect()
        if not self._connection:
            return pd.DataFrame()
        _validate_identifier(table)
        offset = (page - 1) * page_size
        async with self._connection.execute(
            f'SELECT * FROM "{table}" LIMIT ? OFFSET ?', (page_size, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return pd.DataFrame([dict(r) for r in rows], columns=columns)

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        import pandas as pd
        if not self._connection:
            await self.connect()
        if not self._connection:
            return pd.DataFrame()
        async with self._connection.execute(query) as cursor:
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return pd.DataFrame([dict(r) for r in rows], columns=columns)

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        if not self._connection:
            await self.connect()
        if not self._connection:
            return {}
        _validate_identifier(table)
        async with self._connection.execute(f'SELECT COUNT(*) FROM "{table}"') as cursor:
            row = await cursor.fetchone()
        return {"row_count": row[0] if row else 0}

    async def write_table_data(
        self, table: str, records: List[Dict[str, Any]],
        if_table_exists: str = "fail",
        table_remark: str = "",
        column_remarks: Dict[str, str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """写入数据到 SQLite 表。策略同 PostgreSQL: fail/append/replace/overwrite/truncate/delete_rows/upsert"""
        if not self._connection:
            await self.connect()
        if not self._connection:
            return {"success": False, "message": "数据库连接失败"}
        if not records:
            return {"success": True, "rows_written": 0}
        try:
            _validate_identifier(table)
            columns = list(records[0].keys())
            for col in columns:
                _validate_identifier(col)

            # 检查表是否存在
            async with self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ) as cursor:
                table_exists = await cursor.fetchone() is not None

            if table_exists:
                if if_table_exists == "fail":
                    return {"success": False, "message": f"表 '{table}' 已存在 (if_table_exists=fail)"}
                elif if_table_exists == "replace":
                    await self._connection.execute(f'DROP TABLE "{table}"')
                    col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
                    await self._connection.execute(f'CREATE TABLE "{table}" ({col_defs})')
                elif if_table_exists in ("overwrite", "truncate"):
                    await self._connection.execute(f'DELETE FROM "{table}"')
                    # SQLite 不支持 TRUNCATE，用 DELETE；补齐缺失列
                    async with self._connection.execute(f'PRAGMA table_info("{table}")') as cursor:
                        existing_cols = {r[1] for r in await cursor.fetchall()}
                    for col in columns:
                        if col not in existing_cols:
                            await self._connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" TEXT')
                elif if_table_exists == "delete_rows":
                    await self._connection.execute(f'DELETE FROM "{table}"')
            else:
                col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
                await self._connection.execute(f'CREATE TABLE "{table}" ({col_defs})')

            # 写入数据
            col_names = ", ".join(f'"{c}"' for c in columns)
            placeholders = ", ".join("?" for _ in columns)
            if if_table_exists == "upsert" and table_exists and "id" in columns:
                update_cols = [c for c in columns if c != "id"]
                set_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols) if update_cols else '"id" = excluded."id"'
                insert_sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {set_clause}'
            else:
                insert_sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'

            for record in records:
                values = [str(v) if v is not None else None for v in (record.get(c) for c in columns)]
                await self._connection.execute(insert_sql, values)

            await self._connection.commit()
            return {"success": True, "rows_written": len(records)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None


CONNECTOR_REGISTRY: Dict[str, type] = {
    "postgresql": PostgreSQLConnector,
    "mysql": MySQLConnector,
    "sqlite": SQLiteConnector,
    "csv": CSVConnector,
    "excel": ExcelConnector,
    "obs": OBSConnector,
    "hadoop": HadoopHDFSConnector,
    "chroma": ChromaConnector,
}

SUPPORTED_DATASOURCE_TYPES = list(CONNECTOR_REGISTRY.keys())


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

    async def read_table(self, datasource_id: str, table_name: str, limit: int = 50000) -> dict:
        df = await self.query_table(datasource_id, table_name, limit=limit)
        columns = list(df.columns)
        rows = df.to_dict(orient="records")
        return {"columns": columns, "rows": rows, "row_count": len(rows)}

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

    async def write_table(self, datasource_id: str, table_name: str, records: list, **kwargs):
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
            if hasattr(connector, 'write_table_data'):
                return await connector.write_table_data(table_name, records, **kwargs)
            return {"success": False, "message": f"连接器 {ds.type} 不支持写入操作"}
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
