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
npm install
```

This automatically installs:
- Root tools (concurrently, for starting frontend + backend together)
- Frontend npm dependencies
- Backend Python core dependencies

> **Optional**:
> - Knowledge base RAG or OBS storage:
>   ```bash
>   pip install -e ./backend[all]
>   ```
> - Video processing (keyframe scene detection): install [ffmpeg](https://ffmpeg.org/download.html) and add to PATH. Falls back to opencv interval extraction if not installed.

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
| `npm install` | Install all dependencies (root + frontend + backend) |
| `npm run dev` | Start dev environment (frontend + backend) |
| `npm run dev:backend` | Start backend only (hot reload) |
| `npm run dev:frontend` | Start frontend only |
| `npm run build:frontend` | Build frontend production bundle |
| `pip install -e ./backend[all]` | Install optional dependencies (KB + OBS) |

## Docker Deployment

```bash
docker-compose up -d
```

- Frontend: nginx hosts built assets (port 80)
- Backend: Uvicorn + data volume persistence (`backend_data:/app/data`)
- nginx: reverse proxy + SSE long-connection support (`proxy_buffering off` + `proxy_read_timeout 300s`)
- `DATACRAB_API_BASE` env var: skill_runner subprocess uses it to access backend API (set to `http://backend:8000` in Docker)

## Version

Version number is dynamically generated as `YYYY.MM.DD.commit-count` (from git log), displayed in sidebar footer, login page, and About page.
