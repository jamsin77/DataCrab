"""DataProcessor 数据处理智能体"""

import json
import asyncio
import uuid as _uuid
from typing import Dict, Any, List, AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.services.multi_agent import BaseAgent, AgentMessage, HandoffReason
from app.services.llm import llm_manager
from app.models.datasource import DataSource
from app.models.filelink import FileLink
from app.models.operator import Operator
from app.models.skill import Skill
from app.services.connectors import get_connector

DATA_PROCESSOR_INSTRUCTIONS = """你是 DataCrab 的数据处理智能体（DataProcessor），一位数据处理专家。

## 核心能力
- 擅长 SQL、pandas、数据清洗和转换
- 能理解用户意图并生成/修改算子和技能
- 能调度执行数据处理流程

## 工作准则
1. **安全红线**：DataCrab 不能修改平台自身，只能处理用户数据
2. **输出默认同源**：处理后的数据默认写回原数据源
3. **修改后必验证**：每次修改数据后必须验证结果
4. **交接检查**：数据处理完成后，应交接给 DataInspector 进行质量检查

## 当收到 DataInspector 的检查结果时
- 应定位问题根源
- 修改处理逻辑修复问题
- 重新执行后再次交接检查

## 交接规则
- 数据处理完成后，使用 handoff_to_inspector 交接给检查智能体
- 当用户请求是数据质量检查相关时，直接交接（delegate）给 DataInspector
"""

DATA_PROCESSOR_TOOLS = [
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
            "name": "list_user_datasources",
            "description": "列出用户已连接的数据源，包括名称、类型、表列表",
            "parameters": {"type": "object", "properties": {}},
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
    {
        "type": "function",
        "function": {
            "name": "handoff_to_inspector",
            "description": "将处理结果交接给数据检查智能体进行质量检查",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源ID"},
                    "table_name": {"type": "string", "description": "检查的表名"},
                    "operation_description": {"type": "string", "description": "本次数据处理的操作描述"},
                    "result_summary": {"type": "string", "description": "处理结果摘要"},
                },
                "required": ["datasource_id", "table_name"],
            },
        },
    },
]

MAX_PROCESSOR_ITERATIONS = 12


class DataProcessorAgent(BaseAgent):
    name = "data_processor"
    display_name = "数据处理智能体"
    description = "理解用户意图、生成/修改算子和技能、调度执行、溯源修复"
    instructions = DATA_PROCESSOR_INSTRUCTIONS
    tools = DATA_PROCESSOR_TOOLS
    capabilities = ["data_processing", "data_query", "operator_generation"]

    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        db: AsyncSession = context.get("db")
        user_id = context.get("user_id")

        if not db or not user_id:
            yield {"type": "done", "result": {"error": "缺少数据库会话或用户ID"}}
            return

        await llm_manager.initialize()

        system_prompt = self.build_system_prompt(context)
        local_messages = [{"role": "system", "content": system_prompt}]

        if message.payload:
            if message.reason == HandoffReason.FIX_REQUIRED:
                issues = message.payload.get("issues", [])
                summary = message.payload.get("summary", "")
                fix_prompt = f"DataInspector 发现以下问题需要修复：\n\n摘要：{summary}\n\n问题列表：\n"
                for i, issue in enumerate(issues, 1):
                    fix_prompt += f"{i}. [{issue.get('severity', 'warning')}] {issue.get('description', '')}"
                    if issue.get("column"):
                        fix_prompt += f" (列: {issue['column']})"
                    if issue.get("suggestion"):
                        fix_prompt += f" → 建议: {issue['suggestion']}"
                    fix_prompt += "\n"
                fix_prompt += "\n请分析问题根源，修复数据，修复完成后使用 handoff_to_inspector 交接再检查。"
                local_messages.append({"role": "user", "content": fix_prompt})
            else:
                user_msg = message.payload.get("user_message", message.payload.get("content", ""))
                if user_msg:
                    local_messages.append({"role": "user", "content": user_msg})
        else:
            yield {"type": "done", "result": {"error": "空消息"}}
            return

        for i in range(MAX_PROCESSOR_ITERATIONS):
            response = await llm_manager.chat_with_tools(
                messages=local_messages, tools=self.tools, temperature=0.3, max_tokens=3000
            )
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                content = response.get("content", "")
                if content:
                    yield {"type": "content", "content": content}
                yield {"type": "done", "result": {"agent": self.name, "content": content}}
                return

            content = response.get("content") or ""
            if content:
                yield {"type": "content", "content": content}

            local_messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })

            results = await self._execute_tool_calls_parallel(tool_calls, db, user_id, context)
            for r in results:
                local_messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]})
                yield {"type": "tool_result", "tool_call_id": r["tool_call_id"], "content": r["content"]}

                try:
                    result_data = json.loads(r["content"])
                    if isinstance(result_data, dict) and result_data.get("_handoff"):
                        yield {
                            "type": "handoff",
                            "to": result_data["to"],
                            "reason": result_data["reason"],
                            "payload": result_data.get("payload", {}),
                            "from": self.name,
                        }
                        return
                except (json.JSONDecodeError, AttributeError):
                    pass

        yield {"type": "content", "content": "处理超时，请简化您的问题后重试。"}
        yield {"type": "done", "result": {"agent": self.name, "content": "处理超时"}}

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        datasource_context = context.get("datasource_context", "")
        persona = context.get("persona", "")
        persona_block = f"{persona}\n\n---\n\n" if persona else ""
        ctx_block = f"\n## 可用数据源\n{datasource_context}\n" if datasource_context else ""
        return f"{persona_block}{self.instructions}{ctx_block}"

    async def _execute_tool_calls_parallel(self, tool_calls: list, db: AsyncSession, user_id, context: Dict) -> list:
        async def _safe_execute(tc):
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}
            result = await self._execute_tool(tc["function"]["name"], func_args, db, user_id, context)
            return {"tool_call_id": tc["id"], "content": result}

        results = await asyncio.gather(*[_safe_execute(tc) for tc in tool_calls])
        return list(results)

    async def _execute_tool(self, name: str, arguments: dict, db: AsyncSession, user_id, context: Dict) -> str:
        logger.info(f"DataProcessor执行工具: {name}")

        if name == "query_table_data":
            return await self._query_table_data(arguments, db, user_id)
        elif name == "get_table_schema":
            return await self._get_table_schema(arguments, db, user_id)
        elif name == "list_user_datasources":
            return await self._list_user_datasources(db, user_id)
        elif name == "list_user_file_links":
            return await self._list_user_file_links(db, user_id)
        elif name == "save_file_to_link":
            return await self._save_file_to_link(arguments, db, user_id)
        elif name == "handoff_to_inspector":
            return json.dumps({
                "_handoff": True,
                "to": "data_inspector",
                "reason": HandoffReason.INSPECT_RESULT.value,
                "payload": {
                    "datasource_id": arguments.get("datasource_id", ""),
                    "table_name": arguments.get("table_name", ""),
                    "operation_description": arguments.get("operation_description", ""),
                    "result_summary": arguments.get("result_summary", ""),
                },
            }, ensure_ascii=False)
        else:
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)

    async def _query_table_data(self, args: dict, db: AsyncSession, user_id) -> str:
        try:
            result = await db.execute(
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

    async def _get_table_schema(self, args: dict, db: AsyncSession, user_id) -> str:
        try:
            result = await db.execute(
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

    async def _list_user_datasources(self, db: AsyncSession, user_id) -> str:
        try:
            result = await db.execute(
                select(DataSource).where(
                    DataSource.created_by == user_id,
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

    async def _list_user_file_links(self, db: AsyncSession, user_id) -> str:
        try:
            result = await db.execute(
                select(FileLink).where(
                    FileLink.created_by == user_id,
                    FileLink.is_active == True,
                )
            )
            links = result.scalars().all()
            return json.dumps({
                "file_links": [{"id": str(l.id), "name": l.name, "path": l.path, "link_type": l.link_type} for l in links]
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @staticmethod
    async def _save_file_to_link(args: dict, db: AsyncSession, user_id) -> str:
        try:
            result = await db.execute(
                select(FileLink).where(
                    FileLink.id == _uuid.UUID(args["link_id"]),
                    FileLink.created_by == user_id,
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
