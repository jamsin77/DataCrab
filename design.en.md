# DataCrab Technical Architecture Design Document

## 0. Core Philosophy

**Process data through conversation, accumulate data-processing Skills, form a data ecosystem, and ultimately achieve a fully closed AI loop for data processing.**

| Stage | Philosophy | Industry Trend |
|------|------|---------|
| Conversation as Processing | Replace coding with natural language; the LLM understands intent, matches Skills, generates code | Conversational Data Processing, Agentic UI |
| Accumulation as Asset | Each processing run accumulates as a reusable Skill, getting smarter with use | Skill-based Agent, Compound AI System |
| Ecosystem as Loop | Accumulated Skills form an ecosystem; dual-agent collaboration loop | Multi-Agent Collaboration |
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

#### 2.1.3 Notebook Data Analysis Environment (Deprecated)

> **Deprecated**: The Notebook module only retains basic models and API endpoints; the frontend no longer has a standalone Notebook page. Data analysis is replaced by the chat interface (Chat) and operator/skill execution.

~~The Notebook interface provides a code editing and execution environment as a supplement to conversational interaction.~~
##### Core Features
- Code cells (independently executable)
- Markdown cells (documentation) - execution result display
- Kernel management (Python/SQL) - save/share/export

##### Layout
```
┌───────────────────────────────────────────────────────────────────┐
│Toolbar: [Add Code] [Add MD] | [Run All] [Restart] [Save] [Share]  │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│ ┌───────────────────────────────────────────────────────────────┐ │
│ │Cell 1: Code cell                                              │ │
│ │import pandas as pd                                            │ │
│ │df = pd.read_csv('data.csv')                                   │ │
│ │[Run]                                                          │ │
│ ├───────────────────────────────────────────────────────────────┤ │
│ │Output:                                                        │ │
│ │DataFrame loaded, shape: (1000, 5)                             │ │
│ └───────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ ┌───────────────────────────────────────────────────────────────┐ │
│ │Cell 2: Markdown cell                                          │ │
│ │## Data Analysis                                               │ │
│ │Perform statistical analysis on sales data                     │ │
│ └───────────────────────────────────────────────────────────────┘ │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

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

DataCrab exposes underlying LLM capabilities as a RESTful API. Users can directly call the platform-configured LLM via HTTP requests, supporting multiple call modes.

##### API Endpoint List

| Method | Path | Description | Auth |
|------|------|------|------|
| POST | /api/v1/llm/chat | LLM chat (non-streaming) | Required |
| POST | /api/v1/llm/chat-messages | Multi-turn LLM chat (non-streaming) | Required |
| POST | /api/v1/llm/chat-stream | LLM chat (SSE streaming) | Required |
| POST | /api/v1/llm/chat-stream-messages | Multi-turn LLM chat (SSE streaming) | Required |
| POST | /api/v1/llm/chat-stream-thinking | Multi-turn LLM chat (SSE streaming, with reasoning) | Required |
| POST | /api/v1/llm/embeddings | Generate text embedding vectors | Required |

##### Request/Response Formats

**Non-streaming chat** `POST /api/v1/llm/chat`
```json
// Request
{
    "message": "Help me analyze this dataset",
    "model": null,           // optional; uses system default if omitted
    "temperature": 0.7,      // 0.0-2.0
    "max_tokens": 2000       // 1-32000
}

// Response
{
    "content": "Analysis result...",
    "model": "glm-5.2"
}
```

**Multi-turn chat (non-streaming)** `POST /api/v1/llm/chat-messages`
```json
// Request
{
    "messages": [
        {"role": "system", "content": "You are a data analysis assistant"},
        {"role": "user", "content": "Help me analyze the data"},
        {"role": "assistant", "content": "Sure, please provide the data"},
        {"role": "user", "content": "Here is the data..."}
    ],
    "model": null,
    "temperature": 0.7,
    "max_tokens": 2000
}

// Response
{
    "content": "Based on the data analysis...",
    "model": "glm-5.2"
}
```

**SSE streaming chat** `POST /api/v1/llm/chat-stream`
```
// Request (JSON)
{"message": "Help me analyze the data", "temperature": 0.7}

// Response (SSE event stream)
data: {"type": "content", "content": "Based"}
data: {"type": "content", "content": "on the data analysis"}
data: {"type": "done"}
```

**SSE streaming + reasoning** `POST /api/v1/llm/chat-stream-thinking`
```
// Request (JSON, supports multi-turn messages)
{
    "messages": [{"role": "user", "content": "Help me analyze the data"}],
    "temperature": 0.7
}

// Response (SSE event stream)
data: {"type": "thinking", "content": "The user needs to analyze data, I should..."}
data: {"type": "content", "content": "Based on the data analysis"}
data: {"type": "done"}
```

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

##### Frontend

On the "Config → LLM Chat" page, users can chat directly with the platform-configured LLM:
- ChatGPT-style conversation interface supporting multi-turn dialogue
- Switch among three call modes: streaming+reasoning / streaming / non-streaming
- Temperature slider adjustment
- Reasoning displayed in a blue card (streaming+reasoning mode)
- Markdown rendering of replies
- Supports stop generation and clear conversation

##### Call Examples (curl)

```bash
# Non-streaming chat
curl -X POST http://localhost:8000/api/v1/llm/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "temperature": 0.7}'

# Streaming + reasoning chat
curl -X POST http://localhost:8000/api/v1/llm/chat-stream-thinking \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "temperature": 0.7}'

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

- **Max iterations raised to 12 rounds** (originally 5), supporting more complex multi-step data processing tasks
- **Parallel tool calls**: added `_execute_tool_calls_parallel()`; when the LLM returns multiple tool_calls, they execute in parallel via `asyncio.gather()` to improve efficiency
- Parallel execution results are aggregated in tool_call order and returned to the LLM together, ensuring conversation-context integrity

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
def _build_operator_namespace(datasource_id=None):
    def query_table_data_sync(datasource_id, table_name, limit=1000, **kwargs):
        # Run async DB query in a separate thread to avoid event-loop conflicts
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

##### skill_library.py - Skill Library
- VectorIndex: numpy-based vector index supporting:
  - Vector normalization
  - Cosine similarity search
  - Vector add/delete/update
- SkillLibrary: skill library management, including:
  - Vector index build and search
  - Built-in skill examples (select, filter, sort, groupby, aggregate, join, fillna, dropna, rename, stats)
  - Skill registration and retrieval

##### skill_executor.py - Skill Executor
- ExecutionContext: execution context (session ID, user ID, variables, DataFrame)
- SkillExecutor: supports multiple executor types:
  - python_function: dynamically load a Python module function
  - lambda: safely execute a lambda expression
  - operator_reference: reference a registered operator
  - skill_composition: compose multiple skills into a Pipeline

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

### 2.8 Intelligent Code Generation Module (Deprecated)

> **Deprecated**: This module was based on the DAG node/edge ComposedCode model; all code has been removed (codegen.py, code.py model/schema/endpoint, composed_codes table). Functionality is replaced by §2.6 Pipeline (Python main function) and §2.7 Multi-Agent Collaboration Framework. The following is historical reference only.

#### 2.8.1 Module Architecture (Deprecated)
```
┌───────────────────────────────────────────────┐
│          Intelligent Code Generator           │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  NL Code Parser                       │   │
│   │  - Natural-language parsing           │   │
│   │  - Intent recognition                 │   │
│   │  - Entity extraction                  │   │
│   │  - Code structure generation          │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Skill Composition Engine             │   │
│   │  - Skill matching                     │   │
│   │  - Skill composition                  │   │
│   │  - Parameter inference                │   │
│   │  - Code optimization                  │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Code Validator                       │   │
│   │  - Code validation                    │   │
│   │  - Syntax check                       │   │
│   │  - Parameter validation               │   │
│   │  - Executability analysis             │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Code Executor                        │   │
│   │  - Dynamic operator loading           │   │
│   │  - Code execution                     │   │
│   │  - Result collection                  │   │
│   │  - Error handling                     │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

(The NLCodeGenerator / SkillCompositionEngine / DynamicCodeExecutor / ComposedCode classes are deprecated and omitted here; see git history if needed.)

### 2.9 Scheduling System Module

#### 2.9.1 Scheduling Architecture
```
┌───────────────────────────────────────────────┐
│               Scheduler Service               │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  Schedule Manager                     │   │
│   │  - Schedule config management         │   │
│   │  - Schedule policy config             │   │
│   │  - Schedule history records           │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Cron Scheduler                       │   │
│   │  - Cron expression parsing            │   │
│   │  - Scheduled task triggering          │   │
│   │  - Task queue management              │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Event Scheduler                      │   │
│   │  - Event listening                    │   │
│   │  - Event triggering                   │   │
│   │  - Real-time scheduling               │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Task Executor                        │   │
│   │  - Task execution                     │   │
│   │  - Status monitoring                  │   │
│   │  - Failure retry                      │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

#### 2.9.2 Schedule Configuration Model
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

#### 2.9.3 Task Execution Model
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

### 2.10 Metadata Management Module

#### 2.10.1 Design Goals

Establish a unified metadata center for all datasets (tables/files in data sources) on the platform, divided into **technical metadata** and **business metadata**, supporting:
- One-click auto-sync of technical metadata when configuring a data source
- Business metadata auto-enriched via LLM analysis of data samples; also supports manual editing
- Full-lifecycle metadata management: collection → storage → enrichment → query → lineage tracking

#### 2.10.2 Metadata Architecture

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

#### 2.10.3 Metadata Data Model

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

#### 2.10.4 Technical Metadata Auto-Sync

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

#### 2.10.5 Business Metadata AI Enrichment

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

#### 2.10.6 API Design

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

#### 2.10.7 Frontend Page Design

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

#### 2.10.8 Metadata Applications in the Platform

| Scenario | Description |
|---------|------|
| **Conversation context** | chat.py's `build_datasource_context` reads metadata to provide table structure, business meaning, data domain context to the LLM |
| **Skill/operator generation** | skill_creator / operator SYSTEM_PROMPT injects metadata so the LLM understands data structure before generating scripts |
| **Data catalog** | The frontend metadata page serves as a data catalog for browsing and searching all datasets |
| **Data lineage** | Records input/output relationships of data-processing flows to trace data origins |
| **Data quality monitoring** | Auto-detects data quality issues based on quality rules; computes quality scores |
| **Data security** | Controls data access permissions by security level |

#### 2.10.9 Integration with the Data Source Module

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

### 2.11 Permission Management Module

#### 2.11.1 RBAC Permission Model
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

#### 2.11.2 Permission Check Logic
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

### 2.12 Code Generation Module (Deprecated)

> **Deprecated**: The AST + Jinja2-based code generation module has been replaced by LLM-direct script generation (operator generation, skill generation). The following is historical reference only.

#### 2.12.1 Code Generation Flow (Deprecated)
```
Code Definition (JSON)
    → AST parsing & transformation
    → Code template rendering
    → Python code generation
    → Code optimization & formatting
    → Executable Python script
```

#### 2.12.2 Code Generator
```python
class CodeGenerator:
    """Code generator"""
    
    def generate_python_code(
        self, 
        code: Code
    ) -> str:
        """Generate Python code"""
        
        # 1. Parse the flow definition
        dag = self.parse_dag(code.definition)
        
        # 2. Generate import statements
        imports = self.generate_imports(dag)
        
        # 3. Generate data source connection code
        connections = self.generate_connections(dag)
        
        # 4. Generate operator execution code
        operations = self.generate_operations(dag)
        
        # 5. Generate the main function
        main_function = self.generate_main_function(dag)
        
        # 6. Assemble the full code
        code = f"""
{imports}

{connections}

{operations}

{main_function}

if __name__ == "__main__":
    main()
"""
        
        # 7. Format the code
        formatted_code = self.format_code(code)
        
        return formatted_code
```

#### 2.12.3 Code Template Example
```python
# Data source connection template
DATASOURCE_TEMPLATE = """
def connect_{name}():
    """Connect to data source {display_name}"""
    import {driver}
    
    connection = {driver}.connect(
        {connection_params}
    )
    return connection
"""

# Operator execution template
OPERATOR_TEMPLATE = """
def {operator_name}({inputs}):
    \"\"\"Execute operator: {display_name}
    
    Args:
        {params_doc}
    
    Returns:
        DataFrame: processing result
    \"\"\"
    {operator_logic}
    
    return result
"""
```

### 2.13 Environment Management Module (Deprecated)

> **Deprecated**: Environment isolation and migration is not implemented; no current plan. The following is historical reference only.

#### 2.13.1 Environment Isolation Architecture (Deprecated)
```
┌───────────────────────────────────────────────┐
│              Environment Manager              │
├───────────────────────────────────────────────┤
│   ┌───────────────────────────────────────┐   │
│   │  Development Environment              │   │
│   │  - Dev/test                           │   │
│   │  - Sandbox data                       │   │
│   │  - Debug mode                         │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Testing Environment                  │   │
│   │  - Integration test                   │   │
│   │  - Test data                          │   │
│   │  - Performance test                   │   │
│   └───────────────────────────────────────┘   │
│   ┌───────────────────────────────────────┐   │
│   │  Production Environment               │   │
│   │  - Production run                     │   │
│   │  - Real data                          │   │
│   │  - High-availability deployment       │   │
│   └───────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

#### 2.13.2 Environment Migration Mechanism
```python
class EnvironmentMigrator:
    """Environment migration mechanism"""
    
    async def migrate_code(
        self,
        code_id: UUID,
        source_env: str,
        target_env: str
    ) -> MigrationResult:
        """Migrate a flow"""
        
        # 1. Validate source-env flow
        code = await self.validate_code(code_id, source_env)
        
        # 2. Check dependencies
        dependencies = await self.check_dependencies(code)
        
        # 3. Migrate data source config
        await self.migrate_datasources(dependencies.datasources)
        
        # 4. Migrate operators
        await self.migrate_operators(dependencies.operators, target_env)
        
        # 5. Create target-env flow
        new_code = await self.create_code(code, target_env)
        
        # 6. Validate migration result
        await self.validate_migration(new_code, target_env)
        
        return MigrationResult(
            success=True,
            new_code_id=new_code.id
        )
```

### 2.14 Data Standards / Quality / Security Rule Libraries

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

#### Pipeline Management API (Deprecated)
> **Deprecated**: `/codes` endpoints have been removed, replaced by the `/pipelines` endpoints in §2.6.
```
# Deprecated, no longer used
# POST   /api/v1/codes                # Create code
# GET    /api/v1/codes                # Get code list
# ...etc
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
GET    /api/v1/schedules/{id}/executions # Get execution history
```

#### Natural Language Processing API (Deprecated)
> **Deprecated**: `/nl` endpoints have been removed; NL processing is replaced by the chat service (`/chat`) and the multi-agent framework.
```
# Deprecated, no longer used
# POST   /api/v1/nl/process               # Process natural language
# POST   /api/v1/nl/skills/search         # Search similar skills
# POST   /api/v1/nl/skills/register       # Register a skill
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

#### Skill Pipeline API (Deprecated)
> **Deprecated**: `/skill-pipelines` endpoints have been removed, replaced by the `/pipelines` endpoints in §2.6.
```
# Deprecated, no longer used
# POST   /api/v1/skill-pipelines           # Create a Pipeline
# ...etc
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

### 4.2 WebSocket Interface (Deprecated)

> **Deprecated**: Real-time communication switched to SSE (Server-Sent Events); WebSocket is no longer used.

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
- personal.md (highest-priority behavior rule)
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
