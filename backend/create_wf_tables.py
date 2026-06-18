import asyncio
from app.core.database import engine, Base
from app.models import Workflow, WorkflowExecution

async def f():
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    print("Done")

asyncio.run(f())
