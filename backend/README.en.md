# DataCrab Backend

Backend service of the DataCrab data-intelligence application.

## Core Philosophy

Process data through conversation, accumulate data-processing Skills, form a data ecosystem, and ultimately achieve a fully closed AI loop for data processing.

- **Conversation as Processing**: the LLM understands intent, matches Skills, and generates executable code
- **Accumulation as Asset**: processing runs accumulate as reusable Skills that get smarter with use
- **Ecosystem as Loop**: DataProcessor + DataInspector dual-agent collaboration loop
- **Loop-ification**: AI understands → executes → inspects → self-repairs, with no human intervention (Self-healing Pipeline, Deep Agents)

## Features

- Conversational data interaction (SSE streaming) + multi-agent collaboration (DataProcessor → DataInspector handoff)
- 8 data-source connectors (PG/MySQL/SQLite/CSV/Excel/OBS/HDFS/Chroma) + custom connectors (AI-generated code, sandboxed)
- Full skill/operator/pipeline lifecycle (CRUD + AI generate/debug + self-healing loop + experience library)
- 7 write-table strategies + scheduling system (Cron/interval/manual + 30s scan worker)
- Document knowledge base RAG + metadata management (auto technical sync + AI business enrichment)
- RBAC permissions (user/role/permission, view/use/manage levels)

## Tech Stack

- FastAPI + Uvicorn
- SQLAlchemy 2.0 (async)
- pandas / numpy
- Zhipu GLM / Alibaba Bailian / SiliconFlow / Azure / custom OpenAI-compatible (model auto-selection pick_model_async + multi-model degradation chain + CircuitBreaker)
- SQLite (development) / PostgreSQL 14+ (production)
- ChromaDB (knowledge base vector store)

## Install

```bash
pip install -e .
```

## Run

```bash
uvicorn app.main:app --reload
```
