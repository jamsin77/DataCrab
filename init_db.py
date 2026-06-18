#!/usr/bin/env python3
"""初始化数据库表"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.core.database import engine, Base
from app.models.schedule import Schedule, TaskExecution
from app.models.user import User
from app.models.datasource import DataSource
from app.models.skill import Skill
from app.models.operator import Operator
from app.models.chat import ChatSession, ChatMessage

async def create_tables():
    """创建所有表"""
    print("开始创建数据库表...")
    
    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
    
    print("✅ 数据库表创建成功！")
    print("\n创建的表：")
    
    # 列出所有表
    for table_name in Base.metadata.tables.keys():
        print(f"  - {table_name}")

if __name__ == "__main__":
    asyncio.run(create_tables())