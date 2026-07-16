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

## 2. 一键安装（推荐）

项目根目录提供了 `package.json`，可使用 npm 统一安装前后端依赖：

```bash
# 安装前端依赖 + 后端依赖
npm run install
```

该命令等价于分别执行：
```bash
npm run install:frontend   # 安装前端 npm 依赖
npm run install:backend    # 安装后端 Python 依赖
```

### 手动安装

如需单独安装：

**前端：**
```bash
cd frontend
npm install
cd ..
```

**后端：**
```bash
cd backend
pip install -e .
cd ..
```

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

## 4. 启动开发服务器

### 一键启动（推荐）

```bash
npm run dev
```

该命令会使用 `concurrently` 同时启动后端和前端，终端会显示带颜色标签的日志：

- 🟦 **后端** — 运行在 `http://localhost:8000`
- 🟩 **前端** — 运行在 `http://localhost:5173`

### 单独启动

**仅启动后端：**
```bash
npm run dev:backend
# 或
cd backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**仅启动前端：**
```bash
npm run dev:frontend
# 或
cd frontend && npm run dev
```

## 5. 生产构建

```bash
npm run build:frontend
```

构建产物位于 `frontend/dist/`，可部署到 Nginx 等静态服务器。

后端生产启动（不带热重载）：
```bash
npm run start:backend
# 或
cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 6. 访问应用

启动成功后，在浏览器打开：

- **前端页面**：http://localhost:5173
- **后端 API 文档**：http://localhost:8000/docs

## 常用命令速查

| 命令 | 说明 |
|------|------|
| `npm run install` | 安装全部依赖 |
| `npm run install:frontend` | 仅安装前端依赖 |
| `npm run install:backend` | 仅安装后端依赖 |
| `npm run dev` | 启动开发环境（前后端同时启动） |
| `npm run dev:frontend` | 仅启动前端开发服务器 |
| `npm run dev:backend` | 仅启动后端开发服务器（带热重载） |
| `npm run start:backend` | 后端生产模式启动 |
| `npm run build:frontend` | 构建前端生产包 |
