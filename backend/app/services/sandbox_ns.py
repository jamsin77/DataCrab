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
        """在算子脚本中直接调用大模型"""
        from app.services.llm import llm_manager

        async def _run():
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

        return run_async_in_thread(_run())

    return {
        "query_table_data": query_table_data,
        "get_table_schema": get_table_schema,
        "get_datasource_id_by_name": get_datasource_id_by_name,
        "llm_chat": llm_chat,
        "pd": pd,
        "json": json,
    }
