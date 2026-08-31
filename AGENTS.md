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
| `multi_agent.py` | 多 Agent 框架（BaseAgent / AgentRegistry / AgentRuntime）；**Handoff 由 RunTime `_decide_handoff` 决策（Agent 不感知 handoff 存在）；调试模式自动交接，主对话靠人判断** |
| `agent_config.py` | Agent 配置管理（加载 soul.md 人格、构建各 Agent system prompt 静态段） |
| `chat_router.py` | 对话路由器——一次 LLM 调用判断消息类型(analysis/processing/chat) + 4 段 keep(keep_source/keep_target/keep_skill)；返回 `(msg_type, keep_source, keep_target, keep_skill, events)`；**传当前已选数据上下文（源/目标/技能名）给 LLM 判断 keep/change**；默认 keep，用户明确说换才 change |
| `data_processor_agent.py` | DataProcessor 智能体——数据处理、算子生成；调试模式 5 工具（edit_script/run_script/read_script/grep_script + list_user_datasources，对齐 OpenCode）+ RunTime 自动交接 Inspector；**system prompt 进程级 memoize（Prefix Cache）；删平台信号词匹配，靠 LLM 自主判断 + 3 次执行错误兜底 + StuckDetector 30 轮兜底** |
| `data_inspector_agent.py` | DataInspector 智能体——数据质量/标准/安全检查；规则移至 user message（run_all_checks 预执行 + format_report 表格化）；severity 校正；**报告通过 `inspection_report` 独立事件输出** |
| `data_analyst_agent.py` | DataAnalyst 智能体——只读分析（查询/统计/分布/洞察）；5 个只读工具子集（ANALYSIS_TOOLS）；不参与 handoff；独立截断阈值（30000 字符/50 行）；system prompt 进程级 memoize |
| `shared_tools.py` | **7 个公共工具的 schema + 实现（query_table_data/get_table_schema/list_user_datasources/list_user_file_links/save_file_to_link/kb_search/execute_sql；去重后统一入口 + LRU 缓存）** |
| `inspector_tools.py` | 确定性数据检查工具（pandas/regex），31 条 STD/DQ/SEC 规则实现 + `format_report` 表格化 |
| `agent_utils.py` | **Agent 工程工具：token 估算、结果截断、卡死检测（StuckDetector 空转+总轮次上限）、标识符抽取、反幻觉、动态轮次预算、上下文压力告警、三级反幻觉注入、上下文压缩（Compaction）** |
| `tool_guidance.py` | **工具诚实能力表——主对话/调试模式拆分（`get_tool_guidance(debug=)`），主对话不注入调试工具表** |
| `llm.py` | **LLM 管理器（去全局化：无全局 provider/api_key/model 属性，强制基于用户配置 `_require_user_cfg`）；`_default`/`_flash` 模型属性 + 多模型降级链 + CircuitBreaker 熔断 + 瞬态重试 + 视觉/嵌入模型按 provider 选** |
| `skill_runner.py` | **技能脚本沙箱执行（`run_skill_script_streaming` 统一入口，支持 skill_path 或 script_content；双层超时：idle 无输出 + hard cap 总时长；`_stream_execute` 标记行解析 + 异常类名提取）** |
| `skill_creator.py` | AI 生成完整 Skill 包（SKILL.md + scripts，从自然语言描述生成） |
| `skill_parser.py` | SKILL.md 解析器（YAML front matter + Markdown 内容，含 skill_type 字段） |
| `operator_parser.py` | **Python 脚本 AST 解析（提取算子函数签名/docstring）+ 行级补丁原语 `apply_patch`（对齐 OpenCode edit）+ `apply_partial_code`（函数级合并，保 import/常量/其他函数）** |
| `operators.py` | 算子基类与内置算子 |
| `sandbox_ns.py` | **算子沙箱命名空间构建（build_operator_namespace + run_async_in_thread，从 operator.py 抽出）** |
| `pipeline_builder.py` | Pipeline Builder——从 Skill 机械转换流程（保留调试好的脚本不重新生成，解析函数签名+参数说明） |
| `pipeline_executor.py` | Pipeline Executor——复用 skill_runner 子进程沙箱执行流程主函数 |
| `connectors.py` | 8 种数据源连接器实现（PG/MySQL/SQLite/CSV/Excel/OBS/HDFS/Chroma；Excel 多 sheet 用 `_resolve_table_name` 最长前缀匹配） |
| `datasource.py` | **数据源连接器基类 `BaseConnector`（抽象契约：connect/test_connection/get_schema/get_table_data/get_table_stats/close）** |
| `compute_backend.py` | **计算后端抽象层——分离「算什么」和「在哪里算」（`compute_map`，local multiprocessing 可插拔，预留 ray/dask 分布式）** |
| `experience.py` | 经验库（per-operator 经验积累 + 跨算子聚合） |
| `data_harness.py` | **非侵入式流程层 Harness：ConvergenceGuard（收敛检测）+ collect_experience（经验采集）** |
| `prompt_docs.py` | 沙箱函数文档（SANDBOX_TOOLS_DOC）+ 平台规范文档（PLATFORM_CONVENTIONS_DOC），注入生成/调试/NL 推断三处 |
| `standards_parser.py` | 数据标准/质量/安全规则解析器（解析合法值/检测逻辑） |
| `task_runner.py` | **调度任务后台执行器（execute_task 分派 skill/operator/pipeline + 定时调度扫描器 scheduler_loop）** |
| `permission_service.py` | RBAC 权限管理服务（用户/角色/权限，view/use/manage 三级） |
| `kb_service.py` | 文档知识库服务（解析+切片+嵌入+ChromaDB 存取+语义检索） |
| `video_utils.py` | **视频处理工具：`probe_video`（元数据提取，ffprobe 优先回退 opencv）+ `extract_keyframes`（关键帧抽取，ffmpeg 场景检测优先回退 opencv 等间隔）；帧图片 PIL 压缩 1024px + JPEG quality 85** |
| `asset_io.py` | **资产导出/导入服务——7 类资产（skills/operators/pipelines/llm_config/custom_extensions/datasources/schedules）一键 ZIP 迁移；API Key/密码不导出；按 name 去重 + 按类型独立覆盖；skill_calls 用 skill_name 跨机器引用，调度 task_target_id→task_target_name** |
| `match_service.py` | **向量索引服务（ChromaDB）——技能/流程/算子/数据表 embedding 存取 + 语义检索；LLM 自适应匹配（粗筛→精排两阶段，超阈值才粗筛）；`llm_match_tables` 统一函数（exclude_datasource_id 参数区分源/目标匹配）；`check_similar_resources` 通用相似资源检测；`_mlog` 独立写 match_detail.log；`rebuild_index` 全量重建（启动时可触发）** |
| `soul.md` | 助手人格定义（原 personal.md，rename 对齐「灵魂」语义）；安全红线已移至 DATA_PROCESSOR_INSTRUCTIONS |
| `version.py`（core） | **版本号动态生成（`get_version`：YYYY.MM.DD.提交次数，git log 生成，`@lru_cache` 缓存）** |

> 注：历史单 Agent 服务 `agent.py`（非流式 /chat）与 `skill_executor.py`（ExecutionContext/ExecutionResult）随多智能体统一 + 非流式端点删除已移除，不再存在。

### API 端点（`backend/app/api/v1/endpoints/`）
17 个端点文件、共 188 条路由，主要：
- `chat.py` — 对话/流式响应/数据处理；**classify 传上下文判断 keep/change + 并行匹配每路独立返回结果（data_suggestion/source_datasource_no_match/source_table_no_match/target_suggestion/target_datasource_no_match/target_table_no_match/skill_suggestion/skill_no_match）**；chat 类型直接 LLM 对话不走匹配；**使用技能走调试模式（build_debug_context + runtime.run），Agent 用 run_script 执行技能 + Inspector 自愈**；**directExecute 不存用户消息（避免刷新重复弹出），复用 assistant 消息**；`use_skill` 标记区分使用技能/直接处理
- `agents.py` — 多智能体事件/血缘查询
- `skill.py` — 技能 CRUD + AI 生成/调试（29 路由，最多）
- `operator.py` — 算子 CRUD + 执行
- `datasource.py` — 数据源 + 12 个 `/internal/*` 无认证沙箱端点（SQL/文件 I/O/LLM 对话/视觉/分块读取）
- `knowledge.py` — 文档知识库 RAG
- `assets.py` — 资产导出/导入（7 类资产一键 ZIP 迁移；counts/export/import preview/import）
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

# 后端单独（用 .venv Python 3.12，不用系统 Python）
cd backend && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# 前端单独
cd frontend && npm install && npm run dev

# 测试
cd backend && .venv\Scripts\python.exe -m pytest tests/ -v

# 代码格式
cd backend && .venv\Scripts\python.exe -m black app/ && .venv\Scripts\python.exe -m isort app/
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
用户请求 → chat.py/stream → chat_router 路由判断
    ↓
    ├── 只读分析类（查询/统计/分析）→ DataAnalystAgent → 直接返回结果（无 handoff）
    └── 数据处理类（清洗/转换/修改）→ DataProcessorAgent（统一入口）
        ├── 处理数据 → runtime 自动交接 → DataInspectorAgent
        │                   ├── 检查通过 → 返回结果
        │                   └── 发现问题 → runtime 回交 DataProcessor → 修复 → 再检查
        └── 不需要检查 → 直接返回结果
```

**调试模式**：DataProcessor 暴露 5 个工具（edit_script/run_script/read_script/grep_script + list_user_datasources，对齐 OpenCode Grep/Read/Edit/Bash）；`run_script` 执行成功后 runtime 自动交接 DataInspector（无需 LLM 主动调 handoff 工具）。

**修改尝试正法**：3 次执行错误上限（首次成功前）+ 7 次总修改上限（含检查修复），调查（read/grep）不算次数；平台信号词命中 → 立即退出（不消耗额度）。

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
| 技能库持久化 | skill_library.py（已移除） | VectorIndex `save_to_disk`/`load_from_disk`，重启不丢失（注：skill_library.py 后续已删除，技能检索改用 skill_parser + skill_creator） |
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

### 第十四轮（静默失败审查 + OpenCode 调试显示对齐 + 沙箱补全）

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
| 执行失败 yield content | data_processor_agent.py | 所有执行失败都 yield `❌ 执行失败：{错误}`（之前只有平台信号命中才显示） |
| NL 推断注入数据源列表 | skill.py | 避免LLM猜错目标数据源 |
| extract-image-info 修复 | skills/e5be982a | `llm_vision(file_path, prompt)` 直接传路径 |
| data-etl 修复 | skills/21de3207 | `"create"`→`"fail"`、删死代码、删 import inspect |
| Excel create_new_file 平台能力 | tool_guidance.py | 改为 False（不支持创建新 Excel 文件） |

**与前轮关系**：第十~十三轮建立编辑原语（edit_and_run/apply_partial_code）+ 调试模式（极简 prompt/thinking/修改尝试正法）；本轮补齐静默失败审查 + OpenCode 调试显示对齐。read_script 无 cap 对齐 OpenCode（靠指令引导 offset/limit，不靠硬限制）；错误退出靠平台信号词匹配 + 执行错误计数 + 修改次数上限（不靠错误分级，分级机制后续已删除）。

### 第十五轮（规则全量实现 + 安装修复 + 资产打包 + 架构清理）

**核心洞察**：第十四轮补齐了调试显示和静默失败审查，但规则检查只有 39% 有确定性实现（61% 靠 LLM 主观判断或完全没实现）；安装流程多处断裂（poetry-core 下载超时/passlib 与 bcrypt 4.x 冲突/npm run install 不装 devDependencies）；技能/流程/算子无法跨机器迁移。

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

**与前轮关系**：第十四轮补齐调试显示和静默失败审查；本轮补齐规则实现（39%→78% 有确定性检查）+ 修复安装链路（3 个阻断性 bug）+ 资产打包机制。规则仍无法确定性实现的（DQ-TIM/DQ-ETL-010/DQ-BIZ/SEC-CLASS-002~003/SEC-COMP 等）保持 LLM prompt 判断。

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

### 第十七轮（对齐 OpenCode 调试优化——工具精简 + runtime 自动交接 + 视觉模型 + 备用模型 + SSE 修复）

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
| **data_processor_agent 精简** | data_processor_agent.py | 删除 `_analyze_error`（错误分析）+ `_save_session_log`（会话日志）+ `_compress_tool_result`（工具结果压缩）；删除调试循环中的上下文压缩（`should_compact` 检查）；模型选择统一为 `llm_manager._default` |
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

### 第二十二轮（调试对话流式化 + 执行进度归档 + Inspector 诊断日志 + StuckDetector 收紧 + 关于页 + semantic-classify 地名映射）

**核心洞察**：主对话循环用非流式 `chat_with_tools`，用户等待时间长无反馈；调试执行进度在前端切换阶段时被直接清空丢失；Inspector handoff 触发原因不可观测；StuckDetector 阈值过松（5 轮调查 / 30 轮总计）。本轮补齐这些可感知差距。

| 改进 | 文件 | 说明 |
|------|------|------|
| **主对话循环流式化** | data_processor_agent.py | `run()` 从非流式 `chat_with_tools` → 流式 `chat_stream_with_tools_and_thinking`，实时 yield `model`/`thinking`/`content` 事件（避免长时间无响应）；流式失败时回退非流式 |
| **执行进度归档** | SkillView.vue | `archiveExecutingMsg(msg)`：阶段切换时把 executingMsgs 固化到 `msg.stdouts`（不拼进 content 保持纯净），替代直接 `clearExecutingMsg` 丢失日志；3 个 handler 全部接入 |
| **Inspector 报告诊断日志** | data_inspector_agent.py | INSPECT_RESULT / FIX_COMPLETED 分支各加 `logger.info("[Inspector-DEBUG] report_len=... report_preview=...")` |
| **handoff 诊断日志** | data_processor_agent.py | `run_debug` handoff 触发处加 4 条 `logger.info("[handoff检查] ...")`（written_tables / output_table / debug_max_inspections / 跳过原因） |
| **SSE 调试日志** | multi_agent.py + main.py | `stream_agent_events_sse` 加 `[SSE-DEBUG]` 日志（event type / agent_switch / done / inspector content）；main.py 日志过滤器扩展匹配 `[SSE-DEBUG]`/`[Inspector-DEBUG]`/`[handoff检查]` |
| **StuckDetector 收紧** | agent_utils.py | `investigate_threshold` 5→3，`max_total_rounds` 30→15；删除 `_total_rounds >= max` 时的重置（保留计数） |
| **StuckDetector 强制退出扩展** | data_processor_agent.py | 强制退出条件加 `"只调查" in _stuck_hint`（后于本轮 StuckDetector 收紧，在第二十三轮 Handoff 重构时改回只 `"总轮次上限"`） |
| **tool_result 扩容** | chat.py | 转发给前端的 content 截断 200→2000 字符 |
| **done 事件结论保留** | chat.py | `done` 事件不再 pass——提取 `result.content` 追加 yield（修复 done 时结论丢失） |
| **CORS 通配规范** | chat.py | `allow_credentials` 改为 `"*" not in _cors_origins`（通配源时关闭 credentials，符合浏览器规范） |
| **内部 API 地址可配置** | skill_runner.py | 模板加 `_API_BASE = os.environ.get("DATACRAB_API_BASE", "http://localhost:8000")`；13 处硬编码 localhost:8000 替换 |
| **_param_count 修复** | skill_runner.py | 补算 `vararg`/`kwarg`（+1 each），修复 *args/**kwargs 入口函数检测 |
| **关于页** | AboutView.vue（新增）+ ConfigView.vue | 关于页面展示项目简介、核心特性、技术栈、开源地址；配置页加"关于"tab |
| **vite 网络配置** | vite.config.ts | `server.host` 加 `0.0.0.0`（允许外部访问）；`/api` 代理加 error 日志 |
| **semantic-classify 地名映射** | data/skills/26d263ab | system_prompt 重写为"中国地理信息提取专家"；新增 15 条历史地名映射（沙市→荆州、万县→重庆等）+ 自治州/直辖市规则 |
| **SSE 事件分类处理** | chat.ts | 拆分 `tool_result`/`agent_switch`/`inspecting`/`retry`/`round` 的 executingMsg 赋值逻辑 |

**与前轮关系**：第二十一轮的 SSE 日志 + executingMsg 机制基础上，本轮补齐进度归档（不丢失）+ 诊断日志（handoff 可观测）+ 流式化（主对话不卡）。StuckDetector 收紧（3/15）在第二十三轮被进一步简化（删除"只调查"检测）。

### 第二十三轮（Handoff 提到 RunTime + skill_runner 归并 + StuckDetector 简化 + 非流式端点删除 + 上下文压缩改进）

**核心洞察**：Handoff 之前由 Agent `yield {"type":"handoff"}` 发起，Agent 需要感知 handoff 存在 + 自己决定何时交接——违反 Orchestrator-Worker 原则（Agent 应专注任务，流程编排由 RunTime 负责）。skill_runner 有 3 个函数（`run_skill_script`/`run_skill_script_by_content`/`run_skill_script_streaming_by_content`）功能重叠。`POST /messages` 非流式端点与流式端点重叠。本轮做架构层面减法。

| 改进 | 文件 | 说明 |
|------|------|------|
| **Handoff 提到 RunTime** | multi_agent.py | `AgentRuntime.run()` 重写：从 Agent yield handoff → RunTime 拦截 `done` 事件调用 `_decide_handoff()` 决策；新增 `_extract_issues()` 从检查结果提取 error/critical/fatal；Processor 执行成功 → Inspector；Inspector 有 error/critical → Processor；fatal/warning 靠人判断 |
| **删 handoff 工具** | data_processor_agent.py + data_inspector_agent.py | 两 Agent 删除 handoff 工具 schema + `_execute_tool` 分支 + `run()` 中 `_handoff` 信号解析；Agent 不感知 handoff 存在 |
| **Prefix Cache 静态化** | data_processor_agent.py | `build_system_prompt()` 进程级 memoize（`_MAIN_STATIC_PROMPT_CACHE`）；datasource_context 移出 system prompt → 注入为 user 消息前缀；system 字节稳定命中 GLM prefix cache |
| **动态提示分离** | data_processor_agent.py | 新增 `build_debug_dynamic_hints(context)`：入口函数/最近成功参数/本次参数/数据源表上下文 → 注入为 user 消息前缀（不进 system prompt） |
| **skill_runner 三函数合一** | skill_runner.py | `run_skill_script`/`run_skill_script_by_content`/`run_skill_script_streaming_by_content` 合并为 `run_skill_script_streaming`（支持 `skill_path` 或 `script_content`）；`run_skill_script` 非流式委托流式版丢弃 progress 只取 result；净减 ~685 行 |
| **_stream_execute 共享核心** | skill_runner.py | 新增 `_stream_execute(proc, timeout, temp_path)`：双层超时（idle 无输出 + hard cap 总时长）+ 标记行解析 + 异常类名提取（`_extract_exception_type`）；不再过滤 `[WARN]` 行全部透传 |
| **删 POST /messages** | chat.py + chat.ts | 删除非流式 `POST /messages` 端点（~95 行）+ 前端 `sendMessage()` 方法 |
| **StuckDetector 简化** | agent_utils.py | 删除"只调查不修改"检测（`INVESTIGATION_TOOLS`/`FIX_TOOLS`/`investigate_threshold`/`_investigate_count` 全删）；只保留空转检测 + 总轮次上限 |
| **压缩改进** | agent_utils.py + chat.py | `extract_identifiers_from_messages` 增强（从 tool_calls.arguments 抽取）；`compact_messages` 旧消息截断 500→1000 + tool_calls 摘要列参数 + 摘要 role system→user（避免 system 污染 prefix cache）；`_HISTORY_SUMMARIES` 改 OrderedDict LRU（100 上限） |
| **跨 handoff 上下文持久化** | data_processor_agent.py | `run_debug` Inspector 回交时从 `context["_processor_local_messages"]` 恢复工具调用历史（对齐 OpenCode 连续消息链）；`_should_handoff` 时保存 |
| **Inspector 输出简化** | data_inspector_agent.py | content 输出从逐 token → 一次性 yield；`check_results` 写入 `context["_check_results"]`；done 事件带 `check_results`（供 RunTime `_extract_issues`） |
| **format_report 表格化** | inspector_tools.py | 列概览 + 问题列表从纯文本 → Markdown 表格；`except: pass` → `dq_rules = {}` 兜底 |
| **DQ 空值检测增强** | inspector_tools.py | DQ-COM-003/001 object 类型列加空字符串检测；severity 从硬编码 → 从 `dq_rules` 读取 |
| **PostgreSQL autocommit** | connectors.py | `connect()` 加 `await self._connection.set_autocommit(True)` |
| **SkillView SSE 共享** | SkillView.vue | 新增 `processDebugSSEEvent()` + `readDebugSSEStream()` 共享函数；3 处 handler 内联 SSE 代码替换为调用 |
| **大表处理提示** | prompt_docs.py | PLATFORM_CONVENTIONS_DOC 加"周期性 log/print 进度避免被判定卡死" |

**与前轮关系**：第十七轮"删 handoff_to_inspector 工具"只删了工具 schema 但 Agent 仍通过 yield handoff 发起交接；本轮彻底把 handoff 决策提到 RunTime（Agent 完全不感知）。第十三轮"只调查不修改"检测器在第二十一轮以温和形式回归，本轮再次删除（架构决策：调查是合法行为不应惩罚）。第十六轮 Prefix Cache 静态/动态分区在本轮进一步深化（datasource_context 也移出 system prompt）。

### 第二十四轮（System Prompt 精简 + 调试显示对齐 OpenCode + soul.md 压缩 + tool_guidance 拆分）

**核心洞察**：soul.md 95 行冗长，安全红线与人格定义混在一起；DATA_PROCESSOR_INSTRUCTIONS 的"扩展能力"分节过详细；tool_guidance 主对话也注入调试工具表（主对话不需要 edit_script/run_script）；调试工具调用和结果混在 content 里（不像 OpenCode 的独立 action/summary 卡片）；前端 history 把工具卡片也传给后端（浪费 token + 干扰 LLM）。

| 改进 | 文件 | 说明 |
|------|------|------|
| **soul.md 压缩 95→30 行** | soul.md | 删除冗长行为规则/禁止回复/替代回复段（安全红线移到 instructions）；保留核心：身份定义、能力清单、风格 |
| **DATA_PROCESSOR_INSTRUCTIONS 重写** | data_processor_agent.py | 加"安全红线"段（从 soul.md 移入）；"工作准则"6→5 条；"扩展能力"分节 → 4 条 one-liner |
| **tool_guidance 主对话/调试拆分** | tool_guidance.py | `TOOL_CAPABILITY_TABLE` 拆为 `_MAIN_TOOL_CAPABILITY_TABLE` + `_DEBUG_TOOL_CAPABILITY_TABLE`；`get_tool_guidance(debug=False)` 参数；主对话不注入调试工具表；删"工具选择原则"段 |
| **反幻觉 standard 级具体化** | data_processor_agent.py | 从原则 → 具体操作约束（"提到表名前先调 get_table_schema"） |
| **llmContent 分离** | SkillView.vue | 消息对象新增 `llmContent` 字段（只含 LLM 输出不含工具卡片）；history 提取用 `m.llmContent ?? m.content`（只传 LLM 输出给后端） |
| **tool_action/tool_summary 独立事件** | data_processor_agent.py + SkillView.vue | 工具调用从 `yield content` → `yield {"type":"tool_action","actions":[...]}` 独立事件；工具结果从 `yield content` → `yield {"type":"tool_summary","summaries":[...]}` 独立事件；前端带时间戳卡片 |
| **read_script 50KB cap** | data_processor_agent.py | 加 `_MAX_READ_BYTES = 50KB` 硬 cap（后于本轮在第二十五轮删除恢复默认 2000 行） |
| **grep_script 匹配上限** | data_processor_agent.py | `_MAX_MATCHES` 50→20 |
| **_slim_run_script_result** | data_processor_agent.py | 新增：精简 run_script 工具结果（成功只留 summary+written_tables；失败只留 error+error_type） |
| **executingMsg 生命周期修复** | chat.ts | `error`/`done`/`content` 事件时 `msg.executingMsg = ''`（修复蓝色转圈残留）；`round` 事件显示"第 N 次修改" |
| **DEBUG_INSTRUCTIONS 推理中文** | data_processor_agent.py | 加"推理过程用中文" |
| **archiveExecutingMsg → stdouts** | SkillView.vue | 从拼进 content → 存到 `msg.stdouts` 独立字段（保持 content 纯净） |
| **删主对话 round 事件** | data_processor_agent.py | `run()` 主对话删除每轮 `yield {"type":"round"}`（避免"第N轮"转圈困扰用户） |
| **round 事件 last_chance** | data_processor_agent.py | `run_debug` round 事件带 `last_chance` 标志（最后一次修改机会） |
| **删 modify_script merged_preview** | data_processor_agent.py | 返回删除 `merged_preview`（8000+3000 字符） |

**与前轮关系**：第十七轮 tool_guidance 已有主对话/调试拆分雏形（`get_tool_guidance(debug=)`），本轮彻底分离（主对话完全不注入调试工具表）。第十六轮 Prefix Cache 稳定（datasource_context 移出 system）在本轮配合 soul.md 压缩进一步减少 system prompt 体积。llmContent 分离是第二十三轮"history 透传净化"的前端实现。

### 第二十五轮（调试工具精简至 4 个 + Inspector 报告独立事件 + 前端复制按钮 + 版本号动态生成 + Docker 部署完善）

**核心洞察**：调试工具从 7 个（edit_script/run_script/read_script/grep_script/modify_script/modify_and_run/edit_and_run）精简至 4 个（edit_script/run_script/read_script/grep_script，完全对齐 OpenCode Grep/Read/Edit/Bash）——modify_script/modify_and_run/edit_and_run 的 schema+处理器保留但不暴露给调试 LLM，因为 edit_script（行级补丁）已覆盖所有修改场景，暴露多个修改工具只会让 LLM 困惑选择。Inspector 报告从混在 content 里 → 独立 `inspection_report` 事件。版本号从硬编码 1.0.0 → git 动态生成。Docker 部署从 dev 模式 → nginx 托管构建产物。

| 改进 | 文件 | 说明 |
|------|------|------|
| **调试工具精简至 4 个** | data_processor_agent.py | `DEBUG_TOOLS` 从 7 个 → 4 个（`[EDIT_SCRIPT_TOOL, RUN_SCRIPT_TOOL, READ_SCRIPT_TOOL, GREP_SCRIPT_TOOL]`）；删 modify_script/modify_and_run/edit_and_run 三个工具 schema + `_execute_tool` 分支；`run_debug` 中三处判断 → 只 `run_script` |
| **Inspector 报告独立事件** | data_inspector_agent.py | INSPECT_RESULT/FIX_COMPLETED 分支：`yield {"type":"content", ...}` → `yield {"type":"inspecting", "message":"..."}` + `yield {"type":"inspection_report", "report": report}` |
| **Inspector tool_result 不转发** | multi_agent.py | Inspector `tool_result` 事件不再转发（`pass`，报告已通过 `inspection_report` 格式化发送） |
| **history 透传净化** | skill.py + operator.py + pipeline.py | 删除"智能选择历史"逻辑 → 直接透传 `request.history`（前端已用 `llmContent` 净化）；删除 history content `[:500]` 截断 |
| **前端复制按钮** | SkillView/OperatorView/PipelineView.vue | 用户消息/推理过程/返回数据/检查结果/检查问题均加复制按钮（`<el-button text size="small">`） |
| **OperatorView/PipelineView llmContent** | OperatorView.vue + PipelineView.vue | 同 SkillView 加 `llmContent` 字段 + `tool_action`/`tool_summary`/`inspection_report` 事件处理 + 删 `tool_result` 事件 |
| **retry/round 文案统一** | 三处调试页 | `retry` "第N次修复尝试"→"开始修复..."；`round` "修改尝试"→"修改" |
| **read_script 50KB cap 删除** | data_processor_agent.py | 删除 `_MAX_READ_BYTES` 硬 cap（恢复默认 2000 行）；hint 改为"用 offset 翻页" |
| **版本号动态生成** | version.py（新增）+ main.py + config.py | `get_version()`：`YYYY.MM.DD.提交次数`（git log 生成，`@lru_cache` 缓存）；启动时 `settings.APP_VERSION = get_version()`；新增 `GET /config/version` 端点 |
| **前端版本显示** | version.ts（新增）+ MainLayout.vue + LoginView.vue + AboutView.vue | Pinia store `useVersionStore`：`loadVersion()` 调 `GET /config/version`；侧边栏底部 + 登录页 + 关于页显示版本号 |
| **Docker nginx 托管** | frontend/Dockerfile + docker-compose.yml + nginx/nginx.conf | 前端多阶段构建：builder `npm run build` → 运行阶段 `nginx:alpine` 托管 `dist/`；SPA 路由回退；frontend 端口 5173→80 |
| **SSE 长连接支持** | nginx/nginx.conf | `proxy_buffering off` + `proxy_read_timeout 300s` + `proxy_cache off` + `proxy_http_version 1.1` + `Connection ""` |
| **DATACRAB_API_BASE 配置** | config.py + .env.example + docker-compose.yml | 新增 `DATACRAB_API_BASE` 配置项（skill_runner 子进程通过它访问后端 API）；Docker 中设为 `http://backend:8000` |
| **backend_data 卷持久化** | docker-compose.yml | backend volumes 加 `backend_data:/app/data`（数据持久化） |
| **semantic-classify 行政区划** | data/skills/26d263ab | 新增 `_PREFECTURE_CITIES` frozenset（340 个全国地级以上行政区划白名单）；`_load_data` 重写用 `iter_table_data` 分块读取 + 行数校验 |
| **semantic-merge-records 筛选增强** | data/skills/7940a035 | `contains` 筛选支持 `or` 语法；"类似语义"关键词展开为同义词列表 |

**与前轮关系**：第十~十一轮建立的行级补丁原语（edit_script/apply_partial_code）在本轮成为唯一修改入口（modify_script 等不再暴露），简化 LLM 工具选择面。第二十三轮 Inspector `check_results` 写入 context 供 RunTime `_extract_issues` 在本轮配合 `inspection_report` 独立事件让前端格式化展示。第二十四轮 llmContent 分离在本轮扩展到 OperatorView/PipelineView。版本号动态生成是对 Prefix Cache 理念的延伸（版本号不稳定不影响 cache，因为版本在 user 侧显示不在 system prompt 中）。

### 第二十六轮（DataAnalystAgent 集成——只读分析智能体落地）

**核心洞察**：DataProcessor 同时承担「修改数据」与「只读分析」两类请求，导致分析类问题也走复杂信息链（handoff + 修改计数 + 压缩 + 自愈），既浪费 token 又让 LLM 困惑。按 Orchestrator-Worker 原则拆分职责：只读分析（查询/统计/分布/洞察）由独立 DataAnalystAgent 承担，简单线性信息链、无 handoff、无修改计数；修改类请求仍走 DataProcessor + DataInspector 自愈闭环。三者并列为完整多智能体架构。

| 智能体 | 职责 | 触发场景 |
|---|---|---|
| **DataProcessor** | 修改数据/脚本：清洗、转换、分类、ETL | 修改类请求（默认兜底） |
| **DataInspector** | 对加工后数据做标准/质量/安全检查 | DataProcessor 执行成功后 RunTime 自动 handoff |
| **DataAnalyst** | 只读分析：查询、统计、分布、洞察（不修改数据） | 只读分析类问题，chat_router 关键词路由 |

**边界规则**：是否修改数据/脚本。只查不改 → DataAnalyst；要修改 → DataProcessor。

**触发与路由**（`chat.py` + `chat_router.py`）：
- **关键词路由**：含"查询/统计/分析/分布/多少/查看/列出"且不含"清洗/转换/修改/处理/分类/写入"→ DataAnalyst
- **技能路由**：用户指定技能时，按技能类型（`skill_type` 字段）分派——分析类技能（`analysis`）走 DataAnalyst，处理类技能（`processing`，默认）走 DataProcessor
- **默认兜底**：无法判断时走 DataProcessor（保持现有行为不变）

| 改进 | 文件 | 说明 |
|------|------|------|
| **DataAnalystAgent 类** | data_analyst_agent.py（新增，488 行） | `run()` 流式方法 + 简单线性信息链（system + user + tool + 结论，无跨 handoff 持久化、无修改计数、无 StuckDetector 修改检测，保留空转检测 + 总轮次上限）；`run_debug()` 分析技能调试复用 DataProcessor 调试循环；上下文压缩保留（`should_compact` / `compact_messages`）；独立截断阈值 `ANALYSIS_MAX_TOOL_RESULT_CHARS=30000` / `ANALYSIS_MAX_PREVIEW_ROWS=50`；system prompt 进程级 memoize（Prefix Cache） |
| **只读工具子集** | shared_tools.py | 定义 `ANALYSIS_TOOLS`（5 个：query_table_data/get_table_schema/list_user_datasources/execute_sql/kb_search，从 SHARED_TOOL_SCHEMAS 提取）；不暴露 write_table_data / save_file_to_link / 调试工具（edit_script/run_script 等） |
| **注册 + 不参与 handoff** | multi_agent.py | `ensure_agent_runtime()` 注册 DataAnalystAgent（line 287-302）；`_decide_handoff` 对 data_analyst 返回 None（line 210）—— DataAnalyst 不参与 handoff |
| **路由判断** | chat.py + chat_router.py | 关键词路由 + 技能 skill_type 路由 → 选 Agent |
| **skill_type 字段** | skill_parser.py | 解析 SKILL.md front matter 的 `skill_type`（analysis=分析类 / processing=处理类，默认 processing 保持兼容） |
| **前端调试按钮** | SkillView.vue / ChatView.vue | 分析类技能不显示调试按钮（只读无需调试） |

**流式输出**：`thinking`（推理过程）/ `content`（分析结论）/ `tool_action`（工具调用显示，复用 debug 分离设计）/ `tool_summary`（工具结果摘要）/ `done`（结束，无 handoff）；**不发** `round`/`inspecting`/`retry`/`give_up`/`platform_issue`。

**与前轮关系**：本轮是职责拆分类改动（Orchestrator-Worker），不改 DataProcessor `run()`/`run_debug()` / DataInspector / multi_agent runtime handoff / ConvergenceGuard / experience 正反例 / compact_messages / debug 模式。DataAnalyst 不修改数据故无正反例经验采集。

### 第二十七轮（错误分级机制彻底删除——死代码清理 + 文档校正）

**核心洞察**：第十四轮引入"错误分级退出"（`_classify_execution_error` L4/L5/L6 → 环境问题/平台限制/数据问题），第十七轮引入 `_llm_classify_error`（LLM 重分类 4 类）。这两套分级机制在第二十一轮"模型选择简化"时已删 skill_runner 侧函数定义，但 data_processor_agent 侧的消费者代码（行1868-1873 死代码分支 + 行1939-1963 末尾 LLM 分类兜底）+ DEBUG_INSTRUCTIONS 的"错误判断"指令段 + AGENTS.md 多处记录均未同步删除。死代码分支 `any(kw in _err_type for kw in ("环境问题","平台限制","数据问题"))` 永不命中（`_extract_exception_type` 只提取英文异常类名如 `RuntimeError`，不含中文词），末尾 LLM 分类兜底分类后都走 give_up 无分支差异（死逻辑）。

**当前错误处理机制（分级删除后，第二十八轮进一步删除平台信号词）**：
1. **执行错误计数**（`_exec_failures_before_success` ≥ `_MAX_EXEC_FAILURES`=3）：首次成功前连续 3 次执行失败 → `give_up` 退出
2. **修改次数上限**（`_fix_attempts` ≥ `max_fix_attempts`=7）：总修改次数达 7 次 → `give_up` 退出
3. **LLM 自主判断**：DEBUG_INSTRUCTIONS 引导"能修就修，修不了就说明原因停止"，不强制分类标签
4. **StuckDetector 兜底**：30 轮总轮次上限 → 强制退出

> 注：第二十七轮记录的"平台信号词匹配"（`_PLATFORM_FAILURE_SIGNALS`）在第二十八轮被彻底删除——信号词与 skill_runner 实际 print 措辞不匹配（中文信号词 vs 英文 `failed`），LLM 自主判断更可靠。

| 改进 | 文件 | 说明 |
|------|------|------|
| **删死代码分支** | data_processor_agent.py | 删 `any(kw in _err_type for kw in ("环境问题","平台限制","数据问题"))` 分支（永不命中，`_err_type` 是英文异常类名）；删 `_err_type` 局部变量赋值（无消费者） |
| **删末尾 LLM 分类兜底** | data_processor_agent.py | 删修改次数用完后的 LLM 分类调用（问 LLM 分 代码问题/平台限制/环境问题 三类，分类后都走 give_up 无分支差异）；简化为直接 `give_up` + `done` |
| **DEBUG_INSTRUCTIONS 错误判断段删除** | data_processor_agent.py | 删"错误判断"段（教 LLM 按"非脚本错误：xxx"格式输出，但无代码消费此标签）；替换为极简"看 traceback 自主判断：能修就修，修不了就说明原因停止" |
| **AGENTS.md 记录校正** | AGENTS.md | 第十四轮标题/表格/前轮关系删"错误分级退出"；第十七轮标题/表格删"错误分类 LLM 推断"；skill_runner 职责描述改"错误分类 LLM 推断"→"异常类名提取"；行635 `_stream_execute` 描述改"错误分类"→"异常类名提取" |

**验证**：`app.main` 完整加载 182 路由；`_llm_classify_error`/`_classify_execution_error` 函数定义已不存在（grep 全空）。

**与前轮关系**：第十四轮"错误分级退出" + 第十七轮"错误分类 LLM 推断"在本轮彻底删除（代码 + 文档）。当前错误退出靠平台信号词匹配 + 执行错误计数 + 修改次数上限三层兜底，LLM 自主判断修复可行性（不靠分类标签）。`_PLATFORM_FAILURE_SIGNALS` 信号词与 skill_runner 实际 print 措辞不匹配的问题（中文信号词 vs 英文 `failed`）已知，后续可补信号词对齐。

### 第二十八轮（资产管理导入导出 + LLM 配置去全局化 + 跨平台安装 + 对齐 OpenCode 调试 + 资产去全局化）

**核心洞察**：第二十七轮清理了错误分级死代码，但此后积累了多项重大特性却未更新文档。本轮汇总第二十七轮之后的所有改动——最显著的是新增**资产导入导出**（7 类资产一键 ZIP 迁移，解决跨机器迁移痛点）、**LLM 配置去全局化**（删全局 provider/api_key/model，强制用户配置，配合 `.env` 清理 LLM 硬编码）、**对齐 OpenCode 调试模式**（删平台信号词匹配 + 删 Docker/nginx 回归开发模式）。

**资产管理导入导出（asset_io.py + assets.py）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **资产导出/导入服务** | asset_io.py（新增） | 7 类资产（skills/operators/pipelines/llm_config/custom_extensions/datasources/schedules）ZIP 打包迁移；API Key/密码不导出（导入后手动填）；按 name 去重 + 按类型独立覆盖（overwrite_types）；skill_calls 用 skill_name 跨机器引用，导入时反查 skill_id；调度 task_target_id→task_target_name 跨机器稳定；datasources 导入含连接配置含密码（虚拟数据源不导出） |
| **资产端点** | assets.py（新增） | `GET /assets/counts`（各资产数量统计，按 created_by 筛选）+ `POST /assets/export`（导出 ZIP，时间戳命名当地时区）+ `POST /assets/import/preview`（manifest 预览）+ `POST /assets/import`（导入，types/overwrite_types 逗号分隔） |
| **is_virtual 列** | models/datasource.py + main.py | `data_sources` 加 `is_virtual` 列（DB 列替代 property，SQL 层直接过滤）；虚拟数据源（聊天上传）受保护：不可修改/删除/测试/同步/导出；启动自动迁移从 tech_metadata 回填 |
| **统一 author→created_by** | skill.py + operator.py + 各模型 | skill/operator 的 `author` 字段统一为 `created_by`；10 个模型均含 `created_by`（FK users.id） |
| **seed 资产加载删除** | main.py | 删除从 `data/seed/operators.json`/`pipelines.json` 加载逻辑；仅保留技能磁盘扫描同步 + 内置流程/调度 seed（按 is_builtin 查重，用户删除后不复活） |

**LLM 配置去全局化（bab52b9）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **删全局属性** | llm.py | 删 `llm_manager` 的 `provider`/`api_key`/`api_base`/`model`/`embedding_model`/`fallback_models` 全局属性；新增 `_require_user_cfg()` 强制基于用户配置（contextvar），未配置抛 RuntimeError |
| **vision_model 字段** | models/custom_extension.py + llm.py + config.py | LLMProvider + UserLLMConfig 加 `vision_model` 列；Provider 注册表加 `default_vision_model`/`default_embedding_model`；`_eff_vision_model` 优先用户配置→Provider 默认；前端 ModelConfigView 加视觉/向量模型配置 UI |
| **.env 清理 LLM 硬编码** | .env.example | 删除 `LLM_PROVIDER`/`OPENAI_API_KEY`/`OPENAI_MODEL`/`OPENAI_API_BASE` 等硬编码；LLM 配置全在前端「系统设置-大模型管理」页面管理（存 DB） |
| **create_new 写入策略** | connectors.py | PG/MySQL/SQLite/CSV/Excel 5 种连接器支持表已存在时自动找新表名（_1/_2 后缀） |
| **缺源检测** | chat.py | `_match_datasource_names` 抽出；数据操作关键词但未匹配到数据源时提示用户指定 |

**对齐 OpenCode 调试模式（2bd1a58）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **删平台信号词匹配** | data_processor_agent.py | 删 `_PLATFORM_FAILURE_SIGNALS` + `_has_platform_failure_in_warnings` + `is_platform_issue`；靠 LLM 看 error+stdout 自主判断（对齐 OpenCode 让 LLM 看 traceback） |
| **删超时引导** | data_processor_agent.py | 删错误类型判断→LLM，系统不给约束 |
| **_has_fix 只算 run_script** | data_processor_agent.py | `edit_script` 不算修改尝试（对齐用户设计：3 次执行错误 + 7 次检查循环） |
| **Docker/nginx 删除** | docker-compose.yml + Dockerfile×2 + nginx.conf | 回归开发模式（第二十五轮添加的 Docker 部署被删除） |
| **StuckDetector 增强** | agent_utils.py | 新增"只调查不修改"检测（连续 5 轮只 read/grep 不 edit/run → 提示）+ 总轮次上限（30 轮 → 强制退出）；INVESTIGATION_TOOLS/FIX_TOOLS 工具分类 |

**跨平台后端依赖安装（208294d）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **install-backend.js** | scripts/install-backend.js（新增） | 检测 Python 3.11+ 与 sqlite3 模块后再装后端依赖；依次尝试 py -3 / python3 / python；失败回退核心依赖（requirements.txt）；解决系统 pip 绑定旧 Python / Windows 不在 PATH / 缺 sqlite3 报错不友好 |
| **pyproject.toml** | pyproject.toml | `requires-python` 3.9→3.11，补 tzdata/pillow/opencv-python-headless |
| **SQLite 路径锚定** | config.py | SQLite 相对路径锚定到 backend/ 目录，避免启动 cwd 不同读到错误的数据库文件 |

**其他改进**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **DataAnalyst 调试模式** | data_analyst_agent.py + skill.py + multi_agent.py | 新增 `run_debug()`——3 次执行错误上限，无 Inspector handoff，无修改次数限制；skill_type 路由（analysis→data_analyst / processing→data_processor）；tags 变更同步 SKILL.md front matter |
| **classify_execution_result 共享** | data_processor_agent.py | 抽出 `classify_execution_result`/`_build_platform_reason`/`_record_negative` 共享 helper，供 DataProcessor + DataAnalyst 复用 |
| **Inspector severity 校正** | inspector_tools.py | 所有检查规则 severity 从硬编码改为规则库读取（`_dq_severity`/`_sec_severity`）；format_report 增加按规则 ID 的明细表格；fatal→critical 统一 |
| **resolve_column 删 LLM 匹配** | inspector_tools.py | 删除 LLM 列名模糊匹配，改为机械匹配 |
| **skill_type 全链路** | skill_parser.py + skill_creator.py + SKILL_SPEC.md | 解析 SKILL.md front matter `skill_type` 字段；生成技能强制写 skill_type + 判定规则文档 |
| **flash_model 列迁移修复** | main.py | 旧列 `fast_model`→`flash_model` 数据迁移 + 新数据库无条件添加 `flash_model`/`vision_model`/`embedding_model` 列 |
| **单 Agent 服务删除** | agent.py | 删除 `agent.py`（284 行，非流式 /chat），无残留引用 |

**验证**：`app.main` 完整加载 187 路由（+5 资产端点）；`_PLATFORM_FAILURE_SIGNALS`/`_has_platform_failure_in_warnings`/`is_platform_issue` grep 全空（已删除）；`docker-compose.yml`/`Dockerfile`/`nginx.conf` 均不存在；`asset_io.py`/`match_service.py`/`assets.py` 存在；`.env.example` 无 LLM 硬编码。（注：路由数在第三十轮为 187 API + 1 health = 188）

**与前轮关系**：第二十五轮添加的 Docker 部署在本轮被删除（回归开发模式）。第二十七轮记录的"平台信号词匹配"在本轮被彻底删除。第十四轮的 `create_new_file` Excel 平台能力标记为 False 在本轮由 `create_new` 写入策略实现（5 种连接器支持自动找新表名）。第十五轮的 seed 算子/流程加载逻辑在本轮删除（改用资产导入导出替代 seed 文件）。

## 现状校正（文档 vs 代码实际）

以下为历史轮次记录与代码实际状态的差异，经代码审查确认的勘误（行号以当前代码为准）：

| 轮次 | 记录 | 实际代码 |
|------|------|---------|
| 第十九轮 | "DB model 删 2 个 Column（LLMProvider.fast_model + UserLLMConfig.fast_model）" | `flash_model` 列仍存在于 `models/custom_extension.py`（line 40, 62）；`llm.py` 仍读写 `flash_model`（line 96/107/271/283-284/303/471/524/536 等 12 处，含 `_flash` 属性 line 471）。业务路径用 `_default`/`_flash` 属性间接消费，DB 列未删除（向后兼容） |
| 第二十二轮 | "主对话循环流式化：run() 从非流式 chat_with_tools → 流式 chat_stream_with_tools_and_thinking" | `run()`（line 469）实际仍用非流式 `chat_with_tools()`（line 533）；仅 `run_debug()`（line 1551）用流式 `chat_stream_with_tools_and_thinking`（line 1690） |
| 第二十五轮 | "调试工具精简至 4 个" | 实际暴露 5 个：`DEBUG_TOOLS`（line 149）含 4 核心（edit_script/run_script/read_script/grep_script）+ 第 151 行追加 `list_user_datasources`（从 SHARED_TOOL_SCHEMAS 提取） |
| 第二十三轮 | "skill_runner 三函数合一为 run_skill_script_streaming" | 实际保留 6 个函数：`run_skill_script`（631）/`run_skill_script_async`（659）/`run_skill_script_streaming`（898）/`run_skill_script_streaming_async`（995）/`run_skill_script_by_content`（1043）/`run_skill_script_by_content_async`（1066），含 async 包装器 |
| 第十五轮 | "启动自动 seed 算子：operators 表为空时从 data/seed/operators.json 加载" | 第二十八轮已删除 seed 算子/流程加载逻辑（改用资产导入导出替代）；`data/seed/operators.json` 不存在；`main.py` `_seed_skills_and_pipelines` 仅保留技能磁盘扫描 + 内置流程/调度 seed（按 is_builtin 查重） |
| 路由数 | 第二十一轮记录"183 条路由" | 实际 188 条路由（187 API + 1 health；第三十轮：skills 30 / datasources 24 / operators 18 / permissions 18 / config 16 / pipelines 13 / chat 12 / schedules 12 / filelinks 9 / metadata 7 / auth 6 / agents 5 / knowledge 5 / custom_extension 6（含 connectors+providers）/ assets 4 / filesystem 1 / llm 1 / health 1） |
| 第二十五轮 | "Docker 一键部署：前端多阶段构建 nginx 托管 + SSE 长连接支持" | 第二十八轮（2bd1a58）已删除 Docker/nginx 全部配置（`docker-compose.yml`/`Dockerfile`×2/`nginx/nginx.conf` 均不存在），回归开发模式 |
| 第二十七轮 | "当前错误处理机制含平台信号词匹配（_PLATFORM_FAILURE_SIGNALS）" | 第二十八轮（2bd1a58）已彻底删除平台信号词匹配（`_PLATFORM_FAILURE_SIGNALS`/`_has_platform_failure_in_warnings`/`is_platform_issue` grep 全空），靠 LLM 自主判断 + 执行错误计数 + 修改次数上限三层兜底 |
| 第二十六轮 | "关键词路由：含查询/统计/分析…→ DataAnalyst" | 第三十轮已删除关键词路由，改为 `classify_message` LLM 语义判断 msg_type（analysis/processing/chat）→ 选 Agent；chat_router 不再依赖关键词列表 |
| 第二十九轮 | "classify_message 返回 (msg_type, keep_data, events)" | 第三十轮（d2c13dd）已改为返回 `(msg_type, keep_source, keep_target, keep_skill, events)` 4 段 keep；keep_data 单段 keep 已不存在 |
| 第二十九轮 | "skip_steps 机制（request.skip_steps 控制 tables/pipelines 跳过）" | 第三十轮已彻底删除 skip_steps（schema `ChatMessageCreate.skip_steps` + 前端 + 后端全清）；改用 4 段 keep + 已选跳过判断 |
| 全局 | "skill/operator/pipeline 的 category 字段" | 第三十轮已删除 category 字段（skill→skill_type / pipeline→pipeline_type / operator 无分类字段）；schema + model + match_service 全清 |
| 第三十轮 | "classify 不传 context 信息给 LLM（只靠用户消息语义判断）" | 第三十一轮已改为传当前已选数据上下文（源/目标/技能名）给 LLM，让它能判断 keep/change |
| 第三十轮 | "有任意 suggestion → 保存 ChatMessage + yield done + return；无 suggestion → 走 Agent" | 第三十一轮已改为每路独立返回结果（含 no_match 类型），不再用 `_has_suggestion` 判断 |
| 第三十轮 | "前端 suggestions 数组（data_suggestion/target_suggestion/skill_suggestion + missing_source/missing_target）" | 第三十一轮已改为 8 种独立事件类型（data_suggestion/source_datasource_no_match/source_table_no_match/target_suggestion/target_datasource_no_match/target_table_no_match/skill_suggestion/skill_no_match） |

### 第二十九轮（Chat 数据上下文持久化 + 会话隔离 + 路由判断合并 + 技能匹配优化 + 输入历史隔离）

**核心洞察**：用户测试技能匹配跳转时发现指令全是"请指定"占位符——根因是 `ChatSession.context` 的 SQLAlchemy JSON 字段原地修改不触发 dirty 标记，commit 不写入 DB，数据源/表名永远丢失。本轮修复数据上下文全链路持久化 + 会话隔离 + 路由判断合并 + 技能匹配优化。

**数据上下文持久化（根因修复）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **dict() 触发 dirty** | chat.py:798 + 972 | `_session_obj.context = dict(_session_ctx)` 创建新 dict 对象触发 SQLAlchemy dirty 标记，修复 JSON 字段原地修改不触发 UPDATE 的 bug（`source_datasource_name`/`source_table_name`/`target_*` 永远不写入 DB） |
| **ChatSessionResponse 加 context** | schemas/chat.py | `ChatSessionResponse` 加 `context` 字段，前端能拿到会话上下文 |
| **前端 ChatSession 接口加 context** | api/chat.ts | `ChatSession` 接口加 `context?: Record<string, any>` |
| **switchSession 恢复 selectedData** | stores/chat.ts | 切会话时从 `session.context` 恢复 `selectedData`（source_datasource_id/name/table_name），刷新/重开不丢 |
| **infer-instruction 读 context** | skill.py:807-828 | `ChatSession.context` 读取数据上下文（源/目标数据源名+表名），修复指令全是"请指定"占位符 |
| **infer-instruction UUID 修复** | skill.py:810 | `UUID(request.chat_session_id)` 转换 str→UUID，修复 `AttributeError: 'str' object has no attribute 'hex'`（ChatSession.id 是 UUID(as_uuid=True) 列） |
| **SkillInferInstructionRequest 加 source 字段** | schemas/skill.py | 加 `source_datasource_name`/`source_table_name`（前端跳转 URL 传入，优先于 context） |
| **前端传 source 字段** | SkillView.vue:2860 | 调 infer-instruction 时传 `dsName`/`tblName`（回退 `m.datasource_name`） |

**会话隔离（删会话清消息 + 输入历史隔离）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **delete_session 级联删消息** | chat.py:490-493 | 显式 `delete(ChatMessage).where(session_id=...)` + `_HISTORY_SUMMARIES.pop()` 清缓存（SQLite 默认不启用外键级联） |
| **输入历史按会话隔离** | ChatView.vue + chat.ts | `localStorage` key 从 `dc_chat_history` → `dc_chat_history_<session_id>`；`switchSession` 时 `loadInputHistory(newId)` 加载对应会话的输入历史 |

**路由判断合并（classify + keep/change 一次 LLM 调用）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **classify_message 合并 keep/change** | chat_router.py | 一次 LLM 调用判断类型(analysis/processing/chat) + 是否继续用当前已选数据(keep/change)；返回 `(msg_type, keep_data, events)`；prompt 只给当前已选数据源+表名+判断依据，不加示例不硬编码 |
| **keep_data 控制 tables 跳过** | chat.py:818-828 | `_keep_data=True` → 跳过数据表匹配（继续用当前数据）；`_keep_data=False` → 清除 context 旧数据走数据表匹配 |
| **useMatched 回退 m.datasource_name** | ChatView.vue:607-612 | `useMatched` 跳转时 `chatStore.selectedData` 已被清空（sendMessage 后 null），回退用匹配建议项 `m.datasource_name`/`m.table_name`；后端 infer-instruction 从 context 读 |

**技能/流程匹配优化（msg_type 透传）**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **粗筛+精排带 msg_type** | match_service.py | `_llm_coarse_match`/`_llm_fine_match` 加 `msg_type` 参数；analysis 类加"用户意图：只分析不修改"；processing 类加"用户意图：数据处理"；`llm_match_pipelines`/`llm_match_skills`/`_llm_match_items` 全链路透传 |
| **全部技能加 skill_type** | data/skills/*/SKILL.md | 9 个技能全部加 `skill_type` 字段（8 个 processing + 1 个 analysis）；description 按 skill_creator 规范重写（覆盖常见问法+口语化表达，如"导出/迁移/搬数据"、"清洗/清理/去重"、"提取/识别/标注"） |

**目标表匹配按钮文案**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **按钮文案调整** | ChatView.vue:134+139 | 目标表匹配：每个表项 `继续处理` → `选择此数据`（调 `selectData` 选目标表）；底部 `直接继续处理` → `继续处理`（调 `continueProcessing` 跳过目标匹配） |

**验证**：`ChatSession.context` 正确持久化（源+目标数据源名+表名全写入 DB）；infer-instruction 从 context 读取生成带真实参数的指令；classify 一次 LLM 调用判断类型+keep/change；技能匹配带 msg_type 意图提示；9 个技能全有 skill_type + 口语化 description。

**与前轮关系**：第二十六轮 DataAnalystAgent 集成的 skill_type 路由在本轮扩展到全部技能（之前只有 data-statistics 有 skill_type）；第二十八轮 LLM 配置去全局化的 `_flash`/`_default` 属性在本轮被 classify_message 复用（`model=llm_manager._flash` 快速判断）；第二十三轮的 `_compress_history` 用 `_session_ctx` 但未发现 dirty 问题在本轮修复。

### 第三十轮（匹配流程重构——classify 4 keep + 并行匹配 + 多 suggestion + category 字段删除）

**核心洞察**：第二十九轮的 classify 只返回单段 `keep_data`（控制数据表匹配跳过），无法独立控制「换源表但保留目标表」「换技能但保留数据」等组合——用户说"换个表分析"时 keep_data=False 会把源和目标数据全清掉。本轮把 keep 拆为 4 段（keep_source/keep_target/keep_skill），各自独立控制匹配跳过；同时把串行匹配（源表→目标表→流程→技能，匹配到就 return）改为并行匹配（source/target/skill 各自独立，一次性 yield 所有 suggestion）。此外 skill/operator/pipeline 的 `category` 字段语义混乱（与 skill_type 重叠），本轮彻底删除 category 改用 skill_type/pipeline_type。

**classify 4 段 keep**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **classify 返回 4 keep** | chat_router.py | 一次 LLM 调用输出 4 个词（类型 + 源表 keep/change + 目标表 keep/change + 技能 keep/change）；返回 `(msg_type, keep_source, keep_target, keep_skill, events)`；**不传 context 信息给 LLM**（只靠用户消息语义判断，默认 keep，用户明确说换才 change） |
| **4 keep 各自独立控制** | chat.py | `keep_source=False` → 清源 context 走源表匹配；`keep_target=False` → 清目标 context 走目标表匹配；`keep_skill=False` → 清技能/流程 context 走匹配；已选 + keep → 跳过对应匹配 |

**并行匹配 + chat 直连**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **chat 类型直接 LLM 对话** | chat.py | `msg_type == "chat"` → 不走任何匹配，直接 `llm_manager.chat_stream_with_thinking` 对话（闲聊/问候/设置不浪费匹配） |
| **并行匹配三路独立** | chat.py | source/target/skill 三路各自独立匹配（不再串行 return），收集到 `_all_suggestions` 一次性 yield 所有匹配结果；有任意 suggestion → 保存 ChatMessage + yield done + return；无 suggestion → 走 Agent |
| **已选跳过** | chat.py | `_source_selected`/`_target_selected`/`_skill_selected` 判断：keep=True 且已选 → 跳过该路匹配（不重复匹配已选项） |
| **技能/流程分派** | chat.py | processing：先流程失败才技能；analysis：直接技能（不走流程） |
| **参数凑齐检查** | chat.py | 无 suggestion 且缺源/目标 → yield content 提示"缺少：xxx，请补充" + done + return |

**match_service 重构**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **合并 llm_match_tables** | match_service.py | `llm_match_tables` + `llm_match_target_tables` 合并为一个 `llm_match_tables(user_message, db, exclude_datasource_id="")`；exclude_datasource_id 非空时排除已选源数据源（目标表匹配场景） |
| **check_similar_resources 通用** | match_service.py | 新增通用相似资源检测（向量检索 + 阈值过滤 + 权限判断 + owner 信息），复用于技能/流程/算子 |
| **_mlog 独立日志** | match_service.py | 新增 `_mlog` 函数独立写 `match_detail.log`（候选列表/prompt/LLM 原始响应/匹配结果），不依赖 main.py 日志过滤器 |
| **流程排除内置** | match_service.py | `llm_match_pipelines` 排除 `is_builtin=True`（内置维护类流程不参与用户业务匹配） |
| **match_type 区分** | match_service.py | `_llm_match_items`/`_llm_fine_match` 加 `match_type` 参数（"table" 时提示 LLM 按表名/业务描述/标签/列名语义匹配） |
| **desc 增强** | match_service.py | 匹配 item 的 desc 增加标签、business_purpose、business_tags 字段，提高 LLM 匹配准确率 |

**category 字段删除**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **skill category→skill_type** | schemas/skill.py + models/skill.py | `SkillCreate`/`SkillUpdate`/`SkillResponse`/`SkillSearchRequest` 的 `category` 字段 → `skill_type`；model 同步 |
| **pipeline category→pipeline_type** | schemas/pipeline.py + models/pipeline.py | `PipelineCreate`/`PipelineUpdate`/`PipelineResponse` 的 `category` 字段 → `pipeline_type`；内置流程 `category="system"` → `pipeline_type="system"` |
| **operator 删 category** | schemas/operator.py + models/operator.py | `OperatorCreate`/`OperatorUpdate`/`OperatorResponse`/`SimilarOperatorItem` 删除 `category` 字段（算子无分类） |
| **match_service 删 category** | match_service.py | `_build_skill_text`/`_build_operator_text`/`_build_pipeline_text` 删除 category 拼接 |
| **SimilarSkillItem 修复** | schemas/skill.py | `SimilarSkillItem.category` → `skill_type`（第三十轮 category 删除遗漏，修复后 check-similar 端点 `extra_fields_fn` 返回的 `skill_type` 正确映射；schemas 目录 category grep 全空） |
| **DB 迁移** | main.py | skills 表加 `skill_type` 列（从 tags 的 skill_type:xxx 迁移 + 清理 tags）；pipelines 表加 `pipeline_type` 列（内置=system / 其他从关联技能 skill_type 推断）；seed 同步 skill_type + 清理 tags |

**skip_steps 机制删除**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **删 skip_steps schema** | schemas/chat.py | `ChatMessageCreate.skip_steps` 字段删除 |
| **删 skip_steps 后端逻辑** | chat.py | 删除 `"tables"/"target"/"pipelines"/"skills" not in _skip_steps` 全部条件分支（~120 行）；改用 4 段 keep + 已选跳过判断 |
| **删 skip_steps 前端** | chat.ts + ChatView.vue | 前端不再传 `skip_steps`，改用 `skip_match` + selected_datasource_id |

**前端多 suggestion 展示**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **suggestions 数组** | ChatView.vue + chat.ts | `data_suggestion`/`target_suggestion`/`skill_suggestion` 事件存入 `msg.suggestions` 数组（一条消息可含多个 suggestion）；缺源/目标提示 `missing_source`/`missing_target` |
| **目标表写入策略** | ChatView.vue | 目标表匹配：覆盖/追加/直接使用 + 新表名输入框（自动生成可修改） |
| **executing 可折叠** | ChatView.vue | executing 提示改为可折叠默认展开 |

**验证**：`app.main` 完整加载 188 路由（skills 30 / datasources 24 / operators 18 等）；`classify_message` 返回 5 元组（4 keep）；`llm_match_target_tables` grep 全空（已合并入 `llm_match_tables`）；`skip_steps` grep 全空（schema + 后端 + 前端）；`category` grep 全空（skill/pipeline/operator schema + model）；`check_similar_resources`/`_mlog` 存在。

**与前轮关系**：第二十九轮的单段 `keep_data` + 串行匹配（源→目标→流程→技能，匹配到即 return）被本轮 4 段 keep + 并行匹配取代——支持「换源表保留目标表」等组合，且一次性展示所有匹配结果。第二十六轮的关键词路由在本轮彻底改为 classify LLM 语义判断（不再依赖关键词列表）。第二十一轮的 SSE 日志扩展（main.py filter 加 `[match-detail]`/`[match]`）。chat_router 的 `classify_message` 不再读 session_ctx（只靠用户消息语义判断），第二十九轮「prompt 给当前已选数据源+表名」已删除。

### 第三十一轮（Chat 匹配流程完善 + 使用技能走调试模式 + 多智能体自愈闭环）

**核心洞察**：第三十轮建立了 4 段 keep + 并行匹配框架，但前端卡片渲染、技能调用、参数上下文传递、directExecute 用户体验等多处未完善。本轮系统补齐匹配结果展示、技能调用链路、参数提示、前后端数据同步等问题。

**classify 传上下文修复**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **classify prompt 注入已选数据** | chat_router.py | 把 `session_ctx` 里的源/目标/技能名注入 prompt，LLM 能对比"当前选的"和"用户想要的"判断 keep/change（之前不传上下文 LLM 无法判断"换"还是"继续用"） |
| **classify 日志加文件 sink** | main.py | `debug_sse.log` filter 加 `[classify]`/`[direct_execute]`/`[route]`，日志写文件方便排查 |

**每路独立返回结果**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **8 种事件类型** | chat.py | `data_suggestion`/`source_datasource_no_match`/`source_table_no_match`/`target_suggestion`/`target_datasource_no_match`/`target_table_no_match`/`skill_suggestion`/`skill_no_match`——每路匹配到/没匹配到独立返回，不返回 None |
| **去掉 _has_suggestion 复杂判断** | chat.py | 每路独立 yield 事件，不再用 `_has_suggestion` 判断要不要补发 `no_match` |
| **keep_skill 有技能也展示卡片** | chat.py | `keep_skill=True` 且有 `last_skill_id` 时，把已选技能作为 `skill_suggestion` 卡片加到结果里（之前跳过匹配不展示卡片，用户无法操作） |

**前端卡片渲染**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **v-if/v-for 拆分** | ChatView.vue | `v-if` 和 `v-for` 从同一元素拆开（Vue 3 `v-if` 优先级高于 `v-for` 导致只渲染一个卡片） |
| **卡片始终显示** | ChatView.vue | 去掉 `_suggestionConsumed`/`_consumedSuggestions` 关闭逻辑，卡片始终显示，可重复选择 |
| **data_no_match/target_no_match 提示放 content** | chat.ts | 数据源/数据表未匹配到的提示放 `msg.content`（Chat 回复区），不渲染卡片；`skill_no_match` 渲染卡片（创建新技能+直接处理） |
| **前端参数提示实时更新** | ChatView.vue | `updateParamsHint` 函数：选了数据/目标表后立刻更新 `msg.content` 的参数提示（✅ 已确定 + ⚠️ 还缺），不用等下次发消息 |
| **suggestions 数组响应式修复** | chat.ts | `push` 后加 `messages.value = [...messages.value]` 触发 Vue 更新 |
| **_syncFromDB 恢复 suggestions** | chat.ts | 保存 `_savedSuggestions` → DB 刷新后恢复 → `messages.value = [...messages.value]` 触发更新 |
| **技能卡片四个蓝色按钮** | ChatView.vue | 使用技能/调试技能/创建新技能/直接处理，统一 `type="primary"` 对齐 |

**使用技能走调试模式**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **使用技能走 run_debug** | chat.py | `use_skill=true` 时走 `build_debug_context` + `runtime.run()`，Agent 用 `run_script` 工具执行技能；RunTime 自动 Inspector handoff 自愈闭环 |
| **use_skill 标记区分** | schemas/chat.py + chat.ts + ChatView.vue | `use_skill` 字段区分使用技能/直接处理；使用技能 `directExecute=true, useSkill=true`；直接处理 `directExecute=true, useSkill=false` |
| **技能信息 + 数据参数 + 执行需求展示** | chat.py | yield 技能名/描述/已确定参数/拼好的执行需求（"把 文物库 的 xxx 表导出到 文物列表 的 xxx 表"）给用户 |
| **_run_skill_nl 共享函数** | skill.py | `run_skill_nl` 端点的核心逻辑抽成 `_run_skill_nl`，供 chat.py 复用 |
| **调试技能跳转传目标表** | ChatView.vue + SkillView.vue + skill.py | `debugSkill` 传 `target_ds_name`/`target_table_name`；SkillView 接收传给 `infer-instruction`；`SkillInferInstructionRequest` 加 `target_datasource_name`/`target_table_name` |

**directExecute 用户体验修复**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **directExecute 不存用户消息** | chat.py | `directExecute=true` 时后端不存用户消息到 DB（避免刷新后重复弹出） |
| **directExecute 复用 assistant 消息** | chat.ts | `directExecute=true` 时复用最后一条 assistant 消息（清空内容接收新流式数据），不 push 新的用户消息和 assistant 消息 |
| **directExecute 跳过 _syncFromDB** | chat.ts | `directExecute` 时不从 DB 刷新消息列表（避免重复用户消息冒出） |
| **后端报错前端明确提示** | chat.ts | `_syncFromDB` catch 从 `[已停止生成]` → `❌ 服务连接失败：xxx` |
| **输入历史 onMounted 加载** | ChatView.vue | 页面首次加载时显式调 `loadInputHistory`（之前只 watch 切换时触发，首次进入不加载） |

**参数上下文全链路**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **目标表/技能写入 session_ctx** | chat.py | `target_datasource_id`/`target_table_name`/`target_write_mode`/`selected_skill_id`/`selected_skill_name` 从前端传入后写入 `session_ctx`（之前只有源表写入，目标表/技能从不写入） |
| **前端 selectedData 传 target/skill** | chat.ts + api/chat.ts | `sendMessage` 提取 `target_datasource_id`/`target_table_name`/`target_write_mode`/`skill_id`/`skill_name`/`skill_type` 传给后端 |
| **switchSession 恢复目标表** | chat.ts | 切会话时从 `session.context` 恢复目标数据源名/表名到 `selectedData` |
| **sendMessage 后不清空 selectedData** | chat.ts | 之前 `sendMessage` 后 `selectedData.value = null` 清空，之前聊的参数丢了；改为不清空保持 |
| **_get_ready_params/_get_missing_params/_build_params_hint 共享函数** | chat.py | 三处参数展示/检查逻辑抽成共享函数，避免重复代码 |
| **写入策略注入** | chat.py | `_get_ready_params` 加 `target_write_mode` 显示（"写入策略: 覆盖（if_table_exists=overwrite）"） |

**匹配提示丰富化**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **匹配池规模提示** | chat.py | "正在从「文物库」匹配数据表（3 张表中）..."；只统计用户提到的数据源的表数（之前报全库 130 张表） |
| **已选数据提示** | chat.py | "✓ 沿用上次选定的数据：文物库 → xxx" |
| **匹配结果汇总** | chat.py | "✓ 数据表匹配到 2 个结果，✗ 技能/流程未匹配到结果" |
| **匹配结果消息带参数** | chat.py | "检测到匹配结果，请选择操作。\n\n✅ 已确定参数：...\n\n⚠️ 还缺：..." |

**Python 3.12 venv**：

| 改进 | 文件 | 说明 |
|------|------|------|
| **package.json 用 .venv** | package.json | `dev:backend`/`start:backend` 用 `.venv\Scripts\python.exe` 替代系统 `python`（系统 Python 3.14 无依赖） |
| **Python 3.12 venv 创建** | backend/.venv | 用 uv 的 Python 3.12 创建 venv，装 requirements.txt + chromadb + minio + pytest |

**验证**：`app.main` 完整加载 188 路由；130 测试全通过；前端 vite build 通过；classify 传上下文后 keep/change 判断正确；使用技能走调试模式 Agent 用 run_script 执行；directExecute 不弹重复用户消息。

**与前轮关系**：第三十轮的 4 段 keep + 并行匹配框架在本轮完善——每路独立返回结果类型、前端卡片渲染修复、技能调用走调试模式复用 `build_debug_context`。第二十三轮的 `build_debug_context`/`build_debug_message` 在本轮被 chat.py 复用（之前只有 skill.py/operator.py/pipeline.py 用）。第二十九轮的 `selectedData` 只传源表在本轮扩展到目标表+技能全链路。
