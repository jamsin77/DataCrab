# DataCrab Windows 安装包

把 DataCrab（FastAPI 后端 + Vue3 前端 + Embeddable Python 运行时）打成一个
免安装链路的 Windows 安装包：目标机器不需要 Python、不需要 Node.js。

## 一次性准备（构建机）

```powershell
# 1. backend\.venv 已存在（开发环境本来就有）
# 2. Node.js 已安装
# 3. Inno Setup 6（打 exe 安装包用）
winget install JRSoftware.InnoSetup
```

## 构建

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

开关：`-SkipFrontend`（复用 frontend\dist）/ `-SkipDeps`（复用 cache 下的依赖包）/ `-SkipInstaller`（只组装 staging 不出 exe）

产物：

- `installer\build\DataCrab\` —— 完整安装目录布局，可直接冒烟测试
- `installer\dist\DataCrab-Setup-<版本>.exe` —— 安装包（每用户安装，无需管理员）

## 冒烟测试（打包前必做）

```powershell
cd installer\build\DataCrab
$env:DATACRAB_PORT=8765; $env:DATACRAB_NO_BROWSER=1
.\runtime\python.exe .\launcher.py
# 另开窗口验证：
#   curl http://127.0.0.1:8765/health          -> JSON
#   curl http://127.0.0.1:8765/                -> index.html
#   curl http://127.0.0.1:8765/skill           -> index.html（SPA 回退）
#   curl http://127.0.0.1:8765/api/v1/xxx      -> 404 JSON（API 不回退）
#   打开浏览器完整走一遍注册/登录/对话
```

## 结构与设计决策

| 决策 | 原因 |
|---|---|
| Embeddable Python + pip --target，不用 PyInstaller | 沙箱（skill_runner.py）用 `Popen([sys.executable, ...])` 起子进程跑技能脚本，冻结成 exe 后 sys.executable 指向 exe 本身，沙箱全挂 |
| 前端 dist 由 FastAPI 托管（main.py SPA mount） | 单端口、运行时不需要 Node；axios 用相对路径 /api/v1 天然同源 |
| 每用户安装（{localappdata}\Programs，无 UAC） | 数据库/技能/日志都写在 backend\ 下，安装目录必须可写 |
| 依赖分两个目录：Lib\site-packages（核心）/ Lib\extra-packages（chromadb+minio） | Inno 组件化；不装向量组件时主程序照常跑（匹配流程有 try/except 兜底） |
| 固定 8000 起步、被占自动顺延端口 | launcher 动态设 DATACRAB_API_BASE，沙箱子进程回连地址始终正确 |
| 卸载不删数据 | Inno 只删自己装的文件，运行时生成的 db/日志留在安装目录 |

## 版本号

沿用 `app/core/version.py` 的 `YYYY.MM.DD.提交次数`（git 生成）；
目标机无 git 时版本模块自动退化为当天日期，不影响运行。
