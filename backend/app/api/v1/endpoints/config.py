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
async def get_llm_config():
    """获取LLM配置（公开接口，不需要认证）"""
    try:
        from app.core.database import async_session
        from app.models.custom_extension import LLMProvider
        from app.core.crypto import decrypt
        from sqlalchemy import select as sa_select

        provider = llm_manager.provider or settings.LLM_PROVIDER
        api_base = llm_manager.api_base or settings.OPENAI_API_BASE
        model = llm_manager.model or settings.OPENAI_MODEL
        embedding_model = llm_manager.embedding_model or settings.OPENAI_EMBEDDING_MODEL

        # 从 DB 读取各 Provider 的 API Key 状态
        async with async_session() as session:
            result = await session.execute(
                sa_select(LLMProvider).where(LLMProvider.is_active == True)
            )
            provider_key_map = {}
            for p in result.scalars().all():
                provider_key_map[p.provider_name] = bool(p.api_key_encrypted)

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
            fast_model=getattr(settings, 'LLM_FAST_MODEL', '') or '',
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
    """更新LLM配置 — API Key 加密存数据库，其余配置存 .env"""
    try:
        from app.core.crypto import encrypt, decrypt
        from app.core.database import async_session
        from app.models.custom_extension import LLMProvider
        from sqlalchemy import select as sa_select

        # 1. API Key 加密存到 Provider 表
        api_keys_to_save = {}  # provider_name -> encrypted_key
        if config.api_key and config.api_key.strip():
            api_keys_to_save[config.provider] = encrypt(config.api_key.strip())
        if config.fallback_models:
            for f in config.fallback_models:
                fb_provider = f.get("provider") or ""
                fb_key = f.get("api_key") or ""
                if fb_provider and fb_key.strip():
                    api_keys_to_save[fb_provider] = encrypt(fb_key.strip())

        if api_keys_to_save:
            async with async_session() as save_session:
                for pname, enc_key in api_keys_to_save.items():
                    result = await save_session.execute(
                        sa_select(LLMProvider).where(LLMProvider.provider_name == pname)
                    )
                    record = result.scalar_one_or_none()
                    if record:
                        record.api_key_encrypted = enc_key
                    else:
                        logger.warning(f"Provider {pname} 不在数据库中，API Key 未保存")
                await save_session.commit()
                logger.info(f"已加密保存 {len(api_keys_to_save)} 个 API Key")

        # 2. 降级链（不再含 api_key 明文，只存 provider/model/fast_model/api_base）
        if config.fallback_models is not None:
            fallback_models = []
            for f in config.fallback_models:
                fallback_models.append({
                    "provider": f.get("provider") or "",
                    "api_base": f.get("api_base"),
                    "model": f.get("model") or "",
                    "fast_model": f.get("fast_model") or "",
                })
        else:
            fallback_models = []
        fallback_json = json.dumps(fallback_models or [], ensure_ascii=False)

        # 3. 其余配置存 .env（不含 API Key）
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
            "LLM_FAST_MODEL": config.fast_model or "",
            "OPENAI_EMBEDDING_MODEL": config.embedding_model,
            "LLM_FALLBACK_MODELS": fallback_json,
        }
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
                elif key == "OPENAI_API_KEY":
                    # 不再在 .env 中存储明文 API Key，跳过
                    continue
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        for key, value in config_map.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        # 4. 立即更新运行时 settings
        settings.LLM_PROVIDER = config.provider
        settings.OPENAI_MODEL = config.model
        settings.LLM_FAST_MODEL = config.fast_model or ""
        settings.OPENAI_EMBEDDING_MODEL = config.embedding_model
        settings.LLM_FALLBACK_MODELS = fallback_json
        if config.api_base and config.api_base.strip():
            settings.OPENAI_API_BASE = config.api_base

        # 5. 从 DB 读取解密后的 API Key，重新初始化 LLM 客户端
        async with async_session() as key_session:
            result = await key_session.execute(
                sa_select(LLMProvider).where(LLMProvider.provider_name == config.provider)
            )
            provider_record = result.scalar_one_or_none()
            current_api_key = ""
            if provider_record and provider_record.api_key_encrypted:
                current_api_key = decrypt(provider_record.api_key_encrypted)

            # 降级模型的 API Key 也从 DB 读取
            fb_with_keys = []
            for f in fallback_models:
                fb_provider = f.get("provider", "")
                fb_result = await key_session.execute(
                    sa_select(LLMProvider).where(LLMProvider.provider_name == fb_provider)
                )
                fb_record = fb_result.scalar_one_or_none()
                fb_key = decrypt(fb_record.api_key_encrypted) if fb_record and fb_record.api_key_encrypted else ""
                fb_with_keys.append({**f, "api_key": fb_key})

        current_api_base = settings.OPENAI_API_BASE or llm_manager.api_base
        if current_api_key:
            try:
                await llm_manager.reinitialize(
                    provider=config.provider,
                    api_key=current_api_key,
                    api_base=current_api_base,
                    model=config.model,
                    embedding_model=config.embedding_model,
                    fallback_models=fb_with_keys,
                )
            except Exception as e:
                logger.warning(f"LLM客户端重新初始化失败（配置已保存）: {e}")

        logger.info(f"LLM配置已更新 by user {current_user.username}")

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


@router.get("/agent/personal-md")
async def get_personal_md():
    """获取personal.md内容"""
    try:
        md_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "services", "personal.md")
        if not os.path.exists(md_path):
            return {"content": "", "exists": False}
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "exists": True}
    except Exception as e:
        logger.error(f"读取personal.md失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取personal.md失败: {str(e)}")


@router.post("/agent/personal-md", response_model=ConfigUpdateResult)
async def update_personal_md(
    req: AgentConfigRequest,
    current_user: User = Depends(get_current_user),
):
    """更新personal.md内容"""
    try:
        md_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "services", "personal.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(req.content)
        from app.services.agent_config import agent_config
        agent_config._load_from_md()
        logger.info(f"personal.md已更新 by user {current_user.username}")
        return ConfigUpdateResult(success=True, message="智能体配置已保存")
    except Exception as e:
        logger.error(f"更新personal.md失败: {e}")
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