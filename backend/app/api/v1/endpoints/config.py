"""系统配置API端点"""

import os
import json
from typing import Optional, List, Dict
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
    fast_model: Optional[str] = None
    embedding_model: str = "text-embedding-ada-002"
    fallback_models: Optional[List[Dict[str, str]]] = None


class FallbackModelItem(BaseModel):
    """降级模型项（不回显 api_key）"""
    provider: str
    api_base: Optional[str] = None
    model: str = ""
    fast_model: str = ""
    api_key_set: bool = False


class LLMConfigResponse(BaseModel):
    """LLM配置响应"""
    provider: str
    api_key_set: bool  # 不返回实际key，只返回是否已设置
    api_base: Optional[str] = None
    model: str
    fast_model: Optional[str] = None
    embedding_model: str
    is_configured: bool
    fallback_models: List[FallbackModelItem] = []


class AgentConfigRequest(BaseModel):
    """Agent配置请求"""
    content: str


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
async def get_llm_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的 LLM 配置（按用户隔离；未配置则回退全局）"""
    try:
        from app.models.custom_extension import UserLLMConfig, LLMProvider
        from sqlalchemy import select as sa_select

        result = await db.execute(sa_select(UserLLMConfig).where(UserLLMConfig.user_id == current_user.id))
        rec = result.scalar_one_or_none()

        # 各 Provider 的公共 API Key 状态
        providers = await db.execute(sa_select(LLMProvider).where(LLMProvider.is_active == True))
        provider_key_map = {p.provider_name: bool(p.api_key_encrypted) for p in providers.scalars().all()}

        if rec:
            provider = rec.provider
            api_base = rec.api_base or ""
            model = rec.model or ""
            fast_model = rec.fast_model or ""
            embedding_model = rec.embedding_model or ""
            api_key_set = bool(rec.api_key_encrypted)
            fb_items = [
                FallbackModelItem(
                    provider=f.get("provider") or "",
                    api_base=f.get("api_base"),
                    model=f.get("model") or "",
                    fast_model=f.get("fast_model") or "",
                    api_key_set=bool(f.get("api_key_encrypted")),
                )
                for f in (rec.fallback_models or [])
            ]
        else:
            # 用户未配置，回退全局
            provider = llm_manager.provider or settings.LLM_PROVIDER
            api_base = llm_manager.api_base or settings.OPENAI_API_BASE
            model = llm_manager.model or settings.OPENAI_MODEL
            fast_model = getattr(settings, 'LLM_FAST_MODEL', '') or ''
            embedding_model = llm_manager.embedding_model or settings.OPENAI_EMBEDDING_MODEL
            api_key_set = provider_key_map.get(provider, False)
            fb_items = [
                FallbackModelItem(
                    provider=f.get("provider") or "",
                    api_base=f.get("api_base"),
                    model=f.get("model") or "",
                    fast_model=f.get("fast_model") or "",
                    api_key_set=provider_key_map.get(f.get("provider", ""), False),
                )
                for f in (getattr(llm_manager, "fallback_models", []) or [])
            ]

        return LLMConfigResponse(
            provider=provider,
            api_key_set=api_key_set,
            api_base=api_base,
            model=model,
            fast_model=fast_model,
            embedding_model=embedding_model,
            is_configured=api_key_set,
            fallback_models=fb_items,
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
    """更新当前用户的 LLM 配置 — API Key 加密存 UserLLMConfig（按用户隔离）"""
    try:
        from app.core.crypto import encrypt
        from app.models.custom_extension import UserLLMConfig
        from sqlalchemy import select as sa_select

        # 降级链：每个 fb 的 api_key 加密内联存储
        fallback_models = []
        if config.fallback_models:
            for f in config.fallback_models:
                fb_item = {
                    "provider": f.get("provider") or "",
                    "api_base": f.get("api_base"),
                    "model": f.get("model") or "",
                    "fast_model": f.get("fast_model") or "",
                }
                fb_key = f.get("api_key") or ""
                if fb_key.strip():
                    fb_item["api_key_encrypted"] = encrypt(fb_key.strip())
                fallback_models.append(fb_item)

        # upsert 当前用户的配置
        result = await db.execute(sa_select(UserLLMConfig).where(UserLLMConfig.user_id == current_user.id))
        rec = result.scalar_one_or_none()
        api_key_encrypted = rec.api_key_encrypted if rec else None
        if config.api_key and config.api_key.strip():
            api_key_encrypted = encrypt(config.api_key.strip())

        if rec:
            rec.provider = config.provider
            rec.api_key_encrypted = api_key_encrypted
            rec.api_base = config.api_base or ""
            rec.model = config.model
            rec.fast_model = config.fast_model or ""
            rec.embedding_model = config.embedding_model
            rec.fallback_models = fallback_models
        else:
            rec = UserLLMConfig(
                user_id=current_user.id,
                provider=config.provider,
                api_key_encrypted=api_key_encrypted,
                api_base=config.api_base or "",
                model=config.model,
                fast_model=config.fast_model or "",
                embedding_model=config.embedding_model,
                fallback_models=fallback_models,
            )
            db.add(rec)
        await db.commit()

        # 立即生效：加载到当前请求的 contextvar
        from app.services.llm import init_user_llm_context
        await init_user_llm_context(current_user.id)

        logger.info(f"用户 {current_user.username} 的 LLM 配置已更新")
        return ConfigUpdateResult(
            success=True,
            message="配置已保存并生效（API Key 已加密存储）",
            restart_required=False,
        )
    except Exception as e:
        logger.error(f"配置更新失败: {e}")
        return ConfigUpdateResult(
            success=False,
            message=f"配置保存失败: {str(e)}",
        )


@router.post("/llm/test")
async def test_llm_connection(
    body: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """测试LLM连接（用传入的配置测试，不依赖当前已保存的配置）"""
    from app.services.llm import get_provider_api_base, _custom_adapter_cache
    from app.core.database import async_session
    from app.models.custom_extension import LLMProvider
    from app.core.crypto import decrypt
    from sqlalchemy import select as sa_select
    from openai import AsyncOpenAI

    try:
        body = body or {}
        provider = body.get("provider") or llm_manager.provider or settings.LLM_PROVIDER
        model = body.get("model") or llm_manager.model or settings.OPENAI_MODEL

        # API Key：优先用传入的，其次从 DB 读取已保存的
        api_key = body.get("api_key") or ""
        if not api_key:
            async with async_session() as key_session:
                result = await key_session.execute(
                    sa_select(LLMProvider).where(LLMProvider.provider_name == provider)
                )
                record = result.scalar_one_or_none()
                if record and record.api_key_encrypted:
                    api_key = decrypt(record.api_key_encrypted)
        if not api_key:
            api_key = llm_manager.api_key or settings.OPENAI_API_KEY

        # API Base：优先用传入的，其次查内置/DB
        api_base = body.get("api_base") or ""
        if not api_base:
            async with async_session() as base_session:
                result = await base_session.execute(
                    sa_select(LLMProvider).where(LLMProvider.provider_name == provider)
                )
                record = result.scalar_one_or_none()
                if record and record.api_base:
                    api_base = record.api_base
        if not api_base:
            api_base = get_provider_api_base(provider) or ""

        if not api_key:
            return {
                "success": False,
                "message": "API Key未设置，请先填写并保存配置",
            }

        base_url = api_base
        logger.info(f"测试LLM连接: provider={provider}, model={model}, base_url={base_url}")

        # 优先检查自定义适配器
        if provider in _custom_adapter_cache:
            adapter_cls = _custom_adapter_cache[provider]
            client = adapter_cls(api_key=api_key, base_url=base_url, model=model)
        elif provider == "azure":
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


@router.get("/agent/soul-md")
async def get_soul_md():
    """获取soul.md内容"""
    try:
        md_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "services", "soul.md")
        if not os.path.exists(md_path):
            return {"content": "", "exists": False}
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "exists": True}
    except Exception as e:
        logger.error(f"读取soul.md失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取soul.md失败: {str(e)}")


@router.post("/agent/soul-md", response_model=ConfigUpdateResult)
async def update_soul_md(
    req: AgentConfigRequest,
    current_user: User = Depends(get_current_user),
):
    """更新soul.md内容"""
    try:
        md_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "services", "soul.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(req.content)
        from app.services.agent_config import agent_config
        agent_config._load_from_md()
        logger.info(f"soul.md已更新 by user {current_user.username}")
        return ConfigUpdateResult(success=True, message="性格设定已保存")
    except Exception as e:
        logger.error(f"更新soul.md失败: {e}")
        return ConfigUpdateResult(success=False, message=f"保存失败: {str(e)}")


def _standards_paths(name: str):
    """返回 (运行时可编辑路径, 默认路径)"""
    from pathlib import Path
    runtime = str(Path(settings.SKILL_STORAGE_PATH).parent / "standards" / name)
    default = str(Path(__file__).resolve().parents[3] / "defaults" / name)
    return runtime, default


def _read_md(name: str) -> str:
    runtime, default = _standards_paths(name)
    if not os.path.exists(runtime) and os.path.exists(default):
        os.makedirs(os.path.dirname(runtime), exist_ok=True)
        with open(default, "r", encoding="utf-8") as f:
            content = f.read()
        with open(runtime, "w", encoding="utf-8") as f:
            f.write(content)
    if not os.path.exists(runtime):
        return ""
    with open(runtime, "r", encoding="utf-8") as f:
        return f.read()


def _write_md(name: str, content: str) -> None:
    runtime, _ = _standards_paths(name)
    os.makedirs(os.path.dirname(runtime), exist_ok=True)
    with open(runtime, "w", encoding="utf-8") as f:
        f.write(content)


def _reset_md(name: str) -> str:
    runtime, default = _standards_paths(name)
    if not os.path.exists(default):
        raise HTTPException(status_code=500, detail="默认模板不存在")
    os.makedirs(os.path.dirname(runtime), exist_ok=True)
    with open(default, "r", encoding="utf-8") as f:
        content = f.read()
    with open(runtime, "w", encoding="utf-8") as f:
        f.write(content)
    return content


@router.get("/data-standards")
async def get_data_standards():
    """获取数据标准库 MD 内容"""
    try:
        return {"content": _read_md("data_standards.md")}
    except Exception as e:
        logger.error(f"读取数据标准库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/data-standards", response_model=ConfigUpdateResult)
async def update_data_standards(
    req: AgentConfigRequest,
    current_user: User = Depends(get_current_user),
):
    """编辑数据标准库 MD"""
    try:
        _write_md("data_standards.md", req.content)
        logger.info(f"数据标准库已更新 by {current_user.username}")
        return ConfigUpdateResult(success=True, message="数据标准库已保存")
    except Exception as e:
        return ConfigUpdateResult(success=False, message=f"保存失败: {str(e)}")


@router.post("/data-standards/reset", response_model=ConfigUpdateResult)
async def reset_data_standards(current_user: User = Depends(get_current_user)):
    """恢复数据标准库默认值"""
    try:
        _reset_md("data_standards.md")
        return ConfigUpdateResult(success=True, message="已恢复默认数据标准库")
    except Exception as e:
        return ConfigUpdateResult(success=False, message=str(e))


@router.get("/data-quality")
async def get_data_quality():
    """获取数据质量库 MD 内容"""
    try:
        return {"content": _read_md("data_quality_rules.md")}
    except Exception as e:
        logger.error(f"读取数据质量库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/data-quality", response_model=ConfigUpdateResult)
async def update_data_quality(
    req: AgentConfigRequest,
    current_user: User = Depends(get_current_user),
):
    """编辑数据质量库 MD"""
    try:
        _write_md("data_quality_rules.md", req.content)
        logger.info(f"数据质量库已更新 by {current_user.username}")
        return ConfigUpdateResult(success=True, message="数据质量库已保存")
    except Exception as e:
        return ConfigUpdateResult(success=False, message=f"保存失败: {str(e)}")


@router.post("/data-quality/reset", response_model=ConfigUpdateResult)
async def reset_data_quality(current_user: User = Depends(get_current_user)):
    """恢复数据质量库默认值"""
    try:
        _reset_md("data_quality_rules.md")
        return ConfigUpdateResult(success=True, message="已恢复默认数据质量库")
    except Exception as e:
        return ConfigUpdateResult(success=False, message=str(e))


@router.get("/data-security")
async def get_data_security():
    """获取数据安全规则库 MD 内容"""
    try:
        return {"content": _read_md("data_security_rules.md")}
    except Exception as e:
        logger.error(f"读取数据安全规则库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/data-security", response_model=ConfigUpdateResult)
async def update_data_security(
    req: AgentConfigRequest,
    current_user: User = Depends(get_current_user),
):
    """编辑数据安全规则库 MD"""
    try:
        _write_md("data_security_rules.md", req.content)
        logger.info(f"数据安全规则库已更新 by {current_user.username}")
        return ConfigUpdateResult(success=True, message="数据安全规则库已保存")
    except Exception as e:
        return ConfigUpdateResult(success=False, message=f"保存失败: {str(e)}")


@router.post("/data-security/reset", response_model=ConfigUpdateResult)
async def reset_data_security(current_user: User = Depends(get_current_user)):
    """恢复数据安全规则库默认值"""
    try:
        _reset_md("data_security_rules.md")
        return ConfigUpdateResult(success=True, message="已恢复默认数据安全规则库")
    except Exception as e:
        return ConfigUpdateResult(success=False, message=str(e))


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
            {"id": "glm-5.2", "name": "GLM-5.2", "description": "智谱AI最新一代模型"},
            {"id": "glm-5.1", "name": "GLM-5.1", "description": "智谱AI新一代模型"},
            {"id": "glm-5", "name": "GLM-5", "description": "智谱AI新一代模型"},
            {"id": "glm-4", "name": "GLM-4", "description": "智谱AI主力模型"},
            {"id": "glm-4-plus", "name": "GLM-4 Plus", "description": "增强版模型"},
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