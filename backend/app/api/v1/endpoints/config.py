"""系统配置API端点"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_current_user
from app.models.user import User
from app.services.llm import llm_manager
from loguru import logger

router = APIRouter()


class LLMConfigRequest(BaseModel):
    """LLM配置请求"""
    provider: str = "openai"
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model: str = "gpt-4"
    embedding_model: str = "text-embedding-ada-002"


class LLMConfigResponse(BaseModel):
    """LLM配置响应"""
    provider: str
    api_key_set: bool  # 不返回实际key，只返回是否已设置
    api_base: Optional[str] = None
    model: str
    embedding_model: str
    is_configured: bool


class ConfigUpdateResult(BaseModel):
    """配置更新结果"""
    success: bool
    message: str
    restart_required: bool = False


def _get_env_path() -> str:
    """获取.env文件的绝对路径"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), ".env")
    if os.path.exists(env_path):
        return env_path
    return ".env"


def _read_env_config() -> dict:
    """从.env文件读取配置"""
    env_path = _get_env_path()
    env_config = {}
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    env_config[key.strip()] = value.strip()
    except FileNotFoundError:
        logger.warning(f"配置文件不存在: {env_path}")
    except Exception as e:
        logger.error(f"读取配置失败: {e}")
    return env_config


@router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_config():
    """获取LLM配置（公开接口，不需要认证）"""
    try:
        provider = llm_manager.provider or settings.LLM_PROVIDER
        api_key = llm_manager.api_key or settings.OPENAI_API_KEY
        api_base = llm_manager.api_base or settings.OPENAI_API_BASE
        model = llm_manager.model or settings.OPENAI_MODEL
        embedding_model = llm_manager.embedding_model or settings.OPENAI_EMBEDDING_MODEL

        return LLMConfigResponse(
            provider=provider,
            api_key_set=bool(api_key),
            api_base=api_base,
            model=model,
            embedding_model=embedding_model,
            is_configured=bool(api_key),
        )
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.post("/llm", response_model=ConfigUpdateResult)
async def update_llm_config(
    config: LLMConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新LLM配置"""
    try:
        env_path = _get_env_path()

        env_lines = []
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                env_lines = f.readlines()
        except FileNotFoundError:
            env_lines = []

        config_map = {
            "LLM_PROVIDER": config.provider,
            "OPENAI_MODEL": config.model,
            "OPENAI_EMBEDDING_MODEL": config.embedding_model,
        }
        if config.api_key and config.api_key.strip():
            config_map["OPENAI_API_KEY"] = config.api_key
        if config.api_base and config.api_base.strip():
            config_map["OPENAI_API_BASE"] = config.api_base

        updated_keys = set()
        new_lines = []
        for line in env_lines:
            if "=" in line and not line.startswith("#"):
                key = line.split("=")[0].strip()
                if key in config_map:
                    new_lines.append(f"{key}={config_map[key]}\n")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        for key, value in config_map.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        # 立即更新运行时settings
        settings.LLM_PROVIDER = config.provider
        settings.OPENAI_MODEL = config.model
        settings.OPENAI_EMBEDDING_MODEL = config.embedding_model
        if config.api_key and config.api_key.strip():
            settings.OPENAI_API_KEY = config.api_key
        if config.api_base and config.api_base.strip():
            settings.OPENAI_API_BASE = config.api_base

        # 立即重新初始化LLM客户端，使配置生效
        try:
            # 如果用户没有输入新的API Key，使用已有的key
            current_api_key = settings.OPENAI_API_KEY or llm_manager.api_key
            current_api_base = settings.OPENAI_API_BASE or llm_manager.api_base
            if current_api_key:
                await llm_manager.reinitialize(
                    provider=config.provider,
                    api_key=current_api_key,
                    api_base=current_api_base,
                    model=config.model,
                    embedding_model=config.embedding_model,
                )
        except Exception as e:
            logger.warning(f"LLM客户端重新初始化失败（配置已保存）: {e}")

        logger.info(f"LLM配置已更新 by user {current_user.username}")

        return ConfigUpdateResult(
            success=True,
            message="配置已保存并生效",
            restart_required=False,
        )

    except Exception as e:
        logger.error(f"配置更新失败: {e}")
        return ConfigUpdateResult(
            success=False,
            message=f"配置保存失败: {str(e)}",
        )


@router.get("/llm/test")
async def test_llm_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """测试LLM连接"""
    from app.services.llm import PROVIDER_BASE_URLS
    from openai import AsyncOpenAI

    try:
        provider = llm_manager.provider or settings.LLM_PROVIDER
        api_key = llm_manager.api_key or settings.OPENAI_API_KEY
        api_base = llm_manager.api_base or settings.OPENAI_API_BASE or ""
        model = llm_manager.model or settings.OPENAI_MODEL

        if not api_key:
            return {
                "success": False,
                "message": "API Key未设置，请先保存配置",
            }

        base_url = api_base if api_base else PROVIDER_BASE_URLS.get(provider)

        logger.info(f"测试LLM连接: provider={provider}, model={model}, base_url={base_url}")

        if provider == "azure":
            client = AsyncOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version="2024-02-15-preview",
            )
        else:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
            )

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello, this is a test. Reply with 'OK'."}],
            max_tokens=10,
        )

        result_text = response.choices[0].message.content or ""

        logger.info(f"LLM测试成功: response={result_text}")

        return {
            "success": True,
            "message": f"LLM连接成功 (provider: {provider}, model: {model})",
            "response_preview": result_text[:50],
        }

    except Exception as e:
        logger.error(f"LLM测试失败: {e}")
        return {
            "success": False,
            "message": f"连接失败: {str(e)}",
        }


@router.get("/models/list")
async def list_available_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出可用的模型"""
    # 预定义的常用模型列表
    models = {
        "openai": [
            {"id": "gpt-4", "name": "GPT-4", "description": "最强大的模型"},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "description": "更快更便宜"},
            {"id": "gpt-4o", "name": "GPT-4o", "description": "最新多模态模型"},
            {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "description": "性价比高"},
        ],
        "qwen": [
            {"id": "qwen-max", "name": "通义千问 Max", "description": "阿里云最强模型"},
            {"id": "qwen-plus", "name": "通义千问 Plus", "description": "平衡性能与成本"},
            {"id": "qwen-turbo", "name": "通义千问 Turbo", "description": "快速响应"},
            {"id": "qwen-long", "name": "通义千问 Long", "description": "超长上下文"},
        ],
        "glm": [
            {"id": "glm-4", "name": "GLM-4", "description": "智谱AI最新模型"},
            {"id": "glm-4-plus", "name": "GLM-4 Plus", "description": "增强版模型"},
            {"id": "glm-5", "name": "GLM-5", "description": "智谱AI新一代模型"},
            {"id": "glm-3-turbo", "name": "GLM-3 Turbo", "description": "快速响应模型"},
        ],
        "embedding": [
            {"id": "text-embedding-ada-002", "name": "Ada-002", "description": "标准嵌入模型"},
            {"id": "text-embedding-3-small", "name": "Embedding-3 Small", "description": "新一代小型嵌入"},
            {"id": "text-embedding-3-large", "name": "Embedding-3 Large", "description": "新一代大型嵌入"},
        ],
        "other": [
            {"id": "claude-3-opus", "name": "Claude 3 Opus", "description": "Anthropic最强模型"},
            {"id": "claude-3-sonnet", "name": "Claude 3 Sonnet", "description": "Anthropic平衡模型"},
            {"id": "claude-3-haiku", "name": "Claude 3 Haiku", "description": "Anthropic快速模型"},
        ]
    }

    return {
        "current_provider": settings.LLM_PROVIDER,
        "current_model": settings.OPENAI_MODEL,
        "models": models,
    }