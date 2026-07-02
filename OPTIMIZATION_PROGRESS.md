# DataCrab 借鉴 DeepAnalyze 优化进度跟踪

> 参考文档：`d:\doc\DeepAnalyze-系统介绍.html`
> 最后更新：2026-07-02

## 一、已完成（第一轮 12 项，均已实现并集成）

| # | 优化项 | 文件 | 状态 | 验证 |
|---|--------|------|------|------|
| 1 | 工具去重 | `shared_tools.py` | ✅ 已完成 | 6 个公共工具统一 schema + 实现 |
| 2 | 结果截断 | `agent_utils.py` | ✅ 已完成 | `truncate_tool_result` 8000 字符截断，shared_tools 内调用 |
| 3 | 卡死检测 | `agent_utils.py` | ✅ 已完成 | `StuckDetector` 已接入 agent.py / data_processor / data_inspector |
| 4 | token 估算 | `agent_utils.py` | ✅ 已完成 | CJK 感知 `estimate_tokens`，chat.py 压缩使用 |
| 5 | 反幻觉 | `agent_utils.py` | ✅ 已完成 | `is_planning_only` 已接入；`should_warn_ungrounded_claim` 已定义 |
| 6 | 标识符保护 | `agent_utils.py` | ✅ 已完成 | `build_identifier_hint` 在 chat.py `_compress_history` 使用 |
| 7 | 工具诚实 | `tool_guidance.py` | ✅ 已完成 | 能力表注入 system prompt |
| 8 | 瞬态重试 | `llm.py` | ✅ 已完成 | `_acreate_with_retry` 429/超时/500 指数退避 |
| 9 | 收敛检测 | `multi_agent.py` | ✅ 已完成 | 连续 4 次同表 handoff → 终止 |
| 10 | 压缩保护 | `chat.py` | ✅ 已完成 | `_compress_history` 分层摘要 + 标识符保留 |
| 11 | 经验聚合 | `experience.py` | ✅ 已完成 | `distill_cross_patterns` 跨算子 LLM 整合 |
| 12 | 统一路由 | `chat.py` | ✅ 已完成 | `_route_to_agent` 始终从 data_processor 开始 |

## 二、第二轮深度优化（已完成）

| # | 优化项 | 优先级 | 状态 | 实现文件 | 说明 |
|---|--------|--------|------|----------|------|
| 13 | 接入 `should_warn_ungrounded_claim` | 高 | ✅ 已完成 | agent.py / data_processor_agent.py / data_inspector_agent.py | 无工具调用时数据声明触发警告，跟踪 `had_any_tool_calls` 避免误报 |
| 14 | 动态轮次预算 | 高 | ✅ 已完成 | agent_utils.py + 3 个 agent | `estimate_complexity` + `get_turn_budget`：simple=15/medium=25/complex=40 |
| 15 | 上下文压力主动告警 | 高 | ✅ 已完成 | agent_utils.py + 3 个 agent | `get_context_pressure_level` 50%/60% 阈值，`build_pressure_warning` 注入提示 |
| 16 | 三级反幻觉注入 | 中 | ✅ 已完成 | agent_utils.py + 2 个 agent | `get_anti_hallucination_section` basic/standard/strict，Processor=standard, Inspector=strict |
| 17 | 输出长度升级 | 中 | ✅ 已完成 | llm.py + 3 个 agent | `finish_reason` 透传，`_OUTPUT_TOKEN_ESCALATION` 3000→6000→12000 |
| 18 | 工具结果 LRU 缓存 | 中 | ✅ 已完成 | agent_utils.py + shared_tools.py | `ToolResultCache` 按用户隔离，30分钟 TTL，50 条上限，只读工具 |
| 19 | 搜索饱和检测 | 低 | ✅ 已完成 | agent_utils.py + data_processor_agent.py | `SearchSaturationDetector` Jaccard 重叠度 ≥80% 连续 3 次触发 |

## 三、P0 紧急修复（架构债 + 功能缺陷）

| # | 问题 | 优先级 | 状态 | 文件 | 说明 |
|---|------|--------|------|------|------|
| P0-1 | Excel 多 sheet 查询 bug | 高 | ✅ 已修复 | connectors.py | 新增 `_resolve_table_name` 方法：用实际文件列表做最长前缀匹配，正确拆分 `文件名_Sheet名`；替代只认 `\|` 分隔符的 `_parse_table_name` |
| P0-2 | chat.py 领域硬编码 | 高 | ✅ 已修复 | chat.py | 删除 ~443 行文物领域硬编码（CHINESE_ERA_MAP / DYNASTY_PATTERNS / extract_sort_year / _parse_complex_query / _execute_complex_query）；复杂查询意图统一交由 Agent loop + query_table_data 工具处理 |

## 三-B、P1 紧迫问题修复

| # | 问题 | 优先级 | 状态 | 文件 | 说明 |
|---|------|--------|------|------|------|
| P1-1 | `MAX_INSPECTOR_ITERATIONS` 死代码 | 高 | ✅ 已修复 | data_inspector_agent.py | 删除未使用的常量（实际用 `get_turn_budget`），避免误导维护者 |
| P1-2 | 预注入数据与反幻觉冲突 | 高 | ✅ 已修复 | chat.py / data_processor_agent.py / agent.py | context 中传递 `has_preinjected_data` 标记；当 system prompt 已含实时数据预览时跳过 `should_warn_ungrounded_claim` 误报 |
| P1-3 | skill_library 持久化缺失 | 高 | ✅ 已修复 | skill_library.py | VectorIndex 新增 `save_to_disk` / `load_from_disk`（.npy + JSON）；initialize 优先从磁盘加载，register_skill 后自动持久化 |

## 三-C、P1 运行时崩溃修复 + P2 静默失效修复

| # | 问题 | 优先级 | 状态 | 文件 | 说明 |
|---|------|--------|------|------|------|
| P1-4 | chat.py `pd` 未导入 | P1 | ✅ 已修复 | chat.py | process_data / process_data_stream 端点中使用 pandas 但未导入，调用即 NameError |
| P1-5 | chat.py `skill_library` 未定义 | P1 | ✅ 已修复 | chat.py | 3 个端点引用裸名 `skill_library` 但未导入全局实例 |
| P1-6 | operator.py 调用已删除方法 | P1 | ✅ 已修复 | operator.py | 算子沙箱调 `agent_service._query_table_data`/`_get_table_schema`（工具去重后已删），改为 `execute_shared_tool` |
| P2-4 | `connector.get_tables()` 不存在 | P2 | ✅ 已修复 | shared_tools.py / skill.py | 表枚举永远返回空，改为用 `get_schema()` 提取 table_name |
| P2-5 | Inspector 回交丢失数据源信息 | P2 | ✅ 已修复 | data_inspector_agent.py | handoff_to_processor 的 payload 从 context 取 datasource_id 但未写入，导致自修复 Loop 断链 |
| P2-6 | `_user_tool_caches` 无清理 | P2 | ✅ 已修复 | shared_tools.py | 加 OrderedDict LRU 上限（100 用户），避免多用户内存泄漏 |
| P3 | 死代码清理 | P3 | ✅ 已清理 | agent.py / connectors.py / chat.py / 2 个 agent | 删除 DEFAULT_MAX_ITERATIONS、_parse_table_name、_route_to_agent、未使用 import 等 8 项 |

## 四、变更日志

### 2026-07-02 P1 运行时崩溃 + P2 静默失效修复
- **P1-4**：chat.py process_data 系列端点缺少 `import pandas as pd`，调用即 NameError → 已在各端点函数内添加局部导入
- **P1-5**：chat.py `/process-data`、`/process-data-stream`、`/skills` 引用裸名 `skill_library` 但未导入 → 已添加 `from app.services.skill_library import skill_library`
- **P1-6**：operator.py 算子沙箱调用 `agent_service._query_table_data`/`_get_table_schema`（工具去重后已删除） → 改为 `execute_shared_tool("query_table_data"/"get_table_schema", args, db, user_id)`
- **P2-4**：shared_tools.py 和 skill.py 调 `connector.get_tables()`（BaseConnector 无此方法，永远 AttributeError）→ 改为 `connector.get_schema()` + 提取 table_name
- **P2-5**：DataInspectorAgent handoff_to_processor 从 `context.get("current_datasource_id")` 取值但 chat 主流程未设置 → 在 run() 开头将 message.payload 的值写入 context
- **P2-6**：shared_tools.py `_user_tool_caches` 模块级字典无上限 → 改用 OrderedDict + LRU 上限 100 用户
- **P3**：清理 8 项死代码：DEFAULT_MAX_ITERATIONS、_parse_table_name、_route_to_agent、AgentContext.has_preinjected_data 死字段、4 个文件未使用 import
- 全部 64 个测试通过

### 2026-07-02 P1 紧迫问题修复完成
- **P1-1**：删除 `data_inspector_agent.py` 中未使用的 `MAX_INSPECTOR_ITERATIONS = 15` 死代码
- **P1-2**：修复预注入数据与反幻觉机制冲突
  - `chat.py:stream_response` 的 context 新增 `has_preinjected_data` 标记
  - `data_processor_agent.py` 和 `agent.py` 在 `has_preinjected_data=True` 时跳过 `should_warn_ungrounded_claim`
  - 避免简单查询（如"看看数据"）因 Agent 基于预注入数据回答而触发"无工具支撑"误报
- **P1-3**：skill_library 向量索引持久化
  - `VectorIndex` 新增 `save_to_disk` / `load_from_disk`（向量存 .npy，ids/metadata 存 JSON）
  - `SkillLibrary.initialize` 优先从磁盘加载，无需每次重启重新调 LLM 生成向量
  - `register_skill` 成功后自动 `_persist()` 持久化
- 全部 64 个测试通过

### 2026-07-02 P0 紧急修复完成
- **P0-1**：修复 Excel 连接器 `_parse_table_name` 只认 `|` 分隔符导致多 sheet 查询永远读到第一个 sheet 的 bug
  - 新增 `_resolve_table_name` 实例方法，用已知文件 basename 做最长前缀匹配
  - 更新 `get_table_data` / `get_table_stats` / `write_table_data` 使用新方法
- **P0-2**：清除 chat.py 中 ~443 行文物/考古领域硬编码
  - 删除 CHINESE_ERA_MAP（~70行朝代映射）、DYNASTY_PATTERNS（~23行）、extract_sort_year（~21行）
  - 删除 _parse_complex_query（~80行正则意图解析）、_execute_complex_query（~87行 DataFrame 操作）
  - 简化 _query_datasource_previews：只做基础数据预览，复杂查询交由 Agent 自主处理
  - 符合"通用性优先"和"Agent 自主性"原则
- 全部 64 个测试通过

### 2026-07-02 第二轮优化完成
- 审计确认第一轮 12 项全部已实现并集成
- 发现 `should_warn_ungrounded_claim` 已定义但未接入执行循环（gap）→ 已修复
- 实现第二轮 7 项深度优化（#13-#19），全部通过测试
- 新增 21 个单元测试（动态轮次预算、上下文压力、三级反幻觉、搜索饱和、工具缓存）
- 总测试数 64 个全部通过
- 更新 CLAUDE.md 工程改进记录表，新增第二轮 7 项

### 2026-07-02 第二轮优化启动
- 审计确认第一轮 12 项全部已实现并集成
- 发现 `should_warn_ungrounded_claim` 已定义但未接入执行循环（gap）
- 制定第二轮 7 项深度优化计划
