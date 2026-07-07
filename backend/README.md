# DataCrab Backend

DataCrab 数据工程智能体后端服务

## 核心理念

通过对话处理数据，沉淀数据处理 Skill，形成数据生态，最终实现 AI 处理数据完全 Loop 化。

- **对话即处理**：LLM 理解意图、匹配 Skill、生成可执行代码
- **沉淀即资产**：处理过程沉淀为可复用 Skill，越用越聪明
- **生态即闭环**：DataProcessor + DataInspector 双智能体协作闭环
- **Loop 化**：AI 理解→执行→检查→自修复，全程无人干预（Self-healing Pipeline、Deep Agents）

## 功能特性

- 自然语言处理和意图识别
- 智能技能匹配和推荐
- 向量搜索系统
- 数据源管理
- 流程编排

## 技术栈

- FastAPI
- SQLAlchemy
- 智谱 GLM / 阿里百炼 / 硅基流动（均兼容 OpenAI API）
- Redis
- SQLite/PostgreSQL

## 安装

```bash
pip install -e .
```

## 运行

```bash
uvicorn app.main:app --reload
```
