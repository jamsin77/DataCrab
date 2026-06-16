"""SKILL.md 解析器 - 解析 YAML front matter + Markdown 内容"""

import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


def parse_skill_md(content: str) -> Dict[str, Any]:
    """解析 SKILL.md 内容，提取 YAML front matter 和 Markdown body

    格式:
    ---
    name: my-skill
    description: 技能描述
    ---
    # 使用说明
    ...
    """
    front_matter = {}
    body = content

    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if fm_match:
        try:
            front_matter = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError:
            pass
        body = content[fm_match.end():]

    return {
        "front_matter": front_matter,
        "body": body.strip(),
        "name": front_matter.get("name", ""),
        "description": front_matter.get("description", ""),
    }


def build_skill_md(front_matter: Dict[str, Any], body: str) -> str:
    """构建完整的 SKILL.md 内容"""
    fm_str = yaml.dump(front_matter, allow_unicode=True, default_flow_style=False).strip()
    body = body.strip()
    return f"---\n{fm_str}\n---\n\n{body}"


def get_skill_info_from_path(skill_path: Path) -> Dict[str, Any]:
    """从 Skill 文件夹路径读取基本信息"""
    info = {
        "name": skill_path.name,
        "display_name": "",
        "description": "",
        "has_skill_md": False,
        "scripts": [],
        "references": [],
        "assets": [],
    }

    skill_md_path = skill_path / "SKILL.md"
    if skill_md_path.exists():
        info["has_skill_md"] = True
        parsed = parse_skill_md(skill_md_path.read_text(encoding="utf-8"))
        info["name"] = parsed.get("name") or skill_path.name
        info["display_name"] = parsed.get("name") or ""
        info["description"] = parsed.get("description") or ""

    scripts_dir = skill_path / "scripts"
    if scripts_dir.is_dir():
        for f in sorted(scripts_dir.glob("*.py")):
            info["scripts"].append({
                "name": f.name,
                "path": str(f.relative_to(skill_path)),
                "size": f.stat().st_size,
            })

    refs_dir = skill_path / "references"
    if refs_dir.is_dir():
        for f in sorted(refs_dir.iterdir()):
            if f.is_file():
                info["references"].append({
                    "name": f.name,
                    "path": str(f.relative_to(skill_path)),
                    "size": f.stat().st_size,
                })

    assets_dir = skill_path / "assets"
    if assets_dir.is_dir():
        info["assets"] = [f.name for f in sorted(assets_dir.iterdir()) if f.is_file()]

    return info


def read_skill_md(skill_path: Path) -> Optional[str]:
    """读取 SKILL.md 内容"""
    skill_md_path = skill_path / "SKILL.md"
    if skill_md_path.exists():
        return skill_md_path.read_text(encoding="utf-8")
    return None


def write_skill_md(skill_path: Path, content: str):
    """写入 SKILL.md 内容"""
    skill_md_path = skill_path / "SKILL.md"
    skill_md_path.write_text(content, encoding="utf-8")


def read_skill_script(skill_path: Path, script_name: str) -> Optional[str]:
    """读取脚本内容"""
    script_path = skill_path / "scripts" / script_name
    if script_path.exists() and script_path.is_file():
        return script_path.read_text(encoding="utf-8")
    return None


def write_skill_script(skill_path: Path, script_name: str, content: str):
    """写入脚本内容"""
    scripts_dir = skill_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / script_name).write_text(content, encoding="utf-8")


def list_skill_scripts(skill_path: Path) -> list:
    """列出所有脚本"""
    scripts_dir = skill_path / "scripts"
    if not scripts_dir.is_dir():
        return []
    result = []
    for f in sorted(scripts_dir.glob("*.py")):
        result.append({
            "name": f.name,
            "content": f.read_text(encoding="utf-8"),
            "size": f.stat().st_size,
        })
    return result