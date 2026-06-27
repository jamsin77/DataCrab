"""对话API端点"""

import asyncio
import json
import os
import pandas as pd
from uuid import UUID, uuid4
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

_active_stream_events: dict[str, asyncio.Event] = {}

from app.core.database import get_db
from app.models.chat import ChatSession, ChatMessage
from app.models.user import User
from app.models.filelink import FileLink
from app.models.datasource import DataSource
from app.schemas.chat import (
    ChatSessionCreate,
    ChatSessionUpdate,
    ChatSessionResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    NLDataProcessRequest,
    NLDataProcessResponse,
    NLStreamEvent,
)
from app.api.deps import get_current_user
from app.services.llm import llm_manager
from app.services.nl_service import NLService
from app.services.skill_library import skill_library

router = APIRouter()

# 初始化NL服务
nl_service = NLService(llm_manager, skill_library)

# 加载助理人格文件
_persona_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_persona_path = os.path.join(_persona_dir, "services", "personal.md")
try:
    with open(_persona_path, "r", encoding="utf-8") as _f:
        ASSISTANT_PERSONA = _f.read().strip()
except FileNotFoundError:
        ASSISTANT_PERSONA = ""


@router.get("/agent/config")
async def get_agent_config():
    """获取Agent配置信息"""
    from app.services.agent_config import agent_config
    return agent_config.to_dict()


def _build_system_prompt(datasource_context: str) -> str:
    from app.services.prompt_docs import SANDBOX_TOOLS_DOC, SAFETY_RULES_DOC
    persona_block = f"{ASSISTANT_PERSONA}\n\n---\n\n" if ASSISTANT_PERSONA else ""
    return f"""{persona_block}## 数据源知识库
{datasource_context}

## 重要提示
如果上面的上下文中包含了【实时数据查询结果】，说明已经为用户自动查询了真实数据。
请基于这些真实数据直接告诉用户数据的内容，比如列出表中有哪些字段、前几行数据是什么。
如果数据较多，请概括总结数据的特征（如总行数、列名、数据类型等）。

{SANDBOX_TOOLS_DOC}

{SAFETY_RULES_DOC}"""


async def build_datasource_context(
    db: AsyncSession,
    user_id: UUID,
    user_message: str = "",
) -> str:
    result = await db.execute(
        select(DataSource).where(
            DataSource.is_active == True,
            DataSource.created_by == user_id,
        )
    )
    sources = result.scalars().all()

    if not sources:
        return '\n## 可用数据源\n当前没有配置任何数据源。建议用户先在【数据源管理】页面添加数据源。\n'

    lines = ["\n## 可用数据源（工具的知识库）"]
    lines.append(f"以下 {len(sources)} 个数据源已配置，可供用户分析：\n")

    for ds in sources:
        cfg = ds.connection_config or {}
        lines.append(f"### {ds.name}（类型: {ds.type}, ID: {ds.id}）")
        if ds.type in ("mysql", "postgres"):
            lines.append(f"- 主机: {cfg.get('host', 'N/A')}:{cfg.get('port', 'N/A')}")
            lines.append(f"- 数据库: {cfg.get('database', 'N/A')}")
        elif ds.type == "csv":
            lines.append(f"- 文件路径: {cfg.get('file_path', 'N/A')}")
        elif ds.type == "excel":
            lines.append(f"- 文件路径: {cfg.get('file_path', 'N/A')}")
            lines.append(f"- 工作表: {cfg.get('sheet_name', 'N/A')}")
        elif ds.type in ("obs", "s3"):
            lines.append(f"- Endpoint: {cfg.get('endpoint', 'N/A')}")
            lines.append(f"- Bucket: {cfg.get('bucket', 'N/A')}")
            lines.append(f"- 基础路径: {cfg.get('base_path', '/')}")
        elif ds.type == "hadoop":
            lines.append(f"- 地址: {cfg.get('host', 'N/A')}:{cfg.get('port', 'N/A')}")
            lines.append(f"- 用户: {cfg.get('user', 'N/A')}")
            lines.append(f"- 基础路径: {cfg.get('base_path', '/')}")

        if ds.table_metadata:
            table_names = [t.table_name for t in ds.table_metadata if t.table_name]
            if table_names:
                lines.append(f"- 包含的表/文件: {', '.join(table_names[:10])}")
                if len(table_names) > 10:
                    lines.append(f"  ...还有 {len(table_names) - 10} 个")

        lines.append("")

    # 当用户消息中提到了数据源名称时，自动查询实际数据
    data_previews = await _query_datasource_previews(sources, user_message)
    if data_previews:
        lines.append(data_previews)

    return "\n".join(lines)


CHINESE_ERA_MAP = {
    "旧石器": -1000000, "旧石器时代": -1000000,
    "更新世": -1000000,
    "新石器": -10000, "新石器时代": -10000, "石器时代": -10000,
    "新时器时代": -10000,
    "青铜时代": -2000, "新石器至青铜时代": -2000,
    "夏": -2070, "夏商": -2070, "夏至商": -2070, "夏至周": -2070,
    "夏至西周": -2070, "夏商至唐宋": -2070,
    "商": -1600, "殷": -1600, "商周": -1600,
    "西周": -1046, "西周至东周": -1046, "西周至春秋": -1046,
    "西周至战国": -1046, "西周至宋": -1046,
    "东周": -770,
    "春秋": -770, "春秋至战国": -770, "春秋至汉": -770,
    "春秋至西汉": -770, "春秋至明": -770, "春秋至清": -770,
    "春秋至南北朝": -770, "春秋至五代": -770,
    "战国": -475, "战国至汉": -475, "战国至秦": -475,
    "战国至清": -475, "战国至明": -475, "战国至唐": -475,
    "战国至宋": -475, "战国至晋": -475, "战国至金": -475,
    "战国至民国": -475, "战国至秦汉": -475, "战国至东汉": -475,
    "战国至西汉": -475, "战国至隋唐": -475,
    "秦": -221, "秦至汉": -221, "秦至清": -221,
    "秦至宋": -221, "秦至晋": -221, "秦至西汉": -221,
    "秦汉": -221, "秦、汉": -221, "秦、西汉": -221,
    "汉": -206, "西汉": -206, "西汉至东汉": -206,
    "西汉至宋": -206, "西汉至清": -206, "西汉至隋": -206,
    "西汉至西晋": -206, "汉至三国": -206, "汉至六朝": -206,
    "汉至北魏": -206, "汉至南北朝": -206, "汉至唐": -206,
    "汉至宋": -206, "汉至明": -206, "汉至晋": -206,
    "汉至民国": -206, "汉至清": -206, "汉至近代": -206,
    "汉至魏": -206, "汉至魏晋": -206, "汉魏": -206,
    "汉晋": -206, "汉唐": -206, "汉至清": -206,
    "东汉": 25,
    "三国": 220, "曹魏": 220, "曹魏至北齐": 220,
    "魏至唐": 220, "西魏": 535,
    "晋": 266, "西晋": 266, "西晋至民国": 266,
    "晋至唐": 266, "晋至宋": 266, "晋至民国": 266,
    "晋至清": 266, "晋至宋": 266, "晋十六国": 266,
    "十六国": 304,
    "南北朝": 420, "北魏": 386,
    "隋": 581, "隋唐": 581, "隋至唐": 581,
    "隋至宋": 581, "隋至明": 581, "隋至清": 581,
    "隋至五代": 581, "隋至元": 581,
    "唐": 618, "高昌": 460,
    "五代": 907, "五代十国": 907,
    "渤海": 698,
    "宋": 960, "北宋": 960, "南宋": 1127,
    "宋至元": 960, "宋至明": 960, "宋至清": 960,
    "宋至民国": 960, "宋至近代": 960, "宋至中华人民共和国": 960,
    "宋辽": 960, "宋金": 960, "宋金元": 960,
    "宋元": 960, "宋明": 960, "宋明至清": 960,
    "宋明": 960, "宋明清": 960, "宋清": 960,
    "辽": 907, "辽至元": 907, "辽至明": 907,
    "辽至清": 907, "辽至金": 907, "辽金": 907,
    "辽金元": 907, "辽金清": 907,
    "西夏": 1038, "西夏至元": 1038, "西夏至明代": 1038,
    "金": 1115, "金至元": 1115, "金至明": 1115,
    "金至民国": 1115, "金至清": 1115, "金元": 1115,
    "金元明": 1115, "金明": 1115, "金明清": 1115,
    "金清": 1115, "汉金": -206,
    "元": 1271,
    "明": 1368, "明至清末": 1368, "明至民国": 1368,
    "明至清": 1368, "明以前": 1368, "明初至清": 1368,
    "明至中华人民共和国": 1368, "明清": 1368, "明民国": 1368,
    "明近代": 1368,
    "清": 1644, "清代中期": 1776, "清末": 1911,
    "清末民初": 1911, "清至民国": 1644, "清至近代": 1644,
    "清至中华人民共和国": 1644, "清民国": 1644,
    "民国": 1912, "近代": 1840, "近现代": 1912,
    "离": 9999,
}


def extract_sort_year(era_text: str) -> int:
    """将时代文本转换为可排序的年份数字"""
    import re as _re
    if not isinstance(era_text, str) or not era_text.strip():
        return 99999

    text = era_text.strip()
    text_clean = _re.sub(r'\[.*?\]', '', text).strip()

    year_match = _re.search(r'(\d{4})', text_clean)
    if year_match:
        year = int(year_match.group(1))
        if "前" in text_clean or "B" in text_clean.upper():
            year = -year
        return year

    for key, year in sorted(CHINESE_ERA_MAP.items(), key=lambda x: -len(x[0])):
        if key in text_clean:
            return year

    return 99999


DYNASTY_PATTERNS = {
    "旧石器时代": "旧石器", "新石器时代": "新石器", "新石器": "新石器", "旧石器": "旧石器",
    "夏代": "夏", "夏朝": "夏",
    "商代": "商", "商朝": "商",
    "西周": "周", "东周": "周", "周代": "周", "周朝": "周",
    "春秋": "春秋", "战国": "战国",
    "秦代": "秦", "秦朝": "秦",
    "西汉": "汉", "东汉": "汉", "汉代": "汉", "汉朝": "汉",
    "三国": "三国",
    "西晋": "晋", "东晋": "晋", "晋代": "晋", "晋朝": "晋",
    "南北朝": "南北朝",
    "隋代": "隋", "隋朝": "隋",
    "唐代": "唐", "唐朝": "唐",
    "五代": "五代", "十国": "十国",
    "北宋": "宋", "南宋": "宋", "宋代": "宋", "宋朝": "宋",
    "辽代": "辽", "辽朝": "辽",
    "西夏": "西夏",
    "金代": "金", "金朝": "金",
    "元代": "元", "元朝": "元",
    "明代": "明", "明朝": "明",
    "清代": "清", "清朝": "清",
    "民国": "民国",
}


def _parse_complex_query(user_message: str) -> dict:
    """解析用户消息中的复杂查询意图，返回操作指令"""
    import re as _re
    msg = user_message.lower() if user_message else ""
    result = {
        "is_complex": False,
        "sort_field": None,
        "sort_order": "asc",
        "filter_field": None,
        "filter_value": None,
        "limit": None,
        "aggregate": None,
        "group_by": None,
        "dynasty_keywords": None,
    }

    earliest = _re.search(r'最早[的的]?\s*(\d+)?\s*[个条]', msg)
    latest = _re.search(r'最晚[的的]?\s*(\d+)?\s*[个条]', msg)
    newest = _re.search(r'最新[的的]?\s*(\d+)?\s*[个条]', msg)

    if earliest:
        result["is_complex"] = True
        result["sort_field"] = "时代"
        result["sort_order"] = "asc"
        result["limit"] = int(earliest.group(1)) if earliest.group(1) else 100
    elif latest or newest:
        result["is_complex"] = True
        result["sort_field"] = "时代"
        result["sort_order"] = "desc"
        result["limit"] = int((latest or newest).group(1)) if (latest or newest).group(1) else 100

    sort_match = _re.search(r'按[照]?\s*(\S{1,4})\s*(升序|降序|从早到晚|从晚到早|从小到大|从大到小)?\s*排[序名]', msg)
    if sort_match:
        result["is_complex"] = True
        result["sort_field"] = sort_match.group(1)
        order_hint = sort_match.group(2) or ""
        if any(w in order_hint for w in ["降", "到早", "到大"]):
            result["sort_order"] = "desc"

    top_match = _re.search(r'(?:取|要|查|找|显示|列出)\s*(?:前|最前面的|前面的)?\s*(\d+)\s*[个条]', msg)
    if top_match:
        result["is_complex"] = True
        if result["limit"] is None:
            result["limit"] = int(top_match.group(1))

    filter2 = _re.search(r'(\S{1,4})\s*(包含|含有|大于|小于|大于等于|小于等于|>=|<=|>|<)\s*(\S{1,20})', msg)
    if filter2:
        result["is_complex"] = True
        result["filter_field"] = filter2.group(1)
        result["filter_value"] = filter2.group(3)

    dynasty_found = set()
    sorted_patterns = sorted(DYNASTY_PATTERNS.keys(), key=lambda x: -len(x))
    for pattern in sorted_patterns:
        if pattern in user_message:
            dynasty_found.add(DYNASTY_PATTERNS[pattern])
    if dynasty_found:
        result["is_complex"] = True
        result["dynasty_keywords"] = list(dynasty_found)
        if result["filter_field"] is None:
            result["filter_field"] = "时代"
            result["filter_value"] = "|".join(dynasty_found)
        if result["sort_field"] is None:
            result["sort_field"] = "时代"
            result["sort_order"] = "asc"
        if result["limit"] is None:
            fallback_limit = _re.search(r'(\d+)\s*[个条]', msg)
            if fallback_limit:
                result["limit"] = int(fallback_limit.group(1))

    if _re.search(r'(统计|计数|数量|多少个|count)', msg):
        result["is_complex"] = True
        result["aggregate"] = "count"

    group_match = _re.search(r'按[照]?\s*(\S{1,4})\s*(分组|分类|group)', msg)
    if group_match:
        result["is_complex"] = True
        result["group_by"] = group_match.group(1)

    return result


async def _query_datasource_previews(sources, user_message: str) -> str:
    """查询用户消息中提到的数据源的实际数据预览"""
    from app.services.connectors import get_connector
    if not user_message:
        return ""

    msg_lower = user_message.lower()
    previews = []

    import re
    complex_intent = _parse_complex_query(user_message)

    all_keywords = ["全部", "所有", "所有数据", "全部数据", "all", "完整", "整个"]
    want_all = any(kw in msg_lower for kw in all_keywords)
    page_match = re.search(r'第\s*(\d+)\s*页|page\s*(\d+)', msg_lower)
    next_match = re.search(r'下\s*一\s*页|下一页|next\s*page|更多', msg_lower)

    page = 1
    if page_match:
        page = int(page_match.group(1) or page_match.group(2))
    elif next_match:
        page = 2

    page_size = 200 if want_all else 50

    matched_sources = []
    for ds in sources:
        ds_name_lower = ds.name.lower()
        if ds_name_lower in msg_lower:
            matched_sources.append(ds)
            continue
        name_keywords = ds_name_lower.replace('_', ' ').replace('-', ' ').split()
        if any(kw in msg_lower for kw in name_keywords):
            matched_sources.append(ds)
            continue

    if not matched_sources and sources:
        data_keywords = ['数据', '分析', '统计', '查询', '看看', '查看', 'data', 'analyze']
        if any(kw in msg_lower for kw in data_keywords):
            matched_sources = [sources[0]]

    for ds in matched_sources:

        try:
            connector = get_connector(ds.type, ds.connection_config or {})
            schema = await connector.get_schema()

            if not schema:
                await connector.close()
                continue

            first_table = schema[0].get("table_name", "")
            if not first_table:
                await connector.close()
                continue

            total_rows = 0
            try:
                stats = await connector.get_table_stats(first_table)
                total_rows = stats.get("row_count", 0)
            except Exception:
                pass

            if complex_intent["is_complex"]:
                logger.info(f"复杂查询 [{ds.name}] 表 {first_table} intent={complex_intent}")
                load_size = total_rows if total_rows > 0 else 99999
                df = await connector.get_table_data(first_table, page=1, page_size=load_size)
                await connector.close()

                if df.empty:
                    continue

                preview_text = _execute_complex_query(df, ds.name, first_table, complex_intent)
                if preview_text:
                    previews.append(preview_text)
                continue

            logger.info(f"查询数据源 [{ds.name}] 表 {first_table} page={page} size={page_size}")

            df = await connector.get_table_data(first_table, page=page, page_size=page_size)
            await connector.close()

            if df.empty:
                continue

            row_count = len(df)
            col_count = len(df.columns)
            total_pages = (total_rows + page_size - 1) // page_size if total_rows > 0 else 0

            preview_text = f"\n### 【实时数据】{ds.name} - {first_table}\n"
            preview_text += f"总行数: {total_rows}, 总列数: {col_count}, 当前第 {page} 页"
            if total_pages > 0:
                preview_text += f", 共 {total_pages} 页"
                preview_text += "\n> 提示: 如需翻页请说\"显示第2页\"，想看更多请说\"显示所有数据\""
            preview_text += f"\n\n显示 {row_count} 行:\n\n"

            headers = list(df.columns)
            preview_text += "| " + " | ".join(str(h)[:15] for h in headers) + " |\n"
            preview_text += "| " + " | ".join("---" for _ in headers) + " |\n"

            for _, row in df.iterrows():
                vals = [str(v)[:30] if v is not None and str(v) != "nan" else "" for v in row]
                preview_text += "| " + " | ".join(vals) + " |\n"

            previews.append(preview_text)
            logger.info(f"数据源 [{ds.name}] 已查询: {row_count}/{total_rows}行 x {col_count}列")

        except Exception as e:
            logger.warning(f"查询数据源 [{ds.name}] 数据失败: {e}")
            continue

    if previews:
        return "\n## 实时数据查询结果\n以下是从数据源中查询到的真实数据，请基于这些数据回答用户问题：\n" + "\n".join(previews)
    return ""


def _execute_complex_query(df, ds_name: str, table_name: str, intent: dict) -> str:
    """对DataFrame执行复杂查询操作（排序、筛选、限制、聚合）"""
    import re as _re

    result_text = f"\n### 【复杂查询】{ds_name} - {table_name}\n"
    result_text += f"总行数: {len(df)}, 总列数: {len(df.columns)}\n\n"

    if intent["sort_field"]:
        sort_field = intent["sort_field"]
        if sort_field not in df.columns:
            for col in df.columns:
                if sort_field in str(col):
                    sort_field = col
                    break

        if sort_field in df.columns:
            ascending = intent["sort_order"] == "asc"
            if sort_field == "时代":
                result_text += "> 排序方式: 按中国历史年代表排序\n\n"
                df["_sort_year"] = df[sort_field].apply(extract_sort_year)
                df = df.sort_values("_sort_year", ascending=ascending)
                df = df.drop(columns=["_sort_year"])
            else:
                try:
                    df[sort_field] = pd.to_numeric(df[sort_field], errors="coerce")
                    df = df.sort_values(sort_field, ascending=ascending)
                except Exception:
                    df = df.sort_values(sort_field, ascending=ascending)
            result_text += f"按 `{intent['sort_field']}` {'升序' if ascending else '降序'} 排序\n\n"

    if intent["filter_field"]:
        filter_field = intent["filter_field"]
        filter_value = intent["filter_value"]
        df_before = len(df)

        if filter_field in df.columns and filter_value:
            if "|" in filter_value:
                mask = df[filter_field].astype(str).str.contains(filter_value, regex=True, na=False)
            else:
                mask = df[filter_field].astype(str).str.contains(_re.escape(filter_value), na=False)
            df = df[mask]
            matched = len(df)
            if intent.get("dynasty_keywords"):
                dynasty_names = ", ".join(intent["dynasty_keywords"])
                result_text += f"筛选: `{filter_field}` 匹配朝代 [{dynasty_names}]，匹配 {matched}/{df_before} 行\n\n"
            else:
                result_text += f"筛选: `{filter_field}` 包含 `{filter_value}`，匹配 {matched}/{df_before} 行\n\n"
        else:
            for col in df.columns:
                if filter_field in str(col):
                    if "|" in filter_value:
                        mask = df[col].astype(str).str.contains(filter_value, regex=True, na=False)
                    else:
                        mask = df[col].astype(str).str.contains(_re.escape(filter_value), na=False)
                    df = df[mask]
                    result_text += f"筛选: `{col}` 包含 `{filter_value}`，匹配 {len(df)} 行\n\n"
                    break

    if intent["group_by"] and intent["aggregate"] == "count":
        group_field = intent["group_by"]
        if group_field in df.columns:
            counts = df.groupby(group_field).size().reset_index(name="数量")
            counts = counts.sort_values("数量", ascending=False)
            result_text += f"按 `{group_field}` 分组计数:\n\n"
            result_text += counts.head(50).to_markdown(index=False)
            result_text += f"\n\n共 {len(counts)} 个分组\n"
            return result_text

    if intent["limit"]:
        limit = intent["limit"]
        df = df.head(limit)
        result_text += f"取前 {min(limit, len(df))} 行\n\n"

    row_count = len(df)
    headers = list(df.columns)
    result_text += f"显示 {row_count} 行:\n\n"
    result_text += "| " + " | ".join(str(h)[:15] for h in headers) + " |\n"
    result_text += "| " + " | ".join("---" for _ in headers) + " |\n"

    for _, row in df.iterrows():
        vals = [str(v)[:40] if v is not None and str(v) != "nan" else "" for v in row]
        result_text += "| " + " | ".join(vals) + " |\n"

    if row_count == intent.get("limit", 0):
        result_text += f"\n> 已按排序规则返回前 {row_count} 行，如需更多请指定数量\n"

    return result_text


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建对话会话"""
    session = ChatSession(
        user_id=current_user.id,
        title=request.title or "新会话",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取会话列表"""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取会话详情"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return session


@router.put("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: UUID,
    request: ChatSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新会话"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    session.title = request.title
    await db.flush()
    await db.refresh(session)
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除会话"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    await db.delete(session)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def list_messages(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取消息列表"""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或无权访问")
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return result.scalars().all()


@router.post("/messages", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    request: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送消息"""
    # 验证会话存在
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == request.session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    # 保存用户消息
    user_message = ChatMessage(
        session_id=request.session_id,
        role="user",
        content=request.content,
    )
    db.add(user_message)
    await db.flush()
    await db.refresh(user_message)

    try:
        # 初始化技能库
        await skill_library.initialize()

        # 初始化LLM
        await llm_manager.initialize()

        # 调用NL处理服务进行意图识别和技能匹配
        nl_result = await nl_service.process(
            text=request.content,
            context={"user_id": str(current_user.id)}
        )

        # 获取历史消息（最近20条，不包括当前刚保存的）
        history_result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == request.session_id,
                ChatMessage.id != user_message.id,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(20)
        )
        history_messages = list(history_result.scalars().all())
        history_messages.reverse()

        # 构建数据源知识库（含实时数据查询）
        datasource_context = await build_datasource_context(
            db, current_user.id, request.content
        )

        # 构建 system prompt
        system_content = _build_system_prompt(datasource_context)

        # 组装 messages 列表
        messages = [{"role": "system", "content": system_content}]

        for msg in history_messages:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": request.content})

        logger.info(f"chat messages: system={len(system_content)}chars, history={len(history_messages)}, total={len(messages)}")
        for i, m in enumerate(messages):
            preview = m["content"][:80].replace("\n", "\\n")
            logger.debug(f"  msg[{i}] role={m['role']} preview={preview}...")

        ai_content = await llm_manager.chat_with_messages(messages, max_tokens=2000)

    except Exception as e:
        logger.error(f"LLM调用失败: {e}")
        ai_content = f"处理您的请求时出现错误: {str(e)}"

    # 保存AI响应
    ai_message = ChatMessage(
        session_id=request.session_id,
        role="assistant",
        content=ai_content,
    )
    db.add(ai_message)
    await db.flush()
    await db.refresh(ai_message)

    return ai_message


@router.post("/stream")
async def stream_response(
    request: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式响应"""

    async def generate():
        session_id = str(request.session_id)
        cancel_event = asyncio.Event()
        _active_stream_events[session_id] = cancel_event

        try:
            user_message = ChatMessage(
                session_id=request.session_id,
                role="user",
                content=request.content,
            )
            db.add(user_message)
            await db.flush()

            await skill_library.initialize()
            await llm_manager.initialize()

            nl_result = await nl_service.process(
                text=request.content,
                context={"user_id": str(current_user.id)}
            )

            history_result = await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == request.session_id,
                    ChatMessage.id != user_message.id,
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(20)
            )
            history_messages = list(history_result.scalars().all())
            history_messages.reverse()

            datasource_context = await build_datasource_context(
                db, current_user.id, request.content
            )

            system_content = _build_system_prompt(datasource_context)

            messages = [{"role": "system", "content": system_content}]

            for msg in history_messages:
                messages.append({"role": msg.role, "content": msg.content})

            messages.append({"role": "user", "content": request.content})

            from app.services.agent import agent_service, AgentContext

            agent_ctx = AgentContext(
                db=db,
                user_id=current_user.id,
                datasource_context=datasource_context,
                persona=ASSISTANT_PERSONA,
            )

            full_response = ""
            async for sse_chunk in agent_service.run_stream(messages, agent_ctx):
                if cancel_event.is_set():
                    yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                    return
                yield sse_chunk

                try:
                    data = json.loads(sse_chunk.removeprefix("data: ").strip())
                    if data.get("type") == "content":
                        full_response += data.get("content", "")
                except (json.JSONDecodeError, AttributeError):
                    pass

            ai_message = ChatMessage(
                session_id=request.session_id,
                role="assistant",
                content=full_response,
            )
            db.add(ai_message)
            await db.flush()

            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式响应失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            _active_stream_events.pop(session_id, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/stop")
async def stop_generation(session_id: str = Query(..., description="要停止的会话ID")):
    event = _active_stream_events.get(session_id)
    if event:
        event.set()
        return {"message": "已停止生成"}
    return {"message": "没有活跃的生成任务"}


# ===== 自然语言数据处理 =====

@router.post("/process-data", response_model=NLDataProcessResponse)
async def process_data_with_natural_language(
    request: NLDataProcessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """使用自然语言处理数据"""
    try:
        # 导入NL数据处理服务
        from app.services.nl_data_processor import nl_processor

        # 初始化技能库
        await skill_library.initialize()

        # 获取输入数据
        if request.data:
            input_df = pd.DataFrame(request.data)
        elif request.file_id:
            # 从文件加载数据
            result = await db.execute(
                select(FileLink).where(FileLink.id == request.file_id)
            )
            file_link = result.scalar_one_or_none()
            if not file_link:
                raise HTTPException(status_code=404, detail="文件不存在")

            # 根据文件类型加载
            file_path = file_link.file_path
            if file_path.endswith('.csv'):
                input_df = pd.read_csv(file_path)
            elif file_path.endswith('.xlsx') or file_path.endswith('.xls'):
                input_df = pd.read_excel(file_path)
            elif file_path.endswith('.json'):
                input_df = pd.read_json(file_path)
            else:
                raise HTTPException(status_code=400, detail="不支持的文件格式")
        else:
            raise HTTPException(status_code=400, detail="请提供数据或文件ID")

        # 构建处理请求
        from app.services.nl_data_processor import DataProcessingRequest
        process_request = DataProcessingRequest(
            natural_language=request.natural_language,
            input_data=input_df,
            session_id=str(request.session_id or uuid4()),
            context={"user_id": str(current_user.id)}
        )

        # 处理
        result = await nl_processor.process(process_request)

        # 转换输出数据为JSON格式
        output_json = None
        if result.output_data is not None:
            output_json = result.output_data.to_dict(orient="records")

        return NLDataProcessResponse(
            success=result.success,
            output_data=output_json,
            pipeline_name=result.pipeline_name,
            steps=result.steps,
            explanation=result.explanation,
            execution_time=result.execution_time,
            error=result.error,
            logs=result.logs
        )

    except Exception as e:
        logger.error(f"自然语言数据处理失败: {e}")
        return NLDataProcessResponse(
            success=False,
            error=str(e),
            logs=[f"处理失败: {e}"]
        )


@router.post("/process-data-stream")
async def process_data_streaming(
    request: NLDataProcessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式处理数据"""
    async def generate():
        try:
            from app.services.nl_data_processor import nl_processor, DataProcessingRequest

            # 初始化技能库
            await skill_library.initialize()

            # 获取输入数据
            if request.data:
                input_df = pd.DataFrame(request.data)
            elif request.file_id:
                result = await db.execute(
                    select(FileLink).where(FileLink.id == request.file_id)
                )
                file_link = result.scalar_one_or_none()
                if not file_link:
                    yield f"data: {json.dumps({'type': 'error', 'message': '文件不存在'}, ensure_ascii=False)}\n\n"
                    return
                file_path = file_link.file_path
                if file_path.endswith('.csv'):
                    input_df = pd.read_csv(file_path)
                elif file_path.endswith('.xlsx'):
                    input_df = pd.read_excel(file_path)
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': '不支持的文件格式'}, ensure_ascii=False)}\n\n"
                    return
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': '请提供数据或文件ID'}, ensure_ascii=False)}\n\n"
                return

            # 构建处理请求
            process_request = DataProcessingRequest(
                natural_language=request.natural_language,
                input_data=input_df,
                session_id=str(request.session_id or uuid4()),
                context={"user_id": str(current_user.id)}
            )

            # 流式处理
            for event in await nl_processor.process_streaming(process_request):
                # 转换DataFrame为JSON
                if "preview" in event and event["preview"] is not None:
                    preview = event["preview"]
                    if "data" in preview and isinstance(preview["data"], list):
                        pass  # 已经是JSON格式

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"流式处理失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/skills")
async def list_available_skills():
    """列出可用技能"""
    await skill_library.initialize()
    skills = skill_library.list_skills()
    return {
        "skills": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "display_name": s.get("display_name"),
                "description": s.get("description"),
                "category": s.get("category"),
                "tags": s.get("tags", [])
            }
            for s in skills
        ]
    }
