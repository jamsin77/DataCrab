"""LLM管理器（支持多模型降级 + 瞬态重试 + ModelRouter 断路器）

设计借鉴 DeepAnalyze 的 ModelRouter：
- 默认用深度模型（主模型），失败自动降级到快速模型
- 断路器：连续 3 次失败的模型熔断 60 秒，之后 half-open 试探恢复
- 系统内部任务（参数推断等）直接用快速模型，不走断路器
- 不做关键词路由——由调用方声明任务类型，ModelRouter 负责降级
"""

import json
import time
import contextvars
from typing import Optional, AsyncGenerator, List, Dict, Any
from app.core.config import settings
from loguru import logger

# 瞬态重试异常类型（仅对这些错误重试同一模型，其他直接降级）
_TRANSIENT_ERRORS = None

# 当前请求用户的 LLM 配置覆盖（contextvars，请求级隔离，线程/协程安全）
# 设置后 LLMManager 的 _model_configs/_default/_flash 优先使用用户配置（含其私有 API Key）
_user_llm_config: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "_user_llm_config", default=None
)


def set_user_llm_config(cfg: Optional[Dict[str, Any]]) -> None:
    """在请求开始时设置当前用户的 LLM 配置（含解密后的 api_key）"""
    _user_llm_config.set(cfg)


def get_user_llm_config() -> Optional[Dict[str, Any]]:
    return _user_llm_config.get()


def reset_user_llm_config() -> None:
    """清除当前请求的用户配置覆盖（恢复全局）"""
    _user_llm_config.set(None)


async def init_user_llm_context(user_id) -> Optional[Dict[str, Any]]:
    """从 DB 加载用户级 LLM 配置，解密 API Key，设置到 contextvars。
    若用户未配置则清除覆盖（回退全局 llm_manager）。返回生效配置（或 None）。"""
    from app.core.database import async_session
    from app.models.custom_extension import UserLLMConfig
    from app.core.crypto import decrypt
    from sqlalchemy import select as sa_select
    import uuid as _uuid

    if isinstance(user_id, str):
        try:
            user_id = _uuid.UUID(user_id)
        except (ValueError, AttributeError):
            set_user_llm_config(None)
            logger.warning(f"init_user_llm_context: user_id 不是有效的 UUID: {user_id!r}，回退全局配置")
            return None
    elif not isinstance(user_id, _uuid.UUID):
        set_user_llm_config(None)
        logger.warning(f"init_user_llm_context: user_id 类型不支持: {type(user_id)}，回退全局配置")
        return None

    async with async_session() as session:
        result = await session.execute(
            sa_select(UserLLMConfig).where(UserLLMConfig.user_id == user_id)
        )
        rec = result.scalar_one_or_none()

        if not rec:
            set_user_llm_config(None)
            return None

        api_key = decrypt(rec.api_key_encrypted) if rec.api_key_encrypted else ""
        if not api_key:
            set_user_llm_config(None)
            logger.info(f"init_user_llm_context: 用户 {user_id} 的 LLM 配置无 API key，回退全局配置")
            return None

        fallback = []
        for fb in (rec.fallback_models or []):
            fb_key = decrypt(fb["api_key_encrypted"]) if fb.get("api_key_encrypted") else ""
            if not fb_key:
                fb_provider = fb.get("provider", "")
                from app.models.custom_extension import LLMProvider
                pub_result = await session.execute(
                    sa_select(LLMProvider).where(LLMProvider.provider_name == fb_provider, LLMProvider.is_active == True)
                )
                pub_rec = pub_result.scalar_one_or_none()
                if pub_rec and pub_rec.api_key_encrypted:
                    fb_key = decrypt(pub_rec.api_key_encrypted)
                if not fb_key:
                    continue
            fallback.append({
                "provider": fb.get("provider", ""),
                "api_base": fb.get("api_base", ""),
                "default_model": fb.get("model", ""),
                "flash_model": fb.get("flash_model", ""),
                "vision_model": fb.get("vision_model", ""),
                "embedding_model": fb.get("embedding_model", ""),
                "api_key": fb_key,
            })

    cfg = {
        "provider": rec.provider,
        "api_key": api_key,
        "api_base": rec.api_base or "",
        "default_model": rec.model or "",
        "flash_model": rec.flash_model or "",
        "vision_model": rec.vision_model or "",
        "embedding_model": rec.embedding_model or "",
        "fallback_models": fallback,
    }
    set_user_llm_config(cfg)
    return cfg

def _get_transient_errors():
    """延迟导入 OpenAI 异常类型"""
    global _TRANSIENT_ERRORS
    if _TRANSIENT_ERRORS is not None:
        return _TRANSIENT_ERRORS
    try:
        import openai
        _TRANSIENT_ERRORS = (
            openai.RateLimitError,       # 429 限流
            openai.APITimeoutError,      # 请求超时
            openai.APIConnectionError,   # 网络连接错误
            openai.InternalServerError,  # 500 服务端错误
        )
    except (ImportError, AttributeError):
        _TRANSIENT_ERRORS = ()
    return _TRANSIENT_ERRORS


async def _stream_with_timeout(stream, first_timeout: float = 120.0, chunk_timeout: float = 60.0):
    """遍历流式响应，带超时保护。

    首 chunk 用更长超时（思维模型推理阶段可能 60-90s 才出第一个 token），
    后续 chunk 用较短超时（流式建立后 token 应持续到达）。
    超时时抛出 asyncio.TimeoutError，让调用方捕获并降级重试，而非静默结束。

    注意：用 ensure_future + asyncio.wait 替代 wait_for，
    避免 wait_for 取消 __anext__() 导致 SDK async stream 进入坏状态（永久挂起）。
    对齐第八轮 SSE handler 修复的同一模式。
    """
    import asyncio as _aio
    is_first = True
    while True:
        t = first_timeout if is_first else chunk_timeout
        task = _aio.ensure_future(stream.__anext__())
        done, _pending = await _aio.wait({task}, timeout=t)
        if task in done:
            try:
                chunk = task.result()
            except StopAsyncIteration:
                return
            is_first = False
            yield chunk
        else:
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            close = getattr(stream, "close", None)
            if close:
                try:
                    r = close()
                    if hasattr(r, "__await__"):
                        await r
                except Exception:
                    pass
            logger.warning(f"LLM 流式响应超时（{'首个' if is_first else '后续'}chunk {t}s 无数据），将降级重试")
            raise _aio.TimeoutError(f"流式响应超时（{t}s 无数据）")


# Provider 注册表：内存缓存，启动时从 DB 加载
_provider_registry: Dict[str, Dict[str, Any]] = {}

# 预配置 Provider（启动时 seed 到 DB，仅用于开箱即用，运行时不引用）
_SEED_PROVIDERS = {
    "qwen": {
        "display_name": "阿里百炼",
        "description": "通义千问，阿里云大模型服务",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen3.7-max",
        "flash_model": "qwen3.6-flash",
        "vision_model": "qwen-vl-plus",
        "embedding_model": "text-embedding-v3",
        "models": [
            {"label": "Qwen3.7-Max", "value": "qwen3.7-max"},
            {"label": "Qwen3.7-Plus", "value": "qwen3.7-plus"},
            {"label": "Qwen3.6-Flash", "value": "qwen3.6-flash"},
            {"label": "DeepSeek-V4-Pro", "value": "deepseek-v4-pro"},
            {"label": "DeepSeek-V4-Flash", "value": "deepseek-v4-flash"},
        ],
    },
    "glm": {
        "display_name": "智谱AI (GLM)",
        "description": "智谱AI GLM 系列大模型",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-5.2",
        "flash_model": "glm-4-flash",
        "vision_model": "glm-4v-plus",
        "embedding_model": "embedding-3",
        "models": [
            {"label": "GLM-5.2", "value": "glm-5.2"},
            {"label": "GLM-5.1", "value": "glm-5.1"},
            {"label": "GLM-5", "value": "glm-5"},
            {"label": "GLM-4 Plus", "value": "glm-4-plus"},
            {"label": "GLM-4", "value": "glm-4"},
            {"label": "GLM-4 Flash", "value": "glm-4-flash"},
        ],
    },
    "siliconflow": {
        "display_name": "硅基流动",
        "description": "硅基流动 Model API 平台",
        "api_base": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "vision_model": "Qwen/Qwen2-VL-72B-Instruct",
        "embedding_model": "BAAI/bge-large-zh-v1.5",
        "models": [
            {"label": "DeepSeek-V3", "value": "deepseek-ai/DeepSeek-V3"},
            {"label": "Qwen2.5-72B", "value": "Qwen/Qwen2.5-72B-Instruct"},
            {"label": "Qwen2.5-Coder-32B", "value": "Qwen/Qwen2.5-Coder-32B-Instruct"},
        ],
    },
    "volcengine": {
        "display_name": "火山方舟",
        "description": "字节跳动火山引擎方舟平台（豆包系列模型）",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-1.5-pro-32k",
        "flash_model": "doubao-1.5-lite-32k",
        "vision_model": "doubao-1.5-vision-pro-32k",
        "embedding_model": "doubao-embedding-text-240715",
        "models": [
            {"label": "Doubao-1.5-Pro-32k", "value": "doubao-1.5-pro-32k"},
            {"label": "Doubao-1.5-Pro-256k", "value": "doubao-1.5-pro-256k"},
            {"label": "Doubao-1.5-Lite-32k", "value": "doubao-1.5-lite-32k"},
            {"label": "Doubao-1.5-Vision-Pro-32k", "value": "doubao-1.5-vision-pro-32k"},
            {"label": "Doubao-Pro-32k", "value": "doubao-pro-32k"},
            {"label": "Doubao-Pro-128k", "value": "doubao-pro-128k"},
            {"label": "Doubao-Lite-32k", "value": "doubao-lite-32k"},
            {"label": "Doubao-Embedding-Text-240715", "value": "doubao-embedding-text-240715"},
        ],
    },
}


async def load_providers_from_db():
    """启动时从 DB 加载所有 Provider，seed 预配置 Provider"""
    from app.core.database import async_session
    from app.models.custom_extension import LLMProvider
    from sqlalchemy import select as sa_select

    async with async_session() as session:
        # seed 预配置 Provider（内置公共）
        for name, info in _SEED_PROVIDERS.items():
            existing = await session.execute(
                sa_select(LLMProvider).where(LLMProvider.provider_name == name)
            )
            record = existing.scalar_one_or_none()
            if not record:
                from datetime import datetime, timedelta
                _seed_time = datetime(2026, 6, 1)
                record = LLMProvider(
                    provider_name=name,
                    display_name=info["display_name"],
                    description=info["description"],
                    api_base=info["api_base"],
                    models=info["models"],
                    default_model=info.get("default_model", ""),
                    flash_model=info.get("flash_model", ""),
                    vision_model=info.get("vision_model", ""),
                    embedding_model=info.get("embedding_model", ""),
                    code=None,
                    is_public=True,
                    created_at=_seed_time,
                    updated_at=_seed_time,
                )
                session.add(record)
            else:
                # 已存在的内置 Provider 确保标记为公共，更新默认模型
                record.is_public = True
                if info.get("flash_model") and not record.flash_model:
                    record.flash_model = info["flash_model"]
                if info.get("vision_model") and not record.vision_model:
                    record.vision_model = info["vision_model"]
                if info.get("embedding_model") and not record.embedding_model:
                    record.embedding_model = info["embedding_model"]
        await session.commit()

        # 加载所有 Provider 到内存
        result = await session.execute(
            sa_select(LLMProvider).where(LLMProvider.is_active == True)
        )
        _provider_registry.clear()
        for p in result.scalars().all():
            _provider_registry[p.provider_name] = {
                "display_name": p.display_name,
                "description": p.description,
                "api_base": p.api_base,
                "models": p.models or [],
                "default_model": p.default_model,
                "flash_model": p.flash_model or "",
                "vision_model": p.vision_model or "",
                "embedding_model": p.embedding_model or "",
                "code": p.code,
            }
        logger.info(f"已加载 {len(_provider_registry)} 个 Provider: {list(_provider_registry.keys())}")


def get_provider_api_base(provider: str) -> str:
    """获取 Provider 的 API base URL"""
    info = _provider_registry.get(provider)
    if info and info.get("api_base"):
        return info["api_base"]
    return None


def get_all_providers() -> Dict[str, Dict[str, Any]]:
    """获取所有 Provider 信息"""
    return dict(_provider_registry)


def refresh_provider(provider_name: str, info: Dict[str, Any]):
    """注册或刷新 Provider 到内存缓存"""
    _provider_registry[provider_name] = info
    logger.info(f"Provider 已刷新: {provider_name}")


def _parse_fallback_models(raw: str) -> List[Dict[str, str]]:
    """解析降级模型链 JSON"""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, dict) and item.get("model"):
                out.append({
                    "provider": item.get("provider") or "",
                    "api_key": item.get("api_key") or "",
                    "api_base": item.get("api_base"),
                    "model": item.get("model"),
                })
        return out
    except Exception as e:
        logger.warning(f"解析 LLM_FALLBACK_MODELS 失败: {e}")
        return []


class CircuitBreaker:
    """断路器（借鉴 DeepAnalyze ModelRouter）。
    
    状态：closed（正常）→ open（熔断，连续 3 次失败）→ half-open（60s 后试探）
    """
    def __init__(self, failure_threshold: int = 3, cooldown: int = 60):
        self._failures: Dict[str, int] = {}
        self._open_until: Dict[str, float] = {}
        self._threshold = failure_threshold
        self._cooldown = cooldown

    def is_available(self, model: str) -> bool:
        if model not in self._open_until:
            return True
        if time.time() >= self._open_until[model]:
            del self._open_until[model]
            self._failures.pop(model, None)
            logger.info(f"断路器 half-open: {model} 试探恢复")
            return True
        return False

    def record_success(self, model: str):
        self._failures.pop(model, None)
        self._open_until.pop(model, None)

    def record_failure(self, model: str):
        count = self._failures.get(model, 0) + 1
        self._failures[model] = count
        if count >= self._threshold:
            self._open_until[model] = time.time() + self._cooldown
            logger.warning(f"断路器 open: {model} 熔断 {self._cooldown}s (连续 {count} 次失败)")


_circuit = CircuitBreaker()

# 自定义 LLM 适配器缓存：provider_name → adapter_class
_custom_adapter_cache: Dict[str, type] = {}


def _load_custom_adapter(code: str, provider_name: str) -> type:
    """从 Python 源码动态加载 LLM 适配器类"""
    import ast
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            _DANGER = {"os", "subprocess", "shutil", "ctypes", "sys"}
            if module.split(".")[0] in _DANGER:
                raise ValueError(f"自定义适配器禁止 import: {module}")

    namespace = {"Any": Any, "Dict": Dict, "List": List, "Optional": Optional}
    exec(code, namespace)

    for obj in namespace.values():
        if isinstance(obj, type) and hasattr(obj, "chat_completion") and obj.__name__ != "type":
            return obj
    raise ValueError(f"代码中未找到带 chat_completion 方法的适配器类: {provider_name}")


def register_custom_adapter(provider_name: str, code: str) -> type:
    """注册自定义 LLM 适配器"""
    cls = _load_custom_adapter(code, provider_name)
    _custom_adapter_cache[provider_name] = cls
    logger.info(f"自定义 LLM 适配器已注册: {provider_name} → {cls.__name__}")
    return cls


def get_custom_adapter_providers() -> List[str]:
    """获取所有已注册的自定义适配器 provider 名"""
    return list(_custom_adapter_cache.keys())


def _require_user_cfg() -> Dict[str, Any]:
    """获取用户 LLM 配置；若未配置则抛出错误。无全局回退。"""
    cfg = get_user_llm_config()
    if not cfg:
        raise RuntimeError("未配置 LLM Provider，请在配置页面设置您的 API Key 和模型")
    return cfg


class LLMManager:
    """大模型管理器（主模型 + 降级链）

    无全局 Provider 概念——所有 LLM 调用必须基于用户配置（contextvar）。
    若未设置用户配置，抛出 RuntimeError 提示用户在配置页面设置。
    """

    def __init__(self):
        self._client_cache: Dict[tuple, Any] = {}
        self._initialized = False

    def _available_models(self) -> List[str]:
        """当前用户 Provider 可用的文本模型列表"""
        cfg = _require_user_cfg()
        provider = cfg.get("provider", "")
        info = _provider_registry.get(provider)
        if info and info.get("models"):
            return [m["value"] for m in info["models"] if m.get("value")]
        return [cfg["default_model"]] if cfg.get("default_model") else []

    def _eff_model(self, model_type: str, cfg: Dict[str, Any] = None) -> str:
        """统一模型取值（只看用户配置，空就返回空）。

        seed 只用于初始化 DB，运行时不参与。
        """
        if cfg is None:
            cfg = _require_user_cfg()
        return cfg.get(model_type, "") or ""

    @property
    def _default(self) -> str:
        """默认深度模型"""
        return self._eff_model("default_model")

    @property
    def _flash(self) -> str:
        """快速模型（未配置则回退默认模型）"""
        return self._eff_model("flash_model") or self._eff_model("default_model")

    def _eff_vision_model(self, provider: str = "") -> str:
        """视觉模型（兼容旧签名；优先用 fallback cfg）"""
        cfg = _require_user_cfg()
        if provider and provider != cfg.get("provider", ""):
            for fb in (cfg.get("fallback_models") or []):
                if fb.get("provider") == provider:
                    return self._eff_model("vision_model", fb)
        return self._eff_model("vision_model", cfg)

    # ---------- 客户端管理 ----------
    def _client_for(self, cfg: Dict[str, str]):
        """按配置构建/复用 AsyncOpenAI 客户端"""
        key = (cfg.get("provider"), cfg.get("api_base"), cfg.get("api_key"), cfg.get("model"))
        cached = self._client_cache.get(key)
        if cached is not None:
            return cached

        # 优先检查自定义适配器（非 OpenAI 兼容厂商）
        provider = cfg.get("provider", "")
        if provider in _custom_adapter_cache:
            adapter_cls = _custom_adapter_cache[provider]
            api_key = cfg.get("api_key") or ""
            base_url = cfg.get("api_base") or ""
            model = cfg.get("model") or ""
            client = adapter_cls(api_key=api_key, base_url=base_url, model=model)
            self._client_cache[key] = client
            return client

        from openai import AsyncOpenAI
        api_key = cfg.get("api_key") or ""
        base_url = cfg.get("api_base") or get_provider_api_base(cfg.get("provider", ""))
        if cfg.get("provider") == "azure":
            client = AsyncOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version="2024-02-15-preview",
            )
        else:
            client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=180.0)
        self._client_cache[key] = client
        return client

    def _model_configs(self) -> List[Dict[str, str]]:
        """返回有序模型配置列表（主模型 + 有 key 的降级模型）；保留所有模型类型字段供 vision/embedding 等取用"""
        cfg = _require_user_cfg()
        configs = [{
            "provider": cfg.get("provider", ""),
            "api_key": cfg.get("api_key", ""),
            "api_base": cfg.get("api_base", ""),
            "model": self._eff_model("default_model", cfg),
            "default_model": self._eff_model("default_model", cfg),
            "flash_model": self._eff_model("flash_model", cfg),
            "vision_model": self._eff_model("vision_model", cfg),
            "embedding_model": self._eff_model("embedding_model", cfg),
        }]
        for fb in (cfg.get("fallback_models") or []):
            if fb.get("api_key"):
                configs.append({
                    "provider": fb.get("provider", ""),
                    "api_key": fb.get("api_key", ""),
                    "api_base": fb.get("api_base", ""),
                    "model": self._eff_model("default_model", fb),
                    "default_model": self._eff_model("default_model", fb),
                    "flash_model": self._eff_model("flash_model", fb),
                    "vision_model": self._eff_model("vision_model", fb),
                    "embedding_model": self._eff_model("embedding_model", fb),
                })
        return configs

    async def _acreate(self, cfg: Dict[str, str], **kwargs):
        """用指定配置创建一次 completion 请求"""
        client = self._client_for(cfg)
        return await client.chat.completions.create(**kwargs)

    async def _acreate_with_retry(self, cfg: Dict[str, str], **kwargs):
        """带瞬态重试的 API 调用（C）。

        借鉴 DeepAnalyze 的四级错误恢复链第一层：
        对 429/超时/网络错误/500 做最多 2 次指数退避重试，
        重试耗尽再由上层 model-chain fallback 换模型。
        """
        import asyncio
        max_retries = 2
        base_delay = 2  # 秒

        for attempt in range(max_retries + 1):
            try:
                return await self._acreate(cfg, **kwargs)
            except Exception as e:
                transient_errors = _get_transient_errors()
                is_transient = isinstance(e, transient_errors) if transient_errors else False
                if not is_transient or attempt >= max_retries:
                    raise
                delay = base_delay * (2 ** attempt)  # 2s → 4s
                logger.warning(f"瞬态错误 [{cfg['provider']}/{cfg['model']}]: {e}，{delay}s 后重试 ({attempt+1}/{max_retries})")
                await asyncio.sleep(delay)

    def _format_chain_error(self, errors: list, task_name: str, hint: str = "") -> RuntimeError:
        """格式化降级链错误（不吞错误，保留每次尝试的原因）"""
        if not errors:
            return RuntimeError(f"{task_name}：无可用LLM模型")
        lines = [f"{task_name}失败，已尝试 {len(errors)} 个配置："]
        lines.extend(f"  {err}" for err in errors)
        if hint:
            lines.append(f"提示：{hint}")
        return RuntimeError("\n".join(lines))

    async def initialize(self):
        """初始化（无全局客户端，仅标记已初始化；实际客户端由 _client_for 按用户配置动态构建）"""
        self._initialized = True

    async def reinitialize(self, provider: str, api_key: str, api_base: str = None, model: str = None, embedding_model: str = None, fallback_models: List[Dict[str, str]] = None):
        """使用新配置重新初始化（清空客户端缓存，强制按新配置重建）"""
        self._client_cache = {}
        self._initialized = True
        await self.initialize()

    # ---------- 非流式调用（全链路降级） ----------
    async def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """与大模型对话。"""
        if not self._initialized:
            await self.initialize()

        if model is None:
            model = self._default

        errors = []
        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            try:
                logger.info(f"LLM chat调用: provider={cfg['provider']}, model={actual_model}")
                response = await self._acreate_with_retry(
                    cfg,
                    model=actual_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"LLM chat失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
        raise self._format_chain_error(errors, "LLM 调用")

    async def chat_with_messages(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """多轮对话，支持 system/user/assistant 消息列表。"""
        if not self._initialized:
            await self.initialize()

        if model is None:
            model = self._default

        errors = []
        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            try:
                logger.info(f"LLM chat_with_messages: provider={cfg['provider']}, model={actual_model}, messages={len(messages)}")
                response = await self._acreate_with_retry(
                    cfg,
                    model=actual_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"LLM chat_with_messages失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
        raise self._format_chain_error(errors, "LLM 调用")

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """带工具调用的对话，返回 OpenAI 格式的 response dict"""
        if not self._initialized:
            await self.initialize()

        errors = []
        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            try:
                logger.info(f"LLM chat_with_tools: provider={cfg['provider']}, model={actual_model}, tools={[t['function']['name'] for t in tools]}")
                response = await self._acreate_with_retry(
                    cfg,
                    model=actual_model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                choice = response.choices[0]
                return {
                    "content": choice.message.content,
                    "reasoning": getattr(choice.message, "reasoning_content", None),
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in (choice.message.tool_calls or [])
                    ],
                    "finish_reason": getattr(choice, "finish_reason", None),
                }
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"LLM chat_with_tools失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
        raise self._format_chain_error(errors, "LLM 调用")

    # ---------- 流式调用（创建时降级；开始输出后不重试） ----------
    async def chat_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        if not self._initialized:
            await self.initialize()

        errors = []
        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            try:
                logger.info(f"LLM chat_stream: provider={cfg['provider']}, model={actual_model}")
                stream = await self._acreate(
                    cfg,
                    model=actual_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    stream=True,
                )
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"LLM chat_stream创建失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
            try:
                async for chunk in _stream_with_timeout(stream):
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"模型 {actual_model} 流式超时/中断: {e}，尝试下一个模型")
                continue
        raise self._format_chain_error(errors, "LLM 调用")

    async def chat_stream_with_messages(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """多轮流式对话。"""
        if not self._initialized:
            await self.initialize()

        if model is None:
            model = self._default

        errors = []
        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            try:
                logger.info(f"LLM chat_stream_with_messages: provider={cfg['provider']}, model={actual_model}, messages={len(messages)}")
                stream = await self._acreate(
                    cfg,
                    model=actual_model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                )
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"LLM chat_stream_with_messages创建失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
            try:
                async for chunk in _stream_with_timeout(stream):
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"模型 {actual_model} 流式超时/中断: {e}，尝试下一个模型")
                continue
        raise self._format_chain_error(errors, "LLM 调用")

    async def chat_stream_with_thinking(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[Dict[str, str], None]:
        """流式对话（含推理过程）。"""
        if not self._initialized:
            await self.initialize()

        target_model = model or self._default
        errors = []

        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            if not _circuit.is_available(actual_model):
                continue
            try:
                logger.info(f"LLM chat_stream_with_thinking: provider={cfg['provider']}, model={actual_model}")
                stream = await self._acreate(cfg, model=actual_model, messages=messages, temperature=temperature, stream=True)
            except Exception as e:
                _circuit.record_failure(actual_model)
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"模型 {actual_model} 连接失败: {e}，尝试备用 Provider")
                continue

            try:
                yield {"type": "model", "content": actual_model}
                async for chunk in _stream_with_timeout(stream):
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        yield {"type": "thinking", "content": delta.reasoning_content}
                    if delta.content:
                        yield {"type": "content", "content": delta.content}

                _circuit.record_success(actual_model)
                return
            except Exception as e:
                _circuit.record_failure(actual_model)
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"模型 {actual_model} 流式中断: {e}，尝试备用 Provider")
                continue

        raise self._format_chain_error(errors, "LLM 调用")

    async def chat_stream_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """带工具调用的流式对话"""
        if not self._initialized:
            await self.initialize()

        errors = []
        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            try:
                logger.info(f"LLM chat_stream_with_tools: provider={cfg['provider']}, model={actual_model}, tools={[t['function']['name'] for t in tools]}")
                stream = await self._acreate(
                    cfg,
                    model=actual_model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=temperature,
                    stream=True,
                )
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"LLM chat_stream_with_tools创建失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
            try:
                async for chunk in _stream_with_timeout(stream):
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield f"data: {json.dumps({'type': 'content', 'content': delta.content}, ensure_ascii=False)}\n\n"
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            yield f"data: {json.dumps({'type': 'tool_call', 'id': tc.id, 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}}, ensure_ascii=False)}\n\n"
                return
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"模型 {actual_model} 流式超时/中断: {e}，尝试下一个模型")
                continue
        raise self._format_chain_error(errors, "LLM 调用")

    async def chat_stream_with_tools_and_thinking(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        tool_choice: str = "auto",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式工具调用对话（含推理过程）。

        Yields:
            {"type": "model", "content": "..."} — 模型名
            {"type": "thinking", "content": "..."} — 推理过程（逐 chunk 流式）
            {"type": "content", "content": "..."} — 正文内容（逐 chunk 流式）
            {"type": "tool_calls", "tool_calls": [...]} — 完整工具调用列表（流结束后一次性 yield）
            {"type": "finish", "finish_reason": "tool_calls"|"stop"|"length"} — 结束原因
        """
        if not self._initialized:
            await self.initialize()

        errors = []

        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            if not _circuit.is_available(actual_model):
                continue
            try:
                logger.info(f"LLM stream+tools: provider={cfg['provider']}, model={actual_model}, tools={[t['function']['name'] for t in tools]}")
                stream = await self._acreate(
                    cfg,
                    model=actual_model,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    stream=True,
                )
            except Exception as e:
                _circuit.record_failure(actual_model)
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"模型 {actual_model} 连接失败: {e}，尝试备用 Provider")
                continue

            try:
                yield {"type": "model", "content": actual_model}

                accumulated_tc: Dict[int, Dict] = {}
                finish_reason = None

                async for chunk in _stream_with_timeout(stream):
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta

                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        yield {"type": "thinking", "content": delta.reasoning_content}

                    if delta.content:
                        yield {"type": "content", "content": delta.content}

                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in accumulated_tc:
                                accumulated_tc[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if tc_delta.id:
                                accumulated_tc[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    accumulated_tc[idx]["function"]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    accumulated_tc[idx]["function"]["arguments"] += tc_delta.function.arguments

                    if choice.finish_reason:
                        finish_reason = choice.finish_reason

                _circuit.record_success(actual_model)

                tc_list = [accumulated_tc[i] for i in sorted(accumulated_tc.keys())]
                if tc_list:
                    yield {"type": "tool_calls", "tool_calls": tc_list}

                yield {"type": "finish", "finish_reason": finish_reason or "stop"}
                return

            except Exception as e:
                _circuit.record_failure(actual_model)
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"模型 {actual_model} 流式中断: {e}，尝试备用 Provider")
                continue

        raise self._format_chain_error(errors, "LLM 调用")

    # ---------- 嵌入 ----------
    def _eff_embedding_model(self, provider: str = "") -> str:
        """向量模型（兼容旧签名；优先用 fallback cfg）"""
        cfg = _require_user_cfg()
        if provider and provider != cfg.get("provider", ""):
            for fb in (cfg.get("fallback_models") or []):
                if fb.get("provider") == provider:
                    return self._eff_model("embedding_model", fb)
        return self._eff_model("embedding_model", cfg)

    async def embed(self, text: str) -> list:
        """生成文本嵌入向量（主模型，失败则降级）"""
        if not self._initialized:
            await self.initialize()

        errors = []
        for cfg in self._model_configs():
            try:
                client = self._client_for(cfg)
                emb_model = self._eff_model("embedding_model", cfg)
                if not emb_model:
                    raise RuntimeError(f"Provider {cfg.get('provider','')} 不支持嵌入模型，无法处理向量化任务")
                response = await client.embeddings.create(
                    model=emb_model,
                    input=text,
                )
                return response.data[0].embedding
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{actual_model}] {e}")
                logger.warning(f"LLM embed失败 [{cfg['provider']}/{cfg.get('model','')}]: {e}，尝试下一个模型")
                continue
        raise self._format_chain_error(errors, "LLM 调用")

    async def vision(self, image_b64: str, mime: str, prompt: str, system_prompt: str = None, temperature: float = 0.3, max_tokens: int = 2000) -> str:
        """视觉模型调用（主模型，失败则降级到备用 provider 的视觉模型）"""
        if not self._initialized:
            await self.initialize()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ],
        })

        errors = []
        for cfg in self._model_configs():
            vis_model = self._eff_model("vision_model", cfg)
            if not vis_model:
                logger.warning(f"LLM vision跳过 [{cfg.get('provider','')}]: 视觉模型名未配置（请在 LLM 配置页面填写视觉模型）")
                errors.append(f"[{cfg.get('provider','')}] 视觉模型名未配置")
                continue
            try:
                client = self._client_for(cfg)
                logger.info(f"LLM vision调用: provider={cfg['provider']}, model={vis_model}")
                resp = await client.chat.completions.create(
                    model=vis_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content
            except Exception as e:
                errors.append(f"[{cfg['provider']}/{vis_model}] {e}")
                logger.warning(f"LLM vision失败 [{cfg['provider']}/{vis_model}]: {e}，尝试下一个配置")
                continue
        hint = ""
        if any("content.type" in err or "image_url" in err or "image" in err.lower() for err in errors):
            hint = "该模型可能不支持图片输入，请确认视觉模型配置正确（如 glm-4v-plus）"
        raise self._format_chain_error(errors, "LLM vision", hint=hint)

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """生成文本响应（chat方法的别名）"""
        return await self.chat(prompt, model=model, temperature=temperature, max_tokens=max_tokens)


# 全局LLM管理器实例
llm_manager = LLMManager()
