"""DataCrab 版本号管理

版本格式: YYYY.MM.DD.提交次数
  - YYYY.MM.DD: 最近一次 git 提交日期
  - 提交次数: git 总提交次数
"""

import subprocess
import os
from functools import lru_cache
from datetime import datetime


def _find_git_root() -> str:
    """查找 git 仓库根目录"""
    path = os.path.dirname(os.path.abspath(__file__))
    while path != os.path.dirname(path):
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        path = os.path.dirname(path)
    return os.getcwd()


@lru_cache(maxsize=1)
def _get_git_info() -> tuple:
    """获取 git 信息: (提交日期字符串, 提交次数)"""
    git_root = _find_git_root()
    try:
        date_result = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=format:%Y.%m.%d"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=git_root,
        )
        count_result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=git_root,
        )
        if date_result.returncode == 0 and count_result.returncode == 0:
            commit_date = date_result.stdout.strip()
            commit_count = int(count_result.stdout.strip())
            if commit_date:
                return commit_date, commit_count
    except Exception:
        pass
    return None, 0


@lru_cache(maxsize=1)
def get_version() -> str:
    """生成版本号: YYYY.MM.DD.提交次数"""
    commit_date, commit_count = _get_git_info()
    if commit_date:
        return f"{commit_date}.{commit_count}"
    now = datetime.now()
    return f"{now.year}.{now.month:02d}.{now.day:02d}.{commit_count}"
