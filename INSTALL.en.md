# DataCrab Installation & Run Guide

## Requirements

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| Git | 2.0+ |

## 1. Clone the Project

```bash
git clone https://gitee.com/sui-qi/data-crab.git
cd data-crab
```

## 2. One-click Install (Recommended)

A `package.json` is provided at the project root to install both frontend and backend dependencies via npm:

```bash
# Install frontend + backend dependencies (including optional: KB RAG + OBS storage)
npm run install
```

This is equivalent to running:
```bash
npm run install:frontend   # Install frontend npm dependencies
npm run install:backend    # Install backend Python dependencies (core + optional)
```

> **About optional dependencies**: Backend dependencies are split into core and optional:
> - **Core** (`requirements.txt`): FastAPI / SQLAlchemy / pandas / openai etc. — fast to install
> - **Optional** (`requirements-optional.txt`):
>   - `chromadb` — Knowledge base RAG (pulls 25+ sub-dependencies, slower to install)
>   - `minio` — OBS object storage connector
>
> `npm run install` installs both core and optional. To install core only (without KB and OBS):

### Manual Install

**Frontend:**
```bash
cd frontend
npm install
cd ..
```

**Backend (full):**
```bash
cd backend
pip install -e .
pip install -r requirements-optional.txt
cd ..
```

**Backend (core only, skip KB and OBS):**
```bash
cd backend
pip install -e .
cd ..
```

**Backend (selective optional features):**
```bash
pip install -e ./backend[kb]       # KB RAG only
pip install -e ./backend[obs]      # OBS storage only
pip install -e ./backend[all]      # All optional dependencies
```

## 3. Configure Environment Variables

The backend config file is at `backend/.env`; modify it as needed:

```env
# Database (SQLite by default, no extra setup needed)
DATABASE_URL=sqlite+aiosqlite:///./datacrab.db

# LLM config (can also be configured via frontend Settings page after startup)
LLM_PROVIDER=glm
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=glm-5.2
OPENAI_API_BASE=https://open.bigmodel.cn/api/paas/v4
```

## 4. Start Dev Server

### One-click Start (Recommended)

```bash
npm run dev
```

This uses `concurrently` to start both backend and frontend. The terminal shows color-tagged logs:

- 🟦 **Backend** — runs at `http://localhost:8000`
- 🟩 **Frontend** — runs at `http://localhost:5173`

### Start Separately

**Backend only:**
```bash
npm run dev:backend
# or
cd backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend only:**
```bash
npm run dev:frontend
# or
cd frontend && npm run dev
```

## 5. Production Build

```bash
npm run build:frontend
```

Build output is in `frontend/dist/`, deployable to Nginx or other static servers.

Backend production start (no hot reload):
```bash
npm run start:backend
# or
cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 6. Access the App

Once started, open in your browser:

- **Frontend**: http://localhost:5173
- **Backend API docs**: http://localhost:8000/docs

## Command Reference

| Command | Description |
|---------|-------------|
| `npm run install` | Install all dependencies (frontend + backend core + optional) |
| `npm run install:frontend` | Install frontend dependencies only |
| `npm run install:backend` | Install backend dependencies (core + optional) |
| `pip install -e ./backend` | Install backend core dependencies only (fast) |
| `pip install -e ./backend[all]` | Install all backend dependencies (incl. KB + OBS) |
| `npm run dev` | Start dev environment (frontend + backend) |
| `npm run dev:frontend` | Start frontend dev server only |
| `npm run dev:backend` | Start backend dev server only (with hot reload) |
| `npm run start:backend` | Start backend in production mode |
| `npm run build:frontend` | Build frontend production bundle |
