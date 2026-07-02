"""共享工具定义和实现

提取 agent.py 和 data_processor_agent.py 中完全重复的 5 个公共工具，
统一 schema 定义（含诚实描述）和实现逻辑。

工具结果截断（E）和来源标记（K）在此文件内实现。
"""
import json
import uuid as _uuid
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.models.datasource import DataSource
from app.models.filelink import FileLink
from app.services.connectors import get_connector
from app.services.agent_utils import truncate_tool_result, ToolResultCache


# 按用户隔离的工具结果缓存（会话内只读工具去重）
# 带 LRU 上限，避免多用户场景下无限增长
_user_tool_caches: "OrderedDict[Any, ToolResultCache]" = OrderedDict()
_MAX_USER_CACHES = 100


def _get_tool_cache(user_id) -> ToolResultCache:
    """获取指定用户的工具结果缓存（LRU）"""
    from collections import OrderedDict as _OD
    cache = _user_tool_caches.get(user_id)
    if cache is None:
        cache = ToolResultCache()
        _user_tool_caches[user_id] = cache
        # 超过上限时淘汰最久未用的用户缓存
        while len(_user_tool_caches) > _MAX_USER_CACHES:
            _user_tool_caches.popitem(last=False)
    else:
        _user_tool_caches.move_to_end(user_id)
    return cache


# ==================== 工具 Schema 定义（含诚实描述）====================

SHARED_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_table_data",
            "description": (
                "查询数据源中某个表的数据，支持筛选、排序和分页。"
                "限制：默认最多返回100行；筛选和排序会先加载最多50000行到内存再过滤，"
                "大表可能较慢；不支持跨表JOIN，复杂关联需写算子脚本"
            ),
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
            "description": (
                "获取数据源中某个表的结构信息（列名、数据类型、行数等）。"
                "限制：类型基于5行样本推断，可能有偏差；行数依赖get_table_stats，部分数据源可能不支持"
            ),
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
            "description": "列出用户已连接的数据源，包括名称、类型、表列表。注意：会逐个连接数据源获取表列表，数据源多时较慢",
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
            "description": "在用户已授权的文件链接目录中保存文件（CSV格式）。限制：只能写入CSV格式文本；路径必须在链接目录范围内",
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
            "name": "kb_search",
            "description": (
                "搜索用户上传的文档知识库（PDF/Word/Excel/文本等），返回最相关的文本片段。"
                "适用于从非结构化文档中查找信息。"
                "限制：top_k默认5，必然遗漏大量相关内容，需要全面检索时请多次用不同关键词搜索；"
                "仅支持已上传并解析完成的文档；PDF/DOCX仅提取纯文本，表格结构和图片内容会丢失；"
                "不支持结构化数据源查询（请用 query_table_data）"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或问题"},
                    "top_k": {"type": "integer", "description": "返回结果数量，默认5，最大20"},
                },
                "required": ["query"],
            },
        },
    },
]


# ==================== 工具实现 ====================

async def query_table_data(args: dict, db: AsyncSession, user_id) -> str:
    """查询表数据。结果超 8000 字符自动截断（E），携带来源标记（K）。"""
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

        result_str = json.dumps({
            "total_matched": total or len(df),
            "returned_rows": len(df),
            "columns": list(df.columns),
            "rows": df.fillna("").to_dict(orient="records"),
            "_source": f"datasource:{args['datasource_id']}/table:{args['table_name']}",
        }, ensure_ascii=False, default=str)

        return truncate_tool_result(result_str)
    except Exception as e:
        logger.error(f"查询数据失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def get_table_schema(args: dict, db: AsyncSession, user_id) -> str:
    """获取表结构。"""
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
            "_source": f"datasource:{args['datasource_id']}/table:{args['table_name']}",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def list_user_datasources(db: AsyncSession, user_id) -> str:
    """列出用户数据源。"""
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
                schema = await connector.get_schema()
                item["tables"] = [s.get("table_name", "") for s in schema if s.get("table_name")]
                await connector.close()
            except Exception:
                item["tables"] = []
            data.append(item)
        return json.dumps({"datasources": data}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def list_user_file_links(db: AsyncSession, user_id) -> str:
    """列出用户文件链接。"""
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


async def save_file_to_link(args: dict, db: AsyncSession, user_id) -> str:
    """保存文件到链接目录。"""
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


async def kb_search(args: dict, db: AsyncSession, user_id) -> str:
    """搜索文档知识库。"""
    try:
        from app.services.kb_service import search as kb_search_fn

        query = args.get("query", "").strip()
        if not query:
            return json.dumps({"error": "query 不能为空"}, ensure_ascii=False)

        top_k = min(args.get("top_k", 5), 20)
        results = await kb_search_fn(query, str(user_id), top_k=top_k)

        if not results:
            return json.dumps({
                "results": [],
                "message": "未找到相关文档。可能原因：尚未上传文档、文档仍在解析中、或关键词不匹配。",
            }, ensure_ascii=False)

        formatted = []
        for r in results:
            formatted.append({
                "doc_name": r.get("doc_name", ""),
                "location": r.get("location", ""),
                "content": r.get("content", ""),
                "score": r.get("score"),
                "document_id": r.get("document_id", ""),
            })

        result_str = json.dumps({
            "total": len(formatted),
            "results": formatted,
            "_source": "knowledge_base",
        }, ensure_ascii=False, default=str)

        return truncate_tool_result(result_str)
    except Exception as e:
        logger.error(f"知识库检索失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================== 工具分发 ====================

async def execute_shared_tool(name: str, arguments: dict, db: AsyncSession, user_id) -> str:
    """统一分发共享工具调用（含只读工具 LRU 缓存）。"""
    logger.info(f"执行共享工具: {name}")

    # 只读工具 LRU 缓存：命中则直接返回，避免会话内重复查询
    cache = _get_tool_cache(user_id)
    cached = cache.get(name, arguments)
    if cached is not None:
        logger.info(f"工具缓存命中: {name}")
        return cached

    result = None
    if name == "query_table_data":
        result = await query_table_data(arguments, db, user_id)
    elif name == "get_table_schema":
        result = await get_table_schema(arguments, db, user_id)
    elif name == "list_user_datasources":
        result = await list_user_datasources(db, user_id)
    elif name == "list_user_file_links":
        result = await list_user_file_links(db, user_id)
    elif name == "save_file_to_link":
        result = await save_file_to_link(arguments, db, user_id)
    elif name == "kb_search":
        result = await kb_search(arguments, db, user_id)
    else:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)

    # 写入缓存（只读工具）
    cache.put(name, arguments, result)
    return result
