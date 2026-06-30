"""DataCrab 数据库初始化脚本

用法:
  cd backend && python init_db.py

功能:
  1. 创建所有数据库表
  2. 创建初始管理员用户 (admin / datacrab)
  3. 从磁盘扫描并导入技能到数据库
  4. 从 manifest.json 导入算子到数据库
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

# 确保 backend 目录在 sys.path 中
_backend_dir = Path(__file__).parent
sys.path.insert(0, str(_backend_dir))

from sqlalchemy import select

from app.core.database import engine, Base, async_session
from app.core.security import get_password_hash
from app.models.user import User, Role
from app.models.skill import Skill
from app.models.operator import Operator


async def init_database():
    print("=" * 50)
    print("DataCrab 数据库初始化")
    print("=" * 50)

    # 1. 建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("\n[1/4] 数据库表已创建")

    async with async_session() as db:
        # 2. 创建管理员
        await create_admin(db)
        # 3. 导入技能
        await import_skills(db)
        # 4. 导入算子
        await import_operators(db)
        await db.commit()

    await engine.dispose()
    print("\n" + "=" * 50)
    print("初始化完成! 默认账号: admin / datacrab")
    print("=" * 50)


async def create_admin(db):
    result = await db.execute(select(User).where(User.username == "admin"))
    if result.scalar_one_or_none():
        print("[2/4] 管理员用户已存在，跳过")
        return

    admin = User(
        id=uuid.uuid4(),
        username="admin",
        email="admin@datacrab.local",
        password_hash=get_password_hash("datacrab"),
        display_name="管理员",
        is_active=True,
        is_superuser=True,
    )
    db.add(admin)

    role = Role(
        id=uuid.uuid4(),
        name="admin",
        display_name="管理员",
        description="系统管理员，拥有全部权限",
        permissions={"level": "manage", "resources": "*"},
    )
    db.add(role)
    admin.roles.append(role)
    print("[2/4] 管理员用户已创建 (admin / datacrab)")


async def import_skills(db):
    from app.core.config import settings
    from app.services.skill_parser import parse_skill_md

    skills_dir = Path(settings.SKILL_STORAGE_PATH)
    if not skills_dir.exists():
        print("[3/4] 技能目录不存在，跳过")
        return

    count = 0
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            continue

        result = await db.execute(select(Skill).where(Skill.skill_path == str(skill_dir)))
        if result.scalar_one_or_none():
            continue

        parsed = parse_skill_md(skill_md_path.read_text(encoding="utf-8"))
        fm = parsed.get("front_matter", {})
        skill_name = fm.get("name", skill_dir.name)

        # 检查 name 是否已存在
        result = await db.execute(select(Skill).where(Skill.name == skill_name))
        if result.scalar_one_or_none():
            continue

        skill = Skill(
            id=uuid.uuid4(),
            name=skill_name,
            display_name=fm.get("display_name", skill_name),
            description=fm.get("description", "") or "",
            skill_path=str(skill_dir),
            tags=fm.get("tags") or [],
            category=fm.get("category", "") or "",
            version=fm.get("version", "1.0.0"),
            visibility="public",
        )
        db.add(skill)
        await db.flush()
        count += 1
        print(f"  技能: {skill.display_name}")

    print(f"[3/4] 技能导入完成 ({count} 个)")


async def import_operators(db):
    operators_dir = _backend_dir / "data" / "operators"
    manifest_path = operators_dir / "manifest.json"
    if not manifest_path.exists():
        print("[4/4] 无算子清单，跳过")
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    count = 0
    for item in manifest:
        result = await db.execute(select(Operator).where(Operator.name == item["name"]))
        if result.scalar_one_or_none():
            continue

        script_path = operators_dir / item.get("script_filename", "")
        script_content = ""
        if script_path.exists():
            script_content = script_path.read_text(encoding="utf-8")

        op = Operator(
            id=uuid.uuid4(),
            name=item["name"],
            display_name=item.get("display_name"),
            description=item.get("description"),
            category=item.get("category", "ai_generated"),
            inputs=item.get("inputs"),
            outputs=item.get("outputs"),
            parameters=item.get("parameters"),
            script_content=script_content,
            script_filename=item.get("script_filename"),
            function_name=item.get("function_name"),
            tags=item.get("tags"),
            version=item.get("version", "1.0.0"),
            visibility=item.get("visibility", "public"),
        )
        db.add(op)
        count += 1
        print(f"  算子: {op.display_name or op.name}")

    print(f"[4/4] 算子导入完成 ({count} 个)")


if __name__ == "__main__":
    asyncio.run(init_database())
