"""数据库连接器实现"""

from __future__ import annotations

import re
import asyncio
import glob
from typing import List, Dict, Any, Optional
import os
import io
import pathlib
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from loguru import logger

from app.services.datasource import BaseConnector


def _mtime_to_utc(path: str) -> Optional[datetime]:
    """文件 mtime → UTC aware datetime。

    os.path.getmtime 返回 timestamp（float），fromtimestamp 默认转本地 naive；
    显式用 fromtimestamp(ts, tz=timezone.utc) 得到 UTC aware，避免本地 naive
    被误当 UTC 导致时区错乱。
    """
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except Exception:
        return None

# 标识符安全校验：拒绝 SQL 注入危险字符，允许 Unicode（含中文）表名/列名
# 危险字符：双引号(PostgreSQL/SQLite引用符)、反引号(MySQL引用符)、单引号(SQL字符串)、分号(语句分隔)、null字节
_UNSAFE_IDENTIFIER_RE = re.compile(r'["\'`;\x00]')

# 平台支持的写入策略（fail-fast：不支持的策略在此拦截，不让连接器 if/elif 链静默 fall-through）
VALID_WRITE_STRATEGIES = {"fail", "append", "replace", "overwrite", "truncate", "delete_rows", "upsert", "create_new"}


def _validate_identifier(name: str) -> str:
    if not name or _UNSAFE_IDENTIFIER_RE.search(name):
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
        result = [dict(t) for t in tables]
        try:
            stat_rows = await self._connection.fetch(
                "SELECT relname, GREATEST(last_analyze, last_autoanalyze) AS last_analyzed FROM pg_stat_user_tables"
            )
            stat_map = {r["relname"]: r["last_analyzed"] for r in stat_rows if r["last_analyzed"]}
            for item in result:
                tname = item.get("table_name")
                if tname and tname in stat_map:
                    item["data_updated_at"] = stat_map[tname]
        except Exception:
            pass
        return result

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

    async def execute_query(self, query: str) -> pd.DataFrame:
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
          - create_new:  表已存在时自动创建新表（表名加 _1, _2 后缀），不存在则正常创建
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
            actual_table = table

            if table_exists:
                if if_table_exists in ("fail",):
                    return {"success": False, "message": f"表 '{table}' 已存在 (if_table_exists=fail)"}
                elif if_table_exists == "create_new":
                    # 自动找新表名：表名加 _1, _2, _3 ... 直到不存在
                    base = table
                    suffix = 1
                    while True:
                        candidate = f"{base}_{suffix}"
                        r = await self._connection.fetchrow("SELECT to_regclass($1)", candidate)
                        if not r or r[0] is None:
                            actual_table = candidate
                            break
                        suffix += 1
                    table = actual_table
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

            if not table_exists or if_table_exists == "create_new":
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

            result = {"success": True, "rows_written": len(records)}
            if actual_table != table:
                result["table_name"] = table
            return result
        except Exception as e:
            return {"success": False, "message": str(e), "error_type": type(e).__name__}

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
            raise ConnectionError("数据库连接失败，无法执行查询")
        async with self._connection.cursor() as cur:
            await cur.execute(
                "SELECT table_name, table_type, update_time FROM information_schema.tables WHERE table_schema = DATABASE()"
            )
            rows = await cur.fetchall()
        result = []
        for r in rows:
            item = {"table_name": r[0], "table_type": r[1]}
            if r[2]:
                item["data_updated_at"] = r[2]
            result.append(item)
        return result

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        import pandas as pd
        if not self._connection:
            await self.connect()
        if not self._connection:
            raise ConnectionError("数据库连接失败，无法执行查询")
        _validate_identifier(table)
        offset = (page - 1) * page_size
        async with self._connection.cursor() as cur:
            await cur.execute(f"SELECT * FROM `{table}` LIMIT %s OFFSET %s", (page_size, offset))
            rows = await cur.fetchall()
            cols = [desc[0] for desc in cur.description]
        return pd.DataFrame(rows, columns=cols)

    async def execute_query(self, query: str) -> pd.DataFrame:
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
            raise ConnectionError("数据库连接失败，无法执行查询")
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
        """写入数据到 MySQL 表。策略同 PostgreSQL: fail/append/replace/overwrite/truncate/delete_rows/upsert/create_new"""
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
                actual_table = table

                if table_exists:
                    if if_table_exists == "fail":
                        return {"success": False, "message": f"表 '{table}' 已存在 (if_table_exists=fail)"}
                    elif if_table_exists == "create_new":
                        base = table
                        suffix = 1
                        while True:
                            candidate = f"{base}_{suffix}"
                            await cur.execute(f"SHOW TABLES LIKE %s", (candidate,))
                            if await cur.fetchone() is None:
                                actual_table = candidate
                                break
                            suffix += 1
                        table = actual_table
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

                if not table_exists or if_table_exists == "create_new":
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
            result = {"success": True, "rows_written": len(records)}
            if actual_table != table:
                result["table_name"] = table
            return result
        except Exception as e:
            return {"success": False, "message": str(e), "error_type": type(e).__name__}

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
        data_updated_at = _mtime_to_utc(file_path)
        item = {"table_name": os.path.basename(file_path), "table_type": "csv"}
        if data_updated_at:
            item["data_updated_at"] = data_updated_at
        return [item]

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        import pandas as pd
        file_path = self.config.get("file_path", "")
        df = pd.read_csv(file_path)
        offset = (page - 1) * page_size
        return df.iloc[offset:offset + page_size]

    async def execute_query(self, query: str) -> pd.DataFrame:
        """用 DuckDB 在内存里对 CSV 跑 SQL。表名 = 文件 basename（不带扩展名）。
        多文件模式（mode=files）每个文件注册一张表。
        SQL 里表名建议用双引号包裹（中文/特殊字符），如 SELECT * FROM "销售数据"。
        """
        import pandas as pd
        try:
            import duckdb
        except ImportError:
            logger.warning("duckdb 未安装，CSV SQL 查询不可用")
            return pd.DataFrame()

        file_path = self.config.get("file_path", "")
        file_paths = self.config.get("file_paths", [])
        files = file_paths or ([file_path] if file_path else [])
        files = [f for f in files if f and os.path.exists(f)]
        if not files:
            return pd.DataFrame()

        con = duckdb.connect()
        try:
            for f in files:
                base = os.path.splitext(os.path.basename(f))[0]
                df = pd.read_csv(f)
                con.register(base, df)

            return con.execute(query).fetch_df()
        except Exception as e:
            logger.error(f"CSV DuckDB SQL 执行失败: {e} | SQL: {query[:200]}")
            raise
        finally:
            con.close()

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        import pandas as pd
        file_path = self.config.get("file_path", "")
        df = pd.read_csv(file_path)
        return {"row_count": len(df), "column_count": len(df.columns)}

    async def write_table_data(self, table: str, records: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        import pandas as pd
        import os as _os
        file_path = self.config.get("file_path", "")
        strategy = kwargs.get("if_table_exists", "fail")
        try:
            if _os.path.exists(file_path) and strategy == "fail":
                return {"success": False, "message": f"文件已存在: {file_path} (if_table_exists=fail)"}
            if _os.path.exists(file_path) and strategy == "create_new":
                base, ext = _os.path.splitext(file_path)
                suffix = 1
                while True:
                    candidate = f"{base}_{suffix}{ext}"
                    if not _os.path.exists(candidate):
                        file_path = candidate
                        break
                    suffix += 1
            df_new = pd.DataFrame(records)
            if _os.path.exists(file_path) and strategy == "append":
                df_old = pd.read_csv(file_path)
                df_new = pd.concat([df_old, df_new], ignore_index=True)
            df_new.to_csv(file_path, index=False, encoding="utf-8-sig")
            result = {"success": True, "rows_written": len(df_new)}
            if strategy == "create_new":
                result["file_path"] = file_path
            return result
        except Exception as e:
            return {"success": False, "message": str(e), "error_type": type(e).__name__}

    async def close(self) -> None:
        pass


class ExcelConnector(BaseConnector):
    """Excel文件连接器 — 支持单文件、多文件、文件夹模式"""

    def _get_excel_files(self) -> List[str]:
        """根据 config 返回所有 Excel 文件路径（仅 .xlsx/.xls，其他文件由 get_schema 标注 data_type）"""
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
        """返回所有文件列表（含非 Excel 文件，按 data_type 标注类型）。
        
        Excel 文件展开为 sheet 级表，其他文件（图片/PDF/Word 等）作为单条目列出。
        data_type: excel_sheet / image / document / unknown
        """
        import pandas as pd
        files = self._get_excel_files()
        if not files:
            return []

        _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tiff"}
        _DOC_EXTS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".md"}

        result = []
        for fpath in files:
            base = os.path.splitext(os.path.basename(fpath))[0]
            ext = os.path.splitext(fpath)[1].lower()
            file_data_updated_at = _mtime_to_utc(fpath)

            # 非 Excel 文件：按类型标注，不尝试读 sheet
            if ext not in (".xlsx", ".xls"):
                if ext in _IMAGE_EXTS:
                    data_type = "image"
                elif ext in _DOC_EXTS:
                    data_type = "document"
                else:
                    data_type = "unknown"
                item = {
                    "table_name": base,
                    "data_type": data_type,
                    "file_path": fpath,
                    "file_ext": ext,
                }
                if file_data_updated_at:
                    item["data_updated_at"] = file_data_updated_at
                result.append(item)
                continue

            # Excel 文件：展开 sheet
            try:
                xl = pd.ExcelFile(fpath)
                for i, sheet in enumerate(xl.sheet_names):
                    if i == 0:
                        table_name = base
                    else:
                        table_name = f"{base}_{sheet}"
                    item = {
                        "table_name": table_name,
                        "data_type": "excel_sheet",
                        "file_path": fpath,
                        "sheet_name": sheet,
                        "sheet_index": i,
                    }
                    if file_data_updated_at:
                        item["data_updated_at"] = file_data_updated_at
                    result.append(item)
            except Exception:
                item = {
                    "table_name": base,
                    "data_type": "excel_sheet",
                    "file_path": fpath,
                    "sheet_name": None,
                    "sheet_index": 0,
                }
                if file_data_updated_at:
                    item["data_updated_at"] = file_data_updated_at
                result.append(item)
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

    async def execute_query(self, query: str) -> pd.DataFrame:
        """用 DuckDB 在内存里对 Excel 跑 SQL。
        把所有 sheet 注册成 DuckDB 表，表名 = base + "_" + sheet_name（对齐 _resolve_table_name 格式）；
        第一个 sheet 同时注册为 base 名（精确匹配 base 时返回第一个 sheet）。
        SQL 里表名建议用双引号包裹（中文/特殊字符），如 SELECT * FROM "test_upload_员工"。
        """
        import pandas as pd
        try:
            import duckdb
        except ImportError:
            logger.warning("duckdb 未安装，Excel SQL 查询不可用")
            return pd.DataFrame()

        files = self._get_excel_files()
        if not files:
            return pd.DataFrame()

        con = duckdb.connect()
        try:
            for f in files:
                base = os.path.splitext(os.path.basename(f))[0]
                xls = pd.ExcelFile(f)
                for i, sheet_name in enumerate(xls.sheet_names):
                    df = pd.read_excel(f, sheet_name=sheet_name)
                    tbl = f"{base}_{sheet_name}" if sheet_name else base
                    con.register(tbl, df)
                    if i == 0:
                        con.register(base, df)

            return con.execute(query).fetch_df()
        except Exception as e:
            logger.error(f"Excel DuckDB SQL 执行失败: {e} | SQL: {query[:200]}")
            raise
        finally:
            con.close()

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
        strategy = kwargs.get("if_table_exists", "fail")

        # 文件不存在时：在数据源目录下创建新 xlsx 文件
        if not os.path.exists(file_path):
            # 如果 file_path 不是完整路径，拼接到数据源目录
            if not os.path.dirname(file_path):
                folder = self.config.get("file_path", "")
                if os.path.isdir(folder):
                    file_path = os.path.join(folder, file_path + ".xlsx")
                else:
                    return {"success": False, "message": f"无法确定文件路径: {file_path}"}
            if not file_path.endswith((".xlsx", ".xls")):
                file_path = file_path + ".xlsx"
            # 创建新文件
            df_new = pd.DataFrame(records)
            target_sheet = sheet_name if isinstance(sheet_name, str) else "Sheet1"
            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                df_new.to_excel(writer, sheet_name=target_sheet, index=False)
            return {"success": True, "rows_written": len(df_new), "created_new_file": True}

        try:
            xl_check = pd.ExcelFile(file_path)
            target_sheet_name = sheet_name if isinstance(sheet_name, str) else None
            actual_sheet = target_sheet_name

            if strategy == "fail":
                if target_sheet_name and target_sheet_name in xl_check.sheet_names:
                    xl_check.close()
                    return {"success": False, "message": f"Sheet '{target_sheet_name}' 已存在 (if_table_exists=fail)"}
            elif strategy == "create_new":
                if target_sheet_name and target_sheet_name in xl_check.sheet_names:
                    base = target_sheet_name
                    suffix = 1
                    while True:
                        candidate = f"{base}_{suffix}"
                        if candidate not in xl_check.sheet_names:
                            actual_sheet = candidate
                            break
                        suffix += 1
            xl_check.close()

            df_new = pd.DataFrame(records)
            xl = pd.ExcelFile(file_path)
            sheets_data = {}
            target_sheet = actual_sheet if strategy == "create_new" else (
                sheet_name if isinstance(sheet_name, str) and sheet_name in xl.sheet_names
                else xl.sheet_names[sheet_name if isinstance(sheet_name, int) else 0]
            )

            # 如果 target_sheet 不在已有 sheet 中（create_new 场景），保留所有已有 sheet 并追加新 sheet
            if strategy == "create_new" and actual_sheet not in xl.sheet_names:
                for s in xl.sheet_names:
                    sheets_data[s] = pd.read_excel(xl, sheet_name=s)
                sheets_data[actual_sheet] = df_new
            else:
                for s in xl.sheet_names:
                    if s == target_sheet:
                        if strategy == "append":
                            df_old = pd.read_excel(xl, sheet_name=s)
                            sheets_data[s] = pd.concat([df_old, df_new], ignore_index=True)
                        else:
                            sheets_data[s] = df_new
                    else:
                        sheets_data[s] = pd.read_excel(xl, sheet_name=s)
            xl.close()
            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                for s, df in sheets_data.items():
                    df.to_excel(writer, sheet_name=s, index=False)
            result = {"success": True, "rows_written": len(df_new)}
            if strategy == "create_new" and actual_sheet != target_sheet_name:
                result["sheet_name"] = actual_sheet
            return result
        except Exception as e:
            return {"success": False, "message": str(e), "error_type": type(e).__name__}

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
                        "data_updated_at": obj.last_modified,
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

    async def execute_query(self, query: str) -> pd.DataFrame:
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

    async def write_table_data(self, table: str, records: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """写入数据到 OBS 对象（序列化为 CSV 上传）。
        if_table_exists 策略: fail(默认,对象已存在则报错) / overwrite(覆盖) / append(下载+合并+上传)"""
        import pandas as pd
        if not self._client:
            await self.connect()
        if not self._client:
            return {"success": False, "message": "OBS 连接失败"}

        bucket = self.config.get("bucket", "")
        if not bucket:
            return {"success": False, "message": "OBS 未配置 bucket"}

        strategy = kwargs.get("if_table_exists", "fail")
        object_name = table if table.endswith(".csv") else f"{table}.csv"

        try:
            df_new = pd.DataFrame(records)

            # 检查对象是否已存在
            exists = False
            try:
                await asyncio.to_thread(self._client.stat_object, bucket, object_name)
                exists = True
            except Exception:
                pass

            if exists and strategy == "fail":
                return {"success": False, "message": f"对象 {object_name} 已存在（策略=fail）"}

            if exists and strategy == "append":
                response = await asyncio.to_thread(self._client.get_object, bucket, object_name)
                old_content = response.read()
                response.close()
                response.release_conn()
                df_old = pd.read_csv(io.BytesIO(old_content))
                df_new = pd.concat([df_old, df_new], ignore_index=True)

            # overwrite 或 append 合并后直接上传
            buf = io.StringIO()
            df_new.to_csv(buf, index=False, encoding="utf-8-sig")
            buf.seek(0)
            await asyncio.to_thread(
                self._client.put_object, bucket, object_name,
                io.BytesIO(buf.getvalue().encode("utf-8-sig")),
                len(buf.getvalue().encode("utf-8-sig")),
                "text/csv",
            )
            return {"success": True, "rows_written": len(df_new), "object": object_name}
        except Exception as e:
            logger.error(f"OBS写入失败: {e}")
            return {"success": False, "message": str(e), "error_type": type(e).__name__}

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
            from datetime import datetime as _dt
            result = []
            for item in items:
                mtime_ms = item.get("modificationTime")
                entry = {
                    "table_name": item.get("pathSuffix", ""),
                    "table_type": "hdfs_directory" if item.get("type") == "DIRECTORY" else "hdfs_file",
                    "size": item.get("length", 0),
                }
                if mtime_ms:
                    try:
                        entry["data_updated_at"] = _dt.fromtimestamp(mtime_ms / 1000)
                    except Exception:
                        pass
                result.append(entry)
            return result
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

    async def execute_query(self, query: str) -> pd.DataFrame:
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

    async def write_table_data(self, table: str, records: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """写入数据到 HDFS 文件（序列化为 CSV 上传 via WebHDFS PUT）。
        if_table_exists 策略: fail(默认) / overwrite(覆盖) / append(下载+合并+上传)"""
        import pandas as pd
        if not self._client:
            await self.connect()
        if not self._client:
            return {"success": False, "message": "HDFS 连接失败"}

        base_path = self.config.get("base_path", "/")
        strategy = kwargs.get("if_table_exists", "fail")
        file_name = table if table.endswith(".csv") else f"{table}.csv"
        file_path = f"{base_path.rstrip('/')}/{file_name.lstrip('/')}"

        try:
            df_new = pd.DataFrame(records)

            # 检查文件是否已存在
            exists = False
            check_params = {"op": "GETFILESTATUS", "user.name": self._user}
            check_resp = await self._client.get(f"{self._base_url}{file_path}", params=check_params)
            if check_resp.status_code == 200:
                exists = True

            if exists and strategy == "fail":
                return {"success": False, "message": f"文件 {file_name} 已存在（策略=fail）"}

            if exists and strategy == "append":
                open_params = {"op": "OPEN", "user.name": self._user}
                open_resp = await self._client.get(f"{self._base_url}{file_path}", params=open_params)
                if open_resp.status_code == 200:
                    df_old = pd.read_csv(io.BytesIO(open_resp.content))
                    df_new = pd.concat([df_old, df_new], ignore_index=True)

            # PUT 上传（overwrite=true 覆盖）
            csv_buf = io.StringIO()
            df_new.to_csv(csv_buf, index=False, encoding="utf-8-sig")
            csv_bytes = csv_buf.getvalue().encode("utf-8-sig")

            put_params = {"op": "CREATE", "user.name": self._user, "overwrite": "true"}
            put_resp = await self._client.put(
                f"{self._base_url}{file_path}",
                params=put_params,
                content=csv_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
            if put_resp.status_code in (200, 201):
                return {"success": True, "rows_written": len(df_new), "file": file_name}
            return {"success": False, "message": f"HDFS PUT 失败: HTTP {put_resp.status_code}"}
        except Exception as e:
            logger.error(f"HDFS写入失败: {e}")
            return {"success": False, "message": str(e), "error_type": type(e).__name__}

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

    async def execute_query(self, query: str) -> pd.DataFrame:
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

    async def write_table_data(
        self, table: str, records: List[Dict[str, Any]],
        if_table_exists: str = "fail",
        **kwargs,
    ) -> Dict[str, Any]:
        """写入数据到 ChromaDB 集合。

        if_table_exists 策略:
          - fail:        集合已存在则报错（默认）
          - append:      直接 upsert（ChromaDB 原生 id-based）
          - replace:     删除集合并重建（等同清空）
          - overwrite:   清空集合所有条目后 upsert（保留集合）
          - truncate:    同 overwrite
          - delete_rows: 同 overwrite（ChromaDB 无表结构概念）
          - upsert:      按 id upsert（ChromaDB 原生行为）
          - create_new:  集合已存在时自动创建新集合（名加 _1, _2 后缀）
        """
        if not records:
            return {"success": True, "rows_written": 0}

        client = self._get_client()

        # 检查集合是否存在（list_collections 返回 Collection 对象列表，取 .name）
        _collections = await asyncio.to_thread(client.list_collections)
        _existing_names = set()
        for c in _collections:
            if isinstance(c, str):
                _existing_names.add(c)
            elif hasattr(c, 'name'):
                _existing_names.add(c.name)
        table_exists = table in _existing_names
        actual_table = table

        if table_exists:
            if if_table_exists == "fail":
                return {"success": False, "message": f"集合 '{table}' 已存在 (if_table_exists=fail)"}
            elif if_table_exists == "create_new":
                base = table
                suffix = 1
                while True:
                    candidate = f"{base}_{suffix}"
                    if candidate not in _existing_names:
                        actual_table = candidate
                        break
                    suffix += 1
            elif if_table_exists == "replace":
                await asyncio.to_thread(client.delete_collection, table)
                table_exists = False
            elif if_table_exists in ("overwrite", "truncate", "delete_rows"):
                collection = await asyncio.to_thread(client.get_collection, table)
                existing = await asyncio.to_thread(collection.get, include=[])
                existing_ids = existing.get("ids", [])
                if existing_ids:
                    await asyncio.to_thread(collection.delete, ids=existing_ids)
            # append / upsert: 直接走 upsert

        collection = await asyncio.to_thread(client.get_or_create_collection, actual_table)
        ids = [r.get("id", str(i)) for i, r in enumerate(records)]
        documents = [r.get("document", r.get("text", "")) for r in records]
        metadatas = [r.get("metadata") or r.get("metadatas") or {"_source": "datacrab"} for r in records]
        embeddings = [r.get("embedding") for r in records]
        # 无 embedding 时用平台 LLM embedding API 预计算（避免 ChromaDB 默认 sentence-transformers 模型加载慢/不一致）
        if not any(e is not None for e in embeddings):
            try:
                from app.services.llm import llm_manager
                texts = [d if d else " " for d in documents]
                embeddings = await llm_manager.embed(texts)
                embeddings = [list(e) for e in embeddings]
            except Exception as e:
                logger.warning(f"ChromaDB embedding 预计算失败，回退 ChromaDB 默认: {e}")
                embeddings = None
        upsert_kwargs = {"ids": ids, "documents": documents, "metadatas": metadatas}
        if embeddings and any(e is not None for e in embeddings):
            upsert_kwargs["embeddings"] = [e for e in embeddings if e is not None]
        await asyncio.to_thread(collection.upsert, **upsert_kwargs)
        return {"success": True, "rows_written": len(ids), "collection": actual_table}

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
            raise ConnectionError("数据库连接失败，无法执行查询")
        async with self._connection.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
        ) as cursor:
            rows = await cursor.fetchall()
        # SQLite 不跟踪单表修改时间，用数据库文件 mtime 作为 data_updated_at（任意表被修改，文件 mtime 都会变）
        db_path = self.config.get("database", self.config.get("file_path", ""))
        data_updated_at = _mtime_to_utc(db_path)
        result = []
        for r in rows:
            item = {"table_name": r["name"], "table_type": r["type"]}
            if data_updated_at:
                item["data_updated_at"] = data_updated_at
            result.append(item)
        return result

    async def get_table_data(
        self, table: str, page: int = 1, page_size: int = 20,
        filters: Optional[Dict] = None, sort: Optional[Dict] = None,
    ) -> pd.DataFrame:
        import pandas as pd
        if not self._connection:
            await self.connect()
        if not self._connection:
            raise ConnectionError("数据库连接失败，无法执行查询")
        _validate_identifier(table)
        offset = (page - 1) * page_size
        async with self._connection.execute(
            f'SELECT * FROM "{table}" LIMIT ? OFFSET ?', (page_size, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return pd.DataFrame([dict(r) for r in rows], columns=columns)

    async def execute_query(self, query: str) -> pd.DataFrame:
        import pandas as pd
        if not self._connection:
            await self.connect()
        if not self._connection:
            raise ConnectionError("数据库连接失败，无法执行查询")
        async with self._connection.execute(query) as cursor:
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return pd.DataFrame([dict(r) for r in rows], columns=columns)

    async def get_table_stats(self, table: str) -> Dict[str, Any]:
        if not self._connection:
            await self.connect()
        if not self._connection:
            raise ConnectionError("数据库连接失败，无法执行查询")
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
        """写入数据到 SQLite 表。策略同 PostgreSQL: fail/append/replace/overwrite/truncate/delete_rows/upsert/create_new"""
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
            actual_table = table

            if table_exists:
                if if_table_exists == "fail":
                    return {"success": False, "message": f"表 '{table}' 已存在 (if_table_exists=fail)"}
                elif if_table_exists == "create_new":
                    base = table
                    suffix = 1
                    while True:
                        candidate = f"{base}_{suffix}"
                        async with self._connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (candidate,)
                        ) as cursor:
                            if await cursor.fetchone() is None:
                                actual_table = candidate
                                break
                        suffix += 1
                    table = actual_table
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

            if not table_exists or if_table_exists == "create_new":
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
            result = {"success": True, "rows_written": len(records)}
            if actual_table != table:
                result["table_name"] = table
            return result
        except Exception as e:
            return {"success": False, "message": str(e), "error_type": type(e).__name__}

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None


class GenericFileConnector(BaseConnector):
    """通用文件连接器 — 列出文件夹下的所有文件（按扩展名过滤）。

    支持 mode=files（file_paths 列表，聊天上传用）和 file_path（单文件/文件夹）。
    不解析文件内容，只返回文件列表（文件名/路径/大小/扩展名/修改时间）。
    """

    def _get_files(self) -> list:
        mode = self.config.get("mode", "file")
        file_path = self.config.get("file_path", "")
        file_paths = self.config.get("file_paths", [])
        file_filter = self.config.get("file_filter", "")

        exts = None
        if file_filter:
            exts = set(e.strip().lower().lstrip(".") for e in file_filter.split(",") if e.strip())

        if mode == "files" and file_paths:
            return [pathlib.Path(f) for f in file_paths if pathlib.Path(f).exists()]
        elif file_path:
            p = pathlib.Path(file_path)
            if not p.exists():
                return []
            if p.is_file():
                return [p]
            files = []
            for f in p.rglob("*"):
                if f.is_file():
                    if exts is None or f.suffix.lower().lstrip(".") in exts:
                        files.append(f)
            return files
        return []

    async def connect(self) -> bool:
        return len(self._get_files()) > 0

    async def test_connection(self) -> bool:
        try:
            return await self.connect()
        except Exception:
            return False

    async def get_schema(self) -> list:
        files = self._get_files()
        return [
            {
                "table_name": f.stem,
                "table_type": "file",
                "data_type": f.suffix.lower().lstrip("."),
                "file_path": str(f),
            }
            for f in files
        ]

    async def get_table_data(self, table, page=1, page_size=20, filters=None, sort=None):
        import pandas as pd
        files = self._get_files()
        if not files:
            return pd.DataFrame()

        # table 是文件 stem（get_schema 返回的 table_name = f.stem）
        # 选中具体文件时，解析该文件内容；未选中时返回文件列表
        target = None
        if table:
            target = next((f for f in files if f.stem == table), None)

        if target:
            ext = target.suffix.lower().lstrip(".")
            try:
                if ext == "csv":
                    df = pd.read_csv(target)
                    offset = (page - 1) * page_size
                    return df.iloc[offset:offset + page_size]
                elif ext in ("xlsx", "xls"):
                    # table 可能是 "stem_sheetname" 格式
                    sheet_name = 0
                    if "_" in table and table.rsplit("_", 1)[-1] != target.stem:
                        candidate_sheet = table.rsplit("_", 1)[-1]
                        try:
                            xls = pd.ExcelFile(target)
                            if candidate_sheet in xls.sheet_names:
                                sheet_name = candidate_sheet
                        except Exception:
                            pass
                    df = pd.read_excel(target, sheet_name=sheet_name)
                    offset = (page - 1) * page_size
                    return df.iloc[offset:offset + page_size]
                elif ext == "json":
                    df = pd.read_json(target)
                    offset = (page - 1) * page_size
                    return df.iloc[offset:offset + page_size]
                elif ext == "parquet":
                    df = pd.read_parquet(target)
                    offset = (page - 1) * page_size
                    return df.iloc[offset:offset + page_size]
            except Exception:
                pass  # 解析失败则回退到文件详情

            # 非结构化文件：返回单文件详情
            stat = target.stat()
            size = stat.st_size
            if size >= 1073741824:
                size_h = f"{size / 1073741824:.2f} GB"
            elif size >= 1048576:
                size_h = f"{size / 1048576:.2f} MB"
            elif size >= 1024:
                size_h = f"{size / 1024:.2f} KB"
            else:
                size_h = f"{size} B"
            return pd.DataFrame([{
                "file_name": target.name,
                "file_path": str(target),
                "extension": ext,
                "size_bytes": size,
                "size_human": size_h,
                "modified_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            }])

        # 未选中具体文件：返回文件列表
        rows = []
        for f in files:
            stat = f.stat()
            size = stat.st_size
            if size >= 1073741824:
                size_h = f"{size / 1073741824:.2f} GB"
            elif size >= 1048576:
                size_h = f"{size / 1048576:.2f} MB"
            elif size >= 1024:
                size_h = f"{size / 1024:.2f} KB"
            else:
                size_h = f"{size} B"
            rows.append({
                "file_name": f.name,
                "file_path": str(f),
                "extension": f.suffix.lower().lstrip("."),
                "size_bytes": size,
                "size_human": size_h,
                "modified_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "parent_dir": str(f.parent),
            })
        df = pd.DataFrame(rows)
        offset = (page - 1) * page_size
        return df.iloc[offset:offset + page_size]

    async def get_table_stats(self, table):
        files = self._get_files()
        if table:
            target = next((f for f in files if f.stem == table), None)
            if target:
                ext = target.suffix.lower().lstrip(".")
                try:
                    import pandas as pd
                    if ext == "csv":
                        return {"row_count": len(pd.read_csv(target)), "table_name": table}
                    elif ext in ("xlsx", "xls"):
                        df = pd.read_excel(target)
                        return {"row_count": len(df), "table_name": table}
                    elif ext == "json":
                        return {"row_count": len(pd.read_json(target)), "table_name": table}
                    elif ext == "parquet":
                        return {"row_count": len(pd.read_parquet(target)), "table_name": table}
                except Exception:
                    pass
                return {"row_count": 1, "table_name": table}
        return {"row_count": len(files), "table_name": table}

    async def write_table_data(self, table: str, records: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """写入数据到文件。根据 table 名的扩展名决定写入格式。
        策略: fail(默认) / append / overwrite / replace / create_new"""
        import pandas as pd
        mode = kwargs.get("if_table_exists", "fail")
        df = pd.DataFrame(records)

        # table 是文件名（带后缀），在文件列表所在目录写
        files = self._get_files()
        if files:
            out_dir = files[0].parent
        else:
            out_dir = pathlib.Path(os.path.join(os.environ.get("TEMP", "/tmp"), "datacrab_output"))
            out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / table
        if not out_path.suffix:
            out_path = out_path.with_suffix(".xlsx")
        ext = out_path.suffix.lower().lstrip(".")

        # create_new: 文件已存在时自动找新文件名
        if out_path.exists() and mode == "create_new":
            base = out_path.stem
            suffix = 1
            while True:
                candidate = out_dir / f"{base}_{suffix}{out_path.suffix}"
                if not candidate.exists():
                    out_path = candidate
                    break
                suffix += 1
            mode = "fail"  # 新文件不存在，改 fail 直接写

        if out_path.exists():
            if mode == "fail":
                return {"success": False, "message": f"文件已存在: {out_path.name} (if_table_exists=fail)"}
            elif mode == "replace":
                out_path.unlink()

        try:
            if ext == "csv":
                if mode == "append" and out_path.exists():
                    old = pd.read_csv(out_path)
                    df = pd.concat([old, df], ignore_index=True)
                df.to_csv(out_path, index=False, encoding="utf-8-sig")
            elif ext in ("xlsx", "xls"):
                if mode == "append" and out_path.exists():
                    old = pd.read_excel(out_path)
                    df = pd.concat([old, df], ignore_index=True)
                df.to_excel(out_path, index=False)
            elif ext == "json":
                if mode == "append" and out_path.exists():
                    old = pd.read_json(out_path)
                    df = pd.concat([old, df], ignore_index=True)
                df.to_json(out_path, orient="records", force_ascii=False)
            else:
                return {"success": False, "message": f"generic_file 不支持写入 {ext} 格式文件"}

            return {"success": True, "rows_written": len(df), "file_path": str(out_path)}
        except Exception as e:
            return {"success": False, "message": str(e), "error_type": type(e).__name__}

    async def close(self):
        pass


# ========== 统一连接器注册表 ==========
# 所有连接器地位平等：启动时统一从 DB 加载、exec() 装载到本注册表。
# seed 连接器的类定义保留在本文件作为源码来源，启动时用 inspect.getsource 提取源码 seed 进 DB。
_connector_registry: Dict[str, type] = {}

# 支持的数据源类型列表（启动时从注册表 in-place 填充，保持外部模块引用同步）
SUPPORTED_DATASOURCE_TYPES: List[str] = []

# 沙箱禁止 import 的危险模块（其余模块允许，以满足 seed 连接器对 os/glob/io/httpx 等的依赖）
_DANGER_IMPORTS = {"subprocess", "shutil", "ctypes", "sys", "socket", "pickle", "threading", "multiprocessing"}

# seed 连接器元信息：name → {display_name, description, config_template, class}
# 启动时 seed 到 DB（is_seed=True），运行时直接用类加载（跳过 exec 提速）

# seed 连接器元信息：name → {display_name, description, config_template, class}
_SEED_CONNECTORS: Dict[str, Dict[str, Any]] = {
    "postgresql": {
        "display_name": "PostgreSQL",
        "description": "基于 asyncpg 的异步 PostgreSQL 连接",
        "class": PostgreSQLConnector,
        "config_template": [
            {"name": "host", "label": "主机地址", "type": "string", "required": True, "default": "localhost"},
            {"name": "port", "label": "端口", "type": "number", "required": True, "default": 5432},
            {"name": "database", "label": "数据库名", "type": "string", "required": True},
            {"name": "user", "label": "用户名", "type": "string", "required": True},
            {"name": "password", "label": "密码", "type": "password", "required": True},
        ],
    },
    "mysql": {
        "display_name": "MySQL",
        "description": "基于 aiomysql 的异步 MySQL 连接",
        "class": MySQLConnector,
        "config_template": [
            {"name": "host", "label": "主机地址", "type": "string", "required": True, "default": "localhost"},
            {"name": "port", "label": "端口", "type": "number", "required": True, "default": 3306},
            {"name": "database", "label": "数据库名", "type": "string", "required": True},
            {"name": "user", "label": "用户名", "type": "string", "required": True},
            {"name": "password", "label": "密码", "type": "password", "required": True},
        ],
    },
    "sqlite": {
        "display_name": "SQLite",
        "description": "基于 aiosqlite 的 SQLite 连接",
        "class": SQLiteConnector,
        "config_template": [
            {"name": "database", "label": "数据库文件路径", "type": "filepath", "required": True},
        ],
    },
    "csv": {
        "display_name": "CSV 文件",
        "description": "本地 CSV 文件连接器",
        "class": CSVConnector,
        "config_template": [
            {"name": "file_path", "label": "文件路径", "type": "filepath", "required": True},
        ],
    },
    "excel": {
        "display_name": "Excel 文件",
        "description": "Excel 文件连接器，支持单文件、多文件、文件夹模式",
        "class": ExcelConnector,
        "config_template": [
            {"name": "mode", "label": "模式", "type": "select", "required": True, "default": "file",
             "options": [{"label": "单文件", "value": "file"}, {"label": "多文件", "value": "files"}, {"label": "文件夹", "value": "folder"}]},
            {"name": "file_path", "label": "文件路径", "type": "filepath", "required": True, "depends_on": {"mode": "file"}},
            {"name": "file_path", "label": "文件夹路径", "type": "folderpath", "required": True, "depends_on": {"mode": "folder"}},
            {"name": "file_paths", "label": "文件列表", "type": "filepath_list", "required": True, "depends_on": {"mode": "files"}},
        ],
    },
    "obs": {
        "display_name": "OBS 华为云对象存储",
        "description": "华为云 OBS / S3 兼容对象存储连接器",
        "class": OBSConnector,
        "config_template": [
            {"name": "endpoint", "label": "Endpoint", "type": "string", "required": True},
            {"name": "access_key", "label": "Access Key", "type": "string", "required": True},
            {"name": "secret_key", "label": "Secret Key", "type": "password", "required": True},
            {"name": "bucket", "label": "Bucket", "type": "string", "required": False},
            {"name": "prefix", "label": "前缀", "type": "string", "required": False},
            {"name": "secure", "label": "HTTPS", "type": "boolean", "default": True},
            {"name": "region", "label": "Region", "type": "string", "required": False},
        ],
    },
    "hadoop": {
        "display_name": "Hadoop HDFS",
        "description": "通过 WebHDFS REST API 访问 HDFS",
        "class": HadoopHDFSConnector,
        "config_template": [
            {"name": "host", "label": "主机地址", "type": "string", "required": True, "default": "localhost"},
            {"name": "port", "label": "端口", "type": "number", "required": True, "default": 9870},
            {"name": "user", "label": "用户名", "type": "string", "required": True, "default": "hadoop"},
            {"name": "base_path", "label": "基础路径", "type": "string", "required": False, "default": "/"},
            {"name": "secure", "label": "HTTPS", "type": "boolean", "default": False},
        ],
    },
    "chroma": {
        "display_name": "ChromaDB 向量库",
        "description": "ChromaDB 嵌入式向量库，集合（Collection）即数据表",
        "class": ChromaConnector,
        "config_template": [
            {"name": "persist_directory", "label": "数据目录", "type": "folderpath", "required": True, "default": "d:/chroma-data"},
        ],
    },
    "generic_file": {
        "display_name": "通用文件",
        "description": "通用文件连接器，列出文件夹/文件列表，支持扩展名过滤和多文件模式",
        "class": GenericFileConnector,
        "config_template": [
            {"name": "mode", "label": "模式", "type": "select", "required": True, "default": "file",
             "options": [{"label": "单文件/文件夹", "value": "file"}, {"label": "多文件", "value": "files"}]},
            {"name": "file_path", "label": "文件/文件夹路径", "type": "folderpath", "required": True, "depends_on": {"mode": "file"}},
            {"name": "file_paths", "label": "文件列表", "type": "filepath_list", "required": True, "depends_on": {"mode": "files"}},
            {"name": "file_filter", "label": "文件过滤（逗号分隔扩展名，如 jpg,png,gif；留空表示所有文件）", "type": "string", "required": False},
        ],
    },
}


def _build_exec_namespace() -> dict:
    """构建连接器 exec 命名空间（提供 seed 连接器所需的模块与工具函数）"""
    import pandas as _pd
    import numpy as _np
    return {
        "BaseConnector": BaseConnector,
        "pd": _pd, "numpy": _np, "np": _np,
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
        "os": os, "re": re, "io": io, "glob": glob, "asyncio": asyncio,
        "httpx": httpx, "logger": logger, "urljoin": urljoin,
        "json": __import__("json"), "datetime": __import__("datetime"),
        "_validate_identifier": _validate_identifier,
    }


def _load_connector_class(code: str, name: str) -> type:
    """从 Python 源码动态加载连接器类（沙箱 exec 统一加载 + 契约校验）"""
    import ast
    import inspect
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            if module and module.split(".")[0] in _DANGER_IMPORTS:
                raise ValueError(f"连接器禁止 import: {module}")
    namespace = _build_exec_namespace()
    exec(code, namespace)
    cls = None
    for obj in namespace.values():
        if isinstance(obj, type) and issubclass(obj, BaseConnector) and obj is not BaseConnector:
            cls = obj
            break
    if cls is None:
        raise ValueError(f"代码中未找到 BaseConnector 的子类: {name}")

    # 契约校验：6 个抽象方法必须存在且为 async def
    _REQUIRED_ASYNC_METHODS = ("connect", "test_connection", "get_schema", "get_table_data", "get_table_stats", "close")
    errors = []
    for m in _REQUIRED_ASYNC_METHODS:
        method = getattr(cls, m, None)
        if method is None:
            errors.append(f"缺少方法 {m}")
        elif not inspect.iscoroutinefunction(method):
            errors.append(f"方法 {m} 必须是 async def（当前是普通 def）")

    # 签名校验：get_table_data 必须含 page 和 page_size 参数
    gtd = getattr(cls, "get_table_data", None)
    if gtd and inspect.iscoroutinefunction(gtd):
        try:
            sig = inspect.signature(gtd)
            params = set(sig.parameters.keys())
            if "page" not in params or "page_size" not in params:
                errors.append("get_table_data 签名必须含 page 和 page_size 参数（如 async def get_table_data(self, table, page=1, page_size=20, filters=None, sort=None)）")
        except (ValueError, TypeError):
            pass

    if errors:
        raise ValueError(f"连接器 '{name}' 契约校验失败: {'; '.join(errors)}")

    return cls


def _sync_supported_types() -> None:
    """同步 SUPPORTED_DATASOURCE_TYPES（in-place 更新以保持外部模块引用同步）"""
    SUPPORTED_DATASOURCE_TYPES.clear()
    SUPPORTED_DATASOURCE_TYPES.extend(_connector_registry.keys())


def register_custom_connector(name: str, code: str) -> type:
    """注册连接器：验证代码 → 加入注册表（AI 生成/修改连接器后即时生效）"""
    cls = _load_connector_class(code, name)
    _connector_registry[name] = cls
    _sync_supported_types()
    logger.info(f"连接器已注册: {name} → {cls.__name__}")
    return cls


def get_custom_connector_types() -> List[str]:
    """获取所有已注册连接器类型名（兼容旧名）"""
    return list(_connector_registry.keys())


def get_all_connector_types() -> List[str]:
    """获取所有已注册连接器类型名"""
    return list(_connector_registry.keys())


def _load_single_connector_from_db(name: str) -> Optional[type]:
    """从 DB 按需加载单个连接器（同步，供子进程使用）"""
    try:
        import sqlite3
        from app.core.config import settings
        db_url = settings.DATABASE_URL
        db_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        if not db_path:
            return None
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT code FROM custom_connectors WHERE name=? AND is_active=1", (name,)).fetchone()
        conn.close()
        if row and row[0]:
            cls = _load_connector_class(row[0], name)
            _connector_registry[name] = cls
            return cls
    except Exception as e:
        logger.warning(f"按需加载连接器 {name} 失败: {e}")
    return None


def get_connector(datasource_type: str, config: Dict[str, Any]) -> BaseConnector:
    """获取连接器实例（注册表 → 内置类 → 按需 DB 加载，兼容子进程）"""
    connector_class = _connector_registry.get(datasource_type)
    if not connector_class:
        # 降级 1：seed 连接器直接用类（子进程中注册表为空时）
        meta = _SEED_CONNECTORS.get(datasource_type)
        if meta:
            connector_class = meta["class"]
            _connector_registry[datasource_type] = connector_class
    if not connector_class:
        # 降级 2：从 DB 按需加载（自定义连接器，子进程中使用）
        connector_class = _load_single_connector_from_db(datasource_type)
    if not connector_class:
        raise ValueError(f"不支持的数据源类型: {datasource_type}")
    return connector_class(config)


async def load_connectors_from_db() -> None:
    """启动时从 DB 加载所有连接器；seed 连接器首次启动时自动写入 DB"""
    import inspect
    from app.core.database import async_session
    from app.models.custom_extension import CustomConnector
    from sqlalchemy import select as sa_select

    async with async_session() as session:
        # 查询超级管理员，作为 seed 连接器的 created_by（与用户创建的连接器无区别）
        from app.models.user import User
        admin = await session.execute(
            sa_select(User).where(User.is_superuser == True, User.is_active == True).order_by(User.id).limit(1)
        )
        admin_user = admin.scalar_one_or_none()
        admin_id = admin_user.id if admin_user else None

        # seed 连接器（仅在 DB 无记录时写入；用户删除后不会复活）
        for name, meta in _SEED_CONNECTORS.items():
            existing = await session.execute(
                sa_select(CustomConnector).where(CustomConnector.name == name)
            )
            record = existing.scalar_one_or_none()
            if not record:
                source = inspect.getsource(meta["class"])
                record = CustomConnector(
                    name=name,
                    display_name=meta["display_name"],
                    description=meta["description"],
                    code=source,
                    config_template=meta["config_template"],
                    created_by=admin_id,
                    is_seed=True,
                )
                session.add(record)
            else:
                # 已存在的 seed 连接器确保标记为 seed
                record.is_seed = True
        await session.commit()

        # 加载所有活跃连接器到注册表（seed 的直接用类，跳过 exec 提速）
        result = await session.execute(
            sa_select(CustomConnector).where(CustomConnector.is_active == True)
        )
        _connector_registry.clear()
        for c in result.scalars().all():
            try:
                if c.name in _SEED_CONNECTORS:
                    _connector_registry[c.name] = _SEED_CONNECTORS[c.name]["class"]
                else:
                    _connector_registry[c.name] = _load_connector_class(c.code, c.name)
            except Exception as e:
                logger.error(f"加载连接器 {c.name} 失败: {e}")
        _sync_supported_types()
        logger.info(f"已加载 {len(_connector_registry)} 个连接器: {list(_connector_registry.keys())}")


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

        # fail-fast：不支持的写入策略立即报错（对齐 OpenCode：不静默 fall-through）
        strategy = kwargs.get("if_table_exists", "fail")
        if strategy not in VALID_WRITE_STRATEGIES:
            return {"success": False, "error": f"不支持的写入策略 '{strategy}'，支持的策略: {', '.join(sorted(VALID_WRITE_STRATEGIES))}"}

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
