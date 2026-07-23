# DataCrab Installation & Run Guide

## Requirements

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| Git | 2.0+ |

## 1. Clone

```bash
git clone https://gitee.com/sui-qi/data-crab.git
cd data-crab
```

## 2. Install Dependencies

```bash
npm run install
```

This installs frontend npm dependencies (including concurrently) + backend Python core dependencies.

> **Optional dependencies**: If you need knowledge base RAG or OBS object storage, run additionally:
> ```bash
> pip install -e ./backend[all]
> ```
> Core features work without them.

## 3. Configure Environment

Backend config is at `backend/.env`:

```env
# Database (SQLite by default)
DATABASE_URL=sqlite+aiosqlite:///./datacrab.db

# LLM config (can also be set via frontend Settings page)
LLM_PROVIDER=glm
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=glm-5.2
OPENAI_API_BASE=https://open.bigmodel.cn/api/paas/v4
```

## 4. Start

```bash
npm run dev
```

Terminal shows color-tagged logs:

- 🟦 **Backend** — `http://localhost:8000`
- 🟩 **Frontend** — `http://localhost:5173`

## 5. Access

- **Frontend**: http://localhost:5173
- **Backend API docs**: http://localhost:8000/docs

## Commands

| Command | Description |
|---------|-------------|
| `npm run install` | Install frontend + backend core dependencies |
| `npm run dev` | Start dev environment (frontend + backend) |
| `npm run dev:backend` | Start backend only (hot reload) |
| `npm run dev:frontend` | Start frontend only |
| `npm run build:frontend` | Build frontend production bundle |
| `pip install -e ./backend[all]` | Install optional dependencies (KB + OBS) |
