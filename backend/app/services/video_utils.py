"""视频处理工具：元数据提取 + 关键帧抽取

优先使用 ffmpeg/ffprobe（工业级稳定），不可用时回退 opencv-python。
抽出的关键帧图片可直接传给 llm_vision 做内容理解。
"""

import json
import shutil
import subprocess
from pathlib import Path

_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"}


def _has_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def is_video_file(path: str) -> bool:
    return Path(path).suffix.lower() in _VIDEO_EXTS


def probe_video(video_path: str) -> dict:
    """提取视频元数据。

    优先 ffprobe（信息最全），回退 opencv（基本元数据）。
    返回 dict:
        duration: float (秒)
        width: int
        height: int
        fps: float
        codec: str | None
        bit_rate: int | None
        size: int (字节)
        total_frames: int | None
        audio: dict | None  (codec, sample_rate, channels)
    """
    p = Path(video_path)
    if not p.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    size = p.stat().st_size

    if _has_ffprobe():
        return _probe_with_ffprobe(str(p), size)

    return _probe_with_opencv(str(p), size)


def _probe_with_ffprobe(video_path: str, size: int) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr[:500]}")

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(fmt.get("duration") or v_stream.get("duration") or 0)
    width = int(v_stream.get("width", 0))
    height = int(v_stream.get("height", 0))

    fps_raw = v_stream.get("avg_frame_rate") or v_stream.get("r_frame_rate") or "0/1"
    fps = _parse_fps(fps_raw)

    bit_rate = int(fmt.get("bit_rate") or v_stream.get("bit_rate") or 0) or None

    audio = None
    if a_stream:
        audio = {
            "codec": a_stream.get("codec_name"),
            "sample_rate": int(a_stream.get("sample_rate", 0)) or None,
            "channels": int(a_stream.get("channels", 0)) or None,
        }

    return {
        "duration": round(duration, 2),
        "width": width,
        "height": height,
        "fps": round(fps, 2),
        "codec": v_stream.get("codec_name"),
        "bit_rate": bit_rate,
        "size": size,
        "total_frames": int(duration * fps) if fps > 0 else None,
        "audio": audio,
    }


def _probe_with_opencv(video_path: str, size: int) -> dict:
    try:
        import cv2
    except ImportError:
        raise RuntimeError(
            "环境问题：ffprobe 不可用且 opencv-python 未安装，无法提取视频信息。"
            "请安装 ffmpeg 或 opencv-python（pip install opencv-python-headless）。"
        )

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = total_frames / fps if fps > 0 else 0

        return {
            "duration": round(duration, 2),
            "width": width,
            "height": height,
            "fps": round(fps, 2),
            "codec": None,
            "bit_rate": None,
            "size": size,
            "total_frames": total_frames or None,
            "audio": None,
        }
    finally:
        cap.release()


def _parse_fps(fps_raw: str) -> float:
    try:
        num, den = fps_raw.split("/")
        den = float(den)
        return float(num) / den if den != 0 else 0
    except (ValueError, ZeroDivisionError):
        return 0


def extract_keyframes(
    video_path: str,
    max_frames: int = 8,
    output_dir: str | None = None,
    method: str = "auto",
) -> list[dict]:
    """抽取视频关键帧，输出为 JPEG 图片文件。

    Args:
        video_path: 视频文件路径
        max_frames: 最多抽取帧数（默认 8）
        output_dir: 输出目录（默认在视频同目录下建 _keyframes 子目录）
        method: "auto"（场景检测+等间隔补充）或 "interval"（纯等间隔）

    Returns:
        [{"frame": 1, "timestamp": 2.5, "image_path": "/path/to/frame_001.jpg"}, ...]

    抽出的帧图片可直接传给 llm_vision 做内容理解。
    """
    p = Path(video_path)
    if not p.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    if output_dir:
        out = Path(output_dir)
    else:
        out = p.parent / f"{p.stem}_keyframes"
    out.mkdir(parents=True, exist_ok=True)

    if method == "auto" and _has_ffmpeg():
        frames = _extract_with_ffmpeg_scene(str(p), str(out), max_frames)
        if len(frames) < max_frames:
            frames = _extract_with_opencv_interval(str(p), str(out), max_frames)
    else:
        frames = _extract_with_opencv_interval(str(p), str(out), max_frames)

    if len(frames) > max_frames:
        frames = frames[:max_frames]

    return frames


def _extract_with_ffmpeg_scene(
    video_path: str, output_dir: str, max_frames: int
) -> list[dict]:
    """用 ffmpeg 场景检测抽关键帧（scene change > 0.3）。"""
    import re

    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"select='gt(scene,0.3)',showinfo",
        "-vsync", "vfr",
        "-q:v", "2",
        "-frame_pts", "true",
        f"{output_dir}/scene_%04d.jpg",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    # 解析 showinfo 中的 pts_time（时间戳）
    timestamps = []
    for m in re.finditer(r"pts_time:(\d+\.?\d*)", result.stderr):
        timestamps.append(float(m.group(1)))

    frames_files = sorted(Path(output_dir).glob("scene_*.jpg"))
    frames = []
    for i, (fp, ts) in enumerate(zip(frames_files, timestamps)):
        compressed_path = _compress_frame(str(fp), output_dir, f"frame_{i+1:04d}.jpg")
        if compressed_path != str(fp):
            fp.unlink()
        frames.append({
            "frame": i + 1,
            "timestamp": round(ts, 2),
            "image_path": compressed_path,
        })

    return frames


def _extract_with_opencv_interval(
    video_path: str, output_dir: str, max_frames: int
) -> list[dict]:
    """用 opencv 等间隔抽帧。"""
    try:
        import cv2
    except ImportError:
        raise RuntimeError(
            "环境问题：ffmpeg 不可用且 opencv-python 未安装，无法抽取视频帧。"
            "请安装 ffmpeg 或 opencv-python（pip install opencv-python-headless）。"
        )

    from PIL import Image

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = cap.get(cv2.CAP_PROP_FPS) or 0

        if total_frames <= 0:
            raise RuntimeError("无法获取视频总帧数，可能视频已损坏")

        step = max(1, total_frames // max_frames)
        frames = []
        for i in range(0, total_frames, step):
            if len(frames) >= max_frames:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                continue

            timestamp = i / fps if fps > 0 else 0
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)

            if img.width > 1024 or img.height > 1024:
                ratio = min(1024 / img.width, 1024 / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            frame_path = f"{output_dir}/frame_{len(frames)+1:04d}.jpg"
            img.save(frame_path, format="JPEG", quality=85)
            frames.append({
                "frame": len(frames) + 1,
                "timestamp": round(timestamp, 2),
                "image_path": frame_path,
            })

        return frames
    finally:
        cap.release()


def _compress_frame(src_path: str, output_dir: str, dest_name: str) -> str:
    """压缩帧图片到 1024px 宽，转 JPEG quality 85。"""
    try:
        from PIL import Image

        img = Image.open(src_path)
        if img.width > 1024 or img.height > 1024:
            ratio = min(1024 / img.width, 1024 / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        dest_path = f"{output_dir}/{dest_name}"
        img.save(dest_path, format="JPEG", quality=85)
        return dest_path
    except Exception:
        return src_path
