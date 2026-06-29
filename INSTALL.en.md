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
# Install frontend + backend dependencies
npm run install
```

This is equivalent to running:
```bash
npm run install:frontend   # Install frontend npm dependencies
npm run install:backend    # Install backend Python dependencies
```

### Manual Install

To install separately:

**Frontend:**
```bash
cd frontend
npm install
cd ..
```

**Backend:**
```bash
cd backend
pip install -e .
cd ..
```

## 3. Configure Environment Variables

The backend config file is at `backend/.env`; modify it as needed:

```env
# Database (SQLite by default; no extra setup needed)
DATABASE_URL=sqlite+aiosqlite:///./datacrab.db

# LLM config
LLM_PROVIDER=glm
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=glm-5.2
OPENAI_API_BASE=https://open.bigmodel.cn/api/coding/paas/v4
```

## 4. Start the Dev Server

### One-click Start (Recommended)

```bash
npm run dev
```

This uses `concurrently` to start both backend and frontend; the terminal shows color-tagged logs:

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

The build output is in `frontend/dist/` and can be deployed to a static server such as Nginx.

Backend production start (without hot reload):
```bash
npm run start:backend
# or
cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 6. Access the App

After a successful start, open in your browser:

- **Frontend page**: http://localhost:5173
- **Backend API docs**: http://localhost:8000/docs

## Common Commands

| Command | Description |
|------|------|
| `npm run install` | Install all dependencies |
| `npm run install:frontend` | Install frontend dependencies only |
| `npm run install:backend` | Install backend dependencies only |
| `npm run dev` | Start dev environment (frontend + backend together) |
| `npm run dev:frontend` | Start frontend dev server only |
| `npm run dev:backend` | Start backend dev server only (with hot reload) |
| `npm run start:backend` | Start backend in production mode |
| `npm run build:frontend` | Build the frontend production bundle |
