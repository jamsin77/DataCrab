"""Agent服务 - 赋予LLM实际执行操作的能力"""

import json
import asyncio
from typing import Dict, Any, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from uuid import UUID

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm import llm_manager
from app.models.datasource import DataSource
from app.models.filelink import FileLink
from app.services.connectors import get_connector
from loguru import logger

MAX_AGENT_ITERATIONS = 5

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_table_data",
            "description": "查询数据源中某个表的数据，支持筛选、排序和分页",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源的UUID"},
                    "table_name": {"type": "string", "description": "要查询的表名"},
                    "filter_column": {"type": "string", "description": "用于筛选的列名，可选"},
                    "filter_value": {"type": "string", "description": "筛选的值，支持正则和|分隔的多值OR匹配，可选"},
                    "sort_column": {"type": "string", "description": "排序的列名，可选"},
                    "sort_order": {"type": "string", "enum": ["asc", "desc"], "description": "排序方向"},
                    "limit": {"type": "integer", "description": "返回的最大行数，默认100"},
                },
                "required": ["datasource_id", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_schema",
            "description": "获取数据源中某个表的结构信息（列名、数据类型、行数等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源的UUID"},
                    "table_name": {"type": "string", "description": "要查看结构的表名"},
                },
                "required": ["datasource_id", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_user_file_links",
            "description": "列出用户已挂载的文件链接目录",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_user_datasources",
            "description": "列出用户已连接的数据源，包括名称、类型、表列表",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_file_to_link",
            "description": "在用户已授权的文件链接目录中保存文件（CSV格式）",
            "parameters": {
                "type": "object",
                "properties": {
                    "link_id": {"type": "string", "description": "文件链接的UUID"},
                    "subpath": {"type": "string", "description": "文件路径，如 export/result.csv"},
                    "content": {"type": "string", "description": "要保存的文件内容"},
                },
                "required": ["link_id", "subpath", "content"],
            },
        },
    },
]


@dataclass
class AgentContext:
    db: AsyncSession
    user_id: UUID
    datasource_context: str = ""
    persona: str = ""


class AgentService:
    """Agent服务 - 让LLM可以调用工具执行实际操作"""

    def __init__(self):
        self.tools = TOOLS

    async def _execute_tool(self, name: str, arguments: dict, ctx: AgentContext) -> str:
        logger.info(f"Agent执行工具: {name}")

        if name == "query_table_data":
            return await self._query_table_data(arguments, ctx)
        elif name == "get_table_schema":
            return await self._get_table_schema(arguments, ctx)
        elif name == "list_user_file_links":
            return await self._list_user_file_links(ctx)
        elif name == "list_user_datasources":
            return await self._list_user_datasources(ctx)
        elif name == "save_file_to_link":
            return await self._save_file_to_link(arguments, ctx)
        else:
            return json.dumps({"error": f"未知工具: {name}"})

    async def _query_table_data(self, args: dict, ctx: AgentContext) -> str:
        try:
            import uuid as _uuid
            result = await ctx.db.execute(
                select(DataSource).where(DataSource.id == _uuid.UUID(args["datasource_id"]))
            )
            datasource = result.scalar_one_or_none()
            if not datasource:
                return json.dumps({"error": "数据源不存在"}, ensure_ascii=False)

            limit = args.get("limit", 100)
            connector = get_connector(datasource.type, datasource.connection_config or {})

            filter_column = args.get("filter_column")
            filter_value = args.get("filter_value")
            sort_column = args.get("sort_column")

            if filter_column or sort_column:
                df = await connector.get_table_data(args["table_name"], page=1, page_size=50000)
                if filter_column and filter_value and filter_column in df.columns:
                    if "|" in filter_value:
                        mask = df[filter_column].astype(str).str.contains(filter_value, na=False, regex=True)
                    else:
                        mask = df[filter_column].astype(str).str.contains(filter_value, na=False, regex=False)
                    df = df[mask]
                if sort_column and sort_column in df.columns:
                    df = df.sort_values(by=sort_column, ascending=args.get("sort_order", "asc") == "asc")
                total = len(df)
                if limit and limit > 0:
                    df = df.head(limit)
            else:
                total = 0
                try:
                    stats = await connector.get_table_stats(args["table_name"])
                    total = stats.get("row_count", 0)
                except Exception:
                    pass
                df = await connector.get_table_data(args["table_name"], page=1, page_size=limit or 100)

            await connector.close()

            return json.dumps({
                "total_matched": total or len(df),
                "returned_rows": len(df),
                "columns": list(df.columns),
                "rows": df.fillna("").to_dict(orient="records"),
            }, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"查询数据失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    async def _get_table_schema(self, args: dict, ctx: AgentContext) -> str:
        try:
            import uuid as _uuid
            result = await ctx.db.execute(
                select(DataSource).where(DataSource.id == _uuid.UUID(args["datasource_id"]))
            )
            datasource = result.scalar_one_or_none()
            if not datasource:
                return json.dumps({"error": "数据源不存在"}, ensure_ascii=False)

            connector = get_connector(datasource.type, datasource.connection_config or {})
            df = await connector.get_table_data(args["table_name"], page=1, page_size=5)
            stats = {}
            try:
                stats = await connector.get_table_stats(args["table_name"])
            except Exception:
                pass
            await connector.close()

            return json.dumps({
                "table_name": args["table_name"],
                "row_count": stats.get("row_count", "未知"),
                "columns": [
                    {"name": col, "dtype": str(df[col].dtype), "sample": df[col].dropna().head(3).tolist()}
                    for col in df.columns
                ],
            }, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    async def _list_user_file_links(self, ctx: AgentContext) -> str:
        try:
            result = await ctx.db.execute(
                select(FileLink).where(
                    FileLink.created_by == ctx.user_id,
                    FileLink.is_active == True,
                )
            )
            links = result.scalars().all()
            return json.dumps({
                "file_links": [{"id": str(l.id), "name": l.name, "path": l.path, "link_type": l.link_type} for l in links]
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    async def _list_user_datasources(self, ctx: AgentContext) -> str:
        try:
            result = await ctx.db.execute(
                select(DataSource).where(
                    DataSource.created_by == ctx.user_id,
                    DataSource.is_active == True,
                )
            )
            sources = result.scalars().all()
            data = []
            for ds in sources:
                item = {"id": str(ds.id), "name": ds.name, "type": ds.type}
                try:
                    connector = get_connector(ds.type, ds.connection_config or {})
                    item["tables"] = await connector.get_tables()
                    await connector.close()
                except Exception:
                    item["tables"] = []
                data.append(item)
            return json.dumps({"datasources": data}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @staticmethod
    async def _save_file_to_link(args: dict, ctx: AgentContext) -> str:
        try:
            import uuid as _uuid
            from pathlib import Path

            result = await ctx.db.execute(
                select(FileLink).where(
                    FileLink.id == _uuid.UUID(args["link_id"]),
                    FileLink.created_by == ctx.user_id,
                )
            )
            link = result.scalar_one_or_none()
            if not link:
                return json.dumps({"error": "文件链接不存在或无权访问"}, ensure_ascii=False)
            if link.link_type != "directory":
                return json.dumps({"error": "只能向目录类型的链接写入文件"}, ensure_ascii=False)

            base_path = Path(link.path).resolve()
            full_path = (base_path / args["subpath"]).resolve()
            if not str(full_path).startswith(str(base_path)):
                return json.dumps({"error": "非法路径"}, ensure_ascii=False)

            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(args["content"])

            return json.dumps({"status": "success", "path": str(full_path), "size": full_path.stat().st_size}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    async def run(self, messages: List[Dict[str, str]], ctx: AgentContext) -> str:
        await llm_manager.initialize()
        local_messages = list(messages)

        for i in range(MAX_AGENT_ITERATIONS):
            response = await llm_manager.chat_with_tools(
                messages=local_messages, tools=self.tools, temperature=0.3, max_tokens=3000
            )
            tool_calls = response.get("tool_calls", [])
            if not tool_calls:
                return response.get("content", "")

            local_messages.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            for tc in tool_calls:
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    func_args = {}
                result = await self._execute_tool(tc["function"]["name"], func_args, ctx)
                local_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

        return "处理超时，请简化您的问题后重试。"

    async def run_stream(self, messages: List[Dict[str, str]], ctx: AgentContext) -> AsyncGenerator[str, None]:
        await llm_manager.initialize()
        local_messages = list(messages)

        for i in range(MAX_AGENT_ITERATIONS):
            response = await llm_manager.chat_with_tools(
                messages=local_messages, tools=self.tools, temperature=0.3, max_tokens=3000
            )
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                content = response.get("content", "")
                if content:
                    yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                return

            content = response.get("content") or ""
            if content:
                yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'status', 'content': '正在执行操作...'}, ensure_ascii=False)}\n\n"

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            for tc in tool_calls:
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    func_args = {}
                result = await self._execute_tool(tc["function"]["name"], func_args, ctx)
                local_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

        yield f"data: {json.dumps({'type': 'content', 'content': '处理超时，请简化您的问题后重试。'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"


agent_service = AgentService()