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
    model: Optional[str] = None
    flash_model: str = ""
    vision_model: str = ""
    embedding_model: str = ""
    fallback_models: Optional[List[Dict[str, str]]] = None


def _provider_default_model(provider: str) -> str:
    """按 provider 从注册表取推荐深度模型名"""
    from app.services.llm import _provider_registry
    info = _provider_registry.get(provider)
    if info and info.get("default_model"):
        return info["default_model"]
    return ""


def _provider_default_flash_model(provider: str) -> str:
    """按 provider 从注册表取推荐快速模型名"""
    from app.services.llm import _provider_registry
    info = _provider_registry.get(provider)
    if info:
        return info.get("flash_model", "")
    return ""


def _provider_default_vision_model(provider: str) -> str:
    """按 provider 从注册表取推荐视觉模型名"""
    from app.services.llm import _provider_registry
    info = _provider_registry.get(provider)
    if info:
        return info.get("vision_model", "")
    return ""


def _provider_default_embedding_model(provider: str) -> str:
    """按 provider 从注册表取推荐 embedding 模型名"""
    from app.services.llm import _provider_registry
    info = _provider_registry.get(provider)
    if info:
        return info.get("embedding_model", "")
    return ""


class FallbackModelItem(BaseModel):
    """降级模型项（不回显 api_key）"""
    provider: str
    api_base: Optional[str] = None
    model: str = ""
    flash_model: str = ""
    vision_model: str = ""
    embedding_model: str = ""
    api_key_set: bool = False


class LLMConfigResponse(BaseModel):
    """LLM配置响应"""
    provider: str
    api_key_set: bool  # 不返回实际key，只返回是否已设置
    api_base: Optional[str] = None
    model: str
    flash_model: str
    vision_model: str
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
            flash_model = rec.flash_model or ""
            vision_model = rec.vision_model or ""
            embedding_model = rec.embedding_model or ""
            api_key_set = bool(rec.api_key_encrypted)
            fb_items = [
                FallbackModelItem(
                    provider=f.get("provider") or "",
                    api_base=f.get("api_base"),
                    model=f.get("model") or "",
                    flash_model=f.get("flash_model") or "",
                    vision_model=f.get("vision_model") or "",
                    embedding_model=f.get("embedding_model") or "",
                    api_key_set=bool(f.get("api_key_encrypted")),
                )
                for f in (rec.fallback_models or [])
            ]
        else:
            # 用户未配置
            provider = ""
            api_base = ""
            model = ""
            flash_model = ""
            vision_model = ""
            embedding_model = ""
            api_key_set = False
            fb_items = []

        return LLMConfigResponse(
            provider=provider,
            api_key_set=api_key_set,
            api_base=api_base,
            model=model,
            flash_model=flash_model,
            vision_model=vision_model,
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

        # upsert 当前用户的配置
        result = await db.execute(sa_select(UserLLMConfig).where(UserLLMConfig.user_id == current_user.id))
        rec = result.scalar_one_or_none()
        saved_fallbacks = {f["provider"]: f for f in (rec.fallback_models if rec and rec.fallback_models else []) if f.get("provider")}

        # 降级链：每个 fb 的 api_key 加密内联存储
        fallback_models = []
        if config.fallback_models:
            for f in config.fallback_models:
                fb_item = {
                    "provider": f.get("provider") or "",
                    "api_base": f.get("api_base"),
                    "model": f.get("model") or "",
                    "flash_model": f.get("flash_model") or "",
                    "vision_model": f.get("vision_model") or "",
                    "embedding_model": f.get("embedding_model") or "",
                }
                fb_key = f.get("api_key") or ""
                if fb_key.strip():
                    fb_item["api_key_encrypted"] = encrypt(fb_key.strip())
                elif f.get("provider") in saved_fallbacks and saved_fallbacks[f.get("provider")].get("api_key_encrypted"):
                    fb_item["api_key_encrypted"] = saved_fallbacks[f.get("provider")]["api_key_encrypted"]
                fallback_models.append(fb_item)

        api_key_encrypted = rec.api_key_encrypted if rec else None
        if config.api_key and config.api_key.strip():
            api_key_encrypted = encrypt(config.api_key.strip())

        # 用户传什么存什么（空就存空），不回退 seed
        eff_model = config.model or ""
        eff_flash = config.flash_model or ""
        eff_vision = config.vision_model or ""
        eff_embedding = config.embedding_model or ""

        if rec:
            rec.provider = config.provider
            rec.api_key_encrypted = api_key_encrypted
            rec.api_base = config.api_base or ""
            rec.model = eff_model
            rec.flash_model = eff_flash
            rec.vision_model = eff_vision
            rec.embedding_model = eff_embedding
            rec.fallback_models = fallback_models
        else:
            rec = UserLLMConfig(
                user_id=current_user.id,
                provider=config.provider,
                api_key_encrypted=api_key_encrypted,
                api_base=config.api_base or "",
                model=eff_model,
                flash_model=eff_flash,
                vision_model=eff_vision,
                embedding_model=eff_embedding,
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
    """测试 LLM 连接（主模型 + 备用模型逐个测试，返回每个的结果）"""
    from app.services.llm import get_provider_api_base, _custom_adapter_cache
    from app.models.custom_extension import UserLLMConfig, LLMProvider
    from app.core.crypto import decrypt
    from sqlalchemy import select as sa_select
    from openai import AsyncOpenAI

    try:
        body = body or {}
        provider = body.get("provider") or ""

        # 用户已保存的配置（API key / model / api_base 来源之一）
        user_rec = await db.execute(sa_select(UserLLMConfig).where(UserLLMConfig.user_id == current_user.id))
        user_cfg = user_rec.scalar_one_or_none()
        if not provider and user_cfg:
            provider = user_cfg.provider or ""

        # model：传入 → 用户已保存 → 公共 Provider 默认
        model = body.get("model")
        if not model and user_cfg and user_cfg.model:
            model = user_cfg.model
        if not model:
            model = _provider_default_model(provider) or ""

        # API Key：传入 → 用户已保存（解密）→ 公共 Provider
        api_key = body.get("api_key") or ""
        if not api_key and user_cfg and user_cfg.api_key_encrypted:
            api_key = decrypt(user_cfg.api_key_encrypted)
        if not api_key:
            pub = await db.execute(sa_select(LLMProvider).where(LLMProvider.provider_name == provider))
            pub_rec = pub.scalar_one_or_none()
            if pub_rec and pub_rec.api_key_encrypted:
                api_key = decrypt(pub_rec.api_key_encrypted)

        # API Base：传入 → 用户已保存 → 公共 Provider → 内置注册表
        api_base = body.get("api_base") or ""
        if not api_base and user_cfg and user_cfg.api_base:
            api_base = user_cfg.api_base
        if not api_base:
            pub = await db.execute(sa_select(LLMProvider).where(LLMProvider.provider_name == provider))
            pub_rec = pub.scalar_one_or_none()
            if pub_rec and pub_rec.api_base:
                api_base = pub_rec.api_base
        if not api_base:
            api_base = get_provider_api_base(provider) or ""

        results = []

        async def _test_one(label: str, prov: str, mdl: str, key: str, base: str) -> dict:
            """测试单个模型连接"""
            if not key:
                return {"label": label, "provider": prov, "model": mdl, "success": False, "message": "API Key 未设置，请在上方输入框填写"}
            if not mdl:
                return {"label": label, "provider": prov, "model": mdl, "success": False, "message": "模型未设置"}
            try:
                if prov in _custom_adapter_cache:
                    adapter_cls = _custom_adapter_cache[prov]
                    client = adapter_cls(api_key=key, base_url=base, model=mdl)
                elif prov == "azure":
                    client = AsyncOpenAI(api_key=key, azure_endpoint=base, api_version="2024-02-15-preview")
                else:
                    client = AsyncOpenAI(api_key=key, base_url=base)
                response = await client.chat.completions.create(
                    model=mdl,
                    messages=[{"role": "user", "content": "Hello, this is a test. Reply with 'OK'."}],
                    max_tokens=10,
                )
                text = response.choices[0].message.content or ""
                return {"label": label, "provider": prov, "model": mdl, "success": True, "message": f"连接成功: {text[:20]}"}
            except Exception as e:
                msg = str(e)
                if "401" in msg or "Authentication" in msg or "身份验证失败" in msg or "invalid api key" in msg.lower():
                    msg = "API Key 无效或已过期，请检查密钥是否正确"
                elif "404" in msg or "model" in msg.lower() and "not found" in msg.lower():
                    msg = f"模型 '{mdl}' 不存在或无权访问，请检查模型名"
                elif "429" in msg or "rate limit" in msg.lower() or "quota" in msg.lower():
                    msg = "请求过于频繁或额度已用完，请稍后重试"
                elif "Connection" in msg or "connect" in msg.lower() or "timeout" in msg.lower() or "timed out" in msg.lower():
                    msg = f"无法连接到服务（{base}），请检查网络或 API 地址"
                elif "403" in msg or "forbidden" in msg.lower():
                    msg = "访问被拒绝，该 API Key 可能无权使用此模型"
                return {"label": label, "provider": prov, "model": mdl, "success": False, "message": msg}

        # 测试主模型
        results.append(await _test_one("主模型", provider, model, api_key, api_base))

        # 测试备用模型
        fallbacks = body.get("fallback_models") or []
        for i, fb in enumerate(fallbacks):
            if not fb.get("provider"):
                continue
            fb_provider = fb["provider"]
            fb_model = fb.get("model") or _provider_default_model(fb_provider) or ""
            # API Key：表单输入 → 用户已保存的 fallback → 公共 Provider
            fb_key = fb.get("api_key") or ""
            if not fb_key and user_cfg and user_cfg.fallback_models:
                for saved_fb in user_cfg.fallback_models:
                    if saved_fb.get("provider") == fb_provider:
                        if saved_fb.get("api_key_encrypted"):
                            fb_key = decrypt(saved_fb["api_key_encrypted"])
                        break
            if not fb_key:
                pub = await db.execute(sa_select(LLMProvider).where(LLMProvider.provider_name == fb_provider))
                pub_rec = pub.scalar_one_or_none()
                if pub_rec and pub_rec.api_key_encrypted:
                    fb_key = decrypt(pub_rec.api_key_encrypted)
            # API Base：表单输入 → 公共 Provider → 内置注册表
            fb_base = fb.get("api_base") or ""
            if not fb_base:
                pub = await db.execute(sa_select(LLMProvider).where(LLMProvider.provider_name == fb_provider))
                pub_rec = pub.scalar_one_or_none()
                if pub_rec and pub_rec.api_base:
                    fb_base = pub_rec.api_base
            if not fb_base:
                fb_base = get_provider_api_base(fb_provider) or ""

            results.append(await _test_one(f"备用 {i+1}", fb_provider, fb_model, fb_key, fb_base))

        success_count = sum(1 for r in results if r["success"])
        all_success = success_count == len(results)

        return {
            "success": all_success,
            "message": f"{success_count}/{len(results)} 个模型连接成功",
            "results": results,
        }

    except Exception as e:
        logger.error(f"LLM测试失败: {e}")
        return {
            "success": False,
            "message": f"测试失败: {str(e)}",
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

    return {"models": models}


@router.get("/version")
async def get_app_version():
    """获取应用版本号（无需认证，前端启动时调用）"""
    return {"version": settings.APP_VERSION}