# DataCrab 安装与运行指南

## 环境要求

| 工具 | 版本要求 |
|------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| Git | 2.0+ |

## 1. 克隆项目

```bash
git clone https://gitee.com/sui-qi/data-crab.git
cd data-crab
```

## 2. 安装依赖

```bash
npm install
```

这会自动安装：
- 根目录工具（concurrently，用于同时启动前后端）
- 前端 npm 依赖
- 后端 Python 核心依赖

> **可选依赖**：
> - 文档知识库 RAG 或 OBS 对象存储：
>   ```bash
>   pip install -e ./backend[all]
>   ```
> - 视频处理（关键帧场景检测）：安装 [ffmpeg](https://ffmpeg.org/download.html) 并加入 PATH。未安装时自动回退 opencv 等间隔抽帧。

## 3. 配置环境变量

后端配置文件位于 `backend/.env`，根据实际情况修改：

```env
# 数据库（默认 SQLite，无需额外配置）
DATABASE_URL=sqlite+aiosqlite:///./datacrab.db

# LLM 配置（也可启动后在前端「系统设置」页面配置）
LLM_PROVIDER=glm
OPENAI_API_KEY=你的API密钥
OPENAI_MODEL=glm-5.2
OPENAI_API_BASE=https://open.bigmodel.cn/api/paas/v4
```

## 4. 启动

```bash
npm run dev
```

终端会显示带颜色标签的日志：

- 🟦 **后端** — `http://localhost:8000`
- 🟩 **前端** — `http://localhost:5173`

## 5. 访问

- **前端页面**：http://localhost:5173
- **后端 API 文档**：http://localhost:8000/docs

## 常用命令

| 命令 | 说明 |
|------|------|
| `npm install` | 安装全部依赖（根目录 + 前端 + 后端） |
| `npm run dev` | 启动开发环境（前后端同时） |
| `npm run dev:backend` | 仅启动后端（热重载） |
| `npm run dev:frontend` | 仅启动前端 |
| `npm run build:frontend` | 构建前端生产包 |
| `pip install -e ./backend[all]` | 安装可选依赖（知识库 + OBS） |

## Docker 部署

```bash
docker-compose up -d
```

- 前端：nginx 托管构建产物（端口 80）
- 后端：Uvicorn + 数据卷持久化（`backend_data:/app/data`）
- nginx：反向代理 + SSE 长连接支持（`proxy_buffering off` + `proxy_read_timeout 300s`）
- `DATACRAB_API_BASE` 环境变量：skill_runner 子进程通过它访问后端 API（Docker 中设为 `http://backend:8000`）

## 版本号

版本号动态生成，格式为 `YYYY.MM.DD.提交次数`（基于 git log），显示在侧边栏底部、登录页和关于页。
