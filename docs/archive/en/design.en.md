# DataCrab Technical Architecture Design Document

## 0. Core Philosophy

**Process data through conversation, accumulate data-processing Skills, form a data ecosystem, and ultimately achieve a fully closed AI loop for data processing.**

| Stage | Philosophy | Industry Trend |
|------|------|---------|
| Conversation as Processing | Replace coding with natural language; the LLM understands intent, matches Skills, generates code | Conversational Data Processing, Agentic UI |
| Accumulation as Asset | Each processing run accumulates as a reusable Skill, getting smarter with use | Skill-based Agent, Compound AI System |
| Ecosystem as Loop | Accumulated Skills form an ecosystem; tri-agent collaboration loop | Multi-Agent Collaboration |
| Loop-ification | AI understands → executes → inspects → self-repairs, no human intervention | Self-healing Pipeline, Full-loop Automation, Deep Agents |

Loop-ification is the ultimate goal: the AI iterates continuously in an "execute → observe → correct" loop until the task is complete. The multi-agent Handoff mechanism and skill self-evolution capability are concrete practices of this philosophy.

## 1. System Architecture Overview

### 1.1 Overall Architecture
A layered microservice architecture supporting both local single-machine and distributed deployment. At its core is a ChatGPT-style human-machine chat interface where users interact with the system to process data via natural-language conversation.
```
┌───────────────────────────────────────────────────────────────┐
│                 HMI Interface (Human-Machine Interface)        │
├───────────────────────────────────────────────────────────────┤
│ChatGPT-style conversation interface                            │
│- Clean chat message stream                                     │
│- Natural-language conversation input                           │
│- Intelligent intent recognition and suggestions                │
│- Conversation history management                               │
│- Multi-session switching                                       │
│- Streaming response display                                    │
│- Code block highlighting and copy                              │
│- Markdown rendering                                            │
└───────────────────────────────────────────────────────────────┘
                               │                               
                        WebSocket/HTTP                         
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                      Frontend                                  │
├───────────────────────────────────────────────────────────────┤
│               Vue 3 + Element Plus + TypeScript               │
└───────────────────────────────────────────────────────────────┘
                               │                               
                              HTTPS                             
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                       API Gateway                              │
├───────────────────────────────────────────────────────────────┤
│           Auth | Rate-limit/Circuit-break | Routing | Audit   │
└───────────────────────────────────────────────────────────────┘
                               │                               
                                                                
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                      Business Services                         │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ Chat Service │ Skill Mgmt   │ Operator Svc │ DataSource Svc │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ ChatService  │ SkillManager │ OperatorSvc  │ DataSource     │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ Agent Svc    │ Schedule Svc │ Auth Svc     │ Metadata Svc   │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ AgentRuntime │ Scheduler    │ Auth         │ Metadata       │
└──────────────┴──────────────┴──────────────┴────────────────┘
                               │                               
                                                                
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                       Core Engine                              │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ Agent Engine │ Skill Engine │ Pipeline Eng │ Schedule Eng   │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ AgentEngine  │ SkillRunner  │ PipelineExec │ Sched Engine   │
└──────────────┴──────────────┴──────────────┴────────────────┘
                               │                               
                                                                
                               ▼                               
┌───────────────────────────────────────────────────────────────┐
│                      Data Storage                              │
├──────────────┬──────────────┬────────────────────────────────┤
│ SQLite/PG    │ Local FS     │ Skill package directory         │
├──────────────┼──────────────┼────────────────────────────────┤
│ Business data│ Datasrc files│ SKILL.md + scripts/             │
└──────────────┴──────────────┴────────────────────────────────┘
```

### 1.2 Technology Stack

#### HMI Interface Stack
- **Framework**: Vue 3 + Composition API
- **UI components**: Element Plus
- **State management**: Pinia
- **Routing**: Vue Router 4
- **HTTP client**: Axios
- **Real-time communication**: EventSource (SSE streaming)
- **Markdown rendering**: markdown-it + highlight.js
- **Code editing**: Monaco Editor (code block editing)
- **Data visualization**: ECharts

#### Backend Stack
- **Language**: Python 3.11+
- **Web framework**: FastAPI
- **ORM**: SQLAlchemy 2.0
- **Async support**: asyncio + uvicorn
- **LLM integration**: Zhipu GLM (glm-4-flash / glm-4-plus / glm-5.2)

#### Data Storage
- **Relational DB**: SQLite (development) / PostgreSQL 14+ (production)
- **File storage**: local file system

#### Infrastructure
- **Containerization**: Docker + Docker Compose (optional)
- **Reverse proxy**: Nginx (production deployment)

## 2. Core Module Design

### 2.1 Human-Machine Interface Module

#### 2.1.1 Interface Architecture
```
┌─────────────────────────────────────────────────────┐
│        ChatGPT-style Chat Interface                 │
├─────────────────────────────────────────────────────┤
│   ┌─────────────────────────────────────────────┐   │
│   │  Main layout (clean single page)            │   │
│   │  - Left sidebar (session list, new, settings)│   │
│   │  - Center chat area (message stream, input) │   │
│   │  - Top toolbar (model select, clear, export)│   │
│   └─────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────┐   │
│   │  Chat message area                          │   │
│   │  - User messages (right side)               │   │
│   │  - AI assistant messages (left, Markdown)   │   │
│   │  - Code blocks (highlight, copy, run)       │   │
│   │  - Data tables (sort, filter, export)       │   │
│   │  - Chart visualization (ECharts)            │   │
│   │  - Streaming response (typewriter effect)   │   │
│   └─────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────┐   │
│   │  Input area                                 │   │
│   │  - Multi-line text (Shift+Enter for newline)│   │
│   │  - Send button (Enter to send)              │   │
│   │  - Stop generation button                   │   │
│   │  - Attachment upload (files, data sources)  │   │
│   └─────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────┐   │
│   │  Session management                         │   │
│   │  - Session list (grouped: Today/Yesterday)  │   │
│   │  - Session search and filter                │   │
│   │  - Session rename and delete                │   │
│   │  - Session export and share                 │   │
│   └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

#### 2.1.2 ChatGPT-style Conversation Interface Design

Design principle: **Clean, with natural-language interaction at the core**
##### Core Interaction Flow
```
User enters natural language ─────────────────────────────────────────>

System processing: 1. Intent recognition (data processing, create operator, create pipeline, query data)
2. Auto-match skill/operator
3. Generate execution code
4. Stream response with results

AI reply: - Text explanation
- Executable code block (one-click run)
- Data table (exportable) - Chart visualization

Key boundary: DataCrab cannot modify the platform itself, but can help users create and modify their own conversations, operators, and skills.
Scripts in operators and skills can only operate on the user's business data, not platform system data.

User confirms/adjusts ─────────────────────────────────────────────>
```

##### Main Interaction Scenarios

**Scenario 1: Data Processing**
```
User: Help me analyze the sales data and calculate total sales by region

AI: I understand you need sales stats by region, processing...

    [Execution code] df.groupby('region')['sales'].sum()

    [Result table]
    region    | sales
    ----------|-------
    Beijing   | 125000
    Shanghai  | 98000

    [Chart] Showing bar chart...
```

**Scenario 2: Create Operator**
```
User: Create an operator that calculates the moving average
AI: Creating the operator for you...

    Operator name: moving_average
    Parameters: column (column name), window (window size, default 7)
    Code generated and tested, operator registered.
```

**Scenario 3: Create Skill Pipeline**
```
User: Help me create a data-analysis pipeline: first clean data, then filter outliers, finally compute stats
AI: Creating the pipeline...

    Pipeline name: data_analysis_flow
    Steps: data cleaning → outlier filtering → statistical analysis
    
    Pipeline created; can run directly or save as a Skill.
```

##### Layout (minimal)
```
┌─────────────────────────────────────────────────────────────┐
│[New Session]                                                │
├─────────────────────────────────────────────────────────────┤
│Session list                                                 │
│  • Today                                                    │
│    • Sales data analysis                                    │
│    • Create operator session                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│[Message stream]                                             │
│                                                             │
│User: Help me analyze sales data...                          │
│                                                             │
│AI: Processing...                                            │
│    [Code block] [Copy] [Run]                                │
│    [Result table] [Export]                                  │
│    [Chart]                                                  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│[Input box] Enter message...                          [Send]  │
└─────────────────────────────────────────────────────────────┘
```

##### Input Area Features
- Multi-line text input (Shift+Enter for newline) - Attachment upload (data files)
- Shortcut commands: `/create-operator`, `/create-pipeline`, `/run`

##### Message Display Features
- Markdown rendering
- Code block syntax highlighting + one-click copy/run
- Data table preview + export
- Chart visualization - streaming response (typewriter effect)

#### 2.1.4 Data Exploration Panel Design

The data exploration panel provides data source connection, table structure viewing, and data preview.

##### Core Features
- Data source connection management
- Table structure viewing (fields, types, descriptions)
- Data preview (sample data)
- Metadata search
- Show total row count when browsing tables: "Total X rows, showing first Y" (backend `get_table_stats()` provides total count)

##### Layout (simplified)
```
┌─────────────────────────────────────────────────────────────┐
│  Data source list │ Table list │ Table details              │
├─────────────┼────────┼─────────────────────────────────────┤
│  [Sales DB] │ sales  │ Field list:                         │
│  [User DB]  │ users  │ - id (int) primary key              │
│             │ orders │ - name (varchar)                    │
│             │        │ - created_at (datetime)             │
│             │        │                                     │
│             │        │ Data preview: [View]                │
└─────────────┴────────┴─────────────────────────────────────┘
```

### 2.2 Data Source Management Module
#### 2.2.1 Architecture
```
┌───────────────────────────────────────────────┐
│              DataSource Manager               │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  Connection Pool Manager              │   │
│   │  - Connection pool management         │   │
│   │  - Connection health check            │   │
│   │  - Connection reuse                   │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Connector Registry                   │   │
│   │  - Built-in connector registration    │   │
│   │  - Custom connector registration      │   │
│   │  - Connector lifecycle management     │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Metadata Extractor                   │   │
│   │  - Technical metadata extraction      │   │
│   │  - Sample data collection             │   │
│   │  - Data quality analysis              │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

#### 2.2.2 Connector Plugin Mechanism
```python
# Base connector interface
class BaseConnector(ABC):
    @abstractmethod
    async def connect(self, config: dict) -> Connection:
        """Establish connection"""
        pass
    
    @abstractmethod
    async def test_connection(self) -> bool:
        """Test connection"""
        pass
    
    @abstractmethod
    async def get_schema(self) -> List[TableSchema]:
        """Get data source schema"""
        pass
    
    @abstractmethod
    async def execute_query(self, query: str) -> DataFrame:
        """Execute query"""
        pass
    
    @abstractmethod
    async def close(self):
        """Close connection"""
        pass

# Built-in connectors
- DatabaseConnector (MySQL, PostgreSQL, Oracle, SQL Server)
- FileConnector (CSV, Excel, JSON, Parquet)
- APIConnector (REST API, GraphQL)
- BigDataConnector (Hive, Spark, Kafka)
- CloudConnector (S3, OSS, Azure Blob)
```

#### 2.2.3 Data Source Configuration Model
```python
class DataSource(Base):
    __tablename__ = "data_sources"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)  # mysql, postgres, api, file
    connection_config = Column(JSON, nullable=False)  # encrypted storage
    metadata = Column(JSON)  # technical metadata
    business_metadata = Column(JSON)  # business metadata
    security_level = Column(String)
    created_by = Column(UUID, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
```

### 2.3 Natural Language Processing Module

#### 2.3.1 NL Processing Flow
```
User input (natural language)
    → Intent Recognition
    → Entity Extraction
    → Skill Matching
    → Code Generation
    → Parameter Inference
    → Execution Plan
```

#### 2.3.2 LLM Integration Architecture
```python
class LLMManager:
    """LLM Manager"""
    
    def __init__(self):
        self.models = {
            "openai": OpenAIModel,
            "azure": AzureOpenAIModel,
            "local": LocalLLMModel,  # supports local models
            "custom": CustomModel
        }
    
    async def process_natural_language(
        self,
        text: str,
        context: dict
    ) -> ProcessingResult:
        """Process natural-language input"""
        
        # 1. Intent recognition
        intent = await self.recognize_intent(text)
        
        # 2. Entity extraction
        entities = await self.extract_entities(text)
        
        # 3. Generate processing flow (based on Skills)
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
        """Chat with the LLM"""
        model_config = self.get_model_config(model)
        response = await model_config.chat(prompt, temperature)
        return response
```

#### 2.3.3 LLM Public API

DataCrab exposes underlying LLM capabilities as a RESTful API, providing text embedding vectors and more.

##### API Endpoint List

| Method | Path | Description | Auth |
|------|------|------|------|
| POST | /api/v1/llm/embeddings | Generate text embedding vectors | Required |

##### Request/Response Formats

**Embeddings** `POST /api/v1/llm/embeddings`
```json
// Request
{"text": "Text to embed"}

// Response
{
    "embedding": [0.0023, -0.0091, ...],
    "dimensions": 1536
}
```

##### Call Examples (curl)

```bash
# Embeddings
curl -X POST http://localhost:8000/api/v1/llm/embeddings \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "Text to embed"}'
```

##### Calling the LLM inside operator and skill scripts

Besides exposing via HTTP API, DataCrab injects LLM capability into the execution sandbox of operators and skills. Script code can directly call the `llm_chat()` function without HTTP requests.

**Injection methods**:
- **Operator debug execution** (`exec()` sandbox): injects a synchronous `llm_chat` function via `_build_operator_namespace()`, internally calling `llm_manager` via `_run_async_in_thread()`
- **Skill script execution** (`subprocess` sandbox): injects `llm_chat` via the `SKILL_RUNNER_TEMPLATE`, which starts a subprocess to call `llm_manager`

**Function signature**:
```python
def llm_chat(prompt, system_prompt=None, temperature=0.7, max_tokens=2000):
    """
    Call the platform LLM directly inside an operator/skill script

    Args:
        prompt: user message (required)
        system_prompt: system prompt to set AI role and rules (optional)
        temperature: temperature, 0.0-2.0, higher means more random (default 0.7)
        max_tokens: max tokens to generate (default 2000)

    Returns:
        str: the LLM's text reply
    """
```

**Example in an operator script**:
```python
import pandas as pd
from typing import Dict, Any

def translate_data(data, target_language="en"):
    """Translate text columns in the data"""
    df = data if hasattr(data, 'columns') else pd.DataFrame(data)

    # Call the platform LLM to translate
    result = llm_chat(
        prompt=f"Translate the Chinese in the following JSON data to {target_language}, keeping the JSON structure unchanged:\n{df.to_json(orient='records')}",
        system_prompt="You are a professional translation assistant; return only the translated JSON without any explanation.",
        temperature=0.3
    )

    translated_df = pd.DataFrame(eval(result))
    return {"success": True, "data": translated_df.to_dict(orient="records")}
```

**Example in a skill script**:
```python
def analyze_data(data, **kwargs):
    """Analyze data with the LLM"""
    import pandas as pd
    df = data if hasattr(data, 'columns') else pd.DataFrame(data)

    # Get a data summary
    summary = df.describe().to_string()

    # Call the platform LLM to analyze
    analysis = llm_chat(
        prompt=f"Analyze the following statistical summary and give key insights and suggestions:\n{summary}",
        system_prompt="You are a data analyst; answer concisely in Chinese.",
        temperature=0.5
    )

    return {"analysis": analysis, "row_count": len(df)}
```

**Security boundary**:
- `llm_chat` can only call the platform-configured LLM and cannot access the API Key
- `llm_chat` in skill scripts is called via subprocess, isolated from the main process
- `llm_chat` in operator debug executes async calls in a thread with a 60-second timeout

#### 2.3.4 Skills Library
```python
class SkillLibrary:
    """Skill Library - core component"""
    
    def __init__(self, embedding_service):
        self.skills = {}  # skill registry
        self.embeddings = {}  # skill vector index
        self.embedding_service = embedding_service
    
    async def register_skill(self, skill: Skill):
        """Register a skill"""
        # Generate skill description vector
        embedding = await self.embedding_service.embed(
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
        """Search similar skills"""
        # Generate query vector
        query_embedding = await self.embedding_service.embed(query)
        
        # Vector similarity search
        similarities = self.cosine_similarity(query_embedding, ...)
        
        # Filter and rank
        filtered_skills = self.filter_skills(similarities, filters)
        
        return filtered_skills[:top_k]
    
    async def get_skill(self, skill_id: str) -> Skill:
        """Get a skill"""
        return self.skills.get(skill_id)
    
    async def get_skill_executor(self, skill_id: str):
        """Get a skill executor"""
        skill = await self.get_skill(skill_id)
        return skill.get_executor()
```

#### 2.3.4 Skill Definition Model
```python
class Skill(Base):
    __tablename__ = "skills"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200))
    description = Column(Text, nullable=False)
    
    # Skill type
    skill_type = Column(String(50))  # operator, function, pipeline
    
    # Input/output definitions
    inputs = Column(JSON)
    """
    {
        "data": {
            "type": "DataFrame",
            "description": "Input data",
            "required": true
        }
    }
    """
    
    outputs = Column(JSON)
    """
    {
        "result": {
            "type": "DataFrame",
            "description": "Processing result"
        }
    }
    """
    
    # Parameter definitions
    parameters = Column(JSON)
    """
    {
        "columns": {
            "type": "list",
            "description": "Selected columns",
            "required": true,
            "default": []
        }
    }
    """
    
    # Execution config
    executor_config = Column(JSON)
    """
    {
        "type": "python_function",
        "module": "app.skills.operators",
        "function": "select_operator"
    }
    """
    
    # Usage examples (for vector retrieval)
    usage_examples = Column(JSON)
    """
    [
        "Select name and age from the user table",
        "Extract order id and amount from order data",
        "Filter product name and sales amount from sales data"
    ]
    """
    
    # Skill tags for classification and search
    tags = Column(JSON)
    """
    ["data selection", "column ops", "basic operator"]
    """
    
    # Skill category
    category = Column(String(50))
    """
    transform, aggregate, filter, join, analyze
    """
    
    # Metadata
    version = Column(String(20), default="1.0.0")
    author = Column(UUID, ForeignKey("users.id"))
    
    # Permissions
    visibility = Column(String(20))  # private, public, shared
    
    # Statistics
    usage_count = Column(Integer, default=0)
    success_rate = Column(Float, default=1.0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    def get_executor(self):
        """Get the skill executor"""
        config = self.executor_config
        
        if config["type"] == "python_function":
            return self._get_python_executor(config)
        elif config["type"] == "lambda":
            return self._get_lambda_executor(config)
        else:
            raise ValueError(f"Unsupported executor type: {config['type']}")
    
    def _get_python_executor(self, config):
        """Get a Python function executor"""
        module = importlib.import_module(config["module"])
        return getattr(module, config["function"])
    
    def _get_lambda_executor(self, config):
        """Get a Lambda executor"""
        return eval(config["code"])
```

#### 2.3.5 Agent Iteration and Parallel Execution Enhancements

- **Dynamic turn budget**: iteration limit allocated by task complexity (simple=15/medium=25/complex=40), replacing fixed limits
- **Parallel tool calls**: added `_execute_tool_calls_parallel()`; when the LLM returns multiple tool_calls, they execute in parallel via `asyncio.gather()` to improve efficiency
- Parallel execution results are aggregated in tool_call order and returned to the LLM together, ensuring conversation-context integrity
- **Output length escalation**: auto-increase max_tokens on `finish_reason=length` (3000→6000→12000)
- **Context pressure warning**: inject Level-1 hint at 50% token usage, Level-2 urgent at 60%
- **Tiered anti-hallucination**: basic/standard/strict auto-selected by agent role (Inspector=strict, Processor=standard)
- **Tool result LRU cache**: read-only tools deduplicated within session (30-min TTL, 50 entries, 100-user LRU)

### 2.4 Operator Management Module

#### 2.4.1 Operator Architecture

Operators are centered on Python scripts, supporting .py upload, AI natural-language generation, debug execution, modification, and cloning.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Operator Framework                           │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────┐  ┌───────────────────────────────┐  │
│  │  Python Script Parser │  │  Operator Registry             │  │
│  │  - Function signature │  │  - Operator register/discover  │  │
│  │  - Param type inference│  │  - Version management          │  │
│  │  - Docstring parsing  │  │  - Category filter             │  │
│  └───────────────────────┘  └───────────────────────────────┘  │
│  ┌───────────────────────┐  ┌───────────────────────────────┐  │
│  │  AI Generator          │  │  Debug Executor                │  │
│  │  - NL generate script  │  │  - Sandbox-run Python script   │  │
│  │  - NL modify script    │  │  - Parameter injection (DataFrame)│
│  │  - LLM integration     │  │  - Result visualization        │  │
│  └───────────────────────┘  └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.4.2 Operator Definition Model

```python
class Operator(Base):
    __tablename__ = "operators"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)
    category = Column(String(50))  # transform, aggregate, filter, join, ai_generated
    
    # Input/output definitions
    inputs = Column(JSON)   # [{"name": "data", "type": "DataFrame", "required": true}]
    outputs = Column(JSON)  # [{"name": "result", "type": "DataFrame"}]
    
    # Parameter definitions
    parameters = Column(JSON)  # [{"name": "columns", "type": "list", "required": true}]
    
    # Execution config
    execution_config = Column(JSON)  # {"type": "python_script"}
    code_template = Column(Text)     # code template (legacy compat)
    
    # Python script related fields (core)
    script_content = Column(Text)        # full Python script content
    script_filename = Column(String(200)) # script file name
    function_name = Column(String(100))   # entry function name
    
    # Metadata
    version = Column(String(20), default="1.0.0")
    tags = Column(JSON)
    author = Column(UUID, ForeignKey("users.id"))
    
    # Permissions
    visibility = Column(String(20))  # private, public, shared
    permissions = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

#### 2.4.3 Built-in Operator List

```python
# Data transformation operators
- SelectOperator: column selection
- FilterOperator: data filtering
- MapOperator: data mapping
- RenameOperator: column rename
- TypeConvertOperator: type conversion

# Data aggregation operators
- GroupByOperator: group-by aggregation
- PivotOperator: pivot
- AggregateOperator: aggregate computation

# Data join operators
- JoinOperator: table join
- UnionOperator: data union
- ConcatOperator: data concatenation

# Data cleaning operators
- DropNAOperator: drop nulls
- FillNAOperator: fill nulls
- DuplicateOperator: deduplication
- OutlierOperator: outlier handling

# Data analysis operators
- StatisticsOperator: statistical analysis
- CorrelationOperator: correlation analysis
- DistributionOperator: distribution analysis
```

#### 2.4.4 Operator Management Features

The operator management page provides:

##### 2.4.4.1 Upload Python Script
User uploads a .py file → Python Script Parser parses the function signature → auto-extracts parameter types/defaults/descriptions → generates an operator

**Parsing flow**:
```
Upload .py file
    ↓
parse_python_script() parses
    ↓
Extract function_name, inputs, outputs, parameters
    ↓
Create Operator record (script_content stores the full script)
```

**API endpoint**: `POST /operators/upload` (multipart/form-data)

##### 2.4.4.2 AI Generate Operator
User enters a natural-language description → LLM generates a Python script → parse and validate → create operator → auto-jump to the debug page

**SYSTEM_PROMPT enhancements**:
- Includes complete few-shot examples (e.g., `filter_expensive_products`) showing the full flow of parameter extraction, data query, and return format
- Dynamically injects user data source info via `_build_datasource_info()` (available data source names, table names, field structures) so the LLM generates immediately runnable scripts
- Injects lessons learned (collected from the `## Common Issues & Lessons` section of user skills' SKILL.md) to avoid repeated mistakes

**API endpoint**: `POST /operators/generate`
**Request body**:
```json
{
    "prompt": "Filter cultural-relics data by dynasty; support querying by data source name; return the first 100 rows"
}
```

**Implementation**:
```python
@router.post("/generate")
async def generate_operator(request: OperatorGenerateRequest):
    # 1. Call the LLM to generate Python code
    raw_code = await llm_manager.chat_with_messages(messages)
    
    # 2. Clean markdown markers
    script_content = clean_code_blocks(raw_code)
    
    # 3. Parse the script to extract function info
    parsed = parse_python_script(script_content)
    
    # 4. Create the operator record
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

##### 2.4.4.3 AI Modify Operator
Select an existing operator → enter a modification instruction → LLM modifies based on the original script → **auto-verify the modification** → overwrite-update → auto-jump to the debug page

**Mandatory verification after modification**: After modifying an operator script, the system must automatically call the debug endpoint (POST /operators/debug) to verify the modification introduced no errors. If verification fails, prompt the user and provide fix suggestions.

**Output defaults to same source**: When an operator generates a new file, if no output path is specified, it defaults to saving under the file path specified by the DataSource.

**Auto-verification and LLM repair loop**: After modifying an operator script, the system automatically runs `exec()` to verify script syntax and function callability. If verification fails, it automatically calls the LLM to repair the script (up to 2 rounds), feeding the error info back to the LLM to regenerate each round. Helper functions include:
- `_validate_operator_script(script_content)`: compile + exec to verify script syntax and extract the function signature
- `_llm_fix_operator_script(original_script, error_message, instruction)`: pass the original script + error info + modification instruction to the LLM to generate a repaired script
- `_strip_code_fences(raw_code)`: strip markdown code fences (```python ... ```) from LLM output

**API endpoint**: `POST /operators/{operator_id}/modify`
**Request body**:
```json
{
    "instruction": "Add a count-limit parameter, default return 50 rows"
}
```

**Implementation**:
```python
@router.post("/{operator_id}/modify")
async def modify_operator(operator_id, request: OperatorModifyRequest):
    # 1. Get the original script
    operator = get_operator(operator_id)
    
    # 2. Build prompt including original script + modification instruction
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Original script:
{operator.script_content}
Modification request:
{request.instruction}"}
    ]
    
    # 3. LLM generates the modified script
    raw_code = await llm_manager.chat_with_messages(messages)
    
    # 4. Parse and update
    parsed = parse_python_script(clean_code_blocks(raw_code))
    operator.script_content = clean_code_blocks(raw_code)
    operator.function_name = parsed["function_name"]
    operator.inputs = parsed["inputs"]
    operator.outputs = parsed["outputs"]
    operator.parameters = parsed["parameters"]
    return operator
```

##### 2.4.4.4 Clone Operator (Save As)
Select an existing operator → enter a new name → copy all config and scripts → generate an independent new operator

**API endpoint**: `POST /operators/{operator_id}/clone`
**Request body**:
```json
{
    "name": "New operator name"
}
```

**Implementation**:
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
        script_content=operator.script_content,   # copy script
        script_filename=f"{request.name}.py",
        function_name=operator.function_name,
        tags=operator.tags,
        visibility=operator.visibility
    )
    db.add(clone)
    return clone
```

##### 2.4.4.5 Operator Debug
Click the debug button → dialog opens → two-column layout: left has the parameter panel on top + script editor below, right is the AI code-assistant chat panel → fill in parameters and execute → show result/error → debug and modify code via the AI assistant

**AI Code Assistant**: a ChatGPT-style chat interface on the right; the AI can analyze code logic, fix bugs, optimize code, and directly modify the script (after outputting a complete script wrapped in a python fence, the database is auto-updated). Supports reasoning display (blue card), auto-execution/modification of scripts.

**Interaction enhancements**:
- All input fields support ↑↓ arrow keys to switch historical inputs (localStorage persistence, up to 100)
- AI generate/modify dialogs also support ↑↓ history switching
- Execution results (stdout, return result) auto-expand instead of collapsing
- All dialogs add `close-on-press-escape="false"` to prevent accidental close when focus leaves
- Placeholder text auto-wraps (CSS `white-space: pre-wrap; word-break: break-all`)

**API endpoints**: 
- `POST /operators/{id}/debug` - execute debug
- `POST /operators/{id}/debug-chat` - AI code debug assistant (SSE streaming, with reasoning)

**Debug interface layout**:
```
┌──────────────────────────────────────────────────────────────────┐
│  Debug: operator name                                  [Close X]│
├────────────────────────────────┬─────────────────────────────────┤
│  ┌──────────────────────────┐  │  AI Code Assistant              │
│  │ Parameter panel          │  │  ┌───────────────────────────┐  │
│  │ func_name(param1, ...)   │  │  │  Reasoning (blue card)    │  │
│  │ Input: data [DataFrame]  │  │  │  🔄 Analyzing script...   │  │
│  │ Optional: limit=100      │  │  ├───────────────────────────┤  │
│  │ [Run Debug]              │  │  │  AI reply                 │  │
│  ├──────────────────────────┤  │  │  Suggest modifying line 23│  │
│  │ Script editor            │  │  │  [Code updated]           │  │
│  │ def filter_data(df, ...):│  │  ├───────────────────────────┤  │
│  │     ...                  │  │  │  [Enter debug cmd...] [Send]│  │
│  └──────────────────────────┘  │  └───────────────────────────┘  │
│  ┌──────────────────────────┐  │                                 │
│  │ Execution result (auto)  │  │                                 │
│  │ ✅ Success 120ms         │  │                                 │
│  │ Stdout: ...              │  │                                 │
│  │ Return result: ...       │  │                                 │
│  └──────────────────────────┘  │                                 │
└────────────────────────────────┴─────────────────────────────────┘
```

**debug-chat context passing**:
- The frontend automatically passes the left panel's input parameter values and execution result (success/failure/error) as context to the backend
- The backend attaches the context to the user message so the AI knows the current debug state
- When the AI outputs a complete script with a ```python fence, the backend auto-parses and updates the operator's script_content

**Debug execution flow**:
```
User clicks "Run Debug"
    ↓
POST /operators/debug {operator_id, params, script_content}
    ↓
Backend builds execution namespace (injects query_table_data, get_table_schema, etc.)
    ↓
exec() runs the script + calls the entry function
    ↓
Returns: {success, stdout, result, error, execution_time_ms}
```

**Debug Executor core implementation**:
```python
# Tool function injection - provide data-query capability in the operator execution env
def _build_operator_namespace(current_user_id):
    def query_table_data(datasource_id, table_name, **kwargs):
        args = {"datasource_id": str(datasource_id), "table_name": table_name, **kwargs}
        # Run async DB query in a separate thread via execute_shared_tool
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
        "get_table_schema": get_table_schema_sync,
        "get_datasource_id_by_name": get_datasource_id_by_name,
    }
```

##### 2.4.4.6 Download Script
Click download → download the .py file (script_filename as filename, script_content as content)

**API endpoint**: `GET /operators/{operator_id}/download`

##### 2.4.4.7 Operator Management UI

Page layout:
```
┌──────────────────────────────────────────────────────────────┐
│ [Upload Python] [AI Generate]  [Category▼]  [Search...]      │
├──────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Operator card 1 │  │ Operator card 2 │  │ Operator card│ │
│  │ Name: xxx       │  │ Name: xxx       │  │ 3            │ │
│  │ Desc: xxx       │  │ Desc: xxx       │  │              │ │
│  │ [param1] [p2]   │  │ [param1]        │  │              │ │
│  │                 │  │                 │  │              │ │
│  │ [Debug][Download]│  │ [Debug][Download]│  │              │ │
│  │ [Modify][SaveAs]│  │ [Modify][SaveAs]│  │              │ │
│  │ [Delete]        │  │ [Delete]        │  │              │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

Card button descriptions:
| Button | Function |
|------|------|
| 🔵 Debug | Open the right drawer, edit script and debug-run |
| ⚪ Download | Download the .py script file |
| 🟠 Modify | AI modifies the script per natural-language instruction |
| ⚫ Save As | Copy the operator and script as a new independent operator |
| 🔴 Delete | Delete the operator |


### 2.5 Skill Management Module

#### 2.5.1 Design Philosophy

A Skill is DataCrab's modular capability package following the Agent Skills open standard. Each Skill is an independent folder containing:

```
SKILL.md          # Core instruction doc (YAML metadata + Markdown instructions)
scripts/          # Executable Python scripts
  main.py         # Main processing script
references/       # Reference materials
assets/           # Static assets
```

Relationship with Operator:
- **Operator**: low-level technical component; a pure Python function with no business description; executes directly
- **Skill**: business-semantic wrapper; has a natural-language description; supports vector search; can be composed into Pipelines
- A Skill can reference an Operator as its execution logic, or define its own scripts

#### 2.5.2 Data Model

```python
class Skill(Base):
    """Skill model - manages Skill packages (folders)"""
    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)

    skill_path = Column(String(500))  # on-disk storage path

    tags = Column(JSON)               # tag list
    category = Column(String(50), index=True)  # category

    version = Column(String(20), default="1.0.0")
    author = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    visibility = Column(String(20), index=True)  # public/private

    usage_count = Column(Integer, default=0)
    success_rate = Column(Float, default=1.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

#### 2.5.3 SKILL.md Format Spec

SKILL.md is the Skill's core document, using YAML front matter + Markdown:

```markdown
---
name: skill-name
description: Skill description
category: data_cleaning
tags: [filter, transform]
---

# Skill Name

## Function Description
Describe the skill's function...

## Usage
Explain how to use...

## Script Description
- main.py: main processing script
- helper.py: helper functions

## Parameter Spec
| Parameter | Type | Required | Description |
|------|------|------|------|
| column | string | yes | column name |
| limit | int | no | row limit |
```

#### 2.5.4 API Endpoints

| Method | Path | Description |
|------|------|------|
| GET | /api/v1/skills | Get skill list (supports category filter) |
| GET | /api/v1/skills/categories | Get all categories |
| GET | /api/v1/skills/{id} | Get skill detail (incl. SKILL.md, script list) |
| POST | /api/v1/skills | Create skill |
| PUT | /api/v1/skills/{id} | Update skill metadata |
| DELETE | /api/v1/skills/{id} | Delete skill (incl. disk files) |
| POST | /api/v1/skills/upload | Upload Skill package (.zip) |
| GET | /api/v1/skills/{id}/download | Download Skill package (.zip) |
| GET | /api/v1/skills/{id}/skill-md | Get SKILL.md content |
| PUT | /api/v1/skills/{id}/skill-md | Update SKILL.md content |
| GET | /api/v1/skills/{id}/scripts | Get script list |
| GET | /api/v1/skills/{id}/scripts/{name} | Get a specific script's content |
| PUT | /api/v1/skills/{id}/scripts/{name} | Update or create a script |
| DELETE | /api/v1/skills/{id}/scripts/{name} | Delete a script |
| POST | /api/v1/skills/{id}/run | Execute a Skill script |
| POST | /api/v1/skills/{id}/run-stream | Execute a Skill script (SSE streaming, real-time status) |
| POST | /api/v1/skills/{id}/run-nl | Natural-language execute Skill (LLM infers params then runs) |
| POST | /api/v1/skills/{id}/run-nl-stream | Natural-language execute Skill (SSE streaming, with reasoning) |
| POST | /api/v1/skills/{id}/modify-stream | AI modify skill (SSE streaming, with thinking) |
| POST | /api/v1/skills/{id}/debug-chat | AI debug assistant (SSE streaming, reasoning display, auto-run/modify script) |
| POST | /api/v1/skills/generate | AI generate a complete Skill package |
| POST | /api/v1/skills/{id}/clone | Clone a skill |
| POST | /api/v1/skills/search | Search skills |
| POST | /api/v1/skills/{id}/summarize-errors | AI analyzes error logs, generates lessons and writes to SKILL.md |

#### 2.5.5 Core Services

##### skill_parser.py - SKILL.md Parser
- parse_skill_md(): parse YAML front matter + Markdown content
- build_skill_md(): build a complete SKILL.md file
- get_skill_info_from_path(): read basic Skill info from a folder
- read_skill_md() / write_skill_md(): read/write SKILL.md
- read_skill_script() / write_skill_script(): read/write script files
- list_skill_scripts(): list all script files

##### skill_runner.py - Sandbox Executor
Executes Skill scripts in an isolated subprocess, supporting:
- Injecting input data (DataFrame)
- Injecting parameters (parameters dict)
- Built-in tool functions: query_table_data(), get_table_schema(), get_datasource_id_by_name()
- Auto-detecting the main function name in the script (via AST parsing)
- Timeout control (default 60s, configurable via SKILL_RUNNER_TIMEOUT)
- Result capture: parse the return value via the __RESULT__ marker

##### skill_creator.py - AI Generator
- generate_skill() / generate_skill_stream(): generate a complete Skill package from a natural-language description
  - New `datasource_info` parameter: dynamically query user data source info (names, table names, field structures), replacing hardcoded data source names
  - New `lessons` parameter: inject lessons learned from similar skills (collected via `_collect_all_lessons()`), letting the LLM reference historical experience to avoid repeated mistakes
- The Skill Creator system prompt includes:
  - SKILL.md writing spec
  - Script writing spec (pandas processing, type annotations, boundary handling)
  - Built-in tool function descriptions
  - Complete few-shot example (filter-by-dynasty skill package) showing the full generation flow from description to SKILL.md + scripts
  - Data source reference info (dynamically injected via datasource_info, removing hardcoded data source names)
- create_skill_on_disk(): create the Skill folder structure on disk

##### data_analyst_agent.py - Data Analysis Agent
- DataAnalystAgent: read-only analysis agent (query/stats/distribution/insights), no data modification
- 5 read-only tool subset (ANALYSIS_TOOLS): query_table_data/get_table_schema/list_user_datasources/execute_sql/kb_search
- Independent truncation threshold (ANALYSIS_MAX_TOOL_RESULT_CHARS=30000, 50-row preview)
- No handoff; chat_router keyword routing decides DataAnalyst vs DataProcessor
- System prompt process-level memoize (Prefix Cache)

##### prompt_docs.py - Sandbox Function Docs
- SANDBOX_TOOLS_DOC: 17 sandbox function signatures
- PLATFORM_CONVENTIONS_DOC: platform conventions (prefer built-in / no extensions / no external API)
- Injected into generate/debug/NL-inference

##### standards_parser.py - Rule Parser
- Parse data standards/quality/security rules (valid values / detection logic)
- parse_security_rules no longer skips regex-less rules

##### skill_executor.py - Execution Context & Result Data Structures
- ExecutionContext: execution context (session ID, user ID, variables, DataFrame)
- ExecutionResult: execution result (success/output/error/logs/metrics)
- Used by nl_data_processor; SkillExecutor class and built-in skill functions have been removed (unused)

#### 2.5.6 Frontend

SkillView.vue provides the full skill management UI:
- Skill card grid layout (supports category filter and text search)
- Upload Skill package dialog (.zip drag-drop upload, auto-parse SKILL.md)
- AI generate skill dialog (enter a natural-language description; AI auto-generates a complete Skill package)
- Skill detail drawer (three tabs):
  - SKILL.md tab: edit and preview SKILL.md content
  - Script list tab: view/edit scripts; can open debug directly from a script
  - Properties tab: view skill metadata
- Natural-language modification (AI modify drawer, streaming display of thinking/generation)
- Skill debug interface (merging execution and AI debug assistant):
  - Left execution panel: three input modes — natural language / command line / JSON params; real-time execution result display
  - Right AI debug panel: ChatGPT-style chat; AI can auto-run or modify scripts
  - AI replies show reasoning (blue reasoning card) with a spinner and thinking content
  - SSE streaming response, real-time reasoning and reply content
- Skill execution supports stop/pause (frontend AbortController + backend asyncio.create_subprocess_exec)
- Skill self-evolution: error logs auto-recorded to error_log.json; the "Summarize Lessons" button on the skill detail page calls the summarize-errors endpoint; lessons are written to SKILL.md
- Detail drawer and generate dialog add `close-on-press-escape="false"` to prevent accidental close when focus leaves
- Skill download (export as .zip) and delete

#### 2.5.7 Skill Execution & Debug Flow

##### Basic Execution Flow
```
Client requests POST /api/v1/skills/{id}/run
  → skill_runner.run_skill_script()
  → build SKILL_RUNNER_TEMPLATE (inject data, params, tool functions)
  → subprocess.run() in an independent Python process
  → parse the __RESULT__ marker in stdout to get the return value
  → _sanitize_nans() recursively replaces NaN/Infinity with None
  → return SkillRunResponse { success, result, stdout, execution_time_ms }
```

##### SSE Streaming Execution
```
POST /api/v1/skills/{id}/run-stream
  → SSE event stream: executing → done/error
  → real-time push of execution status and result
```

##### Natural-Language Execution
```
POST /api/v1/skills/{id}/run-nl-stream
  → LLM infers execution params (thinking → content → inferred_params)
  → auto-inject datasource/tables params
  → execute script and stream result
```

##### AI Debug Assistant
```
POST /api/v1/skills/{id}/debug-chat
  → system prompt includes SKILL.md + script content context
  → LLM can output action JSON: {"action": "run"} triggers execution, {"action": "modify_script"} triggers script modification
  → mandatory verification after modify: after modify_script, must auto-run to verify
  → output defaults to same source: new files default to the DataSource's file path
  → SSE event stream: thinking (reasoning) → content (reply) → run_result/script_updated → done
  → frontend shows reasoning card (blue border, spinner + thinking content)
  → supports multi-turn dialogue; context includes history messages and execution results
```

##### Debug Interface Layout
```
┌──────────────────────────────────────────────────────────────────┐
│  Debug: skill name                                    [Close X] │
├────────────────────────────────┬─────────────────────────────────┤
│  Execution panel               │  AI Debug Assistant             │
│  ┌──────────────────────────┐  │  ┌───────────────────────────┐  │
│  │ [NL][Cmd][JSON]          │  │  │  Reasoning                │  │
│  │                          │  │  │  🔄 AI is analyzing...    │  │
│  │  Input area              │  │  │  Line 23 may have...      │  │
│  │  [Execute]               │  │  ├───────────────────────────┤  │
│  ├──────────────────────────┤  │  │  AI reply                 │  │
│  │  Execution result        │  │  │  Suggest changing limit...│  │
│  │  ✅ Success 120ms        │  │  │  [Success] [Script updated]│  │
│  │  Return data: ...        │  │  ├───────────────────────────┤  │
│  └──────────────────────────┘  │  │  [Enter debug cmd...] [Send]│  │
│                                │  └───────────────────────────┘  │
└────────────────────────────────┴─────────────────────────────────┘
```

#### 2.5.8 Self-Evolving Experience Library (operators + skills unified)

Operators and skills share a unified self-evolution mechanism (`app/services/experience.py`): failures auto-record **negative examples**; successes after a fix auto-record **positive examples**; the LLM distills them into "common errors + success patterns" lessons, written to a unified `experience.json` and injected into subsequent generate/modify/debug prompts, closing the "execute → record → distill → inject" loop.

- Skills: `{skill_path}/experience.json` (backward-compatible read of legacy `error_log.json`; lessons mirrored to SKILL.md `## Common Issues & Lessons`)
- Operators: `backend/data/operator_experiences/{operator_id}/experience.json` (operators have no folder; stored on disk uniformly)
- `experience.json` structure: `{negative:[...], positive:[...], lessons:""}`
- Collection rules: failure → `append_negative`; success when prior negatives exist (i.e., fix-then-success) → `append_positive`
- Distill: `POST /operators/{id}/summarize-experience`, `POST /skills/{id}/summarize-errors`; the LLM analyzes both negative and positive examples
- Injection: `collect_all_lessons(db, user_id)` gathers all the user's operator + skill lessons and injects them into operator generate/modify/debug-chat and skill skill_creator prompts

##### Auto Negative (Error) Recording

On each execution failure, the system appends the error info to the experience library's `negative` list (max 200 entries, FIFO):

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

- The `source` field marks the error origin: `run` (direct execution), `debug` (debug execution), `nl` (natural-language execution)
- Log file path: `{skill_path}/error_log.json`

##### LLM Lesson Summarization

`POST /api/v1/skills/{id}/summarize-errors` endpoint:
1. Read the skill's `error_log.json`
2. Call the LLM to analyze error patterns (high-frequency error types, common causes, fix suggestions)
3. Write the summary into the `## Common Issues & Lessons` section of SKILL.md (update if it exists)
4. Return the summary content to the frontend

##### Lesson Injection

- **When generating new skills**: `_collect_all_lessons()` collects the `## Common Issues & Lessons` section from all the current user's skills' SKILL.md and injects it as the `lessons` parameter into the skill_creator prompt, letting the LLM reference historical experience to avoid repeated mistakes
- **Debug assistant**: the debug assistant's system prompt injects `read_lessons()` to read the current skill's lessons, letting the AI reference historical experience to guide debugging

##### Frontend "Summarize Lessons" Button

The skill detail page adds a "Summarize Lessons" button; clicking it calls `POST /api/v1/skills/{id}/summarize-errors`, displays the LLM-generated lessons, and auto-writes them to SKILL.md.

#### 2.5.9 Built-in Skill List

SkillLibrary presets these data-processing skills:

| Skill | Category | Function |
|----------|------|------|
| select | transform | Select specified columns |
| filter | transform | Filter rows by condition |
| sort | transform | Sort by column |
| groupby | aggregate | Group-by aggregation |
| aggregate | aggregate | Aggregate stats |
| join | fusion | Table join |
| fillna | cleaning | Fill missing values |
| dropna | cleaning | Drop missing values |
| rename | transform | Rename columns |
| stats | analysis | Statistical description |

### 2.6 Pipeline Module

#### 2.6.1 Design Philosophy

**A Pipeline is DataCrab's core orchestration concept—each pipeline is a Python main function.**

Discarding the old DAG node/edge model, the essence of a pipeline is: **one Python main function + the Skill scripts it calls**. Users only need to understand one Python function to grasp the entire data-processing logic.

**Core principles**:
- **One pipeline = one Python main function**: the main function orchestrates the complete logic of data reading, processing, and writing
- **Skill → main function conversion**: one-click convert a Skill script into a standalone runnable Python main function; the main function calls the Skill's script to do the work
- **Code visualization**: the frontend shows the main function source (syntax highlighted) and parses out the call graph from the main function to Skill scripts
- **Direct execution**: no DAG engine needed; just run the main function to get results

```
┌──────────────────────────────────────────────────────────┐
│   Pipeline: cultural-relics data cleaning                │
│                                                          │
│   def main(datasource, tables, primary_key, options):    │
│       # 1. Read data                                     │
│       from app.services.connectors import ConnectorManager │
│       df = ConnectorManager.read_table(datasource, tables) │
│                                                          │
│       # 2. Call Skill script to process                  │
│       result = clean_data_main(df, primary_key, options) │
│                                                          │
│       # 3. Write result                                  │
│       ConnectorManager.write_table(datasource, tables,   │
│                                    result)               │
│       return result                                      │
│                                                          │
│   Call graph:  [Skill: data-cleaning-deduplication]      │
│             main() ──▶ scripts/main.py :: clean_data_main()│
└──────────────────────────────────────────────────────────┘
```

#### 2.6.2 Relationship with Skill

| Dimension | Skill | Pipeline |
|------|-------|-----------------|
| **Essence** | Modular capability package (SKILL.md + scripts/) | Executable complete Python program |
| **Composition** | Docs + scripts + references | Python main function source |
| **Run mode** | Subprocess sandbox runs a single script | Directly run the main function |
| **Source** | Upload / AI generate | Converted from Skill / manual / AI generate |
| **Relationship** | Called by pipelines | Calls one or more Skills' scripts |

#### 2.6.3 Data Model

```python
class Pipeline(Base):
    """Pipeline definition - a complete Python main function"""
    __tablename__ = "pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)

    # Core: Python main function source
    main_code = Column(Text, nullable=False)
    """
    def main(datasource: str, tables: List[str], **kwargs):
        '''Cultural-relics data cleaning pipeline'''
        from app.services.connectors import ConnectorManager

        cm = ConnectorManager()
        df = cm.read_table(datasource, tables[0])

        # Call the Skill's main script
        result = clean_data_main(df, **kwargs)

        cm.write_table(datasource, tables[0], result)
        return result
    """

    # Main function signature info (parsed from main_code)
    entry_function = Column(String(100), default="main")  # entry function name
    parameters = Column(JSON)
    """
    [
        {"name": "datasource", "type": "str", "required": true, "description": "Data source ID"},
        {"name": "tables", "type": "list", "required": true, "description": "Table name list"}
    ]
    """

    # Call relationships: which Skill scripts the main function calls
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

    # Source
    source_skill_id = Column(UUID(as_uuid=True))  # converted from which Skill

    # Metadata
    version = Column(Integer, default=1)
    tags = Column(JSON)
    category = Column(String(50))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    visibility = Column(String(20), default="private")

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PipelineExecution(Base):
    """Pipeline execution record"""
    __tablename__ = "pipeline_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id = Column(UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False)

    status = Column(String(20), default="pending")  # pending, running, success, failed, cancelled

    # Runtime params
    inputs = Column(JSON)
    outputs = Column(JSON)

    # Time and duration
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)

    # Error info
    error_message = Column(Text)

    # Execution logs (stdout/stderr)
    logs = Column(Text)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
```

#### 2.6.4 Pipeline Builder

The Pipeline Builder's core task is to **generate a complete Python main function**, not to build a DAG.

##### Generate Pipeline from Skill

```
User clicks "Convert to Pipeline"
    │
    ├─ 1. Read the Skill's SKILL.md (metadata + parameter definitions)
    │
    ├─ 2. Read the Skill's scripts/ directory (all script contents)
    │
    ├─ 3. LLM generates the Python main function
    │     ├─ Inject: Skill script content (as the called module)
    │     ├─ Inject: data source info (available datasource/table)
    │     ├─ Generate: import statements + main function definition
    │     ├─ Inside the main function:
    │     │   ├─ ConnectorManager.read_table() reads data
    │     │   ├─ Call the Skill script's entry function to process data
    │     │   └─ ConnectorManager.write_table() writes results
    │     └─ Main function supports command-line args (argparse)
    │
    ├─ 4. Parse call relationships
    │     └─ AST analyze main_code to extract calls to Skill script functions
    │
    └─ 5. Create Pipeline record + return to frontend
```

##### LLM Prompt Template

```python
PIPELINE_BUILDER_PROMPT = """You are a Python code generator that converts a Skill into an executable Python main function.

## Input
- Skill name: {skill_name}
- Skill description: {skill_description}
- Skill params: {skill_params}
- Skill script content: {skill_scripts}

## Output Requirements
Generate a complete Python main function file containing:

### 1. File header comment
```python
'''
Pipeline: {pipeline_display_name}
Description: {description}
Generated from Skill: {skill_name}
'''
```

### 2. import section
```python
import argparse
import os
import pandas as pd
from app.services.connectors import ConnectorManager
```

### 3. Inlined Skill script functions
Inline each of the Skill's script function definitions into the main file; prefix function names with `_skill_` to avoid conflicts.

### 4. Main function
```python
def main(datasource_name: str, table_name: str, **kwargs):
    cm = ConnectorManager()
    df = cm.read_table(datasource_name, table_name)
    result = _skill_main(df, **kwargs)
    cm.write_table(datasource_name, table_name, result)
    return result
```

### 5. argparse entry (support direct command-line run)
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("datasource_name", type=str, help="Data source name")
    ...
    args = parser.parse_args()
    main(**vars(args))
```

## Important Rules
- Must use `ConnectorManager.read_table()` / `ConnectorManager.write_table()` for data read/write
- Data source params use names not UUIDs; `ConnectorManager` resolves internally
- Prefix all Skill script functions with `_skill_`
- Handle edge cases (empty tables, missing columns, etc.)
- Function signatures and parameters must have type annotations
```

#### 2.6.5 Execution Engine

Pipeline execution directly runs the Python main function; no DAG traversal needed.

```python
class PipelineExecutor:
    """Pipeline executor - directly runs a Python main function"""

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
            # 1. Dynamically compile the main function code
            module_code = compile(pipeline.main_code, f"<pipeline_{pipeline.id}>", "exec")
            namespace = {"__name__": "__pipeline__", "__builtins__": __builtins__}
            exec(module_code, namespace)

            # 2. Get the entry function
            func = namespace.get(pipeline.entry_function or "main")
            if not callable(func):
                raise ValueError(f"Entry function '{pipeline.entry_function}' is not callable")

            # 3. Call the main function
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
        """SSE streaming execution, real-time status push"""
        yield {"type": "status", "status": "running", "message": "Pipeline starts running..."}

        execution = PipelineExecution(
            pipeline_id=pipeline.id,
            status="running",
            inputs=inputs,
            started_at=datetime.utcnow(),
        )
        yield {"type": "status", "status": "running", "message": "Compiling main function..."}

        try:
            module_code = compile(pipeline.main_code, f"<pipeline_{pipeline.id}>", "exec")
            namespace = {"__name__": "__pipeline__", "__builtins__": __builtins__}
            exec(module_code, namespace)
            func = namespace.get(pipeline.entry_function or "main")

            yield {"type": "status", "status": "running", "message": "Executing main function..."}

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

#### 2.6.6 API Endpoints

| Method | Path | Description |
|------|------|------|
| GET | /api/v1/pipelines | Get pipeline list (supports name/tag filter) |
| GET | /api/v1/pipelines/{id} | Get pipeline detail (incl. main_code) |
| POST | /api/v1/pipelines | Create pipeline (manually write main_code) |
| PUT | /api/v1/pipelines/{id} | Update pipeline (modify main_code, etc.) |
| DELETE | /api/v1/pipelines/{id} | Delete pipeline |
| **POST** | **/api/v1/pipelines/from-skill/{skill_id}** | **Generate pipeline from Skill (LLM generates main_code)** |
| POST | /api/v1/pipelines/{id}/run | Execute pipeline |
| POST | /api/v1/pipelines/{id}/run-stream | SSE streaming execution |
| GET | /api/v1/pipelines/{id}/executions | Get execution history |
| GET | /api/v1/pipelines/executions/{eid} | Get a single execution detail |
| POST | /api/v1/pipelines/{id}/clone | Clone pipeline |

#### 2.6.7 Frontend

##### Pipeline List Page

```
┌──────────────────────────────────────────────────────────────┐
│ [New Pipeline] [From Skill▼]  [Category▼]  [Search...]       │
├──────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐            │
│  │ 📄 Relics cleaning   │  │ 📄 Sales analysis    │            │
│  │ From Skill           │  │ Manual               │            │
│  │ Calls 2 scripts      │  │ Calls 1 script       │            │
│  │ Last: success 3.2s   │  │ Last: failed         │            │
│  │                      │  │                      │            │
│  │ [View Code] [Run]    │  │ [View Code] [Run]    │            │
│  │ [Schedule] [Delete]  │  │ [Schedule] [Delete]  │            │
│  └─────────────────────┘  └─────────────────────┘            │
└──────────────────────────────────────────────────────────────┘
```

##### Pipeline Detail Page (code + call graph)

```
┌──────────────────────────────────────────────────────────────────┐
│  Pipeline: relics cleaning                  [Edit] [Run▶] [Schedule]│
├────────────────────────┬─────────────────────────────────────────┤
│  Main function code    │  Call graph                              │
│  ┌────────────────────┐ │  ┌───────────────────────────────────┐ │
│  │ 1 │ '''            │ │  │  main()                           │ │
│  │ 2 │ Pipeline: ...  │ │  │  ├── ConnectorManager.read_table()│ │
│  │ 3 │ '''            │ │  │  ├──▶ Skill: data-cleaning        │ │
│  │ 4 │                │ │  │  │    └─ scripts/main.py          │ │
│  │ 5 │ import ...     │ │  │  │       :: clean_data_main()     │ │
│  │ 6 │                │ │  │  └── ConnectorManager.write_table()│ │
│  │ 7 │ def main(...): │ │  └───────────────────────────────────┘ │
│  │ 8 │     cm = ...   │ │                                         │
│  │ 9 │     df = cm... │ │  Execution history                      │
│  │10 │     result =   │ │  ┌───────────────────────────────────┐ │
│  │11 │         _skill │ │  │ ✅ 2026-06-18 10:30  3.2s  success│ │
│  │12 │     cm.write.. │ │  │ ✅ 2026-06-18 09:15  2.8s  success│ │
│  │13 │     return ... │ │  │ ❌ 2026-06-17 14:20  0.5s  failed │ │
│  │14 │                │ │  └───────────────────────────────────┘ │
│  │15 │ if __name__... │ │                                         │
│  └────────────────────┘ │                                         │
├────────────────────────┴─────────────────────────────────────────┤
│  [Monaco Editor - Python syntax highlighting]                    │
└──────────────────────────────────────────────────────────────────┘
```

##### Skill → Pipeline conversion entry

On the Skill page, the "Convert to Pipeline" button:

```
┌─────────────────────────────────┐
│ Data cleaning dedup             │
│ Dedup and null handling         │
│                                  │
│ [Debug] [Download] [Modify]     │
│ [Convert to Pipeline▶]          │
└─────────────────────────────────┘
```

Clicking it opens a confirmation dialog (SSE streaming of the generation process):

```
┌──────────────────────────────────────┐
│  Convert Skill to Pipeline           │
│                                      │
│  Skill: Data cleaning dedup          │
│  Includes script: main.py            │
│                                      │
│  Skill Creator is generating...      │
│  ┌────────────────────────────────┐  │
│  │ Analyzing Skill structure...   │  │
│  │ Generating Python main fn...   │  │
│  │ Done, 3 function calls found   │  │
│  └────────────────────────────────┘  │
│                                      │
│  Pipeline name: [Cleaning - Pipeline]│
│                                      │
│         [Cancel]    [Create & View]  │
└──────────────────────────────────────┘
```

##### Frontend Tech Choices

| Component | Library | Description |
|------|-----|------|
| Code edit/display | Monaco Editor | Python syntax highlight, code editing, read-only mode |
| Call graph | Custom Vue component | Tree view of main function → Skill script call chain |
| List page | Element Plus Card | Pipeline card grid |
| Execution status | SSE EventSource | Real-time execution progress push |

#### 2.6.8 Pipeline & Schedule Relationship

A pipeline can be linked to a schedule config for automated scheduled/event-triggered execution:

```
Pipeline ──1:1──▶ Schedule
                    ├─ task_type: "pipeline"
                    ├─ task_target_id: pipeline.id
                    ├─ cron: "0 2 * * *"    (every day at 2am)
                    ├─ event: data source update (event trigger)
                    └─ manual: manual trigger
```

When a schedule triggers, a PipelineExecution record is created and status is pushed to the frontend in real time.

#### 2.6.9 Implementation Status

| Feature | Status | Description |
|------|------|------|
| Pipeline data model | ✅ Done | Pipeline + PipelineExecution |
| Pipeline Builder (Skill→pipeline) | ✅ Done | LLM generates Python main function |
| Pipeline execution engine | ✅ Done | Dynamic compile + exec runs main function |
| API endpoints | ✅ Done | CRUD + from-skill + run + run-stream + clone |
| Frontend list page | ✅ Done | Pipeline card grid |
| Frontend detail page | ✅ Done | Code display + call graph |
| Skill page "Convert to Pipeline" button | ✅ Done | Generate Pipeline from Skill |
| SSE streaming generation+execution | ✅ Done | LLM generation streaming + execution streaming |

**Deprecated old features**:
- ~~DAG node/edge model~~
- ~~Vue Flow canvas editor~~
- ~~Kahn topological sort~~
- ~~Multi-engine adaptation (Prefect/Airflow)~~
- ~~Node type enums (skill/condition/parallel, etc.)~~
- ~~Parameter mapping expressions ($upstream.$input)~~

### 2.7 Multi-Agent Collaboration Framework

#### 2.7.1 Design Philosophy

DataCrab evolved from a single-agent architecture to a **multi-agent collaboration framework**. Each agent is an independent responsibility unit with its own LLM instructions, toolset, and knowledge context, collaborating via a message bus.

**Core design principles**:
- **Single responsibility**: each agent handles only one domain (data processing, quality inspection, security audit...), with precise unambiguous instructions
- **Handoff**: agents hand off work via structured messages, carrying full context (data, issues, traceability info)
- **Pluggable extension**: adding an agent only requires implementing the Agent interface and registering with AgentRegistry; no need to modify existing agents
- **Human-in-the-loop**: key decision points (e.g., data-repair plans) can pause for human confirmation

**Reference frameworks**:
- **OpenAI Swarm / Agents SDK**: Agent + Handoff primitive; lightweight; returning an Agent from a function triggers handoff
- **CrewAI**: Crew (team) + Task + Sequential/Hierarchical process; emphasizes role division and process orchestration
- **AutoGen**: RoutedAgent + Topic/Subscription message routing; supports distributed runtime

DataCrab borrows Swarm's Handoff simplicity + CrewAI's role division + AutoGen's message routing to form a multi-agent architecture suited to data-processing scenarios.

#### 2.7.2 Agent List

| Agent | Code | Responsibility | Core Tools | Receives from | Can hand off to |
|--------|------|------|----------|----------|----------|
| **Data Processing Agent** | `DataProcessor` | Understand user intent, generate/modify operators and skills, schedule execution, trace and repair | `query_table_data`, `get_table_schema`, `write_table_data`, `generate_operator`, `generate_skill`, `run_pipeline` | User chat, `DataInspector` | `DataInspector` |
| **Data Inspection Agent** | `DataInspector` | Inspect processed data for standards, quality, security; record and feed back on errors | `check_data_standards`, `check_data_quality`, `check_data_security`, `profile_data` | `DataProcessor` | `DataProcessor` |
| **Data Analysis Agent** | `DataAnalyst` | Read-only analysis: query, statistics, distribution, insights (no data modification) | `query_table_data`, `get_table_schema`, `list_user_datasources`, `execute_sql`, `kb_search` | User chat (chat_router routing) | None (no handoff) |
| *(Future expansion)* | | | | | |
| Data Governance Agent | `DataGovernor` | Data lineage tracking, metadata enrichment, data catalog management | `trace_lineage`, `enrich_metadata` | Any agent | Any agent |
| Data Security Agent | `DataSentinel` | Sensitive data identification, masking suggestions, compliance review | `detect_pii`, `suggest_masking`, `audit_compliance` | `DataInspector`, user | `DataProcessor` |

#### 2.7.3 Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Agent Runtime                                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐   Message Bus   ┌──────────────────┐                  │
│  │  DataProcessor   │ ◄──────────────►│  DataInspector   │                  │
│  │                  │                 │                  │                  │
│  │  Instr: data     │  Handoff msg    │  Instr: quality  │                  │
│  │  Tools: query/gen│ ──────────────► │  Tools: inspect  │                  │
│  │  Knowledge: ds   │  results+issues │  Knowledge: std  │                  │
│  │                  │ ◄────────────── │                  │                  │
│  └──────────────────┘                 └──────────────────┘                  │
│         ▲                                    │                               │
│         │              ┌──────────────────┐  │                               │
│         └──────────────│  AgentRegistry   │◄─┘                               │
│                        │  - discover agents│                                  │
│                        │  - route messages│                                  │
│                        │  - lifecycle mgmt│                                  │
│                        └──────────────────┘                                   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────┐        │
│  │  Shared Context                                                  │        │
│  │  - datasource_context: data source info                         │        │
│  │  - session_id                                                    │        │
│  │  - user_id                                                       │        │
│  │  - execution_history: which SQL/script produced which data       │        │
│  │  - inspection_results: issue list, severity, fix suggestions     │        │
│  └──────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────┐        │
│  │  Event Store                                                     │        │
│  │  - agent_handoff_events                                          │        │
│  │  - data_lineage_events                                           │        │
│  │  - inspection_events (issue found, fix confirmed)                │        │
│  └──────────────────────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────────────────┘
```

> **DataAnalyst Agent** (implemented): read-only analysis questions (query/stats/analysis) are routed via `chat_router` keywords to `DataAnalystAgent`, using 5 read-only tools (ANALYSIS_TOOLS), no handoff, returns results directly. DataAnalyst sits alongside DataProcessor/DataInspector; the three form the complete multi-agent architecture.

#### 2.7.4 Core Abstractions

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum


class HandoffReason(str, Enum):
    """Agent handoff reasons"""
    INSPECT_RESULT = "inspect_result"           # processing done, needs inspection
    FIX_REQUIRED = "fix_required"               # inspection found issues, needs fix
    FIX_COMPLETED = "fix_completed"             # fix done, needs re-inspection
    ESCALATE = "escalate"                       # escalate to human
    DELEGATE = "delegate"                       # delegate to another agent


@dataclass
class AgentMessage:
    """Message passed between agents"""
    from_agent: str                             # sending agent code
    to_agent: str                               # receiving agent code
    reason: HandoffReason                       # handoff reason
    payload: Dict[str, Any]                     # message content
    context: Dict[str, Any] = field(default_factory=dict)  # shared context
    trace_id: str = ""                          # trace ID
    parent_trace_id: str = ""                   # parent trace ID (for lineage)


@dataclass
class InspectionResult:
    """Data inspection result"""
    passed: bool                                # whether passed
    issues: List[Dict[str, Any]] = field(default_factory=list)  # issue list
    summary: str = ""                           # inspection summary
    severity: str = "info"                      # highest severity: info/warning/error/critical


class BaseAgent(ABC):
    """Agent base class - all agents must implement this interface"""

    name: str                                   # agent code
    display_name: str                           # display name
    description: str                            # responsibility description
    instructions: str                           # LLM system prompt
    tools: List[Dict]                           # available tool definitions

    @abstractmethod
    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        """
        Execute the agent task, streaming intermediate process and final result via SSE.

        Yields:
            {"type": "thinking", "content": "..."}    # reasoning
            {"type": "content", "content": "..."}     # reply content
            {"type": "tool_call", ...}                # tool call
            {"type": "tool_result", ...}              # tool result
            {"type": "handoff", "to": "...", "reason": "...", "payload": {...}}  # handoff
            {"type": "done", "result": {...}}         # done
        """
        pass

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build the system prompt; subclasses can override to inject dynamic context"""
        return self.instructions
```

#### 2.7.5 AgentRegistry

```python
class AgentRegistry:
    """Agent registry - manages discovery, routing, and lifecycle of all agents"""

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):
        """Register an agent"""
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        """Get an agent instance"""
        return self._agents.get(name)

    def list_agents(self) -> List[Dict]:
        """List all registered agents"""
        return [
            {"name": a.name, "display_name": a.display_name, "description": a.description}
            for a in self._agents.values()
        ]

    def find_by_capability(self, capability: str) -> List[BaseAgent]:
        """Find agents by capability (e.g., 'data_quality', 'pii_detection')"""
        return [a for a in self._agents.values() if capability in getattr(a, 'capabilities', [])]


# global registry
agent_registry = AgentRegistry()
```

#### 2.7.6 AgentRuntime

```python
class AgentRuntime:
    """Agent runtime - manages message passing, handoff, and execution flow between agents"""

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
        Run an agent, auto-handle handoffs, stream all events.

        Flow:
        1. Get the target agent
        2. Call agent.run() to get streaming output
        3. If output contains a handoff event, auto-switch to the target agent and continue
        4. Repeat until no handoff or max handoffs reached
        5. Record all events to EventStore (for lineage)
        """
        handoff_count = 0
        current_agent = self.registry.get(agent_name)
        current_message = message

        while current_agent and handoff_count < max_handoffs:
            async for event in current_agent.run(current_message, context):
                if event.get("type") == "handoff":
                    # record handoff event
                    self._event_store.record_handoff(
                        from_agent=current_agent.name,
                        to_agent=event["to"],
                        reason=event["reason"],
                        trace_id=current_message.trace_id,
                    )

                    # switch to the target agent
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
                # agent.run() ended normally, no handoff
                break
```

#### 2.7.7 DataProcessor

**Responsibility**: understand user intent, generate/modify operators and skills, schedule execution, receive inspection results and trace/repair.

**System prompt key elements**:
- Data processing expert, skilled in SQL, pandas, data cleaning and transformation
- Security red line: DataCrab cannot modify the platform itself
- Output defaults to same source
- Mandatory verification after modification
- When receiving DataInspector's inspection results, locate the root cause and repair

**Tool set**:
```python
DATA_PROCESSOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_table_data",
            "description": "Query data of a table in a data source",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_schema",
            "description": "Get table structure info",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_operator",
            "description": "Generate an operator script from a natural-language description",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_skill",
            "description": "Generate a complete skill package from a natural-language description",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "modify_script",
            "description": "Modify an operator or skill script",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_script",
            "description": "Execute an operator or skill script",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_inspector",
            "description": "Hand the processing result to the data inspection agent for quality check",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string", "description": "Data source ID"},
                    "table_name": {"type": "string", "description": "Table name to inspect"},
                    "operation_description": {"type": "string", "description": "Description of this data processing"},
                    "result_summary": {"type": "string", "description": "Processing result summary"}
                },
                "required": ["datasource_id", "table_name"]
            }
        }
    },
]
```

**Handoff triggers**:
- After data processing, auto or user-triggered handoff to `DataInspector`
- On receiving a `fix_required` handoff, locate the issue per inspection results, modify the script, re-execute

#### 2.7.8 DataInspector

**Responsibility**: perform three-dimensional inspection on processed data — standard compliance, quality assessment, security audit.

**Inspection dimensions**:

| Dimension | Check items | Example rules |
|------|--------|----------|
| **Standards** | Field naming conventions, type consistency, encoding conventions | Column names should be snake_case; date columns should be datetime |
| **Quality** | Completeness, uniqueness, range validity, business-logic consistency | Primary keys unique; numeric columns no extreme outliers; related fields logically consistent |
| **Security** | PII identification, sensitive data exposure, masking completeness | Whether phone/ID numbers are stored in plaintext; whether sensitive fields are masked |

**System prompt key elements**:
- Data quality expert, skilled in data standards, quality rules, and security audit
- When inspecting, first use `profile_data` for an overview, then targeted checks
- On finding issues, must give: description, severity, impact scope, fix suggestion
- Repaired data must be re-inspected to confirm

**Tool set**:
```python
DATA_INSPECTOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "profile_data",
            "description": "Get a data overview: row count, column count, column types, null rate, unique count, sample data",
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
            "description": "Check whether data complies with naming conventions, type standards, encoding conventions",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "standard_rules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Check rule list, e.g. ['naming_convention', 'type_consistency']"
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
            "description": "Check data quality: completeness, uniqueness, range validity, business-logic consistency",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "quality_dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Quality dimensions, e.g. ['completeness', 'uniqueness', 'validity', 'consistency']"
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
            "description": "Check data security: PII identification, sensitive data exposure, masking completeness",
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
            "description": "Hand inspection-found issues to the data processing agent for repair",
            "parameters": {
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "description": "Issue list",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string", "description": "Issue description"},
                                "severity": {"type": "string", "enum": ["warning", "error", "critical"]},
                                "column": {"type": "string", "description": "Affected column"},
                                "suggestion": {"type": "string", "description": "Fix suggestion"}
                            }
                        }
                    },
                    "summary": {"type": "string", "description": "Inspection summary"}
                },
                "required": ["issues", "summary"]
            }
        }
    },
]
```

#### 2.7.9 Typical Collaboration Flows

##### Flow 1: Data Processing + Auto Inspection

```
User: "Help me clean the relics data, remove duplicates and nulls"
      │
      ▼
┌──────────────────────────────────────────────────────────────┐
│ DataProcessor                                                │
│ 1. Understand intent: dedup + fill/drop nulls                │
│ 2. query_table_data() reads data                             │
│ 3. Generate/select cleaning operator script                  │
│ 4. run_script() executes cleaning                            │
│ 5. Done → handoff_to_inspector()                             │
│    payload: {datasource_id, table_name, "dedup and nulls done"}│
└──────────────────────────────────────────────────────────────┘
      │ Handoff(inspect_result)
      ▼
┌──────────────────────────────────────────────────────────────┐
│ DataInspector                                                │
│ 1. profile_data() data overview                              │
│ 2. check_data_standards() naming and type conventions        │
│ 3. check_data_quality() completeness, uniqueness             │
│ 4. check_data_security() sensitive data                      │
│ 5. Issues found:                                             │
│    - "era" column has 3 non-standard values (warning)        │
│    - "id" column has 2 duplicates (error)                    │
│ 6. handoff_to_processor(issues=[...], summary="2 issues")    │
└──────────────────────────────────────────────────────────────┘
      │ Handoff(fix_required)
      ▼
┌──────────────────────────────────────────────────────────────┐
│ DataProcessor                                                │
│ 1. Analyze inspection results, locate root cause             │
│ 2. modify_script() fix cleaning logic:                       │
│    - era column: add standard value mapping                  │
│    - id column: dedup logic missed a field combination       │
│ 3. run_script() re-execute                                   │
│ 4. Fix done → handoff_to_inspector() re-inspect              │
└──────────────────────────────────────────────────────────────┘
      │ Handoff(inspect_result)
      ▼
┌──────────────────────────────────────────────────────────────┐
│ DataInspector                                                │
│ 1. Re-inspect the repaired data                              │
│ 2. All checks pass                                           │
│ 3. Return InspectionResult(passed=True)                      │
└──────────────────────────────────────────────────────────────┘
      │
      ▼
User: receives inspection report + processing result
```

##### Flow 2: User-Triggered Inspection

```
User: "Help me check the data quality of the national relics table"
      │
      ▼
┌──────────────────────────────────────────────────────────────┐
│ DataProcessor (routing layer)                                │
│ 1. Recognize intent: data quality inspection                 │
│ 2. Hand off directly to DataInspector                        │
│    handoff_to_inspector(reason=delegate)                     │
└──────────────────────────────────────────────────────────────┘
      │ Handoff(delegate)
      ▼
┌──────────────────────────────────────────────────────────────┐
│ DataInspector                                                │
│ 1. profile_data() → data overview                            │
│ 2. check_data_quality(dimensions=['completeness', ...])      │
│ 3. Generate inspection report                                │
│ 4. If issues → handoff_to_processor(reason=fix_required)     │
│    No issues → return report to user                         │
└──────────────────────────────────────────────────────────────┘
```

#### 2.7.10 Inspection Tool Implementation

Inspection tools are implemented in `app/services/data_inspector.py`, analyzing data queried by ConnectorManager using pandas:

```python
class DataInspectorTools:
    """Data inspection toolset - injected into the DataInspector agent's execution sandbox"""

    async def profile_data(self, datasource_id: str, table_name: str) -> dict:
        """
        Data overview: row count, column count, column types, null rate, unique count, sample data
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
        Standards check:
        - naming_convention: whether column names follow snake_case
        - type_consistency: whether a column has consistent types across rows
        - encoding_check: whether garbled characters exist
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
                        "description": f"Column name '{col}' does not follow snake_case",
                        "suggestion": f"Suggest renaming to '{re.sub(r'([A-Z])', r'_\\1', col).lower()}'"
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
                            "description": f"Column '{col}' has mixed types ({types} kinds)",
                            "suggestion": "Suggest unifying the data type"
                        })

        return {"dimension": "standards", "passed": len(issues) == 0, "issues": issues}

    async def check_data_quality(self, datasource_id: str, table_name: str, quality_dimensions: list = None) -> dict:
        """
        Quality check:
        - completeness: completeness (null rate)
        - uniqueness: uniqueness (duplicate rate)
        - validity: validity (numeric range, date reasonableness)
        - consistency: consistency (business-logic validation)
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
                        "description": f"Column '{col}' null rate {null_rate:.1%}",
                        "suggestion": "Suggest filling default values or dropping null rows"
                    })

        if not quality_dimensions or 'uniqueness' in quality_dimensions:
            dupe_count = total - len(df.drop_duplicates())
            if dupe_count > 0:
                issues.append({
                    "dimension": "uniqueness",
                    "severity": "error",
                    "description": f"{dupe_count} fully duplicated rows exist ({dupe_count/total:.1%})",
                    "suggestion": "Suggest deduplication"
                })

        return {"dimension": "quality", "passed": len(issues) == 0, "issues": issues}

    async def check_data_security(self, datasource_id: str, table_name: str) -> dict:
        """
        Security check:
        - PII identification (phone, ID number, email, bank card)
        - Sensitive data exposure detection
        """
        issues = []
        df = await self._load_data(datasource_id, table_name)

        PII_PATTERNS = {
            "phone": r'1[3-9]\d{9}',
            "ID number": r'[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3 01])\d{3}[\dXx]',
            "email": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
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
                            "description": f"Column '{col}' suspected to contain plaintext {pii_type} ({match_count}/{len(sample)} samples matched)",
                            "suggestion": f"Suggest masking the {pii_type}"
                        })

        return {"dimension": "security", "passed": len(issues) == 0, "issues": issues}
```

#### 2.7.11 Event Store & Data Lineage

Every agent handoff and data-processing operation is recorded to the EventStore, supporting data lineage:

```python
@dataclass
class AgentEvent:
    """Agent event"""
    id: str
    trace_id: str                               # trace ID
    parent_trace_id: str                        # parent event ID
    agent_name: str                             # agent code
    event_type: str                             # handoff / tool_call / inspection / fix
    timestamp: datetime
    payload: Dict[str, Any]                     # event content


class EventStore:
    """Event store - records all agent operations, supports lineage"""

    async def record(self, event: AgentEvent):
        """Record an event"""
        pass

    async def get_trace(self, trace_id: str) -> List[AgentEvent]:
        """Get the full trace"""
        pass

    async def get_lineage(self, datasource_id: str, table_name: str) -> List[AgentEvent]:
        """Get data lineage: which operations affected this table"""
        pass
```

**Lineage scenario**: when DataInspector finds "the id column has duplicates", DataProcessor can query the EventStore via `trace_id` to find the specific operation that produced the duplicate data (which SQL, which script's which run), enabling precise root-cause location.

#### 2.7.12 Integration with Existing Modules

| Existing module | Integration |
|----------|----------|
| `agent.py` (AgentService) | Refactored into the `DataProcessor` agent, retaining existing tools and execution logic |
| `chat.py` | Conversation entry adds a routing layer: recognizes user intent then dispatches to the corresponding agent |
| `operator.py` | DataProcessor's `generate_operator`/`modify_script`/`run_script` tools call existing endpoints |
| `skill.py` | DataProcessor's `generate_skill`/`modify_script`/`run_script` tools call existing endpoints |
| `connectors.py` | Both agents read/write data via `get_connector` |
| `skill_parser.py` | DataInspector's lessons are injected into DataProcessor's prompt |
| `data_inspector.py` (new) | DataInspector agent's inspection tool implementation |

#### 2.7.13 API Endpoints

| Method | Path | Description |
|------|------|------|
| GET | /api/v1/agents | Get the list of registered agents |
| POST | /api/v1/agents/{agent_name}/run | Run a specified agent (SSE streaming) |
| POST | /api/v1/agents/inspect | Inspect a specified data source/table |
| GET | /api/v1/agents/events/{trace_id} | Get an agent execution trace |
| GET | /api/v1/agents/lineage/{datasource_id}/{table_name} | Get data lineage |

#### 2.7.14 Frontend

##### Agent Status Indicator

Show the currently active agent in the conversation interface:

```
┌──────────────────────────────────────────────────────────────┐
│  🤖 DataProcessor is processing...                           │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ User: Help me clean the relics data                    │  │
│  │                                                         │  │
│  │ [DataProcessor] Reading data source...                 │  │
│  │ [DataProcessor] Generating cleaning script...          │  │
│  │ [DataProcessor] Done, handoff to inspect ▶             │  │
│  │                                                         │  │
│  │ [DataInspector] Checking data quality...               │  │
│  │ [DataInspector] ⚠ Found 2 issues                       │  │
│  │   - era column: 3 non-standard values (warning)        │  │
│  │   - id column: 2 duplicates (error)                    │  │
│  │ [DataInspector] Handoff to fix ▶                       │  │
│  │                                                         │  │
│  │ [DataProcessor] Fixing issues...                       │  │
│  │ [DataProcessor] Fix done, handoff to re-inspect ▶      │  │
│  │                                                         │  │
│  │ [DataInspector] ✅ All checks passed                   │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

##### Data Inspection Report Page

A new "Data Inspection" page where users can actively select a data source and table to trigger inspection:

```
┌──────────────────────────────────────────────────────────────┐
│  Data Inspection                                              │
├──────────────┬───────────────────────────────────────────────┤
│ Data source: │  Result: National relics                      │
│ Table:       │                                               │
│              │  📋 Standards  ✅ Pass                         │
│ [Start]      │  📊 Quality    ⚠ 2 warnings                   │
│              │  🔒 Security   🚨 1 critical                   │
│              │                                               │
│              │  ┌─ Critical ─────────────────────────────┐   │
│              │  │ 🚨 "phone" column contains plaintext   │   │
│              │  │    phone numbers (38/100 rows)         │   │
│              │  │    Suggestion: mask                     │   │
│              │  │    [One-click fix]                      │   │
│              │  └────────────────────────────────────────┘   │
│              │  ┌─ Warnings ─────────────────────────────┐   │
│              │  │ ⚠ "era" column 3 non-standard values   │   │
│              │  │ ⚠ "protection_level" null rate 15.3%   │   │
│              │  └────────────────────────────────────────┘   │
└──────────────┴───────────────────────────────────────────────┘
```

#### 2.7.15 Implementation Roadmap

| Phase | Content | Status |
|------|------|------|
| **Phase 1** | Basic framework: BaseAgent + AgentRegistry + AgentRuntime + Handoff | ✅ Done |
| **Phase 2** | DataProcessor agent: refactor existing agent.py into DataProcessor | ✅ Done |
| **Phase 3** | DataInspector agent: implement inspection tools + system prompt | ✅ Done |
| **Phase 4** | Frontend: agent status indicator + inspection report page | ✅ Done |
| **Phase 5** | Event store and lineage | ✅ Done |
| **Phase 6** | Expansion: DataGovernor / DataSentinel and other new agents | ⬜ TODO |

#### 2.7.16 Debug Pages Integrated with Multi-Agent (Completed)

##### Background

Before the refactor, multi-agent collaboration (DataProcessor → DataInspector) was **only triggered in the main chat flow (`/chat/stream`)**. The debug assistants (debug-chat) for skills/operators/pipelines took a completely separate path: a hand-written LLM loop + regex-parsed actions + execution, bypassing the multi-agent framework.

| Entry | Before | After |
|------|--------|--------|
| Chat page | ✅ AgentRuntime → DataProcessor → DataInspector | unchanged |
| Skill debug | ❌ hand-written LLM loop | ✅ AgentRuntime → DataProcessor → DataInspector |
| Operator debug | ❌ hand-written LLM loop | ✅ AgentRuntime → DataProcessor → DataInspector |
| Pipeline debug | ❌ hand-written LLM loop | ✅ AgentRuntime → DataProcessor → DataInspector |

##### Architecture: Orchestrator-Worker Pattern

Adopts the mainstream Orchestrator-Worker pattern (same as Claude Code / OpenAI Agents SDK / Google ADK):

```
DataProcessor (Orchestrator + lightweight tools)
    ├── directly calls modify_script (Tool) — simple op, no separate LLM loop
    ├── directly calls run_script (Tool) — simple op
    ├── directly calls query_table_data / write_table_data, etc. (shared Tools)
    └── delegate → DataInspector (Worker Agent) — complex task, independent LLM loop
                     ├── profile_data
                     ├── check_data_standards
                     ├── check_data_quality
                     ├── check_data_security
                     └── handoff_back → DataProcessor to repair
```

**Granularity principle**: Agents for complex reasoning, Tools for simple operations.
- `edit_script` (line-level patch) / `run_script` (sandbox execution) are simple ops → Tool, no separate Agent needed
- Data quality inspection is complex reasoning (decide what to check, interpret results, judge severity) → Agent (Worker)
- Making simple ops into separate Workers would add 2 agent hops + 2 extra LLM calls per modify+run, doubling latency

##### Key Technique: Streaming Tool Calls + Reasoning

Before the refactor, DataProcessor used `chat_with_tools()` (non-streaming, no reasoning) and the debug assistant used `chat_stream_with_thinking()` (streaming reasoning, no tool calls). The two were incompatible.

Added `chat_stream_with_tools_and_thinking()` (`llm.py`), supporting streaming reasoning, streaming content, and tool calls:

| Capability | Source | Implementation |
|------|------|------|
| Streaming reasoning (thinking) | chat_stream_with_thinking | yield reasoning_content chunk by chunk |
| Streaming content | chat_stream_with_thinking | yield content chunk by chunk |
| Tool calls (tool_calls) | chat_with_tools | accumulate tool_call deltas, yield once after the stream ends |
| Multi-model degradation chain | simplified in Round 17 (replaces L2/L3/L4 truncation contract) | per-model attempt + CircuitBreaker (trips after 3 consecutive failures for 60s) + transient retry (429/timeout/500 exponential backoff); finish_reason=length returns directly without continuation |
| Circuit-breaker fallback + timeout guard | chat_stream_with_thinking + added in Round 8 | model failure / 120s first-chunk timeout / 60s subsequent-chunk timeout → switch to the fallback chain |

##### DataProcessor Debug Mode

DataProcessor adds a `run_debug()` method, dispatched in `run()` when `context["debug_mode"]` is detected:

| Feature | run() (main chat flow) | run_debug() (debug assistant) |
|------|-------------------|------------------------|
| LLM call | chat_with_tools() (non-streaming) | chat_stream_with_tools_and_thinking() (streaming) |
| Toolset | shared tools + handoff_to_inspector | edit_script + run_script + read_script + grep_script (4 tools, aligning with OpenCode Grep/Read/Edit/Bash) |
| system prompt | general data-processing instructions | debug-specific instructions (script content, sandbox function list, parameter memory) |
| Self-healing | handoff back-and-forth (DataInspector ↔ DataProcessor) | autonomous within the tool-call loop (run_script fails → LLM sees error → auto modify → run again) |

##### New Tools

| Tool | Type | Description |
|------|------|------|
| `edit_script` | Tool | Line-level patch to modify the script (old_string/new_string, aligning with OpenCode Edit); supports skill (file) / operator (DB) / pipeline (DB) modes |
| `run_script` | Tool | Sandbox-execute the script; skill uses subprocess, operator uses exec(), pipeline does not support direct execution; auto-hands off to DataInspector on success |
| `read_script` | Tool | Read script content (with line numbers, aligning with OpenCode Read); supports offset/limit for precise reads |
| `grep_script` | Tool | Search script content (aligning with OpenCode Grep); locates keyword line numbers |

##### Code Volume Before/After

| Endpoint | Before | After | Notes |
|------|--------|--------|------|
| `skill.py` debug-chat | ~300 lines hand-written loop | ~120 lines AgentRuntime call | -180 lines |
| `operator.py` debug-chat | ~180 lines | ~90 lines | -90 lines |
| `pipeline.py` debug-chat | ~85 lines | ~95 lines | +10 lines (added event translation) |

##### SSE Event Flow

```
user message → DataProcessor.run_debug()
    ↓
model / thinking / content (streaming reasoning + content)
    ↓
tool_calls → edit_script → script_updated event
    ↓
tool_calls → run_script → executing + run_result events
    ↓
run_script succeeds → runtime auto-handoff → agent_switch event
    ↓ (AgentRuntime auto-switch)
inspecting event → DataInspector.run()
    ↓
thinking / content / tool_result (inspection reasoning + results)
    ↓
handoff_back → agent_switch → retry event → DataProcessor repair
    ↓
done event
```

Frontend adds event handling: `inspecting` (🔍 DataInspector inspecting), `retry` (🔄 repair retry), `give_up` (⚠ cannot repair).

##### Supported Debug Types

| Type | debug_type | Script storage | Execution | modify_script | run_script |
|------|-----------|----------|----------|:---:|:---:|
| Skill | (default) | file (folder/scripts/) | subprocess sandbox | ✅ file write | ✅ skill_runner |
| Operator | "operator" | DB (Operator.script_content) | exec() sandbox | ✅ DB update | ✅ exec() + _build_operator_namespace |
| Pipeline | "pipeline" | DB (Pipeline.main_code) | direct execution not supported | ✅ DB update | ❌ returns "please use the pipeline execution feature" |

### 2.8 Scheduling System Module

#### 2.8.1 Scheduling Architecture

The scheduling system consists of `schedule.py` (API endpoints) + `task_runner.py` (background execution + scheduled scan):

```
┌───────────────────────────────────────────────┐
│               Scheduler Service               │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  Schedule Manager (schedule.py)       │   │
│   │  - Schedule config CRUD               │   │
│   │  - Pause/resume/manual trigger        │   │
│   │  - Cron expression validation         │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Task Runner (task_runner.py)         │   │
│   │  - execute_task(): dispatch by type   │   │
│   │    skill → asyncio.to_thread          │   │
│   │    operator → exec+func               │   │
│   │    pipeline → await execute_pipeline  │   │
│   │  - Update TaskExecution + Schedule    │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Scheduler Loop (task_runner.py)      │   │
│   │  - 30s interval scan next_run_at<=now │   │
│   │  - Concurrency control (concurrent)   │   │
│   │  - next_run_at recompute (dedup)      │   │
│   │  - lifespan start/stop                │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

> **Implementation**: Manual trigger (`POST /schedules/{id}/trigger`) calls `execute_task` via FastAPI `BackgroundTasks`; scheduled scanning is performed by `_scheduler_loop` started with `asyncio.create_task` at app startup, scanning due active schedules every 30 seconds. `sandbox_ns.py` provides the operator sandbox namespace (`build_operator_namespace`), shared by `task_runner` and `operator.py`.

#### 2.8.2 Schedule Configuration Model
```python
class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # Task type and target
    task_type = Column(String(20), nullable=False)  # pipeline, operator, skill
    task_target_id = Column(UUID(as_uuid=True), nullable=False)
    task_params = Column(JSON)  # execution params

    # Schedule type
    schedule_type = Column(String(20), nullable=False)  # cron, interval, manual

    # Cron config
    cron_expression = Column(String(100))
    timezone = Column(String(50), default="Asia/Shanghai")

    # Interval config (seconds)
    interval_seconds = Column(Integer)

    # Event config
    event_config = Column(JSON)

    # Execution config
    max_retries = Column(Integer, default=3)
    retry_interval = Column(Integer, default=60)
    timeout = Column(Integer, default=3600)
    concurrent_runs = Column(Integer, default=1)

    # Status
    status = Column(String(20), index=True, default="active")  # active, paused, stopped
    last_run_at = Column(DateTime)
    next_run_at = Column(DateTime)
    last_run_status = Column(String(20))

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    executions = relationship("TaskExecution", back_populates="schedule", lazy="selectin")
```

#### 2.8.3 Task Execution Model
```python
class TaskExecution(Base):
    __tablename__ = "task_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="CASCADE"), index=True)

    # Task info
    task_type = Column(String(20), nullable=False)  # pipeline, operator, skill
    task_target_id = Column(UUID(as_uuid=True), nullable=False)

    # Execution info
    status = Column(String(20), nullable=False, index=True)  # pending, running, success, failed, timeout
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration = Column(Integer)  # seconds

    # Execution result
    result = Column(JSON)
    error_message = Column(Text)
    exit_code = Column(Integer)

    # Retry info
    retry_count = Column(Integer, default=0)

    # Execution logs
    logs = Column(Text)

    # Lineage
    input_data = Column(JSON)
    output_data = Column(JSON)

    # Trigger type
    trigger_type = Column(String(20), default="schedule")  # schedule, manual, event
    triggered_by = Column(UUID(as_uuid=True))

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    schedule = relationship("Schedule", back_populates="executions")
```

### 2.9 Metadata Management Module

#### 2.9.1 Design Goals

Establish a unified metadata center for all datasets (tables/files in data sources) on the platform, divided into **technical metadata** and **business metadata**, supporting:
- One-click auto-sync of technical metadata when configuring a data source
- Business metadata auto-enriched via LLM analysis of data samples; also supports manual editing
- Full-lifecycle metadata management: collection → storage → enrichment → query → lineage tracking

#### 2.9.2 Metadata Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Metadata Manager                             │
├──────────────────┬──────────────────┬───────────────────────────┤
│  Technical       │  Business        │  Operational              │
├──────────────────┼──────────────────┼───────────────────────────┤
│ · Dataset ID     │ · Source system  │ · Last access time        │
│ · Dataset name   │ · Business desc  │ · Access count            │
│ · Dataset type   │ · Business tags  │ · Last sync time          │
│ · Dataset format │ · Business use   │ · Data change records     │
│ · Storage loc    │ · Data domain    │ · Quality score           │
│ · Schema         │ · Data owner     │ · Quality rules           │
│ · Row count est  │ · Security level │ · Data lineage            │
│ · Field stats    │ · Retention pol  │                           │
│ · Partition info │                  │                           │
├──────────────────┼──────────────────┼───────────────────────────┤
│  ← Auto sync     │  ← AI + manual   │  ← Auto collect           │
│  (Connector)     │  (LLM samples)   │  (runtime records)        │
└──────────────────┴──────────────────┴───────────────────────────┘
```

#### 2.9.3 Metadata Data Model

```python
class TableMetadata(Base):
    """Dataset metadata model (one data source's one table/file = one metadata record)"""
    __tablename__ = "table_metadata"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    data_source_id = Column(UUID, ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)

    # ========== Technical metadata ==========
    # Basic info
    table_name = Column(String(200), nullable=False)          # dataset name (table/file/sheet)
    table_type = Column(String(50))                           # dataset type: table, view, sheet, file
    storage_format = Column(String(50))                       # format: csv, excel, parquet, mysql, postgres...
    storage_location = Column(String(500))                    # storage loc: file path / DB host:port/db
    source_connector = Column(String(50))                     # source connector type

    # Schema definition
    table_schema = Column(JSON)                               # schema: [{"name": "col", "dtype": "VARCHAR(255)", "nullable": true, "description": "..."}]
    primary_keys = Column(JSON)                               # primary key columns
    indexes = Column(JSON)                                    # index info

    # Data volume stats
    row_count = Column(BigInteger)                            # row count (estimated/actual)
    size_bytes = Column(BigInteger)                           # storage size (bytes)
    column_count = Column(Integer)                            # column count
    sample_data = Column(JSON)                                # sample data (first 5 rows, for AI analysis)
    column_stats = Column(JSON)                               # field stats: {"col": {"min":.., "max":.., "null_rate":.., "unique_count":..}}

    # Partitions (for big data sources)
    partition_info = Column(JSON)                             # partition info

    # ========== Business metadata ==========
    business_name = Column(String(200))                      # business name
    business_description = Column(Text)                      # business description
    business_tags = Column(JSON)                             # business tags (multiple)
    business_purpose = Column(Text)                           # business purpose
    source_system = Column(String(200))                      # source business system
    data_domain = Column(String(100))                        # data domain
    data_owner = Column(String(100))                         # data owner (dept/person)
    data_steward = Column(String(100))                       # data steward

    # Security & compliance
    security_level = Column(String(20))                      # security level: public, internal, confidential, secret
    retention_policy = Column(String(200))                   # retention policy

    # ========== Operational metadata ==========
    last_synced_at = Column(DateTime)                        # last technical metadata sync time
    last_accessed_at = Column(DateTime)                      # last access time
    access_count = Column(Integer, default=0)                # access count

    # Data quality
    quality_rules = Column(JSON)                             # quality rules
    quality_score = Column(Float)                            # quality score (0-100)
    quality_details = Column(JSON)                           # quality details

    # Data lineage
    lineage = Column(JSON)                                   # lineage: {"upstream": [...], "downstream": [...]}

    # AI-enriched metadata
    ai_enriched = Column(Boolean, default=False)             # whether AI-enriched business metadata
    ai_enriched_at = Column(DateTime)                        # AI enrichment time

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    data_source = relationship("DataSource", back_populates="table_metadata")
```

#### 2.9.4 Technical Metadata Auto-Sync

When creating/editing a data source, users can choose "Sync technical metadata"; the system auto-extracts technical metadata for all tables via the Connector.

```python
# Sync option on data source create/edit
class DataSourceSyncRequest(BaseModel):
    sync_technical_metadata: bool = True     # whether to sync technical metadata
    sample_rows: int = 5                     # sample rows (for AI analysis and preview)
    max_tables: int = 100                    # max tables to sync

# Sync flow
async def sync_technical_metadata(datasource: DataSource, db: AsyncSession):
    """
    1. Get all tables/files of the data source via the Connector
    2. For each table extract technical metadata:
       a. connector.get_schema() → table structure, field types
       b. connector.get_table_stats() → row count, size
       c. connector.get_table_data(table, page=1, page_size=5) → sample data
       d. compute field stats (null rate, unique count, min/max)
    3. Write/update the table_metadata table
    4. Mark last_synced_at
    """
    connector = get_connector(datasource.type, datasource.connection_config)
    try:
        schema_list = await connector.get_schema()          # all tables/sheets

        for table_info in schema_list:
            table_name = table_info["table_name"]

            # Extract table structure
            df_sample = await connector.get_table_data(table_name, page=1, page_size=5)
            stats = await connector.get_table_stats(table_name)

            # Compute field stats
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

            # Infer storage format
            storage_format = datasource.type  # mysql, excel, csv...

            # Infer storage location
            if datasource.type in ("csv", "excel"):
                storage_location = datasource.connection_config.get("file_path", "")
            elif datasource.type in ("mysql", "postgres"):
                cfg = datasource.connection_config
                storage_location = f"{cfg.get('host')}:{cfg.get('port')}/{cfg.get('database')}"
            else:
                storage_location = str(datasource.connection_config)

            # Write or update (preserve existing business metadata; only update technical)
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

**Sync timing:**
- On data source creation: user checks "Sync technical metadata" (checked by default)
- On data source edit: user manually triggers "Re-sync"
- Scheduled task: optionally configure scheduled sync (e.g., daily at midnight)

#### 2.9.5 Business Metadata AI Enrichment

Auto-generate business metadata suggestions via the LLM analyzing sample data and existing technical metadata.

```python
class BusinessMetadataAIRequest(BaseModel):
    table_metadata_id: UUID
    force_refresh: bool = False       # whether to force regenerate

async def enrich_business_metadata(meta: TableMetadata, db: AsyncSession):
    """
    Enrich business metadata via LLM analysis of sample data:
    1. Assemble technical metadata + sample data into a prompt
    2. LLM infers business name, description, tags, purpose, data domain
    3. After user confirmation, write to business metadata fields
    """
    prompt = f"""Analyze the following dataset's technical info and sample data; infer business metadata.

## Technical Info
- Data source name: {meta.data_source.name if meta.data_source else 'unknown'}
- Dataset name: {meta.table_name}
- Storage format: {meta.storage_format}
- Field structure: {json.dumps(meta.table_schema, ensure_ascii=False)}
- Row count: {meta.row_count}
- Field stats: {json.dumps(meta.column_stats, ensure_ascii=False)}

## Sample data (first 5 rows)
{json.dumps(meta.sample_data, ensure_ascii=False, default=str)}

## Output business metadata in JSON
{{
    "business_name": "business name of the dataset",
    "business_description": "one paragraph describing what data this dataset contains and its characteristics",
    "business_tags": ["tag1", "tag2", "tag3"],
    "business_purpose": "possible business use of this dataset",
    "source_system": "business system that may produce this data",
    "data_domain": "data domain classification",
    "security_level": "public/internal/confidential/secret"
}}

Output JSON only, no explanation."""

    result = await llm_manager.chat_with_messages(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=500,
    )

    # Parse LLM output and write
    parsed = json.loads(result.strip().strip("```json").strip("```"))
    for key, value in parsed.items():
        setattr(meta, key, value)
    meta.ai_enriched = True
    meta.ai_enriched_at = datetime.utcnow()
    await db.flush()
```

#### 2.9.6 API Design

```
# Technical metadata sync
POST   /api/v1/datasources/{id}/sync-metadata        # trigger technical metadata sync
GET    /api/v1/datasources/{id}/metadata              # get metadata of all tables under a data source

# Metadata CRUD
GET    /api/v1/metadata                                # metadata list (filter/search/paginate)
GET    /api/v1/metadata/{table_metadata_id}            # metadata detail
PUT    /api/v1/metadata/{table_metadata_id}            # edit metadata (mainly business metadata)

# Business metadata AI enrichment
POST   /api/v1/metadata/{table_metadata_id}/ai-enrich  # AI enrich business metadata

# Metadata search
GET    /api/v1/metadata/search?q=relics&tag=heritage   # search by name/description/tags

# Metadata stats
GET    /api/v1/metadata/stats                          # metadata statistical overview
```

#### 2.9.7 Frontend Page Design

```
┌─────────────────────────────────────────────────────────────────┐
│  Metadata Management                                            │
├──────────┬──────────────────────────────────────────────────────┤
│ Filters  │  Metadata list                                       │
│          │  ┌────────────────────────────────────────────────┐  │
│ Source▼  │  │ ☑ National relics | excel | 988 rows × 5 cols │  │
│ Domain▼  │  │   🏷 relics,heritage | Business: National list│  │
│ Tags▼    │  │   📊 Quality: 98 | 🕐 Sync: 2024-01-15        │  │
│          │  ├────────────────────────────────────────────────┤  │
│ Search   │  │ ☑ Sales detail   | mysql | 50000 rows × 12 cols│  │
│ [Search] │  │   🏷 sales,finance | Business: Sales orders    │  │
│          │  │   📊 Quality: 85 | 🕐 Sync: 2024-01-14        │  │
│          │  └────────────────────────────────────────────────┘  │
├──────────┴──────────────────────────────────────────────────────┤
│  Metadata detail (click a list item to expand)                  │
│  ┌──────────────────────┬─────────────────────────────────────┐ │
│  │ Technical            │ Business                            │ │
│  │ Name: National relics│ Business name: [National list____]  │ │
│  │ Type: excel/sheet    │ Description: [National relics______]│ │
│  │ Format: excel        │ Tags: [relics][heritage][+]         │ │
│  │ Loc: D:\wenwu\...    │ Purpose: [relics analysis__________]│ │
│  │ Rows: 988            │ Source system: [Admin of relics___] │ │
│  │ Cols: 5              │ Domain: [relics ▼]                  │ │
│  │                      │ Security: [internal ▼]              │ │
│  │ Fields:              │                                     │ │
│  │ ┌col─type─null─desc─┐│ [AI Enrich] [Save]                  │ │
│  │ │name str ✗ ___     ││                                     │ │
│  │ │era  str ✗ ___     ││                                     │ │
│  │ └───────────────────┘│                                     │ │
│  │ [Re-sync technical]  │                                     │ │
│  └──────────────────────┴─────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.9.8 Metadata Applications in the Platform

| Scenario | Description |
|---------|------|
| **Conversation context** | chat.py's `build_datasource_context` reads metadata to provide table structure, business meaning, data domain context to the LLM |
| **Skill/operator generation** | skill_creator / operator SYSTEM_PROMPT injects metadata so the LLM understands data structure before generating scripts |
| **Data catalog** | The frontend metadata page serves as a data catalog for browsing and searching all datasets |
| **Data lineage** | Records input/output relationships of data-processing flows to trace data origins |
| **Data quality monitoring** | Auto-detects data quality issues based on quality rules; computes quality scores |
| **Data security** | Controls data access permissions by security level |

#### 2.9.9 Integration with the Data Source Module

Add a "Sync technical metadata" option in the data source create/edit flow:

```
Data source creation flow:
1. User fills connection config → test connection
2. Check "Sync technical metadata" (checked by default)
3. System auto:
   a. Get all table/sheet list
   b. Per table extract schema, row count, sample data
   c. Write to the table_metadata table
4. Creation done → jump to the metadata management page
5. User can click "AI enrich business metadata" to let the LLM analyze and fill business fields
6. User can manually edit business metadata
```

Add a "Re-sync" button in the data source edit flow; clicking it re-extracts technical metadata (preserving existing business metadata).

### 2.10 Permission Management Module

#### 2.10.1 RBAC Permission Model
```python
class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    # User info
    display_name = Column(String(100))
    avatar = Column(String(500))
    
    # Status
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)

class Role(Base):
    __tablename__ = "roles"
    
    id = Column(UUID, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100))
    description = Column(Text)
    
    # Permission list
    permissions = Column(JSON)  # ["code:view", "operator:use", "schedule:manage"]
    
    created_at = Column(DateTime, default=datetime.utcnow)

class Permission(Base):
    __tablename__ = "permissions"
    
    id = Column(UUID, primary_key=True)
    resource_type = Column(String(50))  # code, operator, datasource, schedule
    resource_id = Column(UUID)
    user_id = Column(UUID, ForeignKey("users.id"))
    role_id = Column(UUID, ForeignKey("roles.id"))
    
    # Permission level
    permission_level = Column(String(20))  # view, use, manage
    
    created_at = Column(DateTime, default=datetime.utcnow)
```

#### 2.10.2 Permission Check Logic
```python
class PermissionChecker:
    """Permission checker"""
    
    async def check_permission(
        self,
        user: User,
        resource_type: str,
        resource_id: UUID,
        required_level: str  # view, use, manage
    ) -> bool:
        """Check permission"""
        
        # Superuser has all permissions
        if user.is_superuser:
            return True
        
        # Query user permissions
        permissions = await self.get_user_permissions(
            user.id, 
            resource_type, 
            resource_id
        )
        
        # Permission level mapping
        level_map = {"view": 1, "use": 2, "manage": 3}
        
        # Check permission
        for perm in permissions:
            if level_map[perm.permission_level] >= level_map[required_level]:
                return True
        
        return False
```

### 2.11 Data Standards / Quality / Security Rule Libraries

Three Markdown rule libraries serve as DataInspector's inspection basis, viewable/editable on the system settings page.

**Storage**:
- Defaults (shipped read-only): `backend/app/defaults/data_standards.md`, `data_quality_rules.md`, `data_security_rules.md`
- Runtime editable copies: `backend/data/standards/` (copied from defaults on first GET)

**Libraries**:
| Library | ID | Content |
|--------|------|------|
| Data Standards | STD-xxx | Field-level format regex & constraints: ID card (checksum)/USCC/bank card (Luhn)/phone/email/address/zip/IP/date/amount/age/enum/relics-era, etc. |
| Data Quality | DQ-xxx | DAMA 6 dimensions (completeness/uniqueness/validity/consistency/accuracy/timeliness) + ETL process quality (no volume growth/reconciliation: row-count·amount·group-sum/search ≤ total/null rate/PK uniqueness) + business rules |
| Data Security | SEC-xxx | PII detection / credential leak (password·API key·private key·conn string) / sensitive business data (salary·medical·minor) / data classification / masking / compliance retention |

**API**: `GET/PUT /api/v1/config/data-standards|data-quality|data-security`, `POST .../reset`

**Parsing & execution** (`app/services/standards_parser.py`):
- `parse_standards()` / `parse_quality_rules()` / `parse_security_rules()` parse MD into structured rules
- DataInspector `build_system_prompt` injects all three libraries
- `inspector_tools` executes deterministically: standard format via regex (`match_columns`), security via regex scan, quality via aggregation; each issue tagged with `standard_id` (STD) / `rule_id` (DQ/SEC) + severity + fix suggestion
- Semantic checks (business logic, cross-table consistency) by LLM

## 3. Database Design
### 3.1 Core Table Structure
#### User & Permission Tables
```sql
-- Users table
CREATE TABLE users (
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

-- Roles table
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    permissions JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User-role association table
CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- Permissions table
CREATE TABLE permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_type VARCHAR(50) NOT NULL,
    resource_id UUID NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    permission_level VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Data Source Tables
```sql
-- Data sources table
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

-- Table metadata
CREATE TABLE table_metadata (
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

#### Operator & Pipeline Tables
```sql
-- Operators table
CREATE TABLE operators (
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

-- Pipelines table (replaces the deprecated composed_codes table)
-- Pipeline data is stored in the pipelines table (see the "Pipeline Tables" section below)
```

#### Skills Table
```sql
-- Skills table (note: the actual implementation is simplified; inputs/outputs/parameters/executor_config/usage_examples are stored in the SKILL.md file, not the DB)
CREATE TABLE skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200),
    description TEXT NOT NULL,
    skill_type VARCHAR(50), -- operator, function, pipeline
    inputs JSONB,
    outputs JSONB,
    parameters JSONB,
    executor_config JSONB,
    usage_examples JSONB,
    tags JSONB,
    category VARCHAR(50),
    version VARCHAR(20) DEFAULT '1.0.0',
    author UUID REFERENCES users(id),
    visibility VARCHAR(20), -- private, public, shared
    permissions JSONB,
    usage_count INTEGER DEFAULT 0,
    success_rate FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Skill version history table
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
```

#### Pipeline Tables
```sql
CREATE TABLE pipelines (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200),
    description TEXT,

    -- Python main function source
    main_code TEXT NOT NULL,

    -- Main function signature
    entry_function VARCHAR(100) DEFAULT 'main',
    parameters JSON,

    -- Call relationships (which Skill scripts the main function calls)
    skill_calls JSON,

    -- Source
    source_skill_id UUID,

    -- Metadata
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

#### Schedule & Execution Tables
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

#### Data Source Management API
```
POST   /api/v1/datasources              # Create data source
GET    /api/v1/datasources              # Get data source list
GET    /api/v1/datasources/{id}         # Get data source detail
PUT    /api/v1/datasources/{id}         # Update data source
DELETE /api/v1/datasources/{id}         # Delete data source
POST   /api/v1/datasources/{id}/test    # Test connection
GET    /api/v1/datasources/{id}/schema  # Get data source schema
```

#### Operator Management API
```
POST   /api/v1/operators                # Create operator
GET    /api/v1/operators                # Get operator list
GET    /api/v1/operators/{id}           # Get operator detail
PUT    /api/v1/operators/{id}           # Update operator
DELETE /api/v1/operators/{id}           # Delete operator
GET    /api/v1/operators/categories     # Get operator categories
```

#### Schedule Management API
```
POST   /api/v1/schedules                # Create schedule
GET    /api/v1/schedules                # Get schedule list
GET    /api/v1/schedules/{id}           # Get schedule detail
PUT    /api/v1/schedules/{id}           # Update schedule
DELETE /api/v1/schedules/{id}           # Delete schedule
POST   /api/v1/schedules/{id}/pause     # Pause schedule
POST   /api/v1/schedules/{id}/resume    # Resume schedule
POST   /api/v1/schedules/{id}/trigger   # Manual trigger (BackgroundTasks)
GET    /api/v1/schedules/{id}/executions # Get execution history
GET    /api/v1/schedules/executions/{exec_id} # Get execution detail
POST   /api/v1/schedules/validate-cron  # Cron expression validation
GET    /api/v1/schedules/stats/overview # Schedule stats overview
```

#### Skill Management API
```
# Skill CRUD
POST   /api/v1/skills                    # Create skill
GET    /api/v1/skills                    # Get skill list
GET    /api/v1/skills/{id}               # Get skill detail
PUT    /api/v1/skills/{id}               # Update skill
DELETE /api/v1/skills/{id}               # Delete skill
# Skill operations
POST   /api/v1/skills/{id}/execute       # Execute a single skill
POST   /api/v1/skills/{id}/test          # Test skill execution
GET    /api/v1/skills/{id}/versions      # Get skill version history
POST   /api/v1/skills/{id}/rollback      # Roll back skill version
POST   /api/v1/skills/{id}/validate      # Validate skill definition
# Skill publishing
GET    /api/v1/skills/categories         # Get skill categories
GET    /api/v1/skills/search             # Search skills
POST   /api/v1/skills/recommend          # Recommend related skills
# Skill conversion
POST   /api/v1/skills/from-operator      # Create skill from operator
POST   /api/v1/skills/from-code          # Create skill from code
POST   /api/v1/skills/from-nl            # Create skill from natural language
# Skill templates
GET    /api/v1/skills/templates          # Get skill template list
POST   /api/v1/skills/templates/{id}/apply # Apply a skill template
```

#### Skill & Pipeline API Detailed Description

##### Create Skill
```json
POST /api/v1/skills
Request:
{
    "name": "filter_rows",
    "display_name": "Data Filter",
    "description": "Filter data by condition",
    "skill_type": "operator",
    "inputs": {
        "data": {
            "type": "DataFrame",
            "description": "Input data",
            "required": true
        }
    },
    "outputs": {
        "result": {
            "type": "DataFrame",
            "description": "Filtered data"
        }
    },
    "parameters": {
        "condition": {
            "type": "str",
            "description": "Filter condition expression",
            "required": true
        }
    },
    "executor_config": {
        "type": "python_function",
        "module": "app.skills.operators",
        "function": "filter_operator"
    },
    "usage_examples": [
        "Filter users older than 18",
        "Filter orders with sales over 1000"
    ],
    "tags": ["filter", "data cleaning"],
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

##### Create Skill from Natural Language
```json
POST /api/v1/skills/from-nl
Request:
{
    "description": "Create a skill to compute mean, max, min, and std deviation of data",
    "user_id": "uuid"
}

Response:
{
    "skill": {
        "id": "uuid",
        "name": "calculate_statistics",
        "display_name": "Statistical Analysis",
        "description": "Compute statistical metrics of data",
        "skill_type": "operator",
        "inputs": {...},
        "outputs": {...},
        "parameters": {...}
    },
    "generated_code": "def calculate_statistics(data, columns=None): ...",
    "validation_passed": true
}
```

## 5. Deployment Architecture

### 5.1 Single-Machine Deployment
```
┌───────────────────────────────────────────────┐
│               Local dev / production          │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  Frontend (Vite Dev / Nginx)          │   │
│   │  - Vue 3 SPA                          │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Backend (uvicorn)                    │   │
│   │  - FastAPI app                        │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  SQLite / PostgreSQL                  │   │
│   │  - Business data                      │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Local file system                    │   │
│   │  - Data source files / skill packages │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

### 5.2 Docker Compose Config (Optional)

> Production can use Docker Compose; for development, `npm run dev` is enough (see INSTALL.md).

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

## 6. Security Design

### 6.1 Operation Boundary (Core Security Principle)

**DataCrab cannot modify the platform itself, but can help users create and modify their own conversations, operators, and skills.**

| Category | Description | Modifiable |
|------|------|----------|
| DataCrab platform itself | Source code, config, users/roles/permissions, system tables, infrastructure | ❌ Forbidden |
| User-defined conversations | Sessions and messages created by the user | ✅ Allowed |
| User-defined operators | Operator scripts created by the user | ✅ Allowed |
| User-defined skills | Skill packages and scripts created by the user | ✅ Allowed |
| User's business data | Business data in data sources | ✅ Allowed |

This rule is written into:
- soul.md (highest-priority behavior rule)
- chat.py _build_system_prompt (conversation prompt)
- operator.py SYSTEM_PROMPT (operator prompt)
- skill.py debug-assistant/modify prompt (skill prompt)
- skill_creator.py SKILL_CREATOR_SYSTEM_PROMPT (skill creation prompt)
- pipeline_builder.py PIPELINE_BUILDER_SYSTEM_PROMPT (pipeline prompt)

### 6.2 Data Security
- **Transport encryption**: HTTPS/TLS encrypted transport
- **Storage encryption**: sensitive data encrypted at rest
- **Data masking**: sensitive fields masked in display
- **Security classification**: data security-level classification

### 6.3 Security Protection
- **SQL injection protection**: parameterized queries
- **XSS protection**: input/output escaping
- **CSRF protection**: CSRF token verification
- **Rate limiting**: API access rate limiting

## 7. Monitoring & Operations
### 7.1 Monitoring Metrics
- **System metrics**: CPU, memory, disk, network
- **App metrics**: request volume, response time, error rate
- **Business metrics**: pipeline execution count, success rate, failure rate

### 7.2 Log Management
- **App logs**: application runtime logs
- **Access logs**: API access logs
- **Audit logs**: user operation audit logs
- **Execution logs**: pipeline execution logs

### 7.3 Alerting
- **System alerts**: resource usage alerts
- **App alerts**: service exception alerts
- **Business alerts**: task failure alerts

## 8. Extensibility Design
### 8.1 Plugin Mechanism
- **Data source plugins**: support custom data source connectors
- **Operator plugins**: support custom operator development
- **Auth plugins**: support custom auth methods
- **Storage plugins**: support custom storage backends
### 8.2 Horizontal Scaling
- **Stateless services**: API services are stateless
- **Load balancing**: supports multi-instance load balancing
- **Async tasks**: asyncio coroutines + subprocess sandbox execution
- **Database sharding**: supports database sharding scaling

## 9. Development Standards
### 9.1 Code Standards
- **Python**: PEP 8 + Black formatting
- **TypeScript**: ESLint + Prettier
- **Git commits**: Conventional Commits (Chinese description, feat:/fix: prefix)
- **Code review**: Pull Request review mechanism

### 9.2 Testing Standards
- **Unit tests**: pytest + unittest
- **Integration tests**: pytest-asyncio
- **E2E tests**: Playwright
- **Coverage**: > 80%

### 9.3 Documentation Standards
- **API docs**: OpenAPI/Swagger
- **Code docs**: Docstring
- **User docs**: Markdown
- **Deployment docs**: Docker Compose

## 10. Technical Risks & Mitigations

### 10.1 Performance Risk
- **Risk**: large-data-volume processing performance issues
- **Mitigation**: batch processing, stream processing, async execution
### 10.2 Reliability Risk
- **Risk**: task execution failure
- **Mitigation**: retry mechanism, transaction rollback, state recovery
### 10.3 Security Risk
- **Risk**: data leakage, malicious attacks
- **Mitigation**: encrypted storage, access control, security audit
### 10.4 Extensibility Risk
- **Risk**: difficulty scaling the system
- **Mitigation**: modular design, plugin mechanism, microservice architecture

## 11. Engineering Improvement Records (inspired by DeepAnalyze)

This section records engineering improvements made to DataCrab after drawing on the design ideas of DeepAnalyze, a general-purpose Agent platform. Each improvement notes the corresponding file and the design-philosophy source.

### 11.1 Tool System Improvements

#### Tool Deduplication (shared_tools.py)
- **Problem**: `agent.py` and `data_processor_agent.py` had 5 tools whose schema and implementation were fully copy-pasted
- **Improvement**: extracted `shared_tools.py`, unifying the schema + implementation of 7 shared tools; both Agents import it
- **Philosophy**: inspired by DeepAnalyze's ToolRegistry unified-management idea

#### Tool Result Truncation (agent_utils.py → truncate_tool_result)
- **Problem**: `query_table_data` returned 100 rows of full JSON by default, bloating context over multiple rounds
- **Improvement**: when a tool's returned JSON exceeds 8000 chars, auto-truncate to the first 5 rows + column names + total row count + a truncation notice
- **Philosophy**: inspired by DeepAnalyze's Micro-Compact strategy

#### Tool Honesty Capability Table (tool_guidance.py)
- **Problem**: tool descriptions only said what they could do, not what they couldn't, leading to model misuse
- **Improvement**: annotated each tool with coverage/precision/known limitations and injected the capability table into the system prompt
- **Philosophy**: inspired by DeepAnalyze's "tool honesty" principle—write tool weaknesses truthfully so the model can compose tools correctly

### 11.2 Agent Loop Improvements

#### Stuck Detection (agent_utils.py → StuckDetector)
- **Problem**: the Agent loop had only a hard `MAX_AGENT_ITERATIONS=12` cap, with no detection of going in circles
- **Improvement**: detect repeated calls (2 consecutive rounds with the same tool+args) and idling (3 consecutive rounds with no tool call), injecting a strategy-switch hint
- **Philosophy**: inspired by DeepAnalyze's StuckDetector (four stuck modes; DataCrab adopts two)

#### Anti-Hallucination Checks (agent_utils.py → is_planning_only / should_warn_ungrounded_claim)
- **Problem**: the Agent might "only plan without executing" or emit data claims unsupported by tools (a past "AI fabricates data" bug)
- **Improvement**:
  - before finishing, check whether the output is merely planning text ("I will... then..."); if so, refuse to end
  - tool results carry a `_source` origin marker (datasource:xxx/table:yyy)
- **Philosophy**: inspired by DeepAnalyze's "prevent plan-only" and zero-hallucination six-layer defense

#### Handoff Convergence Detection (data_harness.py → ConvergenceGuard)
- **Problem**: processor↔inspector could ping-pong the same issue, wasting 10×12=120 API calls
- **Improvement**: `ConvergenceGuard` non-intrusive component; `record()` logs handoff signatures (to_agent, datasource_id, table_name), `is_diverged()` terminates after 4 consecutive back-and-forths on the same table; multi_agent.py calls only 3 lines instead of inline signature tracking
- **Philosophy**: inspired by DeepAnalyze's convergence-detection idea; the flow-layer Harness is non-intrusive, business code is unaware of detection details

### 11.3 Context Management Improvements

#### CJK-aware Token Estimation (agent_utils.py → estimate_tokens)
- **Problem**: `_compress_history` used character count (`len()`) as the trigger, with large error in Chinese scenarios
- **Improvement**: estimate tokens as CJK chars ×1.5, non-ASCII ×0.5, ASCII ×0.25
- **Philosophy**: inspired by DeepAnalyze's CJK-aware token estimation

#### Compression Identifier Protection (agent_utils.py → extract_identifiers / build_identifier_hint)
- **Problem**: after history summarization the Agent forgot which tables/datasources it had queried and repeated searches
- **Improvement**: mechanically extract UUIDs/table names/datasource IDs during compression and require the summary prompt to preserve these identifiers
- **Philosophy**: inspired by DeepAnalyze's identifier-protection principle

### 11.4 LLM Call Improvements

#### Transient Retries (llm.py → _acreate_with_retry)
- **Problem**: 429 rate-limit/network timeout directly switched models without retrying the same model; tenacity was declared but unused
- **Improvement**: up to 2 exponential-backoff retries (2s→4s) for RateLimitError/APITimeoutError/APIConnectionError/InternalServerError, then fall back through the model chain after retries are exhausted
- **Philosophy**: inspired by DeepAnalyze's four-level error-recovery chain, first level

### 11.5 Routing Improvements

#### Unified Routing + Agent-autonomous Handoff (chat.py)
- **Problem**: `_route_to_agent` pre-judged routing via keyword matching ("check/quality"→inspector), misjudging edge cases
- **Improvement**: always start from DataProcessorAgent; the Agent autonomously decides whether to hand off to inspector; `_route_to_agent` was deleted
- **Philosophy**: inspired by DeepAnalyze's "Agent autonomy" principle—the system gives signals, not constraints

### 11.6 Experience Library Improvements

#### Cross-operator Experience Aggregation (experience.py → distill_cross_patterns)
- **Problem**: experience accumulated per operator/skill independently, lacking cross-operator general-pattern discovery
- **Improvement**: `distill_cross_patterns()` collects all operators'/skills' lessons and uses the LLM to distill general data-processing patterns, stored in `global_lessons.md`
- **Philosophy**: inspired by DeepAnalyze's AutoDream cross-session experience integration

### 11.7 Engineering Hygiene

#### Test Coverage (tests/)
- **Problem**: `backend/tests/` was completely empty, zero coverage
- **Improvement**: wrote unit tests for the pure functions of `agent_utils.py`, `experience.py`, `shared_tools.py` (64 test cases)
- **Coverage**: token estimation, result truncation, stuck detection, identifier extraction, anti-hallucination checks, dynamic turn budget, context pressure alerts, three-level anti-hallucination, search saturation detection, tool result cache, experience read/write, tool schema validation

#### Cleaning Unused Dependencies (pyproject.toml)
- **Problem**: `redis`, `celery`, `minio`, `elasticsearch` were declared but unused in code
- **Improvement**: removed the 4 unused dependencies from `pyproject.toml`

#### AGENTS.md
- **Problem**: the project had no AI-collaboration config file
- **Improvement**: created `AGENTS.md` recording the tech stack, key-file navigation, run commands, and coding standards

### 11.8 New File List

| File | Description |
|------|------|
| `backend/app/services/agent_utils.py` | Agent engineering utility functions (token estimation, truncation, stuck detection, identifier extraction, anti-hallucination, dynamic turn budget, context pressure alerts, three-level anti-hallucination, search saturation detection, tool result cache) |
| `backend/app/services/shared_tools.py` | unified schema + implementation of 7 shared tools (with LRU cache) |
| `backend/app/services/tool_guidance.py` | tool honesty capability table |
| `backend/tests/test_agent_utils.py` | agent_utils unit tests |
| `backend/tests/test_experience.py` | experience unit tests |
| `backend/tests/test_shared_tools.py` | shared_tools + tool_guidance unit tests |
| `AGENTS.md` | project-level AI collaboration config |

### 11.9 Reasoning Truncation Fix

#### Problem
The AI reasoning process (thinking) of the skill/operator/pipeline debug assistant was truncated; users saw reasoning cut off mid-way.

#### Root Cause
The round-4 "prevent infinitely long reasoning chains" optimization introduced two issues:
1. `llm.py:544` escalation-recovery condition included a `not has_content` guard—when reasoning was long but had some content, it **did not escalate-retry**, leaving reasoning cut off
2. `max_tokens=4000` was too tight for reasoning models like GLM-5.2 (reasoning + content share the budget)
3. the `clear_thinking` event cleared only reasoning, not content—even after escalation-retry the content repeated

#### Improvement
| File | Change |
|------|------|
| `llm.py:544` | removed the `not has_content` guard; any `finish_reason=length` escalates-retries (4K→8K→16K) |
| `skill.py:1158` | debug-chat `max_tokens` 4000→8000, giving reasoning models enough budget |
| `SkillView.vue` / `OperatorView.vue` / `PipelineView.vue` | `clear_thinking` also clears `content` + resets `thinkingDone`, preventing content repetition on retry |

### 11.10 debug-chat `{{}}` Bug Fix

#### Problem
After the skill debug assistant's AI modified the script, the `script_updated` event didn't fire, the script wasn't written back to disk, and it reported `unhashable type: 'dict'`.

#### Root Cause
`skill.py:1186-1194` had an f-string escape residue: `{{}}` was actually `{ {} }` (a set containing an empty dict), which raised `TypeError: unhashable type: 'dict'` at runtime. This line executed before modify_script processing, so the AI's modified code was never written back to disk.

#### Improvement
`skill.py`: `{{}}` → `{}`, `{{"action": "run", ...}}` → `{"action": "run", ...}` (3 places)

### 11.11 Execution Parameter Memory

#### Problem
In the skill debug assistant, the user said "the ID and timestamp weren't written in" (without naming a datasource); after the AI modified the script, the run action passed empty params `{}`, and the skill reported "missing required migration parameter". The experience library `experience.json` recorded successful params in `positive` but **never fed them back to the AI**.

#### Root Cause
DataCrab's debug-assistant memory has 4 layers, but with a key breakpoint:
- **Layer 1 conversation history**: `history[-10:]`, each truncated to 500 chars, excluding execution params
- **Layer 2 execution context**: reflects only the current input-box values, not historical params
- **Layer 3 experience library**: `positive` recorded successful params, but `read_lessons()` reads only text summaries, not concrete params
- **Layer 4 error logs**: used only for LLM lesson distillation

#### Improvement
| File | Change |
|------|------|
| `skill.py` | debug-chat system prompt injects the most recent successful execution params (taken from `experience.json`'s `positive`, filtering entries with `success: True`) |
| `skill.py` | fallback: when the run action's params are empty, auto-fill from the most recent successful record |

### 11.12 Sandbox Function Completion

#### Problem
The AI debug assistant used a `log("info", ...)` function when modifying scripts, but the skill_runner sandbox didn't inject `log`, causing `NameError: builtin function 'log' does not exist`.

#### Root Cause
1. The debug-assistant system prompt **did not declare the sandbox's available function list**, so the AI didn't know `log` was unavailable
2. `get_datasource_id_by_name` / `get_table_schema` only had `_dc_`-prefixed versions; skills calling them directly (not via `_get_builtin_func`) couldn't find them

#### Improvement
| File | Change |
|------|------|
| `skill_runner.py` | sandbox adds `log(level, message)` → `print(f"[{LEVEL}] {message}")`; `get_datasource_id_by_name`, `get_table_schema` injected into builtins |
| `skill.py` | debug-chat system prompt references the shared `SANDBOX_TOOLS_DOC` (prompt_docs.py) instead of inline descriptions; `SANDBOX_TOOLS_DOC` annotates all function return types (e.g. `get_table_data` returns a dict, not a DataFrame), fixing AI misuse causing `'dict' object has no attribute 'columns'` |

### 11.13 Self-Healing Loop

#### Problem
After a debug-assistant execution failure, it retried only once (`range(2)`) before giving up, without continuing to repair.

#### Improvement
| File | Change |
|------|------|
| `skill.py` | `range(2)` → `range(5)`: up to 5 self-healing rounds (initial + 4 retries), each failure auto-feeds the error to the AI to keep fixing |
| `skill.py` | after all 5 rounds fail, let the AI analyze why it can't be fixed and emit a `give_up` event |
| `SkillView.vue` | added `retry` event handling (showing a "🔄 Nth repair attempt" separator) and `give_up` event handling (showing the "⚠ cannot repair" reason) |

### 11.14 Failure Detection Fix

#### Problem
When a skill returned `{"success": False, "error": "missing required migration parameter"}`, the debug assistant judged it as **success** (because `run_skill_script`'s `success` only means "the script didn't crash"; the skill's own `success` is nested in the `result` field and wasn't checked). So failures didn't trigger self-healing retries and were even mis-stored as positive examples.

#### Root Cause
`run_skill_script` return structure:
```python
{"success": True,           # script exit code 0 (didn't crash)
 "result": {"success": False, "error": "xxx"},  # the skill's own return (nested)
 "error": None}             # runner has no error
```
The old code `if not exec_result.get("success"):` checked only the outer layer, missing skill-level failures.

#### Improvement
| File | Change |
|------|------|
| `skill.py` | failure judgment changed to a two-layer check: runner-level (`not success` / has error) + skill-level (`result.success is False` / `result.error` non-empty) |
| `SkillView.vue` | `run_result` display also checks the inner `result.success` / `result.error` |

### 11.15 Debug Pages Integrated with Multi-Agent (Completed)

#### Goal
All debug pages (skill/operator/pipeline) use the same DataProcessor + DataInspector multi-agent architecture as the chat page.

#### Implementation
See §2.7.16. Adopts the Orchestrator-Worker pattern:

| Change | File | Description |
|------|------|------|
| Streaming tool-call method | llm.py | added `chat_stream_with_tools_and_thinking()`, 3-in-1 streaming reasoning + tool calls + length escalation |
| DataProcessor debug mode | data_processor_agent.py | added `modify_script`/`run_script` tools + `run_debug()` streaming method + debug-mode system prompt + `_execute_tool` supports skill/operator/pipeline types |
| Skill debug-chat | skill.py | hand-written LLM loop → AgentRuntime call (-180 lines) |
| Operator debug-chat | operator.py | same (-90 lines) |
| Pipeline debug-chat | pipeline.py | same |
| Frontend event handling | SkillView/OperatorView/PipelineView.vue | added `inspecting`/`retry`/`give_up` event handling |

#### Architecture Change
```
Before: debug page → hand-written LLM loop (regex-parse action) → execute → end
After:  all pages → AgentRuntime → DataProcessor (streaming reasoning + tool calls) → DataInspector
```

### 11.16 Orchestrator-Worker Granularity Design

#### Design Principle
Agents for complex reasoning, Tools for simple operations.

| Operation | Complexity | Form | Reason |
|------|--------|------|------|
| modify_script | low (code merge) | Tool | one function call, no LLM reasoning needed |
| run_script | low (sandbox execution) | Tool | execute script and return result, no LLM reasoning needed |
| Data quality inspection | high (multi-round reasoning) | Agent (Worker) | decide what to check, interpret results, judge severity |

#### Reference Frameworks
- Claude Code: the main Agent has simple tools directly (Read/Write/Bash); only complex tasks spawn a subagent
- OpenAI Agents SDK: Agent = instructions + tools + handoff; simple ops use tools, don't reuse an Agent
- DataCrab: DataProcessor has modify_script/run_script directly; complex inspection delegates to DataInspector

### 11.17 Non-Intrusive Harness Architecture (data_harness.py)

#### Problem
Flow-layer Harness logic (convergence detection, experience collection) was scattered across business code; skill.py / operator.py each had inline implementations, ~50 lines of duplicated code, and doc drift caused bugs.

#### Design Principle
The data-layer Harness stays intrusive (must see data content); the flow-layer Harness is non-intrusive (business code calls one line).

| Layer | Component | Intrusiveness | Reason |
|----|------|--------|------|
| Data layer | `get_table_data` / `write_table_data` / `inspector_tools` | intrusive | must access data content, intercept writes |
| Flow layer | `ConvergenceGuard` / `collect_experience` | non-intrusive | only needs execution results, not data details |

#### Components

##### ConvergenceGuard
```python
guard = ConvergenceGuard(threshold=4)
guard.record(to_agent, datasource_id, table_name)
if guard.is_diverged():  # 4 consecutive same-table back-and-forths
    terminate()
```
multi_agent.py went from 13 lines of inline signature tracking → 3 lines of calls.

##### collect_experience
```python
collect_experience(base, source="debug", exec_result=result, parameters=params, script_name=name)
# internally decides: failure → record negative example; success + has historical failure → record positive example
```
skill.py / operator.py went from 4 places ~50 lines of inline collection → 6 lines each.

#### Philosophy
Inspired by Vibe Coding's non-intrusive test-harness pattern: the harness wraps outside the code, and the code under test is unaware of the harness. Data-scenario specialization: the data layer must be intrusive (state + side effects + content dependence), the flow layer can be non-intrusive.

### 11.18 Scheduling System Landing + Dead-Code Cleanup + EP Localization

| Improvement | File | Description |
|------|------|------|
| Scheduling background execution | task_runner.py (new) + schedule.py | `execute_task()` dispatches by task_type to skill (to_thread) / operator (exec+func) / pipeline (await execute_pipeline); the trigger endpoint hooks into BackgroundTasks for actual execution; updates TaskExecution + Schedule records |
| Scheduled scan worker | task_runner.py + main.py | 30s interval scans active schedules with `next_run_at <= now()`; concurrency control (concurrent_runs) + next_run_at recompute to prevent duplicate triggers; lifespan start/stop (start_scheduler/stop_scheduler) |
| Sandbox namespace extraction | sandbox_ns.py (new) + operator.py | `build_operator_namespace` + `run_async_in_thread` moved from the operator.py endpoint to the service layer, eliminating the API→service reverse dependency |
| Element Plus localization | main.ts | `app.use(ElementPlus, { locale: zhCn })` |
| Dead-code cleanup | multiple | deleted the entire CodeView/ExploreView/Notebook set (frontend + backend + model + schema + routes, net -1159 lines); skill_executor.py slimmed to 2 dataclasses (333→37 lines) |

### 11.19 Debug Loop Strengthening

| Improvement | File | Description |
|------|------|------|
| Enforce per-round execution | data_processor_agent.py | DEBUG_INSTRUCTIONS rewritten: every round must call modify_and_run; root-cause analysis goes in thinking, not the body; forbid "plan-only" text output without tool calls |
| AST smart script compression | data_processor_agent.py | `_extract_script_for_context`: scripts over 50k chars use AST to keep all function signatures + docstrings, large functions abbreviated to first/last 5 lines + omission marker; falls back to raw truncation on syntax errors |
| Smart tool-result compression | data_processor_agent.py | `_compress_tool_result`: failures keep full error info, successes keep only a summary + a few data rows, reducing context usage |
| handoff param simplification | data_processor_agent.py | `handoff_to_inspector` no longer requires datasource_id/table_name; auto-uses the current debug context's datasource and table |
| Tool-exception fallback | data_processor_agent.py | `_safe_execute` catches tool-execution exceptions and returns a structured JSON error, preventing a single tool exception from crashing the whole gather |
| LLM stream timeout guard | llm.py | `_stream_with_timeout`: 120s first-chunk / 60s subsequent-chunk timeout, applied to all 5 streaming methods; on timeout degrades to the next model instead of hanging silently |
| Debug no-tool redirection | data_processor_agent.py + data_inspector_agent.py | When the reasoning model emits no tool call (Processor: any no-tool) or reasoning is truncated (Inspector: only `finish_reason=length`), switch to the fast model + `tool_choice=required` to force a tool call, avoiding repeated truncation wasting tokens on the reasoning model; Inspector's normal check-completion is unaffected |
| Length-escalation dead-code cleanup | llm.py + data_processor_agent.py + data_inspector_agent.py | The `token_chain` length escalation in `chat_stream_with_tools_and_thinking` was superseded by the new redirection mechanism; removed the inner loop + `clear_thinking` yield + docstring; the two agents' `_cleared`/`clear_thinking` handling removed in sync (the non-tools `chat_stream_with_thinking` retains its length escalation for endpoints/skill_creator) |
| Inspector fuzzy table-name matching | inspector_tools.py | `_resolve_table_name`: when the table doesn't exist, finds the closest table name by containment, fixing Inspector using a business name as the table name causing `get_table_data` to fail |
| Handoff-cap linkage | multi_agent.py + operator.py + pipeline.py | `max_handoffs` links to `debug_max_inspections` (= inspections×2+2), ConvergenceGuard threshold widened in sync, preventing the 7-round inspect-fix loop from being cut short; retry-round events show the real inspection round |
| written_tables tracking | skill_runner.py + data_processor_agent.py | `write_table_data` records `_WRITTEN_TABLES`, execution result returns `written_tables`; DataProcessor handoff prefers the actually-written table name from it, not inferring from the result type |
| Provider-aware embedding selection | llm.py | `_eff_embedding_model` + `_PROVIDER_EMBEDDING_MODELS`: picks the embedding model by provider (glm→embedding-3 / qwen→text-embedding-v3 etc.), avoiding OpenAI model names being sent to Zhipu et al.; `init_user_llm_context` adds UUID type validation + empty-API-key fallback to global config |

### 11.20 Round 9 — Truncation-Guarantee Contract + Reasoning-Budget Right Fix + Prefix Cache

**Core insight**: After comparing with Opencode / DeepAnalyze, round 8's `max_tokens=4000` "to prevent reasoning from dragging on" was self-harm — max_tokens is a cap, not a charge; the model's reasoning self-terminates, so the cap only truncates and never saves tokens. The real cause of "reasoning dragging on" is circular reasoning (the model stuck in a loop), which should be fixed at the root with StuckDetector + frequency_penalty, not with a cap. Both goals (no truncation + token saving) are satisfied by the same set of levers.

**Truncation-guarantee contract (user-visible truncation → zero)**:
- L1 prevent: max_tokens raised to 12000 (cap≠cost; reasoning self-terminates, no waste)
- L2 continue: on finish_reason=length → append partial + "continue from where you stopped", same-model continuation (≤5 rounds); partial reused as input (hits prefix cache), no regeneration, no clear_thinking
- L3 force-progress: if continuation exhausted and still length (extremely rare) → same model + tool_choice=required fallback (does NOT switch to fast_model — preserves already-generated reasoning)
- L4 circular-reasoning right fix: has_massive_repetition detects reasoning duplication → inject frequency_penalty=0.1 next round (one-shot, DA line 1567)

| Change | File | Notes |
|------|------|------|
| L1 delete 4000 cap + delete "thinking ≤5 sentences" | llm.py + 2 agents + endpoints | max_tokens 4000/6000/8000 → 12000 (cap≠cost); removed DEBUG_INSTRUCTIONS "keep thinking within 5 sentences" (cap doesn't save tokens; prompt-begging doesn't save provider reasoning tokens, only degrades quality) |
| L2 truncation continuation | llm.py | `chat_stream_with_tools_and_thinking` / `chat_stream_with_thinking` add L2 continue: on finish_reason=length append generated partial assistant + "continue" user msg, same-model continuation ≤5 rounds; partial reused as input (prefix-cache hit), no regeneration, no clear_thinking; replaces token_chain escalation (4K→8K→16K regeneration) |
| L3 force-progress (replaces fast_model redirect) | data_processor_agent.py + data_inspector_agent.py | Deleted length→fast_model redirect (loses reasoning + double billing); L2 exhausted → same model + tool_choice=required (`_force_tool_attempts` ≤2); L3 failure → give_up graceful termination (explicit failure signal, not a truncated fake result) |
| L4 circular-reasoning right fix | agent_utils.py + llm.py + 2 agents | `has_massive_repetition`: samples candidate substrings and counts non-overlapping occurrences (≥3 = repetition); reasoning repetition detected → next round `frequency_penalty=0.1` (one-shot, reset after use); root-cause fix for "reasoning dragging on", replacing the 4000-cap band-aid |
| Prefix Cache static/dynamic partition | data_processor_agent.py | `build_debug_system_prompt` split into static region (instructions + spec + sandbox docs + tool guidance + safety + anti-hallucination) memoized byte-stable above `---DYNAMIC_BOUNDARY---`, dynamic region (script/params/lessons/history) below; removed round_num progressive injection (broke cache); GLM context cache hits static prefix from round 2, input cost down 30%+ (DA line 1484-1536) |
| continue event observability | llm.py + 2 agents | L2 continuation yields `{"type":"continue","round":n}` forwarded to frontend; L3/L4 trigger warning logs |
| Cross-turn reasoning summary keeps conclusion | data_processor_agent.py | `thinking_content[:500]` (first-segment only) → first 200 + last 300 chars (preserves root-cause conclusion, not just opening context) |
| endpoints max_tokens sync | operator.py + pipeline.py + skill.py | 4 `chat_stream_with_thinking(max_tokens=4000/2000)` → 12000, consistent with new default |

**Relationship to prior rounds**: Round 8's "no-tool redirect (switch to fast_model)" and "length-escalation dead-code cleanup" are fully superseded by this round's L2+L3 — L2 continuation preserves reasoning (no loss), L3 same-model fallback (no dumb-model switch). Round 8's `_stream_with_timeout` / written_tables / provider-aware embedding / handoff-cap linkage remain untouched.

### 11.21 Round 10 — Line-Level Patch Primitive (aligning with OpenCode edit)

**Core insight**: Round 9's L2 continuation can rescue "output truncation", but cannot rescue the root cause of "shouldn't have generated this much code in the first place". Comparing with OpenCode revealed the essential gap is **edit-primitive granularity**: OpenCode uses line-level patches (old_string/new_string) — small edits produce small output, naturally never truncating; DataCrab's `modify_and_run(code=...)` forces the LLM to emit the entire function or even the whole script, with a high output floor → truncation. experience.json's lessons plainly recorded "fix is just one line" yet the LLM still rewrote the whole thing, dropped imports, and truncated. This round lowers the edit primitive from function-level to line-level.

| Change | File | Notes |
|------|------|------|
| apply_patch line-level patch | operator_parser.py | `apply_patch(original, old_string, new_string)`: exact string match (unique) → per-line strip lenient match (tolerates indentation); 0 hits → "not found" error, >1 hits → "not unique" error; returns `{success, code, message}`. Aligns with OpenCode edit semantics |
| edit_script / edit_and_run tools | data_processor_agent.py | New `EDIT_SCRIPT_TOOL` / `EDIT_AND_RUN_TOOL` schema (old_string+new_string, line-level patch); `edit_and_run` delegates to edit_script+run_script (symmetric with modify_and_run); `DEBUG_TOOLS` grows to 6 |
| read_script tool (verbatim read) | data_processor_agent.py | `READ_SCRIPT_TOOL`: returns the verbatim full text of the current script (optional function_name to view a single function). Call before line-level patch to get the exact old_string; result is not compressed (preserves verbatim text), fixing the issue where `_extract_script_for_context` compressed >8KB scripts so the LLM couldn't get verbatim text |
| _finalize_script_change shared helper | data_processor_agent.py | Extracted modify_script's "write operator/pipeline/skill + skill_md + AST syntax check + diff" into a shared method, reused by both modify_script and edit_script, eliminating ~90 lines of duplication |
| DEBUG_INSTRUCTIONS rewrite | data_processor_agent.py | "every round must use modify_and_run" → "every round must use edit_and_run or modify_and_run"; prefer edit_and_run for small edits (small output, no truncation); only use modify_and_run for whole-function rewrites; added edit_and_run call example |
| run_debug loop integration | data_processor_agent.py | `_TOOL_LABELS` adds edit_script/edit_and_run/read_script; "executing" detection adds edit_and_run; "query-only no edit" check adds edit_and_run/edit_script; result-handling blocks `modify_and_run`/`modify_and_run` branches expanded to `in (modify_and_run, edit_and_run)` / `in (modify_script, edit_script)`; read_script result not compressed |
| tool honesty table | tool_guidance.py | Added "debug script-editing tools" section: honest comparison of edit_and_run (small output / precise / requires unique match), modify_and_run (large output / function-level / may truncate), read_script (verbatim / costs tokens) |
| apply_patch unit tests | tests/test_apply_patch.py | 7 cases: exact unique replace / not found / multiple non-unique / empty old_string / lenient indentation match / multiline replace / lenient multiple fails |

**Relationship to prior rounds**: Round 9's L2 continuation + L3 force-progress remain untouched — they are the fallback for "output truncation"; this round reduces output volume at the root, so small edits no longer trigger truncation. The two are complementary: edit_and_run makes output small (prevention), L2 continuation backs up rare output truncation (insurance).

### 11.22 Round 11 — Function-Level Merge Fixes Subfunction-Split Bug (modify_script losing functions)

**Core bug**: Round 10's `edit_and_run` solved "small edits don't truncate", but `modify_script`'s (whole-function rewrite scenario) merge logic was still the old "full replacement" — when the LLM returned multi-function code with imports, it would overwrite the entire original script, losing all imports / constants / other functions; worse, new functions (not present in the original script) would be mistakenly treated by the subsequent `_strip_main_block` as "code outside the main block" and deleted, so the LLM's helper functions simply vanished. experience.json repeatedly recorded "after edit, main can't find helper" — exactly this bug.

**Fix strategy**: `apply_partial_code` always performs function-level merge, no longer full replacement.

| Change | File | Notes |
|------|------|------|
| `apply_partial_code` function-level merge | operator_parser.py | Rewritten: AST parses top-level FunctionDef/AsyncFunctionDef/ClassDef in partial → same-name definitions replace the corresponding ones in the original script (replace back-to-front to avoid line-offset issues) → new functions (non-same-name) inserted before `if __name__ == '__main__':` (to avoid deletion by `_strip_main_block`); no longer overwrites the whole segment, preserving the original script's imports/constants/other functions |
| `_find_main_block_line` AST locator | operator_parser.py | New helper: uses AST to precisely find the line number (0-based) of `if __name__ == '__main__':`; returns the last line count if not found (append to file end); more robust than regex, immune to string literals |
| `modify_script` integration | data_processor_agent.py | `modify_script` tool changed from "write code directly" to `apply_partial_code(current, code)` function-level merge, then goes through `_finalize_script_change` (write + AST syntax check + diff); edit_script unaffected (line-level patch never does full replacement anyway) |
| `apply_partial_code` unit tests | tests/test_apply_patch.py | 5 new cases: no main block append / insert before main block (core bug) / mixed (same-name replace + new function) / multiple new functions all before main / same-name replace (regression of original behavior); total cases 7→12 |

**Relationship to prior rounds**: Round 10's `edit_and_run` (line-level patch, small edits) + this round's `apply_partial_code` (function-level merge, whole-function rewrites) together cover both usage scenarios of modify_script — small edits go through line-level patch (small output), large changes go through function-level merge (no function loss). Both avoid the old "full replacement loses context" bug.

### 11.23 Round 12 — Aligning with OpenCode Debug Mode (minimal prompt + thinking + investigate-without-fix detection + SSE keepalive + import fixes)

**Core insight**: Comparing with OpenCode revealed DataCrab's debug mode gap — OpenCode locates code via context (error→direct Edit), DataCrab guided "first investigate" causing 7 rounds of investigation without fixing; OpenCode has thinking, DataCrab disabled it (`enable_thinking=False`); OpenCode has no round concept, DataCrab's round display was accidentally deleted.

| Change | File | Notes |
|------|------|------|
| DEBUG_INSTRUCTIONS to OpenCode minimal style | data_processor_agent.py | Removed investigation guidance + round info, changed to "look at error, use edit_and_run to modify and execute" |
| thinking enabled | data_processor_agent.py | `enable_thinking=False`→`True` + loop forwards thinking events to frontend (previously discarded) |
| investigate-without-fix detection | data_processor_agent.py | `_no_fix_rounds`: called tools but not edit_and_run/modify_and_run/run_script → count; 3 consecutive → give_up |
| analyze mode 1 round | data_processor_agent.py | `max_iterations = 1 if analyze_only else 7` |
| round display fix | SkillView/OperatorView/PipelineView.vue | round event adds `─── Round ${data.round} ───` (previously accidentally deleted) |
| run() adds yield round | data_processor_agent.py | Main chat run() yields round each round (previously missing) |
| SSE ping mechanism | skill.py | Auto-fix adds ping (every 20s keepalive, prevents network error) |
| platform issue prediction | data_processor_agent.py | `_is_platform_issue_report` + `_PLATFORM_ISSUE_SIGNALS`: LLM output judged as platform issue → platform_issue event + terminate |
| per-round platform check removed | data_processor_agent.py | Removed per-round fast_model platform check (misjudgment + waste) |
| import fixes | data_processor_agent.py | Added StuckDetector/SearchSaturationDetector/estimate_complexity/get_turn_budget/should_warn_ungrounded_claim/is_planning_only/get_context_pressure_level/build_pressure_warning |
| frontend platform_issue handling | SkillView/OperatorView.vue | Shows "platform capability missing" |
| timeout back to 300s | config.py | SKILL_RUNNER_TIMEOUT 60→300 |

**Relationship to prior rounds**: Rounds 10-11 aligned the editing primitive layer (edit_and_run + apply_partial_code); this round aligns the debug mode layer (minimal prompt + thinking + context-based locating). Complementary: primitives make small edits not truncate, mode makes LLM modify directly without investigating.

### 11.24 Round 13 — Fix-Attempt Right Fix (3-execution-failure cap + 7-total-fix cap, investigation doesn't count)

**Core insight**: The user corrected the design philosophy — "7 fix attempts = modify 7 times, not call LLM 7 times, not freely choose to investigate-then-fix; equivalent to OpenCode interacting 7 times to make modifications". Only actual code modifications (edit_and_run/modify_and_run/run_script) count as a fix attempt; investigation (read/grep) is preparation and doesn't count. Two limits: **3 = consecutive execution-failure cap before first success**, **7 = total fix-attempt cap** (including inspection-driven fixes).

| Change | File | Notes |
|------|------|------|
| **3-execution-failure sub-limit** | data_processor_agent.py | `_exec_failures_before_success`: 3 consecutive failures before first success → stop; resets after success |
| **7-total-fix cap** | data_processor_agent.py | `while _fix_attempts < 7`: all fixes (execution-error + inspection fixes) counted together |
| **cross-handoff persistent counters** | data_processor_agent.py | `_fix_attempts`/`_execution_succeeded`/`_exec_failures` persisted via `context` |
| **round event counts fix attempts** | data_processor_agent.py | `yield {"type":"round","round":_fix_attempts}` only on fix-tool detection; investigation rounds have no round event |
| **removed fast model** | data_processor_agent.py | Always deep model (glm-5.2); fast model (glm-4-flash) too weak, reads but doesn't modify |
| **removed investigate-without-fix detector** | data_processor_agent.py | Removed `_no_fix_rounds` counter + 3-idle give_up logic; investigation is legitimate, no penalty |
| **DEBUG_INSTRUCTIONS rewrite** | data_processor_agent.py | Added "judge fixability first" + "fix fully each time, don't rely on next" + "max 3 execution errors" |
| **removed enable_thinking dead code** | llm.py | Param removed (default True, no one passes False) + `extra_body={"thinking":"disabled"}` removed |
| **removed frequency_penalty dead code** | llm.py | Residual `if frequency_penalty is not None` removed |
| **removed max_tokens=12000** | data_processor_agent.py + llm.py | Use platform default (align with OpenCode); L2 continuation (max_continues=5) backs up truncation |
| **debug_max_rounds default 7** | skill.py + pipeline.py + operator.py | 5 places `"debug_max_rounds": 7` |
| **frontend "round"→"fix attempt"** | SkillView/OperatorView/PipelineView.vue | `─── Round N ───`→`─── Fix attempt N ───` (3 places) |
| **tool-result display** | data_processor_agent.py | Investigation tools (grep/read/query/schema) result summary yielded to frontend (like OpenCode showing grep/read) |

**Relationship to prior rounds**: Round 12 aligned debug mode with OpenCode (minimal prompt + thinking + context locating); this round rights the fix-count design — 3-execution cap + 7-total-fix cap, investigation doesn't count. Removing fast model + investigate-without-fix detector lets LLM freely investigate + fix. Dead-code cleanup of enable_thinking/frequency_penalty/max_tokens.

### 11.25 Round 14 — Silent-Failure Audit + OpenCode Debug-Display Alignment + Error-Classification Exit + Sandbox Completion

**Core insight**: Comparing with OpenCode, audited DataCrab silent failures (6 types) + debug-info gaps. OpenCode debug flow: Grep locates line → Read(offset/limit) reads only relevant lines → Edit(old_string/new_string) modifies. DataCrab previously Read full file (22828 chars), display showed only char-count summary, Edit display truncated 80 chars, errors unclassified relying on LLM text judgment.

**Silent-failure audit**:

| Change | File | Notes |
|------|------|------|
| UUID type mismatch | datasource.py | 4 internal endpoints UUID→str fix |
| CSV/Excel fail silent overwrite | connectors.py | `write_table_data` fail strategy → raise, no silent overwrite |
| error result caching | shared_tools.py | Tool-execution failures not cached, avoid reuse of bad results |
| connection-failure raise | connectors.py | 8 places: return None → raise ConnectionError |
| list_user_datasources close | shared_tools.py | close() moved to finally, avoid leak |
| stats except: pass | connectors.py | 2 places `except: pass` → `logger.warning` |
| skill_runner empty return | skill_runner.py | 6 tool functions return empty → raise explicit error |
| VALID_WRITE_STRATEGIES | connectors.py | Validate write strategy at entry, invalid → raise |

**OpenCode debug-display alignment**:

| Change | File | Notes |
|------|------|------|
| read_script no cap | data_processor_agent.py | Default returns full text (align OpenCode Read default 2000 lines); offset/limit optional; removed 60-line hard cap |
| read_script with line numbers | data_processor_agent.py | `L1: content` format (align OpenCode Read) |
| read_script shows actual content | data_processor_agent.py | Was `read: func (22828 chars)` → now shows actual content code block (cap 40 lines) |
| grep_script shows matching lines | data_processor_agent.py | Was `search: 3 matches, first: ...` → now all matching lines `>> L636: content` (cap 10) |
| edit_and_run action shows diff | data_processor_agent.py | Was truncated 80 chars `repr(old)→repr(new)` → now ```diff``` block full old(-)/new(+) (cap 40 lines) |
| modify_and_run result shows diff | data_processor_agent.py | Was only function name → now also `changed_lines` diff block |
| DEBUG_INSTRUCTIONS workflow | data_processor_agent.py | Explicit `grep → read(offset/limit) → edit` workflow, no full-file/full-function reads |

**Sandbox completion + doc unification**: call_operator builtin (skill_runner.py + sandbox_ns.py); SANDBOX_TOOLS_DOC full signatures (prompt_docs.py, 17 functions); PLATFORM_CONVENTIONS_DOC (platform-conventions doc injected into generation+debug+NL-inference); read_file image fail-fast; DQ-UNI-001 primary-key uniqueness check (inspector_tools.py).

**Other**: personal.md → soul.md full rename; frontend label renames; give_up shows reason (6 places); SSE ping keepalive; execution-failure yield content; NL-inference injects datasource list; extract-image-info / data-etl skill fixes; Excel create_new_file platform-capability → False.

**Relationship to prior rounds**: Rounds 10-13 built editing primitives + debug mode; this round fills in silent-failure audit + OpenCode debug-display alignment. read_script no-cap aligns OpenCode (guide offset/limit via instructions, not hard limits); error exit relies on platform-signal keyword matching + execution-error count + fix-attempt cap (not error classification, which was removed later).

### 11.26 Round 15 — Full Rule Implementation + Install Fixes + Asset Packaging + Architecture Cleanup

**Core insight**: Round 14 filled in debug display and silent-failure audit, but rule checks were only 39% deterministically implemented (61% relied on LLM subjective judgment or unimplemented); install flow broke in multiple places (poetry-core download timeout / passlib vs bcrypt 4.x conflict / npm run install not installing devDependencies); skills/pipelines/operators couldn't migrate across machines.

**Full rule implementation (31 new deterministic checks)**:

| Change | File | Notes |
|------|------|------|
| standards_parser extension | standards_parser.py | Parse legal values + don't skip no-regex rules + parse detection logic |
| STD enum checks | inspector_tools.py | STD-ENUM-001~004 (gender/id/marriage/country) + STD-HERITAGE-001~002 (era/protection-level) |
| STD numeric constraints | inspector_tools.py | STD-NUM-001 amount / -002 percent / -003 age / -004 quantity |
| STD geo | inspector_tools.py | STD-LOC-001 address / -004 lat-lng range |
| STD time | inspector_tools.py | STD-TIME-003 Unix timestamp / -004 time-range consistency |
| DQ completeness/uniqueness/validity/consistency | inspector_tools.py | DQ-COM-001/002, DQ-UNI-002, DQ-VAL-002, DQ-CON-001 |
| DQ-ETL extension | inspector_tools.py | DQ-ETL-007/008/009 target-table null-rate/primary-key-unique/field-type-consistency |
| SEC PII/sensitive-business/masking/classification | inspector_tools.py | SEC-PII-006/007, SEC-BIZ-001~003, SEC-MASK-001~004, SEC-CLASS-001 |

**Bug fixes**: DQ-COM-003 threshold inversion (`null_rate > 0.95`→`0.05`); DQ-UNI-001 false-positive (removed "编号" column); local_messages undefined after handoff (passed via `context["_local_messages"]`); session-list not bubbling (two entry points add `session.updated_at = now()`).

**Install fixes**: pyproject.toml poetry→setuptools (no poetry-core download dependency); requirements.txt completion (openai/chromadb/minio/aiosqlite/pyyaml/croniter); passlib→bcrypt direct (resolves passlib vs bcrypt 4.x conflict); npm install fix (postinstall hook); easyflow→datacrab cleanup; INSTALL.md slimmed.

**Asset packaging (skill/pipeline/operator cross-machine migration)**: startup auto-seed skills/pipelines/operators (main.py); pipeline/operator export endpoints; frontend export buttons; TableMetadata import-path fix.

**Architecture cleanup**: removed skill-auto-sync-operator (skill.py, skills and operators now independent); removed sandbox grep function (unused, full removal).

**Relationship to prior rounds**: Round 14 filled in debug display and silent-failure audit; this round fills in rule implementation (39%→78% deterministic checks) + fixes install chain (3 blocking bugs) + asset-packaging mechanism. Rules still not deterministically implementable (DQ-TIM/DQ-ETL-010/DQ-BIZ/SEC-CLASS-002~003/SEC-COMP etc.) remain LLM-prompt judgment.

### 11.27 Round 16 — Context Compaction + Prefix Cache Stability + SSE Fix + Image Compression + traceback Line-Number Fix

**Core insight** (vs OpenCode): Round 9's L2 continuation solved "output truncation", but the other side of long sessions — unbounded context growth blowing the window — remained untreated. Comparing with OpenCode revealed two fundamental gaps: ①OpenCode has compaction (old-message summary + keep recent verbatim + mechanical identifier protection), DataCrab only had static pressure warnings with no actual compression; ②OpenCode's system prompt is byte-stable to hit provider prefix cache, DataCrab stuffed real-time data previews into system prompt, recomputing prefix cache every message, high input cost. This round fills in context lifecycle management + cache stability.

**Context compaction (aligning with OpenCode)**:

| Change | File | Notes |
|------|------|------|
| `should_compact` + `compact_messages` | agent_utils.py | Trigger at ≥75% context usage: keep system + LLM-summarize old messages + keep last 2 turns verbatim + mechanical identifier extraction (no LLM dependency); fallback to mechanical summary if LLM unavailable |
| `extract_identifiers_from_messages` | agent_utils.py | Reuses `extract_identifiers(text)` full pattern set to extract UUID/table-name/datasource-ID per message; after compaction Agent doesn't forget already-queried tables |
| Processor main-loop integration | data_processor_agent.py | `run()` + `run_debug()` check `should_compact` at loop top; debug mode yields a notice before compacting |
| Inspector integration | data_inspector_agent.py | Compaction check at loop top |

**Prefix cache stability**:

| Change | File | Notes |
|------|------|------|
| data preview moved out of system | chat.py | Real-time data preview from system prompt → one-shot user message (`{preview}\n\n---\n\n{user_msg}`); system byte-stable to hit GLM context cache, input down 30%+ |
| `build_datasource_context` split | chat.py | Returns `(context, preview)` tuple; `_build_system_prompt` drops real-time-data hint section |
| `has_preinjected_data` fix | chat.py | From string-containment check → `bool(data_preview)`, more reliable |

**Inspector anti-hallucination content suppression**: streaming content buffering (data_inspector_agent.py) — don't yield content tokens immediately; decide after stream ends: ungrounded data claims → suppress this turn's content + inject warning to retry; has tool calls / final conclusion → output.

**SSE ping fix**: `ensure_future` + `wait` pattern (operator.py + pipeline.py + skill.py) — `asyncio.wait_for(anext, timeout)` timeout cancels the underlying coroutine, which corrupts async-generator state; changed to `ensure_future` to create a task + `asyncio.wait` (no cancel), on timeout send ping then keep waiting the same task.

**Other improvements**:

| Change | File | Notes |
|------|------|------|
| `execute_query` signature cleanup | connectors.py + datasource.py | Removed unused `params` param from 8 connectors + BaseConnector |
| image compression | datasource.py + sandbox_ns.py | llm_vision images scaled to max 1024px + JPEG quality 85, saves 60-70% tokens; falls back to original if PIL unavailable |
| query_table_data/execute_sql split format | shared_tools.py | `to_dict(orient="records")` → `values.tolist()` + `"format":"split"` (no repeated column names, more token-efficient) |
| traceback line-number fix | skill_runner.py | `_fix_traceback_lines`: subprocess temp-file line numbers → original-script line numbers (minus template preamble 478 lines); run_skill_script + streaming integrated |
| datasource tables sorted by update time | datasource.py + DataSourceView.vue | `get_datasource_tree` joins TableMetadata.updated_at desc (newest first); table items show update time |
| `debug_max_exec_failures` configurable | data_processor_agent.py | 3→context-configurable; DEBUG_INSTRUCTIONS uses `{max_exec_failures}` placeholder |
| debug tool-display refinement | data_processor_agent.py | read shows line range / grep shows keyword / edit shows diff block; removed duplicate modify_script diff; line cap 50→20; execution success shows explicit ✅ |
| anti-hallucination warning wording | agent_utils.py | `should_warn_ungrounded_claim` now directly demands calling inspection tools (no explanation, no admitting error) |
| CLAUDE.md → AGENTS.md | AGENTS.md + design.md + design.en.md | Title + references updated, align with universal agent-collaboration file naming |

**Relationship to prior rounds**: Round 9's L2 continuation treats "output truncation" (single-turn overlong output); this round treats "context growth" (cross-turn history bloat) — the two are orthogonal, together covering the full long-session lifecycle. Prefix-cache stability extends Round 9's static/dynamic partitioning (system must be byte-stable to hit provider cache). The SSE ping fix resolves the latent bug of `wait_for` cancelling an async generator (previously the generator could corrupt after timeout).

### 11.28 Round 17 — OpenCode Debug Alignment: Tool Simplification + Runtime Auto-Handoff + Vision Models + Backup Models + SSE Fixes

**Core insight** (vs. OpenCode): Rounds 10–16 established the line-level patch primitive + fix-attempt discipline + context compaction, but debug tools still exposed 7 (edit_and_run/modify_and_run/modify_script/edit_script/run_script/read_script/grep_script) and relied on the LLM actively calling the handoff_to_inspector tool to hand off inspection. Compared to OpenCode's 5-tool model (Grep/Read/Edit/Bash/Task), this round slimmed debug tools to 4 and made handoff runtime-triggered. It also simplified the streaming methods — Round 9's L2/L3/L4 truncation guarantee contract (max_continues / tool_choice=required / frequency_penalty) was high-complexity, low-payoff and was replaced by a simple multi-model degradation chain.

| Improvement | File | Description |
|------|------|------|
| **Debug tools slimmed to 4** | data_processor_agent.py | `run_debug` exposes only `edit_script`/`run_script`/`read_script`/`grep_script` (aligning with OpenCode Grep/Read/Edit/Bash); `edit_and_run`/`modify_and_run`/`modify_script` schema+handlers retained but no longer exposed to the debug LLM |
| **Removed handoff_to_inspector tool** | data_processor_agent.py | Debug mode no longer exposes a handoff tool; after `run_script` succeeds the runtime auto-hands off to DataInspector (reason=FIX_COMPLETED/INSPECT_RESULT), extracting the target table from written_tables/output_table |
| **Removed script summary** | data_processor_agent.py | Deleted `_script_summary`, forcing the LLM to use `read_script` for real code (aligning with OpenCode's no-pre-summary) |
| **Simplified action summary** | data_processor_agent.py | Shows only tool-name icons, no diff/pattern/offset details (less noise) |
| **Streaming methods simplified to degradation chain** | llm.py | `chat_stream_with_thinking`/`chat_stream_with_tools_and_thinking` removed L2 continuation (max_continues)/L3 force-progress (tool_choice=required)/L4 frequency_penalty; now per-model attempt + CircuitBreaker + transient retry; finish_reason=length returns directly without continuation |
| **Vision model support** | llm.py + sandbox_ns.py + skill_runner.py | `_PROVIDER_VISION_MODELS` (glm→glm-4v-plus/qwen→qwen-vl-plus etc.); `llm_vision` sandbox function picks model by provider; image compression 1024px+JPEG85; failures prefixed with "platform limitation" |
| **Backup model (degradation) config** | llm.py + ModelConfigView.vue | `_model_configs` main model + fallback_models; `_degradation_chain`; CircuitBreaker trips after 3 consecutive failures for 60s; frontend restores backup-model management UI |
| **Inspector removes forced handoff** | data_inspector_agent.py | `_collect_severe_issues` no longer called by run() (dead code); handoff entirely decided by the LLM via the handoff_to_processor tool |
| **Inspector severity correction** | data_inspector_agent.py | `_correct_severity`: overrides LLM-tampered severity with the tool's original severity |
| **SSE handler fixes** | skill.py + operator.py + pipeline.py | done event forwarded (no longer swallows result.content); tool_result forwarded (Inspector tool results visible); platform_issue event handled on frontend |
| **read_script refreshes from disk** | data_processor_agent.py | No longer uses stale context copy; reads latest from disk; offset/limit applies to script scope |

**Relationship to prior rounds**: Rounds 10–11 line-level patch (edit_script/apply_partial_code) + Round 13 fix-attempt discipline (3 execution / 7 total fixes) retained; this round slimmed the exposed tool surface (7→4) + automated handoff (removed handoff tool). Round 9's L2/L3/L4 truncation guarantee contract was simplified to a degradation chain (measured high-complexity, low-payoff; multi-model degradation + CircuitBreaker suffices). Round 8's `_stream_with_timeout`/written_tables/provider-aware embedding retained.

### 11.29 Round 18 — Model Auto-Selection: Remove fast_model/default_model, Infer by Context + Rule Fallback

**Core insight**: Round 4 introduced the deep+fast dual-model architecture (fast_model/default_model); Round 13 removed fast_model to always use the deep model. But "always deep" is wasteful — simple scenarios (parameter inference / chat) don't need glm-5.2. This round eliminates the fast_model/default_model concept entirely, replacing it with `pick_model_async` which lets the LLM pick the most suitable and economical model by context; simple scenarios use a flash-model rule fallback without asking the LLM.

| Improvement | File | Description |
|------|------|------|
| **pick_model_async model auto-selection** | llm.py | Builds available-model list (with capability descriptions) + task scenario → asks LLM to pick the most suitable and economical model → result cached (100 entries); simple scenarios (parameter inference / chat) use a flash-model rule fallback without asking the LLM |
| **Removed fast_model/default_model/classify_task** | llm.py | `fast_model` property / `default_model` concept / `classify_task` task classification all deleted; seed providers drop fast_model/default_model fields |
| **chat methods model=None auto-infer** | llm.py | `chat`/`chat_with_messages`/`chat_stream_*` all call `pick_model_async` when model=None; new `context` parameter propagates the task scenario |
| **context parameter end-to-end propagation** | skill.py + operator.py + pipeline.py + datasource.py | NL inference / skill modification / operator generate-modify-debug / pipeline generation / script llm_chat all add context parameter |
| **Inspector system prompt slimmed** | data_inspector_agent.py | Rule files moved out of system prompt; `run_all_checks` pre-execution + `format_report` generates a compact report injected as a user message |
| **inspector_tools full rule implementation** | inspector_tools.py | 31 deterministic checks (STD-ENUM/NUM/LOC/TIME + DQ-COM/UNI/VAL/CON/ETL + SEC-PII/BIZ/MASK/CLASS); `_resolve_table_name` fuzzy matching |

**Relationship to prior rounds**: Round 4's dual-model architecture + Round 13's "remove fast_model, always deep" are replaced by `pick_model_async` — no longer a binary choice (deep or fast), but selecting the most suitable and economical from the available-model list by context. Round 17's degradation chain + CircuitBreaker retained (execution-layer fault tolerance after model selection).

**Known leftovers** (fixed in Round 19): `data_processor_agent.py`'s `_handle_get_llm_config` referenced the deleted `llm_manager.fast_model` property (AttributeError when calling the get_llm_config tool); DB model/config layers still retained the fast_model column (empty value, no runtime impact). → Both items were fully cleaned up in Round 19.

### 11.30 Round 19 — fast_model Residual Cleanup: Fix AttributeError + DB/Config/Frontend Full-Chain Cleanup

**Core insight**: Round 18's `pick_model_async` deleted the `llm_manager.fast_model` property, but `_handle_get_llm_config` still referenced it (AttributeError when calling the get_llm_config tool), and DB schema/endpoint/frontend had scattered `fast_model` residual reads/writes. This round cleans up the `fast_model` residuals that Round 18 left behind across the full chain; `default_model` is retained (seed/registry still use it as the Provider-recommended deep-model name, not a leftover).

| Improvement | File | Description |
|------|------|------|
| **_handle_get_llm_config rewritten** | data_processor_agent.py | Deleted `llm_manager.fast_model` (AttributeError root cause); now returns `available_models` (with capability descriptions, from `_available_models_with_desc`); providers list `fast_model` → `default_model` |
| **SAVE_LLM_ADAPTER cleanup** | data_processor_agent.py | schema drops `fast_model` parameter; `_handle_save_llm_adapter` removes fast_model reads/writes (4 places) |
| **llm.py 6-place cleanup** | llm.py | `init_user_llm_context` (fallback + cfg) / `_parse_fallback_models` / `load_providers_from_db` (seed + registry) / comments all drop fast_model |
| **DB model drops 2 Columns** | models/custom_extension.py | `LLMProvider.fast_model` + `UserLLMConfig.fast_model` Column definitions deleted; fallback_models comment updated |
| **config.py endpoint cleanup** | endpoints/config.py | `LLMConfigRequest`/`FallbackModelItem`/`LLMConfigResponse` schemas drop fast_model field; `get_llm_config`/`update_llm_config` reads/writes all deleted (8 places) |
| **custom_extension.py return cleanup** | endpoints/custom_extension.py | providers list returns `fast_model` → `default_model` |
| **settings retained for compat** | core/config.py | `LLM_FAST_MODEL: str = ""` retained with deprecation comment — business code no longer reads it; kept only for compat with existing .env LLM_FAST_MODEL vars (pydantic extra_forbidden would crash) |
| **.env.example drops LLM_FAST_MODEL** | backend/.env.example | Removed LLM_FAST_MODEL example line |
| **Frontend display cleanup** | ModelConfigView.vue | `formatCapabilities` drops `if (row.fast_model) caps.push('快速')` |

**Verification**: `app.main` fully loads 184 routes; `LLMProvider`/`UserLLMConfig` table columns confirmed no fast_model; `_handle_get_llm_config` source confirmed no fast_model reference; `llm_manager.fast_model` property confirmed absent.

**Relationship to prior rounds**: Completes the cleanup Round 18 left unfinished (Round 18 only deleted the llm_manager property; DB/schema/endpoint/frontend residuals were not cleaned). `default_model` is not in scope — seed providers still write it, registry still reads it, as the Provider-recommended deep-model name (not a dead field). settings.LLM_FAST_MODEL retention is a backward-compat compromise (deleting it would break existing .env deployments); business code no longer reads it.

### 11.31 Round 20: Video Processing — Keyframe Extraction + Metadata Probe

**Core need**: User requested "extract key scenes and information from a video." Aligned with the existing `llm_vision` image-processing pipeline, added video processing — metadata extraction + keyframe extraction to images (passable to `llm_vision` for content understanding).

| Improvement | File | Description |
|------|------|------|
| **video_utils.py shared module** | video_utils.py (new) | `probe_video` (ffprobe-first, opencv fallback) + `extract_keyframes` (ffmpeg scene-detection-first, opencv equal-interval fallback); frame images PIL-compressed to 1024px + JPEG quality 85 |
| **internal/video/info endpoint** | datasource.py | Video metadata extraction endpoint; skill sandbox subprocess calls via HTTP |
| **internal/video/keyframes endpoint** | datasource.py | Video keyframe extraction endpoint (path validation + output_dir authorization) |
| **extract_video_info / extract_keyframes sandbox functions** | skill_runner.py + sandbox_ns.py | Skill sandbox (HTTP) + operator sandbox (direct); returns metadata / keyframe list; frame images passable to llm_vision |
| **Docs + capability table + deps** | prompt_docs.py + tool_guidance.py + requirements.txt | SANDBOX_TOOLS_DOC + PLATFORM_CONVENTIONS_DOC + available_functions + opencv-python-headless + pillow |

### 11.32 Round 21: Model Selection Simplified + Endpoint Pruning + Chat Export + Streaming Error Recovery + Data Update Time Tracking + StuckDetector Enhancement

**Core insight**: Round 18's `pick_model_async` (LLM picks model) was complex and cost an extra LLM call; simple scenarios don't need to ask the LLM. This round does subtraction: simplify model selection, delete redundant endpoints, delete low-value mechanisms, and add chat export + streaming error recovery.

| Improvement | File | Description |
|------|------|------|
| **Model selection simplified** | llm.py + config.py | Deleted `pick_model_async`/`pick_model`; replaced with `_default` (configured deep model) + `_flash` (flash-named model) properties |
| **skill.py streaming endpoints pruned** | skill.py | Deleted `run_skill_stream` + `run_skill_nl_stream` (-624 lines) |
| **data_processor_agent pruned** | data_processor_agent.py | Deleted `_analyze_error` + `_save_session_log` + `_compress_tool_result`; deleted debug-loop context compaction |
| **StuckDetector enhanced** | agent_utils.py | Added "investigate-only" detection (5 consecutive read/grep rounds → prompt) + total-round cap (30 → prompt) |
| **Streaming error recovery** | chat.py | On streaming error, save partial content + error to DB (prevents reply disappearing on refresh) |
| **Chat export** | ChatView.vue + chat.ts | Export conversation as Markdown (with reasoning fold-out, model, timestamp) |
| **data_updated_at tracking** | datasource.py + metadata.py + connectors.py + models/datasource.py | TableMetadata new `data_updated_at` column (data-source-side real update time) |

**Verification**: `app.main` loads approximately 176 routes; 134 tests pass; no `pick_model`/`run_skill_stream`/`run_skill_nl_stream` residual references.

### 11.33 Round 22: Debug Chat Streaming + Execution Progress Archiving + Inspector Diagnostic Logs + StuckDetector Tightened + About Page

**Core insight**: Main-chat loop used non-streaming `chat_with_tools` (long wait, no feedback); debug execution progress was cleared on phase switch (lost); Inspector handoff trigger was unobservable; StuckDetector thresholds too loose.

| Improvement | File | Description |
|------|------|------|
| **Main-chat streaming** | data_processor_agent.py | `run()` from non-streaming → streaming `chat_stream_with_tools_and_thinking`, real-time yield model/thinking/content |
| **Execution progress archiving** | SkillView.vue | `archiveExecutingMsg`: on phase switch, freeze executingMsgs to `msg.stdouts` (not merged into content) |
| **Inspector + handoff diagnostic logs** | data_inspector_agent.py + data_processor_agent.py | `[Inspector-DEBUG]` / `[handoff检查]` logs; main.py log filter extended |
| **StuckDetector tightened** | agent_utils.py | `investigate_threshold` 5→3, `max_total_rounds` 30→15 |
| **tool_result expansion + done conclusion** | chat.py | content truncation 200→2000; done event extracts result.content |
| **Internal API address configurable** | skill_runner.py | `_API_BASE = os.environ.get("DATACRAB_API_BASE", ...)`; 13 hardcoded replacements |
| **About page** | AboutView.vue (new) + ConfigView.vue | Project intro, core features, tech stack, open-source link |
| **semantic-classify place-name mapping** | data/skills/26d263ab | system_prompt rewritten; 15 historical place-name mappings + autonomous-region/municipality rules |

### 11.34 Round 23: Handoff Moved to RunTime + skill_runner Merged + StuckDetector Simplified + Non-Streaming Endpoint Deleted

**Core insight**: Handoff was initiated by Agent `yield {"type":"handoff"}` — Agent needed to be aware of handoff and decide when to hand off, violating the Orchestrator-Worker principle (Agent should focus on tasks; flow orchestration is RunTime's job). skill_runner had 3 overlapping functions. `POST /messages` non-streaming endpoint overlapped with streaming. This round does architectural subtraction.

| Improvement | File | Description |
|------|------|------|
| **Handoff moved to RunTime** | multi_agent.py | `AgentRuntime.run()` rewritten: from Agent yield handoff → RunTime intercepts `done` event, calls `_decide_handoff()` to decide; new `_extract_issues()` extracts error/critical/fatal from check results |
| **Deleted handoff tools** | data_processor_agent.py + data_inspector_agent.py | Both Agents deleted handoff tool schema + `_execute_tool` branches + `run()` `_handoff` signal parsing; Agents are unaware of handoff |
| **Prefix Cache staticization** | data_processor_agent.py | `build_system_prompt()` process-level memoize; datasource_context moved from system prompt → user message prefix |
| **skill_runner 3-function merge** | skill_runner.py | `run_skill_script`/`by_content`/`streaming_by_content` merged into `run_skill_script_streaming` (supports skill_path or script_content); net -685 lines |
| **_stream_execute shared core** | skill_runner.py | Dual-layer timeout (idle no-output + hard cap total) + marker-line parsing + exception-type extraction (`_extract_exception_type`); no longer filters `[WARN]` lines |
| **Deleted POST /messages** | chat.py + chat.ts | Deleted non-streaming endpoint (~95 lines) + frontend `sendMessage()` |
| **StuckDetector simplified** | agent_utils.py | Deleted "investigate-only" detection (`INVESTIGATION_TOOLS`/`FIX_TOOLS` all deleted); only idle detection + total-round cap retained |
| **Compaction improvements** | agent_utils.py + chat.py | `extract_identifiers_from_messages` enhanced (extracts from tool_calls.arguments); `compact_messages` old-message truncation 500→1000 + summary role system→user |
| **Cross-handoff context persistence** | data_processor_agent.py | Inspector handoff-back restores tool-call history from `context["_processor_local_messages"]` |
| **format_report tabularized** | inspector_tools.py | Column overview + issue list from plain text → Markdown tables |
| **SkillView SSE shared** | SkillView.vue | New `processDebugSSEEvent()` + `readDebugSSEStream()` shared functions; 3 handlers replaced |

**Relationship to prior rounds**: Round 17 "delete handoff_to_inspector tool" only deleted the tool schema but Agent still initiated handoff via yield; this round completely moves handoff decision to RunTime (Agent is completely unaware). Round 13's "investigate-only" detector is deleted again (architectural decision: investigation is legitimate behavior, should not be punished).

### 11.35 Round 24: System Prompt Simplified + Debug Display Aligned with OpenCode + soul.md Compressed + tool_guidance Split

**Core insight**: soul.md was 95 lines verbose; tool_guidance injected debug tool table into main chat (main chat doesn't need edit_script/run_script); debug tool calls and results were mixed in content (unlike OpenCode's independent cards); frontend history passed tool cards to backend (wasted tokens + interfered with LLM).

| Improvement | File | Description |
|------|------|------|
| **soul.md compressed 95→30 lines** | soul.md | Deleted verbose behavior-rule sections (safety red lines moved to instructions); kept core: identity, capability list, style |
| **DATA_PROCESSOR_INSTRUCTIONS rewritten** | data_processor_agent.py | Added "safety red lines" section; "work guidelines" 6→5; "extended capabilities" sections → 4 one-liners |
| **tool_guidance main/debug split** | tool_guidance.py | `TOOL_CAPABILITY_TABLE` split into `_MAIN_TOOL_CAPABILITY_TABLE` + `_DEBUG_TOOL_CAPABILITY_TABLE`; main chat doesn't inject debug tool table |
| **llmContent separation** | SkillView.vue | Message object new `llmContent` field (only LLM output, no tool cards); history extraction uses `m.llmContent ?? m.content` |
| **tool_action/tool_summary independent events** | data_processor_agent.py + SkillView.vue | Tool calls/results from `yield content` → independent events (not in content); frontend with timestamped cards |
| **_slim_run_script_result** | data_processor_agent.py | Slim run_script tool result (success: only summary+written_tables; failure: only error+error_type) |
| **executingMsg lifecycle fix** | chat.ts | `error`/`done`/`content` events clear `msg.executingMsg` (fixes blue-spinner residual) |
| **Deleted main-chat round event** | data_processor_agent.py | `run()` main chat deleted per-round `yield {"type":"round"}` (avoids "Round N" spinner bothering users) |

### 11.36 Round 25: Debug Tools Pruned to 4 + Inspector Report Independent Event + Frontend Copy Buttons + Dynamic Version + Docker Deployment

**Core insight**: Debug tools pruned from 7 to 4 (edit_script/run_script/read_script/grep_script, fully aligned with OpenCode Grep/Read/Edit/Bash) — edit_script (line-level patch) already covers all modification scenarios; exposing multiple modification tools only confuses the LLM. Inspector report from mixed in content → independent `inspection_report` event. Version from hardcoded → git dynamic. Docker from dev mode → nginx hosting.

| Improvement | File | Description |
|------|------|------|
| **Debug tools pruned to 4** | data_processor_agent.py | `DEBUG_TOOLS` from 7 → 4 (`[EDIT_SCRIPT_TOOL, RUN_SCRIPT_TOOL, READ_SCRIPT_TOOL, GREP_SCRIPT_TOOL]`); deleted modify_script/modify_and_run/edit_and_run |
| **Inspector report independent event** | data_inspector_agent.py | `yield content` → `yield {"type":"inspecting"}` + `yield {"type":"inspection_report","report":report}` |
| **History passthrough purified** | skill.py + operator.py + pipeline.py | Deleted "smart history selection" → direct passthrough `request.history` (frontend already purified with `llmContent`) |
| **Frontend copy buttons** | SkillView/OperatorView/PipelineView.vue | User messages / reasoning / results / inspection results all get copy buttons |
| **OperatorView/PipelineView llmContent** | OperatorView.vue + PipelineView.vue | Same as SkillView: `llmContent` field + `tool_action`/`tool_summary`/`inspection_report` event handling |
| **Dynamic version** | version.py (new) + main.py + config.py | `get_version()`: `YYYY.MM.DD.commit-count` (git log, `@lru_cache` cached); `GET /config/version` endpoint |
| **Frontend version display** | version.ts (new) + MainLayout.vue + LoginView.vue + AboutView.vue | Pinia store `useVersionStore`; sidebar footer + login page + about page |
| **Docker nginx hosting** | frontend/Dockerfile + docker-compose.yml + nginx/nginx.conf | Frontend multi-stage build: builder `npm run build` → `nginx:alpine` hosts `dist/`; SPA routing fallback; port 5173→80 |
| **SSE long-connection support** | nginx/nginx.conf | `proxy_buffering off` + `proxy_read_timeout 300s` + `proxy_cache off` + `proxy_http_version 1.1` |
| **DATACRAB_API_BASE config** | config.py + .env.example + docker-compose.yml | skill_runner subprocess uses it to access backend API; Docker sets to `http://backend:8000` |
| **backend_data volume persistence** | docker-compose.yml | backend volumes add `backend_data:/app/data` |

**Relationship to prior rounds**: The line-level patch primitive (edit_script/apply_partial_code) established in Rounds 10-11 becomes the sole modification entry point this round. Round 23's Inspector `check_results` in context for RunTime `_extract_issues` pairs with `inspection_report` independent event for frontend formatting. Round 24's llmContent separation extends to OperatorView/PipelineView.
