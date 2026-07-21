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
| `shared_tools.py` | **7 个公共工具的 schema + 实现（query_table_data/get_table_schema/list_user_datasources/list_user_file_links/save_file_to_link/kb_search/execute_sql；去重后统一入口 + LRU 缓存）** |
| `agent_utils.py` | **Agent 工程工具：token 估算、结果截断、卡死检测、标识符抽取、反幻觉、动态轮次预算、上下文压力告警、三级反幻觉注入、搜索饱和检测、工具结果缓存** |
| `tool_guidance.py` | **工具诚实能力表（注入 system prompt）** |
| `llm.py` | LLM 管理器（多模型降级 + 瞬态重试 + finish_reason 透传） |
| `chat.py`（endpoints） | 对话 API：流式响应、上下文压缩、统一路由、数据预览注入 |
| `experience.py` | 经验库（per-operator 经验积累 + 跨算子聚合） |
| `data_harness.py` | **非侵入式流程层 Harness：ConvergenceGuard（收敛检测）+ collect_experience（经验采集）** |
| `inspector_tools.py` | 确定性数据检查工具（pandas/regex） |
| `skill_library.py` | 技能向量索引（numpy + 磁盘持久化：.npy + JSON） |
| `skill_runner.py` | 技能脚本沙箱执行 |
| `sandbox_ns.py` | **算子沙箱命名空间构建（build_operator_namespace + run_async_in_thread，从 operator.py 抽出）** |
| `task_runner.py` | **调度任务后台执行器（execute_task 分派 skill/operator/pipeline + 定时调度扫描器 scheduler_loop）** |
| `skill_executor.py` | 执行上下文与结果数据结构（ExecutionContext / ExecutionResult，供 nl_data_processor 使用） |
| `connectors.py` | 数据源连接器（8 种：PG/MySQL/SQLite/CSV/Excel/OBS/HDFS/Chroma；Excel 多 sheet 用 `_resolve_table_name` 最长前缀匹配） |
| `personal.md` | 助手人格与安全红线定义 |

### API 端点（`backend/app/api/v1/endpoints/`）
16 个端点文件、共 177 条路由，主要：
- `chat.py` — 对话/流式响应/数据处理
- `agents.py` — 多智能体事件/血缘查询
- `skill.py` — 技能 CRUD + AI 生成/调试（28 路由，最多）
- `operator.py` — 算子 CRUD + 执行
- `datasource.py` — 数据源 + 12 个 `/internal/*` 无认证沙箱端点（SQL/文件 I/O/LLM 对话/视觉/分块读取）
- `knowledge.py` — 文档知识库 RAG
- `custom_extension.py` — 自定义数据源连接器 + LLM Provider 适配器（AI 生成代码，沙箱加载）

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
cd backend && pip install -e . && python -m uvicorn app.main:app --reload --port 8000

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

**收敛检测**：动态阈值（= 检查上限×2+3，默认 17）在同一张表来回 handoff → 终止并提示用户介入。

## 工程改进记录（借鉴 DeepAnalyze）

### 第一轮（基础工程优化）

| 改进 | 文件 | 说明 |
|------|------|------|
| 工具去重 | shared_tools.py | 7 个公共工具统一定义和实现 |
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

### 第七轮（调度系统落地 + 死代码清理 + EP 中文化）

| 改进 | 文件 | 说明 |
|------|------|------|
| **调度系统后台执行** | task_runner.py（新增）+ schedule.py | `execute_task()` 按 task_type 分派到 skill（to_thread）/ operator（exec+func）/ pipeline（await execute_pipeline）；trigger 端点接入 BackgroundTasks 实际执行；更新 TaskExecution + Schedule 记录 |
| **定时调度扫描器** | task_runner.py + main.py | 30s 间隔扫描 `next_run_at <= now()` 的 active 调度；并发控制（concurrent_runs）+ next_run_at 重算防重复触发；lifespan 启停（start_scheduler/stop_scheduler） |
| **沙箱命名空间抽出** | sandbox_ns.py（新增）+ operator.py | `build_operator_namespace` + `run_async_in_thread` 从 operator.py 端点移至 service 层，消除 API→service 反向依赖；operator.py 删除 2 个函数 + 2 个死 import（asyncio/threading） |
| **Element Plus 中文化** | main.ts | `app.use(ElementPlus, { locale: zhCn })` |
| **死代码清理** | 多文件 | 删除 CodeView/ExploreView/Notebook 全套（前后端+model+schema+路由，净减 1159 行）；skill_executor.py 精简至 2 个 dataclass（333→37 行） |

### 第八轮（调试 Loop 强化：上下文压缩 + 强制执行 + handoff 简化）

| 改进 | 文件 | 说明 |
|------|------|------|
| **强制每轮执行** | data_processor_agent.py | DEBUG_INSTRUCTIONS 重写：每轮必须调用 modify_and_run，根因分析放 thinking 不放正文，禁止"只规划不执行"的纯文字输出 |
| **AST 脚本智能压缩** | data_processor_agent.py | `_extract_script_for_context`：超 5 万字符脚本用 AST 保留所有函数签名+docstring，大函数缩略为首尾 5 行+省略标注；语法错误时回退原始截断（调试中脚本可能有语法错误） |
| **工具结果智能压缩** | data_processor_agent.py | `_compress_tool_result`：失败保留全量错误信息，成功只保留摘要+少量数据行，降低上下文占用 |
| **handoff 参数简化** | data_processor_agent.py | `handoff_to_inspector` 去掉 datasource_id/table_name 必填，自动使用当前调试上下文的数据源与表，降低 Agent 调用门槛 |
| **工具异常兜底** | data_processor_agent.py | `_safe_execute` 捕获工具执行异常返回结构化 JSON 错误，避免单工具异常导致整个 gather 崩溃 |
| **LLM 流式超时保护** | llm.py | `_stream_with_timeout`：首 chunk 120s / 后续 60s 超时保护，5 个流式方法全接入；超时降级到下一个模型而非静默挂起 |
| **调试无工具重定向** | data_processor_agent.py + data_inspector_agent.py | 思维模型无工具调用（Processor 任意无工具）/ 推理截断（Inspector 仅 `finish_reason=length`）→ 切快速模型 + `tool_choice=required` 强制工具调用，避免思维模型反复截断浪费 token；Inspector 正常检查完成不受影响 |
| **长度升级死代码清理** | llm.py + data_processor_agent.py + data_inspector_agent.py | `chat_stream_with_tools_and_thinking` 的 `token_chain` 长度升级被新重定向机制替代，移除内层循环 + `clear_thinking` yield + docstring；两个 Agent 的 `_cleared`/`clear_thinking` 处理同步清除（`chat_stream_with_thinking` 非 tools 版的长度升级仍保留，供 endpoints/skill_creator 使用） |
| **Inspector 表名模糊匹配** | inspector_tools.py | `_resolve_table_name`：表不存在时按包含关系找最相似表名，修复 Inspector 误用业务名当表名导致 `get_table_data` 失败 |
| **handoff 上限联动** | multi_agent.py + operator.py + pipeline.py | `max_handoffs` 与 `debug_max_inspections` 联动（= inspections×2+2），ConvergenceGuard 阈值同步放宽，避免 7 轮检查-修复循环被提前截断；retry round 事件显示真实检查轮次 |
| **written_tables 追踪** | skill_runner.py + data_processor_agent.py | `write_table_data` 记录 `_WRITTEN_TABLES`，执行结果返回 `written_tables`；DataProcessor handoff 优先从中取实际写入表名，不依赖 result 类型推断 |
| **embedding 按 provider 选** | llm.py | `_eff_embedding_model` + `_PROVIDER_EMBEDDING_MODELS`：按 provider 选 embedding 模型（glm→embedding-3 / qwen→text-embedding-v3 等），避免用 OpenAI 模型名调智谱等 provider 报错；`init_user_llm_context` 增加 UUID 类型校验 + 空 API key 回退全局 |

### 第九轮（截断保证契约 + 推理预算正法 + Prefix Cache）

**核心洞察**（对照 Opencode / DeepAnalyze）：max_tokens 是 cap 不是 charge，模型推理自终止——cap 只截断不省 token。第八轮的「4000 防 reasoning 无限拉长」是自我伤害。「推理链无限拉长」真因是循环推理，应用 StuckDetector + frequency_penalty 治本，而非 cap 治标。两个目标（不截断 + 省 Token）由同一组杠杆同时满足。

**截断保证契约（用户可见截断归零）**：L1 预防（max_tokens→12000）→ L2 续写（length 时 append partial +「继续」同模型续写 ≤5 轮，partial 复用为 cached input，不重生成不 clear_thinking）→ L3 强制推进（续写耗尽 → 同模型 + tool_choice=required，不换 fast_model）→ L4 循环推理正法（has_massive_repetition → frequency_penalty=0.1 一次性）。

| 改进 | 文件 | 说明 |
|------|------|------|
| **L1 删 4000 cap + 删「thinking 限5句」** | llm.py + 2 个 agent + endpoints | max_tokens 4000/6000/8000→12000（cap≠cost）；删 DEBUG_INSTRUCTIONS「thinking 控制在5句话以内」（prompt 求模型不省 provider 推理 token 只降质量）|
| **L2 截断续写** | llm.py | `chat_stream_with_tools_and_thinking` / `chat_stream_with_thinking` 新增续写：finish_reason=length → append partial +「继续」同模型续写 ≤5 轮；替换 token_chain 升级链（4K→8K→16K 重生成，浪费 2-3x）+ clear_thinking |
| **L3 强制推进**（替代 fast_model 重定向） | data_processor_agent.py + data_inspector_agent.py | 删 length→fast_model 重定向（丢推理+双倍计费）；L2 耗尽 → 同模型 + tool_choice=required（`_force_tool_attempts` ≤2）；失败 → give_up 优雅终止（明确失败信号，非截断假结果）|
| **L4 循环推理正法** | agent_utils.py + llm.py + 2 个 agent | `has_massive_repetition`（候选片段 + str.count ≥3 判重复）；reasoning 重复 → 下轮 `frequency_penalty=0.1`（一次性）；治「推理链无限拉长」根因，替代 4000-cap |
| **Prefix Cache 静态/动态分区** | data_processor_agent.py | `build_debug_system_prompt` 静态区（指令+规范+沙箱+工具指引+安全+反幻觉）memoize 字节稳定 + `---DYNAMIC_BOUNDARY---` + 动态区（脚本/参数/经验/历史）；移除 round_num 渐进式注入；GLM context cache 命中静态前缀，input 降 30%+ |
| **continue 事件可观测** | llm.py + 2 个 agent | L2 续写 yield `{"type":"continue","round":n}` 透传前端；L3/L4 warning 日志 |
| **跨轮推理摘要保结论** | data_processor_agent.py | `thinking_content[:500]`（只取首段）→ 首 200+尾 300（保住根因结论）|
| **endpoints max_tokens 同步** | operator.py + pipeline.py + skill.py | 4 处 chat_stream_with_thinking max_tokens 4000/2000→12000 |

**与前轮关系**：第八轮「无工具重定向（切 fast_model）」+「长度升级死代码清理」被本轮 L2+L3 彻底替代——L2 续写保留推理（不丢），L3 同模型兜底（不换傻模型）。第八轮的 `_stream_with_timeout` / written_tables / embedding 按 provider 选 / handoff 上限联动 保留不动。

### 第十轮（行级补丁原语——对齐 OpenCode edit）

**核心洞察**：第九轮 L2 续写能救「输出截断」，但救不了「本不该生成这么多代码」根因。对照 OpenCode 发现本质差距在**编辑原语粒度**：OpenCode 行级 patch（old_string/new_string）小修改只产生小输出天生不截断；DataCrab `modify_and_run(code=...)` 要求吐整函数/整脚本，输出下限高 → 截断。experience.json lessons 记着「修复方案就一行即可」但 LLM 仍整体重写丢 import 截断。本轮把编辑原语从函数级降到行级。

| 改进 | 文件 | 说明 |
|------|------|------|
| **apply_patch 行级补丁** | operator_parser.py | `apply_patch(original, old_string, new_string)`：精确唯一匹配 → 逐行 strip 宽松匹配；0 次报未找到、>1 次报不唯一；对齐 OpenCode edit 语义 |
| **edit_script / edit_and_run 工具** | data_processor_agent.py | 新增行级补丁工具（old_string+new_string）；edit_and_run 委托 edit_script+run_script；DEBUG_TOOLS 增至 6 个 |
| **read_script 工具** | data_processor_agent.py | 返回当前脚本逐字全文（可指定函数）；行级补丁前调用获取精确 old_string；结果不压缩（保逐字），修复 >8KB 脚本被压缩导致 LLM 拿不到逐字文本的问题 |
| **_finalize_script_change 共享 helper** | data_processor_agent.py | 抽取 modify_script 的写入+语法检查+diff 为共享方法，modify_script 与 edit_script 共用 |
| **DEBUG_INSTRUCTIONS 改写** | data_processor_agent.py | 小修改优先 edit_and_run（输出量小不截断）；整函数重写才 modify_and_run；加调用示例 |
| **run_debug 循环集成** | data_processor_agent.py | 标签/执行检测/修改检查/结果处理块全扩展支持 edit_and_run/edit_script；read_script 结果不压缩 |
| **工具诚实表** | tool_guidance.py | 加调试编辑工具对比：edit（小输出/精确）vs modify（大输出/可能截断）vs read（逐字/占 token） |
| **apply_patch 单测** | tests/test_apply_patch.py | 7 用例覆盖精确/未找到/不唯一/空/宽松缩进/多行/宽松多次 |

**与前轮关系**：第九轮 L2 续写 + L3 强制推进保留（输出截断兜底）；本轮从根上减少输出量，让小修改不再触发截断。互补：edit_and_run 预防（输出小）+ L2 续写保险（罕见截断兜底）。

### 第十一轮（函数级合并修复子函数拆分 bug——modify_script 丢函数）

**核心 Bug**：第十轮 `edit_and_run` 解决了小修改不截断，但 `modify_script`（整函数重写场景）的合并逻辑仍是旧的「全量替换」——LLM 返回带 import 的多函数代码会用整段覆盖原脚本，丢 import/常量/其他函数；新函数还会被 `_strip_main_block` 误删，LLM 写的辅助函数直接消失。experience.json 反复记录「修改后 main 找不到 helper」即此 bug。

**修复**：`apply_partial_code` 始终走函数级合并，不再全量替换。

| 改进 | 文件 | 说明 |
|------|------|------|
| **apply_partial_code 函数级合并** | operator_parser.py | 重写：AST 解析 partial 顶层 FunctionDef/ClassDef → 同名定义替换原脚本对应定义（从后往前避免行号偏移）→ 新函数插入 `if __name__ == '__main__':` 之前（避免被 `_strip_main_block` 删）；不再整段覆盖，保住原脚本 import/常量/其他函数 |
| **_find_main_block_line AST 定位** | operator_parser.py | 新增：用 AST 精准找 `if __name__ == '__main__':` 行号，找不到返回末尾行数；比正则稳健，不受字符串字面量干扰 |
| **modify_script 接入** | data_processor_agent.py | `modify_script` 从「直接写 code」改为 `apply_partial_code(current, code)` 函数级合并后再走 `_finalize_script_change`；edit_script 不受影响（行级补丁本就不全量替换） |
| **apply_partial_code 单测** | tests/test_apply_patch.py | 新增 5 用例：无 main 追加 / 有 main 前插入（核心 bug）/ 混合 / 多新函数 / 同名替换回归；总用例 7→12 |

**与前轮关系**：第十轮 `edit_and_run`（行级补丁，小修改）+ 本轮 `apply_partial_code`（函数级合并，整函数重写）共同覆盖 modify_script 两种场景——小改走行级补丁（输出小），大改走函数级合并（不丢函数）。都避免「全量替换丢上下文」旧 bug。

### 第十二轮（对齐 OpenCode 调试模式——极简 prompt + thinking + 只调查不修改检测 + SSE 保活 + import 补全）

**核心洞察**：对照 OpenCode 发现 DataCrab 调试模式本质差距——OpenCode 靠上下文定位代码（错误信息→直接 Edit），DataCrab 引导「先调查」导致 LLM 七轮全调查不修改；OpenCode 有 thinking，DataCrab 显式关闭（`enable_thinking=False`）；OpenCode 无轮次概念，DataCrab 轮次提示被误删。

| 改进 | 文件 | 说明 |
|------|------|------|
| **DEBUG_INSTRUCTIONS 改成 OpenCode 极简风格** | data_processor_agent.py | 去掉调查引导+轮次信息，改成「看错误信息，用 edit_and_run 修改并执行」 |
| **thinking 开启** | data_processor_agent.py | `enable_thinking=False`→`True` + 循环转发 thinking 事件给前端（之前丢弃） |
| **只调查不修改检测** | data_processor_agent.py | `_no_fix_rounds`：调了工具但没调 edit_and_run/modify_and_run/run_script → 计数；连续 3 次 → give_up |
| **分析模式 1 轮** | data_processor_agent.py | `max_iterations = 1 if analyze_only else 7` |
| **轮次显示修复** | SkillView/OperatorView/PipelineView.vue | round 事件加 `─── 第${data.round}轮 ───`（之前被误删） |
| **run() 加 yield round** | data_processor_agent.py | 主对话 run() 每轮 yield round（之前没有） |
| **SSE ping 机制** | skill.py | 自动修复加 ping（每 20 秒保活，防 network error） |
| **平台问题预判** | data_processor_agent.py | `_is_platform_issue_report` + `_PLATFORM_ISSUE_SIGNALS`：LLM 输出判为平台问题→platform_issue 事件+终止 |
| **每轮平台判断删除** | data_processor_agent.py | 删除每轮 fast_model 平台检查（误判+浪费） |
| **import 补全** | data_processor_agent.py | 补 StuckDetector/SearchSaturationDetector/estimate_complexity/get_turn_budget/should_warn_ungrounded_claim/is_planning_only/get_context_pressure_level/build_pressure_warning |
| **前端 platform_issue 处理** | SkillView/OperatorView.vue | 显示「平台能力缺失」 |
| **超时改回 300 秒** | config.py | SKILL_RUNNER_TIMEOUT 60→300 |

**与前轮关系**：第十~十一轮是编辑原语层面（edit_and_run+apply_partial_code）对齐 OpenCode；本轮是调试模式层面（极简 prompt+thinking+上下文定位）对齐。互补：原语让小修改不截断，模式让 LLM 直接修改不调查。

### 第十三轮（修改尝试正法——3次执行上限 + 7次总修改上限，调查不算次数）

**核心洞察**：用户纠正设计理念——"7 次修改尝试 = 修改 7 次，不是调用 LLM 七次，不是自由选择调查修好就行，相当于 OpenCode 跟人交互了 7 次做修改"。只有实际修改代码（edit_and_run/modify_and_run/run_script）才算一次修改尝试，调查（read/grep）是修改前的准备不算次数。用户进一步明确设计逻辑：

1. **修复前先判断**：这是 DataCrab 能修复的技能错误吗？平台限制直接退出告知不可修复
2. **执行错误阶段**：修改→执行→失败→再修，最多 3 次，3 次仍执行错误就停
3. **检查阶段**：执行成功→Inspector→合格结束，不合格→再修→再执行→再检查，合计修改次数达 7 次停

两个限制：**3 = 首次成功前连续执行错误上限**，**7 = 总修改次数上限**（含检查修复）。

| 改进 | 文件 | 说明 |
|------|------|------|
| **3 次执行错误子限制** | data_processor_agent.py | `_exec_failures_before_success`：首次执行成功前连续 3 次执行失败→停；成功后重置，不再受此限制 |
| **7 次总修改上限** | data_processor_agent.py | `while _fix_attempts < 7`：所有修改（执行错误修复+检查修复）合计达 7 次→停 |
| **跨 handoff 持久化计数器** | data_processor_agent.py | `_fix_attempts`/`_execution_succeeded`/`_exec_failures` 通过 `context` 持久化，Inspector 回交后继续计数 |
| **round 事件按修改尝试计数** | data_processor_agent.py | `yield {"type":"round","round":_fix_attempts}` 只在 fix 工具检测到时 yield，调查轮无 round 事件 |
| **删 fast model** | data_processor_agent.py | 始终用 deep model（glm-5.2），fast model（glm-4-flash）太弱只读不改 |
| **删"只调查不修改"检测器** | data_processor_agent.py | 删 `_no_fix_rounds` 计数器 + 3 次只读 give_up 逻辑；调查是合法行为不应用惩罚 |
| **DEBUG_INSTRUCTIONS 改写** | data_processor_agent.py | 加"修复前先判断可修复性"+"每次全力修复不指望下一次"+"执行错误最多3次"；`{max_rounds} 次修改机会` |
| **删 enable_thinking 死代码** | llm.py | 参数删（默认 True 无人传 False）+ `extra_body={"thinking":"disabled"}` 删 + docstring 更新 |
| **删 frequency_penalty 死代码** | llm.py | body 中残留 `if frequency_penalty is not None` 删（参数已在之前轮删除） |
| **删 max_tokens=12000** | data_processor_agent.py + llm.py | 用平台默认值（对齐 OpenCode 不设 max_tokens）；L2 续写（max_continues=5）兜底截断 |
| **debug_max_rounds 默认 7** | skill.py + pipeline.py + operator.py | 5 处 `"debug_max_rounds": 7`（总修改次数上限） |
| **give_up 消息更新** | data_processor_agent.py | `7轮修复`→`{_fix_attempts}次修改尝试`；删 `max_tokens=1000` |
| **前端"轮"→"修改尝试"** | SkillView/OperatorView/PipelineView.vue | `─── 第N轮 ───`→`─── 第N次修改尝试 ───`（3 处） |
| **工具结果显示** | data_processor_agent.py | 调查工具（grep/read/query/schema）结果摘要 yield 给前端（像 OpenCode 显示 grep/read 结果） |

**与前轮关系**：第十二轮极简 prompt+thinking+上下文定位对齐 OpenCode；本轮正法修改次数设计——3 次执行上限 + 7 次总修改上限，调查不算次数。删 fast model + 删"只调查不修改"检测器让 LLM 自由调查+修复。删 enable_thinking/frequency_penalty/max_tokens 死代码清理。
