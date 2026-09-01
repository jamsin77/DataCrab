# OpenCode 调试机制参考

> 本文档记录 OpenCode 的调试/错误处理机制，作为 DataCrab 调试模式的设计参考。避免每次都去搜互联网。

## 核心原则：LLM 自主判断，系统不替 LLM 做决策

OpenCode 的调试模式核心是：**系统给信号（工具能力描述、卡死检测），不给约束（"必须用A不能用B"）**。错误分类、修复决策全部交给 LLM 自主判断。

## 1. 工具模型：5 个工具，对齐 OpenCode Grep/Read/Edit/Bash/Task

| OpenCode 工具 | DataCrab 对应 | 职责 |
|---|---|---|
| Grep | grep_script | 搜索脚本内容，定位行号 |
| Read | read_script | 读取脚本（支持 offset/limit 翻页，默认返回全文，带行号 `L1: content`） |
| Edit | edit_script | 行级补丁（old_string/new_string，精确唯一匹配） |
| Bash | run_script | 执行脚本验证 |
| Task | list_user_datasources | 列出数据源（辅助） |

**DataCrab 与 OpenCode 的区别**：
- OpenCode 的 Bash 是任意命令执行，DataCrab 的 run_script 只执行技能脚本
- OpenCode 的 Task 是子任务委派，DataCrab 没有（调试模式不需要）

## 2. 错误处理机制：LLM 精准判断，系统不替 LLM 分类

**OpenCode 能精准判断"这是不是脚本问题"——但判断主体是 LLM，不是系统代码。**

### OpenCode 的机制

1. **工具执行结果 = 事实判断**：`bash` 执行命令返回 exit code + stdout + stderr。exit code ≠ 0 = 命令失败了 = 有问题。这是工具执行结果给出的事实，不需要额外分类。

2. **LLM 读错误信息精准判断**：stderr 的完整错误信息给 LLM 看，LLM 自己读：
   - `SyntaxError: invalid syntax` → LLM 精准知道是脚本代码 bug → 修代码
   - `command not found: ffmpeg` → LLM 精准知道是环境缺依赖 → 告诉用户装依赖
   - `ValueError: Expected [a-zA-Z0-9._-]` → LLM 精准知道是脚本没 sanitize → 修代码
   - `timed out` → LLM 精准知道可能要加进度输出或优化 → 修代码或调参数
   
   LLM 比系统信号词列表更精准——因为 LLM 能理解上下文，信号词列表不能。

3. **用户决定是否继续修**：
   - `doom_loop`：同一工具调用重复 3 次（相同参数）→ 触发权限（默认 `ask`，让用户决定是否继续）
   - `max_steps`：agent 步数上限 → 到上限强制用文字回复

### 关键洞察

OpenCode 的"精准判断"是**把错误信息原样给 LLM 看**，LLM 自己理解这是什么问题。系统不维护信号词列表、不替 LLM 做分类决策。

**为什么 LLM 比系统更精准**：
- LLM 能理解上下文（如 `FileNotFoundError` 在不同上下文可能是参数错误或代码路径 bug）
- LLM 能理解错误链（traceback 从哪行崩、为什么崩）
- 信号词列表是死的（`ValueError` 不在列表里 → 误判；"超时"不含英文 "timeout" → 漏匹配）

### DataCrab 当前的问题

`_is_non_script_error` 用信号词列表替 LLM 做判断：
- 超时错误不含英文 "timeout" → 信号词没匹配 → 误判为"参数错误" → give_up
- AI 没机会看到错误自己做判断 → 编了个"平台环境问题"当理由放弃

**违背了本质含义**：
- 脚本错误 = 能通过修改脚本修复（超时可以加进度输出修复 → 是脚本问题）
- 非脚本错误 = 怎么修脚本也修不好（如脚本主动 return success:False 做参数校验）
- `_is_non_script_error` 把超时（能修）误判为非脚本错误（修不了）→ 放弃修复

### DataCrab 应该对齐的做法

- **删除 `_is_non_script_error`**：把错误信息原样给 LLM 看，让 LLM 自己判断该不该修
- **保留兜底**：3 次执行错误 + 7 次修改上限 + StuckDetector 重复检测 + 总轮次上限
- **give_up 时让 LLM 说明原因**，不替它归因

## 3. 调试循环：修改 → 执行 → 看结果

### OpenCode 的循环
```
看错误信息 → Grep/Read 定位代码 → Edit 修改 → Bash 执行 → 看结果
  ↑                                                    ↓
  └────────────── 修复未完成，继续 ←──────────────────┘
```

### DataCrab 的循环（对齐 OpenCode）
```
看错误信息 → grep_script/read_script 定位 → edit_script 修改 → run_script 执行 → 看结果
  ↑                                                              ↓
  └──────────── 修复未完成，继续 ←────────────────────────────────┘
```

### 修改尝试正法
- **3 次执行错误上限**：首次执行成功前连续 3 次执行失败 → give_up
- **7 次总修改上限**：所有修改（执行错误修复 + 检查修复）合计达 7 次 → give_up
- **调查不算次数**：read_script/grep_script 是修改前的准备，不算修改尝试
- **只数 run_script**：一次"修改尝试" = 一次"修改 + 执行"完整循环，edit_script 不单独计数

## 4. 卡死检测（StuckDetector）

### OpenCode 的做法
- OpenCode 无显式卡死检测——靠 LLM 自主判断何时停止
- 但有 token 限制和上下文窗口限制作为自然兜底

### DataCrab 的做法
- **空转检测**：连续 N 轮有输出但没有工具调用 → 干预提示
- **总轮次上限**：30 轮（DataProcessor 调试模式）→ 强制退出
- **重复调用检测**：连续 N 轮调用相同工具 + 相同参数 → 干预提示

## 5. 上下文管理

### OpenCode 的做法
- **Compaction**：上下文使用率超阈值 → 旧消息 LLM 摘要 + 保留近期原文 + 标识符机械抽取
- **Prefix Cache**：system prompt 字节稳定 → 命中 provider context cache

### DataCrab 对齐
- `should_compact` + `compact_messages`：上下文 ≥75% 触发压缩
- `build_debug_system_prompt` 进程级 memoize：静态区字节稳定命中 prefix cache
- 动态提示（脚本/参数/经验/历史）分离到 user 消息前缀，不进 system prompt

## 6. 调试显示（对齐 OpenCode 的 action/summary 卡片）

### OpenCode 的做法
- 工具调用和结果显示为独立卡片，不混在 content 里
- Grep 显示所有匹配行 `>> L636: content`
- Read 显示行号范围 + 实际内容
- Edit 显示 diff（old(-)/new(+)）

### DataCrab 对齐
- `tool_action` 独立事件：工具调用显示为带时间戳卡片
- `tool_summary` 独立事件：工具结果显示为摘要
- `read_script` 带行号 `L1: content`
- `grep_script` 显示匹配行 `>> L636: content`
- `edit_script` 显示 diff 代码块

## 7. 输出规范

### OpenCode 的做法
- 工具调用前输出简短说明（改了什么），然后调工具
- content 和 tool_calls 在同一个 response 里，LLM 自己决定何时切换

### DataCrab 的问题
- LLM 写说明到一半就切到 tool_calls → content 被截断
- prompt 约束效果有限（LLM 不一定遵守）

### 可能的改善方向
- **A. prompt 约束**：要求 AI 先写完整说明再调工具（当前方案，效果有限）
- **B. 前端处理**：content 末尾不完整时自动补"（正在执行...）"
- **C. content 只放最终结论**：修改说明放 thinking 里，content 只输出最终结果
- **D. 去掉 content**：调工具时不输出 content，只有 tool_action 卡片

## 8. Handoff 机制

### OpenCode 的做法
- OpenCode 无 handoff——单 Agent 模式，用户手动决定是否继续

### DataCrab 的做法（Orchestrator-Worker）
- **Handoff 由 RunTime 决策**（Agent 不感知 handoff 存在）
- **调试模式自动交接**：DataProcessor 执行成功 → DataInspector 检查
- **主对话靠人判断**：不自动交接
- **触发条件**：done_result 有 `output_datasource_id` + `output_table`（从 written_tables 提取）

### ChromaDB 的特殊处理
- ChromaDB 写入走 `write_table_data` → skill_runner 记录 `written_tables` → Handoff 自动触发
- Inspector 对 ChromaDB 走专用检查（5 条 VEC 规则），不套结构化 STD/DQ/SEC 规则
- 如果技能没走 `write_table_data`（如直接调 ChromaDB API），written_tables 为空 → Handoff 不触发

## 9. 关键差异总结

| 维度 | OpenCode | DataCrab 当前 | 差异原因 |
|---|---|---|---|
| 错误分类 | LLM 自主判断 | `_is_non_script_error` 机械分类 | DataCrab 想早停省时间，但机械分类不可靠 |
| 卡死检测 | 无（靠 LLM 自停） | StuckDetector 15 轮兜底 | DataCrab 的 LLM 不如 OpenCode 自律 |
| 修改次数 | 无上限 | 3 次执行 + 7 次修改 | DataCrab 怕 LLM 空转浪费 token |
| Handoff | 无 | RunTime 自动交接 Inspector | DataCrab 有多 Agent 架构 |
| 上下文 | Compaction | Compaction + Prefix Cache | DataCrab 对齐了 |

## 10. 待决策问题

### `_is_non_script_error` 怎么改？
- **方案 A（对齐 OpenCode，推荐）**：删除 `_is_non_script_error`，不做错误分类。所有错误都让 AI 看着办，靠 3 次执行错误 + 7 次修改上限 + StuckDetector 兜底。
- **方案 B（简化）**：只判方式 B（`return {"success": False}`）为非脚本错误（参数校验），方式 A（raise 异常/超时/崩溃）一律当脚本问题。不需要信号词列表。
- **方案 C（补全，治标不治本）**：补全 `_crash_signals` 列表 + 加中文信号词——列表永远不全，不推荐。

> 本质含义：脚本错误 = 能通过修改脚本修复（包括超时加进度输出）；非脚本错误 = 怎么修脚本也修不好（如参数校验脚本主动报错）。

### content 截断怎么处理？
- 见第 7 节的 4 个方案。
