# DataCrab Backend

Backend service of the DataCrab data-intelligence application.

## Core Philosophy

Process data through conversation, accumulate data-processing Skills, form a data ecosystem, and ultimately achieve a fully closed AI loop for data processing.

- **Conversation as Processing**: the LLM understands intent, matches Skills, and generates executable code
- **Accumulation as Asset**: processing runs accumulate as reusable Skills that get smarter with use
- **Ecosystem as Loop**: DataProcessor + DataInspector dual-agent collaboration loop
- **Loop-ification**: AI understands → executes → inspects → self-repairs, with no human intervention (Self-healing Pipeline, Deep Agents)

## Features

- Natural-language processing and intent recognition
- Intelligent skill matching and recommendation
- Vector search system
- Data source management
- Pipeline orchestration

## Tech Stack

- FastAPI
- SQLAlchemy
- OpenAI API
- Redis
- SQLite/PostgreSQL

## Install

```bash
pip install -e .
```

## Run

```bash
uvicorn app.main:app --reload
```
