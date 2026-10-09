"""Per-session working copy manager.

多个调试会话同时操作同一个技能时，各自在工作副本上编辑/执行，
互不干扰。用户显式"保存"时，3-way merge 回主干。
"""
import shutil
import time
from pathlib import Path
from typing import Optional

from loguru import logger

_WC_ROOT_NAME = "dc_debug_wc"
_WC_MAX_AGE_SECONDS = 24 * 3600  # 24h


def _wc_root() -> Path:
    from app.core.config import settings
    return Path(settings.SKILL_STORAGE_PATH).parent / _WC_ROOT_NAME


def create_working_copy(skill_folder: Path) -> Path:
    wc_root = _wc_root()
    wc_root.mkdir(parents=True, exist_ok=True)
    import uuid
    wc_id = uuid.uuid4().hex[:12]
    wc_path = wc_root / f"{skill_folder.name}_{wc_id}"
    if skill_folder.exists():
        shutil.copytree(skill_folder, wc_path)
    else:
        wc_path.mkdir(parents=True, exist_ok=True)
    _write_base_snapshot(wc_path, skill_folder)
    logger.info(f"[working_copy] created {wc_path.name} <- {skill_folder.name}")
    return wc_path


def get_working_copy(wc_id: str, skill_folder: Path) -> Optional[Path]:
    if not wc_id:
        return None
    wc_root = _wc_root()
    candidates = list(wc_root.glob(f"{skill_folder.name}_{wc_id}"))
    if candidates and candidates[0].exists():
        return candidates[0]
    return None


def cleanup_working_copy(wc_path: Path) -> None:
    if wc_path.exists() and _wc_root() in wc_path.parents:
        shutil.rmtree(wc_path, ignore_errors=True)
        logger.info(f"[working_copy] cleaned {wc_path.name}")


def cleanup_expired() -> int:
    wc_root = _wc_root()
    if not wc_root.exists():
        return 0
    now = time.time()
    count = 0
    for d in wc_root.iterdir():
        if not d.is_dir():
            continue
        try:
            mtime = d.stat().st_mtime
        except OSError:
            continue
        if now - mtime > _WC_MAX_AGE_SECONDS:
            shutil.rmtree(d, ignore_errors=True)
            count += 1
            logger.info(f"[working_copy] expired cleanup: {d.name}")
    return count


def _write_base_snapshot(wc_path: Path, skill_folder: Path) -> None:
    snapshot = wc_path / ".base_snapshot"
    if skill_folder.exists():
        with open(snapshot, "w", encoding="utf-8") as f:
            for item in sorted(skill_folder.rglob("*")):
                if item.is_file() and ".base_snapshot" not in item.name:
                    rel = item.relative_to(skill_folder)
                    f.write(f"{rel}\x00{item.read_text(encoding='utf-8', errors='replace')}\x00\x00")
    else:
        snapshot.write_text("", encoding="utf-8")


def read_base_snapshot(wc_path: Path) -> dict:
    snapshot = wc_path / ".base_snapshot"
    if not snapshot.exists():
        return {}
    result = {}
    raw = snapshot.read_text(encoding="utf-8", errors="replace")
    for chunk in raw.split("\x00\x00"):
        chunk = chunk.strip("\x00")
        if not chunk:
            continue
        sep = chunk.find("\x00")
        if sep < 0:
            continue
        rel = chunk[:sep]
        content = chunk[sep + 1:]
        result[rel] = content
    return result
