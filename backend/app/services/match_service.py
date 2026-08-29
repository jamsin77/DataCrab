"""技能/流程/算子向量索引服务：ChromaDB embedding 存取 + 语义检索"""

import os
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger

from app.services.llm import llm_manager

_MATCH_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "match_detail.log")

def _mlog(msg: str):
    """独立写入 match_detail.log，不依赖 main.py 的日志过滤器"""
    with open(_MATCH_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MATCH_CHROMA_DIR = os.path.join(_BACKEND_DIR, "data", "match_chroma")
os.makedirs(MATCH_CHROMA_DIR, exist_ok=True)

SKILL_COLLECTION = "datacrab_skills"
PIPELINE_COLLECTION = "datacrab_pipelines"
OPERATOR_COLLECTION = "datacrab_operators"
TABLE_COLLECTION = "datacrab_tables"

MATCH_THRESHOLD = 0.10

_chroma_client = None
_skill_collection = None
_pipeline_collection = None
_operator_collection = None
_table_collection = None


def _get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=MATCH_CHROMA_DIR)
    return _chroma_client


def _get_skill_collection():
    global _skill_collection
    if _skill_collection is None:
        _skill_collection = _get_chroma_client().get_or_create_collection(name=SKILL_COLLECTION)
    return _skill_collection


def _get_pipeline_collection():
    global _pipeline_collection
    if _pipeline_collection is None:
        _pipeline_collection = _get_chroma_client().get_or_create_collection(name=PIPELINE_COLLECTION)
    return _pipeline_collection


def _get_operator_collection():
    global _operator_collection
    if _operator_collection is None:
        _operator_collection = _get_chroma_client().get_or_create_collection(name=OPERATOR_COLLECTION)
    return _operator_collection


def _get_table_collection():
    global _table_collection
    if _table_collection is None:
        _table_collection = _get_chroma_client().get_or_create_collection(name=TABLE_COLLECTION)
    return _table_collection


# ---------- 索引文本构建 ----------

def _build_skill_text(skill) -> str:
    parts = [skill.name or "", skill.description or ""]
    tags = skill.tags or []
    if tags:
        parts.append(" ".join(str(t) for t in tags))
    return "\n".join(p for p in parts if p)


def _build_operator_text(operator) -> str:
    parts = [operator.name or "", operator.description or ""]
    tags = operator.tags or []
    if tags:
        parts.append(" ".join(str(t) for t in tags))
    if operator.display_name:
        parts.insert(0, operator.display_name)
    return "\n".join(p for p in parts if p)


def _build_pipeline_text(pipeline, db=None) -> str:
    parts = [pipeline.display_name or pipeline.name or "", pipeline.description or ""]

    params = pipeline.parameters or []
    for p in params:
        if isinstance(p, dict):
            desc = p.get("description") or ""
            name = p.get("name") or ""
            if desc:
                parts.append(f"{name}: {desc}")

    related_ids = getattr(pipeline, "related_skill_ids", None) or []
    if related_ids and db is not None:
        from app.models.skill import Skill
        from sqlalchemy import select
        for sid in related_ids:
            try:
                import uuid as _uuid
                result = db.execute(select(Skill).where(Skill.id == _uuid.UUID(str(sid))))
                skill = result.scalar_one_or_none()
                if skill:
                    parts.append(f"关联技能: {skill.name} - {skill.description or ''}")
            except Exception:
                pass

    skill_calls = pipeline.skill_calls or []
    for sc in skill_calls:
        if isinstance(sc, dict):
            sname = sc.get("skill_name") or ""
            if sname:
                parts.append(f"调用技能: {sname}")

    tags = pipeline.tags or []
    if tags:
        parts.append(" ".join(str(t) for t in tags))
    return "\n".join(p for p in parts if p)


def _build_table_text(table_meta, ds_name: str = "") -> str:
    parts = [ds_name or "", table_meta.table_name or ""]
    if getattr(table_meta, "business_name", None):
        parts.append(table_meta.business_name)
    if getattr(table_meta, "business_description", None):
        parts.append(table_meta.business_description)
    if getattr(table_meta, "business_purpose", None):
        parts.append(table_meta.business_purpose)
    tags = getattr(table_meta, "business_tags", None) or []
    if tags:
        parts.append(" ".join(str(t) for t in tags))
    if getattr(table_meta, "data_domain", None):
        parts.append(table_meta.data_domain)
    if getattr(table_meta, "source_system", None):
        parts.append(table_meta.source_system)
    schema = getattr(table_meta, "table_schema", None) or []
    col_names = []
    for col in schema:
        if isinstance(col, dict) and col.get("name"):
            col_names.append(col["name"])
    if col_names:
        parts.append("列: " + ", ".join(col_names))
    return "\n".join(p for p in parts if p)


# ---------- 索引操作 ----------

async def index_skill(skill, raise_on_error=False):
    text = _build_skill_text(skill)
    if not text.strip():
        return
    try:
        emb = await llm_manager.embed(text)
        col = _get_skill_collection()
        col.delete(ids=[str(skill.id)]) if str(skill.id) in (col.get().get("ids", []) if hasattr(col, "get") else []) else None
        col.upsert(
            ids=[str(skill.id)],
            embeddings=[emb],
            documents=[text],
            metadatas=[{
                "name": skill.name or "",
                "skill_type": skill.skill_type or "",
                "visibility": skill.visibility or "public",
            }],
        )
    except Exception as e:
        logger.warning(f"索引技能 {getattr(skill, 'name', '?')} 失败: {e}")
        if raise_on_error:
            raise


async def index_pipeline(pipeline, db=None, raise_on_error=False):
    text = _build_pipeline_text(pipeline, db)
    if not text.strip():
        return
    try:
        emb = await llm_manager.embed(text)
        col = _get_pipeline_collection()
        col.upsert(
            ids=[str(pipeline.id)],
            embeddings=[emb],
            documents=[text],
            metadatas=[{
                "name": pipeline.name or "",
                "visibility": getattr(pipeline, "visibility", "private"),
            }],
        )
    except Exception as e:
        logger.warning(f"索引流程 {getattr(pipeline, 'name', '?')} 失败: {e}")
        if raise_on_error:
            raise


async def index_operator(operator, raise_on_error=False):
    text = _build_operator_text(operator)
    if not text.strip():
        return
    try:
        emb = await llm_manager.embed(text)
        col = _get_operator_collection()
        col.upsert(
            ids=[str(operator.id)],
            embeddings=[emb],
            documents=[text],
            metadatas=[{
                "name": operator.name or "",
                "visibility": operator.visibility or "public",
            }],
        )
    except Exception as e:
        logger.warning(f"索引算子 {getattr(operator, 'name', '?')} 失败: {e}")
        if raise_on_error:
            raise


async def update_skill_index(skill):
    await index_skill(skill)


async def update_pipeline_index(pipeline, db=None):
    await index_pipeline(pipeline, db)


async def update_operator_index(operator):
    await index_operator(operator)


async def index_table(table_meta, ds_name: str = "", raise_on_error=False):
    text = _build_table_text(table_meta, ds_name)
    if not text.strip():
        return
    try:
        emb = await llm_manager.embed(text)
        col = _get_table_collection()
        col.upsert(
            ids=[str(table_meta.id)],
            embeddings=[emb],
            documents=[text],
            metadatas=[{
                "data_source_id": str(table_meta.data_source_id) if table_meta.data_source_id else "",
                "table_name": table_meta.table_name or "",
            }],
        )
    except Exception as e:
        logger.warning(f"索引数据表 {getattr(table_meta, 'table_name', '?')} 失败: {e}")
        if raise_on_error:
            raise


def delete_skill_index(skill_id: str):
    try:
        _get_skill_collection().delete(ids=[str(skill_id)])
    except Exception as e:
        logger.warning(f"删除技能索引 {skill_id} 失败: {e}")


def delete_pipeline_index(pipeline_id: str):
    try:
        _get_pipeline_collection().delete(ids=[str(pipeline_id)])
    except Exception as e:
        logger.warning(f"删除流程索引 {pipeline_id} 失败: {e}")


def delete_operator_index(operator_id: str):
    try:
        _get_operator_collection().delete(ids=[str(operator_id)])
    except Exception as e:
        logger.warning(f"删除算子索引 {operator_id} 失败: {e}")


def delete_table_index(table_meta_id: str):
    try:
        _get_table_collection().delete(ids=[str(table_meta_id)])
    except Exception as e:
        logger.warning(f"删除数据表索引 {table_meta_id} 失败: {e}")


# ---------- 搜索 ----------

async def search_pipelines(query: str, top_k: int = 3) -> List[Tuple[str, float]]:
    if not query or not query.strip():
        return []
    q_emb = await llm_manager.embed(query)
    res = _get_pipeline_collection().query(
        query_embeddings=[q_emb],
        n_results=top_k,
    )
    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    return [(ids[i], round(1 - float(dists[i]), 4)) for i in range(len(ids)) if dists[i] is not None]


async def search_skills(query: str, top_k: int = 3) -> List[Tuple[str, float]]:
    if not query or not query.strip():
        return []
    q_emb = await llm_manager.embed(query)
    res = _get_skill_collection().query(
        query_embeddings=[q_emb],
        n_results=top_k,
    )
    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    return [(ids[i], round(1 - float(dists[i]), 4)) for i in range(len(ids)) if dists[i] is not None]


async def search_operators(query: str, top_k: int = 5) -> List[Tuple[str, float]]:
    if not query or not query.strip():
        return []
    try:
        q_emb = await llm_manager.embed(query)
        res = _get_operator_collection().query(
            query_embeddings=[q_emb],
            n_results=top_k,
        )
        ids = (res.get("ids") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        return [(ids[i], round(1 - float(dists[i]), 4)) for i in range(len(ids)) if dists[i] is not None]
    except Exception as e:
        logger.warning(f"算子向量搜索失败: {e}")
        return []


async def check_similar_resources(
    prompt: str,
    search_fn,
    model_cls,
    db,
    user_id,
    permission_resource: str,
    top_k: int = 5,
    extra_fields_fn=None,
) -> list:
    """通用相似资源检测（向量检索 + 阈值过滤 + 权限判断 + owner 信息）。

    :param search_fn: match_service.search_skills / search_operators 等
    :param model_cls: Skill / Operator 等 ORM 模型类
    :param permission_resource: "skill" / "operator" 等，用于 get_accessible_resource_ids
    :param extra_fields_fn: 可选 callable(obj) -> dict，补充类型特有字段
    :return: dict 列表（含 id/name/display_name/description/tags/similarity/can_use/owner_name/owner_email + extra）
    """
    from sqlalchemy import select as sa_select
    from app.models.user import User
    from app.services.permission_service import get_accessible_resource_ids

    matched = await search_fn(prompt, top_k=top_k)
    if not matched:
        return []

    shared_ids = await get_accessible_resource_ids(db, user_id, permission_resource)

    owner_cache: dict = {}
    items = []
    for rid, score in matched:
        if score < MATCH_THRESHOLD:
            continue
        result = await db.execute(sa_select(model_cls).where(model_cls.id == rid))
        obj = result.scalar_one_or_none()
        if not obj:
            continue
        can_use = (
            obj.created_by == user_id
            or obj.visibility == "public"
            or obj.id in shared_ids
        )
        owner_name = None
        owner_email = None
        if not can_use and obj.created_by:
            if obj.created_by not in owner_cache:
                user_result = await db.execute(sa_select(User).where(User.id == obj.created_by))
                owner_cache[obj.created_by] = user_result.scalar_one_or_none()
            owner = owner_cache[obj.created_by]
            if owner:
                owner_name = owner.display_name or owner.username
                owner_email = owner.email
        item = {
            "id": str(obj.id),
            "name": obj.name,
            "display_name": obj.display_name,
            "description": obj.description,
            "tags": obj.tags,
            "similarity": score,
            "can_use": can_use,
            "owner_name": owner_name,
            "owner_email": owner_email,
        }
        if extra_fields_fn:
            item.update(extra_fields_fn(obj))
        items.append(item)
    return items


async def search_tables(query: str, top_k: int = 3) -> List[Tuple[str, float]]:
    if not query or not query.strip():
        return []
    q_emb = await llm_manager.embed(query)
    res = _get_table_collection().query(
        query_embeddings=[q_emb],
        n_results=top_k,
    )
    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    out = []
    for i in range(len(ids)):
        if dists[i] is not None:
            score = round(1 - float(dists[i]), 4)
            meta = metas[i] if i < len(metas) else {}
            out.append((ids[i], score, meta))
    return out


# ---------- LLM 匹配（技能/流程/数据表，直接全列表给 LLM 判断）----------

async def llm_match_tables(
    user_message: str, db,
) -> Tuple[List[Tuple[str, float, dict]], List[str], List[Dict]]:
    """自适应 LLM 匹配数据表。返回 (result, ds_names, events)。

    先按数据源名过滤（字符串匹配），只把相关数据源的表给 LLM。
    - ds_names 非空 = 用户提到了数据源（即使没匹配到表）
    - ds_names 空 = 用户没提到数据源
    """
    from app.models.datasource import DataSource, TableMetadata
    from sqlalchemy import select

    _mlog(f"\n{'#'*60}")
    _mlog(f"# llm_match_tables 入口: user_message={user_message}")
    ds_rows = (await db.execute(select(DataSource))).scalars().all()
    ds_map = {str(ds.id): ds.name for ds in ds_rows}

    # 字符串匹配数据源名
    mentioned_ds_ids = set()
    mentioned_ds_names = []
    for ds in ds_rows:
        if ds.name and ds.name in user_message:
            mentioned_ds_ids.add(str(ds.id))
            mentioned_ds_names.append(ds.name)
            _mlog(f"# 匹配到数据源: {ds.name} -> {ds.id}")

    if not mentioned_ds_ids:
        _mlog(f"# 未匹配到数据源名，返回空")
        return [], [], []

    # 查这些数据源的表
    from uuid import UUID as _UUID
    table_metas = (await db.execute(
        select(TableMetadata).where(
            TableMetadata.data_source_id.in_([_UUID(d) for d in mentioned_ds_ids])
        )
    )).scalars().all()

    if not table_metas:
        _mlog(f"# 数据源中无表，返回空（数据源名已匹配）")
        return [], mentioned_ds_names, []

    id_to_meta = {}
    items = []
    for tm in table_metas:
        ds_name = ds_map.get(str(tm.data_source_id), "")
        col_names = [c["name"] for c in (tm.table_schema or []) if isinstance(c, dict) and c.get("name")]
        items.append({
            "id": str(tm.id),
            "name": f"{ds_name} → {tm.table_name}",
            "desc": f"{getattr(tm, 'business_description', '') or getattr(tm, 'business_name', '') or ''} {getattr(tm, 'business_purpose', '') or ''} 标签: {', '.join(getattr(tm, 'business_tags', []) or [])} 列: {', '.join(col_names[:10])}",
        })
        id_to_meta[str(tm.id)] = (tm, ds_name)

    matched, events = await _llm_match_items(user_message, items, match_type="table")
    result = []
    for mid, score in matched:
        tm, ds_name = id_to_meta.get(mid, (None, ""))
        if tm:
            result.append((mid, score, {
                "data_source_id": str(tm.data_source_id) if tm.data_source_id else "",
                "table_name": tm.table_name or "",
                "datasource_name": ds_name,
                "row_count": tm.row_count,
                "column_count": tm.column_count,
            }))
    return result, mentioned_ds_names, events


async def llm_match_skills(user_message: str, db, msg_type: str = "") -> Tuple[List[Tuple[str, float]], List[Dict]]:
    """用 LLM 判断用户消息匹配哪些技能。返回 (matched, events)。"""
    from app.models.skill import Skill
    from sqlalchemy import select
    skills = (await db.execute(select(Skill))).scalars().all()
    _mlog(f"\n{'#'*60}")
    _mlog(f"# llm_match_skills 入口: msg_type={msg_type} 技能数={len(skills)}")
    for s in skills:
        _mlog(f"#   技能: name={s.name} display={s.display_name} type={s.skill_type} vis={s.visibility}")
    if not skills:
        return [], []
    return await _llm_match_items(user_message, [
        {"id": str(s.id), "name": s.display_name or s.name or "", "desc": f"{s.description or ''} 标签: {', '.join(s.tags or [])}"} for s in skills
    ], msg_type)


async def llm_match_pipelines(user_message: str, db, msg_type: str = "") -> Tuple[List[Tuple[str, float]], List[Dict]]:
    """用 LLM 判断用户消息匹配哪些流程。返回 (matched, events)。"""
    from app.models.pipeline import Pipeline
    from sqlalchemy import select
    # 排除内置流程（平台维护类，不参与用户业务匹配）
    pipelines = (await db.execute(select(Pipeline).where(Pipeline.is_active == True, Pipeline.is_builtin == False))).scalars().all()
    _mlog(f"\n{'#'*60}")
    _mlog(f"# llm_match_pipelines 入口: msg_type={msg_type} 候选流程数={len(pipelines)} (已排除 is_builtin=True)")
    for p in pipelines:
        _mlog(f"#   流程: name={p.name} display={p.display_name} type={p.pipeline_type} builtin={p.is_builtin}")
    if not pipelines:
        return [], []
    return await _llm_match_items(user_message, [
        {"id": str(p.id), "name": p.display_name or p.name or "", "desc": f"{p.description or ''} 标签: {', '.join(p.tags or [])}"} for p in pipelines
    ], msg_type)


_PROMPT_LEN_THRESHOLD = 3000


async def _llm_parse_response(prompt: str, items: List[Dict], top_k: int = None, match_stage: str = "") -> Tuple[List[Tuple[str, float]], List[Dict]]:
    """底层：流式调 LLM 并解析返回的序号列表为 (id, 1.0)。
    返回 (matched, events)——events 供前端显示推理过程。"""
    events = []
    resp_text = ""
    _mlog(f"{'='*60}")
    _mlog(f"[stage={match_stage}] 候选数={len(items)}")
    _mlog(f"[prompt]:\n{prompt}")
    _mlog(f"[候选列表]:")
    for i, it in enumerate(items):
        _mlog(f"  {i}. id={it['id']} name={it.get('name','')} desc={it.get('desc','')[:200]}")
    try:
        async for event in llm_manager.chat_stream_with_thinking(
            messages=[{"role": "user", "content": prompt}],
            model=llm_manager._flash, temperature=0.0,
        ):
            events.append(event)
            if event.get("type") == "content":
                resp_text += event["content"]
        _mlog(f"[LLM 原始响应]: {resp_text}")
        resp = resp_text.strip().lower()
        if not resp or resp == "none":
            _mlog(f"[结果] 无匹配（resp={resp}）")
            return [], events
        matched = []
        for part in resp.replace("，", ",").split(","):
            part = part.strip().rstrip(".")
            if part.isdigit():
                idx = int(part)
                if 0 <= idx < len(items):
                    matched.append((items[idx]["id"], 1.0))
                    _mlog(f"  匹配: idx={idx} -> id={items[idx]['id']} name={items[idx].get('name','')}")
        if top_k:
            matched = matched[:top_k]
        _mlog(f"[最终匹配数]={len(matched)}")
        return matched, events
    except Exception as e:
        _mlog(f"[LLM 匹配失败]: {e}")
        events.append({"type": "error", "content": f"❌ 匹配失败: {e}"})
        return [], events


async def _llm_coarse_match(user_message: str, items: List[Dict], top_k: int = 20, msg_type: str = "") -> Tuple[List[Tuple[str, float]], List[Dict]]:
    """粗筛：只给项目名称，LLM 返回 top_k 个最相关 ID。返回 (matched, events)。"""
    item_list = "\n".join(f"{i}. {it['name']}" for i, it in enumerate(items))
    _type_hint = ""
    if msg_type == "analysis":
        _type_hint = "用户意图：只分析不修改\n"
    elif msg_type == "processing":
        _type_hint = "用户意图：数据处理\n"
    prompt = (
        f"用户消息：{user_message}\n\n"
        f"{_type_hint}"
        f"可选项目：\n{item_list}\n\n"
        f"返回最相关的 {top_k} 个项目的序号（逗号分隔），按相关程度从高到低排序，无匹配返回 none。不要解释。"
    )
    return await _llm_parse_response(prompt, items, top_k=top_k, match_stage="coarse")


async def _llm_fine_match(user_message: str, items: List[Dict], msg_type: str = "", match_type: str = "") -> Tuple[List[Tuple[str, float]], List[Dict]]:
    """精排：给项目名称+描述，LLM 返回所有匹配 ID（按匹配程度排序）。返回 (matched, events)。"""
    item_list = "\n".join(f"{i}. {it['name']} - {it['desc']}" for i, it in enumerate(items))
    _type_hint = ""
    if msg_type == "analysis":
        _type_hint = "用户意图：只分析不修改\n"
    elif msg_type == "processing":
        _type_hint = "用户意图：数据处理\n"
    _task_hint = ""
    if match_type == "table":
        _task_hint = "判断哪些表是用户想要查询或操作的数据表，根据表名、业务描述、标签和列名语义匹配。无匹配返回 none。\n"
    else:
        _task_hint = "判断哪些项目能完成用户的需求。无匹配返回 none。\n"
    prompt = (
        f"用户消息：{user_message}\n\n"
        f"{_type_hint}"
        f"{_task_hint}"
        f"可选项目：\n{item_list}\n\n"
        "返回所有匹配项目的序号（逗号分隔），按匹配程度从高到低排序，不要解释。"
    )
    return await _llm_parse_response(prompt, items, match_stage="fine")


async def _llm_match_items(user_message: str, items: List[Dict], msg_type: str = "", match_type: str = "") -> Tuple[List[Tuple[str, float]], List[Dict]]:
    """自适应匹配：item_list 短就一次精排，超阈值就粗筛→精排两阶段。
    返回 (matched, events)——events 供前端显示推理过程。"""
    if not items:
        return [], []
    item_list = "\n".join(f"{i}. {it['name']} - {it['desc']}" for i, it in enumerate(items))
    all_events = []
    if len(item_list) > _PROMPT_LEN_THRESHOLD:
        _mlog(f"[_llm_match_items] 走两阶段（粗筛→精排） item_list_len={len(item_list)} threshold={_PROMPT_LEN_THRESHOLD}")
        coarse_matched, coarse_events = await _llm_coarse_match(user_message, items, msg_type=msg_type)
        all_events.extend(coarse_events)
        coarse_ids = {mid for mid, _ in coarse_matched}
        fine_items = [it for it in items if it["id"] in coarse_ids]
        if not fine_items:
            _mlog(f"[_llm_match_items] 粗筛无结果，精排跳过")
            return [], all_events
        fine_matched, fine_events = await _llm_fine_match(user_message, fine_items, msg_type, match_type)
        all_events.extend(fine_events)
        return fine_matched, all_events
    _mlog(f"[_llm_match_items] 走一次精排 item_list_len={len(item_list)} threshold={_PROMPT_LEN_THRESHOLD}")
    fine_matched, fine_events = await _llm_fine_match(user_message, items, msg_type, match_type)
    all_events.extend(fine_events)
    return fine_matched, all_events


# ---------- 全量重建 ----------

async def rebuild_index(db):
    from app.models.skill import Skill
    from app.models.pipeline import Pipeline
    from app.models.operator import Operator
    from app.models.datasource import DataSource, TableMetadata
    from sqlalchemy import select

    logger.info("开始重建向量索引...")

    # embedding 健康检查：不可用则直接报错，避免静默吞掉索引失败
    try:
        await llm_manager.embed("健康检查")
    except Exception as e:
        raise RuntimeError(
            f"向量模型不可用，向量索引无法重建。"
            f"请在「系统设置-大模型管理」页面配置正确的向量模型（如 embedding-3）。"
            f"错误详情: {e}"
        ) from e

    for col in [_get_skill_collection(), _get_pipeline_collection(), _get_operator_collection(), _get_table_collection()]:
        try:
            existing = col.get()
            if existing and existing.get("ids"):
                col.delete(ids=existing["ids"])
        except Exception:
            pass

    ok = fail = 0

    skills = (await db.execute(select(Skill))).scalars().all()
    _ok = _fail = 0
    for s in skills:
        try:
            await index_skill(s, raise_on_error=True); _ok += 1
        except Exception:
            _fail += 1
    ok += _ok; fail += _fail
    logger.info(f"技能索引完成: {len(skills)} 条（成功 {_ok}，失败 {_fail}）")

    pipelines = (await db.execute(select(Pipeline).where(Pipeline.is_active == True))).scalars().all()
    _ok = _fail = 0
    for p in pipelines:
        try:
            await index_pipeline(p, db, raise_on_error=True); _ok += 1
        except Exception:
            _fail += 1
    ok += _ok; fail += _fail
    logger.info(f"流程索引完成: {len(pipelines)} 条（成功 {_ok}，失败 {_fail}）")

    operators = (await db.execute(select(Operator))).scalars().all()
    _ok = _fail = 0
    for o in operators:
        try:
            await index_operator(o, raise_on_error=True); _ok += 1
        except Exception:
            _fail += 1
    ok += _ok; fail += _fail
    logger.info(f"算子索引完成: {len(operators)} 条（成功 {_ok}，失败 {_fail}）")

    ds_map = {}
    ds_rows = (await db.execute(select(DataSource))).scalars().all()
    for ds in ds_rows:
        ds_map[str(ds.id)] = ds.name
    table_metas = (await db.execute(select(TableMetadata))).scalars().all()
    _ok = _fail = 0
    for tm in table_metas:
        ds_name = ds_map.get(str(tm.data_source_id), "")
        try:
            await index_table(tm, ds_name, raise_on_error=True); _ok += 1
        except Exception:
            _fail += 1
    ok += _ok; fail += _fail
    logger.info(f"数据表索引完成: {len(table_metas)} 条（成功 {_ok}，失败 {_fail}）")

    logger.info(f"向量索引重建完成：共成功 {ok} 条，失败 {fail} 条")
