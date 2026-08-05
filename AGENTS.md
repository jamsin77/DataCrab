# AGENTS.md — DataCrab 项目 AI 协作指南

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
| `data_processor_agent.py` | DataProcessor 智能体——数据处理、算子生成；调试模式 4 工具（edit_script/run_script/read_script/grep_script）+ runtime 自动交接 Inspector |
| `data_inspector_agent.py` | DataInspector 智能体——数据质量/标准/安全检查；规则移至 user message（run_all_checks 预执行 + format_report）；severity 校正 |
| `shared_tools.py` | **7 个公共工具的 schema + 实现（query_table_data/get_table_schema/list_user_datasources/list_user_file_links/save_file_to_link/kb_search/execute_sql；去重后统一入口 + LRU 缓存）** |
| `agent_utils.py` | **Agent 工程工具：token 估算、结果截断、卡死检测、标识符抽取、反幻觉、动态轮次预算、上下文压力告警、三级反幻觉注入、搜索饱和检测、工具结果缓存、上下文压缩（Compaction）** |
| `tool_guidance.py` | **工具诚实能力表（注入 system prompt）** |
| `llm.py` | LLM 管理器（模型自动选择 pick_model_async + 多模型降级链 + CircuitBreaker 熔断 + 瞬态重试 + 视觉/嵌入模型按 provider 选） |
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
| `video_utils.py` | **视频处理工具：`probe_video`（元数据提取，ffprobe 优先回退 opencv）+ `extract_keyframes`（关键帧抽取，ffmpeg 场景检测优先回退 opencv 等间隔）；帧图片 PIL 压缩 1024px + JPEG quality 85** |
| `soul.md` | 助手人格与安全红线定义（原 personal.md，rename 对齐「灵魂」语义） |

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

1. **安全红线**：DataCrab 只处理用户数据，绝不修改平台自身（soul.md）。例外：用户可用自然语言添加自定义数据源连接器和自定义模型适配器（AI 生成代码，沙箱加载）
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
    ├── 处理数据 → runtime 自动交接 → DataInspectorAgent
    │                   ├── 检查通过 → 返回结果
    │                   └── 发现问题 → handoff_to_processor → 修复 → 再检查
    └── 不需要检查 → 直接返回结果
```

**调试模式**：DataProcessor 暴露 4 个工具（edit_script/run_script/read_script/grep_script，对齐 OpenCode Grep/Read/Edit/Bash）；`run_script` 执行成功后 runtime 自动交接 DataInspector（无需 LLM 主动调 handoff 工具）。

**修改尝试正法**：3 次执行错误上限（首次成功前）+ 7 次总修改上限（含检查修复），调查（read/grep）不算次数；错误分级退出（环境/平台/数据问题直接终止，不消耗额度）。

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

### 第十四轮（静默失败审查 + OpenCode 调试显示对齐 + 错误分级退出 + 沙箱补全）

**核心洞察**：对照 OpenCode 审查 DataCrab 静默失败（6 类）+ 调试提示信息差距。OpenCode 调试流程：Grep 定位行号 → Read(offset/limit) 只读相关行 → Edit(old_string/new_string) 修改。DataCrab 之前 Read 读全文（22828字符）、显示只有字符数摘要、Edit 显示截断 80 字符、错误不分级全靠 LLM 文字判断。

**静默失败审查**（AUDIT_SILENT_FAILURES.md）：

| 改进 | 文件 | 说明 |
|------|------|------|
| UUID 类型不匹配 | datasource.py | 4 个 internal 端点 UUID 转 str 修复 |
| CSV/Excel fail 静默覆盖 | connectors.py | `write_table_data` fail 策略改为 raise，不再静默覆盖 |
| 错误结果缓存 | shared_tools.py | 工具执行失败不缓存，避免错误结果被重复使用 |
| 连接失败 raise | connectors.py | 8 处连接失败从 return None 改为 raise ConnectionError |
| list_user_datasources close | shared_tools.py | close() 移到 finally，避免异常泄漏 |
| stats except: pass | connectors.py | 2 处 `except: pass` 改为 `logger.warning` |
| skill_runner 空 return | skill_runner.py | 6 个工具函数 return 空→raise 明确错误 |
| VALID_WRITE_STRATEGIES | connectors.py | 入口校验写入策略，无效策略直接 raise |

**错误分级退出**（替代 LLM 文字判断）：

| 改进 | 文件 | 说明 |
|------|------|------|
| `_classify_execution_error` L4/L5/L6 | skill_runner.py | L4 环境问题（DLL/ModuleNotFound）/ L5 平台限制（不支持写入策略/NotImplementedError）/ L6 数据问题（表/文件不存在）；L1/L2 脚本错误继续修复 |
| run_debug 三级退出 | data_processor_agent.py | `any(kw in _err_type for kw in ("环境问题","平台限制","数据问题"))` → give_up + return；在 `_exec_failures` 之前（不消耗 3 次额度） |
| `_is_platform_issue_report` 保留为兜底 | data_processor_agent.py | 仅在 `not tool_calls` 时检查（LLM 不执行下结论的兜底），主要退出靠错误分级 |

**OpenCode 调试显示对齐**：

| 改进 | 文件 | 说明 |
|------|------|------|
| read_script 无 cap | data_processor_agent.py | 默认返回全文（对齐 OpenCode Read 默认 2000 行）；offset/limit 可选用于精确读；删 60 行硬 cap |
| read_script 带行号 | data_processor_agent.py | `L1: content` 格式（对齐 OpenCode Read） |
| read_script 结果显示实际内容 | data_processor_agent.py | 之前 `读取: func (22828 字符)` → 现在显示实际内容 code block（cap 40 行显示） |
| grep_script 结果显示匹配行 | data_processor_agent.py | 之前 `搜索: 3 个匹配，首个: ...` → 现在显示所有匹配行 `>> L636: content`（cap 10 个） |
| edit_and_run action 显示 diff | data_processor_agent.py | 之前截断 80 字符 `repr(old)→repr(new)` → 现在 ```diff``` 代码块完整 old(-)/new(+)（cap 40 行） |
| modify_and_run result 显示 diff | data_processor_agent.py | 之前只显示函数名 → 现在额外显示 `changed_lines` diff 代码块 |
| DEBUG_INSTRUCTIONS 工作流 | data_processor_agent.py | 明确 `grep → read(offset/limit) → edit` 工作流，禁止读全文/整个函数 |
| read_script 工具描述 | data_processor_agent.py | 必须用 offset/limit，给出示例 `offset=行号-5, limit=15` |

**沙箱补全 + 文档统一**：

| 改进 | 文件 | 说明 |
|------|------|------|
| call_operator 内置函数 | skill_runner.py + sandbox_ns.py | 调用用户算子（按名称模糊匹配） |
| grep 内置函数（后删除） | skill_runner.py + sandbox_ns.py | 文件搜索——因无技能使用，第十五轮删除 |
| SANDBOX_TOOLS_DOC 全签名 | prompt_docs.py | 17 个函数签名全补全，对齐实际代码 |
| PLATFORM_CONVENTIONS_DOC | prompt_docs.py | 平台规范文档（内置函数优先/不装扩展/不调外部API）注入生成+调试+NL推断三处 |
| read_file 图片 fail-fast | datasource.py + sandbox_ns.py + skill_runner.py | 图片直接报错不静默返回空 |
| DQ-UNI-001 主键唯一检查 | inspector_tools.py | 确定性主键唯一性检查实现 |

**其他改进**：

| 改进 | 文件 | 说明 |
|------|------|------|
| personal.md → soul.md | 全量 rename | 对齐「灵魂」语义；agent_config.py + config 端点 + 前端 API 全更新 |
| 前端标签改名 | ConfigView.vue 等 | 性格设定管理/大模型管理/数据标准规则/数据质量规则/数据安全规则 |
| give_up 显示 reason | SkillView/OperatorView/PipelineView.vue | 6 处显示 `data.reason`（之前只显示固定文案） |
| SSE ping 保活 | skill.py | run-nl-stream + 直接执行端点加 20 秒 ping |
| 执行失败 yield content | data_processor_agent.py | 所有执行失败都 yield `❌ 执行失败：{错误}`（之前只有环境问题才显示） |
| NL 推断注入数据源列表 | skill.py | 避免LLM猜错目标数据源 |
| extract-image-info 修复 | skills/e5be982a | `llm_vision(file_path, prompt)` 直接传路径 |
| data-etl 修复 | skills/21de3207 | `"create"`→`"fail"`、删死代码、删 import inspect |
| Excel create_new_file 平台能力 | tool_guidance.py | 改为 False（不支持创建新 Excel 文件） |

**与前轮关系**：第十~十三轮建立编辑原语（edit_and_run/apply_partial_code）+ 调试模式（极简 prompt/thinking/修改尝试正法）；本轮补齐静默失败审查 + OpenCode 调试显示对齐 + 错误分级退出。read_script 无 cap 对齐 OpenCode（靠指令引导 offset/limit，不靠硬限制）；错误分级替代 LLM 文字判断（可靠退出靠错误消息分类，不靠关键词匹配）。

### 第十五轮（规则全量实现 + 安装修复 + 资产打包 + 架构清理）

**核心洞察**：第十四轮补齐了调试显示和错误分级，但规则检查只有 39% 有确定性实现（61% 靠 LLM 主观判断或完全没实现）；安装流程多处断裂（poetry-core 下载超时/passlib 与 bcrypt 4.x 冲突/npm run install 不装 devDependencies）；技能/流程/算子无法跨机器迁移。

**规则全量实现（31 条新增确定性检查）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| standards_parser 扩展 | standards_parser.py | 解析合法值（合法值: 行）+ 不跳过无正则规则 + 检测逻辑解析；parse_security_rules 不再跳过无正则规则 |
| STD 枚举检查 | inspector_tools.py | STD-ENUM-001~004（性别/证件/婚姻/国家代码）+ STD-HERITAGE-001~002（文物年代/保护级别）合法值校验 |
| STD 数值约束 | inspector_tools.py | STD-NUM-001 金额（非负+上限）/ STD-NUM-002 百分比（0~100或0~1）/ STD-NUM-003 年龄（0~150整数）/ STD-NUM-004 数量（非负） |
| STD 地理位置 | inspector_tools.py | STD-LOC-001 地址（长度≥5+无换行）/ STD-LOC-004 经纬度范围（经度-180~180/纬度-90~90） |
| STD 时间 | inspector_tools.py | STD-TIME-003 Unix 时间戳（10/13位+范围）/ STD-TIME-004 时间范围一致性（end≥start 跨字段） |
| DQ 完整性 | inspector_tools.py | DQ-COM-001 必填字段空值（0%阈值）/ DQ-COM-002 主键非空 |
| DQ 唯一性 | inspector_tools.py | DQ-UNI-002 业务键唯一（order_no/id_card/bank_card 等列名匹配查重） |
| DQ 有效性 | inspector_tools.py | DQ-VAL-002 枚举合法（复用 STD-ENUM 合法值） |
| DQ 一致性 | inspector_tools.py | DQ-CON-001 跨字段逻辑（end_date≥start_date + age≈当前年-birth_year） |
| DQ-ETL 扩展 | inspector_tools.py | DQ-ETL-007 目标表字段空值率（10%）/ DQ-ETL-008 目标表主键唯一 / DQ-ETL-009 源→目标字段类型一致 |
| SEC PII 扩展 | inspector_tools.py | SEC-PII-006 完整地址明文（省/市/区+路/号正则）/ SEC-PII-007 姓名字段与强 PII 同表检测 |
| SEC 敏感业务 | inspector_tools.py | SEC-BIZ-001 薪资字段 / SEC-BIZ-002 医疗字段 / SEC-BIZ-003 未成年人（age<18+PII） |
| SEC 脱敏检测 | inspector_tools.py | SEC-MASK-001~004 手机/身份证/邮箱/银行卡未脱敏检测 |
| SEC 分级 | inspector_tools.py | SEC-CLASS-001 数据分级标注缺失（TableMetadata.security_level 为空） |

**Bug 修复**：

| 改进 | 文件 | 说明 |
|------|------|------|
| DQ-COM-003 阈值反转 | inspector_tools.py | MD 写"95%完整率"→解析出 0.95→代码当空值率阈值→`null_rate > 0.95` 才报警；修复为 `1 - 0.95 = 0.05` |
| DQ-UNI-001 误报 | inspector_tools.py | "编号"列非主键被当主键检查→去掉"编号"，只认 `id` 和 `_id` 后缀（3 处） |
| handoff 后 local_messages 未定义 | data_inspector_agent.py | `_execute_tool` 是独立方法访问不到 `run()` 的 `local_messages`；通过 `context["_local_messages"]` 传递 |
| 会话列表不冒泡 | chat.py | 发消息时只插 ChatMessage 不更新 ChatSession→`updated_at` 不刷新；两处入口加 `session.updated_at = now()` |

**安装修复**：

| 改进 | 文件 | 说明 |
|------|------|------|
| pyproject.toml poetry→setuptools | pyproject.toml | `pip install -e .` 不再依赖 poetry-core（下载超时根因） |
| requirements.txt 补全 | requirements.txt + requirements-optional.txt | 补 openai/chromadb/minio/aiosqlite/pyyaml/croniter；chromadb+minio 拆为可选依赖 |
| passlib→bcrypt 直用 | security.py + requirements.txt | passlib 1.7.4 与 bcrypt 4.x 不兼容（`__about__` 被删）；chromadb 要 bcrypt≥4，passlib 要 bcrypt<4，冲突；去掉 passlib，直接用 `bcrypt.hashpw`/`checkpw` |
| npm install 修复 | package.json | `install` 脚本改成 `postinstall` 钩子；`npm install`（不带 run）先装 concurrently 再跑前后端安装 |
| easyflow 清理 | .env.example + docker-compose.yml | 8 处 easyflow/EasyFlow → datacrab/DataCrab |
| INSTALL.md 精简 | INSTALL.md + INSTALL.en.md | 5 步安装指南，可选依赖单独说明 |

**资产打包（技能/流程/算子跨机器迁移）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| 启动自动 seed 技能 | main.py | 扫描 `data/skills/` 文件夹，SKILL.md 解析元数据，DB 中不存在的自动创建记录 |
| 启动自动 seed 流程 | main.py | pipelines 表为空时从 `data/seed/pipelines.json` 加载 |
| 启动自动 seed 算子 | main.py | operators 表为空时从 `data/seed/operators.json` 加载 |
| 流程导出端点 | pipeline.py | `POST /pipelines/export-seed` → 写 `data/seed/pipelines.json` |
| 算子导出端点 | operator.py | `POST /operators/export-seed` → 写 `data/seed/operators.json` |
| 前端导出按钮 | PipelineView.vue + OperatorView.vue | 「导出打包」按钮，点击后更新 seed 文件 |
| TableMetadata 导入路径修复 | inspector_tools.py | `from app.models.table_metadata` → `from app.models.datasource`（模型定义在 datasource.py） |

**架构清理**：

| 改进 | 文件 | 说明 |
|------|------|------|
| 删除技能自动同步算子 | skill.py | 删除 `_sync_scripts_to_operators` 函数 + 8 处调用 + 2 处删除清理 + Operator import；技能和算子从此独立 |
| 删除沙箱 grep 函数 | sandbox_ns.py + skill_runner.py + prompt_docs.py + tool_guidance.py + datasource.py | 因无技能使用，全量删除（函数定义/注册/文档/端点） |

**与前轮关系**：第十四轮补齐调试显示和错误分级；本轮补齐规则实现（39%→78% 有确定性检查）+ 修复安装链路（3 个阻断性 bug）+ 资产打包机制。规则仍无法确定性实现的（DQ-TIM/DQ-ETL-010/DQ-BIZ/SEC-CLASS-002~003/SEC-COMP 等）保持 LLM prompt 判断。

### 第十六轮（上下文压缩 + Prefix Cache 稳定 + SSE 修复 + 图片压缩 + traceback 行号修正）

**核心洞察**（对照 OpenCode）：第九轮 L2 续写解决「输出截断」，但长会话的另一面——上下文无限增长撑爆窗口——一直没有治理。对照 OpenCode 发现两个本质差距：①OpenCode 有 compaction（旧消息摘要 + 保留近期原文 + 标识符机械保护），DataCrab 只有静态压力告警没有实际压缩；②OpenCode 的 system prompt 字节稳定命中 provider prefix cache，DataCrab 把实时数据预览塞进 system prompt，每条消息都重算前缀缓存，input 成本高。本轮补齐上下文生命周期管理 + 缓存稳定性。

**上下文压缩（Compaction，对齐 OpenCode）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| `should_compact` + `compact_messages` | agent_utils.py | 上下文使用≥75% 触发：system 保留 + 旧消息 LLM 摘要 + 最近 2 轮原文 + 标识符机械抽取（不依赖 LLM）；LLM 不可用时兜底机械摘要 |
| `extract_identifiers_from_messages` | agent_utils.py | 复用 `extract_identifiers(text)` 完整模式集逐条抽取 UUID/表名/数据源ID，压缩后 Agent 不忘已查过的表 |
| Processor 主循环接入 | data_processor_agent.py | `run()` + `run_debug()` 每轮开头 `should_compact` 检查；debug 模式压缩前 yield 提示 |
| Inspector 接入 | data_inspector_agent.py | 每轮开头压缩检查 |

**Prefix Cache 稳定性**：

| 改进 | 文件 | 说明 |
|------|------|------|
| 数据预览移出 system | chat.py | 实时数据预览从 system prompt → 一次性 user message（`{preview}\n\n---\n\n{user_msg}`）；system 字节稳定命中 GLM context cache，input 降 30%+ |
| `build_datasource_context` 拆分 | chat.py | 返回 `(context, preview)` 元组；`_build_system_prompt` 删实时数据提示段 |
| `has_preinjected_data` 修正 | chat.py | 从字符串包含判断 → `bool(data_preview)`，更可靠 |

**Inspector 反幻觉内容抑制**：

| 改进 | 文件 | 说明 |
|------|------|------|
| 流式 content 缓冲 | data_inspector_agent.py | 不立即 yield content token，流式结束后决定：无工具支撑的数据声明→抑制本轮 content + 注入警告重试；有工具调用/最终结论→输出 |

**SSE ping 修复**：

| 改进 | 文件 | 说明 |
|------|------|------|
| `ensure_future` + `wait` 模式 | operator.py + pipeline.py + skill.py | `asyncio.wait_for(anext, timeout)` 超时会取消底层协程，对 async generator 会损坏状态；改为 `ensure_future` 创建任务 + `asyncio.wait` 不取消，超时发 ping 后继续等同一任务 |

**其他改进**：

| 改进 | 文件 | 说明 |
|------|------|------|
| `execute_query` 签名清理 | connectors.py + datasource.py | 删除 8 个连接器 + BaseConnector 未使用的 `params` 参数 |
| 图片压缩 | datasource.py + sandbox_ns.py | llm_vision 图片缩到最大 1024px + JPEG quality 85，省 60-70% token；PIL 不可用回退原图 |
| query_table_data/execute_sql split 格式 | shared_tools.py | `to_dict(orient="records")` → `values.tolist()` + `"format":"split"`（无重复列名，更省 token） |
| traceback 行号修正 | skill_runner.py | `_fix_traceback_lines`：子进程临时文件行号→原始脚本行号（减模板前缀 478 行）；run_skill_script + streaming 接入 |
| 数据源表按更新时间排序 | datasource.py + DataSourceView.vue | `get_datasource_tree` 关联 TableMetadata.updated_at 降序（最新在前）；表项显示更新时间 |
| `debug_max_exec_failures` 可配置 | data_processor_agent.py | 3→context 可配置；DEBUG_INSTRUCTIONS 用 `{max_exec_failures}` 占位符 |
| 调试工具显示优化 | data_processor_agent.py | read 显示行号范围 / grep 显示关键词 / edit 显示 diff 代码块；删 modify_script 重复 diff；行数 cap 50→20；执行成功显式 ✅ |
| 反幻觉警告措辞 | agent_utils.py | `should_warn_ungrounded_claim` 改为直接要求调检查工具（不解释不承认错误） |
| CLAUDE.md → AGENTS.md | AGENTS.md + design.md + design.en.md | 标题 + 引用更新，对齐通用 agent 协作文件命名 |

**与前轮关系**：第九轮 L2 续写治理「输出截断」（单轮输出过长）；本轮治理「上下文增长」（跨轮历史膨胀）——两者正交，共同覆盖长会话全生命周期。Prefix Cache 稳定是对第九轮静态/动态分区的延伸（system 字节稳定才能命中 provider 缓存）。SSE ping 修复解决 `wait_for` 取消 async generator 的隐性 bug（之前超时后 generator 可能损坏）。

### 第十七轮（对齐 OpenCode 调试优化——工具精简 + runtime 自动交接 + 视觉模型 + 错误分类 LLM 推断 + 备用模型 + SSE 修复）

**核心洞察**（对照 OpenCode）：第十~十六轮建立了行级补丁原语 + 修改尝试正法 + 上下文压缩，但调试工具仍暴露 7 个（edit_and_run/modify_and_run/modify_script/edit_script/run_script/read_script/grep_script），且依赖 LLM 主动调 handoff_to_inspector 工具交接检查。对照 OpenCode 的 5 工具模型（Grep/Read/Edit/Bash/Task），本轮精简调试工具到 4 个，交接改为 runtime 自动触发。同时简化流式方法——第九轮的 L2/L3/L4 截断保证契约（max_continues 续写 / tool_choice=required / frequency_penalty）复杂度高收益低，改为简单多模型降级链。

| 改进 | 文件 | 说明 |
|------|------|------|
| **调试工具精简至 4 个** | data_processor_agent.py | `run_debug` 只暴露 `edit_script`/`run_script`/`read_script`/`grep_script`（对齐 OpenCode Grep/Read/Edit/Bash）；`edit_and_run`/`modify_and_run`/`modify_script` 的 schema+处理器保留但不再暴露给调试 LLM |
| **删 handoff_to_inspector 工具** | data_processor_agent.py | 调试模式不暴露 handoff 工具；`run_script` 执行成功后 runtime 自动交接 DataInspector（reason=FIX_COMPLETED/INSPECT_RESULT），从 written_tables/output_table 提取目标表 |
| **删脚本摘要** | data_processor_agent.py | 删 `_script_summary`，逼 LLM 用 `read_script` 读真实代码（对齐 OpenCode 不预摘要） |
| **action summary 精简** | data_processor_agent.py | 只显示工具名图标，不显示 diff/pattern/offset 详情（降低噪声） |
| **DEBUG_INSTRUCTIONS 工作流** | data_processor_agent.py | 明确 `grep → read(offset,limit) → edit_script → run_script` |
| **流式方法简化为降级链** | llm.py | `chat_stream_with_thinking`/`chat_stream_with_tools_and_thinking` 删 L2 续写（max_continues）/L3 强制推进（tool_choice=required）/L4 frequency_penalty；改为逐模型尝试 + CircuitBreaker 熔断 + 瞬态重试；finish_reason=length 直接返回不续写 |
| **视觉模型支持** | llm.py + sandbox_ns.py + skill_runner.py | `_PROVIDER_VISION_MODELS`（glm→glm-4v-plus/qwen→qwen-vl-plus 等）；`llm_vision` 沙箱函数按 provider 选模型；图片压缩 1024px+JPEG85；失败加"平台限制"前缀 |
| **错误分类 LLM 推断** | skill_runner.py | `_llm_classify_error`：关键词匹配返回 script_error 时用 LLM 重新分 4 类（环境/平台/数据/脚本）；源文件不存在→数据问题，目标文件不存在→脚本错误 |
| **备用模型（降级）配置** | llm.py + ModelConfigView.vue | `_model_configs` 主模型+fallback_models；`_degradation_chain` 降级链；CircuitBreaker 连续 3 次失败熔断 60s；前端恢复备用模型管理 UI |
| **Inspector 删强制交接** | data_inspector_agent.py | `_collect_severe_issues` 不再被 run() 调用（死代码）；交接完全由 LLM 通过 handoff_to_processor 工具决定 |
| **Inspector severity 校正** | data_inspector_agent.py | `_correct_severity`：用工具原始 severity 覆盖 LLM 可能篡改的 severity |
| **Inspector _load_data 扩容** | data_inspector_agent.py | page_size 5000→50000 |
| **SSE handler 修复** | skill.py + operator.py + pipeline.py | done 事件转发（不再吞 result.content）；tool_result 转发（Inspector 工具结果可见）；platform_issue 事件前端处理 |
| **read_script 从磁盘刷新** | data_processor_agent.py | 不用 context 旧版本，从磁盘读最新；offset/limit 适用于 script scope |
| **seed 逻辑修复** | main.py | 用技能名而非文件夹名查重 |
| **Excel write_table_data 增强** | connectors.py | 支持创建新文件 + append 策略 |

**与前轮关系**：第十~十一轮行级补丁（edit_script/apply_partial_code）+ 第十三轮修改尝试正法（3 次执行/7 次修改）保留；本轮精简工具暴露面（7→4）+ 交接自动化（删 handoff 工具）。第九轮 L2/L3/L4 截断保证契约被简化为降级链（实测复杂度高收益低，多模型降级 + CircuitBreaker 已足够兜底）。第八轮的 `_stream_with_timeout`/written_tables/embedding 按 provider 选保留。

### 第十八轮（模型自动选择——去 fast_model/default_model，按上下文推断 + 规则兜底）

**核心洞察**：第四轮引入深度+快速双模型架构（fast_model/default_model），第十三轮删 fast_model 改始终用 deep model。但"始终用 deep model"浪费——简单场景（参数推断/对话）不需要 glm-5.2。本轮彻底去掉 fast_model/default_model 概念，改为 `pick_model_async` 按上下文让 LLM 选最合适且最经济的模型，简单场景规则兜底用 flash 模型不问 LLM。

| 改进 | 文件 | 说明 |
|------|------|------|
| **pick_model_async 模型自动选择** | llm.py | 构建可用模型列表（含能力描述）+ 任务场景 → 调 LLM 选最合适且最经济模型 → 结果缓存（100 条）；简单场景（参数推断/对话）规则兜底用 flash 模型不问 LLM |
| **删 fast_model/default_model/classify_task** | llm.py | `fast_model` 属性/`default_model` 概念/`classify_task` 任务分类全删；seed providers 去掉 fast_model/default_model 字段 |
| **chat 方法 model=None 自动推断** | llm.py | `chat`/`chat_with_messages`/`chat_stream_*` 所有方法 model=None 时调 `pick_model_async`；新增 `context` 参数透传任务场景 |
| **context 参数全链路透传** | skill.py + operator.py + pipeline.py + datasource.py | NL 推断/技能修改/算子生成修改调试/流程生成/脚本 llm_chat 全加 context 参数 |
| **Inspector system prompt 精简** | data_inspector_agent.py | 规则文件移出 system prompt；`run_all_checks` 预执行 + `format_report` 生成紧凑报告作为 user message 注入 |
| **inspector_tools 规则全量实现** | inspector_tools.py | 31 条确定性检查（STD-ENUM/NUM/LOC/TIME + DQ-COM/UNI/VAL/CON/ETL + SEC-PII/BIZ/MASK/CLASS）；`_resolve_table_name` 模糊匹配 |

**与前轮关系**：第四轮双模型架构 + 第十三轮"删 fast_model 始终用 deep model"被本轮 `pick_model_async` 替代——不再二选一（deep 或 fast），而是按上下文从可用模型列表中选最合适且最经济的。第十七轮的降级链 + CircuitBreaker 保留（模型选完后的执行层容错）。

**已知遗留**（第十九轮已修复）：`data_processor_agent.py` 的 `_handle_get_llm_config` 引用已删除的 `llm_manager.fast_model` 属性（调用 get_llm_config 工具时会 AttributeError）；DB 模型/配置层仍保留 fast_model 列（值为空，运行时不影响）。→ 两项均已在第十九轮彻底清理。

### 第十九轮（fast_model 残留彻底清理——修复 AttributeError + DB/配置/前端全链路清理）

**核心洞察**：第十八轮 `pick_model_async` 删了 `llm_manager.fast_model` 属性，但 `_handle_get_llm_config` 仍引用它（调用 get_llm_config 工具即 AttributeError），且 DB schema/endpoint/前端散落 `fast_model` 残留读写。本轮把第十八轮没清干净的 `fast_model` 全链路清掉，`default_model` 保留（seed/registry 仍用作 Provider 推荐深度模型名，非遗留）。

| 改进 | 文件 | 说明 |
|------|------|------|
| **_handle_get_llm_config 重写** | data_processor_agent.py | 删 `llm_manager.fast_model`（AttributeError 根因）；改返 `available_models`（带能力描述，来自 `_available_models_with_desc`）；providers 列表 `fast_model` → `default_model` |
| **SAVE_LLM_ADAPTER 清理** | data_processor_agent.py | schema 删 `fast_model` 参数；`_handle_save_llm_adapter` 删 fast_model 读写（4 处） |
| **llm.py 6 处清理** | llm.py | `init_user_llm_context`（fallback + cfg）/`_parse_fallback_models`/`load_providers_from_db`（seed + registry）/注释 全去 fast_model |
| **DB model 删 2 个 Column** | models/custom_extension.py | `LLMProvider.fast_model` + `UserLLMConfig.fast_model` Column 定义删除；fallback_models 注释更新 |
| **config.py endpoint 清理** | endpoints/config.py | `LLMConfigRequest`/`FallbackModelItem`/`LLMConfigResponse` schema 删 fast_model 字段；`get_llm_config`/`update_llm_config` 读写全删（8 处） |
| **custom_extension.py 返回清理** | endpoints/custom_extension.py | providers 列表返回 `fast_model` → `default_model` |
| **settings 保留兼容** | core/config.py | `LLM_FAST_MODEL: str = ""` 保留并标废弃注释——业务代码已不读，仅为兼容已有 .env 的 LLM_FAST_MODEL 变量（pydantic extra_forbidden 会崩） |
| **.env.example 删 LLM_FAST_MODEL** | backend/.env.example | 删除 LLM_FAST_MODEL 示例行 |
| **前端展示清理** | ModelConfigView.vue | `formatCapabilities` 删 `if (row.fast_model) caps.push('快速')` |

**验证**：`app.main` 完整加载 184 路由；`LLMProvider`/`UserLLMConfig` 表列确认无 fast_model；`_handle_get_llm_config` 源码确认无 fast_model 引用；`llm_manager.fast_model` 属性确认不存在。

**与前轮关系**：补齐第十八轮未完成的清理（第十八轮只删了 llm_manager 属性，DB/schema/endpoint/前端残留未清）。`default_model` 不在清理范围——seed providers 仍写入、registry 仍读取，作为 Provider 推荐深度模型名（非死字段）。settings.LLM_FAST_MODEL 保留是向后兼容妥协（删了会破坏已有 .env 部署），业务代码已完全不读。

### 第二十轮（视频处理能力——关键帧抽取 + 元数据提取）

**核心需求**：用户要求"把一段视频的关键画面和信息提取出来"。对齐现有 `llm_vision` 图片处理链路，新增视频处理能力——提取视频元数据 + 抽取关键帧为图片（可传给 `llm_vision` 做内容理解）。

| 改进 | 文件 | 说明 |
|------|------|------|
| **video_utils.py 共享模块** | video_utils.py（新增） | `probe_video`（ffprobe 优先，回退 opencv）+ `extract_keyframes`（ffmpeg 场景检测优先，回退 opencv 等间隔）；帧图片 PIL 压缩 1024px + JPEG quality 85 |
| **internal/video/info 端点** | datasource.py | 视频元数据提取端点（路径校验 + probe_video）；技能沙箱子进程通过 HTTP 调用 |
| **internal/video/keyframes 端点** | datasource.py | 视频关键帧抽取端点（路径校验 + extract_keyframes + output_dir 授权校验） |
| **read_file 视频格式 fail-fast** | datasource.py + sandbox_ns.py | 视频格式（mp4/avi/mov/mkv 等 12 种）→ 400 错误提示用 extract_video_info / extract_keyframes |
| **extract_video_info 沙箱函数** | skill_runner.py + sandbox_ns.py | 技能沙箱（HTTP 调端点）+ 算子沙箱（直接实现）；返回 duration/width/height/fps/codec/bit_rate/size/total_frames/audio |
| **extract_keyframes 沙箱函数** | skill_runner.py + sandbox_ns.py | 技能沙箱（HTTP 调端点）+ 算子沙箱（直接实现）；返回 [{frame, timestamp, image_path}]，帧图片可直接传 llm_vision |
| **builtins 注入** | skill_runner.py | `_builtins.extract_video_info` / `_builtins.extract_keyframes` + `_wrap_tool_log` + `_INJECTED_FUNCTIONS` + 7 处沙箱白名单 |
| **文档更新** | prompt_docs.py | SANDBOX_TOOLS_DOC 加两个函数完整签名 + 典型流程示例；PLATFORM_CONVENTIONS_DOC 加视频处理场景 |
| **能力表更新** | tool_guidance.py | available_functions 加 extract_video_info / extract_keyframes |
| **依赖** | requirements.txt | 加 opencv-python-headless + pillow |
| **安装说明** | INSTALL.md + INSTALL.en.md | ffmpeg 可选依赖说明（未装时回退 opencv） |

**与前轮关系**：对齐 `llm_vision`（图片处理）的三层架构（共享工具 → datasource 端点 + sandbox_ns 直接实现 → skill_runner HTTP 调用）。视频处理不需要调 LLM，关键帧抽出后传给 `llm_vision` 做内容理解——`extract_keyframes` + `llm_vision` 组合实现"视频关键画面和信息提取"完整链路。

### 第二十一轮（模型选择简化 + 端点精简 + 对话导出 + 流式错误恢复 + 数据更新时间追踪 + StuckDetector 增强）

**核心洞察**：第十八轮 `pick_model_async`（LLM 选模型）复杂度高、额外消耗一次 LLM 调用，且简单场景（参数推断/对话）不需要问 LLM。第十~十六轮在 data_processor_agent 中堆叠了 `_analyze_error`/`_compress_tool_result`/上下文压缩等多层机制，实际调试中收益低于复杂度成本。同时 skill.py 的 `run_skill_stream`/`run_skill_nl_stream` 流式端点与非流式端点功能重叠。本轮做减法：简化模型选择、删除冗余端点、删除低收益机制，同时补齐对话导出和流式错误恢复两个用户可感知改进。

| 改进 | 文件 | 说明 |
|------|------|------|
| **模型选择简化** | llm.py + config.py | 删除 `pick_model_async`/`pick_model`（第十八轮 LLM 模型自动选择）；替换为 `_default`（配置的深度模型）+ `_flash`（名称含 flash 的模型，找不到回退默认）属性；所有 chat 方法用 `self._default`；config.py 注释更新 |
| **skill.py 流式端点精简** | skill.py | 删除 `run_skill_stream` + `run_skill_nl_stream` 两个流式端点（-624 行），功能由非流式端点覆盖 |
| **data_processor_agent 精简** | data_processor_agent.py | 删除 `_analyze_error`（错误分析，被 skill_runner 的 `_llm_classify_error` 覆盖）+ `_save_session_log`（会话日志）+ `_compress_tool_result`（工具结果压缩）；删除调试循环中的上下文压缩（`should_compact` 检查）；模型选择统一为 `llm_manager._default` |
| **StuckDetector 增强** | agent_utils.py | 新增"只调查不修改"检测（连续 5 轮只 read/grep 不 edit/run → 提示立即修改）+ 总轮次上限（30 轮 → 提示结束）；INVESTIGATION_TOOLS/FIX_TOOLS 工具分类 |
| **流式错误恢复** | chat.py | `full_response` 初始化提前到 try 之前；流式响应出错时保存已收到的部分内容 + 错误信息到 DB，避免前端刷新后回复消失 |
| **对话导出** | ChatView.vue + chat.ts | 导出对话为 Markdown 文件（含推理过程折叠、模型、时间）；侧边栏下拉 + 顶部工具栏双入口 |
| **执行进度显示** | ChatView.vue + chat store | 处理 progress/executing/tool_result/agent_switch/inspecting/retry/round 事件 → executingMsg；前端显示旋转图标 + 进度文字 |
| **时间格式升级** | ChatView.vue | 消息时间从仅时分秒 → 完整年月日时分秒 |
| **SSE 日志** | multi_agent.py + main.py | 转发 executing/progress/run_result 等事件时记 `[SSE]` 日志；main.py 加 `debug_sse.log`（1MB 轮转）便于排查 SSE 丢事件 |
| **seed 技能去重修复** | main.py | 用 skill_path 文件夹名去重（之前用 name，SKILL.md 无 front matter 时 name 为空导致重复创建）；跳过无 front matter 的 SKILL.md |
| **data_updated_at 追踪** | datasource.py + metadata.py + connectors.py + models/datasource.py + main.py | TableMetadata 新增 `data_updated_at` 列（数据源端真实更新时间，区别于元数据记录的 updated_at）；connectors `_mtime_to_utc` 辅助；metadata 同步时写入；main.py 自动迁移加列 |
| **llm.py 注释清理** | llm.py | 第 21 行 `pick_model` 引用 → `_default/_flash` |

**验证**：`app.main` 完整加载 183 路由（删除 2 个流式端点后 -1）；134 测试全通过（修复 `test_read_script_platform_scope` 硬编码行号 → 全文搜索）；无 `pick_model`/`run_skill_stream`/`run_skill_nl_stream` 残留引用（仅 llm.py 注释已清理）。

**与前轮关系**：第十八轮 `pick_model_async` 被本轮 `_default/_flash` 替代——不再问 LLM 选模型（省一次调用），简单场景直接用配置模型。第十三轮删除的"只调查不修改"检测器以更温和形式回归（StuckDetector 内，5 轮阈值 + 仅提示不 give_up + 30 轮总上限兜底）。第八轮 `_compress_tool_result` + 第十六轮调试循环上下文压缩被删除（复杂度高、调试场景消息量有限收益低；主对话 chat.py 的 `_compress_history` 保留不动）。第二十轮视频处理不受影响。
