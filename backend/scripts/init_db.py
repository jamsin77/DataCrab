"""数据库初始化脚本 - 创建初始数据"""

import asyncio
import os
import secrets
from sqlalchemy import select
from app.core.database import async_session, engine, Base
from app.models.user import User, Role
from app.core.security import get_password_hash


async def init_db():
    """初始化数据库"""
    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("数据库表已创建")

    async with async_session() as session:
        # 检查是否已有管理员
        result = await session.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            print("管理员用户已存在，跳过初始化")
            return

        # 创建默认角色
        admin_role = Role(
            name="admin",
            display_name="管理员",
            description="系统管理员，拥有所有权限",
            permissions={"all": "manage"},
        )
        user_role = Role(
            name="user",
            display_name="普通用户",
            description="普通用户，基本使用权限",
            permissions={"datasource": "use", "skill": "use", "code": "use"},
        )
        session.add(admin_role)
        session.add(user_role)
        await session.flush()

        # 创建管理员用户（默认随机强密码，可用 ADMIN_INITIAL_PASSWORD 指定）
        admin_password = os.environ.get("ADMIN_INITIAL_PASSWORD") or secrets.token_urlsafe(12)
        admin = User(
            username="admin",
            email="admin@datacrab.com",
            password_hash=get_password_hash(admin_password),
            display_name="管理员",
            is_superuser=True,
            is_active=True,
        )
        admin.roles.append(admin_role)
        session.add(admin)

        await session.commit()
        print("初始数据创建完成")
        print(f"管理员账号: admin / {admin_password}")


if __name__ == "__main__":
    asyncio.run(init_db())
