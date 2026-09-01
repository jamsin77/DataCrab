import os
import json
import pandas as pd
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time


def _log_step(msg: str) -> None:
    """输出进度提示：print 立即 flush，避免长时间无输出被判超时"""
    log("info", msg)
    print(msg, flush=True)


# ============================================================
# Step 1: 视频元数据提取
# ============================================================

def _extract_video_metadata(video_path: str) -> Dict[str, Any]:
    """提取视频元数据（时长、分辨率、帧率等）"""
    log("info", f"开始提取视频元数据: {video_path}")

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    info = extract_video_info(video_path)
    duration = info.get("duration", 0)
    width = info.get("width", 0)
    height = info.get("height", 0)
    fps = info.get("fps", 0)
    total_frames = info.get("total_frames", 0)

    print(f"  时长: {duration:.1f}s | 分辨率: {width}x{height} | 帧率: {fps:.1f}fps | 总帧数: {total_frames}")

    if duration < 1:
        log("warn", f"视频时长过短 ({duration:.1f}s)，可能无法有效抽帧")

    return info


# ============================================================
# Step 2: 关键帧抽取
# ============================================================

def _extract_keyframes(video_path: str, max_frames: int = 8) -> List[Dict]:
    """抽取视频关键帧，返回帧信息列表"""
    log("info", f"开始抽取关键帧，最多 {max_frames} 帧")

    frames = extract_keyframes(video_path, max_frames=max_frames, method="auto")

    if not frames:
        raise RuntimeError("未能从视频中抽取任何关键帧，请检查视频文件格式和内容")

    print(f"  共抽取 {len(frames)} 个关键帧:")
    for f in frames:
        print(f"    帧 {f['frame']:>3d} | 时间戳 {f['timestamp']:>7.1f}s | {f['image_path']}")

    return frames


# ============================================================
# Step 3: 帧内容分析（并发）
# ============================================================

def _analyze_single_frame(frame: Dict, video_name: str) -> Dict[str, Any]:
    """分析单个关键帧：OCR文字提取 + 画面描述 + 知识点主题识别"""
    image_path = frame["image_path"]
    timestamp = frame["timestamp"]
    frame_num = frame["frame"]

    # 构造分析 prompt
    prompt = (
        "请仔细分析这张培训/教学视频截图，提取以下信息：\n\n"
        "1. 【文字内容】: 画面中所有可见文字（标题、正文、标注、表格数据、PPT要点等），按原始排版尽量完整还原\n"
        "2. 【画面描述】: 画面的主要视觉元素、图表、演示内容、操作步骤等\n"
        "3. 【知识点主题】: 这张图片在培训教学中传达的核心知识点或主题（一句话概括）\n"
        "4. 【关键术语】: 画面中出现的专业术语或关键词（逗号分隔）\n\n"
        "请严格按以下格式返回：\n"
        "【文字内容】:\n...\n\n"
        "【画面描述】:\n...\n\n"
        "【知识点主题】:\n...\n\n"
        "【关键术语】:\n..."
    )

    try:
        result = llm_vision(
            image_path,
            prompt,
            system_prompt=(
                "你是一个专业的培训内容分析专家，擅长从教学视频截图中精准提取文字、"
                "描述画面内容并识别培训知识点。请务必完整提取画面中的所有文字信息。"
            ),
            temperature=0.3,
            max_tokens=2000
        )
    except Exception as e:
        raise RuntimeError(
            f"LLM 帧分析调用失败（帧 {frame_num} @ {round(timestamp, 1)}s）: {e}"
        ) from e

    if not result or not str(result).strip():
        raise RuntimeError(f"LLM 帧分析返回空结果（帧 {frame_num} @ {round(timestamp, 1)}s）")

    return {
        "frame_number": frame_num,
        "timestamp": round(timestamp, 1),
        "image_path": image_path,
        "analysis": result,
        "video_name": video_name,
    }


def _analyze_frames_concurrent(
    frames: List[Dict],
    video_name: str,
    max_workers: int = 4
) -> List[Dict]:
    """并发分析所有关键帧"""
    worker_count = min(max_workers, len(frames))
    log("info", f"开始并发分析 {len(frames)} 个关键帧（并发数={worker_count}）")

    results: List[Dict] = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(_analyze_single_frame, frame, video_name): frame
            for frame in frames
        }

        completed = 0
        total = len(frames)
        for future in as_completed(future_map):
            frame = future_map[future]
            completed += 1
            # 不再吞掉 LLM 调用异常：future.result() 会重新抛出底层异常，
            # 让错误信息完整上抛，避免任务“假成功”后写入降级的占位内容。
            result = future.result()
            results.append(result)
            _log_step(f"  [{video_name}] 帧分析进度 {completed}/{total}（帧 {frame['frame']} @ {frame['timestamp']:.1f}s 完成）")

    # 按帧号排序
    results.sort(key=lambda x: x["frame_number"])
    print(f"  所有帧分析完成，成功 {len(results)}/{len(results)}")

    return results


# ============================================================
# Step 4: 语义聚合与知识提取
# ============================================================

def _semantic_extraction(
    frame_analyses: List[Dict],
    video_info: Dict[str, Any],
    video_name: str
) -> List[Dict]:
    """将所有帧分析结果送入大模型进行语义聚合，提取结构化知识条目"""

    log("info", "开始语义聚合与知识提取")

    # 拼接所有帧的分析文本
    frame_texts = []
    for fa in frame_analyses:
        frame_texts.append(
            f"=== 帧 {fa['frame_number']} (时间戳: {fa['timestamp']}s) ===\n{fa['analysis']}"
        )
    combined_text = "\n\n".join(frame_texts)

    duration = video_info.get("duration", 0)

    system_prompt = (
        "你是一个专业的培训知识管理专家。你的任务是从培训视频的多个关键帧分析结果中，"
        "提取、整合并结构化培训知识点。要求：\n"
        "1. 识别视频中的核心培训主题和章节结构\n"
        "2. 将分散在各帧中的信息整合为连贯的知识点\n"
        "3. 去除重复信息，合并相关内容\n"
        "4. 为每个知识点标注重要程度（高/中/低）和所属章节\n"
        "5. 内容应详实、准确，保留关键数据和操作步骤\n"
        "6. 如果某些帧内容重复或相似，合并为一个知识点\n\n"
        "请严格以JSON数组格式输出，不要包含其他文字。每个元素格式：\n"
        '{"knowledge_point": "知识点标题", "category": "知识分类", '
        '"content": "详细内容（保留关键数据和步骤）", "importance": "高/中/低", '
        '"chapter": "所属章节", "timestamp": "对应视频时间戳（秒）"}'
    )

    prompt = (
        f"培训视频名称: {video_name}\n"
        f"视频时长: {duration:.1f}秒\n"
        f"视频分辨率: {video_info.get('width', 0)}x{video_info.get('height', 0)}\n\n"
        f"以下是 {len(frame_analyses)} 个关键帧的分析结果：\n\n"
        f"{combined_text}\n\n"
        f"请从以上内容中提取结构化的培训知识点，以JSON数组格式返回。"
        f"确保每个知识点内容详实、独立可用。"
    )

    # LLM 偶发返回空结果，加入重试机制；重试后仍空则降级返回空列表（由外层跳过该视频）
    max_retries = 3
    result = None
    for attempt in range(1, max_retries + 1):
        try:
            result = llm_chat(
                prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=4000
            )
        except Exception as e:
            result = None
            log("warn", f"LLM 语义聚合第 {attempt} 次调用异常: {e}")
        if result and str(result).strip():
            break
        log("warn", f"LLM 语义聚合第 {attempt} 次未返回有效结果")
        if attempt < max_retries:
            time.sleep(2)

    if not result or not str(result).strip():
        log("warn", "LLM 语义聚合多次未返回有效结果，降级为无知识条目（该视频将被跳过）")
        return []

    # 解析 JSON 结果
    knowledge_points = _parse_knowledge_json(result)

    print(f"  语义提取完成，共生成 {len(knowledge_points)} 个知识条目")
    for i, kp in enumerate(knowledge_points):
        print(f"    [{i+1}] {kp.get('knowledge_point', 'N/A')} (重要度: {kp.get('importance', 'N/A')}, 章节: {kp.get('chapter', 'N/A')})")

    return knowledge_points


def _parse_knowledge_json(raw_text: str) -> List[Dict]:
    """解析大模型返回的JSON知识条目，容错处理"""
    text = raw_text.strip()

    # 尝试提取 JSON 数组
    start = text.find('[')
    end = text.rfind(']')

    if start != -1 and end != -1:
        json_str = text[start:end + 1]
        try:
            points = json.loads(json_str)
            if isinstance(points, list):
                return points
        except json.JSONDecodeError as e:
            log("warn", f"JSON解析失败: {str(e)}，尝试修复")

            # 尝试修复常见JSON问题（尾逗号等）
            import re
            fixed = re.sub(r',\s*]', ']', json_str)
            fixed = re.sub(r',\s*}', '}', fixed)
            try:
                points = json.loads(fixed)
                if isinstance(points, list):
                    log("info", "JSON修复成功")
                    return points
            except json.JSONDecodeError:
                pass

    # 如果无法解析，将整个结果作为一条知识
    log("warn", "无法解析为JSON数组，将原始文本作为单条知识保存")
    return [{
        "knowledge_point": "综合培训内容（未结构化）",
        "category": "通用",
        "content": raw_text,
        "importance": "中",
        "chapter": "整体",
        "timestamp": "0",
    }]


# ============================================================
# Step 5: 生成视频整体摘要
# ============================================================

def _generate_video_summary(
    knowledge_points: List[Dict],
    video_info: Dict[str, Any],
    video_name: str
) -> str:
    """生成培训视频的整体摘要"""
    log("info", "生成视频整体摘要")

    kp_titles = [f"- {kp.get('knowledge_point', '')} ({kp.get('importance', '')})" for kp in knowledge_points]
    kp_list = "\n".join(kp_titles)

    prompt = (
        f"培训视频: {video_name}\n"
        f"时长: {video_info.get('duration', 0):.1f}秒\n"
        f"提取的知识点列表:\n{kp_list}\n\n"
        f"请用2-3句话概括这个培训视频的核心内容和培训目标。"
    )

    try:
        summary = llm_chat(prompt, temperature=0.3, max_tokens=500)
    except Exception as e:
        raise RuntimeError(f"LLM 摘要生成调用失败: {e}") from e

    if not summary or not str(summary).strip():
        raise RuntimeError("LLM 摘要生成返回空结果")

    print(f"  摘要: {summary[:100]}...")
    return summary


# ============================================================
# Step 6: 构建入库记录
# ============================================================

def _build_records(
    knowledge_points: List[Dict],
    frame_analyses: List[Dict],
    video_info: Dict[str, Any],
    video_path: str,
    video_name: str,
    summary: str = ""
) -> List[Dict]:
    """构建写入数据库的记录列表"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_id = datetime.now().strftime("%Y%m%d%H%M%S")
    duration = video_info.get("duration", 0)
    resolution = f"{video_info.get('width', 0)}x{video_info.get('height', 0)}"

    records = []
    for i, kp in enumerate(knowledge_points):
        record = {
            "id": f"{now_id}_{i + 1:04d}",
            "video_name": video_name,
            "video_path": video_path,
            "video_duration": round(duration, 1),
            "video_resolution": resolution,
            "frame_count": len(frame_analyses),
            "knowledge_point": kp.get("knowledge_point", ""),
            "category": kp.get("category", ""),
            "content": kp.get("content", ""),
            "importance": kp.get("importance", "中"),
            "chapter": kp.get("chapter", ""),
            "timestamp_ref": str(kp.get("timestamp", "")),
            "video_summary": summary,
            "extracted_at": now,
        }
        records.append(record)

    return records


# ============================================================
# Step 7: 知识写入知识库（Chroma 向量库）
# ============================================================

def _build_chroma_records(
    knowledge_points: List[Dict],
    video_name: str,
    video_info: Dict[str, Any],
    summary: str = "",
) -> List[Dict]:
    """将知识点构建为 Chroma 向量库可写入的 records。

    Chroma 连接器的 write_table_data 只识别每条记录中的
    `id` / `document`(或 text) / `metadata`(或 metadatas) / `embedding` 字段。
    document 是向量化与语义检索的主体文本，metadata 承载结构化属性。
    """
    duration = video_info.get("duration", 0)
    resolution = f"{video_info.get('width', 0)}x{video_info.get('height', 0)}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    video_stem = os.path.splitext(os.path.basename(video_name))[0]

    records = []
    for i, kp in enumerate(knowledge_points):
        title = (kp.get("knowledge_point") or "").strip() or "未命名知识点"
        category = (kp.get("category") or "").strip() or "通用"
        content = (kp.get("content") or "").strip()
        importance = (kp.get("importance") or "").strip() or "中"
        chapter = (kp.get("chapter") or "").strip() or "整体"
        timestamp = str(kp.get("timestamp") or "").strip()

        # document：知识正文 + 结构化元信息（供向量检索命中）
        doc_parts = [f"# {title}"]
        doc_parts.append(f"章节: {chapter} | 分类: {category} | 重要度: {importance}")
        if timestamp:
            doc_parts.append(f"视频时间戳: {timestamp}s")
        doc_parts.append("")
        doc_parts.append(content)
        document = "\n".join(doc_parts)

        records.append({
            "id": f"{video_stem}_{i + 1:04d}",
            "document": document,
            "metadata": {
                "video_name": video_name,
                "video_duration": round(duration, 1),
                "video_resolution": resolution,
                "knowledge_point": title,
                "category": category,
                "importance": importance,
                "chapter": chapter,
                "timestamp": timestamp,
                "source": "training_video",
                "extracted_at": now,
                "video_summary": summary or "",
            },
        })
    return records


def _sanitize_collection_name(name: str) -> str:
    """将用户输入的集合名规范化为 Chroma 合法的 name。

    Chroma 要求 name 为 3-512 字符、字符集 [a-zA-Z0-9._-]，
    且首尾必须是 [a-zA-Z0-9]。中文集合名（如「知识库」）会导致 HTTP 500。
    处理策略：内置中文映射 → ASCII 清理 → hash 兜底。
    """
    import hashlib
    import re

    if not name or not str(name).strip():
        raise ValueError("集合名不能为空")

    raw = str(name).strip()

    # 1) 内置常见中文名映射（确定性、可读）
    _NAME_MAP = {
        "知识库": "knowledge_base",
        "培训知识库": "training_knowledge_base",
        "银行培训": "bank_training",
        "银行培训知识": "bank_training_knowledge",
    }
    if raw in _NAME_MAP:
        sanitized = _NAME_MAP[raw]
        _log_step(f"[写入] 集合名规范化: {name} → {sanitized}")
        return sanitized

    # 2) 保留 [a-zA-Z0-9._-]，其余字符替换为下划线
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw)
    sanitized = sanitized.strip("._-")

    # 3) 全部被清理成空（如纯中文未命中映射）→ hash 兜底
    if not sanitized:
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
        sanitized = f"kb_{digest}"
    elif len(sanitized) < 3:
        sanitized = f"kb_{sanitized}"

    # 4) 超长截断到 512，并确保末尾合法
    if len(sanitized) > 512:
        sanitized = sanitized[:512].rstrip("._-")

    _log_step(f"[写入] 集合名规范化: {name} → {sanitized}")
    return sanitized


def _get_datasource_connection_config(datasource_name: str):
    """通过内部 API 获取数据源的 connection_config（用于读取 chroma 持久化目录等）。

    沙箱内脚本无法直接拿到数据源配置，get_datasource_id_by_name 只返回 UUID，
    因此这里复刻 _discover_video_files 的做法，用内部无认证接口拉取完整配置。
    """
    import urllib.request
    _base = os.environ.get("DATACRAB_API_BASE", "http://localhost:8000")
    url = f"{_base}/api/v1/datasources/internal/datasources"
    with urllib.request.urlopen(url, timeout=30) as resp:
        _all = json.loads(resp.read().decode("utf-8"))
    for s in _all:
        if s.get("name") == datasource_name:
            cfg = s.get("connection_config") or {}
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except Exception:
                    cfg = {}
            return s, cfg
    return None, {}


def _delete_existing_knowledge(
    datasource_name: str,
    collection_name: str,
    video_names: List[str],
) -> int:
    """删除向量库中与本次视频同名的旧知识条目，实现「覆盖」而非累积。

    后端 Chroma 连接器的 write_table_data 只做 upsert，没有删除入口；当同一视频
    重新分析后知识条数变化或 id 变化时，历史条目会残留。这里直接通过 chromadb
    客户端按 metadata.video_name 精确删除旧条目（沙箱与后端同 Python 环境，已装 chromadb）。
    """
    import chromadb

    if not video_names:
        return 0

    _ds, cfg = _get_datasource_connection_config(datasource_name)
    persist_dir = cfg.get("persist_directory") or cfg.get("path") or "d:/chroma-data"
    if not persist_dir or not os.path.isdir(persist_dir):
        log("warn", f"[覆盖历史] chroma 数据目录不存在，跳过删除: {persist_dir}")
        return 0

    client = chromadb.PersistentClient(path=persist_dir)
    try:
        col = client.get_collection(collection_name)
    except Exception:
        _log_step(f"[覆盖历史] 集合 {collection_name} 尚不存在，无需删除")
        return 0

    before = col.count()
    failed = []
    for vn in video_names:
        try:
            col.delete(where={"video_name": vn})
        except Exception as e:
            failed.append(f"{vn}: {e}")
    if failed:
        raise RuntimeError(
            f"删除集合 {collection_name} 历史知识失败: {'; '.join(failed)}"
        )
    after = col.count()
    deleted = max(0, before - after)
    _log_step(f"[覆盖历史] 已删除 {deleted} 条旧知识条目（涉及视频 {len(video_names)} 个）")
    return deleted


def _write_to_chroma(
    records: List[Dict],
    datasource_name: str,
    collection_name: str,
    batch_size: int = 100,
    video_names: Optional[List[str]] = None,
) -> None:
    """写入知识条目到 Chroma 向量库集合。

    注意：Chroma 连接器内部走 upsert，且其 write_table_data 签名只接受
    (table, records)，不能传 if_table_exists / table_remark / column_remarks，
    否则会因连接器不接受 kwargs 而报错。
    """
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        raise ValueError(f"找不到数据源: {datasource_name}")

    # Chroma 集合名仅接受 [a-zA-Z0-9._-]，中文名会触发 HTTP 500，先规范化
    collection_name = _sanitize_collection_name(collection_name)

    # 覆盖历史：同一视频重新分析时，先删除该视频旧知识条目，再 upsert 新条目，
    # 避免知识条数变化或 id 变化导致历史数据累积残留。
    if video_names:
        _delete_existing_knowledge(datasource_name, collection_name, video_names)

    total = len(records)
    _log_step(f"[写入] 开始写入 {total} 条知识条目 → {datasource_name}.{collection_name} (Chroma upsert)")
    total_batches = (total + batch_size - 1) // batch_size

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        _log_step(f"[写入] 批次 {batch_num}/{total_batches} ({len(batch)} 条)")
        result = write_table_data(ds_id, collection_name, records=batch)
        if not result.get("success"):
            raise ValueError(f"写入失败: {result.get('message', '未知错误')}")

    print(f"  写入完成: {total} 条知识条目 → {datasource_name}.{collection_name}", flush=True)


# ============================================================
# 主业务编排函数
# ============================================================

def _nested_config_path(ds: Dict[str, Any], keys, default=None):
    """从数据源的 connection_config（可能嵌套）里按顺序取第一个存在的值。"""
    if not isinstance(ds, dict):
        return default
    cfg = ds.get("connection_config")
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    if not isinstance(cfg, dict):
        cfg = ds  # 兜底：直接在数据源字典上找
    for k in keys:
        v = cfg.get(k)
        if v:
            return v
    return default


def _discover_video_files(video_datasource: str) -> List[str]:
    """从视频数据源（generic_file）中发现视频文件路径列表。

    覆盖三种常见的 connection_config 结构：目录 path、多文件 file_paths、
    单文件 file_path；同时用 list_tables 兜底（对文件型数据源会返回表名/文件名）。
    """
    VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv",
                  ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"}

    _log_step(f"[1/5] 获取视频数据源信息: {video_datasource}")
    ds_id = get_datasource_id_by_name(video_datasource)
    if not ds_id:
        raise ValueError(f"找不到视频数据源: {video_datasource}")

    # 通过内部接口拿完整数据源信息（含 connection_config）
    ds_info = None
    try:
        import urllib.request as _ureq
        _url = f"{os.environ.get('DATACRAB_API_BASE', 'http://localhost:8000')}/api/v1/datasources/internal/datasources"
        with _ureq.urlopen(_url, timeout=10) as _resp:
            _all = json.loads(_resp.read().decode("utf-8"))
        for s in _all:
            if s.get("name") == video_datasource or s.get("id") == ds_id:
                ds_info = s
                break
    except Exception as e:
        log("warn", f"无法获取视频数据源配置详情: {e}")

    candidates: List[str] = []

    if ds_info:
        path = _nested_config_path(ds_info, ["path", "folder_path", "file_path", "directory"])
        if path:
            if os.path.isfile(path):
                candidates.append(path)
            elif os.path.isdir(path):
                try:
                    for _f in sorted(os.listdir(path)):
                        _full = os.path.join(path, _f)
                        if os.path.isfile(_full) and os.path.splitext(_full)[1].lower() in VIDEO_EXTS:
                            candidates.append(_full)
                except OSError as e:
                    log("warn", f"读取视频目录失败: {e}")
        fps = _nested_config_path(ds_info, ["file_paths"], [])
        if isinstance(fps, list):
            for _f in fps:
                if _f and os.path.isfile(_f) and os.path.splitext(_f)[1].lower() in VIDEO_EXTS:
                    candidates.append(_f)

    # 兜底：list_tables 返回的文件名
    try:
        tables = list_tables(video_datasource) or []
        for _t in tables:
            _name = _t.get("table_name", _t) if isinstance(_t, dict) else str(_t)
            if _name and os.path.splitext(_name)[1].lower() in VIDEO_EXTS:
                if os.path.isfile(_name):
                    candidates.append(_name)
                else:
                    # 只拿到文件名时，尝试拼接配置目录
                    if ds_info:
                        _dir = _nested_config_path(ds_info, ["path", "folder_path", "file_path", "directory"])
                        if _dir and os.path.isdir(_dir):
                            _full = os.path.join(_dir, _name)
                            if os.path.isfile(_full):
                                candidates.append(_full)
    except Exception as e:
        log("warn", f"list_tables 视频发现失败: {e}")

    # 去重（保持顺序）
    seen = set()
    out = []
    for c in candidates:
        c = os.path.abspath(c)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _process_single_video(
    vp: str,
    max_frames: int,
    max_workers: int,
) -> Dict[str, Any]:
    """处理单个视频：每一步都带进度提示，失败返回 error 而非抛异常（由外层统一决定是否退出）。

    返回 dict：
        - success=True 时含 video_name/video_path/frames_extracted/knowledge_points/records/summary
        - success=False 时含 video_name/video_path/error
    """
    video_name = os.path.basename(vp)
    print(f"\n>>> 开始处理视频: {video_name}", flush=True)

    # Step 1：视频元数据
    _log_step(f"[{video_name}] 步骤1/7 提取视频元数据")
    try:
        video_info = _extract_video_metadata(vp)
    except Exception as e:
        log("warn", f"视频 {video_name} 元数据提取失败，跳过: {e}")
        return {"success": False, "video_name": video_name, "video_path": vp, "error": f"元数据提取失败: {e}"}

    # Step 2：关键帧抽取
    _log_step(f"[{video_name}] 步骤2/7 抽取关键帧 (最多 {max_frames} 帧)")
    try:
        frames = _extract_keyframes(vp, max_frames)
    except Exception as e:
        log("warn", f"视频 {video_name} 抽帧失败，跳过: {e}")
        return {"success": False, "video_name": video_name, "video_path": vp, "error": f"抽帧失败: {e}"}

    # Step 3：并发帧分析
    _log_step(f"[{video_name}] 步骤3/7 帧内容分析 (共 {len(frames)} 帧，并发 {max_workers})")
    try:
        frame_analyses = _analyze_frames_concurrent(frames, video_name, max_workers)
    except Exception as e:
        log("warn", f"视频 {video_name} 帧分析失败，跳过: {e}")
        return {"success": False, "video_name": video_name, "video_path": vp, "error": f"帧分析失败: {e}"}

    # Step 4：语义聚合提取
    _log_step(f"[{video_name}] 步骤4/7 语义聚合提取知识点")
    knowledge_points = _semantic_extraction(frame_analyses, video_info, video_name)
    if not knowledge_points:
        log("warn", f"视频 {video_name} 未提取到有效知识点，跳过")
        return {"success": False, "video_name": video_name, "video_path": vp, "error": "未提取到有效知识点"}

    # Step 5：生成视频摘要
    _log_step(f"[{video_name}] 步骤5/7 生成视频摘要")
    try:
        summary = _generate_video_summary(knowledge_points, video_info, video_name)
    except Exception as e:
        log("warn", f"视频 {video_name} 摘要生成失败，跳过: {e}")
        return {"success": False, "video_name": video_name, "video_path": vp, "error": f"摘要生成失败: {e}"}

    # Step 6：构建入库记录
    _log_step(f"[{video_name}] 步骤6/7 构建知识记录 (共 {len(knowledge_points)} 条)")
    # Chroma 只识别 id/document/metadata，必须用带 document 正文的构建函数
    # （_build_records 是宽表结构，会导致 document 为空）
    records = _build_chroma_records(knowledge_points, video_name, video_info, summary)

    print(f">>> 视频 {video_name} 处理完成: {len(knowledge_points)} 个知识点，{len(records)} 条记录", flush=True)
    return {
        "success": True,
        "video_name": video_name,
        "video_path": vp,
        "frames_extracted": len(frames),
        "knowledge_points": len(knowledge_points),
        "knowledge_point_list": knowledge_points,
        "records": records,
        "summary": summary,
    }


def extract_training_knowledge(
    video_path: str = None,
    video_datasource: str = "培训视频",
    datasource_name: str = "培训知识库",
    table_name: str = "bank_training_knowledge",
    max_frames: int = 8,
    if_table_exists: str = "replace",
    max_workers: int = 4,
    **kwargs
) -> Dict[str, Any]:
    """
    主业务函数：编排 视频发现/抽帧 → 帧分析 → 语义提取 → 知识入库

    参数:
        video_path: 视频文件路径（可选；未提供时从 video_datasource 数据源中发现）
        video_datasource: 视频来源数据源名称（generic_file，默认“培训视频”）
        datasource_name: 输出知识库数据源名称（chroma，默认“培训知识库”）
        table_name: 知识库集合名（chroma collection）
        max_frames: 每个视频最大抽取帧数
        if_table_exists: 写入策略（chroma 恒为 upsert，此参数保留兼容）
        max_workers: 帧分析并发数
    """

    # ---- 参数兼容映射 ----
    param_aliases = {
        "video_path": ["video_path", "video_file", "file_path", "path"],
        "video_datasource": ["video_datasource", "source_datasource", "video_source"],
        "datasource_name": ["datasource_name", "target_datasource", "target_datasource_name", "output_datasource", "knowledge_base"],
        "table_name": ["table_name", "target_table", "output_table", "collection", "collection_name"],
        "max_frames": ["max_frames", "frame_count", "frames"],
        "if_table_exists": ["if_table_exists", "write_strategy"],
        "max_workers": ["max_workers", "workers", "concurrency"],
    }

    resolved = {}
    for canonical, aliases in param_aliases.items():
        for alias in aliases:
            if alias in kwargs and kwargs[alias] is not None:
                resolved[canonical] = kwargs[alias]
                break
        if canonical not in resolved:
            resolved[canonical] = locals()[canonical]

    video_path = resolved["video_path"]
    video_datasource = resolved["video_datasource"]
    datasource_name = resolved["datasource_name"]
    table_name = resolved["table_name"]
    max_frames = int(resolved["max_frames"])
    if_table_exists = resolved["if_table_exists"]
    max_workers = int(resolved["max_workers"])

    # ---- 视频来源解析：优先显式路径，否则从数据源发现 ----
    # video_path 可能是完整路径、纯文件名（关键词）或 None；
    # 完整存在的路径直接使用，其余情况都走数据源发现，再按名称关键词过滤。
    video_paths: List[str] = []
    if video_path and os.path.exists(video_path):
        video_paths = [video_path]
    else:
        if not video_datasource:
            return {"success": False, "error": "缺少视频来源：请提供 video_path 或 video_datasource", "message": "请指定视频文件路径或视频数据源"}
        try:
            video_paths = _discover_video_files(video_datasource)
        except Exception as e:
            return {"success": False, "error": f"视频发现失败: {e}", "message": f"无法从数据源 {video_datasource} 发现视频文件"}
        # video_path 为纯文件名/关键词时，按名称匹配过滤（如“银行培训”匹配含该关键词的文件）
        if video_path and video_paths:
            _kw = os.path.basename(video_path).lower()
            _matched = [p for p in video_paths if _kw in os.path.basename(p).lower()]
            if _matched:
                video_paths = _matched
            else:
                return {"success": False, "error": f"数据源 {video_datasource} 中未找到匹配视频: {video_path}", "message": "请检查视频文件名"}

    if not video_paths:
        return {"success": False, "error": "未发现任何视频文件", "message": f"数据源 {video_datasource} 中未发现视频文件"}

    print("=" * 60)
    print(f"  培训视频知识提取")
    print(f"  视频来源: {video_datasource or '直接路径'}")
    print(f"  视频数量: {len(video_paths)}")
    print(f"  输出: {datasource_name}.{table_name}")
    print(f"  最大帧数: {max_frames} | 并发数: {max_workers}")
    print("=" * 60)
    for i, vp in enumerate(video_paths):
        print(f"    [{i + 1}] {vp}")

    # ---- 并发处理多个视频：单视频失败仅记录 error，全部失败才抛异常退出 ----
    all_records: List[Dict] = []
    all_knowledge_summary: List[Dict] = []
    processed_videos: List[Dict] = []
    failed_videos: List[Dict] = []

    video_count = len(video_paths)
    # 视频级并发：不高于视频数量和帧分析并发数，避免 LLM/抽帧同时打满
    video_workers = min(max(1, max_workers // 2), video_count)
    _log_step(f"[2/5] 并发处理 {video_count} 个视频（视频并发数={video_workers}，帧内并发={max_workers}）")

    with ThreadPoolExecutor(max_workers=video_workers) as executor:
        future_map = {
            executor.submit(_process_single_video, vp, max_frames, max_workers): vp
            for vp in video_paths
        }
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            vp = future_map[future]
            video_name = os.path.basename(vp)
            try:
                res = future.result()
            except Exception as e:
                res = {"success": False, "video_name": video_name, "video_path": vp, "error": str(e)}

            _log_step(f"[{completed}/{video_count}] 视频 {video_name} 并发任务结束")

            if res.get("success"):
                all_records.extend(res["records"])
                _kp_list = res.get("knowledge_point_list", [])
                for kp in _kp_list:
                    all_knowledge_summary.append({
                        "video_name": video_name,
                        "knowledge_point": kp.get("knowledge_point", ""),
                        "category": kp.get("category", ""),
                        "importance": kp.get("importance", ""),
                        "chapter": kp.get("chapter", ""),
                    })
                processed_videos.append({
                    "video_name": video_name,
                    "video_path": vp,
                    "frames_extracted": res.get("frames_extracted", 0),
                    "knowledge_points": res.get("knowledge_points", 0),
                })
            else:
                failed_videos.append({
                    "video_name": video_name,
                    "video_path": vp,
                    "error": res.get("error", "未知错误"),
                })

    # 所有视频均处理失败才抛异常退出
    if not processed_videos:
        _errs = "; ".join(f"{f['video_name']}: {f['error']}" for f in failed_videos)
        raise RuntimeError(f"所有视频均处理失败: {_errs or '未知原因'}")

    # ---- Step 7: 写入数据源（先删除同名视频历史知识，再 upsert 新知识）----
    _log_step(f"[3/5] 写入 {len(all_records)} 条知识条目 → {datasource_name}.{table_name}")
    _video_names = [v["video_name"] for v in processed_videos]
    _write_to_chroma(all_records, datasource_name, table_name, video_names=_video_names)

    # ---- 返回结果 ----
    total_frames = sum(v["frames_extracted"] for v in processed_videos)
    total_kp = sum(v["knowledge_points"] for v in processed_videos)

    result = {
        "success": True,
        "videos_total": len(video_paths),
        "videos_processed": len(processed_videos),
        "videos_failed": len(failed_videos),
        "processed_videos": processed_videos,
        "failed_videos": failed_videos,
        "frames_extracted": total_frames,
        "knowledge_points_count": total_kp,
        "records_written": len(all_records),
        "target_datasource": datasource_name,
        "target_table": table_name,
        "knowledge_summary": all_knowledge_summary[:15],
    }

    print("=" * 60)
    print(f"  处理完成!")
    print(f"  成功 {len(processed_videos)}/{len(video_paths)} 个视频，失败 {len(failed_videos)} 个")
    print(f"  知识条目: {total_kp} 条 | 写入记录: {len(all_records)} 条")
    print(f"  写入位置: {datasource_name}.{table_name}")
    print("=" * 60)

    return result


# ============================================================
# 入口函数
# ============================================================

def main(**params):
    """主入口，系统注入用户参数"""
    return extract_training_knowledge(**params)