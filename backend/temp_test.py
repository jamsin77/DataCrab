import asyncio, sqlite3, uuid

async def test():
    conn = sqlite3.connect('datacrab.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM user_llm_configs LIMIT 1")
    uid = c.fetchone()[0]
    conn.close()

    from app.services.llm import init_user_llm_context
    await init_user_llm_context(uuid.UUID(uid))

    from app.services.match_service import llm_match_tables, llm_match_skills, llm_match_pipelines
    from app.core.database import async_session

    q = "我想把他挪到数据列表里，可以吗"
    async with async_session() as db:
        tables = await llm_match_tables(q, db)
        print(f"tables: {len(tables)} matched")
        for tid, score, meta in tables:
            print(f"  {meta.get('datasource_name','')} -> {meta.get('table_name','')}")

        skills = await llm_match_skills(q, db)
        print(f"\nskills: {len(skills)} matched")
        from app.models.skill import Skill
        from sqlalchemy import select
        for sid, score in skills:
            s = (await db.execute(select(Skill).where(Skill.id == uuid.UUID(sid)))).scalar_one_or_none()
            if s:
                print(f"  {s.name}")

        pipes = await llm_match_pipelines(q, db)
        print(f"\npipelines: {len(pipes)} matched")

asyncio.run(test())
