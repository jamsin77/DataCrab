"""算子沙箱命名空间构建 - 供算子脚本执行时注入工具函数"""

import asyncio
import json
import threading

from app.core.database import async_session


def run_async_in_thread(coro):
    """在独立线程的新 event loop 中运行协程，供同步算子脚本内部调用异步 DB 操作"""
    result_container = {}
    exception_container = {}

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            result_container["value"] = loop.run_until_complete(coro)
        except Exception as exc:
            exception_container["value"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(timeout=60)

    if "value" in exception_container:
        raise exception_container["value"]
    if thread.is_alive():
        raise RuntimeError("查询超时（60秒）")
    return result_container.get("value")


def build_operator_namespace(current_user_id):
    """构建算子脚本执行命名空间，注入数据查询、LLM 调用等工具函数"""
    import pandas as pd

    def query_table_data(datasource_id, table_name, **kwargs):
        args = {"datasource_id": str(datasource_id), "table_name": table_name, **kwargs}

        async def _run():
            async with async_session() as db:
                from app.services.shared_tools import execute_shared_tool
                return await execute_shared_tool("query_table_data", args, db, current_user_id)

        result = json.loads(run_async_in_thread(_run()))
        if isinstance(result, dict) and "rows" in result and "columns" in result:
            return pd.DataFrame(result["rows"], columns=result["columns"])
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(result["error"])
        return result

    def get_table_schema(datasource_id, table_name):
        args = {"datasource_id": str(datasource_id), "table_name": table_name}

        async def _run():
            async with async_session() as db:
                from app.services.shared_tools import execute_shared_tool
                return await execute_shared_tool("get_table_schema", args, db, current_user_id)

        return json.loads(run_async_in_thread(_run()))

    def get_datasource_id_by_name(name):
        async def _run():
            async with async_session() as db:
                from sqlalchemy import select as _select
                from app.models.datasource import DataSource as _DS
                result = await db.execute(_select(_DS).where(_DS.name == name))
                ds = result.scalar_one_or_none()
                if ds is None:
                    return json.dumps({"error": f"未找到数据源: {name}"})
                return json.dumps({"id": str(ds.id), "name": ds.name, "type": ds.type})

        result = json.loads(run_async_in_thread(_run()))
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["id"]

    def llm_chat(prompt, system_prompt=None, temperature=0.7, max_tokens=2000):
        """在算子脚本中直接调用大模型（自动使用当前用户的 LLM 配置）"""
        from app.services.llm import llm_manager, init_user_llm_context, reset_user_llm_config

        async def _run():
            if current_user_id:
                await init_user_llm_context(current_user_id)
            try:
                await llm_manager.initialize()
                if system_prompt:
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ]
                    return await llm_manager.chat_with_messages(
                        messages, temperature=temperature, max_tokens=max_tokens
                    )
                return await llm_manager.chat(
                    prompt, temperature=temperature, max_tokens=max_tokens
                )
            finally:
                reset_user_llm_config()

        return run_async_in_thread(_run())

    def execute_sql(datasource_id, sql, params=None, limit=10000):
        """在数据源上执行 SQL，返回 DataFrame（支持 JOIN/聚合/窗口函数）"""
        import uuid as _uuid

        async def _run():
            async with async_session() as db:
                from sqlalchemy import select as _select
                from app.models.datasource import DataSource as _DS
                from app.services.connectors import get_connector
                result = await db.execute(_select(_DS).where(_DS.id == _uuid.UUID(str(datasource_id))))
                ds = result.scalar_one_or_none()
                if not ds:
                    raise RuntimeError(f"数据源不存在: {datasource_id}")
                connector = get_connector(ds.type, ds.connection_config or {})
                try:
                    await connector.connect()
                    df = await connector.execute_query(sql)
                finally:
                    await connector.close()
                if df is not None and not df.empty and len(df) > limit:
                    df = df.head(limit)
                return df

        return run_async_in_thread(_run())

    def list_tables(datasource_id):
        """列出数据源中的所有表名，返回 list[str]"""
        import uuid as _uuid

        async def _run():
            async with async_session() as db:
                from sqlalchemy import select as _select
                from app.models.datasource import DataSource as _DS
                from app.services.connectors import get_connector
                result = await db.execute(_select(_DS).where(_DS.id == _uuid.UUID(str(datasource_id))))
                ds = result.scalar_one_or_none()
                if not ds:
                    raise RuntimeError(f"数据源不存在: {datasource_id}")
                connector = get_connector(ds.type, ds.connection_config or {})
                try:
                    await connector.connect()
                    schema = await connector.get_schema()
                finally:
                    await connector.close()
                return [t.get("table_name", str(t)) if isinstance(t, dict) else str(t) for t in schema]

        return run_async_in_thread(_run())

    def iter_table_data(datasource_id, table_name, chunk_size=10000):
        """分块迭代读取大表数据，返回生成器，每次 yield DataFrame"""
        import uuid as _uuid

        def _generator():
            page = 1
            while True:
                async def _fetch(p=page):
                    async with async_session() as db:
                        from sqlalchemy import select as _select
                        from app.models.datasource import DataSource as _DS
                        from app.services.connectors import get_connector
                        result = await db.execute(_select(_DS).where(_DS.id == _uuid.UUID(str(datasource_id))))
                        ds = result.scalar_one_or_none()
                        if not ds:
                            raise RuntimeError(f"数据源不存在: {datasource_id}")
                        connector = get_connector(ds.type, ds.connection_config or {})
                        try:
                            await connector.connect()
                            df = await connector.get_table_data(table_name, page=p, page_size=chunk_size)
                            stats = await connector.get_table_stats(table_name)
                        finally:
                            await connector.close()
                        return df, stats.get("row_count", len(df))

                df, total = run_async_in_thread(_fetch())
                if df is None or df.empty:
                    break
                yield df
                if page * chunk_size >= total:
                    break
                page += 1

        return _generator()

    def read_file(path, format=None):
        """读取文件（自动检测格式，路径须在文件链接授权目录内）"""
        from pathlib import Path

        async def _run():
            async with async_session() as db:
                from sqlalchemy import select as _select
                from app.models.filelink import FileLink
                result = await db.execute(_select(FileLink).where(
                    FileLink.is_active == True, FileLink.created_by == current_user_id
                ))
                links = result.scalars().all()
                allowed = [f.path for f in links if f.link_type == "directory"]
                for f in links:
                    if f.link_type == "file":
                        allowed.append(str(Path(f.path).parent))

                resolved = Path(path).resolve()
                ok = any(str(resolved).startswith(str(Path(a).resolve())) for a in allowed)
                if not ok:
                    raise RuntimeError(f"路径不在授权目录范围内: {path}")

                if not resolved.exists():
                    raise RuntimeError(f"文件不存在: {path}")

                ext = resolved.suffix.lower()
                if ext == ".json":
                    return json.loads(resolved.read_text(encoding="utf-8"))
                elif ext == ".csv":
                    return pd.read_csv(resolved)
                elif ext in (".xlsx", ".xls"):
                    return pd.read_excel(resolved)
                elif ext == ".parquet":
                    return pd.read_parquet(resolved)
                else:
                    return resolved.read_text(encoding="utf-8")

        return run_async_in_thread(_run())

    def write_file(path, data, format=None):
        """写入文件（路径须在文件链接授权目录内）"""
        from pathlib import Path

        async def _run():
            async with async_session() as db:
                from sqlalchemy import select as _select
                from app.models.filelink import FileLink
                result = await db.execute(_select(FileLink).where(
                    FileLink.is_active == True, FileLink.created_by == current_user_id
                ))
                links = result.scalars().all()
                allowed = [f.path for f in links if f.link_type == "directory"]

                resolved = Path(path).resolve()
                ok = any(str(resolved).startswith(str(Path(a).resolve())) for a in allowed)
                if not ok:
                    raise RuntimeError(f"路径不在授权目录范围内: {path}")

                resolved.parent.mkdir(parents=True, exist_ok=True)
                ext = resolved.suffix.lower()
                if ext == ".json" or format == "json":
                    resolved.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                elif ext == ".csv" or format == "csv":
                    if hasattr(data, "to_csv"):
                        data.to_csv(resolved, index=False, encoding="utf-8-sig")
                    elif isinstance(data, list) and data and isinstance(data[0], dict):
                        pd.DataFrame(data).to_csv(resolved, index=False, encoding="utf-8-sig")
                    else:
                        resolved.write_text(str(data), encoding="utf-8")
                else:
                    if isinstance(data, (dict, list)):
                        resolved.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    else:
                        resolved.write_text(str(data), encoding="utf-8")
                return {"success": True, "path": str(resolved), "size": resolved.stat().st_size}

        return run_async_in_thread(_run())

    def compute_map(fn, partitions, backend="local", **kwargs):
        """对分块数据并行执行函数（分布式计算抽象）
        backend: "sequential" / "local"(multiprocessing) / "ray"(预留)
        """
        from app.services.compute_backend import compute_map as _cm
        return _cm(fn, partitions, backend=backend, **kwargs)

    return {
        "query_table_data": query_table_data,
        "get_table_schema": get_table_schema,
        "get_datasource_id_by_name": get_datasource_id_by_name,
        "llm_chat": llm_chat,
        "execute_sql": execute_sql,
        "list_tables": list_tables,
        "iter_table_data": iter_table_data,
        "read_file": read_file,
        "write_file": write_file,
        "compute_map": compute_map,
        "pd": pd,
        "json": json,
    }
