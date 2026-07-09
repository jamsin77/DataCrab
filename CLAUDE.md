# CLAUDE.md — DataCrab 项目 AI 协作指南

## 项目概述

DataCrab（数据工程智能体）是一个 ChatGPT 风格的对话式数据工程智能体。用户通过自然语言对话完成数据查询、清洗、转换、分析、可视化——无需写代码。

**终极目标**：Loop 化——AI 理解→执行→检查→自修复，全程无人干预。

## 技术栈

- **后端**：Python 3.11+ / FastAPI / SQLAlchemy 2.0 async / pandas / OpenAI-compatible SDK
- **前端**：Vue 3 + TypeScript / Vite 5 / Element Plus / Pinia / ECharts / Monaco Editor
- **数据库**：SQLite（开发默认）/ PostgreSQL 14+（生产）
- **向量库**：ChromaDB（文档知识库 RAG）
- **LLM**：GLM（智谱，默认）/ Qwen / SiliconFlow / 自定义 OpenAI 兼容

## 关键文件导航

### 核心服务层（`backend/app/services/`）
| 文件 | 职责 |
|------|------|
| `agent.py` | 单 Agent 服务（AgentService），非流式 /chat 端点使用 |
| `multi_agent.py` | 多 Agent 框架（BaseAgent / AgentRegistry / AgentRuntime / Handoff） |
| `data_processor_agent.py` | DataProcessor 智能体——数据处理、算子生成 |
| `data_inspector_agent.py` | DataInspector 智能体——数据质量/标准/安全检查 |
| `shared_tools.py` | **6 个公共工具的 schema + 实现（去重后统一入口 + LRU 缓存）** |
| `agent_utils.py` | **Agent 工程工具：token 估算、结果截断、卡死检测、标识符抽取、反幻觉、动态轮次预算、上下文压力告警、三级反幻觉注入、搜索饱和检测、工具结果缓存** |
| `tool_guidance.py` | **工具诚实能力表（注入 system prompt）** |
| `llm.py` | LLM 管理器（多模型降级 + 瞬态重试 + finish_reason 透传） |
| `chat.py`（endpoints） | 对话 API：流式响应、上下文压缩、统一路由、数据预览注入 |
| `experience.py` | 经验库（per-operator 经验积累 + 跨算子聚合） |
| `data_harness.py` | **非侵入式流程层 Harness：ConvergenceGuard（收敛检测）+ collect_experience（经验采集）** |
| `inspector_tools.py` | 确定性数据检查工具（pandas/regex） |
| `skill_library.py` | 技能向量索引（numpy + 磁盘持久化：.npy + JSON） |
| `skill_runner.py` | 技能脚本沙箱执行 |
| `connectors.py` | 数据源连接器（8 种：PG/MySQL/SQLite/CSV/Excel/OBS/HDFS/Chroma；Excel 多 sheet 用 `_resolve_table_name` 最长前缀匹配） |
| `personal.md` | 助手人格与安全红线定义 |

### API 端点（`backend/app/api/v1/endpoints/`）
18 个端点文件，主要：
- `chat.py` — 对话/流式响应/数据处理
- `agents.py` — 多智能体事件/血缘查询
- `skill.py` — 技能 CRUD + AI 生成/调试
- `operator.py` — 算子 CRUD + 执行
- `knowledge.py` — 文档知识库 RAG

### 前端（`frontend/src/`）
- `views/chat/` — 主对话界面
- `views/skill/` — 技能管理
- `views/operator/` — 算子管理
- `stores/chat.ts` — 对话状态管理

## 运行命令

```bash
# 开发模式（前后端联动）
npm run dev

# 后端单独
cd backend && poetry install && uvicorn app.main:app --reload --port 8000

# 前端单独
cd frontend && npm install && npm run dev

# 测试
cd backend && python -m pytest tests/ -v

# 代码格式
cd backend && black app/ && isort app/
```

## 编码规范

1. **安全红线**：DataCrab 只处理用户数据，绝不修改平台自身（personal.md）。例外：用户可用自然语言添加自定义数据源连接器和自定义模型适配器（AI 生成代码，沙箱加载）
2. **准确优先**：所有数据结论必须基于工具返回的实际数据，不得编造
3. **修改后必验证**：每次修改数据/代码后必须测试验证
4. **输出默认同源**：处理后的数据默认写回原数据源路径
5. **工具诚实**：工具描述必须标注真实局限性，不做使用推荐
6. **Agent 自主性**：系统给信号（工具能力描述、卡死检测）不给约束（"必须用A不能用B"）

## 多 Agent 架构

```
用户请求 → chat.py/stream
    ↓
DataProcessorAgent（统一入口）
    ├── 处理数据 → handoff_to_inspector → DataInspectorAgent
    │                   ├── 检查通过 → 返回结果
    │                   └── 发现问题 → handoff_to_processor → 修复 → 再检查
    └── 不需要检查 → 直接返回结果
```

**收敛检测**：连续 4 次在同一张表上来回 handoff → 终止并提示用户介入。

## 工程改进记录（借鉴 DeepAnalyze）

### 第一轮（基础工程优化）

| 改进 | 文件 | 说明 |
|------|------|------|
| 工具去重 | shared_tools.py | 6 个公共工具统一定义和实现 |
| 结果截断 | agent_utils.py | 工具返回超 8000 字符自动截断 |
| 卡死检测 | agent_utils.py | StuckDetector 检测重复调用和空转 |
| token 估算 | agent_utils.py | CJK 感知（1.5 token/字 vs 0.25） |
| 反幻觉 | agent_utils.py | 防"只规划不执行" + 无工具支撑的数据声明检查 |
| 标识符保护 | agent_utils.py | 压缩时机械抽取 UUID/表名/数据源ID |
| 工具诚实 | tool_guidance.py | 能力表注入 system prompt |
| 瞬态重试 | llm.py | 对 429/超时/500 指数退避重试 |
| 收敛检测 | data_harness.py → multi_agent.py | ConvergenceGuard 非侵入式 handoff 签名追踪 |
| 压缩保护 | chat.py | _compress_history 加标识符提取 |
| 经验聚合 | experience.py | distill_cross_patterns 跨算子经验整合 |
| 统一路由 | chat.py | 始终从 data_processor 开始，Agent 自主 handoff |

### 第二轮（深度 Agent Loop 优化）

| 改进 | 文件 | 说明 |
|------|------|------|
| 反幻觉数据声明警告 | agent.py / data_processor_agent.py / data_inspector_agent.py | should_warn_ungrounded_claim 接入循环：无工具调用时数据声明触发警告 |
| 动态轮次预算 | agent_utils.py + 3 个 agent | 按任务复杂度分配迭代上限（simple=15/medium=25/complex=40），替代固定 12 |
| 上下文压力告警 | agent_utils.py + 3 个 agent | token 超 50% 注入 Level-1 提示，超 60% 注入 Level-2 紧急提示 |
| 三级反幻觉注入 | agent_utils.py + 2 个 agent | basic/standard/strict 按 Agent 角色自动选级（Inspector=strict, Processor=standard） |
| 输出长度升级 | llm.py + 3 个 agent | finish_reason=length 时提升 max_tokens（3000→6000→12000） |
| 工具结果 LRU 缓存 | agent_utils.py + shared_tools.py | 只读工具会话内去重（30 分钟 TTL，50 条上限） |
| 搜索饱和检测 | agent_utils.py + data_processor_agent.py | SearchSaturationDetector 重复搜索 Jaccard 重叠度检测 |

### 第三轮（Bug 修复 + 架构债清理）

| 改进 | 文件 | 说明 |
|------|------|------|
| Excel 多 sheet 查询修复 | connectors.py | `_resolve_table_name` 最长前缀匹配替代只认 `\|` 的旧方法 |
| 领域硬编码清除 | chat.py | 删除 ~443 行文物领域硬编码，复杂查询交由 Agent 自主处理 |
| 预注入数据反幻觉修复 | chat.py + 2 个 agent | `has_preinjected_data` 标记避免 system prompt 已含数据时的误报 |
| 技能库持久化 | skill_library.py | VectorIndex `save_to_disk`/`load_from_disk`，重启不丢失 |
| operator.py 调用修复 | operator.py | 算子沙箱改用 `execute_shared_tool` 替代已删除的 `agent_service._query_table_data` |
| 表枚举修复 | shared_tools.py / skill.py | `get_tables()`→`get_schema()` 提取 table_name |
| Inspector 回交修复 | data_inspector_agent.py | run() 开头将 payload 值写入 context，修复自修复 Loop 断链 |
| 工具缓存 LRU 上限 | shared_tools.py | `_user_tool_caches` 加 OrderedDict LRU（100 用户上限） |
| 死代码清理 | 多文件 | 删除 8 项：DEFAULT_MAX_ITERATIONS、_parse_table_name、_route_to_agent 等 |

### 第四轮（LLM 双模型 + 写表策略 + 调试自执行 + UI 优化）

| 改进 | 文件 | 说明 |
|------|------|------|
| 深度模型+快速模型双模型架构 | llm.py + config.py + ModelConfigView.vue | 深度模型(glm-5.2)用于生成/修改脚本，快速模型(glm-4-flash)用于调试对话；`pick_model()` 按消息关键词动态选择；配置页面可分别设置 |
| write_table_data 7 种策略 | connectors.py + skill_runner.py | fail/append/replace/overwrite/truncate/delete_rows/upsert；PostgreSQL/MySQL/SQLite 全支持；支持 table_remark/column_remarks |
| skill_runner write_table_data 参数透传 | skill_runner.py | 显式参数 if_table_exists/table_remark/column_remarks，通过临时文件传递给 ConnectorManager |
| 算子 debug-chat 自动执行 | operator.py | AI 修改脚本后自动用当前调试参数执行，结果推入消息流；执行失败记录反例，成功采集正例 |
| 技能 debug-chat 自动执行 | skill.py | modify_script 后无 run action 则自动补执行；正则放宽支持无 parameters 的 run action |
| 技能转流程移至调试页面 | SkillView.vue + pipeline.py | AI 助手头部加"转为流程"按钮，流式推送推理过程到消息流；弹窗输入流程名称可修改 |
| 流程参数显示优化 | PipelineView.vue + pipeline_builder.py | 真实函数签名、参数说明列表、自动生成含描述的示例 JSON；docstring 解析参数说明 |
| 调试推理过程自动滚动修复 | SkillView.vue | 4 处 scrollSkillDebugToBottom 加 nextTick，DOM 更新后再滚动 |
| 算子调试结果合并至消息流 | OperatorView.vue | 移除左侧独立结果框，执行结果显示在 AI 助手消息流中，与技能调试页风格一致 |
| 文件浏览器单击导航 | FileSystemBrowser.vue | 文件夹模式单击直接进入子文件夹，移除 v-loading 改用文字提示，close-on-click-modal=false |
| 数据源浏览页刷新按钮 | DataSourceView.vue | 侧边栏标题加刷新图标，重新加载表列表 |
| LLM 提示词精简 | skill.py + operator.py | debug-chat 系统提示词大幅精简（SKILL.md 3000→1500、脚本截断、删除冗余文档），历史消息 20→10 条 |
| max_tokens 限制 | llm.py + 4 个端点 | 所有 chat_stream_with_thinking 调用加 max_tokens=4000，防止推理链无限拉长 |

### 第五轮（调试助手推理截断修复 + 参数记忆 + 自愈循环 + 沙箱补全 + 失败检测 + 多智能体架构统一）

| 改进 | 文件 | 说明 |
|------|------|------|
| 推理截断修复 | llm.py + SkillView/OperatorView/PipelineView.vue + skill.py | 去掉 `not has_content` 守卫；debug-chat max_tokens 4000→8000；clear_thinking 同时清 content + 重置 thinkingDone |
| debug-chat `{{}}` bug | skill.py | f-string 转义残留 → `{}`，修复 unhashable type:'dict' 导致脚本写不回磁盘 |
| 执行参数记忆 | skill.py | system prompt 注入 experience.json 最近成功参数；run 参数为空时兜底填充 |
| 沙箱 log 函数 | skill_runner.py + skill.py | 新增 `log(level, message)` 注入 builtins；`get_datasource_id_by_name`/`get_table_schema` 也注入；system prompt 声明可用函数清单 |
| 自愈循环 5 轮 | skill.py + SkillView.vue | `range(2)`→`range(5)`；5 轮全失败让 AI 分析原因（give_up 事件）；前端 retry/give_up 处理 |
| 失败检测两层 | skill.py + SkillView.vue | runner 级 + 技能级（result.success/result.error），修复技能返回失败被误判成功 |
| **流式工具调用方法** | llm.py | 新增 `chat_stream_with_tools_and_thinking()`：流式推理 + 工具调用 + 长度升级三合一（Orchestrator-Worker 架构地基） |
| **DataProcessor 调试模式** | data_processor_agent.py | 新增 `modify_script`/`run_script` 工具 + `run_debug()` 流式方法 + debug system prompt；`_execute_tool` 支持 skill/operator/pipeline 三种类型；`run()` 检测 debug_mode 自动分派 |
| **调试页面统一 AgentRuntime** | skill.py + operator.py + pipeline.py | 三个 debug-chat 端点从手写 LLM 循环改为 AgentRuntime 调用，DataProcessor → DataInspector handoff 统一 |
| **前端事件适配** | SkillView/OperatorView/PipelineView.vue | 新增 `inspecting`（DataInspector 检查中）/`retry`/`give_up` 事件处理 |
| **Orchestrator-Worker 粒度** | design.md §2.7.16 + §11.16 | Agent 用于复杂推理（DataInspector），Tool 用于简单操作（modify_script/run_script）；参考 Claude Code / OpenAI Agents SDK |

### 第六轮（非侵入式 Harness 重构 + 沙箱文档统一 + UI 修复）

| 改进 | 文件 | 说明 |
|------|------|------|
| **非侵入式 Harness 抽出** | data_harness.py（新增）+ multi_agent.py + skill.py + operator.py | 新增 `ConvergenceGuard`（收敛检测）+ `collect_experience`（经验采集）；multi_agent.py 13 行内联签名追踪 → 3 行调用；skill.py/operator.py 4 处共 ~50 行内联正反例采集 → 各 6 行调用；流程层 Harness 从业务代码中解耦 |
| **沙箱函数文档统一** | skill.py + prompt_docs.py | debug-chat 内联沙箱函数描述（缺返回类型）→ 引用共享 `SANDBOX_TOOLS_DOC`；修复 AI 误把 `get_table_data()` 返回的 dict 当 DataFrame 导致 `'dict' object has no attribute 'columns'` |
| **数据源刷新只刷当前表** | DataSourceView.vue | 刷新按钮从重载整个表列表+跳回第一张表 → 只刷新当前选中表数据 |
| **对话推理过程自动滚动** | ChatView.vue | 推理流式输出自动展开 + 即时滚动（smooth→auto），修复 smooth 动画被高频 token 打断导致不滚动 |
