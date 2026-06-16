# DataCrab 技术架构设计文�?
## 1. 系统架构概览

### 1.1 整体架构
采用分层微服务架�?支持本地单机部署和分布式部署两种模式。核心是ChatGPT风格的人机聊天交互界�?用户通过自然语言对话与系统交互处理数据�?
```
┌─────────────────────────────────────────────────────────────�?�?             人机交互界面�?(HMI Interface)                 �?�? ┌─────────────────────────────────────────────────────�?  �?�? �?  ChatGPT风格对话界面                               �?  �?�? �?  - 简洁的聊天消息�?                               �?  �?�? �?  - 自然语言对话输入                                �?  �?�? �?  - 智能意图识别和建�?                             �?  �?�? �?  - 对话历史管理                                    �?  �?�? �?  - 多会话切�?                                     �?  �?�? �?  - 流式响应展示                                    �?  �?�? �?  - 代码块高亮和复制                                �?  �?�? �?  - Markdown渲染                                    �?  �?�? └─────────────────────────────────────────────────────�?  �?└─────────────────────────────────────────────────────────────�?                              �?WebSocket/HTTP
┌─────────────────────────────────────────────────────────────�?�?                     前端应用�?(Frontend)                      �?�?             Vue 3 + Element Plus + TypeScript               �?└─────────────────────────────────────────────────────────────�?                              �?HTTPS
┌─────────────────────────────────────────────────────────────�?�?                     API网关�?(Gateway)                      �?�?         认证鉴权 | 限流熔断 | 路由转发 | 日志审计              �?└─────────────────────────────────────────────────────────────�?                              �?┌─────────────────────────────────────────────────────────────�?�?                     业务服务�?(Services)                    �?├──────────────┬──────────────┬──────────────┬────────────────�?�?NL处理服务   �?代码生成服务  �?执行服务      �?数据源服�?     �?�?NL Service   �?CodeGen      �?Executor      �?DataSource     �?├──────────────┼──────────────┼──────────────┼────────────────�?�?技能管理服�? �?调度服务      �?权限服务      �?元数据服�?     �?�?Skill Manager�?Scheduler     �?Auth          �?Metadata       �?└──────────────┴──────────────┴──────────────┴────────────────�?                              �?┌─────────────────────────────────────────────────────────────�?�?                     核心引擎�?(Engine)                      �?├──────────────┬──────────────┬──────────────┬────────────────�?�?NL理解引擎    �?代码生成引擎  �?执行引擎      �?调度引擎        �?�?NL Engine    �?Code Engine   �?Exec Engine   �?Sched Engine   �?└──────────────┴──────────────┴──────────────┴────────────────�?                              �?┌─────────────────────────────────────────────────────────────�?�?                     数据存储�?(Storage)                     �?├──────────────┬──────────────┬──────────────┬────────────────�?�?PostgreSQL   �?Redis        �?MinIO        �?Elasticsearch  �?�?业务数据      �?缓存/队列     �?文件存储      �?日志/检�?      �?└──────────────┴──────────────┴──────────────┴────────────────�?```

### 1.2 技术栈选型

#### 人机交互界面技术栈
- **框架**: Vue 3 + Composition API
- **UI组件**: Element Plus
- **状态管�?*: Pinia
- **路由**: Vue Router 4
- **HTTP客户�?*: Axios
- **WebSocket**: 原生WebSocket + Socket.io
- **Markdown渲染**: markdown-it + highlight.js
- **代码高亮**: highlight.js + Prism.js
- **实时通信**: WebSocket + EventSource (流式响应)
- **数据可视�?*: ECharts + D3.js
- **代码编辑**: Monaco Editor (代码块编�?
- **动画效果**: animate.css (消息动画)

#### 后端技术栈
- **语言**: Python 3.9+
- **Web框架**: FastAPI
- **ORM**: SQLAlchemy 2.0
- **任务队列**: Celery + Redis
- **异步支持**: asyncio + uvicorn
- **大模型集�?*: LangChain / LlamaIndex
- **代码生成**: AST + Jinja2

#### 数据存储
- **关系数据�?*: PostgreSQL 14+ (主数据库)
- **缓存**: Redis 7+ (缓存、会话、消息队�?
- **对象存储**: MinIO (文件、代码包)
- **搜索引擎**: Elasticsearch 8+ (日志、全文检�?

#### 基础设施
- **容器�?*: Docker + Docker Compose
- **反向代理**: Nginx
- **监控**: Prometheus + Grafana
- **日志**: ELK Stack

## 2. 核心模块设计

### 2.1 人机交互界面模块

#### 2.1.1 界面架构设计
```
┌─────────────────────────────────────────────────────────────�?�?             ChatGPT风格对话界面 (Chat Interface)            �?├─────────────────────────────────────────────────────────────�?�? ┌─────────────────────────────────────────────────────�?  �?�? �?  主界面布局 (简洁单页面)                           �?  �?�? �?  - 左侧边栏 (会话历史列表、新建会话、设�?         �?  �?�? �?  - 中间聊天区域 (消息流、输入框)                   �?  �?�? �?  - 顶部工具�?(模型选择、清空会话、导�?           �?  �?�? └─────────────────────────────────────────────────────�?  �?�? ┌─────────────────────────────────────────────────────�?  �?�? �?  聊天消息�?                                       �?  �?�? �?  - 用户消息 (右侧显示)                             �?  �?�? �?  - AI助手消息 (左侧显示，支持Markdown)             �?  �?�? �?  - 代码�?(语法高亮、复制按钮、执行按�?           �?  �?�? �?  - 数据表格 (可排序、筛选、导�?                   �?  �?�? �?  - 图表可视�?(ECharts交互图表)                    �?  �?�? �?  - 流式响应 (打字机效�?                           �?  �?�? └─────────────────────────────────────────────────────�?  �?�? ┌─────────────────────────────────────────────────────�?  �?�? �?  输入区域                                          �?  �?�? �?  - 多行文本输入�?(支持Shift+Enter换行)            �?  �?�? �?  - 发送按�?(Enter发�?                            �?  �?�? �?  - 停止生成按钮 (流式响应中断)                     �?  �?�? �?  - 附件上传 (支持文件、数据源)                     �?  �?�? └─────────────────────────────────────────────────────�?  �?�? ┌─────────────────────────────────────────────────────�?  �?�? �?  会话管理                                          �?  �?�? �?  - 会话列表 (按时间分组：今天、昨天、更�?         �?  �?�? �?  - 会话搜索和筛�?                                 �?  �?�? �?  - 会话重命名和删除                                �?  �?�? �?  - 会话导出和分�?                                 �?  �?�? └─────────────────────────────────────────────────────�?  �?└─────────────────────────────────────────────────────────────�?```

#### 2.1.2 ChatGPT风格对话界面设计

界面设计原则�?*简洁、以自然语言交互为核�?*�?
##### 核心交互流程
```
用户输入自然语言 ─────────────────────────────────────────>

系统处理�?1. 意图识别（数据处理、创建算子、创建Pipeline、查询数据）
2. 自动匹配技�?算子
3. 生成执行代码
4. 流式响应返回结果

AI回复�?- 文本解释
- 可执行代码块（一键执行）
- 数据表格（可导出�?- 图表可视�?
用户确认/调整 ─────────────────────────────────────────────>
```

##### 主要交互场景

**场景1：数据处�?*
```
用户：帮我分析销售数据，统计每个地区的总销售额

AI：我理解您需要按地区统计销售额，正在处�?..

    [执行代码] df.groupby('region')['sales'].sum()

    [结果表格]
    region    | sales
    ----------|-------
    北京      | 125000
    上海      | 98000

    [可视化图表] 显示柱状�?..
```

**场景2：创建算�?*
```
用户：创建一个算子，计算移动平均�?
AI：正在为您创建算�?..

    算子名称：moving_average
    参数：column（列名）、window（窗口大小，默认7�?    已生成代码并测试通过，算子已注册�?```

**场景3：创�?Skill Pipeline**
```
用户：帮我创建一个数据分析流程：先清洗数据，再过滤异常值，最后统�?
AI：正在创�?Pipeline...

    Pipeline 名称：data_analysis_flow
    步骤：数据清�?�?异常值过�?�?统计分析

    Pipeline 已创建，可直接运行或保存�?Skill�?```

##### 界面布局（极简�?```
┌─────────────────────────────────────────────────────────────�?�? [新建会话]                                                  �?├─────────────────────────────────────────────────────────────�?�? 会话列表                                                    �?�? �?今天                                                     �?�? �?�?销售数据分�?                                          �?�? �?�?创建算子会话                                           �?├─────────────────────────────────────────────────────────────�?�?                                                            �?�? [消息流]                                                    �?�?                                                            �?�? 用户：帮我分析销售数�?..                                   �?�?                                                            �?�? AI：正在处�?..                                             �?�?     [代码块] [复制] [执行]                                  �?�?     [结果表格] [导出]                                       �?�?     [图表]                                                  �?�?                                                            �?├─────────────────────────────────────────────────────────────�?�? [输入框] 输入消息...                        [发送]          �?└─────────────────────────────────────────────────────────────�?```

##### 输入区域功能
- 多行文本输入（Shift+Enter换行�?- 支持附件上传（数据文件）
- 快捷命令：`/create-operator`、`/create-pipeline`、`/run`

##### 消息展示功能
- Markdown渲染
- 代码块语法高�?+ 一键复�?执行
- 数据表格预览 + 导出
- 图表可视�?- 流式响应（打字机效果�?
#### 2.1.3 Notebook数据分析环境设计

Notebook 界面为用户提供代码编辑和执行环境，作为对话交互的补充�?
##### 核心功能
- 代码单元格（可单独执行）
- Markdown单元格（文档说明�?- 执行结果展示
- 内核管理（Python/SQL�?- 保存/分享/导出

##### 界面布局
```
┌─────────────────────────────────────────────────────────────�?�? 工具栏：[添加代码] [添加MD] | [运行全部] [重启] [保存] [分享] �?├─────────────────────────────────────────────────────────────�?�?                                                            �?�? ┌─────────────────────────────────────────────────────�?  �?�? �?Cell 1: 代码单元�?                                  �?  �?�? �?import pandas as pd                                  �?  �?�? �?df = pd.read_csv('data.csv')                        �?  �?�? �?[运行]                                               �?  �?�? ├─────────────────────────────────────────────────────�?  �?�? �?输出:                                                �?  �?�? �?DataFrame loaded, shape: (1000, 5)                  �?  �?�? └─────────────────────────────────────────────────────�?  �?�?                                                            �?�? ┌─────────────────────────────────────────────────────�?  �?�? �?Cell 2: Markdown单元�?                              �?  �?�? �?## 数据分析                                          �?  �?�? �?对销售数据进行统计分�?                              �?  �?�? └─────────────────────────────────────────────────────�?  �?�?                                                            �?└─────────────────────────────────────────────────────────────�?```

#### 2.1.4 数据探索面板设计

数据探索面板提供数据源连接、表结构查看、数据预览等功能。

##### 核心功能
- 数据源连接管理
- 表结构查看（字段、类型、描述）
- 数据预览（采样数据展示）
- 元数据搜索

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

### 2.2 数据源管理模�?
#### 2.2.1 架构设计
```
┌─────────────────────────────────────────�?�?        DataSource Manager              �?├─────────────────────────────────────────�?�? ┌─────────────────────────────────�?  �?�? �?  Connection Pool Manager       �?  �?�? �?  - 连接池管�?                  �?  �?�? �?  - 连接健康检�?                �?  �?�? �?  - 连接复用                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Connector Registry            �?  �?�? �?  - 内置连接器注�?              �?  �?�? �?  - 自定义连接器注册             �?  �?�? �?  - 连接器生命周期管�?          �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Metadata Extractor            �?  �?�? �?  - 技术元数据提取               �?  �?�? �?  - 样本数据采集                 �?  �?�? �?  - 数据质量分析                 �?  �?�? └─────────────────────────────────�?  �?└─────────────────────────────────────────�?```

#### 2.2.2 连接器插件机�?```python
# 基础连接器接�?class BaseConnector(ABC):
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
        """获取数据源结�?""
        pass
    
    @abstractmethod
    async def execute_query(self, query: str) -> DataFrame:
        """执行查询"""
        pass
    
    @abstractmethod
    async def close(self):
        """关闭连接"""
        pass

# 内置连接�?- DatabaseConnector (MySQL, PostgreSQL, Oracle, SQL Server)
- FileConnector (CSV, Excel, JSON, Parquet)
- APIConnector (REST API, GraphQL)
- BigDataConnector (Hive, Spark, Kafka)
- CloudConnector (S3, OSS, Azure Blob)
```

#### 2.2.3 数据源配置模�?```python
class DataSource(Base):
    __tablename__ = "data_sources"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)  # mysql, postgres, api, file
    connection_config = Column(JSON, nullable=False)  # 加密存储
    metadata = Column(JSON)  # 技术元数据
    business_metadata = Column(JSON)  # 业务元数�?    security_level = Column(String(20))  # 安全等级
    created_by = Column(UUID, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
```

### 2.3 自然语言处理模块

#### 2.3.1 NL处理流程
```
用户输入(自然语言)
    �?意图识别(Intent Recognition)
    �?实体提取(Entity Extraction)
    �?技能匹�?Skill Matching)
    �?代码生成(Code Generation)
    �?参数推理(Parameter Inference)
    �?执行计划(Execution Plan)
```

#### 2.3.2 大模型集成架�?```python
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

#### 2.3.3 Skills技能库
```python
class SkillLibrary:
    """技能库 - 核心组件"""
    
    def __init__(self, embedding_service):
        self.skills = {}  # 技能注册表
        self.embeddings = {}  # 技能向量索�?        self.embedding_service = embedding_service
    
    async def register_skill(self, skill: Skill):
        """注册技�?""
        # 生成技能描述向�?        embedding = await self.embedding_service.embed(
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
        """搜索相似技�?""
        # 生成查询向量
        query_embedding = await self.embedding_service.embed(query)
        
        # 向量相似度搜�?        similarities = self.cosine_similarity(query_embedding, self.embeddings)
        
        # 过滤和排�?        filtered_skills = self.filter_skills(similarities, filters)
        
        return filtered_skills[:top_k]
    
    async def get_skill(self, skill_id: str) -> Skill:
        """获取技�?""
        return self.skills.get(skill_id)
    
    async def get_skill_executor(self, skill_id: str):
        """获取技能执行器"""
        skill = await self.get_skill(skill_id)
        return skill.get_executor()
```

#### 2.3.4 技能定义模�?```python
class Skill(Base):
    __tablename__ = "skills"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200))
    description = Column(Text, nullable=False)
    
    # 技能类�?    skill_type = Column(String(50))  # operator, function, workflow
    
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
    
    # 使用示例(用于向量�?
    usage_examples = Column(JSON)
    """
    [
        "选择用户表中的姓名和年龄�?,
        "从订单数据中提取订单号和金额",
        "筛选出销售数据中的商品名称和销�?
    ]
    """
    
    # 技能标�?用于分类和搜�?
    tags = Column(JSON)
    """
    ["数据选择", "列操�?, "基础算子"]
    """
    
    # 技能分�?    category = Column(String(50))
    """
    transform, aggregate, filter, join, analyze
    """
    
    # 元数�?    version = Column(String(20), default="1.0.0")
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
        """获取Python函数执行�?""
        module = importlib.import_module(config["module"])
        return getattr(module, config["function"])
    
    def _get_lambda_executor(self, config):
        """获取Lambda执行�?""
        return eval(config["code"])
```

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
选择已有算子 → 输入修改指令 → LLM 基于原脚本修改 → 覆盖更新 → 自动跳转调试页面

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
点击调试按钮 → 右侧抽屉打开 → 左侧显示可编辑的 Python 脚本 → 右侧显示调试面板 → 填写入参/可选参数 → 点击执行 → 展示 stdout/返回结果/错误信息

**API 端点**: `POST /operators/debug`
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
def _build_operator_namespace(datasource_id=None):
    def query_table_data_sync(datasource_id, table_name, limit=1000, **kwargs):
        # 在独立线程中执行异步数据库查询，避免事件循环冲突
        data = _run_async_in_thread(
            agent_service.query_table(datasource_id, table_name, limit)
        )
        return pd.DataFrame(data["rows"], columns=data["columns"])
    
    def get_datasource_id_by_name(name):
        result = _run_async_in_thread(
            db.execute(select(DataSource).where(DataSource.name == name))
        )
        return str(result.id)
    
    return {
        "pd": pd,
        "query_table_data": query_table_data_sync,
        "get_table_schema": get_table_schema_sync,
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
| POST | /api/v1/skills/generate | AI 生成完整 Skill 包 |
| POST | /api/v1/skills/{id}/clone | 克隆技能 |
| POST | /api/v1/skills/search | 搜索技能 |

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
- generate_skill(): 根据自然语言描述生成完整 Skill 包
- Skill Creator 系统提示词包含：
  - SKILL.md 编写规范
  - 脚本编写规范（pandas 处理、类型注解、边界处理）
  - 内置工具函数说明
  - 数据源参考信息
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

##### skill_executor.py - 技能执行器
- ExecutionContext: 执行上下文（会话ID、用户ID、变量、DataFrame）
- SkillExecutor: 支持多种执行器类型：
  - python_function: 动态加载 Python 模块函数
  - lambda: 安全执行 lambda 表达式
  - operator_reference: 引用已注册的算子
  - skill_composition: 组合多个技能形成 Pipeline

#### 2.5.6 前端界面

SkillView.vue 提供完整的技能管理界面：
- 技能卡片网格布局（支持分类筛选和文本搜索）
- 上传 Skill 包对话框（.zip 拖拽上传，自动解析 SKILL.md）
- AI 生成技能对话框（输入自然语言描述，AI 自动生成完整 Skill 包）
- 技能详情抽屉（三个 Tab 页）：
  - SKILL.md Tab：编辑和预览 SKILL.md 内容
  - 脚本列表 Tab：查看/编辑/执行脚本
  - 属性 Tab：查看技能元数据
- 技能执行对话框（选择数据源、输入表名、配置 JSON 参数，显示执行结果）
- 技能下载（导出为 .zip）和删除功能

#### 2.5.7 技能执行流程

```
客户端请求 POST /api/v1/skills/{id}/run
  → skill_runner.run_skill_script()
  → 构建 SKILL_RUNNER_TEMPLATE（注入数据、参数、工具函数）
  → subprocess.run() 在独立 Python 进程中执行
  → 解析 stdout 中的 __RESULT__ 标记获取返回值
  → 返回 SkillRunResponse { success, result, stdout, execution_time_ms }
```

#### 2.5.8 内置技能列表

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

### 2.6 智能代码生成模块

#### 2.5.1 模块架构
```
┌─────────────────────────────────────────�?�?     Intelligent Code Generator         �?├─────────────────────────────────────────�?�? ┌─────────────────────────────────�?  �?�? �?  NL Code Parser                �?  �?�? �?  - 自然语言解析                 �?  �?�? �?  - 意图识别                     �?  �?�? �?  - 实体提取                     �?  �?�? �?  - 代码结构生成                 �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Skill Composition Engine      �?  �?�? �?  - 技能匹�?                    �?  �?�? �?  - 技能组�?                    �?  �?�? �?  - 参数推理                     �?  �?�? �?  - 代码优化                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────��   �?�? �?  Code Validator                �?  �?�? �?  - 代码验证                     �?  �?�? �?  - 语法检�?                    �?  �?�? �?  - 参数校验                     �?  �?�? �?  - 可执行性分�?                �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Code Executor                 �?  �?�? �?  - 动态算子加�?                �?  �?�? �?  - 代码执行                     �?  �?�? �?  - 结果收集                     �?  �?�? �?  - 错误处理                     �?  �?�? └─────────────────────────────────�?  �?└─────────────────────────────────────────�?```

#### 2.5.2 自然语言代码生成
```python
class NLCodeGenerator:
    """自然语言代码生成�?""
    
    def __init__(self, llm_manager, skill_library):
        self.llm_manager = llm_manager
        self.skill_library = skill_library
    
    async def generate_from_nl(
        self,
        nl_description: str,
        context: dict
    ) -> GeneratedCode:
        """
        从自然语言描述生成数据处理流程
        
        Args:
            nl_description: 自然语言描述
            context: 上下文信�?数据源、历史等)
            
        Returns:
            生成的流程对�?        """
        
        # 1. 解析自然语言描述
        parsed = await self.parse_nl_description(nl_description)
        
        # 2. 识别数据处理意图
        intent = await self.recognize_intent(parsed, context)
        
        # 3. 匹配相关技�?        skills = await self.match_skills(intent)
        
        # 4. 组合技能形成流�?        code = await self.compose_skills(skills, intent)
        
        # 5. 推理和填充参�?        await self.infer_parameters(code, context)
        
        # 6. 验证流程
        validation = await self.validate_code(code)
        
        return GeneratedCode(
            description=nl_description,
            intent=intent,
            skills=skills,
            code=code,
            validation=validation
        )
    
    async def parse_nl_description(
        self,
        text: str
    ) -> NLParseResult:
        """解析自然语言描述"""
        
        prompt = f"""
        解析以下数据处理需�?提取关键信息:
        
        需求描�? {text}
        
        请提�?
        1. 数据源信�?        2. 数据处理步骤
        3. 预期输出
        4. 特殊要求
        
        以JSON格式返回结果�?        """
        
        response = await self.llm_manager.chat(prompt)
        return NLParseResult.parse(response)
    
    async def recognize_intent(
        self,
        parsed: NLParseResult,
        context: dict
    ) -> ProcessingIntent:
        """识别处理意图"""
        # 使用大模型识别用户意�?        prompt = f"""
        基于以下解析结果,识别数据处理意图:
        
        解析结果: {parsed.json()}
        上下�? {context}
        
        意图类型:
        - 数据清洗
        - 数据转换
        - 数据聚合
        - 数据分析
        - 数据融合
        - 数据导出
        """
        
        response = await self.llm_manager.chat(prompt)
        return ProcessingIntent.parse(response)
    
    async def match_skills(
        self,
        intent: ProcessingIntent
    ) -> List[Skill]:
        """匹配相关技�?""
        
        # 1. 从技能库中查找相似技�?        similar_skills = await self.skill_library.search_similar(
            query=intent.description,
            top_k=10
        )
        
        # 2. 使用大模型选择最合适的技�?        selected_skills = await self.select_skills(
            intent=intent,
            candidates=similar_skills
        )
        
        return selected_skills
    
    async def compose_skills(
        self,
        skills: List[Skill],
        intent: ProcessingIntent
    ) -> ComposedCode:
        """组合技能形成流�?""
        
        prompt = f"""
        将以下技能组合成完整的数据处理流�?
        
        可用技�?
        {self.format_skills(skills)}
        
        处理意图: {intent.description}
        
        �?
        1. 确定技能的执行顺序
        2. 定义技能之间的数据流转
        3. 生成流程的DAG结构
        
        返回JSON格式的流程定义�?        """
        
        response = await self.llm_manager.chat(prompt)
        return ComposedCode.parse(response)
    
    async def infer_parameters(
        self,
        code: ComposedCode,
        context: dict
    ):
        """推理和填充参�?""
        
        for step in code.steps:
            skill = step.skill
            
            # 如果参数未指�?尝试从上下文推理
            if not step.parameters:
                inferred = await self.infer_step_parameters(
                    skill=skill,
                    context=context,
                    previous_steps=code.steps[:code.steps.index(step)]
                )
                step.parameters = inferred
    
    async def validate_code(
        self,
        code: ComposedCode
    ) -> ValidationResult:
        """验证流程"""
        
        # 1. 验证技能依�?        dependency_validation = await self.validate_dependencies(code)
        
        # 2. 验证参数完整�?        parameter_validation = await self.validate_parameters(code)
        
        # 3. 验证数据流转
        data_flow_validation = await self.validate_data_flow(code)
        
        return ValidationResult(
            dependencies=dependency_validation,
            parameters=parameter_validation,
            data_flow=data_flow_validation,
            is_valid=all([
                dependency_validation.valid,
                parameter_validation.valid,
                data_flow_validation.valid
            ])
        )
```

#### 2.5.3 Skills技能组�?```python
class SkillCompositionEngine:
    """技能组合引�?""
    
    def __init__(self, skill_library, llm_manager):
        self.skill_library = skill_library
        self.llm_manager = llm_manager
    
    async def compose(
        self,
        requirements: dict,
        available_skills: List[Skill]
    ) -> ComposedCode:
        """
        组合技能形成处理流�?        
        Args:
            requirements: 处理需�?            available_skills: 可用技能列�?            
        Returns:
            组合后的流程
        """
        
        # 1. 分析需�?        analysis = await self.analyze_requirements(requirements)
        
        # 2. 技能选择
        selected_skills = await self.select_skills(
            analysis=analysis,
            available=available_skills
        )
        
        # 3. 技能排�?        ordered_skills = await self.order_skills(
            skills=selected_skills,
            analysis=analysis
        )
        
        # 4. 参数映射
        parameter_mapping = await self.map_parameters(
            skills=ordered_skills,
            requirements=requirements
        )
        
        # 5. 生成流程
        code = self.build_code(
            skills=ordered_skills,
            parameters=parameter_mapping
        )
        
        return code
    
    async def select_skills(
        self,
        analysis: dict,
        available: List[Skill]
    ) -> List[Skill]:
        """选择合适的技�?""
        
        # 使用大模型进行技能选择
        prompt = f"""
        根据以下需�?从可用技能中选择最合适的技�?
        
        需求分�? {analysis}
        
        可用技�?
        {self.format_skills(available)}
        
        请选择能够完成需求的技能组�?并说明选择理由�?        """
        
        response = await self.llm_manager.chat(prompt)
        return self.parse_skill_selection(response, available)
    
    async def order_skills(
        self,
        skills: List[Skill],
        analysis: dict
    ) -> List[Skill]:
        """确定技能执行顺�?""
        
        # 构建技能依赖图
        dependency_graph = self.build_dependency_graph(skills)
        
        # 使用拓扑排序确定执行顺序
        ordered = self.topological_sort(dependency_graph)
        
        # 使用大模型验证和优化顺序
        optimized = await self.optimize_order(ordered, analysis)
        
        return optimized
```

#### 2.5.4 动态代码执�?```python
class DynamicCodeExecutor:
    """动态流程执行器"""
    
    async def execute(
        self,
        code: ComposedCode,
        context: ExecutionContext
    ) -> ExecutionResult:
        """
        执行组合流程
        
        Args:
            code: 组合代码
            context: 执行上下�?            
        Returns:
            执行结果
        """
        
        # 1. 初始化执行环�?        env = await self.init_environment(context)
        
        # 2. 按顺序执行技�?        results = {}
        for step in code.steps:
            # 动态加载技�?            skill = await self.load_skill(step.skill_id)
            
            # 准备输入数据
            inputs = await self.prepare_inputs(step, results, env)
            
            # 执行技�?            result = await self.execute_skill(
                skill=skill,
                inputs=inputs,
                parameters=step.parameters
            )
            
            # 保存结果
            results[step.id] = result
            
            # 记录执行日志
            await self.log_execution(step, result)
        
        # 3. 返回最终结�?        final_result = await self.collect_results(results, code)
        
        return ExecutionResult(
            code_id=code.id,
            status="success",
            results=final_result,
            execution_time=...
        )
    
    async def load_skill(self, skill_id: str) -> Skill:
        """动态加载技�?""
        # 从技能库加载技�?        return await self.skill_library.get_skill(skill_id)
    
    async def execute_skill(
        self,
        skill: Skill,
        inputs: dict,
        parameters: dict
    ) -> Any:
        """执行单个技�?""
        
        # 每个技能都是一个可执行的函�?        skill_function = skill.get_executor()
        
        # 执行技�?        result = await skill_function(
            inputs=inputs,
            parameters=parameters
        )
        
        return result
```

#### 2.5.5 代码定义模型
```python
class ComposedCode(Base):
    __tablename__ = "composed_codes"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), nullable=False)
    
    # 自然语言描述
    nl_description = Column(Text, nullable=False)
    
    # 意图识别结果
    intent = Column(JSON)
    
    # 流程定义(基于Skills)
    steps = Column(JSON)
    """
    [
        {
            "id": "step_1",
            "skill_id": "uuid",
            "skill_name": "FilterOperator",
            "parameters": {...},
            "dependencies": [],
            "description": "过滤数据"
        },
        {
            "id": "step_2",
            "skill_id": "uuid",
            "skill_name": "GroupByOperator",
            "parameters": {...},
            "dependencies": ["step_1"],
            "description": "分组聚合"
        }
    ]
    """
    
    # 流程元数�?    input_schema = Column(JSON)  # 输入数据结构
    output_schema = Column(JSON)  # 输出数据结构
    
    # 验证结果
    validation_result = Column(JSON)
    
    # 版本管理
    version = Column(Integer, default=1)
    
    # 执行统计
    execution_count = Column(Integer, default=0)
    last_executed_at = Column(DateTime)
    
    # 权限
    created_by = Column(UUID, ForeignKey("users.id"))
    visibility = Column(String(20))  # private, public, shared
    
    # 元数�?    tags = Column(JSON)
    category = Column(String(50))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

### 2.6 调度系统模块

#### 2.6.1 调度架构
```
┌─────────────────────────────────────────�?�?        Scheduler Service               �?├─────────────────────────────────────────�?�? ┌─────────────────────────────────�?  �?�? �?  Schedule Manager              �?  �?�? �?  - 调度配置管理                 �?  �?�? �?  - 调度策略配置                 �?  �?�? �?  - 调度历史记录                 �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Cron Scheduler                �?  �?�? �?  - Cron表达式解�?              �?  �?�? �?  - 定时任务触发                 �?  �?�? �?  - 任务队列管理                 �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Event Scheduler               �?  �?�? �?  - 事件监听                     �?  �?�? �?  - 事件触发                     �?  �?�? �?  - 实时调度                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Task Executor                 �?  �?�? �?  - 任务执行                     �?  �?�? �?  - 状态监�?                    �?  �?�? �?  - 失败重试                     �?  �?�? └─────────────────────────────────�?  �?└─────────────────────────────────────────�?```

#### 2.6.2 调度配置模型
```python
class Schedule(Base):
    __tablename__ = "schedules"
    
    id = Column(UUID, primary_key=True)
    code_id = Column(UUID, ForeignKey("composed_codes.id"))
    
    # 调度类型
    schedule_type = Column(String(20))  # cron, event, manual
    
    # Cron配置
    cron_expression = Column(String(100))  # "0 0 * * *"
    timezone = Column(String(50), default="Asia/Shanghai")
    
    # 事件配置
    event_config = Column(JSON)  # 事件触发配置
    
    # 执行配置
    max_retries = Column(Integer, default=3)
    retry_interval = Column(Integer, default=60)  # �?    timeout = Column(Integer, default=3600)  # �?    
    # 状�?    status = Column(String(20))  # active, paused, stopped
    last_run_at = Column(DateTime)
    next_run_at = Column(DateTime)
    
    created_by = Column(UUID, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
```

#### 2.6.3 任务执行模型
```python
class TaskExecution(Base):
    __tablename__ = "task_executions"
    
    id = Column(UUID, primary_key=True)
    schedule_id = Column(UUID, ForeignKey("schedules.id"))
    code_id = Column(UUID, ForeignKey("composed_codes.id"))
    
    # 执行信息
    status = Column(String(20))  # pending, running, success, failed
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration = Column(Integer)  # 毫秒
    
    # 执行结果
    result = Column(JSON)  # 执行结果
    error_message = Column(Text)  # 错误信息
    
    # 重试信息
    retry_count = Column(Integer, default=0)
    
    # 执行日志
    logs = Column(Text)  # 执行日志
    
    # 血缘关�?    input_data = Column(JSON)  # 输入数据�?    output_data = Column(JSON)  # 输出数据�?    
    created_at = Column(DateTime, default=datetime.utcnow)
```

### 2.7 元数据管理模�?
#### 2.7.1 元数据架�?```
┌─────────────────────────────────────────�?�?        Metadata Manager                �?├─────────────────────────────────────────�?�? ┌─────────────────────────────────�?  �?�? �?  Technical Metadata            �?  �?�? �?  - 表结构信�?                  �?  �?�? �?  - 字段类型                     �?  �?�? �?  - 索引信息                     �?  �?�? �?  - 数据统计                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Business Metadata             �?  �?�? �?  - 业务含义                     �?  �?�? �?  - 数据�?                      �?  �?�? �?  - 数据质量规则                 �?  �?�? �?  - 数据所有�?                  �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Operational Metadata          �?  �?�? �?  - 执行统计                     �?  �?�? �?  - 访问记录                     �?  �?�? �?  - 数据血�?                    �?  �?�? �?  - 变更历史                     �?  �?�? └─────────────────────────────────�?  �?└─────────────────────────────────────────�?```

#### 2.7.2 元数据模�?```python
class TableMetadata(Base):
    __tablename__ = "table_metadata"
    
    id = Column(UUID, primary_key=True)
    data_source_id = Column(UUID, ForeignKey("data_sources.id"))
    
    # 表信�?    table_name = Column(String(200), nullable=False)
    table_type = Column(String(50))  # table, view, stream
    
    # 技术元数据
    schema = Column(JSON)  # 表结�?    row_count = Column(BigInteger)  # 行数
    size_bytes = Column(BigInteger)  # 大小
    
    # 业务元数�?    business_name = Column(String(200))  # 业务名称
    business_description = Column(Text)  # 业务描述
    data_domain = Column(String(100))  # 数据�?    data_owner = Column(String(100))  # 数据所有�?    
    # 数据质量
    quality_rules = Column(JSON)  # 质量规则
    quality_score = Column(Float)  # 质量评分
    
    # 安全等级
    security_level = Column(String(20))  # public, internal, confidential, secret
    
    # 血缘关�?    lineage = Column(JSON)  # 数据血�?    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

### 2.8 权限管理模块

#### 2.8.1 RBAC权限模型
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
    
    # 状�?    is_active = Column(Boolean, default=True)
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

#### 2.8.2 权限检查逻辑
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
        """检查权�?""
        
        # 超级用户拥有所有权�?        if user.is_superuser:
            return True
        
        # 查询用户权限
        permissions = await self.get_user_permissions(
            user.id, 
            resource_type, 
            resource_id
        )
        
        # 权限级别映射
        level_map = {"view": 1, "use": 2, "manage": 3}
        
        # 检查权�?        for perm in permissions:
            if level_map[perm.permission_level] >= level_map[required_level]:
                return True
        
        return False
```

### 2.9 代码生成模块

#### 2.9.1 代码生成流程
```
Code Definition (JSON)
    �?AST解析与转�?    �?代码模板渲染
    �?Python代码生成
    �?代码优化与格式化
    �?可执行Python脚本
```

#### 2.9.2 代码生成�?```python
class CodeGenerator:
    """代码生成�?""
    
    def generate_python_code(
        self, 
        code: Code
    ) -> str:
        """生成Python代码"""
        
        # 1. 解析流程定义
        dag = self.parse_dag(code.definition)
        
        # 2. 生成导入语句
        imports = self.generate_imports(dag)
        
        # 3. 生成数据源连接代�?        connections = self.generate_connections(dag)
        
        # 4. 生成算子执行代码
        operations = self.generate_operations(dag)
        
        # 5. 生成主函�?        main_function = self.generate_main_function(dag)
        
        # 6. 组装完整代码
        code = f"""
{imports}

{connections}

{operations}

{main_function}

if __name__ == "__main__":
    main()
"""
        
        # 7. 代码格式�?        formatted_code = self.format_code(code)
        
        return formatted_code
```

#### 2.9.3 代码模板示例
```python
# 数据源连接模�?DATASOURCE_TEMPLATE = """
def connect_{name}():
    \"\"\"连接数据�? {display_name}\"\"\"
    import {driver}
    
    connection = {driver}.connect(
        {connection_params}
    )
    return connection
"""

# 算子执行模板
OPERATOR_TEMPLATE = """
def {operator_name}({inputs}):
    \"\"\"执行算子: {display_name}
    
    参数:
        {params_doc}
    
    返回:
        DataFrame: 处理结果
    \"\"\"
    {operator_logic}
    
    return result
"""
```

### 2.10 环境管理模块

#### 2.10.1 环境隔离架构
```
┌─────────────────────────────────────────�?�?        Environment Manager             �?├─────────────────────────────────────────�?�? ┌─────────────────────────────────�?  �?�? �?  Development Environment       �?  �?�? �?  - 开发测�?                    �?  �?�? �?  - 沙箱数据                     �?  �?�? �?  - 调试模式                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Testing Environment           �?  �?�? �?  - 集成测试                     �?  �?�? �?  - 测试数据                     �?  �?�? �?  - 性能测试                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Production Environment        �?  �?�? �?  - 生产运行                     �?  �?�? �?  - 真实数据                     �?  �?�? �?  - 高可用部�?                  �?  �?�? └─────────────────────────────────�?  �?└─────────────────────────────────────────�?```

#### 2.10.2 环境迁移机制
```python
class EnvironmentMigrator:
    """环境迁移�?""
    
    async def migrate_code(
        self,
        code_id: UUID,
        source_env: str,
        target_env: str
    ) -> MigrationResult:
        """迁移流程"""
        
        # 1. 验证源环境流�?        code = await self.validate_code(code_id, source_env)
        
        # 2. 检查依�?        dependencies = await self.check_dependencies(code)
        
        # 3. 迁移数据源配�?        await self.migrate_datasources(dependencies.datasources, target_env)
        
        # 4. 迁移算子
        await self.migrate_operators(dependencies.operators, target_env)
        
        # 5. 创建目标环境流程
        new_code = await self.create_code(code, target_env)
        
        # 6. 验证迁移结果
        await self.validate_migration(new_code, target_env)
        
        return MigrationResult(
            success=True,
            new_code_id=new_code.id
        )
```

## 3. 数据库设�?
### 3.1 核心表结�?
#### 用户与权限表
```sql
-- 用户�?CREATE TABLE users (
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

-- 角色�?CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    permissions JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户角色关联�?CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- 权限�?CREATE TABLE permissions (
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

-- 表元数据�?CREATE TABLE table_metadata (
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
-- 算子�?CREATE TABLE operators (
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

-- 流程�?CREATE TABLE composed_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    definition JSONB NOT NULL,
    version INTEGER DEFAULT 1,
    parent_id UUID REFERENCES composed_codes(id),
    environment VARCHAR(20),
    created_by UUID REFERENCES users(id),
    visibility VARCHAR(20),
    permissions JSONB,
    tags JSONB,
    category VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
```

#### 技能表（Skills�?```sql
-- 技能表
CREATE TABLE skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200),
    description TEXT NOT NULL,
    skill_type VARCHAR(50), -- operator, function, workflow, pipeline
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
        "选择用户表中的姓名和年龄�?,
        "从订单数据中提取订单号和金额"
    ]
    """
    tags JSONB,
    """
    ["数据选择", "列操�?, "基础技�?]
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

-- Skill Pipeline 表（技能组合流水线�?CREATE TABLE skill_pipelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200),
    description TEXT,
    skill_steps JSONB NOT NULL,
    """
    [
        {
            "step_id": "step_1",
            "skill_id": "uuid",
            "skill_name": "FilterOperator",
            "order": 1,
            "input_mapping": {"data": "$input.raw_data"},
            "output_mapping": {"result": "$context.filtered_data"},
            "parameters": {"condition": "age > 18"}
        },
        {
            "step_id": "step_2",
            "skill_id": "uuid",
            "skill_name": "GroupByOperator",
            "order": 2,
            "input_mapping": {"data": "$context.filtered_data"},
            "output_mapping": {"result": "$output.final_result"},
            "parameters": {"group_by": "category"}
        }
    ]
    """
    input_schema JSONB,
    """
    {
        "raw_data": {
            "type": "DataFrame",
            "description": "原始输入数据",
            "required": true
        }
    }
    """
    output_schema JSONB,
    """
    {
        "final_result": {
            "type": "DataFrame",
            "description": "最终处理结�?
        }
    }
    """
    version INTEGER DEFAULT 1,
    parent_id UUID REFERENCES skill_pipelines(id),
    created_by UUID REFERENCES users(id),
    visibility VARCHAR(20),
    permissions JSONB,
    tags JSONB,
    category VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Pipeline 执行历史�?CREATE TABLE pipeline_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID REFERENCES skill_pipelines(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL, -- pending, running, completed, failed
    inputs JSONB,
    outputs JSONB,
    step_results JSONB,
    """
    {
        "step_1": {"status": "completed", "output": {...}},
        "step_2": {"status": "completed", "output": {...}}
    }
    """
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration INTEGER,
    error_message TEXT,
    error_step VARCHAR(50),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 调度与执行表
```sql
-- 调度�?CREATE TABLE schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id UUID REFERENCES composed_codes(id) ON DELETE CASCADE,
    schedule_type VARCHAR(20) NOT NULL,
    cron_expression VARCHAR(100),
    timezone VARCHAR(50) DEFAULT 'Asia/Shanghai',
    event_config JSONB,
    max_retries INTEGER DEFAULT 3,
    retry_interval INTEGER DEFAULT 60,
    timeout INTEGER DEFAULT 3600,
    status VARCHAR(20),
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 任务执行�?CREATE TABLE task_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID REFERENCES schedules(id) ON DELETE CASCADE,
    code_id UUID REFERENCES composed_codes(id),
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration INTEGER,
    result JSONB,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    logs TEXT,
    input_data JSONB,
    output_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 4. API接口设计

### 4.1 RESTful API规范

#### 数据源管理API
```
POST   /api/v1/datasources              # 创建数据�?GET    /api/v1/datasources              # 获取数据源列�?GET    /api/v1/datasources/{id}         # 获取数据源详�?PUT    /api/v1/datasources/{id}         # 更新数据�?DELETE /api/v1/datasources/{id}         # 删除数据�?POST   /api/v1/datasources/{id}/test    # 测试连接
GET    /api/v1/datasources/{id}/schema  # 获取数据源结�?```

#### 算子管理API
```
POST   /api/v1/operators                # 创建算子
GET    /api/v1/operators                # 获取算子列表
GET    /api/v1/operators/{id}           # 获取算子详情
PUT    /api/v1/operators/{id}           # 更新算子
DELETE /api/v1/operators/{id}           # 删除算子
GET    /api/v1/operators/categories     # 获取算子分类
```

#### 流程管理API
```
POST   /api/v1/codes                # 创建代码
GET    /api/v1/codes                # 获取代码列表
GET    /api/v1/codes/{id}           # 获取代码详情
PUT    /api/v1/codes/{id}           # 更新代码
DELETE /api/v1/codes/{id}           # 删除代码
POST   /api/v1/codes/{id}/execute   # 执行代码
POST   /api/v1/codes/{id}/generate  # 生成代码
GET    /api/v1/codes/{id}/versions  # 获取版本历史
POST   /api/v1/codes/{id}/rollback  # 回退版本
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
GET    /api/v1/schedules/{id}/executions # 获取执行历史
```

#### 自然语言处理API
```
POST   /api/v1/nl/process               # 处理自然语言
POST   /api/v1/nl/skills/search         # 搜索相似技�?POST   /api/v1/nl/skills/register       # 注册技�?```

#### 技能管理API
```
# 技�?CRUD
POST   /api/v1/skills                    # 创建技�?GET    /api/v1/skills                    # 获取技能列�?GET    /api/v1/skills/{id}               # 获取技能详�?PUT    /api/v1/skills/{id}               # 更新技�?DELETE /api/v1/skills/{id}               # 删除技�?
# 技能操�?POST   /api/v1/skills/{id}/execute       # 执行单个技�?POST   /api/v1/skills/{id}/test          # 测试技能执�?GET    /api/v1/skills/{id}/versions      # 获取技能版本历�?POST   /api/v1/skills/{id}/rollback      # 回退技能版�?POST   /api/v1/skills/{id}/validate      # 验证技能定�?
# 技能发�?GET    /api/v1/skills/categories         # 获取技能分�?GET    /api/v1/skills/search             # 搜索技�?POST   /api/v1/skills/recommend          # 推荐相关技�?
# 技能转�?POST   /api/v1/skills/from-operator      # 从算子创建技�?POST   /api/v1/skills/from-code          # 从代码创建技�?POST   /api/v1/skills/from-nl            # 自然语言创建技�?
# 技能模�?GET    /api/v1/skills/templates          # 获取技能模板列�?POST   /api/v1/skills/templates/{id}/apply # 应用技能模�?```

#### Skill Pipeline API
```
# Pipeline CRUD
POST   /api/v1/skill-pipelines           # 创建 Pipeline
GET    /api/v1/skill-pipelines           # 获取 Pipeline 列表
GET    /api/v1/skill-pipelines/{id}      # 获取 Pipeline 详情
PUT    /api/v1/skill-pipelines/{id}      # 更新 Pipeline
DELETE /api/v1/skill-pipelines/{id}      # 删除 Pipeline

# Pipeline 执行
POST   /api/v1/skill-pipelines/{id}/run  # 执行 Pipeline
GET    /api/v1/skill-pipelines/{id}/run/streaming  # 流式执行 Pipeline (SSE)
POST   /api/v1/skill-pipelines/{id}/test # 测试 Pipeline
POST   /api/v1/skill-pipelines/{id}/validate # 验证 Pipeline 定义

# Pipeline 执行历史
GET    /api/v1/skill-pipelines/{id}/executions      # 获取执行历史
GET    /api/v1/skill-pipelines/executions/{eid}     # 获取执行详情
GET    /api/v1/skill-pipelines/executions/{eid}/logs # 获取执行日志

# Pipeline 版本管理
GET    /api/v1/skill-pipelines/{id}/versions        # 获取版本历史
POST   /api/v1/skill-pipelines/{id}/rollback        # 回退版本
POST   /api/v1/skill-pipelines/{id}/fork            # 复制 Pipeline

# Pipeline 导入导出
GET    /api/v1/skill-pipelines/{id}/export          # 导出 Pipeline 定义
POST   /api/v1/skill-pipelines/import               # 导入 Pipeline
```

#### Skill �?Pipeline API 详细说明

##### 创建技�?```json
POST /api/v1/skills
Request:
{
    "name": "filter_rows",
    "display_name": "数据过滤",
    "description": "根据条件过滤数据�?,
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
            "description": "过滤条件表达�?,
            "required": true
        }
    },
    "executor_config": {
        "type": "python_function",
        "module": "app.skills.operators",
        "function": "filter_operator"
    },
    "usage_examples": [
        "过滤年龄大于18的用�?,
        "筛选销售额超过1000的订�?
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

##### 自然语言创建技�?```json
POST /api/v1/skills/from-nl
Request:
{
    "description": "创建一个技能，用于计算数据的平均值、最大值、最小值和标准�?,
    "user_id": "uuid"
}

Response:
{
    "skill": {
        "id": "uuid",
        "name": "calculate_statistics",
        "display_name": "统计分析",
        "description": "计算数据的统计指�?,
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
    "description": "清洗、过滤、聚合销售数�?,
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
            "description": "原始销售数�?,
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

### 4.2 WebSocket接口

#### 实时执行日志
```
WebSocket: /ws/executions/{execution_id}

消息格式:
{
    "type": "log",
    "timestamp": "2026-03-12T10:30:00Z",
    "level": "info",
    "message": "执行算子: FilterOperator",
    "node_id": "node_1"
}
```

## 5. 部署架构

### 5.1 单机部署架构
```
┌─────────────────────────────────────────�?�?           Docker Compose               �?├─────────────────────────────────────────�?�? ┌─────────────────────────────────�?  �?�? �?  Nginx (Port 80/443)          �?  �?�? �?  - 反向代理                     �?  �?�? �?  - SSL终止                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Frontend Container            �?  �?�? �?  - Vue 3 应用                   �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Backend Container             �?  �?�? �?  - FastAPI 应用                 �?  �?�? �?  - Uvicorn Server               �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Celery Worker Container       �?  �?�? �?  - 任务执行                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  PostgreSQL Container          �?  �?�? �?  - 数据存储                     �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  Redis Container               �?  �?�? �?  - 缓存/队列                    �?  �?�? └─────────────────────────────────�?  �?�? ┌─────────────────────────────────�?  �?�? �?  MinIO Container               �?  �?�? �?  - 文件存储                     �?  �?�? └─────────────────────────────────�?  �?└─────────────────────────────────────────�?```

### 5.2 Docker Compose配置
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
      - ./ssl:/etc/nginx/ssl
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
      - REDIS_URL=redis://redis:6379/0
      - MINIO_URL=http://minio:9000
    depends_on:
      - postgres
      - redis
      - minio

  celery_worker:
    build: ./backend
    command: celery -A app.celery worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/datacrab
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis

  celery_beat:
    build: ./backend
    command: celery -A app.celery beat --loglevel=info
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/datacrab
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:14-alpine
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=datacrab
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      - MINIO_ROOT_USER=admin
      - MINIO_ROOT_PASSWORD=password
    volumes:
      - minio_data:/data

volumes:
  postgres_data:
  redis_data:
  minio_data:
```

## 6. 安全设计

### 6.1 认证与授�?- **JWT认证**: 使用JWT进行用户认证
- **RBAC**: 基于角色的访问控�?- **API密钥**: 支持API密钥认证
- **OAuth2**: 支持第三方登�?
### 6.2 数据安全
- **传输加密**: HTTPS/TLS加密传输
- **存储加密**: 敏感数据加密存储
- **数据脱敏**: 敏感字段脱敏显示
- **安全分级**: 数据安全等级分类

### 6.3 安全防护
- **SQL注入防护**: 参数化查�?- **XSS防护**: 输入输出转义
- **CSRF防护**: CSRF Token验证
- **限流防护**: API访问限流

## 7. 监控与运�?
### 7.1 监控指标
- **系统指标**: CPU、内存、磁盘、网�?- **应用指标**: 请求量、响应时间、错误率
- **业务指标**: 流程执行数、成功率、失败率

### 7.2 日志管理
- **应用日志**: 应用运行日志
- **访问日志**: API访问日志
- **审计日志**: 用户操作审计日志
- **执行日志**: 流程执行日志

### 7.3 告警机制
- **系统告警**: 资源使用率告�?- **应用告警**: 服务异常告警
- **业务告警**: 任务失败告警

## 8. 扩展性设�?
### 8.1 插件机制
- **数据源插�?*: 支持自定义数据源连接�?- **算子插件**: 支持自定义算子开�?- **认证插件**: 支持自定义认证方�?- **存储插件**: 支持自定义存储后�?
### 8.2 水平扩展
- **无状态服�?*: API服务无状态设�?- **负载均衡**: 支持多实例负载均�?- **分布式任�?*: Celery分布式任务执�?- **数据库分�?*: 支持数据库分片扩�?
## 9. 开发规�?
### 9.1 代码规范
- **Python**: PEP 8 + Black格式�?- **TypeScript**: ESLint + Prettier
- **Git提交**: Conventional Commits
- **代码审查**: Pull Request审查机制

### 9.2 测试规范
- **单元测试**: pytest + unittest
- **集成测试**: pytest-asyncio
- **E2E测试**: Playwright
- **覆盖�?*: > 80%

### 9.3 文档规范
- **API文档**: OpenAPI/Swagger
- **代码文档**: Docstring
- **用户文档**: Markdown
- **部署文档**: Docker Compose

## 10. 技术风险与应对

### 10.1 性能风险
- **风险**: 大数据量处理性能问题
- **应对**: 分批处理、流式处理、异步执�?
### 10.2 可靠性风�?- **风险**: 任务执行失败
- **应对**: 重试机制、事务回滚、状态恢�?
### 10.3 安全风险
- **风险**: 数据泄露、恶意攻�?- **应对**: 加密存储、访问控制、安全审�?
### 10.4 扩展性风�?- **风险**: 系统扩展困难
- **应对**: 模块化设计、插件机制、微服务架构
