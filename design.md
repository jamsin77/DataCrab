# DataCrab 技术架构设计文档

## 0. 核心理念

**通过对话处理数据，沉淀数据处理 Skill，形成数据生态，最终实现 AI 处理数据完全 Loop 化。**

| 阶段 | 理念 | 业界趋势 |
|------|------|---------|
| 对话即处理 | 自然语言代替编码，LLM 理解意图、匹配 Skill、生成代码 | Conversational Data Processing、Agentic UI |
| 沉淀即资产 | 每次处理沉淀为可复用 Skill，越用越聪明 | Skill-based Agent、Compound AI System |
| 生态即闭环 | Skill 积累形成生态，双智能体协作闭环 | Multi-Agent Collaboration |
| Loop 化 | AI 理解→执行→检查→自修复，全程无人干预 | Self-healing Pipeline、Full-loop Automation、Deep Agents |

Loop 化是终极目标：AI 在「执行 → 观测 → 修正」的循环中持续迭代，直到任务完成。多智能体 Handoff 机制和技能自我进化能力是这一理念的具体实践。

## 1. 系统架构概览

### 1.1 整体架构
采用分层微服务架构，支持本地单机部署和分布式部署两种模式。核心是ChatGPT风格的人机聊天交互界面，用户通过自然语言对话与系统交互处理数据。
```
┌───────────────────────────────────────────────────────────────┐
│                 人机交互界面 (HMI Interface)                  │
├───────────────────────────────────────────────────────────────┤
│ChatGPT风格对话界面                                            │
│- 简洁的聊天消息流                                             │
│- 自然语言对话输入                                             │
│- 智能意图识别和建议                                           │
│- 对话历史管理                                                 │
│- 多会话切换                                                   │
│- 流式响应展示                                                 │
│- 代码块高亮和复制                                             │
│- Markdown渲染                                                 │
└───────────────────────────────────────────────────────────────┘
                               │                               
                        WebSocket/HTTP                         
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                      前端应用 (Frontend)                      │
├───────────────────────────────────────────────────────────────┤
│               Vue 3 + Element Plus + TypeScript               │
└───────────────────────────────────────────────────────────────┘
                               │                               
                             HTTPS                             
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                       API网关 (Gateway)                       │
├───────────────────────────────────────────────────────────────┤
│           认证鉴权 | 限流熔断 | 路由转发 | 日志审计           │
└───────────────────────────────────────────────────────────────┘
                               │                               
                                                               
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                      业务服务 (Services)                      │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ 对话服务     │ 技能管理服务 │ 算子服务     │ 数据源服务     │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ ChatService  │ SkillManager │ OperatorSvc  │ DataSource     │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ 智能体服务   │ 调度服务     │ 权限服务     │ 元数据服务     │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ AgentRuntime │ Scheduler    │ Auth         │ Metadata       │
└──────────────┴──────────────┴──────────────┴────────────────┘
                               │                               
                                                               
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                       核心引擎 (Engine)                       │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ 智能体引擎   │ 技能执行引擎 │ 流程执行引擎 │ 调度引擎       │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ AgentEngine  │ SkillRunner  │ PipelineExec │ Sched Engine   │
└──────────────┴──────────────┴──────────────┴────────────────┘
                               │                               
                                                               
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                      数据存储 (Storage)                       │
├──────────────┬──────────────┬────────────────────────────────┤
│ SQLite/PG    │ 本地文件系统 │ 技能包目录                      │
├──────────────┼──────────────┼────────────────────────────────┤
│ 业务数据     │ 数据源文件   │ SKILL.md + scripts/             │
└──────────────┴──────────────┴────────────────────────────────┘
```

### 1.2 技术栈选型

#### 人机交互界面技术栈
- **框架**: Vue 3 + Composition API
- **UI组件**: Element Plus
- **状态管理**: Pinia
- **路由**: Vue Router 4
- **HTTP客户端**: Axios
- **实时通信**: EventSource (SSE流式响应)
- **Markdown渲染**: markdown-it + highlight.js
- **代码编辑**: Monaco Editor (代码块编辑)
- **数据可视化**: ECharts

#### 后端技术栈
- **语言**: Python 3.11+
- **Web框架**: FastAPI
- **ORM**: SQLAlchemy 2.0
- **异步支持**: asyncio + uvicorn
- **大模型集成**: 智谱GLM / 阿里百炼 / 硅基流动（均兼容 OpenAI API）

#### 数据存储
- **关系数据库**: SQLite（开发）/ PostgreSQL 14+（生产）
- **文件存储**: 本地文件系统

#### 基础设施
- **容器化**: Docker + Docker Compose（可选）
- **反向代理**: Nginx（生产部署）

## 2. 核心模块设计

### 2.1 人机交互界面模块

#### 2.1.1 界面架构设计
```
┌─────────────────────────────────────────────────────┐
│        ChatGPT风格对话界面 (Chat Interface)         │
├─────────────────────────────────────────────────────┤
│   ┌─────────────────────────────────────────────┐   │
│   │  主界面布局 (简洁单页面)                    │   │
│   │  - 左侧边栏 (会话历史列表、新建会话、设置)  │   │
│   │  - 中间聊天区域 (消息流、输入框)            │   │
│   │  - 顶部工具栏 (模型选择、清空会话、导出)    │   │
│   └─────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────┐   │
│   │  聊天消息区                                 │   │
│   │  - 用户消息 (右侧显示)                      │   │
│   │  - AI助手消息 (左侧显示，支持Markdown)      │   │
│   │  - 代码块 (语法高亮、复制按钮、执行按钮)    │   │
│   │  - 数据表格 (可排序、筛选、导出)            │   │
│   │  - 图表可视化 (ECharts交互图表)             │   │
│   │  - 流式响应 (打字机效果)                    │   │
│   └─────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────┐   │
│   │  输入区域                                   │   │
│   │  - 多行文本输入框 (支持Shift+Enter换行)     │   │
│   │  - 发送按钮 (Enter发送)                     │   │
│   │  - 停止生成按钮 (流式响应中断)              │   │
│   │  - 附件上传 (支持文件、数据源)              │   │
│   └─────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────┐   │
│   │  会话管理                                   │   │
│   │  - 会话列表 (按时间分组：今天、昨天、更早)  │   │
│   │  - 会话搜索和筛选                           │   │
│   │  - 会话重命名和删除                         │   │
│   │  - 会话导出和分享                           │   │
│   └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

#### 2.1.2 ChatGPT风格对话界面设计

界面设计原则：**简洁、以自然语言交互为核心**
##### 核心交互流程
```
用户输入自然语言 ─────────────────────────────────────────>

系统处理：1. 意图识别（数据处理、创建算子、创建Pipeline、查询数据）
2. 自动匹配技能/算子
3. 生成执行代码
4. 流式响应返回结果

AI回复：- 文本解释
- 可执行代码块（一键执行）
- 数据表格（可导出）- 图表可视化

关键边界：DataCrab 不能修改平台自身，但可以帮用户创建和修改用户自己的对话、算子、技能。
算子和技能中的脚本只能操作用户的业务数据，不能操作平台系统数据。
例外：用户可用自然语言添加自定义数据源连接器和自定义模型适配器（AI 生成代码，沙箱加载），这两项是唯一允许用户扩展的平台能力。

用户确认/调整 ─────────────────────────────────────────────>
```

##### 主要交互场景

**场景1：数据处理**
```
用户：帮我分析销售数据，统计每个地区的总销售额

AI：我理解您需要按地区统计销售额，正在处理...

    [执行代码] df.groupby('region')['sales'].sum()

    [结果表格]
    region    | sales
    ----------|-------
    北京      | 125000
    上海      | 98000

    [可视化图表] 显示柱状图...
```

**场景2：创建算子**
```
用户：创建一个算子，计算移动平均值
AI：正在为您创建算子...

    算子名称：moving_average
    参数：column（列名）、window（窗口大小，默认7）    已生成代码并测试通过，算子已注册。```

**场景3：创建Skill Pipeline**
```
用户：帮我创建一个数据分析流程：先清洗数据，再过滤异常值，最后统计
AI：正在创建Pipeline...

    Pipeline 名称：data_analysis_flow
    步骤：数据清洗 → 异常值过滤 → 统计分析
    
    Pipeline 已创建，可直接运行或保存为Skill。```

##### 界面布局（极简版）```
┌─────────────────────────────────────────────────────────────┐
│[新建会话]                                                   │
├─────────────────────────────────────────────────────────────┤
│会话列表                                                     │
│  • 今天                                                     │
│    • 销售数据分析                                           │
│    • 创建算子会话                                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│[消息流]                                                     │
│                                                             │
│用户：帮我分析销售数据...                                    │
│                                                             │
│AI：正在处理...                                              │
│    [代码块] [复制] [执行]                                   │
│    [结果表格] [导出]                                        │
│    [图表]                                                   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│[输入框] 输入消息...                                   [发送]│
└─────────────────────────────────────────────────────────────┘
```

##### 输入区域功能
- 多行文本输入（Shift+Enter换行）- 支持附件上传（数据文件）
- 快捷命令：`/create-operator`、`/create-pipeline`、`/run`

##### 消息展示功能
- Markdown渲染
- 代码块语法高亮 + 一键复制/执行
- 数据表格预览 + 导出
- 图表可视化 - 流式响应（打字机效果）

#### 2.1.4 数据探索面板设计

数据探索面板提供数据源连接、表结构查看、数据预览等功能。

##### 核心功能
- 数据源连接管理
- 表结构查看（字段、类型、描述）
- 数据预览（采样数据展示）
- 元数据搜索
- 浏览数据表时显示总行数："共 X 条，显示前 Y 行"（后端 `get_table_stats()` 提供总行数）

##### 界面布局（简化）
```
┌─────────────────────────────────────────────────────────────┐
│  数据源列表 │ 表列表 │ 表详情                            │
├─────────────┼────────┼─────────────────────────────────────┤
│  [销售数据库]│ sales  │ 字段列表:                          │
│  [用户数据库]│ users  │ - id (int) 主键                    │
│             │ orders │ - name (varchar)                   │
│             │        │ - created_at (datetime)            │
│             │        │                                    │
│             │        │ 数据预览: [查看]                    │
└─────────────┴────────┴─────────────────────────────────────┘
```

### 2.2 数据源管理模块
#### 2.2.1 架构设计
```
┌───────────────────────────────────────────────┐
│              DataSource Manager               │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  Connection Pool Manager              │   │
│   │  - 连接池管理                         │   │
│   │  - 连接健康检查                       │   │
│   │  - 连接复用                           │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Connector Registry                   │   │
│   │  - 内置连接器注册                     │   │
│   │  - 自定义连接器注册                   │   │
│   │  - 连接器生命周期管理                 │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Metadata Extractor                   │   │
│   │  - 技术元数据提取                     │   │
│   │  - 样本数据采集                       │   │
│   │  - 数据质量分析                       │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

#### 2.2.2 连接器插件机制```python
# 基础连接器接口class BaseConnector(ABC):
    @abstractmethod
    async def connect(self, config: dict) -> Connection:
        """建立连接"""
        pass
    
    @abstractmethod
    async def test_connection(self) -> bool:
        """测试连接"""
        pass
    
    @abstractmethod
    async def get_schema(self) -> List[TableSchema]:
        """获取数据源结构"""
        pass
    
    @abstractmethod
    async def execute_query(self, query: str) -> DataFrame:
        """执行查询"""
        pass
    
    @abstractmethod
    async def close(self):
        """关闭连接"""
        pass

# 内置连接器- DatabaseConnector (MySQL, PostgreSQL, Oracle, SQL Server)
- FileConnector (CSV, Excel, JSON, Parquet)
- APIConnector (REST API, GraphQL)
- BigDataConnector (Hive, Spark, Kafka)
- CloudConnector (S3, OSS, Azure Blob)
```

#### 2.2.3 数据源配置模型```python
class DataSource(Base):
    __tablename__ = "data_sources"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)  # mysql, postgres, api, file
    connection_config = Column(JSON, nullable=False)  # 加密存储
    metadata = Column(JSON)  # 技术元数据
    business_metadata = Column(JSON)  # 业务元数据    security_level = Column(String
    created_by = Column(UUID, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
```

### 2.3 自然语言处理模块

#### 2.3.1 NL处理流程
```
用户输入(自然语言)
    → 意图识别(Intent Recognition)
    → 实体提取(Entity Extraction)
    → 技能匹配(Skill Matching)
    → 代码生成(Code Generation)
    → 参数推理(Parameter Inference)
    → 执行计划(Execution Plan)
```

#### 2.3.2 大模型集成架构```python
class LLMManager:
    """大模型管理器"""
    
    def __init__(self):
        self.models = {
            "openai": OpenAIModel,
            "azure": AzureOpenAIModel,
            "local": LocalLLMModel,  # 支持本地模型
            "custom": CustomModel
        }
    
    async def process_natural_language(
        self,
        text: str,
        context: dict
    ) -> ProcessingResult:
        """处理自然语言输入"""
        
        # 1. 意图识别
        intent = await self.recognize_intent(text)
        
        # 2. 实体提取
        entities = await self.extract_entities(text)
        
        # 3. 生成处理流程(基于Skills)
        code = await self.generate_code(intent, entities, context)
        
        return ProcessingResult(
            intent=intent,
            entities=entities,
            code=code
        )
    
    async def chat(
        self,
        prompt: str,
        model: str = None,
        temperature: float = 0.7
    ) -> str:
        """与大模型对话"""
        model_config = self.get_model_config(model)
         response = await model_config.chat(prompt, temperature)
        return response
```

#### 2.3.3 大模型公开API

DataCrab 将底层大模型能力以 RESTful API 形式开放，提供文本嵌入向量等能力。

##### API 端点列表

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | /api/v1/llm/embeddings | 生成文本嵌入向量 | 需认证 |

##### 请求/响应格式

**嵌入向量** `POST /api/v1/llm/embeddings`
```json
// 请求
{"text": "要嵌入的文本"}

// 响应
{
    "embedding": [0.0023, -0.0091, ...],
    "dimensions": 1536
}
```

##### 调用示例（curl）

```bash
# 嵌入向量
curl -X POST http://localhost:8000/api/v1/llm/embeddings \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "要嵌入的文本"}'
```

##### 在算子和技能脚本中调用大模型

除了通过 HTTP API 对外开放，DataCrab 还将大模型能力注入到算子和技能的执行沙箱中，脚本代码可直接调用 `llm_chat()` 函数，无需走 HTTP 请求。

**注入方式**：
- **算子调试执行**（`exec()` 沙箱）：通过 `_build_operator_namespace()` 注入同步 `llm_chat` 函数，内部用 `_run_async_in_thread()` 调用 `llm_manager`
- **技能脚本执行**（`subprocess` 沙箱）：通过 `SKILL_RUNNER_TEMPLATE` 模板注入 `llm_chat` 函数，内部启动子进程调用 `llm_manager`

**函数签名**：
```python
def llm_chat(prompt, system_prompt=None, temperature=0.7, max_tokens=2000):
    """
    在算子/技能脚本中直接调用平台大模型

    参数:
        prompt: 用户消息（必填）
        system_prompt: 系统提示词，用于设定AI角色和规则（可选）
        temperature: 温度参数，0.0-2.0，越高越随机（默认0.7）
        max_tokens: 最大生成token数（默认2000）

    返回:
        str: 大模型的文本回复
    """
```

**算子脚本中使用示例**：
```python
import pandas as pd
from typing import Dict, Any

def translate_data(data, target_language="en"):
    """翻译数据中的文本列"""
    df = data if hasattr(data, 'columns') else pd.DataFrame(data)

    # 调用平台大模型翻译
    result = llm_chat(
        prompt=f"将以下JSON数据中的中文翻译为{target_language}，保持JSON结构不变：\n{df.to_json(orient='records')}",
        system_prompt="你是一个专业翻译助手，只返回翻译后的JSON，不要添加任何解释。",
        temperature=0.3
    )

    translated_df = pd.DataFrame(eval(result))
    return {"success": True, "data": translated_df.to_dict(orient="records")}
```

**技能脚本中使用示例**：
```python
def analyze_data(data, **kwargs):
    """用大模型分析数据"""
    import pandas as pd
    df = data if hasattr(data, 'columns') else pd.DataFrame(data)

    # 获取数据摘要
    summary = df.describe().to_string()

    # 调用平台大模型分析
    analysis = llm_chat(
        prompt=f"分析以下数据统计摘要，给出关键洞察和建议：\n{summary}",
        system_prompt="你是一个数据分析师，请用简洁的中文回答。",
        temperature=0.5
    )

    return {"analysis": analysis, "row_count": len(df)}
```

**安全边界**：
- `llm_chat` 只能调用平台配置的大模型，不能访问 API Key
- 技能脚本中的 `llm_chat` 通过子进程调用，与主进程隔离
- 算子调试中的 `llm_chat` 在线程中执行异步调用，有60秒超时限制

#### 2.3.4 Skills技能库
```python
class SkillLibrary:
    """技能库 - 核心组件"""
    
    def __init__(self, embedding_service):
        self.skills = {}  # 技能注册表
        self.embeddings = {}  # 技能向量索引        self.embedding_service = embeddin
    
    async def register_skill(self, skill: Skill):
        """注册技能"""
        # 生成技能描述向量        embedding = await self.embedding_service.embed(
            skill.description + " " + skill.get_usage_example()
        )
        self.skills[skill.id] = skill
        self.embeddings[skill.id] = embedding
    
    async def search_similar(
        self,
        query: str,
        top_k: int = 5,
        filters: dict = None
    ) -> List[Skill]:
        """搜索相似技能"""
        # 生成查询向量
        query_embedding = await self.embedding_service.embed(query)
        
        # 向量相似度搜索        similarities = self.cosine_similarity(query_embedding,
        
        # 过滤和排序        filtered_skills = self.filter_skills(similarities, filte
        
        return filtered_skills[:top_k]
    
    async def get_skill(self, skill_id: str) -> Skill:
        """获取技能"""
        return self.skills.get(skill_id)
    
    async def get_skill_executor(self, skill_id: str):
        """获取技能执行器"""
        skill = await self.get_skill(skill_id)
        return skill.get_executor()
```

#### 2.3.4 技能定义模型```python
class Skill(Base):
    __tablename__ = "skills"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200))
    description = Column(Text, nullable=False)
    
    # 技能类型    skill_type = Column(String(50))  # operator, function, pipeline
    
    # 输入输出定义
    inputs = Column(JSON)
    """
    {
        "data": {
            "type": "DataFrame",
            "description": "输入数据",
            "required": true
        }
    }
    """
    
    outputs = Column(JSON)
    """
    {
        "result": {
            "type": "DataFrame",
            "description": "处理结果"
        }
    }
    """
    
    # 参数定义
    parameters = Column(JSON)
    """
    {
        "columns": {
            "type": "list",
            "description": "选择的列",
            "required": true,
            "default": []
        }
    }
    """
    
    # 执行配置
    executor_config = Column(JSON)
    """
    {
        "type": "python_function",
        "module": "app.skills.operators",
        "function": "select_operator"
    }
    """
    
    # 使用示例(用于向量检索)
    usage_examples = Column(JSON)
    """
    [
        "选择用户表中的姓名和年龄",
        "从订单数据中提取订单号和金额",
        "筛选出销售数据中的商品名称和销售额"
    ]
    """
    
    # 技能标签，用于分类和搜索
    tags = Column(JSON)
    """
    ["数据选择", "列操作", "基础算子"]
    """
    
    # 技能分类    category = Column(String(50))
    """
    transform, aggregate, filter, join, analyze
    """
    
    # 元数据    version = Column(String(20), default="1.0.0")
    author = Column(UUID, ForeignKey("users.id"))
    
    # 权限
    visibility = Column(String(20))  # private, public, shared
    
    # 统计信息
    usage_count = Column(Integer, default=0)
    success_rate = Column(Float, default=1.0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    def get_executor(self):
        """获取技能执行器"""
        config = self.executor_config
        
        if config["type"] == "python_function":
            return self._get_python_executor(config)
        elif config["type"] == "lambda":
            return self._get_lambda_executor(config)
        else:
            raise ValueError(f"Unsupported executor type: {config['type']}")
    
    def _get_python_executor(self, config):
        """获取Python函数执行器"""
        module = importlib.import_module(config["module"])
        return getattr(module, config["function"])
    
    def _get_lambda_executor(self, config):
        """获取Lambda执行器"""
        return eval(config["code"])
```

#### 2.3.5 Agent 迭代与并行执行增强

- **动态轮次预算**：按任务复杂度分配迭代上限（simple=15/medium=25/complex=40），替代固定上限
- **并行工具调用**：新增 `_execute_tool_calls_parallel()` 函数，当 LLM 返回多个 tool_call 时，使用 `asyncio.gather()` 并行执行，提升执行效率
- 并行执行结果按 tool_call 顺序汇总后统一返回给 LLM，确保对话上下文完整性
- **输出长度升级**：`finish_reason=length` 时自动提升 max_tokens（3000→6000→12000）
- **上下文压力告警**：token 超 50% 注入 Level-1 提示，超 60% 注入 Level-2 紧急提示
- **三级反幻觉注入**：basic/standard/strict 按 Agent 角色自动选级（Inspector=strict, Processor=standard）
- **工具结果 LRU 缓存**：只读工具会话内去重（30 分钟 TTL，50 条上限，100 用户 LRU）

### 2.4 算子管理模块

#### 2.4.1 算子架构

算子以 Python 脚本为核心，支持上传 .py 文件、AI 自然语言生成、调试执行、修改和克隆。

```
┌─────────────────────────────────────────────────────────────────┐
│                    Operator Framework                           │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────┐  ┌───────────────────────────────┐  │
│  │  Python Script Parser │  │  Operator Registry             │  │
│  │  - 函数签名提取       │  │  - 算子注册/发现              │  │
│  │  - 参数类型推断       │  │  - 版本管理                   │  │
│  │  - Docstring 解析     │  │  - 分类筛选                   │  │
│  └───────────────────────┘  └───────────────────────────────┘  │
│  ┌───────────────────────┐  ┌───────────────────────────────┐  │
│  │  AI Generator          │  │  Debug Executor               │  │
│  │  - 自然语言生成脚本    │  │  - 沙箱执行 Python 脚本       │  │
│  │  - 自然语言修改脚本    │  │  - 参数注入 (DataFrame)       │  │
│  │  - LLM 集成            │  │  - 结果可视化                 │  │
│  └───────────────────────┘  └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.4.2 算子定义模型

```python
class Operator(Base):
    __tablename__ = "operators"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)
    category = Column(String(50))  # transform, aggregate, filter, join, ai_generated
    
    # 输入输出定义
    inputs = Column(JSON)   # [{"name": "data", "type": "DataFrame", "required": true}]
    outputs = Column(JSON)  # [{"name": "result", "type": "DataFrame"}]
    
    # 参数定义
    parameters = Column(JSON)  # [{"name": "columns", "type": "list", "required": true}]
    
    # 执行配置
    execution_config = Column(JSON)  # {"type": "python_script"}
    code_template = Column(Text)     # 代码模板（兼容旧版）
    
    # Python 脚本相关字段 (核心)
    script_content = Column(Text)        # 完整 Python 脚本内容
    script_filename = Column(String(200)) # 脚本文件名
    function_name = Column(String(100))   # 入口函数名
    
    # 元数据
    version = Column(String(20), default="1.0.0")
    tags = Column(JSON)
    author = Column(UUID, ForeignKey("users.id"))
    
    # 权限
    visibility = Column(String(20))  # private, public, shared
    permissions = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

#### 2.4.3 内置算子列表

```python
# 数据转换算子
- SelectOperator: 列选择
- FilterOperator: 数据过滤
- MapOperator: 数据映射
- RenameOperator: 列重命名
- TypeConvertOperator: 类型转换

# 数据聚合算子
- GroupByOperator: 分组聚合
- PivotOperator: 数据透视
- AggregateOperator: 聚合计算

# 数据连接算子
- JoinOperator: 表连接
- UnionOperator: 数据合并
- ConcatOperator: 数据拼接

# 数据清洗算子
- DropNAOperator: 删除空值
- FillNAOperator: 填充空值
- DuplicateOperator: 去重
- OutlierOperator: 异常值处理

# 数据分析算子
- StatisticsOperator: 统计分析
- CorrelationOperator: 相关性分析
- DistributionOperator: 分布分析
```

#### 2.4.4 算子管理功能

算子管理页面提供以下功能：

##### 2.4.4.1 上传 Python 脚本
用户上传 .py 文件 → Python Script Parser 解析函数签名 → 自动提取参数类型/默认值/描述 → 生成算子

**解析流程**：
```
上传 .py 文件
    ↓
parse_python_script() 解析
    ↓
提取 function_name, inputs, outputs, parameters
    ↓
创建 Operator 记录（script_content 存储完整脚本）
```

**API 端点**: `POST /operators/upload` (multipart/form-data)

##### 2.4.4.2 AI 生成算子
用户输入自然语言描述 → LLM 生成 Python 脚本 → 解析验证 → 创建算子 → 自动跳转调试页面

**SYSTEM_PROMPT 增强**：
- 包含完整 few-shot 示例（如 `filter_expensive_products`），展示参数提取、数据查询、返回格式的完整流程
- 通过 `_build_datasource_info()` 动态注入用户数据源信息（可用数据源名称、表名、字段结构），让 LLM 生成可立即执行的脚本
- 注入经验总结（从用户技能 SKILL.md 的 `## 常见问题与经验` 章节收集），避免重复犯错

**API 端点**: `POST /operators/generate`
**请求体**:
```json
{
    "prompt": "按照年代筛选文物数据，支持根据数据源名称查询，返回前100条"
}
```

**实现**:
```python
@router.post("/generate")
async def generate_operator(request: OperatorGenerateRequest):
    # 1. 调用 LLM 生成 Python 代码
    raw_code = await llm_manager.chat_with_messages(messages)
    
    # 2. 清理 markdown 标记
    script_content = clean_code_blocks(raw_code)
    
    # 3. 解析脚本提取函数信息
    parsed = parse_python_script(script_content)
    
    # 4. 创建算子记录
    operator = Operator(
        name=func_name,
        script_content=script_content,
        function_name=func_name,
        inputs=parsed["inputs"],
        outputs=parsed["outputs"],
        parameters=parsed["parameters"],
        category="ai_generated",
        tags=["ai_generated"]
    )
    db.add(operator)
    return operator
```

##### 2.4.4.3 AI 修改算子
选择已有算子 → 输入修改指令 → LLM 基于原脚本修改 → **自动验证修改是否正确** → 覆盖更新 → 自动跳转调试页面

**修改后必验证**：修改算子脚本后，系统必须自动调用调试端点（POST /operators/debug）验证修改未引入错误。如果验证失败，应提示用户并提供修复建议。

**输出默认同源**：算子生成新文件时，如果未指定输出路径，默认保存到 DataSource（数据源）指定的文件路径下。

**自动验证与 LLM 修复循环**：修改算子脚本后，系统自动执行 `exec()` 验证脚本语法和函数可调用性。如果验证失败，自动调用 LLM 修复脚本（最多2轮），每轮将错误信息反馈给 LLM 重新生成。辅助函数包括：
- `_validate_operator_script(script_content)`: 编译+exec验证脚本语法、提取函数签名
- `_llm_fix_operator_script(original_script, error_message, instruction)`: 将原脚本+错误信息+修改指令传给 LLM，生成修复后脚本
- `_strip_code_fences(raw_code)`: 清理 LLM 输出中的 markdown 代码围栏（```python ... ```）

**API 端点**: `POST /operators/{operator_id}/modify`
**请求体**:
```json
{
    "instruction": "增加数量限制参数，默认返回50条"
}
```

**实现**:
```python
@router.post("/{operator_id}/modify")
async def modify_operator(operator_id, request: OperatorModifyRequest):
    # 1. 获取原脚本
    operator = get_operator(operator_id)
    
    # 2. 构建 prompt 包含原脚本 + 修改指令
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"原脚本:
{operator.script_content}
修改要求:
{request.instruction}"}
    ]
    
    # 3. LLM 生成修改后的脚本
    raw_code = await llm_manager.chat_with_messages(messages)
    
    # 4. 解析并更新
    parsed = parse_python_script(clean_code_blocks(raw_code))
    operator.script_content = clean_code_blocks(raw_code)
    operator.function_name = parsed["function_name"]
    operator.inputs = parsed["inputs"]
    operator.outputs = parsed["outputs"]
    operator.parameters = parsed["parameters"]
    return operator
```

##### 2.4.4.4 克隆算子（另存为）
选择已有算子 → 输入新名称 → 复制所有配置和脚本 → 生成独立的新算子

**API 端点**: `POST /operators/{operator_id}/clone`
**请求体**:
```json
{
    "name": "新算子名称"
}
```

**实现**:
```python
@router.post("/{operator_id}/clone")
async def clone_operator(operator_id, request: OperatorCloneRequest):
    operator = get_operator(operator_id)
    clone = Operator(
        name=request.name,
        display_name=request.name,
        description=operator.description,
        category=operator.category,
        inputs=operator.inputs,
        outputs=operator.outputs,
        parameters=operator.parameters,
        execution_config=operator.execution_config,
        script_content=operator.script_content,   # 复制脚本
        script_filename=f"{request.name}.py",
        function_name=operator.function_name,
        tags=operator.tags,
        visibility=operator.visibility
    )
    db.add(clone)
    return clone
```

##### 2.4.4.5 算子调试
点击调试按钮 → 弹窗打开 → 双栏布局：左侧上方参数面板 + 下方脚本编辑区，右侧 AI 代码助手聊天面板 → 填写参数并执行 → 展示结果/错误 → 可通过 AI 助手调试和修改代码

**AI 代码助手**：右侧 ChatGPT 风格对话界面，AI 可分析代码逻辑、修复 bug、优化代码、直接修改脚本（输出 python 围栏包裹的完整脚本后自动更新数据库）。支持推理过程展示（蓝色卡片），自动执行/修改脚本。

**交互增强**：
- 所有输入字段支持 ↑↓ 箭头切换历史输入（localStorage 持久化，最多100条）
- AI 生成/修改对话框也支持 ↑↓ 历史切换
- 执行结果（标准输出、返回结果）自动展开显示，不再折叠
- 所有对话框添加 `close-on-press-escape="false"`，防止焦点离开时误关闭
- placeholder 文本自动换行（CSS `white-space: pre-wrap; word-break: break-all`）

**API 端点**: 
- `POST /operators/{id}/debug` - 执行调试
- `POST /operators/{id}/debug-chat` - AI 代码调试助手（SSE流式，含推理过程）

**调试界面布局**:
```
┌──────────────────────────────────────────────────────────────────┐
│  调试: 算子名称                                        [关闭 X]  │
├────────────────────────────────┬─────────────────────────────────┤
│  ┌──────────────────────────┐  │  AI 代码助手                    │
│  │ 参数面板                 │  │  ┌───────────────────────────┐  │
│  │ func_name(param1, ...)   │  │  │  推理过程（蓝色卡片）       │  │
│  │ 入参: data [DataFrame]   │  │  │  🔄 分析脚本逻辑...        │  │
│  │ 可选参数: limit=100      │  │  ├───────────────────────────┤  │
│  │ [执行调试]               │  │  │  AI 回复                  │  │
│  ├──────────────────────────┤  │  │  建议修改第23行...         │  │
│  │ 脚本编辑区               │  │  │  [代码已更新]              │  │
│  │ def filter_data(df, ...):│  │  ├───────────────────────────┤  │
│  │     ...                  │  │  │  [输入调试指令...]  [发送] │  │
│  └──────────────────────────┘  │  └───────────────────────────┘  │
│  ┌──────────────────────────┐  │                                 │
│  │ 执行结果（自动展开）      │  │                                 │
│  │ ✅ 成功 120ms            │  │                                 │
│  │ 标准输出: ...            │  │                                 │
│  │ 返回结果: ...            │  │                                 │
│  └──────────────────────────┘  │                                 │
└────────────────────────────────┴─────────────────────────────────┘
```

**debug-chat 上下文传递**：
- 前端自动将左侧面板的输入参数值、执行结果（成功/失败/错误信息）作为 context 传入后端
- 后端将上下文附加到用户消息中，让 AI 了解当前调试状态
- AI 输出含 ```python 围栏的完整脚本时，后端自动解析并更新算子的 script_content

**调试执行流程**:
```
用户点击"执行调试"
    ↓
POST /operators/debug {operator_id, params, script_content}
    ↓
后端构建执行命名空间（注入 query_table_data, get_table_schema 等工具函数）
    ↓
exec() 执行脚本 + 调用入口函数
    ↓
返回结果：{success, stdout, result, error, execution_time_ms}
```

**Debug Executor 核心实现**:
```python
# 工具函数注入 - 在算子执行环境中提供数据查询能力
def _build_operator_namespace(current_user_id):
    def query_table_data(datasource_id, table_name, **kwargs):
        args = {"datasource_id": str(datasource_id), "table_name": table_name, **kwargs}
        # 在独立线程中通过 execute_shared_tool 执行异步数据库查询
        async def _run():
            async with async_session() as db:
                from app.services.shared_tools import execute_shared_tool
                return await execute_shared_tool("query_table_data", args, db, current_user_id)
        result = json.loads(_run_async_in_thread(_run()))
        return pd.DataFrame(result["rows"], columns=result["columns"])

    def get_table_schema(datasource_id, table_name):
        args = {"datasource_id": str(datasource_id), "table_name": table_name}
        async def _run():
            async with async_session() as db:
                from app.services.shared_tools import execute_shared_tool
                return await execute_shared_tool("get_table_schema", args, db, current_user_id)
        return json.loads(_run_async_in_thread(_run()))

    return {
        "pd": pd,
        "query_table_data": query_table_data,
        "get_table_schema": get_table_schema,
        "get_datasource_id_by_name": get_datasource_id_by_name,
    }
```

##### 2.4.4.6 下载脚本
点击下载按钮 → 下载 .py 文件（script_filename 作为文件名，script_content 作为内容）

**API 端点**: `GET /operators/{operator_id}/download`

##### 2.4.4.7 算子管理 UI

页面布局：
```
┌──────────────────────────────────────────────────────────────┐
│ [上传Python脚本] [AI生成算子]  [分类筛选▼]  [搜索算子...]    │
├──────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ 算子卡片 1      │  │ 算子卡片 2      │  │ 算子卡片 3    │ │
│  │ 名称: xxx       │  │ 名称: xxx       │  │               │ │
│  │ 描述: xxx       │  │ 描述: xxx       │  │               │ │
│  │ [param1] [p2]   │  │ [param1]        │  │               │ │
│  │                 │  │                 │  │               │ │
│  │ [调试][下载]    │  │ [调试][下载]    │  │               │ │
│  │ [修改][另存为]  │  │ [修改][另存为]  │  │               │ │
│  │ [删除]          │  │ [删除]          │  │               │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

卡片按钮说明：
| 按钮 | 功能 |
|------|------|
| 🔵 调试 | 打开右侧抽屉，编辑脚本并调试执行 |
| ⚪ 下载 | 下载 .py 脚本文件 |
| 🟠 修改 | AI 根据自然语言指令修改脚本 |
| ⚫ 另存为 | 复制算子和脚本为新的独立算子 |
| 🔴 删除 | 删除算子 |


### 2.5 Skill 技能管理模块

#### 2.5.1 设计理念

Skill（技能）是 DataCrab 遵循 Agent Skills 开放标准的模块化能力包。每个 Skill 是一个独立的文件夹，包含以下结构：

```
SKILL.md          # 核心指令文档（YAML 元数据 + Markdown 指令）
scripts/          # 可执行 Python 脚本
  main.py         # 主处理脚本
references/       # 参考资料
assets/           # 静态资源
```

与 Operator（算子）的关系：
- **Operator**: 底层技术组件，纯 Python 函数，无业务描述，直接执行
- **Skill**: 业务语义封装，有自然语言描述，支持向量搜索，可组合为 Pipeline
- Skill 可以引用 Operator 作为执行逻辑，也可以定义自己的脚本

#### 2.5.2 数据模型

```python
class Skill(Base):
    """技能模型 - 管理 Skill 包（文件夹）"""
    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)

    skill_path = Column(String(500))  # 磁盘存储路径

    tags = Column(JSON)               # 标签列表
    category = Column(String(50), index=True)  # 分类

    version = Column(String(20), default="1.0.0")
    author = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    visibility = Column(String(20), index=True)  # public/private

    usage_count = Column(Integer, default=0)
    success_rate = Column(Float, default=1.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

#### 2.5.3 SKILL.md 格式规范

SKILL.md 是 Skill 的核心文档，采用 YAML front matter + Markdown 格式：

```markdown
---
name: skill-name
description: 技能描述
category: data_cleaning
tags: [filter, transform]
---

# 技能名称

## 功能说明
描述技能的功能...

## 使用方式
说明如何使用...

## 脚本说明
- main.py: 主处理脚本
- helper.py: 辅助函数

## 参数规范
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| column | string | 是 | 列名 |
| limit | int | 否 | 限制行数 |
```

#### 2.5.4 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/skills | 获取技能列表（支持分类筛选） |
| GET | /api/v1/skills/categories | 获取所有分类 |
| GET | /api/v1/skills/{id} | 获取技能详情（含 SKILL.md、脚本列表） |
| POST | /api/v1/skills | 创建技能 |
| PUT | /api/v1/skills/{id} | 更新技能元数据 |
| DELETE | /api/v1/skills/{id} | 删除技能（含磁盘文件） |
| POST | /api/v1/skills/upload | 上传 Skill 包（.zip 格式） |
| GET | /api/v1/skills/{id}/download | 下载 Skill 包（.zip 格式） |
| GET | /api/v1/skills/{id}/skill-md | 获取 SKILL.md 内容 |
| PUT | /api/v1/skills/{id}/skill-md | 更新 SKILL.md 内容 |
| GET | /api/v1/skills/{id}/scripts | 获取脚本列表 |
| GET | /api/v1/skills/{id}/scripts/{name} | 获取指定脚本内容 |
| PUT | /api/v1/skills/{id}/scripts/{name} | 更新或创建脚本 |
| DELETE | /api/v1/skills/{id}/scripts/{name} | 删除脚本 |
| POST | /api/v1/skills/{id}/run | 执行 Skill 脚本 |
| POST | /api/v1/skills/{id}/run-stream | 执行 Skill 脚本（SSE 流式，实时推送执行状态） |
| POST | /api/v1/skills/{id}/run-nl | 自然语言执行 Skill（LLM 推断参数后运行） |
| POST | /api/v1/skills/{id}/run-nl-stream | 自然语言执行 Skill（SSE 流式，含推理过程） |
| POST | /api/v1/skills/{id}/modify-stream | AI 修改技能（SSE 流式，含思考过程） |
| POST | /api/v1/skills/{id}/debug-chat | AI 调试助手（SSE 流式，支持推理过程展示、自动执行/修改脚本） |
| POST | /api/v1/skills/generate | AI 生成完整 Skill 包 |
| POST | /api/v1/skills/{id}/clone | 克隆技能 |
| POST | /api/v1/skills/search | 搜索技能 |
| POST | /api/v1/skills/{id}/summarize-errors | AI 分析错误日志，生成经验总结并写入 SKILL.md |

#### 2.5.5 核心服务

##### skill_parser.py - SKILL.md 解析器
- parse_skill_md(): 解析 YAML front matter + Markdown 内容
- build_skill_md(): 构建完整的 SKILL.md 文件
- get_skill_info_from_path(): 从文件夹读取 Skill 基本信息
- read_skill_md() / write_skill_md(): 读写 SKILL.md
- read_skill_script() / write_skill_script(): 读写脚本文件
- list_skill_scripts(): 列出所有脚本文件

##### skill_runner.py - 沙箱执行器
在独立子进程中执行 Skill 脚本，支持：
- 注入输入数据（DataFrame 格式）
- 注入参数（parameters dict）
- 内置工具函数：query_table_data(), get_table_schema(), get_datasource_id_by_name()
- 自动检测脚本中的主函数名（通过 AST 解析）
- 超时控制（默认 60 秒，可通过 SKILL_RUNNER_TIMEOUT 配置）
- 结果捕获：通过 __RESULT__ 标记解析返回值

##### skill_creator.py - AI 生成器
- generate_skill() / generate_skill_stream(): 根据自然语言描述生成完整 Skill 包
  - 新增 `datasource_info` 参数：动态查询用户数据源信息（名称、表名、字段结构），替代硬编码数据源名称
  - 新增 `lessons` 参数：注入同类技能经验总结（通过 `_collect_all_lessons()` 收集），让 LLM 参考历史经验避免重复犯错
- Skill Creator 系统提示词包含：
  - SKILL.md 编写规范
  - 脚本编写规范（pandas 处理、类型注解、边界处理）
  - 内置工具函数说明
  - 完整 few-shot 示例（filter-by-dynasty skill package），展示从描述到 SKILL.md + 脚本的完整生成流程
  - 数据源参考信息（通过 datasource_info 参数动态注入，移除硬编码数据源名称）
- create_skill_on_disk(): 在磁盘创建 Skill 文件夹结构

##### skill_library.py - 技能库
- VectorIndex: 基于 numpy 的向量索引，支持：
  - 向量归一化
  - 余弦相似度搜索
  - 向量增删改
- SkillLibrary: 技能库管理，包含：
  - 向量索引构建和搜索
  - 内置技能示例（select, filter, sort, groupby, aggregate, join, fillna, dropna, rename, stats）
  - 技能注册和检索机制

##### skill_executor.py - 执行上下文与结果数据结构
- ExecutionContext: 执行上下文（会话ID、用户ID、变量、DataFrame）
- ExecutionResult: 执行结果（success/output/error/logs/metrics）
- 供 nl_data_processor 使用；SkillExecutor 类及内置技能函数已删除（无人调用）

#### 2.5.6 前端界面

SkillView.vue 提供完整的技能管理界面：
- 技能卡片网格布局（支持分类筛选和文本搜索）
- 上传 Skill 包对话框（.zip 拖拽上传，自动解析 SKILL.md）
- AI 生成技能对话框（输入自然语言描述，AI 自动生成完整 Skill 包）
- 技能详情抽屉（三个 Tab 页）：
  - SKILL.md Tab：编辑和预览 SKILL.md 内容
  - 脚本列表 Tab：查看/编辑脚本，可从脚本直接打开调试
  - 属性 Tab：查看技能元数据
- 自然语言修改（AI 修改 Drawer，流式展示思考/生成过程）
- 技能调试界面（合并执行与 AI 调试助手）：
  - 左侧执行面板：自然语言 / 命令行 / JSON 参数三种输入方式，执行结果实时展示
  - 右侧 AI 调试面板：ChatGPT 风格对话，AI 可自动执行脚本或修改脚本
  - AI 回复展示推理过程（蓝色推理卡片），含旋转图标和思考内容
  - SSE 流式响应，实时展示推理和回复内容
- 技能执行支持停止/暂停（前端 AbortController + 后端 asyncio.create_subprocess_exec）
- 技能自我进化：错误日志自动记录到 error_log.json，技能详情页"总结经验"按钮调用 summarize-errors 端点，经验总结写入 SKILL.md
- 详情 Drawer 和生成对话框添加 `close-on-press-escape="false"`，防止焦点离开时误关闭
- 技能下载（导出为 .zip）和删除功能

#### 2.5.7 技能执行与调试流程

##### 基础执行流程
```
客户端请求 POST /api/v1/skills/{id}/run
  → skill_runner.run_skill_script()
  → 构建 SKILL_RUNNER_TEMPLATE（注入数据、参数、工具函数）
  → subprocess.run() 在独立 Python 进程中执行
  → 解析 stdout 中的 __RESULT__ 标记获取返回值
  → _sanitize_nans() 递归替换 NaN/Infinity 为 None
  → 返回 SkillRunResponse { success, result, stdout, execution_time_ms }
```

##### SSE 流式执行
```
POST /api/v1/skills/{id}/run-stream
  → SSE 事件流：executing → done/error
  → 实时推送执行状态和结果
```

##### 自然语言执行
```
POST /api/v1/skills/{id}/run-nl-stream
  → LLM 推断执行参数（thinking → content → inferred_params）
  → 自动注入 datasource/tables 参数
  → 执行脚本并流式返回结果
```

##### AI 调试助手
```
POST /api/v1/skills/{id}/debug-chat
  → 系统提示词包含 SKILL.md + 脚本内容上下文
  → LLM 支持输出动作 JSON：{"action": "run"} 触发执行，{"action": "modify_script"} 触发脚本修改
  → 修改后必验证：modify_script 后必须自动 run 验证
  → 输出默认同源：生成新文件时默认保存到 DataSource（数据源）指定的文件路径下
  → SSE 事件流：thinking（推理过程）→ content（回复内容）→ run_result/script_updated → done
  → 前端展示推理过程卡片（蓝色边框，旋转图标 + 思考内容）
  → 支持多轮对话，上下文包含历史消息和执行结果
```

##### 调试界面布局
```
┌──────────────────────────────────────────────────────────────────┐
│  调试: 技能名称                                      [关闭 X]  │
├────────────────────────────────┬─────────────────────────────────┤
│  执行面板                      │  AI 调试助手                    │
│  ┌──────────────────────────┐  │  ┌───────────────────────────┐  │
│  │ [自然语言][命令行][JSON] │  │  │  推理过程                  │  │
│  │                          │  │  │  🔄 AI 正在分析脚本...     │  │
│  │  输入区域                │  │  │  检查到第23行可能有...     │  │
│  │  [执行]                  │  │  ├───────────────────────────┤  │
│  ├──────────────────────────┤  │  │  AI 回复                  │  │
│  │  执行结果                │  │  │  建议将 limit 参数...      │  │
│  │  ✅ 执行成功 120ms       │  │  │  [执行成功] [脚本已更新]   │  │
│  │  返回数据: ...           │  │  ├───────────────────────────┤  │
│  └──────────────────────────┘  │  │  [输入调试指令...]  [发送] │  │
│                                │  └───────────────────────────┘  │
└────────────────────────────────┴─────────────────────────────────┘
```

#### 2.5.8 自我进化经验库（算子+技能统一）

算子与技能共用统一的自我进化机制（`app/services/experience.py`）：执行失败自动记录**反例**，修错后成功自动采集**正例**，由 LLM 归纳为「常见错误+成功模式」经验，写入统一 `experience.json` 并注入后续生成/修改/调试提示词，形成"执行→记录→归纳→注入"闭环。

- 技能：`{skill_path}/experience.json`（兼容旧 `error_log.json` 读取，经验镜像写入 SKILL.md `## 常见问题与经验`）
- 算子：`backend/data/operator_experiences/{operator_id}/experience.json`（算子无文件夹，统一存盘）
- `experience.json` 结构：`{negative:[...], positive:[...], lessons:""}`
- 采集规则：失败→`append_negative`；成功且历史有反例（即修错后成功）→`append_positive`
- 归纳：`POST /operators/{id}/summarize-experience`、`POST /skills/{id}/summarize-errors`，LLM 同时分析反例+正例
- 注入：`collect_all_lessons(db, user_id)` 收集该用户全部算子+技能经验，注入算子 generate/modify/debug-chat 与技能 skill_creator 提示词

##### 反例（错误日志）自动记录

每次执行失败，系统自动将错误信息追加到经验库的 `negative` 列表（最多保留200条，FIFO）：

```json
[
  {
    "timestamp": "2026-06-27T10:30:00Z",
    "script_name": "main.py",
    "error_type": "KeyError",
    "error_message": "'column_name' not in index",
    "parameters": {"datasource_id": "xxx", "table_name": "sales"},
    "stdout_preview": "Processing data...\nError at line 23:",
    "source": "run"
  }
]
```

- `source` 字段标识错误来源：`run`（直接执行）、`debug`（调试执行）、`nl`（自然语言执行）
- 日志文件路径：`{skill_path}/error_log.json`

##### LLM 总结经验

`POST /api/v1/skills/{id}/summarize-errors` 端点：
1. 读取技能的 `error_log.json`
2. 调用 LLM 分析错误规律（高频错误类型、常见原因、修复建议）
3. 将总结写入 SKILL.md 的 `## 常见问题与经验` 章节（如已有则更新）
4. 返回总结内容给前端

##### 经验注入

- **生成新技能时**：`_collect_all_lessons()` 函数收集当前用户所有技能 SKILL.md 中的 `## 常见问题与经验` 章节内容，作为 `lessons` 参数注入 skill_creator 提示词，让 LLM 参考历史经验避免重复犯错
- **调试助手**：调试助手的系统提示词中注入 `read_lessons()` 读取当前技能的经验总结，让 AI 参考历史经验指导调试

##### 前端"总结经验"按钮

技能详情页增加"总结经验"按钮，点击后调用 `POST /api/v1/skills/{id}/summarize-errors` 端点，展示 LLM 生成的经验总结，并自动写入 SKILL.md。

#### 2.5.9 内置技能列表

SkillLibrary 预置了以下数据处理技能：

| 技能名称 | 分类 | 功能 |
|----------|------|------|
| select | transform | 选择指定列 |
| filter | transform | 按条件过滤行 |
| sort | transform | 按列排序 |
| groupby | aggregate | 分组聚合 |
| aggregate | aggregate | 聚合统计 |
| join | fusion | 表连接 |
| fillna | cleaning | 填充缺失值 |
| dropna | cleaning | 删除缺失值 |
| rename | transform | 重命名列 |
| stats | analysis | 统计描述 |

### 2.6 流程模块（Pipeline）

#### 2.6.1 设计理念

**流程（Pipeline）是 DataCrab 的核心编排概念——每个流程就是一个 Python 主函数。**

抛弃旧的 DAG 节点/边模型，流程的本质是：**一个 Python 主函数 + 它调用的 Skill 脚本**。用户只需理解一个 Python 函数就能掌握整个数据处理逻辑。

**核心原则**：
- **一个流程 = 一个 Python 主函数**：主函数负责编排数据读取、处理、写入的完整逻辑
- **Skill → 主函数转换**：一键将 Skill 脚本转换为可独立运行的 Python 主函数，主函数调用 Skill 的脚本来完成工作
- **代码可视化**：前端展示主函数源码（语法高亮），并解析出主函数对 Skill 脚本的调用关系图
- **直接执行**：无需 DAG 引擎，直接运行主函数即可得到结果

```
┌──────────────────────────────────────────────────────────┐
│   流程: 文物数据清洗                                      │
│                                                          │
│   def main(datasource, tables, primary_key, options):    │
│       # 1. 读取数据                                       │
│       from app.services.connectors import ConnectorManager │
│       df = ConnectorManager.read_table(datasource, tables) │
│                                                          │
│       # 2. 调用 Skill 脚本处理                            │
│       result = clean_data_main(df, primary_key, options) │
│                                                          │
│       # 3. 写入结果                                       │
│       ConnectorManager.write_table(datasource, tables,   │
│                                    result)               │
│       return result                                      │
│                                                          │
│   调用关系:  [Skill: data-cleaning-deduplication]        │
│             main() ──▶ scripts/main.py :: clean_data_main()│
└──────────────────────────────────────────────────────────┘
```

#### 2.6.2 与 Skill 的关系

| 维度 | Skill | Pipeline（流程） |
|------|-------|-----------------|
| **本质** | 模块化能力包（SKILL.md + scripts/） | 可执行的完整 Python 程序 |
| **组成** | 文档 + 脚本 + 参考资料 | Python 主函数源码 |
| **运行方式** | 子进程沙箱执行单个脚本 | 直接执行主函数 |
| **来源** | 上传 / AI 生成 | 从 Skill 转换 / 手动编写 / AI 生成 |
| **关系** | 被流程调用 | 调用一个或多个 Skill 的脚本 |

#### 2.6.3 数据模型

```python
class Pipeline(Base):
    """流程定义 - 一个完整的 Python 主函数"""
    __tablename__ = "pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)

    # 核心：Python 主函数源码
    main_code = Column(Text, nullable=False)
    """
    def main(datasource: str, tables: List[str], **kwargs):
        '''文物数据清洗流程'''
        from app.services.connectors import ConnectorManager

        cm = ConnectorManager()
        df = cm.read_table(datasource, tables[0])

        # 调用 Skill 的 main 脚本
        result = clean_data_main(df, **kwargs)

        cm.write_table(datasource, tables[0], result)
        return result
    """

    # 主函数签名信息（从 main_code 解析得出）
    entry_function = Column(String(100), default="main")  # 入口函数名
    parameters = Column(JSON)
    """
    [
        {"name": "datasource", "type": "str", "required": true, "description": "数据源ID"},
        {"name": "tables", "type": "list", "required": true, "description": "表名列表"}
    ]
    """

    # 调用关系：主函数调用了哪些 Skill 脚本
    skill_calls = Column(JSON)
    """
    [
        {
            "skill_id": "uuid",
            "skill_name": "data-cleaning-deduplication",
            "script": "scripts/main.py",
            "function": "clean_data_main",
            "line": 12
        }
    ]
    """

    # 来源
    source_skill_id = Column(UUID(as_uuid=True))  # 从哪个 Skill 转换而来

    # 元数据
    version = Column(Integer, default=1)
    tags = Column(JSON)
    category = Column(String(50))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    visibility = Column(String(20), default="private")

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PipelineExecution(Base):
    """流程执行记录"""
    __tablename__ = "pipeline_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id = Column(UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False)

    status = Column(String(20), default="pending")  # pending, running, success, failed, cancelled

    # 运行时参数
    inputs = Column(JSON)
    outputs = Column(JSON)

    # 时间与耗时
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)

    # 错误信息
    error_message = Column(Text)

    # 执行日志（stdout/stderr）
    logs = Column(Text)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
```

#### 2.6.4 流程生成器（Pipeline Builder）

Pipeline Builder 的核心任务是**生成一个完整的 Python 主函数**，而不是构建 DAG。

##### 从 Skill 生成流程

```
用户点击"转为流程"
    │
    ├─ 1. 读取 Skill 的 SKILL.md（元数据 + 参数定义）
    │
    ├─ 2. 读取 Skill 的 scripts/ 目录（所有脚本内容）
    │
    ├─ 3. LLM 生成 Python 主函数
    │     ├─ 注入：Skill 的脚本内容（作为被调用的模块）
    │     ├─ 注入：数据源信息（可用的 datasource/table）
    │     ├─ 生成：import 语句 + 主函数定义
    │     ├─ 主函数内：
    │     │   ├─ ConnectorManager.read_table() 读取数据
    │     │   ├─ 调用 Skill 脚本的入口函数处理数据
    │     │   └─ ConnectorManager.write_table() 写入结果
    │     └─ 主函数支持命令行参数（argparse）
    │
    ├─ 4. 解析调用关系
    │     └─ AST 分析 main_code，提取对 Skill 脚本函数的调用
    │
    └─ 5. 创建 Pipeline 记录 + 返回前端
```

##### LLM Prompt 模板

```python
PIPELINE_BUILDER_PROMPT = """你是一个 Python 代码生成器，将 Skill 转换为可执行的 Python 主函数。

## 输入信息
- Skill 名称: {skill_name}
- Skill 描述: {skill_description}
- Skill 参数: {skill_params}
- Skill 脚本内容: {skill_scripts}

## 输出要求
生成一个完整的 Python 主函数文件，包含：

### 1. 文件头注释
```python
'''
流程: {pipeline_display_name}
描述: {description}
从 Skill 生成: {skill_name}
'''
```

### 2. import 区域
```python
import argparse
import os
import pandas as pd
from app.services.connectors import ConnectorManager
```

### 3. Skill 脚本的内联函数
将 Skill 的每个脚本的函数定义内联到主文件中，函数名加 `_skill_` 前缀以避免冲突。

### 4. 主函数
```python
def main(datasource_name: str, table_name: str, **kwargs):
    cm = ConnectorManager()
    df = cm.read_table(datasource_name, table_name)
    result = _skill_main(df, **kwargs)
    cm.write_table(datasource_name, table_name, result)
    return result
```

### 5. argparse 入口（支持命令行直接运行）
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("datasource_name", type=str, help="数据源名称")
    ...
    args = parser.parse_args()
    main(**vars(args))
```

## 重要规则
- 必须使用 `ConnectorManager.read_table()` / `ConnectorManager.write_table()` 进行数据读写
- 数据源参数用名称而非 UUID，`ConnectorManager` 内部自动解析
- 所有 Skill 脚本函数前加 `_skill_` 前缀
- 处理边界情况（空表、列不存在等）
- 函数签名和参数要有类型注解
```

#### 2.6.5 执行引擎

流程执行直接运行 Python 主函数，无需 DAG 遍历。

```python
class PipelineExecutor:
    """流程执行器 - 直接运行 Python 主函数"""

    async def execute(
        self, pipeline: Pipeline, inputs: dict, db_session=None
    ) -> PipelineExecution:
        execution = PipelineExecution(
            pipeline_id=pipeline.id,
            status="running",
            inputs=inputs,
            started_at=datetime.utcnow(),
        )

        try:
            # 1. 动态编译主函数代码
            module_code = compile(pipeline.main_code, f"<pipeline_{pipeline.id}>", "exec")
            namespace = {"__name__": "__pipeline__", "__builtins__": __builtins__}
            exec(module_code, namespace)

            # 2. 获取入口函数
            func = namespace.get(pipeline.entry_function or "main")
            if not callable(func):
                raise ValueError(f"入口函数 '{pipeline.entry_function}' 不可调用")

            # 3. 调用主函数
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: func(**inputs)
            )

            execution.status = "success"
            execution.outputs = _sanitize_nans(result)
        except Exception as e:
            execution.status = "failed"
            execution.error_message = str(e)
        finally:
            execution.finished_at = datetime.utcnow()
            if execution.started_at:
                execution.duration_ms = int(
                    (execution.finished_at - execution.started_at).total_seconds() * 1000
                )

        return execution

    async def execute_stream(
        self, pipeline: Pipeline, inputs: dict, db_session=None
    ) -> AsyncGenerator[dict, None]:
        """SSE 流式执行，实时推送状态"""
        yield {"type": "status", "status": "running", "message": "流程开始执行..."}

        execution = PipelineExecution(
            pipeline_id=pipeline.id,
            status="running",
            inputs=inputs,
            started_at=datetime.utcnow(),
        )
        yield {"type": "status", "status": "running", "message": "编译主函数..."}

        try:
            module_code = compile(pipeline.main_code, f"<pipeline_{pipeline.id}>", "exec")
            namespace = {"__name__": "__pipeline__", "__builtins__": __builtins__}
            exec(module_code, namespace)
            func = namespace.get(pipeline.entry_function or "main")

            yield {"type": "status", "status": "running", "message": "执行主函数..."}

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: func(**inputs))

            execution.status = "success"
            execution.outputs = _sanitize_nans(result)
            yield {"type": "done", "status": "success", "outputs": execution.outputs}
        except Exception as e:
            execution.status = "failed"
            execution.error_message = str(e)
            yield {"type": "error", "status": "failed", "message": str(e)}
        finally:
            execution.finished_at = datetime.utcnow()
            if execution.started_at:
                execution.duration_ms = int(
                    (execution.finished_at - execution.started_at).total_seconds() * 1000
                )
```

#### 2.6.6 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/pipelines | 获取流程列表（支持名称/标签筛选） |
| GET | /api/v1/pipelines/{id} | 获取流程详情（含 main_code） |
| POST | /api/v1/pipelines | 创建流程（手动编写 main_code） |
| PUT | /api/v1/pipelines/{id} | 更新流程（修改 main_code 等） |
| DELETE | /api/v1/pipelines/{id} | 删除流程 |
| **POST** | **/api/v1/pipelines/from-skill/{skill_id}** | **从 Skill 生成流程（LLM 生成 main_code）** |
| POST | /api/v1/pipelines/{id}/run | 执行流程 |
| POST | /api/v1/pipelines/{id}/run-stream | SSE 流式执行 |
| GET | /api/v1/pipelines/{id}/executions | 获取执行历史 |
| GET | /api/v1/pipelines/executions/{eid} | 获取单次执行详情 |
| POST | /api/v1/pipelines/{id}/clone | 克隆流程 |

#### 2.6.7 前端界面

##### 流程列表页

```
┌──────────────────────────────────────────────────────────────┐
│ [新建流程] [从Skill生成▼]  [分类筛选▼]  [搜索流程...]          │
├──────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐            │
│  │ 📄 文物数据清洗      │  │ 📄 销售数据分析      │            │
│  │ 从 Skill 生成        │  │ 手动编写             │            │
│  │ 调用 2 个脚本        │  │ 调用 1 个脚本        │            │
│  │ 上次: 成功 3.2s      │  │ 上次: 失败           │            │
│  │                      │  │                      │            │
│  │ [查看代码] [运行]    │  │ [查看代码] [运行]    │            │
│  │ [调度] [删除]        │  │ [调度] [删除]        │            │
│  └─────────────────────┘  └─────────────────────┘            │
└──────────────────────────────────────────────────────────────┘
```

##### 流程详情页（代码 + 调用关系）

```
┌──────────────────────────────────────────────────────────────────┐
│  流程: 文物数据清洗                        [编辑] [运行▶] [调度] │
├────────────────────────┬─────────────────────────────────────────┤
│  主函数代码 (Python)    │  调用关系                                │
│  ┌────────────────────┐ │  ┌───────────────────────────────────┐ │
│  │ 1 │ '''            │ │  │  main()                           │ │
│  │ 2 │ 流程: 文物...  │ │  │  ├── ConnectorManager.read_table()│ │
│  │ 3 │ '''            │ │  │  ├──▶ Skill: data-cleaning        │ │
│  │ 4 │                │ │  │  │    └─ scripts/main.py          │ │
│  │ 5 │ import ...     │ │  │  │       :: clean_data_main()     │ │
│  │ 6 │                │ │  │  └── ConnectorManager.write_table()│ │
│  │ 7 │ def main(...): │ │  └───────────────────────────────────┘ │
│  │ 8 │     cm = ...   │ │                                         │
│  │ 9 │     df = cm... │ │  执行历史                               │
│  │10 │     result =   │ │  ┌───────────────────────────────────┐ │
│  │11 │         _skill │ │  │ ✅ 2026-06-18 10:30  3.2s  成功   │ │
│  │12 │     cm.write.. │ │  │ ✅ 2026-06-18 09:15  2.8s  成功   │ │
│  │13 │     return ... │ │  │ ❌ 2026-06-17 14:20  0.5s  失败   │ │
│  │14 │                │ │  └───────────────────────────────────┘ │
│  │15 │ if __name__... │ │                                         │
│  └────────────────────┘ │                                         │
├────────────────────────┴─────────────────────────────────────────┤
│  [Monaco Editor - Python 语法高亮]                                │
└──────────────────────────────────────────────────────────────────┘
```

##### Skill → 流程转换入口

在 Skill 页面，"转为流程"按钮：

```
┌─────────────────────────────────┐
│ 数据清洗去重                     │
│ 对数据进行去重和空值处理          │
│                                  │
│ [调试] [下载] [修改]             │
│ [转为流程▶]                      │
└─────────────────────────────────┘
```

点击后弹出确认对话框（SSE 流式展示生成过程）：

```
┌──────────────────────────────────────┐
│  将 Skill 转换为流程                  │
│                                      │
│  Skill: 数据清洗去重                  │
│  包含脚本: main.py                    │
│                                      │
│  Skill Creator 正在生成流程代码...    │
│  ┌────────────────────────────────┐  │
│  │ 正在分析 Skill 结构...          │  │
│  │ 正在生成 Python 主函数...       │  │
│  │ 生成完成，3 个函数调用已识别     │  │
│  └────────────────────────────────┘  │
│                                      │
│  流程名称: [数据清洗去重 - 流程]      │
│                                      │
│         [取消]    [创建并查看]        │
└──────────────────────────────────────┘
```

##### 前端技术选型

| 组件 | 库 | 说明 |
|------|-----|------|
| 代码编辑/展示 | Monaco Editor | Python 语法高亮，代码编辑，只读模式 |
| 调用关系图 | 自定义 Vue 组件 | 树形展示主函数 → Skill 脚本的调用链 |
| 列表页 | Element Plus Card | 流程卡片网格 |
| 执行状态 | SSE EventSource | 实时推送执行进度 |

#### 2.6.8 流程与调度的关系

流程可关联调度配置，实现定时/事件触发的自动化执行：

```
Pipeline ──1:1──▶ Schedule
                   ├─ task_type: "pipeline"
                   ├─ task_target_id: pipeline.id
                   ├─ cron: "0 2 * * *"    (每天凌晨2点)
                   ├─ event: 数据源更新     (事件触发)
                   └─ manual: 手动触发
```

调度触发后创建 PipelineExecution 记录，状态实时推送至前端。

#### 2.6.9 实现状态

| 功能 | 状态 | 说明 |
|------|------|------|
| Pipeline 数据模型 | ✅ 已完成 | Pipeline + PipelineExecution |
| Pipeline Builder（Skill→流程） | ✅ 已完成 | LLM 生成 Python 主函数 |
| 流程执行引擎 | ✅ 已完成 | 动态编译 + exec 运行主函数 |
| API 端点 | ✅ 已完成 | CRUD + from-skill + run + run-stream + clone |
| 前端列表页 | ✅ 已完成 | 流程卡片网格 |
| 前端详情页 | ✅ 已完成 | 代码展示 + 调用关系图 |
| Skill 页面"转为流程"按钮 | ✅ 已完成 | 从 Skill 生成 Pipeline |
| SSE 流式生成+执行 | ✅ 已完成 | LLM 生成过程流式展示 + 执行过程流式推送 |

**废弃的旧功能**：
- ~~DAG 节点/边模型~~
- ~~Vue Flow 画布编辑器~~
- ~~Kahn 拓扑排序~~
- ~~多引擎适配（Prefect/Airflow）~~
- ~~节点类型枚举（skill/condition/parallel 等）~~
- ~~参数映射表达式（$upstream.$input）~~

### 2.7 多智能体协作框架

#### 2.7.1 设计理念

DataCrab 从单智能体架构演进为**多智能体协作框架**。每个智能体是独立的职责单元，拥有专属的 LLM 指令、工具集和知识上下文，通过消息总线进行协作。

**核心设计原则**：
- **职责单一**：每个智能体只负责一个领域（数据处理、质量检查、安全审计……），指令精准不模糊
- **Handoff 交接**：智能体通过结构化消息交接工作，交接时携带完整上下文（数据、问题、溯源信息）
- **可插拔扩展**：新增智能体只需实现 Agent 接口、注册到 AgentRegistry，无需修改已有智能体
- **人机协同**：关键决策点（如数据修复方案）可暂停等待人工确认

**参考框架**：
- **OpenAI Swarm / Agents SDK**：Agent + Handoff 原语，轻量级，函数返回 Agent 即触发交接
- **CrewAI**：Crew（团队）+ Task + Sequential/Hierarchical 流程，强调角色分工和流程编排
- **AutoGen**：RoutedAgent + Topic/Subscription 消息路由，支持分布式运行时

DataCrab 借鉴 Swarm 的 Handoff 简洁性 + CrewAI 的角色分工思想 + AutoGen 的消息路由机制，形成适合数据处理场景的多智能体架构。

#### 2.7.2 智能体列表

| 智能体 | 代号 | 职责 | 核心工具 | 接收来自 | 可交接给 |
|--------|------|------|----------|----------|----------|
| **数据处理智能体** | `DataProcessor` | 理解用户意图、生成/修改算子和技能、调度执行、溯源修复 | `query_table_data`、`get_table_schema`、`write_table_data`、`generate_operator`、`generate_skill`、`run_pipeline` | 用户对话、`DataInspector` | `DataInspector` |
| **数据检查智能体** | `DataInspector` | 对加工后的数据进行标准检查、质量检查、安全检查，发现错误后记录并反馈 | `check_data_standards`、`check_data_quality`、`check_data_security`、`profile_data` | `DataProcessor` | `DataProcessor` |
| *(未来扩展)* | | | | | |
| 数据治理智能体 | `DataGovernor` | 数据血缘追踪、元数据补全、数据目录管理 | `trace_lineage`、`enrich_metadata` | 任意智能体 | 任意智能体 |
| 数据安全智能体 | `DataSentinel` | 敏感数据识别、脱敏建议、合规审查 | `detect_pii`、`suggest_masking`、`audit_compliance` | `DataInspector`、用户 | `DataProcessor` |

#### 2.7.3 架构设计

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Agent Runtime（智能体运行时）                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐   Message Bus   ┌──────────────────┐                  │
│  │  DataProcessor   │ ◄──────────────►│  DataInspector   │                  │
│  │  数据处理智能体   │                 │  数据检查智能体   │                  │
│  │                  │                 │                  │                  │
│  │  指令: 数据处理   │  Handoff消息    │  指令: 质量检查   │                  │
│  │  工具: 查询/生成  │ ──────────────► │  工具: 检查/分析  │                  │
│  │  知识: 数据源     │  检查结果+问题  │  知识: 标准规范   │                  │
│  │                  │ ◄────────────── │                  │                  │
│  └──────────────────┘                 └──────────────────┘                  │
│         ▲                                    │                               │
│         │              ┌──────────────────┐  │                               │
│         └──────────────│  AgentRegistry   │◄─┘                               │
│                        │  智能体注册中心   │                                  │
│                        │  - 发现智能体     │                                  │
│                        │  - 路由消息       │                                  │
│                        │  - 生命周期管理   │                                  │
│                        └──────────────────┘                                   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────┐        │
│  │  Shared Context（共享上下文）                                      │        │
│  │  - datasource_context: 数据源信息                                 │        │
│  │  - session_id: 会话标识                                           │        │
│  │  - user_id: 用户标识                                              │        │
│  │  - execution_history: 执行历史（哪条SQL/脚本产生了什么数据）       │        │
│  │  - inspection_results: 检查结果（问题列表、严重等级、修复建议）   │        │
│  └──────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────┐        │
│  │  Event Store（事件存储）                                           │        │
│  │  - agent_handoff_events: 智能体交接事件                           │        │
│  │  - data_lineage_events: 数据血缘事件                              │        │
│  │  - inspection_events: 检查事件（问题发现、修复确认）               │        │
│  └──────────────────────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────────────────┘
```

#### 2.7.4 核心抽象

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum


class HandoffReason(str, Enum):
    """智能体交接原因"""
    INSPECT_RESULT = "inspect_result"           # 处理完成，需检查
    FIX_REQUIRED = "fix_required"               # 检查发现问题，需修复
    FIX_COMPLETED = "fix_completed"             # 修复完成，需再检查
    ESCALATE = "escalate"                       # 上报人工
    DELEGATE = "delegate"                       # 委派给其他智能体


@dataclass
class AgentMessage:
    """智能体间传递的消息"""
    from_agent: str                             # 发送方智能体代号
    to_agent: str                               # 接收方智能体代号
    reason: HandoffReason                       # 交接原因
    payload: Dict[str, Any]                     # 消息内容
    context: Dict[str, Any] = field(default_factory=dict)  # 共享上下文
    trace_id: str = ""                          # 链路追踪ID
    parent_trace_id: str = ""                   # 父链路ID（溯源用）


@dataclass
class InspectionResult:
    """数据检查结果"""
    passed: bool                                # 是否通过
    issues: List[Dict[str, Any]] = field(default_factory=list)  # 问题列表
    summary: str = ""                           # 检查摘要
    severity: str = "info"                      # 最高严重等级: info/warning/error/critical


class BaseAgent(ABC):
    """智能体基类 - 所有智能体必须实现此接口"""

    name: str                                   # 智能体代号
    display_name: str                           # 显示名称
    description: str                            # 职责描述
    instructions: str                           # LLM 系统提示词
    tools: List[Dict]                           # 可用工具定义

    @abstractmethod
    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        """
        执行智能体任务，以 SSE 流式返回中间过程和最终结果。

        Yields:
            {"type": "thinking", "content": "..."}    # 推理过程
            {"type": "content", "content": "..."}     # 回复内容
            {"type": "tool_call", ...}                # 工具调用
            {"type": "tool_result", ...}              # 工具结果
            {"type": "handoff", "to": "...", "reason": "...", "payload": {...}}  # 交接
            {"type": "done", "result": {...}}         # 完成
        """
        pass

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        """构建系统提示词，子类可覆盖以注入动态上下文"""
        return self.instructions
```

#### 2.7.5 AgentRegistry 智能体注册中心

```python
class AgentRegistry:
    """智能体注册中心 - 管理所有智能体的发现、路由和生命周期"""

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):
        """注册智能体"""
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        """获取智能体实例"""
        return self._agents.get(name)

    def list_agents(self) -> List[Dict]:
        """列出所有已注册智能体"""
        return [
            {"name": a.name, "display_name": a.display_name, "description": a.description}
            for a in self._agents.values()
        ]

    def find_by_capability(self, capability: str) -> List[BaseAgent]:
        """按能力查找智能体（如 'data_quality'、'pii_detection'）"""
        return [a for a in self._agents.values() if capability in getattr(a, 'capabilities', [])]


# 全局注册中心
agent_registry = AgentRegistry()
```

#### 2.7.6 AgentRuntime 智能体运行时

```python
class AgentRuntime:
    """智能体运行时 - 管理智能体间的消息传递、交接和执行流程"""

    def __init__(self, registry: AgentRegistry, llm_manager):
        self.registry = registry
        self.llm_manager = llm_manager
        self._event_store = EventStore()

    async def run(
        self,
        agent_name: str,
        message: AgentMessage,
        context: Dict[str, Any],
        max_handoffs: int = 10,
    ) -> AsyncGenerator[Dict, None]:
        """
        运行智能体，自动处理交接，流式返回所有事件。

        流程：
        1. 获取目标智能体
        2. 调用 agent.run() 获取流式输出
        3. 如果输出包含 handoff 事件，自动切换到目标智能体继续执行
        4. 重复直到无交接或达到最大交接次数
        5. 记录所有事件到 EventStore（溯源用）
        """
        handoff_count = 0
        current_agent = self.registry.get(agent_name)
        current_message = message

        while current_agent and handoff_count < max_handoffs:
            async for event in current_agent.run(current_message, context):
                if event.get("type") == "handoff":
                    # 记录交接事件
                    self._event_store.record_handoff(
                        from_agent=current_agent.name,
                        to_agent=event["to"],
                        reason=event["reason"],
                        trace_id=current_message.trace_id,
                    )

                    # 切换到目标智能体
                    target_name = event["to"]
                    current_agent = self.registry.get(target_name)
                    current_message = AgentMessage(
                        from_agent=event.get("from", current_agent.name),
                        to_agent=target_name,
                        reason=HandoffReason(event["reason"]),
                        payload=event.get("payload", {}),
                        context=context,
                        trace_id=current_message.trace_id,
                        parent_trace_id=current_message.trace_id,
                    )
                    handoff_count += 1
                    yield {"type": "agent_switch", "agent": target_name, "reason": event["reason"]}
                    break
                else:
                    yield event
            else:
                # agent.run() 正常结束，无交接
                break
```

#### 2.7.7 DataProcessor 数据处理智能体

**职责**：理解用户意图，生成/修改算子和技能，调度执行，接收检查结果并溯源修复。

**系统提示词核心要素**：
- 数据处理专家，擅长 SQL、pandas、数据清洗和转换
- 安全红线：DataCrab 不能修改平台自身（例外：用户可添加自定义数据源连接器和模型适配器）
- 输出默认同源
- 修改后必验证
- 当收到 DataInspector 的检查结果时，应定位问题根源并修复

**工具集**：
```python
DATA_PROCESSOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_table_data",
            "description": "查询数据源中某个表的数据",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_schema",
            "description": "获取表结构信息",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_operator",
            "description": "根据自然语言描述生成算子脚本",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_skill",
            "description": "根据自然语言描述生成完整技能包",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "modify_script",
            "description": "修改算子或技能脚本",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_script",
            "description": "执行算子或技能脚本",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_inspector",
            "description": "将处理结果交接给数据检查智能体进行质量检查",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "数据源ID"},
                    "table_name": {"type": "string", "description": "检查的表名"},
                    "operation_description": {"type": "string", "description": "本次数据处理的操作描述"},
                    "result_summary": {"type": "string", "description": "处理结果摘要"}
                },
                "required": ["datasource_id", "table_name"]
            }
        }
    },
]
```

**交接触发**：
- 数据处理完成后，自动或用户触发交接给 `DataInspector`
- 收到 `fix_required` 交接时，根据检查结果定位问题、修改脚本、重新执行

#### 2.7.8 DataInspector 数据检查智能体

**职责**：对加工后的数据执行三维度检查——标准合规、质量评估、安全审计。

**检查维度**：

| 维度 | 检查项 | 示例规则 |
|------|--------|----------|
| **标准检查** | 字段命名规范、类型一致性、编码规范 | 列名应为 snake_case，日期列应为 datetime 类型 |
| **质量检查** | 完整性、唯一性、范围合理性、业务逻辑一致性 | 主键不重复，数值列无异常极值，关联字段逻辑一致 |
| **安全检查** | PII 识别、敏感数据暴露、脱敏完整性 | 手机号/身份证号是否明文存储，敏感字段是否有脱敏 |

**系统提示词核心要素**：
- 数据质量专家，擅长数据标准、质量规则和安全审计
- 检查时优先使用 `profile_data` 获取数据概览，再针对性检查
- 发现问题必须给出：问题描述、严重等级、影响范围、修复建议
- 对修复后的数据必须再次检查确认

**工具集**：
```python
DATA_INSPECTOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "profile_data",
            "description": "获取数据概览：行数、列数、各列类型、空值率、唯一值数、样本数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string"},
                    "table_name": {"type": "string"}
                },
                "required": ["datasource_id", "table_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_standards",
            "description": "检查数据是否符合命名规范、类型标准、编码规范",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "standard_rules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "检查规则列表，如 ['naming_convention', 'type_consistency']"
                    }
                },
                "required": ["datasource_id", "table_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_quality",
            "description": "检查数据质量：完整性、唯一性、范围合理性、业务逻辑一致性",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "quality_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "质量维度，如 ['completeness', 'uniqueness', 'validity', 'consistency']"
                    }
                },
                "required": ["datasource_id", "table_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_security",
            "description": "检查数据安全：PII识别、敏感数据暴露、脱敏完整性",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string"},
                    "table_name": {"type": "string"}
                },
                "required": ["datasource_id", "table_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_processor",
            "description": "将检查发现的问题交接给数据处理智能体进行修复",
            "parameters": {
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "description": "问题列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string", "description": "问题描述"},
                                "severity": {"type": "string", "enum": ["warning", "error", "critical"]},
                                "column": {"type": "string", "description": "涉及列名"},
                                "suggestion": {"type": "string", "description": "修复建议"}
                            }
                        }
                    },
                    "summary": {"type": "string", "description": "检查摘要"}
                },
                "required": ["issues", "summary"]
            }
        }
    },
]
```

#### 2.7.9 典型协作流程

##### 流程一：数据处理 + 自动检查

```
用户: "帮我清洗文物数据，去除重复和空值"
     │
     ▼
┌──────────────────────────────────────────────────────────────┐
│ DataProcessor                                                │
│ 1. 理解意图：去重 + 填充/删除空值                             │
│ 2. query_table_data() 读取数据                               │
│ 3. 生成/选择清洗算子脚本                                      │
│ 4. run_script() 执行清洗                                     │
│ 5. 处理完成 → handoff_to_inspector()                         │
│    payload: {datasource_id, table_name, "去重和空值处理完成"} │
└──────────────────────────────────────────────────────────────┘
     │ Handoff(inspect_result)
     ▼
┌──────────────────────────────────────────────────────────────┐
│ DataInspector                                                │
│ 1. profile_data() 获取数据概览                                │
│ 2. check_data_standards() 检查命名和类型规范                  │
│ 3. check_data_quality() 检查完整性、唯一性                    │
│ 4. check_data_security() 检查敏感数据                         │
│ 5. 发现问题：                                                 │
│    - "时代"列有3个非标准值（warning）                          │
│    - "编号"列存在2条重复（error）                              │
│ 6. handoff_to_processor(issues=[...], summary="2个问题")     │
└──────────────────────────────────────────────────────────────┘
     │ Handoff(fix_required)
     ▼
┌──────────────────────────────────────────────────────────────┐
│ DataProcessor                                                │
│ 1. 分析检查结果，定位问题根源                                  │
│ 2. modify_script() 修改清洗逻辑：                             │
│    - 时代列：增加标准值映射                                    │
│    - 编号列：去重逻辑遗漏了某个字段组合                        │
│ 3. run_script() 重新执行                                      │
│ 4. 修复完成 → handoff_to_inspector() 再检查                   │
└──────────────────────────────────────────────────────────────┘
     │ Handoff(inspect_result)
     ▼
┌──────────────────────────────────────────────────────────────┐
│ DataInspector                                                │
│ 1. 对修复后的数据再次检查                                     │
│ 2. 所有检查通过                                               │
│ 3. 返回 InspectionResult(passed=True)                         │
└──────────────────────────────────────────────────────────────┘
     │
     ▼
用户: 收到检查报告 + 处理结果
```

##### 流程二：用户主动触发检查

```
用户: "帮我检查一下全国文物这张表的数据质量"
     │
     ▼
┌──────────────────────────────────────────────────────────────┐
│ DataProcessor（路由层）                                       │
│ 1. 识别意图：数据质量检查                                     │
│ 2. 直接交接给 DataInspector                                  │
│    handoff_to_inspector(reason=delegate)                     │
└──────────────────────────────────────────────────────────────┘
     │ Handoff(delegate)
     ▼
┌──────────────────────────────────────────────────────────────┐
│ DataInspector                                                │
│ 1. profile_data() → 数据概览                                 │
│ 2. check_data_quality(dimensions=['completeness', ...])      │
│ 3. 生成检查报告                                               │
│ 4. 如有问题 → handoff_to_processor(reason=fix_required)      │
│    无问题 → 返回检查报告给用户                                │
└──────────────────────────────────────────────────────────────┘
```

#### 2.7.10 检查工具实现

检查工具在 `app/services/data_inspector.py` 中实现，基于 pandas 对 ConnectorManager 查询的数据进行分析：

```python
class DataInspectorTools:
    """数据检查工具集 - 注入到 DataInspector 智能体的执行沙箱"""

    async def profile_data(self, datasource_id: str, table_name: str) -> dict:
        """
        数据概览：行数、列数、各列类型、空值率、唯一值数、样本数据
        """
        connector = get_connector(ds.type, ds.connection_config)
        df = await connector.get_table_data(table_name, page=1, page_size=1000)
        profile = {
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": {
                col: {
                    "dtype": str(df[col].dtype),
                    "null_count": int(df[col].isna().sum()),
                    "null_rate": round(float(df[col].isna().mean()), 4),
                    "unique_count": int(df[col].nunique()),
                    "sample_values": df[col].dropna().head(5).tolist(),
                }
                for col in df.columns
            }
        }
        return profile

    async def check_data_standards(self, datasource_id: str, table_name: str, standard_rules: list = None) -> dict:
        """
        标准检查：
        - naming_convention: 列名是否符合 snake_case 规范
        - type_consistency: 同名列在不同行中类型是否一致
        - encoding_check: 是否存在乱码字符
        """
        issues = []
        df = await self._load_data(datasource_id, table_name)

        if not standard_rules or 'naming_convention' in standard_rules:
            import re
            for col in df.columns:
                if not re.match(r'^[a-z][a-z0-9_]*$', col) and not re.match(r'^[\u4e00-\u9fff]', col):
                    issues.append({
                        "dimension": "naming_convention",
                        "column": col,
                        "severity": "warning",
                        "description": f"列名 '{col}' 不符合 snake_case 命名规范",
                        "suggestion": f"建议重命名为 '{re.sub(r'([A-Z])', r'_\\1', col).lower()}'"
                    })

        if not standard_rules or 'type_consistency' in standard_rules:
            for col in df.columns:
                non_null = df[col].dropna()
                if len(non_null) > 0:
                    types = non_null.apply(type).nunique()
                    if types > 1:
                        issues.append({
                            "dimension": "type_consistency",
                            "column": col,
                            "severity": "warning",
                            "description": f"列 '{col}' 存在混合类型（{types}种）",
                            "suggestion": "建议统一数据类型"
                        })

        return {"dimension": "standards", "passed": len(issues) == 0, "issues": issues}

    async def check_data_quality(self, datasource_id: str, table_name: str, quality_dimensions: list = None) -> dict:
        """
        质量检查：
        - completeness: 完整性（空值率）
        - uniqueness: 唯一性（重复率）
        - validity: 有效性（数值范围、日期合理性）
        - consistency: 一致性（业务逻辑校验）
        """
        issues = []
        df = await self._load_data(datasource_id, table_name)
        total = len(df)

        if not quality_dimensions or 'completeness' in quality_dimensions:
            for col in df.columns:
                null_rate = df[col].isna().mean()
                if null_rate > 0.1:
                    issues.append({
                        "dimension": "completeness",
                        "column": col,
                        "severity": "error" if null_rate > 0.3 else "warning",
                        "description": f"列 '{col}' 空值率 {null_rate:.1%}",
                        "suggestion": "建议填充默认值或删除空值行"
                    })

        if not quality_dimensions or 'uniqueness' in quality_dimensions:
            dupe_count = total - len(df.drop_duplicates())
            if dupe_count > 0:
                issues.append({
                    "dimension": "uniqueness",
                    "severity": "error",
                    "description": f"存在 {dupe_count} 条完全重复的行（{dupe_count/total:.1%}）",
                    "suggestion": "建议执行去重操作"
                })

        return {"dimension": "quality", "passed": len(issues) == 0, "issues": issues}

    async def check_data_security(self, datasource_id: str, table_name: str) -> dict:
        """
        安全检查：
        - PII 识别（手机号、身份证号、邮箱、银行卡号）
        - 敏感数据暴露检测
        """
        issues = []
        df = await self._load_data(datasource_id, table_name)

        PII_PATTERNS = {
            "手机号": r'1[3-9]\d{9}',
            "身份证号": r'[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]',
            "邮箱": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        }

        for col in df.columns:
            if df[col].dtype == 'object':
                sample = df[col].dropna().head(100).astype(str)
                for pii_type, pattern in PII_PATTERNS.items():
                    match_count = sample.str.contains(pattern, regex=True, na=False).sum()
                    if match_count > 0:
                        issues.append({
                            "dimension": "security",
                            "column": col,
                            "severity": "critical",
                            "description": f"列 '{col}' 疑似包含明文 {pii_type}（{match_count}/{len(sample)} 条样本命中）",
                            "suggestion": f"建议对 {pii_type} 进行脱敏处理"
                        })

        return {"dimension": "security", "passed": len(issues) == 0, "issues": issues}
```

#### 2.7.11 事件存储与数据溯源

每次智能体交接和数据处理操作都记录到 EventStore，支持数据溯源：

```python
@dataclass
class AgentEvent:
    """智能体事件"""
    id: str
    trace_id: str                               # 链路追踪ID
    parent_trace_id: str                        # 父事件ID
    agent_name: str                             # 智能体代号
    event_type: str                             # handoff / tool_call / inspection / fix
    timestamp: datetime
    payload: Dict[str, Any]                     # 事件内容


class EventStore:
    """事件存储 - 记录所有智能体操作，支持溯源"""

    async def record(self, event: AgentEvent):
        """记录事件"""
        pass

    async def get_trace(self, trace_id: str) -> List[AgentEvent]:
        """获取完整链路"""
        pass

    async def get_lineage(self, datasource_id: str, table_name: str) -> List[AgentEvent]:
        """获取数据血缘：哪些操作影响了这张表"""
        pass
```

**溯源场景**：当 DataInspector 发现"编号列存在重复"时，DataProcessor 可以通过 `trace_id` 查询 EventStore，找到产生重复数据的具体操作（哪条 SQL、哪个脚本的哪次执行），从而精准定位问题根源。

#### 2.7.12 与现有模块的集成

| 现有模块 | 集成方式 |
|----------|----------|
| `agent.py` (AgentService) | 重构为 `DataProcessor` 智能体，保留现有工具和执行逻辑 |
| `chat.py` | 对话入口增加路由层：识别用户意图后分派到对应智能体 |
| `operator.py` | DataProcessor 的 `generate_operator`/`modify_script`/`run_script` 工具调用现有端点 |
| `skill.py` | DataProcessor 的 `generate_skill`/`modify_script`/`run_script` 工具调用现有端点 |
| `connectors.py` | 两个智能体都通过 `get_connector` 读写数据 |
| `skill_parser.py` | DataInspector 的经验总结注入 DataProcessor 的提示词 |
| `data_inspector.py` (新增) | DataInspector 智能体的检查工具实现 |

#### 2.7.13 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/agents | 获取已注册智能体列表 |
| POST | /api/v1/agents/{agent_name}/run | 运行指定智能体（SSE 流式） |
| POST | /api/v1/agents/inspect | 对指定数据源/表执行数据检查 |
| GET | /api/v1/agents/events/{trace_id} | 获取智能体执行链路 |
| GET | /api/v1/agents/lineage/{datasource_id}/{table_name} | 获取数据血缘 |

#### 2.7.14 前端界面

##### 智能体状态指示

在对话界面中显示当前活跃的智能体：

```
┌──────────────────────────────────────────────────────────────┐
│  🤖 DataProcessor 正在处理...                                │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 用户：帮我清洗文物数据                                   │  │
│  │                                                         │  │
│  │ [DataProcessor] 正在读取数据源...                        │  │
│  │ [DataProcessor] 生成清洗脚本...                          │  │
│  │ [DataProcessor] 执行完成，交接检查 ▶                     │  │
│  │                                                         │  │
│  │ [DataInspector] 正在检查数据质量...                      │  │
│  │ [DataInspector] ⚠ 发现2个问题                           │  │
│  │   - 时代列: 3个非标准值 (warning)                        │  │
│  │   - 编号列: 2条重复 (error)                              │  │
│  │ [DataInspector] 交接修复 ▶                               │  │
│  │                                                         │  │
│  │ [DataProcessor] 正在修复问题...                          │  │
│  │ [DataProcessor] 修复完成，交接再检查 ▶                   │  │
│  │                                                         │  │
│  │ [DataInspector] ✅ 所有检查通过                          │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

##### 数据检查报告页

新增"数据检查"页面，用户可主动选择数据源和表触发检查：

```
┌──────────────────────────────────────────────────────────────┐
│  数据检查                                                     │
├──────────────┬───────────────────────────────────────────────┤
│ 数据源: [▼]  │  检查结果: 全国文物                           │
│ 表: [▼]      │                                               │
│              │  📋 标准检查  ✅ 通过                          │
│ [开始检查]   │  📊 质量检查  ⚠ 2个警告                       │
│              │  🔒 安全检查  🚨 1个严重                       │
│              │                                               │
│              │  ┌─ 严重问题 ──────────────────────────────┐  │
│              │  │ 🚨 "电话"列包含明文手机号 (38/100条)    │  │
│              │  │    建议：脱敏处理                        │  │
│              │  │    [一键修复]                            │  │
│              │  └────────────────────────────────────────┘  │
│              │  ┌─ 警告 ──────────────────────────────────┐  │
│              │  │ ⚠ "时代"列3个非标准值                    │  │
│              │  │ ⚠ "保护级别"空值率 15.3%                 │  │
│              │  └────────────────────────────────────────┘  │
└──────────────┴───────────────────────────────────────────────┘
```

#### 2.7.15 实现路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| **Phase 1** | 基础框架：BaseAgent + AgentRegistry + AgentRuntime + Handoff 机制 | ✅ 已完成 |
| **Phase 2** | DataProcessor 智能体：将现有 agent.py 重构为 DataProcessor | ✅ 已完成 |
| **Phase 3** | DataInspector 智能体：实现检查工具 + 系统提示词 | ✅ 已完成 |
| **Phase 4** | 前端：智能体状态指示 + 检查报告页 | ✅ 已完成 |
| **Phase 5** | 事件存储与溯源 | ✅ 已完成 |
| **Phase 6** | 扩展：DataGovernor / DataSentinel 等新智能体 | ⬜ 待实现 |
| **Phase 7** | 调试页面集成多智能体：技能/算子/流程调试助手接入 DataProcessor + DataInspector | ✅ 已完成 |

#### 2.7.16 调试页面集成多智能体（已完成）

##### 问题背景

改造前，系统的多智能体协作（DataProcessor → DataInspector）**仅在主对话流（`/chat/stream`）中触发**。技能/算子/流程的调试助手（debug-chat）走的是完全独立的路径：手写 LLM 循环 + 正则解析 action + 执行，不经过多智能体框架。

| 入口 | 改造前 | 改造后 |
|------|--------|--------|
| 聊天页面 | ✅ AgentRuntime → DataProcessor → DataInspector | 不变 |
| 技能调试 | ❌ 手写 LLM 循环 | ✅ AgentRuntime → DataProcessor → DataInspector |
| 算子调试 | ❌ 手写 LLM 循环 | ✅ AgentRuntime → DataProcessor → DataInspector |
| 流程调试 | ❌ 手写 LLM 循环 | ✅ AgentRuntime → DataProcessor → DataInspector |

##### 架构设计：Orchestrator-Worker 模式

采用主流的 Orchestrator-Worker 模式（Claude Code / OpenAI Agents SDK / Google ADK 同款）：

```
DataProcessor（Orchestrator + 轻量工具）
    ├── 直接调用 modify_script（Tool）—— 简单操作，不需要独立 LLM 循环
    ├── 直接调用 run_script（Tool）—— 简单操作
    ├── 直接调用 query_table_data / write_table_data 等（共享 Tool）
    └── delegate → DataInspector（Worker Agent）—— 复杂任务，独立 LLM 循环
                    ├── profile_data
                    ├── check_data_standards
                    ├── check_data_quality
                    ├── check_data_security
                    └── handoff_back → DataProcessor 修复
```

**粒度原则**：Agent 用于复杂推理，Tool 用于简单操作。
- `modify_script`（代码合并）/ `run_script`（沙箱执行）是简单操作 → Tool，不需要独立 Agent
- 数据质量检查是复杂推理（决定查什么、解读结果、判断严重等级）→ Agent（Worker）
- 如果把简单操作也做成独立 Worker，每次 modify+run 多 2 次 Agent 跳转 + 2 次额外 LLM 调用，延迟翻倍

##### 关键技术：流式工具调用 + 推理过程

改造前 DataProcessor 使用 `chat_with_tools()`（非流式，无推理过程），调试助手使用 `chat_stream_with_thinking()`（流式推理，无工具调用）。两者不兼容。

新增 `chat_stream_with_tools_and_thinking()` 方法（`llm.py`），同时支持流式推理、流式正文和工具调用：

| 能力 | 来源 | 实现 |
|------|------|------|
| 流式推理（thinking） | chat_stream_with_thinking | 逐 chunk yield reasoning_content |
| 流式正文（content） | chat_stream_with_thinking | 逐 chunk yield content |
| 工具调用（tool_calls） | chat_with_tools | 累积 tool_call deltas，流结束后一次性 yield |
| 无工具重定向 | 第八轮新增（替代原长度升级） | 思维模型无工具调用 / 推理截断（finish_reason=length）→ 切快速模型 + tool_choice=required 强制工具调用 |
| 断路器降级 + 超时保护 | chat_stream_with_thinking + 第八轮新增 | 模型失败 / 首 chunk 120s 超时 / 后续 60s 超时 → 切换降级链 |

##### DataProcessor 调试模式

DataProcessor 新增 `run_debug()` 方法，在 `run()` 中检测 `context["debug_mode"]` 时分派：

| 特性 | run()（主对话流） | run_debug()（调试助手） |
|------|-------------------|------------------------|
| LLM 调用 | chat_with_tools()（非流式） | chat_stream_with_tools_and_thinking()（流式） |
| 工具集 | 共享工具 + handoff_to_inspector | 共享工具 + handoff + modify_script + run_script |
| system prompt | 通用数据处理指令 | 调试专用指令（含脚本内容、沙箱函数清单、参数记忆） |
| 自愈 | handoff 来回（DataInspector ↔ DataProcessor） | 工具调用循环内自治（run_script 失败 → LLM 看到错误 → 自动 modify → 再 run） |

##### 新增工具

| 工具 | 类型 | 说明 |
|------|------|------|
| `modify_script` | Tool | 修改脚本代码（函数级合并 apply_partial_code）；支持 skill（文件）/ operator（DB）/ pipeline（DB）三种模式 |
| `run_script` | Tool | 沙箱执行脚本；skill 用 subprocess，operator 用 exec()，pipeline 不支持直接执行 |
| `handoff_to_inspector` | Tool | 交接给 DataInspector 质量检查（原有，调试模式也可用） |

##### 改造前后代码量

| 端点 | 改造前 | 改造后 | 说明 |
|------|--------|--------|------|
| `skill.py` debug-chat | ~300 行手写循环 | ~120 行 AgentRuntime 调用 | -180 行 |
| `operator.py` debug-chat | ~180 行 | ~90 行 | -90 行 |
| `pipeline.py` debug-chat | ~85 行 | ~95 行 | +10 行（增加事件翻译） |

##### SSE 事件流

```
用户消息 → DataProcessor.run_debug()
    ↓
model / thinking / content（流式推理 + 正文）
    ↓
tool_calls → modify_script → script_updated 事件
    ↓
tool_calls → run_script → executing + run_result 事件
    ↓
tool_calls → handoff_to_inspector → agent_switch 事件
    ↓ (AgentRuntime 自动切换)
inspecting 事件 → DataInspector.run()
    ↓
thinking / content / tool_result（检查推理 + 结果）
    ↓
handoff_back → agent_switch → retry 事件 → DataProcessor 修复
    ↓
done 事件
```

前端新增事件处理：`inspecting`（🔍 DataInspector 检查中）、`retry`（🔄 修复重试）、`give_up`（⚠ 无法修复）。

##### 支持的调试类型

| 类型 | debug_type | 脚本存储 | 执行方式 | modify_script | run_script |
|------|-----------|----------|----------|:---:|:---:|
| 技能 | (默认) | 文件（folder/scripts/） | subprocess 沙箱 | ✅ 文件写入 | ✅ skill_runner |
| 算子 | "operator" | 数据库（Operator.script_content） | exec() 沙箱 | ✅ DB 更新 | ✅ exec() + _build_operator_namespace |
| 流程 | "pipeline" | 数据库（Pipeline.main_code） | 不支持直接执行 | ✅ DB 更新 | ❌ 返回"请使用流程执行功能" |

### 2.9 调度系统模块

#### 2.9.1 调度架构

调度系统由 `schedule.py`（API 端点）+ `task_runner.py`（后台执行 + 定时扫描）组成：

```
┌───────────────────────────────────────────────┐
│               Scheduler Service               │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  Schedule Manager (schedule.py)       │   │
│   │  - 调度配置 CRUD                      │   │
│   │  - 暂停/恢复/手动触发                 │   │
│   │  - Cron 表达式校验                    │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Task Runner (task_runner.py)         │   │
│   │  - execute_task(): 后台执行分派       │   │
│   │    skill → asyncio.to_thread          │   │
│   │    operator → exec+func               │   │
│   │    pipeline → await execute_pipeline  │   │
│   │  - 更新 TaskExecution + Schedule      │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Scheduler Loop (task_runner.py)      │   │
│   │  - 30s 间隔扫描 next_run_at <= now    │   │
│   │  - 并发控制 (concurrent_runs)         │   │
│   │  - next_run_at 重算防重复触发         │   │
│   │  - lifespan 启停                      │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

> **实现说明**：手动触发（`POST /schedules/{id}/trigger`）通过 FastAPI `BackgroundTasks` 调用 `execute_task`；定时扫描由 `_scheduler_loop` 在应用启动时 `asyncio.create_task` 创建，30 秒间隔扫描到期的 active 调度。`sandbox_ns.py` 提供算子沙箱命名空间（`build_operator_namespace`），供 `task_runner` 和 `operator.py` 共用。

#### 2.9.2 调度配置模型
```python
class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # 任务类型和目标
    task_type = Column(String(20), nullable=False)  # pipeline, operator, skill
    task_target_id = Column(UUID(as_uuid=True), nullable=False)
    task_params = Column(JSON)  # 执行参数

    # 调度类型
    schedule_type = Column(String(20), nullable=False)  # cron, interval, manual

    # Cron配置
    cron_expression = Column(String(100))
    timezone = Column(String(50), default="Asia/Shanghai")

    # 间隔配置（秒）
    interval_seconds = Column(Integer)

    # 事件配置
    event_config = Column(JSON)

    # 执行配置
    max_retries = Column(Integer, default=3)
    retry_interval = Column(Integer, default=60)
    timeout = Column(Integer, default=3600)
    concurrent_runs = Column(Integer, default=1)

    # 状态
    status = Column(String(20), index=True, default="active")  # active, paused, stopped
    last_run_at = Column(DateTime)
    next_run_at = Column(DateTime)
    last_run_status = Column(String(20))

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    executions = relationship("TaskExecution", back_populates="schedule", lazy="selectin")
```

#### 2.9.3 任务执行模型
```python
class TaskExecution(Base):
    __tablename__ = "task_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="CASCADE"), index=True)

    # 任务信息
    task_type = Column(String(20), nullable=False)  # pipeline, operator, skill
    task_target_id = Column(UUID(as_uuid=True), nullable=False)

    # 执行信息
    status = Column(String(20), nullable=False, index=True)  # pending, running, success, failed, timeout
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration = Column(Integer)  # 秒

    # 执行结果
    result = Column(JSON)
    error_message = Column(Text)
    exit_code = Column(Integer)

    # 重试信息
    retry_count = Column(Integer, default=0)

    # 执行日志
    logs = Column(Text)

    # 血缘关系
    input_data = Column(JSON)
    output_data = Column(JSON)

    # 触发方式
    trigger_type = Column(String(20), default="schedule")  # schedule, manual, event
    triggered_by = Column(UUID(as_uuid=True))

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    schedule = relationship("Schedule", back_populates="executions")
```
### 2.10 元数据管理模块

#### 2.10.1 设计目标

对平台中所有数据集（数据源中的表/文件）建立统一的元数据中心，分为**技术元数据**和**业务元数据**两大类，支持：
- 技术元数据在配置数据源时一键自动同步
- 业务元数据通过大模型分析数据样本自动补充，也支持人工编辑
- 元数据全生命周期管理：采集 → 存储 → 补充 → 查询 → 血缘追踪

#### 2.10.2 元数据架构

```
┌──────────────────────────────────────────────────────────────────┐
│                     Metadata Manager                             │
├──────────────────┬──────────────────┬───────────────────────────┤
│  技术元数据       │  业务元数据       │  运营元数据               │
│  Technical       │  Business        │  Operational              │
├──────────────────┼──────────────────┼───────────────────────────┤
│ · 数据集ID        │ · 业务系统来源    │ · 最后访问时间             │
│ · 数据集名称      │ · 业务描述        │ · 访问次数                 │
│ · 数据集类型      │ · 业务标签(多)    │ · 最近同步时间             │
│ · 数据集格式      │ · 业务用途        │ · 数据变更记录             │
│ · 存放地址        │ · 数据域          │ · 质量评分                 │
│ · 格式定义(Schema)│ · 数据所有者      │ · 质量规则                 │
│ · 数据量预估      │ · 安全等级        │ · 数据血缘                 │
│ · 字段统计        │ · 保留策略        │                           │
│ · 分区信息        │                  │                           │
├──────────────────┼──────────────────┼───────────────────────────┤
│  ← 自动同步       │  ← AI补充 + 人工   │  ← 自动采集                │
│  (Connector提取)  │  (LLM分析样本)    │  (运行时记录)              │
└──────────────────┴──────────────────┴───────────────────────────┘
```

#### 2.10.3 元数据数据模型

```python
class TableMetadata(Base):
    """数据集元数据模型（一个数据源的一张表/文件 = 一条元数据记录）"""
    __tablename__ = "table_metadata"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    data_source_id = Column(UUID, ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)

    # ========== 技术元数据 ==========
    # 基础信息
    table_name = Column(String(200), nullable=False)          # 数据集名称（表名/文件名/Sheet名）
    table_type = Column(String(50))                           # 数据集类型: table, view, sheet, file
    storage_format = Column(String(50))                       # 数据集格式: csv, excel, parquet, mysql, postgres...
    storage_location = Column(String(500))                    # 存放地址: 文件路径 / 数据库主机:端口/库名
    source_connector = Column(String(50))                     # 来源连接器类型

    # Schema 定义
    table_schema = Column(JSON)                               # 格式定义: [{"name": "col", "dtype": "VARCHAR(255)", "nullable": true, "description": "..."}]
    primary_keys = Column(JSON)                               # 主键列
    indexes = Column(JSON)                                    # 索引信息

    # 数据量统计
    row_count = Column(BigInteger)                            # 行数（预估/实际）
    size_bytes = Column(BigInteger)                           # 存储大小（字节）
    column_count = Column(Integer)                            # 列数
    sample_data = Column(JSON)                                # 样本数据（前5行，用于AI分析）
    column_stats = Column(JSON)                               # 字段统计: {"col": {"min":.., "max":.., "null_rate":.., "unique_count":..}}

    # 分区与分区键（适用于大数据源）
    partition_info = Column(JSON)                             # 分区信息: {"partitioned": true, "partition_keys": ["date"], "partition_count": 30}

    # ========== 业务元数据 ==========
    business_name = Column(String(200))                      # 业务名称（如"全国重点文物保护单位名录"）
    business_description = Column(Text)                      # 业务描述
    business_tags = Column(JSON)                             # 业务标签（多个）: ["文物", "文化遗产", "国家级"]
    business_purpose = Column(Text)                           # 业务用途（如"用于文物统计分析与保护规划"）
    source_system = Column(String(200))                      # 产生该数据集的业务系统名称
    data_domain = Column(String(100))                        # 数据域: 文物、财务、人事、销售...
    data_owner = Column(String(100))                         # 数据所有者（部门/人）
    data_steward = Column(String(100))                       # 数据管理员

    # 安全与合规
    security_level = Column(String(20))                      # 安全等级: public, internal, confidential, secret
    retention_policy = Column(String(200))                   # 保留策略: 如"永久保留"、"保留5年"

    # ========== 运营元数据 ==========
    last_synced_at = Column(DateTime)                        # 最后技术元数据同步时间
    last_accessed_at = Column(DateTime)                      # 最后访问时间
    access_count = Column(Integer, default=0)                # 访问次数

    # 数据质量
    quality_rules = Column(JSON)                             # 质量规则: [{"rule": "not_null", "column": "name"}]
    quality_score = Column(Float)                            # 质量评分 (0-100)
    quality_details = Column(JSON)                           # 质量详情: {"completeness": 98.5, "accuracy": 95.0, "consistency": 100}

    # 数据血缘
    lineage = Column(JSON)                                   # 血缘关系: {"upstream": [...], "downstream": [...]}

    # AI 补充元数据
    ai_enriched = Column(Boolean, default=False)             # 是否经过AI补充业务元数据
    ai_enriched_at = Column(DateTime)                        # AI补充时间

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    data_source = relationship("DataSource", back_populates="table_metadata")
```

#### 2.10.4 技术元数据自动同步

在数据源创建/编辑时，用户可选择"同步技术元数据"，系统通过 Connector 自动提取所有表的技术元数据。

```python
# 数据源创建/编辑时的同步选项
class DataSourceSyncRequest(BaseModel):
    sync_technical_metadata: bool = True     # 是否同步技术元数据
    sample_rows: int = 5                     # 采样行数（用于AI分析和预览）
    max_tables: int = 100                    # 最大同步表数

# 同步流程
async def sync_technical_metadata(datasource: DataSource, db: AsyncSession):
    """
    1. 通过 Connector 获取数据源所有表/文件列表
    2. 对每个表提取技术元数据：
       a. 调用 connector.get_schema() → 表结构、字段类型
       b. 调用 connector.get_table_stats() → 行数、大小
       c. 调用 connector.get_table_data(table, page=1, page_size=5) → 样本数据
       d. 计算字段统计（空值率、唯一值数、min/max）
    3. 写入/更新 table_metadata 表
    4. 标记 last_synced_at
    """
    connector = get_connector(datasource.type, datasource.connection_config)
    try:
        schema_list = await connector.get_schema()          # 所有表/Sheet

        for table_info in schema_list:
            table_name = table_info["table_name"]

            # 提取表结构
            df_sample = await connector.get_table_data(table_name, page=1, page_size=5)
            stats = await connector.get_table_stats(table_name)

            # 计算字段统计
            column_stats = {}
            for col in df_sample.columns:
                column_stats[col] = {
                    "dtype": str(df_sample[col].dtype),
                    "null_rate": float(df_sample[col].isna().mean()),
                    "unique_count": int(df_sample[col].nunique()),
                }
                if df_sample[col].dtype in ['int64', 'float64']:
                    column_stats[col]["min"] = df_sample[col].min()
                    column_stats[col]["max"] = df_sample[col].max()

            # 推断存储格式
            storage_format = datasource.type  # mysql, excel, csv...

            # 推断存放地址
            if datasource.type in ("csv", "excel"):
                storage_location = datasource.connection_config.get("file_path", "")
            elif datasource.type in ("mysql", "postgres"):
                cfg = datasource.connection_config
                storage_location = f"{cfg.get('host')}:{cfg.get('port')}/{cfg.get('database')}"
            else:
                storage_location = str(datasource.connection_config)

            # 写入或更新（保留已有业务元数据，只更新技术元数据）
            existing = await db.execute(
                select(TableMetadata).where(
                    TableMetadata.data_source_id == datasource.id,
                    TableMetadata.table_name == table_name,
                )
            )
            meta = existing.scalar_one_or_none()

            tech_data = {
                "table_name": table_name,
                "table_type": table_info.get("table_type", "table"),
                "storage_format": storage_format,
                "storage_location": storage_location,
                "source_connector": datasource.type,
                "table_schema": [
                    {"name": c, "dtype": str(df_sample[c].dtype), "nullable": bool(df_sample[c].isna().any())}
                    for c in df_sample.columns
                ],
                "row_count": stats.get("row_count", 0),
                "column_count": len(df_sample.columns),
                "size_bytes": stats.get("size_bytes"),
                "sample_data": df_sample.fillna("").to_dict(orient="records"),
                "column_stats": column_stats,
                "last_synced_at": datetime.utcnow(),
            }

            if meta:
                for k, v in tech_data.items():
                    setattr(meta, k, v)
            else:
                meta = TableMetadata(data_source_id=datasource.id, **tech_data)
                db.add(meta)

        await db.flush()
    finally:
        await connector.close()
```

**同步时机：**
- 数据源创建时：用户勾选"同步技术元数据"（默认勾选）
- 数据源编辑时：用户手动触发"重新同步"
- 定时任务：可选配置定时同步（如每天凌晨）

#### 2.10.5 业务元数据 AI 补充

通过大模型分析样本数据和已有技术元数据，自动生成业务元数据建议。

```python
class BusinessMetadataAIRequest(BaseModel):
    table_metadata_id: UUID
    force_refresh: bool = False       # 是否强制重新生成

async def enrich_business_metadata(meta: TableMetadata, db: AsyncSession):
    """
    通过 LLM 分析样本数据，自动补充业务元数据：
    1. 将技术元数据 + 样本数据组装为 prompt
    2. LLM 推断业务名称、描述、标签、用途、数据域
    3. 用户确认后写入业务元数据字段
    """
    prompt = f"""请分析以下数据集的技术信息和样本数据，推断业务元数据。

## 技术信息
- 数据源名称: {meta.data_source.name if meta.data_source else '未知'}
- 数据集名称: {meta.table_name}
- 存储格式: {meta.storage_format}
- 字段结构: {json.dumps(meta.table_schema, ensure_ascii=False)}
- 行数: {meta.row_count}
- 字段统计: {json.dumps(meta.column_stats, ensure_ascii=False)}

## 样本数据（前5行）
{json.dumps(meta.sample_data, ensure_ascii=False, default=str)}

## 请输出 JSON 格式的业务元数据
{{
    "business_name": "数据集的业务名称",
    "business_description": "一段话描述这个数据集包含什么数据、有什么特征",
    "business_tags": ["标签1", "标签2", "标签3"],
    "business_purpose": "这个数据集可能的业务用途",
    "source_system": "可能产生该数据的业务系统",
    "data_domain": "数据域分类",
    "security_level": "public/internal/confidential/secret"
}}

只输出 JSON，不要任何解释。"""

    result = await llm_manager.chat_with_messages(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=500,
    )

    # 解析 LLM 输出并写入
    parsed = json.loads(result.strip().strip("```json").strip("```"))
    for key, value in parsed.items():
        setattr(meta, key, value)
    meta.ai_enriched = True
    meta.ai_enriched_at = datetime.utcnow()
    await db.flush()
```

#### 2.10.6 API 设计

```
# 技术元数据同步
POST   /api/v1/datasources/{id}/sync-metadata        # 触发技术元数据同步
GET    /api/v1/datasources/{id}/metadata              # 获取数据源下所有表的元数据

# 元数据 CRUD
GET    /api/v1/metadata                                # 元数据列表（支持筛选/搜索/分页）
GET    /api/v1/metadata/{table_metadata_id}            # 元数据详情
PUT    /api/v1/metadata/{table_metadata_id}            # 编辑元数据（主要编辑业务元数据）

# 业务元数据 AI 补充
POST   /api/v1/metadata/{table_metadata_id}/ai-enrich  # AI补充业务元数据

# 元数据搜索
GET    /api/v1/metadata/search?q=文物&tag=文化遗产      # 按名称/描述/标签搜索

# 元数据统计
GET    /api/v1/metadata/stats                          # 元数据统计概览
```

#### 2.10.7 前端页面设计

```
┌─────────────────────────────────────────────────────────────────┐
│  元数据管理                                                      │
├──────────┬──────────────────────────────────────────────────────┤
│ 筛选栏   │  元数据列表                                           │
│          │  ┌────────────────────────────────────────────────┐  │
│ 数据源▼  │  │ ☑ 全国重点文物 | excel | 988行 × 5列          │  │
│ 数据域▼  │  │   🏷 文物,文化遗产  | 业务名称: 全国文物名录   │  │
│ 标签▼    │  │   📊 质量: 98分 | 🕐 同步: 2024-01-15         │  │
│          │  ├────────────────────────────────────────────────┤  │
│ 搜索框   │  │ ☑ 销售明细表   | mysql | 50000行 × 12列       │  │
│ [搜索]   │  │   🏷 销售,财务    | 业务名称: 销售订单明细    │  │
│          │  │   📊 质量: 85分 | 🕐 同步: 2024-01-14         │  │
│          │  └────────────────────────────────────────────────┘  │
├──────────┴──────────────────────────────────────────────────────┤
│  元数据详情（点击列表项展开）                                     │
│  ┌──────────────────────┬─────────────────────────────────────┐ │
│  │ 技术元数据            │ 业务元数据                          │ │
│  │                      │                                     │ │
│  │ 数据集名称: 全国文物  │ 业务名称: [全国文物名录____]        │ │
│  │ 类型: excel/sheet     │ 业务描述: [包含全国重点文保单位___] │ │
│  │ 格式: excel           │ 业务标签: [文物] [文化遗产] [+]     │ │
│  │ 地址: D:\wenwu\...    │ 业务用途: [文物统计分析与保护规划_] │ │
│  │ 行数: 988             │ 来源系统: [国家文物局____________]  │ │
│  │ 列数: 5               │ 数据域:   [文物 ▼]                 │ │
│  │                      │ 安全等级: [internal ▼]              │ │
│  │ 字段定义:             │                                     │ │
│  │ ┌列名─类型─可空─描述─┐│ [AI补充业务元数据] [保存修改]       │ │
│  │ │名称  str   ✗   ___ ││                                     │ │
│  │ │时代  str   ✗   ___ ││                                     │ │
│  │ │批次  str   ✗   ___ ││                                     │ │
│  │ └───────────────────┘│                                     │ │
│  │                      │                                     │ │
│  │ [重新同步技术元数据]  │                                     │ │
│  └──────────────────────┴─────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.10.8 元数据在平台中的应用

| 应用场景 | 说明 |
|---------|------|
| **对话上下文** | chat.py 的 `build_datasource_context` 读取元数据，为 LLM 提供表结构、业务含义、数据域等上下文 |
| **技能/算子生成** | skill_creator / operator SYSTEM_PROMPT 注入元数据，让 LLM 了解数据结构再生成脚本 |
| **数据目录** | 前端元数据管理页面作为数据目录，用户可浏览搜索所有数据集 |
| **数据血缘** | 记录数据处理流程的输入/输出关系，追溯数据来源 |
| **数据质量监控** | 基于质量规则自动检测数据质量问题，计算质量评分 |
| **数据安全** | 按安全等级控制数据访问权限 |

#### 2.10.9 与数据源模块的集成

数据源创建/编辑流程中增加"同步技术元数据"选项：

```
数据源创建流程:
1. 用户填写连接配置 → 测试连接
2. 勾选"同步技术元数据"（默认勾选）
3. 系统自动:
   a. 获取所有表/Sheet 列表
   b. 逐表提取 Schema、行数、样本数据
   c. 写入 table_metadata 表
4. 创建完成 → 跳转元数据管理页面
5. 用户可点击"AI补充业务元数据"让 LLM 分析并填充业务字段
6. 用户可手动编辑业务元数据
```

数据源编辑流程中增加"重新同步"按钮，点击后重新提取技术元数据（保留已有业务元数据不覆盖）。

### 2.11 权限管理模块

#### 2.11.1 RBAC权限模型
```python
class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    # 用户信息
    display_name = Column(String(100))
    avatar = Column(String(500))
    
    # 状态    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)

class Role(Base):
    __tablename__ = "roles"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100))
    description = Column(Text)
    
    # 权限列表
    permissions = Column(JSON)  # ["code:view", "operator:use", "schedule:manage"]
    
    created_at = Column(DateTime, default=datetime.utcnow)

class Permission(Base):
    __tablename__ = "permissions"
    
    id = Column(UUID, primary_key=True)
    resource_type = Column(String(50))  # code, operator, datasource, schedule
    resource_id = Column(UUID)
    user_id = Column(UUID, ForeignKey("users.id"))
    role_id = Column(UUID, ForeignKey("roles.id"))
    
    # 权限级别
    permission_level = Column(String(20))  # view, use, manage
    
    created_at = Column(DateTime, default=datetime.utcnow)
```

#### 2.11.2 权限检查逻辑
```python
class PermissionChecker:
    """权限检查器"""
    
    async def check_permission(
        self,
        user: User,
        resource_type: str,
        resource_id: UUID,
        required_level: str  # view, use, manage
    ) -> bool:
        """检查权限"""
        
        # 超级用户拥有所有权限        if user.is_superuser:
            return True
        
        # 查询用户权限
        permissions = await self.get_user_permissions(
            user.id, 
            resource_type, 
            resource_id
        )
        
        # 权限级别映射
        level_map = {"view": 1, "use": 2, "manage": 3}
        
        # 检查权限        for perm in permissions:
            if level_map[perm.permission_level] >= level_map[required_level]:
                return True
        
        return False
```

### 2.14 数据标准 / 质量 / 安全规则库

三份 Markdown 规则库，作为 DataInspector 的检查依据，可在系统设置页查看编辑。

**存储**：
- 默认库（随代码发布，只读）：`backend/app/defaults/data_standards.md`、`data_quality_rules.md`、`data_security_rules.md`
- 运行时可编辑副本：`backend/data/standards/`（首次 GET 从默认库复制）

**规则库内容**：
| 规则库 | 编号 | 内容 |
|--------|------|------|
| 数据标准库 | STD-xxx | 字段级格式正则与约束：身份证(校验位)/统一社会信用代码/银行卡(Luhn)/手机号/邮箱/地址/邮编/IP/日期/金额/年龄/枚举/文物年代等 |
| 数据质量库 | DQ-xxx | DAMA 六维度(完整性/唯一性/有效性/一致性/准确性/及时性) + ETL 过程质量(数据量不增减/对数:记录数·金额·分组汇总/检索不超总量/空值率/主键唯一) + 业务规则 |
| 数据安全规则库 | SEC-xxx | PII 识别/凭证泄露(密码·API Key·私钥·连接串)/敏感业务数据(薪资·医疗·未成年)/数据分级/脱敏规则/合规留存 |

**API**：`GET/PUT /api/v1/config/data-standards|data-quality|data-security`，`POST .../reset`

**解析与执行**（`app/services/standards_parser.py`）：
- `parse_standards()` / `parse_quality_rules()` / `parse_security_rules()` 将 MD 解析为结构化规则
- DataInspector `build_system_prompt` 注入三份库全文
- `inspector_tools` 确定性执行：标准格式用正则(`match_columns` 匹配列名)、安全用正则扫描、质量用聚合；每条问题标注 `standard_id`(STD)/`rule_id`(DQ/SEC) + 严重等级 + 修复建议
- 语义类检查（业务逻辑、跨表一致性）由 LLM 判断

## 3. 数据库设计
### 3.1 核心表结构
#### 用户与权限表
```sql
-- 用户表CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    avatar VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE,
    is_superuser BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP
);

-- 角色表CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    permissions JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户角色关联表CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- 权限表CREATE TABLE permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_type VARCHAR(50) NOT NULL,
    resource_id UUID NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    permission_level VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 数据源表
```sql
-- 数据源表
CREATE TABLE data_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    type VARCHAR(50) NOT NULL,
    connection_config JSONB NOT NULL,
    metadata JSONB,
    business_metadata JSONB,
    security_level VARCHAR(20),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- 表元数据CREATE TABLE table_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    data_source_id UUID REFERENCES data_sources(id) ON DELETE CASCADE,
    table_name VARCHAR(200) NOT NULL,
    table_type VARCHAR(50),
    schema JSONB,
    row_count BIGINT,
    size_bytes BIGINT,
    business_name VARCHAR(200),
    business_description TEXT,
    data_domain VARCHAR(100),
    data_owner VARCHAR(100),
    quality_rules JSONB,
    quality_score FLOAT,
    security_level VARCHAR(20),
    lineage JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 算子与流程表
```sql
-- 算子表CREATE TABLE operators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200),
    description TEXT,
    category VARCHAR(50),
    inputs JSONB,
    outputs JSONB,
    parameters JSONB,
    execution_config JSONB,
    code_template TEXT,
    version VARCHAR(20) DEFAULT '1.0.0',
    tags JSONB,
    author UUID REFERENCES users(id),
    visibility VARCHAR(20),
    permissions JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 流程表（已废弃：composed_codes 表和代码已删除，由 pipelines 表替代）
-- 此表不再使用，流程数据存储在 pipelines 表中（见下方"流程表"章节）
```

#### 技能表（Skills）```sql
-- 技能表（注意：实际实现已简化，inputs/outputs/parameters/executor_config/usage_examples 等字段存储在 SKILL.md 文件中，不在数据库）
CREATE TABLE skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200),
    description TEXT NOT NULL,
    skill_type VARCHAR(50), -- operator, function, pipeline
    inputs JSONB,
    """
    {
        "data": {
            "type": "DataFrame",
            "description": "输入数据",
            "required": true
        }
    }
    """
    outputs JSONB,
    """
    {
        "result": {
            "type": "DataFrame",
            "description": "处理结果"
        }
    }
    """
    parameters JSONB,
    """
    {
        "columns": {
            "type": "list",
            "description": "选择的列",
            "required": true,
            "default": []
        }
    }
    """
    executor_config JSONB,
    """
    {
        "type": "python_function",
        "module": "app.skills.operators",
        "function": "select_operator"
    }
    """
    usage_examples JSONB,
    """
    [
        "选择用户表中的姓名和年龄",
        "从订单数据中提取订单号和金额"
    ]
    """
    tags JSONB,
    """
    ["数据选择", "列操作", "基础技能"]
    """
    category VARCHAR(50),
    """
    transform, aggregate, filter, join, analyze
    """
    version VARCHAR(20) DEFAULT '1.0.0',
    author UUID REFERENCES users(id),
    visibility VARCHAR(20), -- private, public, shared
    permissions JSONB,
    usage_count INTEGER DEFAULT 0,
    success_rate FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 技能版本历史表
CREATE TABLE skill_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id UUID REFERENCES skills(id) ON DELETE CASCADE,
    version VARCHAR(20) NOT NULL,
    definition JSONB NOT NULL,
    change_log TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(skill_id, version)
);

#### 流程表
```sql
CREATE TABLE pipelines (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200),
    description TEXT,

    -- Python 主函数源码
    main_code TEXT NOT NULL,

    -- 主函数签名
    entry_function VARCHAR(100) DEFAULT 'main',
    parameters JSON,

    -- 调用关系（主函数调用了哪些 Skill 脚本）
    skill_calls JSON,

    -- 来源
    source_skill_id UUID,

    -- 元数据
    version INTEGER DEFAULT 1,
    tags JSON,
    category VARCHAR(50),
    created_by UUID REFERENCES users(id),
    visibility VARCHAR(20) DEFAULT 'private',

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pipeline_executions (
    id UUID PRIMARY KEY,
    pipeline_id UUID REFERENCES pipelines(id) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    inputs JSON,
    outputs JSON,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_ms INTEGER,
    error_message TEXT,
    logs TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
#### 调度与执行表
```sql
CREATE TABLE schedules (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    task_type VARCHAR(20) NOT NULL,
    task_target_id UUID NOT NULL,
    task_params JSON,
    schedule_type VARCHAR(20) NOT NULL,
    cron_expression VARCHAR(100),
    timezone VARCHAR(50) DEFAULT 'Asia/Shanghai',
    interval_seconds INTEGER,
    event_config JSON,
    max_retries INTEGER DEFAULT 3,
    retry_interval INTEGER DEFAULT 60,
    timeout INTEGER DEFAULT 3600,
    concurrent_runs INTEGER DEFAULT 1,
    status VARCHAR(20) DEFAULT 'active',
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    last_run_status VARCHAR(20),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE task_executions (
    id UUID PRIMARY KEY,
    schedule_id UUID REFERENCES schedules(id) ON DELETE CASCADE,
    task_type VARCHAR(20) NOT NULL,
    task_target_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration INTEGER,
    result JSON,
    error_message TEXT,
    exit_code INTEGER,
    retry_count INTEGER DEFAULT 0,
    logs TEXT,
    input_data JSON,
    output_data JSON,
    trigger_type VARCHAR(20) DEFAULT 'schedule',
    triggered_by UUID,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 数据源管理API
```
POST   /api/v1/datasources              # 创建数据源
GET    /api/v1/datasources              # 获取数据源列表
GET    /api/v1/datasources/{id}         # 获取数据源详情
PUT    /api/v1/datasources/{id}         # 更新数据源
DELETE /api/v1/datasources/{id}         # 删除数据源
POST   /api/v1/datasources/{id}/test    # 测试连接
GET    /api/v1/datasources/{id}/schema  # 获取数据源结构
```

#### 算子管理API
```
POST   /api/v1/operators                # 创建算子
GET    /api/v1/operators                # 获取算子列表
GET    /api/v1/operators/{id}           # 获取算子详情
PUT    /api/v1/operators/{id}           # 更新算子
DELETE /api/v1/operators/{id}           # 删除算子
GET    /api/v1/operators/categories     # 获取算子分类
```

#### 调度管理API
```
POST   /api/v1/schedules                # 创建调度
GET    /api/v1/schedules                # 获取调度列表
GET    /api/v1/schedules/{id}           # 获取调度详情
PUT    /api/v1/schedules/{id}           # 更新调度
DELETE /api/v1/schedules/{id}           # 删除调度
POST   /api/v1/schedules/{id}/pause     # 暂停调度
POST   /api/v1/schedules/{id}/resume    # 恢复调度
POST   /api/v1/schedules/{id}/trigger   # 手动触发（BackgroundTasks 后台执行）
GET    /api/v1/schedules/{id}/executions # 获取执行历史
GET    /api/v1/schedules/executions/{exec_id} # 获取执行详情
POST   /api/v1/schedules/validate-cron  # Cron 表达式校验
GET    /api/v1/schedules/stats/overview # 调度统计概览
```

#### 技能管理API
```
# 技能CRUD
POST   /api/v1/skills                    # 创建技能GET    /api/v1/skills                    # 获取技能列表GET    /api/v1/skills/{id}               # 获取技能详情PUT    /api/v1/skills/{id}               # 更新技能DELETE /api/v1/skills/{id}               # 删除技能
# 技能操作POST   /api/v1/skills/{id}/execute       # 执行单个技能POST   /api/v1/skills/{id}/test          # 测试技能执行GET    /api/v1/skills/{id}/versions      # 获取技能版本历史POST   /api/v1/skills/{id}/rollback      # 回退技能版本POST   /api/v1/skills/{id}/validate      # 验证技能定义
# 技能发布GET    /api/v1/skills/categories         # 获取技能分类GET    /api/v1/skills/search             # 搜索技能POST   /api/v1/skills/recommend          # 推荐相关技能
# 技能转换POST   /api/v1/skills/from-operator      # 从算子创建技能POST   /api/v1/skills/from-code          # 从代码创建技能POST   /api/v1/skills/from-nl            # 自然语言创建技能
# 技能模板GET    /api/v1/skills/templates          # 获取技能模板列表POST   /api/v1/skills/templates/{id}/apply # 应用技能模板```

#### Skill 与 Pipeline API 详细说明

##### 创建技能```json
POST /api/v1/skills
Request:
{
    "name": "filter_rows",
    "display_name": "数据过滤",
    "description": "根据条件过滤数据",
    "skill_type": "operator",
    "inputs": {
        "data": {
            "type": "DataFrame",
            "description": "输入数据",
            "required": true
        }
    },
    "outputs": {
        "result": {
            "type": "DataFrame",
            "description": "过滤后的数据"
        }
    },
    "parameters": {
        "condition": {
            "type": "str",
            "description": "过滤条件表达式",
            "required": true
        }
    },
    "executor_config": {
        "type": "python_function",
        "module": "app.skills.operators",
        "function": "filter_operator"
    },
    "usage_examples": [
        "过滤年龄大于18的用户",
        "筛选销售额超过1000的订单"
    ],
    "tags": ["过滤", "数据清洗"],
    "category": "filter",
    "visibility": "public"
}

Response:
{
    "id": "uuid",
    "name": "filter_rows",
    "status": "created",
    "validation_result": {
        "valid": true,
        "test_passed": true
    }
}
```

##### 自然语言创建技能```json
POST /api/v1/skills/from-nl
Request:
{
    "description": "创建一个技能，用于计算数据的平均值、最大值、最小值和标准差",
    "user_id": "uuid"
}

Response:
{
    "skill": {
        "id": "uuid",
        "name": "calculate_statistics",
        "display_name": "统计分析",
        "description": "计算数据的统计指标",
        "skill_type": "operator",
        "inputs": {...},
        "outputs": {...},
        "parameters": {...}
    },
    "generated_code": "def calculate_statistics(data, columns=None): ...",
    "validation_passed": true
}
```

##### 创建 Pipeline
```json
POST /api/v1/skill-pipelines
Request:
{
    "name": "sales_analysis_pipeline",
    "display_name": "销售数据分析流水线",
    "description": "清洗、过滤、聚合销售数据",
    "skill_steps": [
        {
            "step_id": "step_1",
            "skill_id": "skill_uuid_1",
            "skill_name": "数据清洗",
            "order": 1,
            "input_mapping": {"data": "$input.raw_data"},
            "output_mapping": {"result": "$context.cleaned_data"},
            "parameters": {"remove_duplicates": true, "fill_na": "mean"}
        },
        {
            "step_id": "step_2",
            "skill_id": "skill_uuid_2",
            "skill_name": "数据过滤",
            "order": 2,
            "input_mapping": {"data": "$context.cleaned_data"},
            "output_mapping": {"result": "$context.filtered_data"},
            "parameters": {"condition": "sales > 1000"}
        },
        {
            "step_id": "step_3",
            "skill_id": "skill_uuid_3",
            "skill_name": "分组聚合",
            "order": 3,
            "input_mapping": {"data": "$context.filtered_data"},
            "output_mapping": {"result": "$output.analysis_result"},
            "parameters": {"group_by": "category", "aggregations": {"sales": "sum"}}
        }
    ],
    "input_schema": {
        "raw_data": {
            "type": "DataFrame",
            "description": "原始销售数据",
            "required": true
        }
    },
    "output_schema": {
        "analysis_result": {
            "type": "DataFrame",
            "description": "分析结果"
        }
    },
    "visibility": "public"
}

Response:
{
    "id": "uuid",
    "name": "sales_analysis_pipeline",
    "status": "created",
    "validation_result": {
        "valid": true,
        "dependency_check_passed": true
    }
}
```

##### 执行 Pipeline（流式）
```json
GET /api/v1/skill-pipelines/{id}/run/streaming
Request (Query Parameters):
{
    "inputs": {
        "raw_data": "data_source_id or DataFrame"
    }
}

Response (SSE Stream):
event: pipeline_start
data: {"execution_id": "uuid", "total_steps": 3}

event: step_start
data: {"step_index": 1, "step_id": "step_1", "skill_name": "数据清洗"}

event: step_complete
data: {"step_index": 1, "success": true, "output_preview": {...}}

event: step_start
data: {"step_index": 2, "step_id": "step_2", "skill_name": "数据过滤"}

event: step_complete
data: {"step_index": 2, "success": true, "output_preview": {...}}

event: step_start
data: {"step_index": 3, "step_id": "step_3", "skill_name": "分组聚合"}

event: step_complete
data: {"step_index": 3, "success": true, "output_preview": {...}}

event: pipeline_complete
data: {"outputs": {...}, "duration": 2.5}
```

## 5. 部署架构

### 5.1 单机部署架构
```
┌───────────────────────────────────────────────┐
│               本地开发 / 生产部署              │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  Frontend (Vite Dev / Nginx)          │   │
│   │  - Vue 3 SPA                          │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Backend (uvicorn)                    │   │
│   │  - FastAPI 应用                       │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  SQLite / PostgreSQL                  │   │
│   │  - 业务数据                           │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  本地文件系统                          │   │
│   │  - 数据源文件 / 技能包                 │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

### 5.2 Docker Compose配置（可选）

> 生产环境可使用 Docker Compose 部署，开发环境使用 `npm run dev` 即可（见 INSTALL.md）。

```yaml
version: '3.8'

services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - frontend
      - backend

  frontend:
    build: ./frontend
    environment:
      - VITE_API_URL=http://backend:8000
    depends_on:
      - backend

  backend:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/datacrab
    depends_on:
      - postgres

  postgres:
    image: postgres:14-alpine
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=datacrab
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

## 6. 安全设计

### 6.1 操作边界（核心安全原则）

**DataCrab 不能修改平台自身，但可以帮用户创建和修改用户自己的对话、算子、技能。**

| 类别 | 说明 | 能否修改 |
|------|------|----------|
| DataCrab 平台自身 | 源代码、配置、用户/角色/权限、系统表、基础设施 | ❌ 禁止 |
| 用户定义的对话 | 用户创建的会话、消息 | ✅ 允许 |
| 用户定义的算子 | 用户创建的算子脚本 | ✅ 允许 |
| 用户定义的技能 | 用户创建的技能包和脚本 | ✅ 允许 |
| 用户的业务数据 | 数据源中的业务数据 | ✅ 允许 |
| 自定义数据源连接器 | 用户用自然语言添加的数据源连接器（AI 生成代码，沙箱加载） | ✅ 允许（仅此两项平台扩展） |
| 自定义模型适配器 | 用户用自然语言添加的 LLM 适配器（AI 生成代码，沙箱加载） | ✅ 允许（仅此两项平台扩展） |

此规则已写入：
- personal.md（最高优先级行为规则）
- chat.py _build_system_prompt（对话提示词）
- operator.py SYSTEM_PROMPT（算子提示词）
- skill.py 调试助手/修改提示词（技能提示词）
- skill_creator.py SKILL_CREATOR_SYSTEM_PROMPT（技能创建提示词）
- pipeline_builder.py PIPELINE_BUILDER_SYSTEM_PROMPT（流程提示词）

### 6.2 数据安全
- **传输加密**: HTTPS/TLS加密传输
- **存储加密**: 敏感数据加密存储
- **数据脱敏**: 敏感字段脱敏显示
- **安全分级**: 数据安全等级分类

### 6.3 安全防护
- **SQL注入防护**: 参数化查询- **XSS防护**: 输入输出转义
- **CSRF防护**: CSRF Token验证
- **限流防护**: API访问限流

## 7. 监控与运维
### 7.1 监控指标
- **系统指标**: CPU、内存、磁盘、网络- **应用指标**: 请求量、响应时间、错误率
- **业务指标**: 流程执行数、成功率、失败率

### 7.2 日志管理
- **应用日志**: 应用运行日志
- **访问日志**: API访问日志
- **审计日志**: 用户操作审计日志
- **执行日志**: 流程执行日志

### 7.3 告警机制
- **系统告警**: 资源使用率告警- **应用告警**: 服务异常告警
- **业务告警**: 任务失败告警

## 8. 扩展性设计
### 8.1 插件机制
- **数据源插件**: 支持自定义数据源连接器- **算子插件**: 支持自定义算子开发- **认证插件**: 支持自定义认证方式- **存储插件**: 支持自定义存储后端
### 8.2 水平扩展
- **无状态服务**: API服务无状态设计
- **负载均衡**: 支持多实例负载均衡
- **异步任务**: asyncio 协程 + subprocess 沙箱执行
- **数据库分片**: 支持数据库分片扩展
## 9. 开发规范
### 9.1 代码规范
- **Python**: PEP 8 + Black格式化
- **TypeScript**: ESLint + Prettier
- **Git提交**: Conventional Commits（中文描述，feat:/fix: 前缀）
- **代码审查**: Pull Request审查机制

### 9.2 测试规范
- **单元测试**: pytest + unittest
- **集成测试**: pytest-asyncio
- **E2E测试**: Playwright
- **覆盖率**: > 80%

### 9.3 文档规范
- **API文档**: OpenAPI/Swagger
- **代码文档**: Docstring
- **用户文档**: Markdown
- **部署文档**: Docker Compose

## 10. 技术风险与应对

### 10.1 性能风险
- **风险**: 大数据量处理性能问题
- **应对**: 分批处理、流式处理、异步执行
### 10.2 可靠性风险- **风险**: 任务执行失败
- **应对**: 重试机制、事务回滚、状态恢复
### 10.3 安全风险
- **风险**: 数据泄露、恶意攻击- **应对**: 加密存储、访问控制、安全审计
### 10.4 扩展性风险- **风险**: 系统扩展困难
- **应对**: 模块化设计、插件机制、微服务架构

## 11. 工程改进记录（借鉴 DeepAnalyze）

本章节记录借鉴 DeepAnalyze 通用 Agent 平台设计思想后，对 DataCrab 做的工程改进。每项改进标注了对应的文件和设计理念来源。

### 11.1 工具系统改进

#### 工具去重（shared_tools.py）
- **问题**：`agent.py` 和 `data_processor_agent.py` 有 5 个工具的 schema 和实现完全 copy-paste
- **改进**：提取 `shared_tools.py`，统一定义 7 个公共工具的 schema + 实现，两个 Agent 各自 import
- **理念**：借鉴 DeepAnalyze 的 ToolRegistry 统一管理思想

#### 工具结果截断（agent_utils.py → truncate_tool_result）
- **问题**：`query_table_data` 默认返回 100 行全量 JSON，多轮查询撑爆上下文
- **改进**：工具返回 JSON 超 8000 字符时自动截断为前 5 行 + 列名 + 总行数 + 截断提示
- **理念**：借鉴 DeepAnalyze 的 Micro-Compact 策略

#### 工具诚实能力表（tool_guidance.py）
- **问题**：工具描述只说能做什么，不说不能做什么，模型误用工具
- **改进**：给每个工具标注覆盖率/精确度/已知局限，作为能力表注入 system prompt
- **理念**：借鉴 DeepAnalyze 的"工具诚实"原则——把工具弱点如实写出来，模型才能正确组合工具

### 11.2 Agent Loop 改进

#### 卡死检测（agent_utils.py → StuckDetector）
- **问题**：Agent loop 只有 `MAX_AGENT_ITERATIONS=12` 硬上限，不检测原地打转
- **改进**：检测重复调用（连续 2 轮相同工具+参数）和空转（连续 3 轮无工具调用），注入策略切换提示
- **理念**：借鉴 DeepAnalyze 的 StuckDetector（四种卡死模式，DataCrab 取两种）

#### 反幻觉检查（agent_utils.py → is_planning_only / should_warn_ungrounded_claim）
- **问题**：Agent 可能"只规划不执行"或输出无工具支撑的数据声明（曾出过"AI虚构数据"bug）
- **改进**：
  - finish 前检查输出是否只是规划文本（"我将...然后..."），如果是则拒绝结束
  - 工具结果携带 `_source` 来源标记（datasource:xxx/table:yyy）
- **理念**：借鉴 DeepAnalyze 的"防只规划不执行"和零幻觉六层防御

#### Handoff 收敛检测（data_harness.py → ConvergenceGuard）
- **问题**：processor↔inspector 可能对同一问题来回踢皮球，白耗 10×12=120 次 API 调用
- **改进**：`ConvergenceGuard` 非侵入式组件，`record()` 记录 handoff 签名（to_agent, datasource_id, table_name），`is_diverged()` 判断连续 4 次在同一张表上来回则终止；multi_agent.py 只调 3 行，不再内联签名追踪
- **理念**：借鉴 DeepAnalyze 的收敛检测思想；流程层 Harness 非侵入式，业务代码不感知检测细节

### 11.3 上下文管理改进

#### CJK 感知 Token 估算（agent_utils.py → estimate_tokens）
- **问题**：`_compress_history` 用字符数（`len()`）做触发判断，中文场景误差大
- **改进**：CJK 字符 ×1.5、非 ASCII ×0.5、ASCII ×0.25 估算 token 数
- **理念**：借鉴 DeepAnalyze 的 CJK 感知 Token 估算

#### 压缩标识符保护（agent_utils.py → extract_identifiers / build_identifier_hint）
- **问题**：历史摘要后 Agent 忘了之前查过什么表/数据源，又重复搜索
- **改进**：压缩时机械抽取 UUID/表名/数据源 ID，在摘要 prompt 中要求保留这些标识符
- **理念**：借鉴 DeepAnalyze 的标识符保护原则

### 11.4 LLM 调用改进

#### 瞬态重试（llm.py → _acreate_with_retry）
- **问题**：429 限流/网络超时直接换模型，不重试同一模型；tenacity 声明了但没用
- **改进**：对 RateLimitError/APITimeoutError/APIConnectionError/InternalServerError 做最多 2 次指数退避重试（2s→4s），重试耗尽再走 model-chain fallback
- **理念**：借鉴 DeepAnalyze 的四级错误恢复链第一层

### 11.5 路由改进

#### 统一路由 + Agent 自主 handoff（chat.py）
- **问题**：`_route_to_agent` 用关键词匹配预判路由（"检查/质量"→inspector），边界场景误判
- **改进**：始终从 DataProcessorAgent 开始，Agent 自主决定是否 handoff 给 inspector；`_route_to_agent` 函数已删除
- **理念**：借鉴 DeepAnalyze 的"Agent 自主性"原则——系统给信号不给约束

### 11.6 经验库改进

#### 跨算子经验聚合（experience.py → distill_cross_patterns）
- **问题**：经验按算子/skill 独立积累，缺少跨算子的通用模式发现
- **改进**：`distill_cross_patterns()` 收集所有算子/技能的 lessons，用 LLM 提炼通用数据处理模式，存到 `global_lessons.md`
- **理念**：借鉴 DeepAnalyze 的 AutoDream 跨会话经验整合思想

### 11.7 工程卫生

#### 测试覆盖（tests/）
- **问题**：`backend/tests/` 完全为空，零测试覆盖
- **改进**：为 `agent_utils.py`、`experience.py`、`shared_tools.py` 的纯函数写单元测试（64 个测试用例）
- **覆盖**：token 估算、结果截断、卡死检测、标识符抽取、反幻觉检查、动态轮次预算、上下文压力告警、三级反幻觉、搜索饱和检测、工具结果缓存、经验读写、工具 schema 验证

#### 清理未使用依赖（pyproject.toml）
- **问题**：`redis`、`celery`、`minio`、`elasticsearch` 声明了但代码里没用
- **改进**：从 `pyproject.toml` 移除 4 个未使用依赖

#### CLAUDE.md
- **问题**：项目没有 AI 协作配置文件
- **改进**：创建 `CLAUDE.md`，记录技术栈、关键文件导航、运行命令、编码规范

### 11.8 新增文件清单

| 文件 | 说明 |
|------|------|
| `backend/app/services/agent_utils.py` | Agent 工程工具函数（token 估算、截断、卡死检测、标识符抽取、反幻觉、动态轮次预算、上下文压力告警、三级反幻觉、搜索饱和检测、工具结果缓存） |
| `backend/app/services/shared_tools.py` | 7 个公共工具的统一 schema + 实现（含 LRU 缓存） |
| `backend/app/services/tool_guidance.py` | 工具诚实能力表 |
| `backend/tests/test_agent_utils.py` | agent_utils 单元测试 |
| `backend/tests/test_experience.py` | experience 单元测试 |
| `backend/tests/test_shared_tools.py` | shared_tools + tool_guidance 单元测试 |
| `CLAUDE.md` | 项目级 AI 协作配置 |

### 11.9 推理截断修复

#### 问题
技能/算子/流程调试助手的 AI 推理过程（thinking）被截断，用户看到推理断在中间。

#### 根因
第四轮优化"防止推理链无限拉长"时引入两个问题：
1. `llm.py:544` 升级恢复条件含 `not has_content` 守卫——当推理长但有部分正文时**不升级重试**，推理断在中间
2. `max_tokens=4000` 对 GLM-5.2 等推理模型太紧（推理+正文共享预算）
3. `clear_thinking` 事件只清推理不清正文——即使升级重试也会正文重复

#### 改进
| 文件 | 改动 |
|------|------|
| `llm.py:544` | 去掉 `not has_content` 守卫，任何 `finish_reason=length` 都升级重试（4K→8K→16K） |
| `skill.py:1158` | debug-chat `max_tokens` 4000→8000，给推理模型足够预算 |
| `SkillView.vue` / `OperatorView.vue` / `PipelineView.vue` | `clear_thinking` 同时清 `content` + 重置 `thinkingDone`，防重试时正文重复 |

### 11.10 debug-chat `{{}}` bug 修复

#### 问题
技能调试助手 AI 修改脚本后，`script_updated` 事件不触发，脚本写不回磁盘，报 `unhashable type: 'dict'`。

#### 根因
`skill.py:1186-1194` 存在 f-string 转义残留：`{{}}` 实际是 `{ {} }`（含空字典的集合），运行到该行抛 `TypeError: unhashable type: 'dict'`。该行在 modify_script 处理之前执行，导致 AI 的修改代码永远写不回磁盘。

#### 改进
`skill.py`：`{{}}` → `{}`，`{{"action": "run", ...}}` → `{"action": "run", ...}`（3 处）

### 11.11 执行参数记忆

#### 问题
技能调试助手中，用户说"ID和时间戳没写进去"（不提数据源名），AI 改完脚本后 run action 传空参数 `{}`，技能报"缺少必要迁移参数"。经验库 `experience.json` 的 `positive` 记录了成功参数但**从未回灌给 AI**。

#### 根因
DataCrab 调试助手记忆机制有 4 层，但存在关键断点：
- **第 1 层 对话历史**：`history[-10:]`，每条截断 500 字，不含执行参数
- **第 2 层 执行上下文**：只反映当前输入框的值，不是历史执行参数
- **第 3 层 经验库**：`positive` 记录了成功参数，但 `read_lessons()` 只读文本总结，不读具体参数
- **第 4 层 错误日志**：仅用于 LLM 归纳经验

#### 改进
| 文件 | 改动 |
|------|------|
| `skill.py` | debug-chat system prompt 注入最近一次成功执行的参数（从 `experience.json` 的 `positive` 中取，过滤 `success: True` 的条目） |
| `skill.py` | 兜底：run action 参数为空时自动从最近成功记录填充 |

### 11.12 沙箱函数补全

#### 问题
AI 调试助手修改脚本时用了 `log("info", ...)` 函数，但 skill_runner 沙箱未注入 `log`，执行报 `NameError: 内置函数 'log' 不存在`。

#### 根因
1. 调试助手 system prompt **未声明沙箱可用函数清单**，AI 不知道 `log` 不存在
2. `get_datasource_id_by_name` / `get_table_schema` 只有 `_dc_` 前缀版，技能不通过 `_get_builtin_func` 直接调用会找不到

#### 改进
| 文件 | 改动 |
|------|------|
| `skill_runner.py` | 沙箱新增 `log(level, message)` 函数 → `print(f"[{LEVEL}] {message}")`；`get_datasource_id_by_name`、`get_table_schema` 注入 builtins |
| `skill.py` | debug-chat system prompt 引用共享 `SANDBOX_TOOLS_DOC`（prompt_docs.py），替代内联描述；`SANDBOX_TOOLS_DOC` 已标注所有函数返回类型（如 `get_table_data` 返回 dict 而非 DataFrame），修复 AI 误用导致的 `'dict' object has no attribute 'columns'` |

### 11.13 自愈循环

#### 问题
调试助手执行失败后只重试 1 次（`range(2)`）就放弃，不继续修复。

#### 改进
| 文件 | 改动 |
|------|------|
| `skill.py` | `range(2)` → `range(5)`：最多 5 轮自愈（初始 + 4 次重试），每轮失败自动反馈错误信息给 AI 继续修 |
| `skill.py` | 5 轮全失败后，让 AI 分析无法修复的原因，输出 `give_up` 事件 |
| `SkillView.vue` | 新增 `retry` 事件处理（显示"🔄 第N次修复尝试"分隔符）和 `give_up` 事件处理（显示"⚠ 无法修复"原因） |

### 11.14 失败检测修复

#### 问题
技能返回 `{"success": False, "error": "缺少必要迁移参数"}` 时，调试助手判定为**成功**（因为 `run_skill_script` 的 `success` 只表示"脚本没崩溃"，技能自身的 `success` 嵌在 `result` 字段里未被检查）。导致失败不触发自愈重试，还误存为正例。

#### 根因
`run_skill_script` 返回结构：
```python
{"success": True,           # 脚本 exit code 0（没崩溃）
 "result": {"success": False, "error": "xxx"},  # 技能自身的返回（嵌在里面）
 "error": None}             # runner 无错误
```
旧代码 `if not exec_result.get("success"):` 只检查外层，漏判技能级失败。

#### 改进
| 文件 | 改动 |
|------|------|
| `skill.py` | 失败判定改为两层检查：runner 级（`not success` / 有 error）+ 技能级（`result.success is False` / `result.error` 非空） |
| `SkillView.vue` | `run_result` 显示也同步检查内层 `result.success` / `result.error` |

### 11.15 调试页面集成多智能体（已完成）

#### 目标
所有调试页面（技能/算子/流程）与聊天页面一致，使用 DataProcessor + DataInspector 多智能体架构。

#### 实现
详见 §2.7.16。采用 Orchestrator-Worker 模式：

| 改动 | 文件 | 说明 |
|------|------|------|
| 流式工具调用方法 | llm.py | 新增 `chat_stream_with_tools_and_thinking()`，流式推理 + 工具调用 + 长度升级三合一 |
| DataProcessor 调试模式 | data_processor_agent.py | 新增 `modify_script`/`run_script` 工具 + `run_debug()` 流式方法 + debug 模式 system prompt + `_execute_tool` 支持 skill/operator/pipeline 三种类型 |
| 技能 debug-chat | skill.py | 手写 LLM 循环 → AgentRuntime 调用（-180 行） |
| 算子 debug-chat | operator.py | 同上（-90 行） |
| 流程 debug-chat | pipeline.py | 同上 |
| 前端事件处理 | SkillView/OperatorView/PipelineView.vue | 新增 `inspecting`/`retry`/`give_up` 事件处理 |

#### 架构变化
```
改造前：调试页面 → 手写 LLM 循环（正则解析 action）→ 执行 → 结束
改造后：所有页面 → AgentRuntime → DataProcessor（流式推理+工具调用）→ DataInspector
```

### 11.16 Orchestrator-Worker 粒度设计

#### 设计原则
Agent 用于复杂推理，Tool 用于简单操作。

| 操作 | 复杂度 | 形态 | 原因 |
|------|--------|------|------|
| modify_script | 低（代码合并） | Tool | 一次函数调用，不需要 LLM 推理 |
| run_script | 低（沙箱执行） | Tool | 执行脚本返回结果，不需要 LLM 推理 |
| 数据质量检查 | 高（多轮推理） | Agent (Worker) | 决定查什么、解读结果、判断严重等级 |

#### 参考框架
- Claude Code：主 Agent 直接有简单工具（Read/Write/Bash），复杂任务才 spawn subagent
- OpenAI Agents SDK：Agent = 指令 + 工具 + handoff，简单操作用工具不复用 Agent
- DataCrab：DataProcessor 直接有 modify_script/run_script，复杂检查 delegate 给 DataInspector

### 11.17 非侵入式 Harness 架构（data_harness.py）

#### 问题
流程层 Harness 逻辑（收敛检测、经验采集）散落在业务代码中，skill.py / operator.py 各自内联实现，~50 行重复代码，且文档漂移导致 bug。

#### 设计原则
数据层 Harness 保持侵入式（必须看到数据内容），流程层 Harness 非侵入式（业务代码只调一行）。

| 层 | 组件 | 侵入性 | 原因 |
|----|------|--------|------|
| 数据层 | `get_table_data` / `write_table_data` / `inspector_tools` | 侵入式 | 必须访问数据内容、拦截写操作 |
| 流程层 | `ConvergenceGuard` / `collect_experience` | 非侵入式 | 只需执行结果，不需感知数据细节 |

#### 组件

##### ConvergenceGuard
```python
guard = ConvergenceGuard(threshold=4)
guard.record(to_agent, datasource_id, table_name)
if guard.is_diverged():  # 连续 4 次同表来回
    terminate()
```
multi_agent.py 从 13 行内联签名追踪 → 3 行调用。

##### collect_experience
```python
collect_experience(base, source="debug", exec_result=result, parameters=params, script_name=name)
# 内部自动判断：失败→记录反例，成功+有历史失败→记录正例
```
skill.py / operator.py 从 4 处 ~50 行内联采集 → 各 6 行调用。

#### 理念
借鉴 Vibe Coding 的 test harness 非侵入模式：harness 包裹在代码外部，被测代码不感知 harness 存在。数据场景特化：数据层必须侵入（状态+副作用+内容依赖），流程层可以非侵入。

### 11.18 调度系统落地 + 死代码清理 + EP 中文化

| 改进 | 文件 | 说明 |
|------|------|------|
| 调度系统后台执行 | task_runner.py（新增）+ schedule.py | `execute_task()` 按 task_type 分派到 skill（to_thread）/ operator（exec+func）/ pipeline（await execute_pipeline）；trigger 端点接入 BackgroundTasks 实际执行；更新 TaskExecution + Schedule 记录 |
| 定时调度扫描器 | task_runner.py + main.py | 30s 间隔扫描 `next_run_at <= now()` 的 active 调度；并发控制（concurrent_runs）+ next_run_at 重算防重复触发；lifespan 启停（start_scheduler/stop_scheduler） |
| 沙箱命名空间抽出 | sandbox_ns.py（新增）+ operator.py | `build_operator_namespace` + `run_async_in_thread` 从 operator.py 端点移至 service 层，消除 API→service 反向依赖 |
| Element Plus 中文化 | main.ts | `app.use(ElementPlus, { locale: zhCn })` |
| 死代码清理 | 多文件 | 删除 CodeView/ExploreView/Notebook 全套（前后端+model+schema+路由，净减 1159 行）；skill_executor.py 精简至 2 个 dataclass（333→37 行） |

### 11.19 调试 Loop 强化

| 改进 | 文件 | 说明 |
|------|------|------|
| 强制每轮执行 | data_processor_agent.py | DEBUG_INSTRUCTIONS 重写：每轮必须调用 modify_and_run，根因分析放 thinking 不放正文，禁止"只规划不执行"的纯文字输出 |
| AST 脚本智能压缩 | data_processor_agent.py | `_extract_script_for_context`：超 5 万字符脚本用 AST 保留所有函数签名+docstring，大函数缩略为首尾 5 行+省略标注；语法错误时回退原始截断 |
| 工具结果智能压缩 | data_processor_agent.py | `_compress_tool_result`：失败保留全量错误信息，成功只保留摘要+少量数据行，降低上下文占用 |
| handoff 参数简化 | data_processor_agent.py | `handoff_to_inspector` 去掉 datasource_id/table_name 必填，自动使用当前调试上下文的数据源与表 |
| 工具异常兜底 | data_processor_agent.py | `_safe_execute` 捕获工具执行异常返回结构化 JSON 错误，避免单工具异常导致整个 gather 崩溃 |
| LLM 流式超时保护 | llm.py | `_stream_with_timeout`：首 chunk 120s / 后续 60s 超时保护，5 个流式方法全接入；超时降级到下一个模型而非静默挂起 |
| 调试无工具重定向 | data_processor_agent.py + data_inspector_agent.py | 思维模型无工具调用（Processor 任意无工具）/ 推理截断（Inspector 仅 `finish_reason=length`）→ 切快速模型 + `tool_choice=required` 强制工具调用，避免思维模型反复截断浪费 token；Inspector 正常检查完成不受影响 |
| 长度升级死代码清理 | llm.py + data_processor_agent.py + data_inspector_agent.py | `chat_stream_with_tools_and_thinking` 的 `token_chain` 长度升级被新重定向机制替代，移除内层循环 + `clear_thinking` yield + docstring；两个 Agent 的 `_cleared`/`clear_thinking` 处理同步清除（`chat_stream_with_thinking` 非 tools 版的长度升级仍保留，供 endpoints/skill_creator 使用） |
| Inspector 表名模糊匹配 | inspector_tools.py | `_resolve_table_name`：表不存在时按包含关系找最相似表名，修复 Inspector 误用业务名当表名导致 `get_table_data` 失败 |
| handoff 上限联动 | multi_agent.py + operator.py + pipeline.py | `max_handoffs` 与 `debug_max_inspections` 联动（= inspections×2+2），ConvergenceGuard 阈值同步放宽，避免 7 轮检查-修复循环被提前截断；retry round 事件显示真实检查轮次 |
| written_tables 追踪 | skill_runner.py + data_processor_agent.py | `write_table_data` 记录 `_WRITTEN_TABLES`，执行结果返回 `written_tables`；DataProcessor handoff 优先从中取实际写入表名，不依赖 result 类型推断 |
| embedding 按 provider 选 | llm.py | `_eff_embedding_model` + `_PROVIDER_EMBEDDING_MODELS`：按 provider 选 embedding 模型（glm→embedding-3 / qwen→text-embedding-v3 等），避免用 OpenAI 模型名调智谱等 provider 报错；`init_user_llm_context` 增加 UUID 类型校验 + 空 API key 回退全局 |
