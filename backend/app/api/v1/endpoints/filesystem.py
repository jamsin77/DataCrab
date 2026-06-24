import os
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/browse")
async def browse_filesystem(
    path: str = Query("D:/", description="浏览路径"),
    mode: str = Query("file", description="选择模式: file / folder"),
    ext: str = Query("", description="文件扩展名过滤，逗号分隔，如 .xlsx,.xls"),
    current_user: User = Depends(get_current_user),
):
    if not os.path.isdir(path):
        parent = str(Path(path).parent)
        if os.path.isdir(parent):
            path = parent
        else:
            path = "D:/"

    path = os.path.normpath(path)
    ext_list = [e.strip().lower() for e in ext.split(",") if e.strip()] if ext else []

    directories = []
    files = []

    try:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return {"current": path, "parent": str(Path(path).parent), "directories": [], "files": []}

    for entry in entries:
        name = entry.name
        if name.startswith(".") or name.startswith("$"):
            continue
        if entry.is_dir():
            directories.append({"name": name, "path": entry.path})
        elif entry.is_file() and mode != "folder":
            if ext_list:
                if not any(name.lower().endswith(e) for e in ext_list):
                    continue
            files.append({"name": name, "path": entry.path})

    parent = str(Path(path).parent) if path != Path(path).root else path

    return {
        "current": path,
        "parent": parent,
        "directories": directories,
        "files": files if mode != "folder" else [],
    }
