import os
import json
import pandas as pd
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime


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
            try:
                result = future.result()
                results.append(result)
                log("info", f"  [{completed}/{total}] 帧 {frame['frame']} 分析完成 (时间戳: {frame['timestamp']:.1f}s)")
            except Exception as e:
                log("error", f"  [{completed}/{total}] 帧 {frame['frame']} 分析失败: {str(e)}")
                results.append({
                    "frame_number": frame["frame"],
                    "timestamp": round(frame["timestamp"], 1),
                    "image_path": frame["image_path"],
                    "analysis": f"帧分析失败: {str(e)}",
                    "video_name": video_name,
                })

    # 按帧号排序
    results.sort(key=lambda x: x["frame_number"])
    print(f"  所有帧分析完成，成功 {sum(1 for r in results if not r['analysis'].startswith('帧分析失败'))}/{len(results)}")

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

    result = llm_chat(
        prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=4000
    )

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

    summary = llm_chat(prompt, temperature=0.3, max_tokens=500)
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
# Step 7: 分批写入数据源
# ============================================================

def _write_records(
    records: List[Dict],
    datasource_name: str,
    table_name: str,
    if_table_exists: str,
    batch_size: int = 500
) -> None:
    """分批写入记录到数据源"""
    ds_id = get_datasource_id_by_name(datasource_name)
    if not ds_id:
        raise ValueError(f"找不到数据源: {datasource_name}")

    clearing_strategies = {"overwrite", "replace", "truncate", "delete_rows"}
    total = len(records)

    log("info", f"开始写入 {total} 条记录 → {datasource_name}.{table_name} (策略: {if_table_exists})")

    column_remarks = {
        "id": "记录ID",
        "video_name": "视频名称",
        "video_path": "视频路径",
        "video_duration": "视频时长(秒)",
        "video_resolution": "视频分辨率",
        "frame_count": "抽取帧数",
        "knowledge_point": "知识点标题",
        "category": "知识分类",
        "content": "知识详细内容",
        "importance": "重要程度",
        "chapter": "所属章节",
        "timestamp_ref": "视频时间戳",
        "video_summary": "视频整体摘要",
        "extracted_at": "提取时间",
    }

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        batch = records[i:i + batch_size]
        current_strategy = if_table_exists
        if batch_num > 1 and if_table_exists in clearing_strategies:
            current_strategy = "append"

        log("info", f"  写入第 {batch_num} 批 ({len(batch)} 条)")

        result = write_table_data(
            ds_id,
            table_name,
            records=batch,
            if_table_exists=current_strategy,
            table_remark="培训视频知识提取结果",
            column_remarks=column_remarks,
        )

        if not result.get("success"):
            raise ValueError(f"写入失败: {result.get('message', '未知错误')}")

    print(f"  写入完成: {total} 条记录 → {datasource_name}.{table_name}")


# ============================================================
# 主业务编排函数
# ============================================================

def extract_training_knowledge(
    video_path: str,
    datasource_name: str = "凭证检索库",
    table_name: str = "training_knowledge",
    max_frames: int = 8,
    if_table_exists: str = "replace",
    max_workers: int = 4,
    **kwargs
) -> Dict[str, Any]:
    """
    主业务函数：编排 视频抽帧 → 帧分析 → 语义提取 → 知识入库

    参数:
        video_path: 视频文件路径
        datasource_name: 输出数据源名称
        table_name: 输出表名
        max_frames: 最大抽取帧数
        if_table_exists: 写入策略
        max_workers: 帧分析并发数
    """

    # ---- 参数兼容映射 ----
    param_aliases = {
        "video_path": ["video_path", "video_file", "file_path", "path"],
        "datasource_name": ["datasource_name", "target_datasource", "target_datasource_name", "output_datasource"],
        "table_name": ["table_name", "target_table", "output_table"],
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
    datasource_name = resolved["datasource_name"]
    table_name = resolved["table_name"]
    max_frames = int(resolved["max_frames"])
    if_table_exists = resolved["if_table_exists"]
    max_workers = int(resolved["max_workers"])

    # ---- 校验参数 ----
    if not video_path:
        return {"success": False, "error": "缺少必填参数: video_path", "message": "请提供视频文件路径"}

    if not os.path.exists(video_path):
        return {"success": False, "error": f"视频文件不存在: {video_path}", "message": "请检查文件路径"}

    print("=" * 60)
    print(f"  培训视频知识提取")
    print(f"  视频: {video_path}")
    print(f"  输出: {datasource_name}.{table_name}")
    print(f"  最大帧数: {max_frames} | 并发数: {max_workers}")
    print("=" * 60)

    # ---- Step 1: 视频元数据 ----
    video_info = _extract_video_metadata(video_path)

    # ---- Step 2: 关键帧抽取 ----
    frames = _extract_keyframes(video_path, max_frames)

    # 提取视频名称
    video_name = os.path.basename(video_path)

    # ---- Step 3: 并发帧分析 ----
    frame_analyses = _analyze_frames_concurrent(frames, video_name, max_workers)

    # ---- Step 4: 语义聚合提取 ----
    knowledge_points = _semantic_extraction(frame_analyses, video_info, video_name)

    if not knowledge_points:
        return {
            "success": True,
            "message": "视频分析完成但未提取到有效知识点",
            "video_name": video_name,
            "frames_extracted": len(frames),
            "knowledge_points": 0,
        }

    # ---- Step 5: 生成视频摘要 ----
    summary = _generate_video_summary(knowledge_points, video_info, video_name)

    # ---- Step 6: 构建记录 ----
    records = _build_records(knowledge_points, frame_analyses, video_info, video_path, video_name, summary)

    # ---- Step 7: 写入数据源 ----
    _write_records(records, datasource_name, table_name, if_table_exists)

    # ---- 返回结果 ----
    result = {
        "success": True,
        "video_name": video_name,
        "video_path": video_path,
        "video_duration": round(video_info.get("duration", 0), 1),
        "video_resolution": f"{video_info.get('width', 0)}x{video_info.get('height', 0)}",
        "frames_extracted": len(frames),
        "frames_analyzed": len(frame_analyses),
        "knowledge_points_count": len(knowledge_points),
        "records_written": len(records),
        "target_datasource": datasource_name,
        "target_table": table_name,
        "video_summary": summary,
        "knowledge_summary": [
            {
                "knowledge_point": kp.get("knowledge_point", ""),
                "category": kp.get("category", ""),
                "importance": kp.get("importance", ""),
                "chapter": kp.get("chapter", ""),
            }
            for kp in knowledge_points[:15]
        ],
    }

    print("=" * 60)
    print(f"  处理完成!")
    print(f"  知识条目: {len(knowledge_points)} 条")
    print(f"  写入位置: {datasource_name}.{table_name}")
    print("=" * 60)

    return result


# ============================================================
# 入口函数
# ============================================================

def main(**params):
    """主入口，系统注入用户参数"""
    return extract_training_knowledge(**params)