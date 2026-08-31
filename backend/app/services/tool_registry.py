"""工具注册中心——所有工具的 schema + handler 集中管理。

各 Agent 通过 tool_names 声明自己要用哪些工具（不定义实现），
统一通过 execute_tool() 分发调用。

handler 签名统一：async def handler(args, db, user_id, context) -> str
"""
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_utils import truncate_tool_result, ToolResultCache


# ==================== 注册中心核心 ====================

@dataclass
class ToolDef:
    name: str
    schema: dict
    handler: Callable  # async (args, db, user_id, context) -> str
    cacheable: bool = False  # 只读工具可缓存


_REGISTRY: Dict[str, ToolDef] = {}


def register_tool(name: str, schema: dict, handler: Callable, cacheable: bool = False):
    _REGISTRY[name] = ToolDef(name=name, schema=schema, handler=handler, cacheable=cacheable)


def get_tool_schema(name: str) -> Optional[dict]:
    td = _REGISTRY.get(name)
    return td.schema if td else None


def get_tool_schemas(names: List[str]) -> List[dict]:
    result = []
    for n in names:
        td = _REGISTRY.get(n)
        if td:
            result.append(td.schema)
    return result


def all_tool_names() -> List[str]:
    return list(_REGISTRY.keys())


# ==================== LRU 缓存（只读工具会话内去重）====================

_user_tool_caches: "OrderedDict[Any, ToolResultCache]" = OrderedDict()
_MAX_USER_CACHES = 100


def _get_tool_cache(user_id) -> ToolResultCache:
    cache = _user_tool_caches.get(user_id)
    if cache is None:
        cache = ToolResultCache()
        _user_tool_caches[user_id] = cache
        while len(_user_tool_caches) > _MAX_USER_CACHES:
            _user_tool_caches.popitem(last=False)
    else:
        _user_tool_caches.move_to_end(user_id)
    return cache


# ==================== 统一分发入口 ====================

async def execute_tool(name: str, args: dict, db: AsyncSession, user_id, context: dict = None) -> str:
    """统一工具执行入口（含只读工具 LRU 缓存）。

    Args:
        name: 工具名
        args: 工具参数
        db: 数据库会话
        user_id: 用户 ID
        context: Agent 上下文（调试工具需要 debug_script_content/debug_folder 等）
    """
    td = _REGISTRY.get(name)
    if not td:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)

    logger.info(f"执行工具: {name}")

    # 只读工具 LRU 缓存
    if td.cacheable:
        cache = _get_tool_cache(user_id)
        cached = cache.get(name, args)
        if cached is not None:
            logger.info(f"工具缓存命中: {name}")
            return cached

    try:
        result = await td.handler(args, db, user_id, context or {})
    except Exception as e:
        logger.error(f"工具 {name} 执行异常: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    # 写入缓存（只读工具）— 跳过错误结果
    if td.cacheable:
        try:
            _result_obj = json.loads(result)
            if isinstance(_result_obj, dict) and _result_obj.get("error"):
                return result
        except (json.JSONDecodeError, TypeError):
            pass
        cache = _get_tool_cache(user_id)
        cache.put(name, args, result)

    return result


# ==================== 向后兼容 ====================
# 旧代码通过 execute_shared_tool / SHARED_TOOL_SCHEMAS / ANALYSIS_TOOLS 引用，
# 重构期间保持兼容，逐步迁移

SHARED_TOOL_SCHEMAS: List[Dict[str, Any]] = []


def _ensure_registered():
    """延迟注册（避免循环导入）"""
    if _REGISTRY:
        return
    _register_data_tools()
    _register_debug_tools()
    _register_extension_tools()
    _register_inspector_tools()
    # 同步旧的 SHARED_TOOL_SCHEMAS（向后兼容）
    global SHARED_TOOL_SCHEMAS
    SHARED_TOOL_SCHEMAS = [
        get_tool_schema(n) for n in
        ["query_table_data", "get_table_schema", "list_user_datasources",
         "list_user_file_links", "save_file_to_link", "kb_search",
         "execute_sql", "web_fetch"]
        if get_tool_schema(n)
    ]


# ==================== 数据工具（原 shared_tools.py）====================

def _register_data_tools():
    from app.models.datasource import DataSource
    from app.models.filelink import FileLink
    from app.services.connectors import get_connector
    import uuid as _uuid
    from pathlib import Path
    from sqlalchemy import select

    register_tool("query_table_data", {
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
    }, _query_table_data_handler, cacheable=True)

    register_tool("get_table_schema", {
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
    }, _get_table_schema_handler, cacheable=True)

    register_tool("list_user_datasources", {
        "type": "function",
        "function": {
            "name": "list_user_datasources",
            "description": "列出用户所有可用的数据源（名称、UUID、类型）。调用此工具获取数据源名称与UUID的映射关系，再用其他工具操作具体数据源。调试模式下可用此工具查找用户提到的数据源名称对应的UUID。",
            "parameters": {"type": "object", "properties": {}},
        },
    }, _list_user_datasources_handler, cacheable=True)

    register_tool("list_user_file_links", {
        "type": "function",
        "function": {
            "name": "list_user_file_links",
            "description": "列出用户已挂载的文件链接目录",
            "parameters": {"type": "object", "properties": {}},
        },
    }, _list_user_file_links_handler, cacheable=True)

    register_tool("save_file_to_link", {
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
    }, _save_file_to_link_handler, cacheable=False)

    register_tool("kb_search", {
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
    }, _kb_search_handler, cacheable=True)

    register_tool("execute_sql", {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": (
                "在数据源上执行 SQL 查询（仅 SELECT）。"
                "DB 型（PostgreSQL/MySQL/SQLite）走原生 SQL；文件型（Excel/CSV）用 DuckDB 在内存里跑 SQL。"
                "适用于跨表 JOIN、GROUP BY 聚合、窗口函数等 query_table_data 无法完成的复杂查询。"
                "限制：仅 SELECT；最多返回 1000 行（可调 limit 最大 10000）；"
                "文件型数据源表名规则：Excel 表名=文件名_工作表名（如 销售数据_Q1），CSV 表名=文件名（不带扩展名）；"
                "表名含中文/特殊字符时用双引号包裹：SELECT * FROM \"销售数据_Q1\""
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源的UUID"},
                    "sql": {"type": "string", "description": "SQL 查询语句（仅 SELECT）"},
                    "limit": {"type": "integer", "description": "返回的最大行数，默认1000，最大10000"},
                },
                "required": ["datasource_id", "sql"],
            },
        },
    }, _execute_sql_handler, cacheable=True)

    register_tool("web_fetch", {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "抓取指定 URL 的网页内容，转为纯文本返回。用于读取官方文档、API 参考、模型列表等页面。局限性：部分网站可能拒绝抓取；JavaScript 渲染的页面无法获取动态内容；返回内容可能被截断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要抓取的网页 URL（必须包含 http:// 或 https://）"},
                },
                "required": ["url"],
            },
        },
    }, _web_fetch_handler, cacheable=True)


# ---- 数据工具 handler 实现 ----

async def _query_table_data_handler(args, db, user_id, context):
    try:
        import uuid as _uuid
        from sqlalchemy import select
        from app.models.datasource import DataSource
        from app.services.connectors import get_connector

        ds_id = args.get("datasource_id")
        table_name = args.get("table_name")
        if not ds_id or not table_name:
            return json.dumps({"error": "缺少必需参数 datasource_id 和 table_name"}, ensure_ascii=False)
        result = await db.execute(
            select(DataSource).where(DataSource.id == _uuid.UUID(ds_id))
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
            df = await connector.get_table_data(table_name, page=1, page_size=50000)
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
                stats = await connector.get_table_stats(table_name)
                total = stats.get("row_count", 0)
            except Exception as e:
                logger.warning(f"query_table_data stats 获取失败: {e}")
            df = await connector.get_table_data(table_name, page=1, page_size=limit or 100)

        await connector.close()

        result_str = json.dumps({
            "total_matched": total or len(df),
            "returned_rows": len(df),
            "columns": list(df.columns),
            "rows": df.fillna("").values.tolist(),
            "format": "split",
            "_source": f"datasource:{ds_id}/table:{table_name}",
        }, ensure_ascii=False, default=str)
        return truncate_tool_result(result_str)
    except Exception as e:
        logger.error(f"查询数据失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _get_table_schema_handler(args, db, user_id, context):
    try:
        import uuid as _uuid
        from sqlalchemy import select
        from app.models.datasource import DataSource
        from app.services.connectors import get_connector

        ds_id = args.get("datasource_id")
        table_name = args.get("table_name")
        if not ds_id or not table_name:
            return json.dumps({"error": "缺少必需参数 datasource_id 和 table_name"}, ensure_ascii=False)
        result = await db.execute(
            select(DataSource).where(DataSource.id == _uuid.UUID(ds_id))
        )
        datasource = result.scalar_one_or_none()
        if not datasource:
            return json.dumps({"error": "数据源不存在"}, ensure_ascii=False)

        connector = get_connector(datasource.type, datasource.connection_config or {})
        df = await connector.get_table_data(table_name, page=1, page_size=5)
        stats = {}
        try:
            stats = await connector.get_table_stats(table_name)
        except Exception as e:
            logger.warning(f"get_table_schema stats 获取失败: {e}")
        await connector.close()

        return json.dumps({
            "table_name": table_name,
            "row_count": stats.get("row_count", "未知"),
            "columns": [
                {"name": col, "dtype": str(df[col].dtype), "sample": df[col].dropna().head(3).tolist()}
                for col in df.columns
            ],
            "_source": f"datasource:{ds_id}/table:{table_name}",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _list_user_datasources_handler(args, db, user_id, context):
    try:
        from sqlalchemy import select
        from app.models.datasource import DataSource
        result = await db.execute(
            select(DataSource).where(
                DataSource.created_by == user_id,
                DataSource.is_active == True,
            )
        )
        sources = result.scalars().all()
        return json.dumps({
            "datasources": [
                {"name": s.name, "id": str(s.id), "type": s.type}
                for s in sources
            ]
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _list_user_file_links_handler(args, db, user_id, context):
    try:
        from sqlalchemy import select
        from app.models.filelink import FileLink
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


async def _save_file_to_link_handler(args, db, user_id, context):
    try:
        import uuid as _uuid
        from pathlib import Path
        from sqlalchemy import select
        from app.models.filelink import FileLink
        link_id = args.get("link_id")
        subpath = args.get("subpath")
        content = args.get("content")
        if not link_id or not subpath or content is None:
            return json.dumps({"error": "缺少必需参数 link_id/subpath/content"}, ensure_ascii=False)
        result = await db.execute(
            select(FileLink).where(
                FileLink.id == _uuid.UUID(link_id),
                FileLink.created_by == user_id,
            )
        )
        link = result.scalar_one_or_none()
        if not link:
            return json.dumps({"error": "文件链接不存在或无权访问"}, ensure_ascii=False)
        if link.link_type != "directory":
            return json.dumps({"error": "只能向目录类型的链接写入文件"}, ensure_ascii=False)

        base_path = Path(link.path).resolve()
        full_path = (base_path / subpath).resolve()
        if not str(full_path).startswith(str(base_path)):
            return json.dumps({"error": "非法路径"}, ensure_ascii=False)

        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        return json.dumps({"status": "success", "path": str(full_path), "size": full_path.stat().st_size}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _kb_search_handler(args, db, user_id, context):
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


async def _execute_sql_handler(args, db, user_id, context):
    try:
        import uuid as _uuid
        from sqlalchemy import select
        from app.models.datasource import DataSource
        from app.services.connectors import get_connector
        ds_id = args.get("datasource_id")
        if not ds_id:
            return json.dumps({"error": "缺少必需参数 datasource_id"}, ensure_ascii=False)
        result = await db.execute(
            select(DataSource).where(DataSource.id == _uuid.UUID(ds_id))
        )
        datasource = result.scalar_one_or_none()
        if not datasource:
            return json.dumps({"error": "数据源不存在"}, ensure_ascii=False)

        sql = args.get("sql", "").strip()
        if not sql:
            return json.dumps({"error": "sql 不能为空"}, ensure_ascii=False)
        sql_upper = sql.lstrip("(").lstrip().upper()
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
            return json.dumps({"error": "仅支持 SELECT 或 WITH 语句（只读查询）"}, ensure_ascii=False)

        limit = min(args.get("limit", 1000), 10000)
        connector = get_connector(datasource.type, datasource.connection_config or {})
        try:
            await connector.connect()
            df = await connector.execute_query(sql)
        finally:
            await connector.close()

        if df is None or df.empty:
            return json.dumps({"columns": list(df.columns) if df is not None else [], "rows": [], "row_count": 0, "_source": "sql"}, ensure_ascii=False)
        if len(df) > limit:
            df = df.head(limit)
        columns = list(df.columns)
        rows = df.fillna("").values.tolist()
        result_str = json.dumps({
            "columns": columns,
            "rows": rows,
            "format": "split",
            "row_count": len(rows),
            "truncated": len(df) >= limit,
            "_source": "sql",
        }, ensure_ascii=False, default=str)
        return truncate_tool_result(result_str)
    except Exception as e:
        logger.error(f"SQL 执行失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _web_fetch_handler(args, db, user_id, context):
    import re
    import httpx
    url = args.get("url", "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return json.dumps({"error": "缺少 url 或协议无效（需 http:// 或 https://）"}, ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return json.dumps({"error": f"HTTP {resp.status_code}"}, ensure_ascii=False)
            html = resp.text
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return json.dumps({"error": "页面无文本内容（可能是 JavaScript 渲染页面）"}, ensure_ascii=False)
        return truncate_tool_result(json.dumps({"url": url, "content": text}, ensure_ascii=False))
    except httpx.TimeoutException:
        return json.dumps({"error": "请求超时（30秒）"}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"web_fetch 失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================== 调试工具（原 data_processor_agent.py）====================

def _register_debug_tools():
    register_tool("run_script", {
        "type": "function",
        "function": {
            "name": "run_script",
            "description": "运行当前调试的技能/脚本（在沙箱中执行），返回执行结果。\n\n用法：\n- parameters 是业务参数（数据源名、表名、策略等），须符合 SKILL.md 参数规范\n- 必选参数不可缺失，系统会校验并告警\n- 返回执行结果：成功返回 stdout + result，失败返回错误信息 + traceback\n- 成功时 stdout 过长会截断（如打印大量数据行）；失败时错误信息和 traceback 完整保留\n- 脚本执行超时（300秒）不是 bug——说明运行时间过长，修复方向是减少 LLM 调用量（加规则预过滤/增大批次/并发），不是找逻辑 bug\n- edit_script 修改后调 run_script 验证修复是否正确\n\n场景：\n- 修改后验证：edit_script 改完 → run_script 跑一遍看结果\n- 复现问题：用原始参数 run_script 看错误是否还在",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                    "parameters": {"type": "object", "description": "执行参数（业务参数，如数据源名、表名、策略等），须符合 SKILL.md 参数规范"},
                },
                "required": [],
            },
        },
    }, _run_script_handler, cacheable=False)

    register_tool("edit_script", {
        "type": "function",
        "function": {
            "name": "edit_script",
            "description": "精确字符串替换，修改脚本。提供 old_string 和 new_string，系统精确定位并替换。\n\n用法：\n- 修改前必须先调 read_script 查看逐字内容，获取精确的 old_string\n- old_string 必须逐字匹配（包括缩进、空格、注释），不能凭记忆编写\n- old_string 在脚本中必须唯一；不唯一时多带几行上下文使其唯一\n- old_string 未找到或多次匹配时会报错——多带上下文行使其唯一\n- 保持 new_string 的缩进与周围代码一致",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_name": {"type": "string", "description": "脚本文件名，如 main.py"},
                    "old_string": {"type": "string", "description": "脚本中要被替换的原文片段（逐字复制，必须唯一匹配）。多带几行上下文以保证唯一。"},
                    "new_string": {"type": "string", "description": "替换后的新内容（保持正确缩进）"},
                    "skill_md": {"type": "string", "description": "（仅技能调试）更新后的完整 SKILL.md 全文。需要改参数规范/描述时提供。"},
                },
                "required": ["old_string", "new_string"],
            },
        },
    }, _edit_script_handler, cacheable=False)

    register_tool("read_script", {
        "type": "function",
        "function": {
            "name": "read_script",
            "description": "读取代码的逐字内容（带行号）。\n\n用法：\n- 默认返回前 2000 行，大文件用 offset 翻页读取后续内容\n- 避免反复读小片段（70 行以下），需要更多上下文时读更大的窗口\n- 内容格式为 \"L行号: 代码\"，行号可用于 edit_script 的定位\n- function_name 可只读指定函数（如 function_name=\"_write_result\"）\n- 行级补丁前调用获取精确 old_string（逐字复制，不要凭记忆）\n- 可同时读取多个文件/函数，并行调用\n- 先读脚本本身（scope=script）定位 bug，确认脚本逻辑无误后再查平台源码（scope=platform）",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["script", "platform"], "description": "script=用户脚本（默认），platform=平台源码"},
                    "script_name": {"type": "string", "description": "脚本文件名（仅 scope=script）"},
                    "function_name": {"type": "string", "description": "可选，仅 scope=script 时读取指定函数"},
                    "file_path": {"type": "string", "description": "平台源码文件名（仅 scope=platform，如 connectors.py）"},
                    "offset": {"type": "integer", "description": "起始行号（1-indexed）"},
                    "limit": {"type": "integer", "description": "读取行数（不传时默认返回前 2000 行）"},
                },
                "required": [],
            },
        },
    }, _read_script_handler, cacheable=False)

    register_tool("grep_script", {
        "type": "function",
        "function": {
            "name": "grep_script",
            "description": "在代码中搜索关键词或正则表达式，返回匹配行+行号+上下文。\n\n用法：\n- pattern 是正则表达式（默认大小写不敏感），如 \"write_table_data\" 或 \"batch.*append\"\n- 返回每个匹配的行号和内容，附带上下文行（默认 3 行）\n- 搜平台源码时用 file_filter 限定文件（如 \"connectors.py\"）",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "正则表达式（默认大小写不敏感）"},
                    "scope": {"type": "string", "enum": ["script", "platform"], "description": "script=搜用户脚本（默认），platform=搜平台源码"},
                    "script_name": {"type": "string", "description": "脚本文件名（仅 scope=script）"},
                    "function_name": {"type": "string", "description": "可选，仅 scope=script 时限定函数范围"},
                    "file_filter": {"type": "string", "description": "可选，仅 scope=platform 时限定文件名（如 connectors.py）"},
                    "context_lines": {"type": "integer", "description": "上下文行数（默认 3）"},
                    "case_sensitive": {"type": "boolean", "description": "是否大小写敏感（默认 false）"},
                },
                "required": ["pattern"],
            },
        },
    }, _grep_script_handler, cacheable=False)


# ---- 调试工具 handler 实现 ----
# 调试工具 handler 需要 context（debug_script_content/debug_folder/debug_type 等），
# 这些 handler 从 data_processor_agent._execute_tool 中原样搬迁

async def _run_script_handler(args, db, user_id, context):
    """运行脚本（技能/算子/流程三种模式）。"""
    script_name = args.get("script_name") or context.get("debug_script_name", "main.py")
    parameters = args.get("parameters", {})
    for key in ["datasource_id", "source_datasource_id", "target_datasource_id"]:
        parameters.pop(key, None)
    try:
        if context.get("debug_type") == "operator":
            import io, time as _time, inspect as _inspect
            from app.api.v1.endpoints.operator import _build_operator_namespace, _sanitize_op
            script = context.get("debug_script_content", "")
            func_name = context.get("debug_function_name", "")
            captured = io.StringIO()
            exec_ns = {"__builtins__": __builtins__, "print": lambda *a, **kw: print(*a, file=captured, **kw)}
            exec_ns.update(_build_operator_namespace(user_id))
            exec(script, exec_ns)
            debug_func = exec_ns.get(func_name)
            if not debug_func:
                return json.dumps({"success": False, "error": f"脚本中未找到函数: {func_name}"})
            exec_start = _time.time()
            is_async = _inspect.iscoroutinefunction(debug_func)
            exec_result = await debug_func(**parameters) if is_async else debug_func(**parameters)
            if hasattr(exec_result, "to_dict"):
                exec_result = exec_result.to_dict(orient="records")
            elapsed = (_time.time() - exec_start) * 1000
            result = {"success": True, "result": _sanitize_op(exec_result), "stdout": captured.getvalue() or None, "execution_time_ms": round(elapsed, 2)}
            context["debug_last_success_params"] = parameters
            logger.info(f"debug run_script (operator): success=True")
            return json.dumps(result, ensure_ascii=False, default=str)
        elif context.get("debug_type") == "pipeline":
            from app.services.skill_runner import run_skill_script_by_content_async
            result = await run_skill_script_by_content_async(
                script_content=context.get("debug_script_content", ""),
                parameters=parameters,
                user_id=str(user_id) if user_id else None,
                entry_function=context.get("debug_function_name"),
                timeout=600,
            )
            _inner = result.get("result") if isinstance(result.get("result"), dict) else {}
            _failed = (not result.get("success")
                       or ("success" in _inner and not _inner["success"])
                       or (result.get("error") and str(result.get("error")).strip())
                       or (_inner.get("error") and str(_inner.get("error")).strip()))
            if not _failed:
                context["debug_last_success_params"] = parameters
            else:
                _err = str(result.get("error") or _inner.get("error") or "")
                logger.info(f"debug run_script (pipeline): success=False, error={_err[:500]}")
            logger.info(f"debug run_script (pipeline): success={not _failed}")
            return json.dumps(result, ensure_ascii=False, default=str)
        else:
            folder = context.get("debug_folder")
            if not folder:
                return json.dumps({"success": False, "error": "缺少 folder"})
            from app.services.skill_runner import run_skill_script_streaming_async
            ds_id = context.get("debug_source_datasource_id") or context.get("debug_datasource_id")
            ds_name = context.get("debug_source_datasource_name") or context.get("debug_datasource_name")
            tbl = context.get("debug_source_table_name") or context.get("debug_table_name")
            result = None
            _progress_queue = context.get("_progress_queue")
            async for _item in run_skill_script_streaming_async(
                skill_path=folder, script_name=script_name, parameters=parameters,
                input_data=None, datasource_id=ds_id, datasource_name=ds_name, table_name=tbl,
                user_id=str(user_id) if user_id else None,
            ):
                _it = _item.get("type")
                if _it == "progress":
                    _msg = _item.get("message", "")
                    _prog_list = context.setdefault("_execution_progress", [])
                    _prog_list.append(_msg)
                    if _progress_queue is not None:
                        _progress_queue.put_nowait(_msg)
                elif _it == "result":
                    result = _item["result"]
            if result is None:
                result = {"success": False, "error": "执行无结果返回"}
            _inner = result.get("result") if isinstance(result.get("result"), dict) else {}
            _failed = (not result.get("success")
                       or ("success" in _inner and not _inner["success"])
                       or (result.get("error") and str(result.get("error")).strip())
                       or (_inner.get("error") and str(_inner.get("error")).strip()))
            if not _failed:
                context["debug_last_success_params"] = parameters
            else:
                _err = str(result.get("error") or _inner.get("error") or "")
                _err_type = result.get("error_type") or _inner.get("error_type") or ""
                logger.info(f"debug run_script (skill): success=False, error_type={_err_type}, error={repr(_err[:800])}")
            return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        import traceback as _tb
        _err = _tb.format_exc()
        logger.warning(f"run_script 失败: {_err[:500]}")
        return json.dumps({"success": False, "error": _err, "error_type": type(e).__name__}, ensure_ascii=False)


async def _edit_script_handler(args, db, user_id, context):
    """行级补丁修改脚本。"""
    if not context.get("_script_has_been_read"):
        return json.dumps({"success": False, "error": "必须先调用 read_script 查看脚本内容，再修改。"}, ensure_ascii=False)
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    if not old_string:
        return json.dumps({"success": False, "error": "缺少 old_string"}, ensure_ascii=False)
    script_name = args.get("script_name") or context.get("debug_script_name", "main.py")
    try:
        from app.services.operator_parser import apply_patch
        current = context.get("debug_script_content", "")
        patch = apply_patch(current, old_string, new_string)
        if not patch.get("success"):
            return json.dumps({"success": False, "error": patch.get("message", "补丁失败"), "patch_error": True}, ensure_ascii=False)
        return await _finalize_script_change(patch["code"], current, script_name, args, db, context)
    except Exception as e:
        logger.warning(f"edit_script 失败: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


async def _finalize_script_change(new_code, old_code, script_name, args, db, context):
    """写入磁盘 + 语法检查 + diff（从 data_processor_agent._finalize_script_change 原样搬迁）。"""
    import os
    from pathlib import Path
    _skill_md_updated = False
    _skill_md = args.get("skill_md", "")
    if _skill_md:
        _folder = context.get("debug_folder")
        if _folder:
            _md_path = Path(_folder) / "SKILL.md"
            _md_path.write_text(_skill_md, encoding="utf-8")
            _skill_md_updated = True

    _folder = context.get("debug_folder")
    if _folder:
        _script_dir = Path(_folder) / "scripts"
        _script_dir.mkdir(parents=True, exist_ok=True)
        _file_path = _script_dir / script_name
        _file_path.write_text(new_code, encoding="utf-8")

    context["debug_script_content"] = new_code
    context["_script_has_been_read"] = False

    diff_lines = _compute_diff_summary(old_code, new_code)
    return json.dumps({
        "success": True,
        "script_name": script_name,
        "message": "脚本已更新，语法检查通过",
        "skill_md_updated": _skill_md_updated,
        "changed_lines": diff_lines,
    }, ensure_ascii=False)


def _compute_diff_summary(old_code, new_code):
    import difflib
    old_lines = old_code.splitlines()
    new_lines = new_code.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=0))
    changed = []
    for line in diff:
        if line.startswith('@@') or line.startswith('---') or line.startswith('+++'):
            continue
        if line.startswith('+') or line.startswith('-'):
            changed.append(line[:200])
    return changed[:30]


async def _read_script_handler(args, db, user_id, context):
    """读取脚本（带行号）。"""
    import os
    from pathlib import Path
    scope = args.get("scope", "script")
    if scope == "platform":
        file_path = args.get("file_path", "")
        if not file_path:
            return json.dumps({"success": False, "error": "缺少 file_path"}, ensure_ascii=False)
        search_dir = Path(__file__).resolve().parent.parent
        candidates = [
            search_dir / file_path,
            search_dir / "services" / file_path,
            search_dir / "api" / "v1" / "endpoints" / file_path,
        ]
        resolved = None
        for c in candidates:
            try:
                rp = c.resolve()
                if str(rp).startswith(str(search_dir.resolve())) and rp.exists():
                    resolved = rp
                    break
            except Exception:
                continue
        if not resolved:
            return json.dumps({"success": False, "error": f"文件未找到: {file_path}"}, ensure_ascii=False)
        offset = max(1, int(args.get("offset", 1)))
        limit = min(200, int(args.get("limit", 50)))
        try:
            with open(resolved, encoding="utf-8") as f:
                all_lines = f.readlines()
            start = offset - 1
            end = min(len(all_lines), start + limit)
            seg_lines = [f"L{i+1}: {all_lines[i].rstrip()}" for i in range(start, end)]
            return json.dumps({"success": True, "file": os.path.relpath(str(resolved), str(search_dir)),
                               "offset": offset, "limit": limit, "total_lines": len(all_lines),
                               "content": "\n".join(seg_lines)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    script_name = args.get("script_name") or context.get("debug_script_name", "main.py")
    _folder = context.get("debug_folder")
    if _folder:
        _file_path = Path(_folder) / "scripts" / script_name
        if _file_path.exists():
            current = _file_path.read_text(encoding="utf-8")
            context["debug_script_content"] = current
        else:
            current = context.get("debug_script_content", "")
    else:
        current = context.get("debug_script_content", "")
    function_name = args.get("function_name")
    offset = int(args.get("offset", 0))
    limit = int(args.get("limit", 0))
    context["_script_has_been_read"] = True

    if function_name:
        try:
            import ast as _ast
            tree = _ast.parse(current)
            for node in _ast.iter_child_nodes(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == function_name:
                    seg = _ast.get_source_segment(current, node) or ""
                    seg_lines = seg.splitlines()
                    start_line = node.lineno
                    total = len(seg_lines)
                    if offset > 0 or limit > 0:
                        s = max(0, (offset - 1) if offset > 0 else 0)
                        e = min(total, s + limit) if limit > 0 else total
                    else:
                        s = 0
                        e = total
                    numbered = "\n".join(f"L{start_line + i}: {seg_lines[i]}" for i in range(s, e))
                    return json.dumps({"success": True, "script_name": script_name, "function": function_name,
                                       "start_line": start_line, "content": numbered, "total_lines": total,
                                       "shown_lines": e - s}, ensure_ascii=False)
            return json.dumps({"success": False, "error": f"未找到函数 {function_name}"}, ensure_ascii=False)
        except SyntaxError as _se:
            return json.dumps({"success": False, "error": f"脚本语法错误，无法解析函数：{_se.msg}（第{_se.lineno}行）。用 edit_script 修复语法。"}, ensure_ascii=False)
    _DEFAULT_READ_CAP = 2000
    all_lines = current.splitlines()
    _total = len(all_lines)
    if offset > 0 or limit > 0:
        start = max(0, (offset - 1) if offset > 0 else 0)
        end = min(_total, start + limit) if limit > 0 else min(_total, start + _DEFAULT_READ_CAP)
    else:
        start = 0
        end = min(_total, _DEFAULT_READ_CAP)
    numbered = "\n".join(f"L{i+1}: {all_lines[i]}" for i in range(start, end))
    result = {"success": True, "script_name": script_name, "offset": start + 1,
              "limit": end - start, "total_lines": _total, "content": numbered}
    if end < _total:
        result["has_more"] = True
        result["hint"] = f"还有 {_total - end} 行未显示，用 offset={end + 1} 翻页读取后续内容"
    return json.dumps(result, ensure_ascii=False)


async def _grep_script_handler(args, db, user_id, context):
    """搜索脚本（正则+行号+上下文）。"""
    from pathlib import Path
    import re as _grep_re
    scope = args.get("scope", "script")
    pattern = args.get("pattern", "")
    if not pattern:
        return json.dumps({"success": False, "error": "缺少 pattern"}, ensure_ascii=False)
    context_lines = int(args.get("context_lines", 3))

    if scope == "platform":
        file_filter = args.get("file_filter", "*.py")
        import glob as _glob
        search_dir = Path(__file__).resolve().parent.parent
        files = _glob.glob(str(search_dir / "**" / file_filter), recursive=True)
        flags = 0 if args.get("case_sensitive") else _grep_re.IGNORECASE
        try:
            regex = _grep_re.compile(pattern, flags)
        except _grep_re.error as e:
            return json.dumps({"success": False, "error": f"正则表达式错误: {e}"}, ensure_ascii=False)
        all_matches = []
        for fpath in sorted(files):
            try:
                with open(fpath, encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception:
                continue
            for i, line in enumerate(lines):
                if regex.search(line):
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    snippet_lines = []
                    for j in range(start, end):
                        prefix = ">>" if j == i else "  "
                        snippet_lines.append(f"{prefix} L{j+1}: {lines[j].rstrip()}")
                    all_matches.append({"file": str(Path(fpath).relative_to(search_dir)), "line": i + 1,
                                        "snippet": "\n".join(snippet_lines)})
        if not all_matches:
            return json.dumps({"success": True, "pattern": pattern, "scope": "platform",
                               "matches": [], "total_matches": 0, "message": "未找到匹配"}, ensure_ascii=False)
        _MAX = 50
        truncated = len(all_matches) > _MAX
        result = {"success": True, "pattern": pattern, "scope": "platform",
                  "matches": all_matches[:_MAX], "total_matches": len(all_matches)}
        if truncated:
            result["truncated"] = True
            result["message"] = f"匹配数超过 {_MAX}，仅显示前 {_MAX} 个。请用 file_filter 限定文件或用更精确的 pattern。"
        return json.dumps(result, ensure_ascii=False)

    script_name = args.get("script_name") or context.get("debug_script_name", "main.py")
    current = context.get("debug_script_content", "")
    case_sensitive = args.get("case_sensitive", False)
    function_name = args.get("function_name")
    all_lines = current.splitlines()
    if function_name:
        try:
            import ast as _ast
            tree = _ast.parse(current)
            func_start = None
            func_end = None
            for node in _ast.iter_child_nodes(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == function_name:
                    func_start = node.lineno
                    func_end = getattr(node, "end_lineno", func_start)
                    break
            if func_start is None:
                return json.dumps({"success": False, "error": f"未找到函数 {function_name}"}, ensure_ascii=False)
            search_lines = all_lines[func_start - 1: func_end]
            line_offset = func_start
        except SyntaxError as _se:
            return json.dumps({"success": False, "error": f"脚本语法错误，无法解析函数：{_se.msg}（第{_se.lineno}行）。用 edit_script 修复语法。"}, ensure_ascii=False)
    else:
        search_lines = all_lines
        line_offset = 1
    flags = 0 if case_sensitive else _grep_re.IGNORECASE
    try:
        regex = _grep_re.compile(pattern, flags)
    except _grep_re.error as e:
        return json.dumps({"success": False, "error": f"正则表达式错误: {e}"}, ensure_ascii=False)
    match_indices = [i for i, line in enumerate(search_lines) if regex.search(line)]
    if not match_indices:
        return json.dumps({"success": True, "pattern": pattern, "script_name": script_name,
                           "function": function_name, "matches": [], "total_matches": 0,
                           "message": "未找到匹配"}, ensure_ascii=False)
    _MAX_MATCHES = 20
    truncated = len(match_indices) > _MAX_MATCHES
    match_blocks = []
    for idx in match_indices[:_MAX_MATCHES]:
        start = max(0, idx - context_lines)
        end = min(len(search_lines), idx + context_lines + 1)
        snippet_lines = []
        for j in range(start, end):
            prefix = ">>" if j == idx else "  "
            snippet_lines.append(f"{prefix} L{line_offset + j}: {search_lines[j]}")
        match_blocks.append({"line": line_offset + idx, "snippet": "\n".join(snippet_lines)})
    result = {"success": True, "pattern": pattern, "script_name": script_name,
              "function": function_name, "matches": match_blocks, "total_matches": len(match_indices)}
    if truncated:
        result["truncated"] = True
        result["message"] = f"匹配数超过 {_MAX_MATCHES}，仅显示前 {_MAX_MATCHES} 个。请用更精确的 pattern 或指定 function_name 缩小范围。"
    return json.dumps(result, ensure_ascii=False)


# ==================== 扩展工具（配置管理，原 data_processor_agent._handle_*）====================

def _register_extension_tools():
    register_tool("save_connector", {
        "type": "function",
        "function": {
            "name": "save_connector",
            "description": "保存数据源连接器（新建或更新）。用户提供自然语言描述，你生成继承 BaseConnector 的 Python 类代码，系统验证后注册。注册后用户即可在数据源管理中创建该类型的数据源。同名或同显示名称的连接器会被覆盖更新，不会产生重复。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "连接器类型名（英文小写，如 mongodb、redis）。更新已有连接器时尽量沿用原 name"},
                    "display_name": {"type": "string", "description": "显示名称（如 MongoDB）"},
                    "description": {"type": "string", "description": "连接器描述"},
                    "code": {"type": "string", "description": "BaseConnector 子类的 Python 代码。必须实现 async connect/test_connection/get_schema/get_table_data(page,page_size)/get_table_stats/close"},
                    "config_template": {"type": "array", "description": "配置项模板，前端据此动态渲染表单。每项 {name,label,type,required,default?,options?,depends_on?}。type 支持：string(文本)、number(数字)、password(密码)、boolean(开关)、select(下拉选择，需配 options:[{label,value}])、filepath(文件路径选择器，带浏览按钮)、folderpath(文件夹路径选择器)、filepath_list(多文件路径列表，可增删)。文件类连接器务必用 filepath/folderpath/filepath_list 而非 string，这样前端会显示文件浏览按钮。depends_on 可选，条件显隐，如 {\"mode\":\"files\"}", "items": {"type": "object", "properties": {"name": {"type": "string"}, "label": {"type": "string"}, "type": {"type": "string"}, "required": {"type": "boolean"}}}},
                },
                "required": ["name", "display_name", "code"],
            },
        },
    }, _save_connector_handler, cacheable=False)

    register_tool("delete_connector", {
        "type": "function",
        "function": {
            "name": "delete_connector",
            "description": "删除指定的数据源连接器。用户要求删除、移除某个连接器时调用此工具。已被数据源使用的连接器无法删除。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "要删除的连接器类型名（如 universal_file、generic_file）"},
                },
                "required": ["name"],
            },
        },
    }, _delete_connector_handler, cacheable=False)

    register_tool("save_llm_adapter", {
        "type": "function",
        "function": {
            "name": "save_llm_adapter",
            "description": "注册或更新大模型 Provider。已存在的 Provider 会被刷新更新。注册后可在模型配置中选择该 Provider。所有 Provider 地位平等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_name": {"type": "string", "description": "厂商标识（英文小写，如 anthropic、google、moonshot）"},
                    "display_name": {"type": "string", "description": "显示名称（如 Anthropic Claude）"},
                    "description": {"type": "string", "description": "Provider 描述"},
                    "api_base": {"type": "string", "description": "API 基础地址（如 https://api.moonshot.cn/v1）"},
                    "models": {"type": "array", "description": "可用模型列表", "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}}}},
                    "default_model": {"type": "string", "description": "默认深度模型名（用于深度推理场景，如 glm-5.2、moonshot-v1-128k）"},
                    "code": {"type": "string", "description": "适配器类代码（OpenAI 兼容厂商可不传，非兼容厂商必须传）。类必须实现 chat_completion(messages, model, temperature, max_tokens, stream) 方法"},
                },
                "required": ["provider_name", "display_name", "api_base"],
            },
        },
    }, _save_llm_adapter_handler, cacheable=False)

    register_tool("get_llm_config", {
        "type": "function",
        "function": {
            "name": "get_llm_config",
            "description": "查询当前平台的 LLM 配置信息，包括当前使用的 Provider、模型、API地址、所有已注册的 Provider 列表。用户要求添加或更新模型时，先调用此工具了解现有配置。",
            "parameters": {"type": "object", "properties": {}},
        },
    }, _get_llm_config_handler, cacheable=False)

    register_tool("delete_llm_adapter", {
        "type": "function",
        "function": {
            "name": "delete_llm_adapter",
            "description": "删除指定的 LLM Provider。用户要求删除、移除某个 Provider 时调用此工具。删除后该 Provider 不可用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_name": {"type": "string", "description": "要删除的 Provider 标识（如 moonshot、deepseek）"},
                },
                "required": ["provider_name"],
            },
        },
    }, _delete_llm_adapter_handler, cacheable=False)


# ---- 扩展工具 handler 实现 ----

async def _save_connector_handler(args, db, user_id, context):
    import json as _json
    connector_name = args.get("name", "").strip().lower()
    display_name = args.get("display_name", connector_name)
    description = args.get("description", "")
    code = args.get("code", "")
    config_template = args.get("config_template", [])

    if not connector_name or not code:
        return _json.dumps({"success": False, "error": "缺少 name 或 code"}, ensure_ascii=False)

    from app.services.connectors import register_custom_connector
    try:
        register_custom_connector(connector_name, code)
    except Exception as e:
        return _json.dumps({"success": False, "error": f"代码验证失败: {e}"}, ensure_ascii=False)

    from app.core.database import async_session
    from app.models.custom_extension import CustomConnector
    from sqlalchemy import select as sa_select, or_
    async with async_session() as save_session:
        existing = await save_session.execute(
            sa_select(CustomConnector).where(
                or_(CustomConnector.name == connector_name, CustomConnector.display_name == display_name),
                CustomConnector.is_active == True,
            )
        )
        record = existing.scalars().first()
        if record:
            record.display_name = display_name
            record.description = description
            record.code = code
            record.config_template = config_template
            record.is_active = True
            dup_result = await save_session.execute(
                sa_select(CustomConnector).where(
                    CustomConnector.display_name == display_name,
                    CustomConnector.is_active == True,
                    CustomConnector.id != record.id,
                )
            )
            for dup in dup_result.scalars().all():
                dup.is_active = False
        else:
            record = CustomConnector(
                name=connector_name,
                display_name=display_name,
                description=description,
                code=code,
                config_template=config_template,
                created_by=user_id,
            )
            save_session.add(record)
        await save_session.commit()
        logger.info(f"连接器已保存: {record.name} (display={display_name})")
        return _json.dumps({"success": True, "message": f"连接器 '{display_name}' 已注册，现在可以在数据源管理中创建该类型的数据源"}, ensure_ascii=False)


async def _delete_connector_handler(args, db, user_id, context):
    import json as _json
    connector_name = args.get("name", "").strip().lower()
    if not connector_name:
        return _json.dumps({"success": False, "error": "缺少 name"}, ensure_ascii=False)

    from app.core.database import async_session
    from app.models.custom_extension import CustomConnector
    from app.models.datasource import DataSource
    from app.models.user import User
    from sqlalchemy import select as sa_select, func
    async with async_session() as del_session:
        result = await del_session.execute(
            sa_select(CustomConnector).where(CustomConnector.name == connector_name, CustomConnector.is_active == True)
        )
        record = result.scalar_one_or_none()
        if not record:
            return _json.dumps({"success": False, "error": f"连接器 '{connector_name}' 不存在"}, ensure_ascii=False)

        user_result = await del_session.execute(sa_select(User).where(User.id == user_id))
        cur_user = user_result.scalar_one_or_none()
        is_super = bool(cur_user and cur_user.is_superuser)
        if record.created_by != user_id and not is_super:
            return _json.dumps({"success": False, "error": "无权删除此连接器（仅所有者或管理员可删）"}, ensure_ascii=False)

        ds_count = await del_session.scalar(
            sa_select(func.count(DataSource.id)).where(
                DataSource.type == connector_name,
                DataSource.is_active == True,
            )
        )
        if ds_count and ds_count > 0:
            return _json.dumps({"success": False, "error": f"该连接器已被 {ds_count} 个数据源使用，无法删除。请先删除或迁移相关数据源"}, ensure_ascii=False)

        display_name = record.display_name or connector_name
        record.is_active = False
        await del_session.commit()

    from app.services.connectors import _connector_registry, _sync_supported_types
    _connector_registry.pop(connector_name, None)
    _sync_supported_types()
    logger.info(f"连接器已删除: {connector_name}")
    return _json.dumps({"success": True, "message": f"连接器 '{display_name}' ({connector_name}) 已删除"}, ensure_ascii=False)


async def _save_llm_adapter_handler(args, db, user_id, context):
    import json as _json
    provider_name = args.get("provider_name", "").strip().lower()
    display_name = args.get("display_name", provider_name)
    description = args.get("description", "")
    api_base = args.get("api_base", "")
    models = args.get("models", [])
    default_model = args.get("default_model", "")
    code = args.get("code", "")

    if not provider_name or not api_base:
        return _json.dumps({"success": False, "error": "缺少 provider_name 或 api_base"}, ensure_ascii=False)

    if code:
        from app.services.llm import register_custom_adapter
        try:
            register_custom_adapter(provider_name, code)
        except Exception as e:
            return _json.dumps({"success": False, "error": f"适配器代码验证失败: {e}"}, ensure_ascii=False)

    from app.core.database import async_session
    from app.models.custom_extension import LLMProvider
    from sqlalchemy import select as sa_select
    async with async_session() as save_session:
        existing = await save_session.execute(sa_select(LLMProvider).where(LLMProvider.provider_name == provider_name))
        record = existing.scalar_one_or_none()
        if record:
            record.display_name = display_name
            record.description = description
            record.api_base = api_base
            record.models = models
            record.default_model = default_model
            if code:
                record.code = code
            record.is_active = True
        else:
            record = LLMProvider(
                provider_name=provider_name,
                display_name=display_name,
                description=description,
                api_base=api_base,
                models=models,
                default_model=default_model,
                code=code or None,
                created_by=user_id,
            )
            save_session.add(record)
        await save_session.commit()

    from app.services.llm import refresh_provider
    refresh_provider(provider_name, {
        "display_name": display_name,
        "description": description,
        "api_base": api_base,
        "models": models,
        "default_model": default_model,
        "code": code or None,
    })
    logger.info(f"Provider 已保存: {provider_name}")
    return _json.dumps({"success": True, "message": f"Provider '{display_name}' 已注册，可在模型配置中使用"}, ensure_ascii=False)


async def _get_llm_config_handler(args, db, user_id, context):
    import json as _json
    from app.services.llm import get_all_providers, llm_manager

    all_providers = []
    for name, info in get_all_providers().items():
        all_providers.append({
            "name": name,
            "display_name": info.get("display_name", name),
            "description": info.get("description", ""),
            "api_base": info.get("api_base", "") or "",
            "models": info.get("models", []),
            "default_model": info.get("default_model", ""),
        })

    available_models = [
        {"model": m, "description": "快速" if "flash" in m.lower() else "深度"}
        for m in llm_manager._available_models()
    ]

    return _json.dumps({
        "providers": all_providers,
        "available_models": available_models,
    }, ensure_ascii=False, default=str)


async def _delete_llm_adapter_handler(args, db, user_id, context):
    import json as _json
    provider_name = args.get("provider_name", "").strip().lower()
    if not provider_name:
        return _json.dumps({"success": False, "error": "缺少 provider_name"}, ensure_ascii=False)

    from app.core.database import async_session
    from app.models.custom_extension import LLMProvider
    from sqlalchemy import select as sa_select
    async with async_session() as del_session:
        existing = await del_session.execute(sa_select(LLMProvider).where(LLMProvider.provider_name == provider_name))
        record = existing.scalar_one_or_none()
        if not record:
            return _json.dumps({"success": False, "error": f"Provider '{provider_name}' 不存在"}, ensure_ascii=False)
        display_name = record.display_name or provider_name
        record.is_active = False
        await del_session.commit()

    from app.services.llm import _custom_adapter_cache, _provider_registry
    _custom_adapter_cache.pop(provider_name, None)
    _provider_registry.pop(provider_name, None)
    logger.info(f"Provider 已删除: {provider_name}")
    return _json.dumps({"success": True, "message": f"Provider '{display_name}' ({provider_name}) 已删除"}, ensure_ascii=False)


# ==================== 检查工具（原 data_inspector_agent.py）====================

def _register_inspector_tools():
    register_tool("profile_data", {
        "type": "function",
        "function": {
            "name": "profile_data",
            "description": "获取数据概览：行数、列数、各列类型、空值率、唯一值数、样本数据。无需传参，自动检查当前数据源和表",
            "parameters": {"type": "object", "properties": {}},
        },
    }, _profile_data_handler, cacheable=False)

    register_tool("check_data_standards", {
        "type": "function",
        "function": {
            "name": "check_data_standards",
            "description": "检查数据是否符合命名规范、类型标准、编码规范。无需传参，自动检查当前数据源和表",
            "parameters": {
                "type": "object",
                "properties": {
                    "standard_rules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "检查规则列表，如 ['naming_convention', 'type_consistency', 'encoding_check']",
                    },
                },
            },
        },
    }, _check_data_standards_handler, cacheable=False)

    register_tool("check_data_quality", {
        "type": "function",
        "function": {
            "name": "check_data_quality",
            "description": "检查数据质量：完整性、唯一性、范围合理性、业务逻辑一致性。无需传参，自动检查当前数据源和表",
            "parameters": {
                "type": "object",
                "properties": {
                    "quality_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "质量维度，如 ['completeness', 'uniqueness', 'validity', 'consistency']",
                    },
                },
            },
        },
    }, _check_data_quality_handler, cacheable=False)

    register_tool("check_data_security", {
        "type": "function",
        "function": {
            "name": "check_data_security",
            "description": "检查数据安全：PII识别、敏感数据暴露、脱敏完整性。无需传参，自动检查当前数据源和表",
            "parameters": {"type": "object", "properties": {}},
        },
    }, _check_data_security_handler, cacheable=False)


# ---- 检查工具 handler 实现 ----
# 从 context 自动填充 datasource_id 和 table_name（原 DataInspector._execute_tool 的逻辑）

async def _profile_data_handler(args, db, user_id, context):
    from app.services.inspector_tools import DataInspectorTools
    ds_id, tbl = _resolve_ds_table(context)
    if not ds_id or not tbl:
        return json.dumps({"error": "缺少数据源ID或表名（context 中未找到当前数据源信息）"}, ensure_ascii=False)
    result = await DataInspectorTools.profile_data(db, ds_id, tbl)
    return json.dumps(result, ensure_ascii=False, default=str)


async def _check_data_standards_handler(args, db, user_id, context):
    from app.services.inspector_tools import DataInspectorTools
    ds_id, tbl = _resolve_ds_table(context)
    if not ds_id or not tbl:
        return json.dumps({"error": "缺少数据源ID或表名（context 中未找到当前数据源信息）"}, ensure_ascii=False)
    result = await DataInspectorTools.check_data_standards(db, ds_id, tbl)
    return json.dumps(result, ensure_ascii=False, default=str)


async def _check_data_quality_handler(args, db, user_id, context):
    from app.services.inspector_tools import DataInspectorTools
    ds_id, tbl = _resolve_ds_table(context)
    if not ds_id or not tbl:
        return json.dumps({"error": "缺少数据源ID或表名（context 中未找到当前数据源信息）"}, ensure_ascii=False)
    result = await DataInspectorTools.check_data_quality(db, ds_id, tbl)
    return json.dumps(result, ensure_ascii=False, default=str)


async def _check_data_security_handler(args, db, user_id, context):
    from app.services.inspector_tools import DataInspectorTools
    ds_id, tbl = _resolve_ds_table(context)
    if not ds_id or not tbl:
        return json.dumps({"error": "缺少数据源ID或表名（context 中未找到当前数据源信息）"}, ensure_ascii=False)
    result = await DataInspectorTools.check_data_security(db, ds_id, tbl)
    return json.dumps(result, ensure_ascii=False, default=str)


def _resolve_ds_table(context):
    """从 context 解析数据源ID和表名（原 DataInspector._execute_tool 的自动填充逻辑）。"""
    ds_id = context.get("datasource_id") or context.get("debug_source_datasource_id") or context.get("debug_datasource_id")
    tbl = context.get("table_name") or context.get("debug_source_table_name") or context.get("debug_table_name")

    if not ds_id or not tbl:
        ds_name = context.get("source_datasource_name") or context.get("debug_source_datasource_name")
        tbl_name = context.get("source_table_name") or context.get("debug_source_table_name")
        if ds_name and tbl_name:
            # 延迟查 DB（需要时再在 handler 内处理）
            return ds_name, tbl_name
    return ds_id, tbl


# ==================== 向后兼容：旧 execute_shared_tool ====================

async def execute_shared_tool(name: str, arguments: dict, db: AsyncSession, user_id) -> str:
    """向后兼容入口（旧代码通过此函数分发共享工具）。
    内部委托 execute_tool，传 context={}（共享工具不需要 context）。
    """
    _ensure_registered()
    return await execute_tool(name, arguments, db, user_id, {})


# ==================== 启动时自动注册 ====================

_ensure_registered()
