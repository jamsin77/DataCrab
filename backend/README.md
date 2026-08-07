# DataCrab Backend

DataCrab 数据工程智能体后端服务

## 核心理念

通过对话处理数据，沉淀数据处理 Skill，形成数据生态，最终实现 AI 处理数据完全 Loop 化。

- **对话即处理**：LLM 理解意图、匹配 Skill、生成可执行代码
- **沉淀即资产**：处理过程沉淀为可复用 Skill，越用越聪明
- **生态即闭环**：DataProcessor + DataInspector 双智能体协作闭环
- **Loop 化**：AI 理解→执行→检查→自修复，全程无人干预（Self-healing Pipeline、Deep Agents）

## 功能特性

- 对话式数据交互（SSE 流式）+ 多智能体协作（DataProcessor → DataInspector，Handoff 由 RunTime 决策）
- 8 种数据源连接器（PG/MySQL/SQLite/CSV/Excel/OBS/HDFS/Chroma）+ 自定义连接器（AI 生成代码，沙箱加载）
- 技能/算子/流程全生命周期（CRUD + AI 生成/调试 + 自愈循环 + 经验库）
- 7 种写表策略 + 调度系统（Cron/间隔/手动 + 30s 定时扫描器）
- 文档知识库 RAG + 元数据管理（技术元数据自动同步 + 业务元数据 AI 补充）
- 视频处理（关键帧抽取 + 元数据提取）+ RBAC 权限（用户/角色/权限，view/use/manage 三级）

## 技术栈

- FastAPI + Uvicorn
- SQLAlchemy 2.0（async）
- pandas / numpy
- 智谱 GLM / 阿里百炼 / 硅基流动 / Azure / 自定义 OpenAI 兼容（`_default`/`_flash` 双模型 + 多模型降级链 + CircuitBreaker 熔断 + 视觉/嵌入按 provider 选）
- SQLite（开发）/ PostgreSQL 14+（生产）
- ChromaDB（文档知识库向量库）

## 安装

```bash
pip install -e .
```

## 运行

```bash
uvicorn app.main:app --reload
```
