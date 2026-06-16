"""API v1路由注册"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, chat, datasource, notebook, skill, operator, code, schedule, filelink, config

api_router = APIRouter()

# 认证路由
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 对话路由
api_router.include_router(chat.router, prefix="/chat", tags=["对话"])

# 数据源路由
api_router.include_router(datasource.router, prefix="/datasources", tags=["数据源"])

# Notebook路由
api_router.include_router(notebook.router, prefix="/notebooks", tags=["Notebook"])

# 技能路由
api_router.include_router(skill.router, prefix="/skills", tags=["技能"])

# 算子路由
api_router.include_router(operator.router, prefix="/operators", tags=["算子"])

# 流程路由
api_router.include_router(code.router, prefix="/codes", tags=["流程"])

# 调度路由
api_router.include_router(schedule.router, prefix="/schedules", tags=["调度"])

# 文件链接路由
api_router.include_router(filelink.router, prefix="/filelinks", tags=["文件链接"])

# 配置路由
api_router.include_router(config.router, prefix="/config", tags=["配置"])
