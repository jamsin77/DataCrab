# DataCrab - 数据智能应用平台

DataCrab 是一款基于大语言模型（LLM）的数据智能应用平台，提供 ChatGPT 风格的对话式数据交互体验。用户无需编写代码，通过自然语言对话即可完成数据的查询、清洗、转换、分析和可视化等操作。

## 核心理念

**用对话代替编码** —— 让数据处理像聊天一样简单。系统通过 LLM 理解用户意图，自动匹配技能/算子，生成可执行的 Python 代码，并以表格、图表和文字说明的形式返回结果。

---

## 主要功能

### 1. 对话式数据交互

- ChatGPT 风格的聊天界面，支持流式响应（SSE）
- 会话管理：创建、列表、重命名、删除、搜索
- 多轮对话：保留最近 20 条消息作为上下文
- 数据源上下文注入：用户提及数据源时，系统自动查询真实数据并注入到 LLM 提示词中
- 复杂查询解析：排序、过滤、分页、聚合，支持中国朝代排序（文物数据领域特色）
- 支持停止生成

### 2. Agent 系统（工具调用）

LLM 可自主调用工具完成数据操作，支持最多 5 轮迭代的 Agent 循环：

| 工具 | 功能 |
|------|------|
| `query_table_data` | 查询数据源中的表数据（支持过滤、排序、分页） |
| `get_table_schema` | 查看表结构 |
| `list_user_datasources` | 列出已连接的数据源 |
| `list_user_file_links` | 列出已挂载的文件目录 |
| `save_file_to_link` | 保存文件到用户目录 |

### 3. 数据源管理

- 插件化连接器架构，支持 6 种数据源：

| 连接器 | 说明 |
|--------|------|
| PostgreSQL | 基于 asyncpg 的异步连接 |
| MySQL | 基于 aiomysql 的异步连接 |
| CSV | 本地 CSV 文件 |
| Excel | 多 Sheet 支持 |
| OBS/S3 | 华为云 OBS 对象存储 |
| HDFS | Hadoop HDFS（WebHDFS REST API） |

- 连接测试、Schema 发现、表数据分页浏览
- 数据质量分析（完整性、缺失值、异常值检测）
- 表统计信息（行数、列数、大小）
- 元数据管理（技术元数据 + 业务元数据）

### 4. 算子管理

算子是存储在数据库中的 Python 脚本，支持：

- **上传**：上传 `.py` 文件，AST 解析器自动提取函数名、参数和文档
- **AI 生成**：自然语言描述 → LLM 生成 Python 脚本 → 自动解析创建
- **AI 修改**：自然语言指令修改已有算子脚本
- **克隆**：复制算子及其脚本
- **调试/执行**：在沙盒命名空间中运行算子，注入工具函数
- **下载**：导出为 `.py` 文件

内置分类：transform、aggregate、filter、join、cleaning、analysis、ai_generated

### 5. 技能管理

技能遵循 Agent Skills 开放标准，每个技能是一个结构化文件夹：

```
SKILL.md          # YAML 前置信息 + Markdown 说明文档
scripts/          # 可执行的 Python 脚本
references/       # 参考资料
assets/           # 静态资源
```

- **完整生命周期**：创建、读取、更新、删除
- **上传/下载**：`.zip` 包上传自动解压解析，导出为 `.zip`
- **AI 生成（技能创建器）**：自然语言描述 → LLM 生成完整技能包
- **AI 修改**：自然语言指令修改 SKILL.md 内容（SSE 流式，展示思考过程）
- **执行**：在子进程沙盒中执行脚本，支持超时控制、SSE 流式状态推送
- **自然语言执行**：LLM 推断执行参数（含推理过程展示），然后运行技能
- **AI 调试助手**：Chat 风格交互式调试界面
  - 左侧执行面板：自然语言/命令行/JSON 三种输入方式
  - 右侧 AI 调试面板：多轮对话，AI 可自动执行或修改脚本
  - 推理过程可视化：蓝色推理卡片实时展示 AI 思考过程
- 技能脚本自动同步到算子表

### 6. 技能库与语义搜索

- 基于 OpenAI Embeddings 的向量语义搜索
- 关键词匹配作为降级方案
- 10 个预置内置技能：select、filter、sort、groupby、aggregate、join、fillna、dropna、rename、stats

### 7. 自然语言处理流水线

- **意图识别**：基于关键词的 8 类意图分类（数据清洗、数据转换、数据聚合、数据分析、数据融合、数据导出、创建算子、创建技能）
- **实体提取**：预留 LLM 基础提取接口
- **技能匹配**：向量搜索 + 关键词匹配组合策略

### 8. 流水线编排

- 定义多步骤数据处理流水线
- 步骤引用技能/算子，支持参数定义和依赖关系（DAG 结构）
- 意图识别 → 技能匹配 → 技能组合 → 参数推断 → 验证的完整流水线

### 9. 调度系统

- 支持算子、技能和工作流的定时执行
- **调度类型**：Cron 表达式、固定间隔（秒）、手动触发
- Cron 表达式校验及下次执行时间预览
- 暂停/恢复调度
- 任务执行追踪：状态、耗时、日志、重试次数
- 执行统计仪表盘

### 10. Notebook 环境

- 类 Jupyter 的代码笔记本
- 代码单元格与 Markdown 单元格
- 内核管理（Python/SQL）
- 版本历史
- 保存/分享/导出

### 11. 数据探索面板

- 浏览数据源树形结构
- 查看表 Schema 和样本数据
- 元数据搜索

### 12. 文件链接管理

- 挂载本地文件/目录路径
- 访问控制（公开/私有，允许的文件扩展名）
- 文件元数据追踪
- Agent 可写入文件到已链接目录

### 13. 认证与授权

- JWT 认证（Access Token + Refresh Token）
- RBAC 角色权限控制：用户 → 角色 → 权限
- 权限级别：view、use、manage
- 资源级权限控制（算子、技能、数据源、调度）

### 14. LLM 多模型支持

| 提供商 | 说明 |
|--------|------|
| OpenAI | GPT 系列 |
| Azure OpenAI | Azure 托管的 OpenAI 服务 |
| 通义千问 | 阿里云 DashScope |
| 智谱 GLM | 智谱 AI |
| 自定义端点 | 兼容 OpenAI API 的任意端点 |

- 运行时动态切换模型提供商/密钥/模型
- 流式输出支持思维链/推理内容
- 工具调用（Function Calling）支持

---

## 技术栈

### 后端

- **语言**：Python 3.9+
- **Web 框架**：FastAPI + Uvicorn
- **ORM**：SQLAlchemy 2.0（异步，支持 SQLite / PostgreSQL）
- **任务队列**：Celery + Redis
- **数据处理**：pandas, numpy
- **LLM 集成**：OpenAI API
- **对象存储**：MinIO
- **搜索引擎**：Elasticsearch
- **数据库迁移**：Alembic

### 前端

- **框架**：Vue 3 + TypeScript + Composition API
- **构建工具**：Vite 5
- **UI 组件库**：Element Plus
- **状态管理**：Pinia
- **路由**：Vue Router 4
- **图表**：ECharts 5
- **代码编辑器**：Monaco Editor
- **Markdown 渲染**：markdown-it + highlight.js

### 基础设施

- **容器化**：Docker + Docker Compose
- **反向代理**：Nginx
- **数据库**：SQLite（开发）/ PostgreSQL 14（生产）
- **缓存**：Redis 7
- **对象存储**：MinIO

---

## 项目结构

```
DataCrab/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── core/              # 核心配置（数据库、安全、类型）
│   │   ├── api/v1/endpoints/  # API 端点（10 个资源组）
│   │   ├── models/            # ORM 模型（9 个模型）
│   │   ├── schemas/           # Pydantic 请求/响应模式
│   │   └── services/          # 业务逻辑服务
│   │       ├── llm.py         # LLM 管理器（多提供商、流式、工具调用）
│   │       ├── agent.py       # Agent 服务（工具调用循环）
│   │       ├── nl_service.py  # 自然语言意图识别
│   │       ├── skill_library.py # 向量索引 + 语义搜索
│   │       ├── skill_parser.py  # SKILL.md 解析器
│   │       ├── skill_runner.py  # 子进程沙盒执行器
│   │       ├── skill_creator.py # AI 技能包生成器
│   │       ├── connectors.py    # 6 种数据源连接器
│   │       └── operator_parser.py # Python AST 脚本解析器
│   ├── data/skills/           # 技能包磁盘存储
│   ├── alembic/               # 数据库迁移
│   └── pyproject.toml         # Poetry 项目定义
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── views/             # 11 个页面视图
│   │   ├── router/            # 路由配置
│   │   ├── stores/            # Pinia 状态管理
│   │   ├── api/               # Axios API 客户端
│   │   └── composables/       # Vue 组合函数
│   └── package.json
├── nginx/                      # Nginx 反向代理配置
├── docker-compose.yml          # 全栈部署配置
└── skills/                     # 示例技能（文物专家）
```

---

## 快速开始

### 环境要求

- Python 3.9+
- Node.js 16+
- Redis（用于 Celery 任务队列）

### 后端启动

```bash
cd backend
pip install -e .

# 配置环境变量（复制 .env.example 为 .env）
# 必须配置：OPENAI_API_KEY

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端启动

```bash
cd frontend
npm install
npm run dev    # Vite 开发服务器，默认端口 5173
```

### Docker 全栈部署

```bash
docker-compose up
```

启动服务：PostgreSQL、Redis、MinIO、后端、Celery Worker、前端、Nginx。

---

## API 概览

所有 API 路由前缀为 `/api/v1/`：

| 路径 | 功能 |
|------|------|
| `/auth` | 登录、注册、令牌刷新 |
| `/chat` | 会话管理、消息、流式对话、自然语言数据处理 |
| `/datasources` | 数据源 CRUD、连接测试、表数据/统计/质量 |
| `/skills` | 技能全生命周期、上传/下载、运行、AI 生成/修改 |
| `/operators` | 算子 CRUD、上传、生成、修改、调试、克隆 |
| `/codes` | 流水线 CRUD、执行 |
| `/schedules` | 调度 CRUD、暂停/恢复、触发、统计 |
| `/notebooks` | 笔记本 CRUD、执行单元格 |
| `/filelinks` | 文件链接 CRUD |
| `/config` | LLM 提供商运行时配置 |

---

## 架构亮点

1. **插件化连接器**：`BaseConnector` 抽象类 + 注册表模式，轻松扩展新数据源类型
2. **Agent 工具调用循环**：LLM 自主决策调用工具，实现无显式指令的数据操作
3. **技能包标准**：结构化文件夹格式（SKILL.md + scripts），兼顾人类可读与机器可解析
4. **双重搜索策略**：向量语义搜索 + 关键词匹配降级，确保搜索可用性
5. **子进程沙盒**：技能脚本在隔离子进程中执行，支持超时控制
6. **技能-算子自动同步**：技能脚本变更自动同步到算子表，打通两大执行体系
7. **LLM 提供商抽象**：统一接口支持多种 LLM 提供商，运行时可动态切换
8. **流式优先架构**：多处端点支持 SSE 流式响应，提供实时反馈
9. **AST 脚本自省**：Python AST 解析自动提取函数签名和文档，零配置注册算子
10. **AI 调试助手**：Chat 风格交互式调试，AI 推理过程可视化，可自动执行/修改脚本
11. **文物领域特化**：内置中国朝代/年号映射，支持历史数据的智能排序和筛选
