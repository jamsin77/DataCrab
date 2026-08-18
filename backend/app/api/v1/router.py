"""API v1路由注册"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, chat, datasource, skill, operator, schedule, filelink, config, pipeline, metadata, filesystem, llm, permission, agents, knowledge, custom_extension, assets

api_router = APIRouter()

# 认证路由
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 对话路由
api_router.include_router(chat.router, prefix="/chat", tags=["对话"])

# 数据源路由
api_router.include_router(datasource.router, prefix="/datasources", tags=["数据源"])

# 技能路由
api_router.include_router(skill.router, prefix="/skills", tags=["技能"])

# 算子路由
api_router.include_router(operator.router, prefix="/operators", tags=["算子"])

# 流程路由
api_router.include_router(pipeline.router, prefix="/pipelines", tags=["流程"])

# 调度路由
api_router.include_router(schedule.router, prefix="/schedules", tags=["调度"])

# 文件链接路由
api_router.include_router(filelink.router, prefix="/filelinks", tags=["文件链接"])

# 配置路由
api_router.include_router(config.router, prefix="/config", tags=["配置"])

# 元数据路由
api_router.include_router(metadata.router, prefix="/metadata", tags=["元数据"])

api_router.include_router(filesystem.router, prefix="/filesystem", tags=["文件系统"])

api_router.include_router(llm.router, prefix="/llm", tags=["大模型"])

api_router.include_router(permission.router, prefix="/permissions", tags=["权限管理"])

api_router.include_router(agents.router, prefix="/agents", tags=["智能体"])

# 知识库路由
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["知识库"])

# 扩展路由（数据源连接器 + LLM 适配器）
api_router.include_router(custom_extension.router, tags=["连接器与模型适配器"])

# 资产导出/导入路由
api_router.include_router(assets.router, prefix="/assets", tags=["资产管理"])
