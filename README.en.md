# DataCrab - Data Intelligence Application Platform

DataCrab is an LLM-powered data intelligence application platform that delivers a ChatGPT-style conversational data interaction experience. Without writing any code, users can query, clean, transform, analyze, and visualize data through natural-language conversations.

## Core Philosophy

**Process data through conversation, accumulate data-processing Skills, form a data ecosystem, and ultimately achieve a fully closed AI loop for data processing.**

These four stages constitute DataCrab's evolution path—from "humans driving data through conversation" to "AI autonomously completing the data loop":

| Stage | Philosophy | Industry Trend |
|------|------|------------|
| **Conversation as Processing** | Replace coding with natural language; the LLM understands intent, matches Skills, generates executable code, and returns results as tables/charts | Conversational Data Processing, Agentic UI |
| **Accumulation as Asset** | Each processing run is automatically accumulated as a reusable Skill, progressively building a skill library that gets smarter with use | Skill-based Agent, Compound AI System |
| **Ecosystem as Loop** | Accumulated Skills form a data ecosystem; DataProcessor (processing) + DataInspector (inspection) dual-agent collaboration closes the loop from ingestion to output | Multi-Agent Collaboration, Human-in-the-loop |
| **Loop-ification** | The ultimate goal: AI understands requirements → matches Skills → executes → inspects → self-repairs, with no human intervention throughout | Self-healing Pipeline, Full-loop Automation, Deep Agents |

> **Loop-ification** is DataCrab's ultimate goal. As advocated by Loop Engineering in the industry—instead of letting AI do only single-step inference, let it iterate continuously in an "execute → observe → correct" loop until the task is complete. DataCrab's multi-agent Handoff mechanism and skill self-evolution capability are concrete practices of this philosophy.

---

## Key Features

### 1. Conversational Data Interaction

- ChatGPT-style chat interface with streaming responses (SSE)
- Session management: create, list, rename, delete, search
- Multi-turn dialogue: keeps the latest 20 messages as context
- Data-source context injection: when a user mentions a data source, the system automatically queries real data and injects it into the LLM prompt
- Supports stopping generation

### 2. Multi-Agent Collaboration Framework

DataCrab adopts a multi-agent collaboration architecture where each agent has clear responsibilities and hands off work via a Handoff mechanism:

| Agent | Responsibility |
|--------|------|
| **DataProcessor** | Understands user intent, generates/modifies operators and skills, schedules execution, traces and repairs |
| **DataInspector** | Performs standard, quality, and security inspections on processed data |

- Agent Handoff: automatically hands off to inspection after processing; automatically hands back for repair when issues are found
- Up to 12 iterations per Agent run, with parallel tool calls
- SSE streaming of reasoning process and execution results

### 3. Data Source Management

- Pluggable connector architecture supporting 6 data sources:

| Connector | Description |
|--------|------|
| PostgreSQL | Async connection based on asyncpg |
| MySQL | Async connection based on aiomysql |
| CSV | Local CSV files |
| Excel | Multi-sheet support |
| OBS/S3 | Huawei Cloud OBS object storage |
| HDFS | Hadoop HDFS (WebHDFS REST API) |

- Connection testing, schema discovery, paginated table data browsing
- Data quality analysis (completeness, missing values, outlier detection)
- Table statistics (row count, column count, size)

### 4. Metadata Management

- **Technical metadata**: one-click auto-sync when configuring a data source (table structure, row count, field stats, sample data)
- **Business metadata**: auto-enriched via LLM analysis of sample data (business name, description, tags, data domain, security level)
- Manual editing of business metadata
- Metadata search and statistical overview

### 5. Operator Management

Operators are Python scripts stored in the database, supporting:

- **Upload**: upload a `.py` file; the AST parser auto-extracts function names, parameters, and docs
- **AI generation**: natural-language description → LLM generates a Python script → auto-parse and create
- **AI modification**: natural-language instructions modify an existing operator script, with auto-verification after modification
- **Clone**: copy an operator and its script
- **Debug/Execute**: run the operator in a sandboxed namespace with injected tool functions (query_table_data, llm_chat, etc.)
- **Download**: export as a `.py` file
- **Self-evolving experience library**: failures auto-record negative examples; successes after a fix auto-record positive examples; the LLM distills lessons (common errors + success patterns) injected into subsequent generate/modify/debug prompts — gets smarter with use

### 6. Skill Management

Skills follow the Agent Skills open standard; each skill is a structured folder:

```
SKILL.md          # YAML front-matter + Markdown documentation
scripts/          # Executable Python scripts
references/       # Reference materials
assets/           # Static assets
```

- **Full lifecycle**: create, read, update, delete
- **Upload/Download**: `.zip` upload auto-extracts and parses; export as `.zip`
- **AI generation**: natural-language description → LLM generates a complete skill package
- **AI modification**: natural-language instructions modify SKILL.md content (SSE streaming, showing the thinking process)
- **Execution**: run scripts in a subprocess sandbox with timeout control and SSE streaming status
- **Natural-language execution**: the LLM infers execution parameters (with reasoning shown), then runs the skill
- **AI debug assistant**: chat-style interactive debugging; the AI can auto-execute or modify scripts
- **Skill self-evolution**: failures record negative examples, successes after a fix record positive examples; the LLM distills lessons into SKILL.md; shares a unified experience library with operators, auto-injected when generating new skills
- **Skill JSON parameter examples**: parameter definitions support an `example` field; the frontend auto-fills example values

### 7. Pipeline

A pipeline is DataCrab's core orchestration concept—**each pipeline is a Python main function**:

- One pipeline = one Python main function + the Skill scripts it calls
- One-click conversion from a Skill into a standalone Python main function
- Code visualization: shows the main function source + call graph
- Direct execution: no DAG engine needed; just run the main function
- SSE streaming generation and execution

### 8. Scheduling System

- Supports scheduled execution of operators, skills, and pipelines
- **Schedule types**: Cron expression, fixed interval (seconds), manual trigger
- Cron expression validation and next-run preview
- Pause/resume schedules
- Task execution tracking: status, duration, logs, retry count

### 9. LLM Public API

The platform exposes underlying LLM capabilities as a RESTful API:

| Endpoint | Description |
|------|------|
| `POST /llm/chat` | LLM chat (non-streaming) |
| `POST /llm/chat-stream` | LLM chat (SSE streaming) |
| `POST /llm/chat-stream-thinking` | Multi-turn LLM chat (SSE streaming, with reasoning) |
| `POST /llm/embeddings` | Generate text embedding vectors |

- The `llm_chat()` function can be called directly inside operator and skill scripts
- The frontend config page supports switching among three call modes

### 10. File Link Management

- Mount local file/directory paths
- Access control (public/private, allowed file extensions)
- Agents can write files to linked directories

### 11. Authentication & Permission Management

- JWT authentication (Access Token + Refresh Token)
- RBAC role-based permissions: user → role → permission
- Permission levels: view, use, manage
- Resource-level permission control (operators, skills, data sources, schedules, pipelines, etc.)
- Permission management API: role CRUD, permission assignment and checking

### 12. Multi-Model LLM Support

| Provider | Description |
|--------|------|
| Zhipu GLM | Zhipu AI (default) |
| OpenAI | GPT series |
| Azure OpenAI | Azure-hosted OpenAI service |
| Tongyi Qianwen | Alibaba Cloud DashScope |
| Custom endpoint | Any OpenAI-API-compatible endpoint |

- Dynamically switch provider/key/model at runtime
- Streaming output supports chain-of-thought / reasoning content
- Function Calling support

### 13. Data Standards / Quality / Security Rule Libraries

Three Markdown rule libraries, viewable/editable on the "System Settings" page; DataInspector references the corresponding IDs when inspecting:

| Library | Content | ID |
|--------|------|------|
| Data Standards | field-level format/constraints (ID card/phone/email/amount/date/enum/industry-specific) | `STD-xxx` |
| Data Quality | DAMA 6 dimensions + ETL process quality (completeness/uniqueness/reconciliation/volume drift) | `DQ-xxx` |
| Data Security | PII detection / credential leak / sensitive business data / classification / masking / compliance | `SEC-xxx` |

- MD editable with "restore defaults"; backend `GET/PUT/POST /config/data-standards|data-quality|data-security`(+`/reset`)
- DataInspector injects all three libraries into its prompt; check tools deterministically execute regex/aggregation, tagging issues with `STD/DQ/SEC` IDs; semantic checks by LLM

---

## Tech Stack

### Backend

- **Language**: Python 3.11+
- **Web framework**: FastAPI + Uvicorn
- **ORM**: SQLAlchemy 2.0 (async, supports SQLite / PostgreSQL)
- **LLM integration**: Zhipu GLM (glm-4-flash / glm-4-plus / glm-5.2)
- **Data processing**: pandas, numpy

### Frontend

- **Framework**: Vue 3 + TypeScript + Composition API
- **Build tool**: Vite 5
- **UI library**: Element Plus
- **State management**: Pinia
- **Routing**: Vue Router 4
- **Charts**: ECharts 5
- **Code editor**: Monaco Editor
- **Markdown rendering**: markdown-it + highlight.js
- **Flow editing**: Vue Flow

### Data Storage

- **Database**: SQLite (development) / PostgreSQL 14+ (production)
- **File storage**: local file system

---

## Project Structure

```
DataCrab/
├── backend/                    # Backend service
│   ├── app/
│   │   ├── main.py            # FastAPI entry
│   │   ├── core/              # Core config (database, security, types)
│   │   ├── api/v1/endpoints/  # API endpoints (17 resource groups)
│   │   ├── models/            # ORM models (9 models)
│   │   ├── schemas/           # Pydantic request/response schemas
│   │   └── services/          # Business-logic services
│   │       ├── llm.py         # LLM manager (multi-provider, streaming, tool calls)
│   │       ├── agent.py       # Agent service (tool-call loop)
│   │       ├── multi_agent.py # Multi-agent runtime (Handoff, AgentRegistry)
│   │       ├── data_processor_agent.py  # DataProcessor agent
│   │       ├── data_inspector_agent.py  # DataInspector agent
│   │       ├── inspector_tools.py       # Data inspection toolset
│   │       ├── skill_library.py  # Vector index + semantic search
│   │       ├── skill_parser.py   # SKILL.md parser
│   │       ├── skill_runner.py   # Subprocess sandbox executor
│   │       ├── skill_creator.py  # AI skill-package generator
│   │       ├── pipeline_builder.py  # Pipeline generator
│   │       ├── pipeline_executor.py # Pipeline execution engine
│   │       ├── connectors.py    # 6 data-source connectors
│   │       └── operator_parser.py # Python AST script parser
│   └── data/skills/           # Skill package on-disk storage
├── frontend/                   # Frontend app
│   ├── src/
│   │   ├── views/             # 14 page views
│   │   ├── router/            # Routing config
│   │   ├── stores/            # Pinia state management
│   │   ├── api/               # Axios API client
│   │   └── composables/       # Vue composables
│   └── package.json
├── package.json               # npm unified install/start scripts
├── INSTALL.md                 # Installation & run guide
└── design.md                  # Technical architecture design document
```

---

## Quick Start

See [INSTALL.md](INSTALL.md) for details.

### Requirements

- Python 3.11+
- Node.js 16+

### One-click Start

```bash
# Install dependencies
npm install

# Development mode (frontend and backend start in parallel)
npm run dev
```

### Start Separately

```bash
# Backend
cd backend
pip install -e .
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run dev    # Vite dev server, default port 5173
```

---

## API Overview

All API routes are prefixed with `/api/v1/`:

| Path | Function |
|------|------|
| `/auth` | Login, register, token refresh |
| `/chat` | Session management, messages, streaming chat, natural-language data processing |
| `/datasources` | Data source CRUD, connection test, table data/stats/quality |
| `/skills` | Skill full lifecycle, upload/download, run, AI generate/modify |
| `/operators` | Operator CRUD, upload, generate, modify, debug, clone |
| `/pipelines` | Pipeline CRUD, generate from Skill, execute, clone |
| `/schedules` | Schedule CRUD, pause/resume, trigger, stats |
| `/metadata` | Metadata management, AI-enriched business metadata |
| `/filelinks` | File link CRUD |
| `/llm` | LLM chat (streaming/non-streaming), embeddings |
| `/config` | LLM provider runtime config |
| `/agents` | Agent list, run agent, data inspection |
| `/permissions` | Permission management |
| `/filesystem` | Filesystem browsing |
| `/notebooks` | Notebook basic CRUD |

---

## Architecture Highlights

1. **Multi-agent collaboration loop**: DataProcessor + DataInspector dual agents with automatic Handoff, forming a self-healing processing+inspection loop (Multi-Agent Collaboration)
2. **Pluggable connectors**: `BaseConnector` abstract class + registry pattern for easily extending new data source types
3. **Skill package standard**: structured folder format (SKILL.md + scripts), both human-readable and machine-parseable; Skills are accumulable, reusable assets
4. **Pipeline = Python main function**: discards the DAG model; each pipeline is a standalone runnable Python function
5. **Self-evolving experience library**: operators and skills share a unified `experience.json` library — failures record negative examples, successes after a fix record positive examples; the LLM distills them into "common errors + success patterns" injected into generate/modify/debug prompts, closing the "execute → record → distill → inject" loop, getting smarter with use
6. **LLM capability injection**: the `llm_chat()` function can be called directly inside operator and skill scripts without HTTP requests
7. **Metadata management**: one-click technical metadata sync + AI-enriched business metadata for a unified data catalog
8. **Streaming-first architecture**: multiple endpoints support SSE streaming for real-time feedback
9. **AST script introspection**: Python AST parsing auto-extracts function signatures and docs, registering operators with zero config
10. **AI debug assistant**: chat-style interactive debugging with visible AI reasoning; on execution failure, error stack traces are automatically fed back to the AI for repair (a Loop Engineering practice)
