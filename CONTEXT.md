# DataCrab - 项目上下文

## 定位

**DataCrab 是数据处理助手，只能处理用户的数据，绝不能修改 DataCrab 平台自身。**

这是一条不可逾越的红线，适用于对话、算子、技能、流程等所有模块。

### 关键区分

| 类别 | 说明 | 能否修改 |
|------|------|----------|
| DataCrab 平台自身 | 源代码、配置、用户/角色/权限、系统表、基础设施 | ❌ 禁止 |
| 用户定义的对话 | 用户创建的会话、消息 | ✅ 允许 |
| 用户定义的算子 | 用户创建的算子脚本 | ✅ 允许 |
| 用户定义的技能 | 用户创建的技能包和脚本 | ✅ 允许 |
| 用户的业务数据 | 数据源中的业务数据 | ✅ 允许 |

**原则：DataCrab 不能修改"自己"（平台），但可以帮用户创建和修改"用户自己的"对话、算子和技能。算子和技能中运行的数据处理脚本，只能操作用户的业务数据，不能操作平台系统数据。**

## 安全边界

### 允许的操作
- 查询、处理、分析用户数据源中的业务数据
- 生成数据处理脚本（清洗、转换、聚合、分析等）
- 在用户授权的文件链接目录中读写文件
- 通过对话理解用户的数据处理需求并执行

### 禁止的操作
- 修改 DataCrab 平台的源代码、配置文件
- 访问或修改平台系统表（users, roles, permissions, schedules 等）
- 删除或篡改平台用户、角色、权限配置
- 通过文件链接向 DataCrab 项目目录写入文件
- 生成以 DataCrab 自身为操作目标的脚本或代码
- 通过算子/技能/对话执行任何影响平台运行的操作

### 允许修改的用户内容
- 用户自己创建的对话（会话、消息）
- 用户自己创建的算子（脚本生成、修改、调试、删除）
- 用户自己创建的技能（技能包创建、修改、调试、删除）
- 用户自己创建的流程（创建、修改、执行、删除）
- 用户数据源中的业务数据

### 实施方式
- **对话模块**：系统提示词中包含操作边界约束（chat.py `_build_system_prompt`）
- **算子模块**：生成/修改算子时的 SYSTEM_PROMPT 包含安全红线（operator.py）
- **技能模块**：Skill Creator 提示词、调试助手提示词、修改提示词均包含安全红线（skill_creator.py, skill.py）
- **流程模块**：Pipeline Builder 提示词包含安全红线（pipeline_builder.py）
- **Persona**：personal.md 包含最高优先级的安全红线规则

## 修改后必验证

**所有修改操作完成后，必须测试验证修改是否正确。** 这适用于对话、算子、技能、流程的所有修改和调试场景。

### 规则
- 修改脚本/代码后，必须自动触发一次测试执行，验证修改未引入错误
- AI 修改算子脚本后，应自动跳转调试页面或调用调试端点验证
- AI 修改技能脚本后，调试助手应主动执行 run action 验证修改效果
- 对话中生成代码后，应主动建议用户测试或尝试执行
- 修改 SKILL.md 后，应重新读取确认修改内容已正确保存
- 如果验证失败，应回滚修改或提供修复方案

### 实施位置
- **算子**：operator.py SYSTEM_PROMPT 中要求生成后自测；修改端点自动验证
- **技能调试**：skill.py 调试助手支持多 action 按序执行（modify_script → run）
- **技能修改**：skill.py 修改提示词中要求输出后验证
- **技能创建**：skill_creator.py 提示词中要求脚本包含自测逻辑
- **流程**：pipeline_builder.py 提示词中要求生成后自测
- **对话**：chat.py _build_system_prompt 中引导修改后验证

## 脚本内置函数

算子和技能的脚本运行环境中，以下函数由系统自动注入到全局作用域，**脚本中直接使用，无需 import**。

### 技能脚本（skill_runner 沙箱注入 builtins）
- `query_table_data(datasource_id, table_name, limit=1000)` → dict: {"success": bool, "data": [行dict], "columns": [列名], "row_count": int}
- `get_table_data(datasource_id, table_name, limit=1000)` → 同 query_table_data
- `get_table_schema(datasource_id, table_name)` → dict: {"columns": [...], "row_count": int}
- `get_datasource_id_by_name(name)` → str (数据源UUID)
- `write_table_data(datasource_id, table_name, records=...)` → dict

### 算子脚本（operator.py _build_operator_namespace 注入 local_ns）
- `query_table_data(datasource_id, table_name, **kwargs)` → DataFrame
- `get_table_schema(datasource_id, table_name)` → dict
- `get_datasource_id_by_name(name)` → str (数据源UUID)

### ⚠️ 绝对禁止
- `import datacrab` / `from datacrab import ...` — datacrab 包不存在
- `pip install datacrab` — datacrab 不是可安装的包
- 技能脚本中 `if __name__ == '__main__':` 会被沙箱自动去掉，main() 由系统调用

## 输出默认同源

**数据处理生成新文件时，如果用户未指定输出路径，默认保存到 DataSource（数据源）指定的文件路径下。**

### 规则
- 用户通过技能/算子/流程处理数据并生成新文件时，如果未指定输出路径，默认将结果保存到 DataSource 的 connection_config.file_path 所在目录
- 示例：DataSource 文件路径为 `D:\wenwu\全国文物.xlsx`，输出文件默认保存到 `D:\wenwu\` 目录下
- 脚本中应通过 `output_dir` 参数控制输出路径，若未提供则自动推断为 DataSource 文件所在目录
- 如果 DataSource 来自数据库（非文件类型），则需用户指定输出路径，此时应主动询问

### 实施位置
- **技能**：skill_creator.py 提示词中要求脚本默认输出到源数据同目录；skill.py 调试助手提示词中引导同源输出
- **算子**：operator.py SYSTEM_PROMPT 中要求默认输出路径与源数据一致
- **流程**：pipeline_builder.py 提示词中要求流程默认输出到源数据同目录
- **对话**：chat.py 提示词中引导用户确认输出路径，未指定时默认同源

## Terminology

- **数据源 (DataSource)**：用户连接的外部数据（数据库、CSV、Excel、OBS 等）
- **算子 (Operator)**：存储在数据库中的 Python 脚本，处理用户业务数据
- **技能 (Skill)**：遵循 Agent Skills 标准的能力包，处理用户业务数据
- **流程 (Pipeline)**：编排多个技能/算子的 Python 主函数，处理用户业务数据
- **文件链接 (FileLink)**：用户挂载的本地文件/目录，平台可在其中读写

## Architecture Decisions

- 数据库：开发环境使用 SQLite，生产环境使用 PostgreSQL
- LLM：支持多提供商（OpenAI, Azure, 通义千问, 智谱GLM, 自定义端点）
- 技能执行：子进程沙箱隔离，超时控制
