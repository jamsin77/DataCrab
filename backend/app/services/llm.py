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
# 设置后 LLMManager 的 _model_configs/fast_model/pick_model 优先使用用户配置（含其私有 API Key）
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
            continue
        fallback.append({
            "provider": fb.get("provider", ""),
            "api_base": fb.get("api_base", ""),
            "model": fb.get("model", ""),
            "fast_model": fb.get("fast_model", ""),
            "api_key": fb_key,
        })

    cfg = {
        "provider": rec.provider,
        "api_key": api_key,
        "api_base": rec.api_base or "",
        "model": rec.model or "",
        "fast_model": rec.fast_model or "",
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
    """
    import asyncio as _aio
    is_first = True
    while True:
        t = first_timeout if is_first else chunk_timeout
        try:
            chunk = await _aio.wait_for(stream.__anext__(), timeout=t)
        except StopAsyncIteration:
            return
        except _aio.TimeoutError:
            logger.warning(f"LLM 流式响应超时（{'首个' if is_first else '后续'}chunk {t}s 无数据），将降级重试")
            raise
        is_first = False
        yield chunk


# Provider 注册表：内存缓存，启动时从 DB 加载
_provider_registry: Dict[str, Dict[str, Any]] = {}

# Provider 默认 embedding 模型映射（避免用 OpenAI 模型名调智谱等 provider）
_PROVIDER_EMBEDDING_MODELS: Dict[str, str] = {
    "glm": "embedding-3",
    "qwen": "text-embedding-v3",
    "siliconflow": "BAAI/bge-large-zh-v1.5",
    "openai": "text-embedding-ada-002",
    "deepseek": "",
    "moonshot": "",
}

# 按 provider 选视觉模型（文本模型不支持图片输入）
_PROVIDER_VISION_MODELS: Dict[str, str] = {
    "glm": "glm-4v-plus",
    "qwen": "qwen-vl-plus",
    "openai": "gpt-4o",
    "siliconflow": "Qwen/Qwen2-VL-72B-Instruct",
    "deepseek": "",
    "moonshot": "",
}

# 预配置 Provider（启动时 seed 到 DB）
_SEED_PROVIDERS = {
    "qwen": {
        "display_name": "阿里百炼",
        "description": "通义千问，阿里云大模型服务",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
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
        "models": [
            {"label": "DeepSeek-V3", "value": "deepseek-ai/DeepSeek-V3"},
            {"label": "Qwen2.5-72B", "value": "Qwen/Qwen2.5-72B-Instruct"},
            {"label": "Qwen2.5-Coder-32B", "value": "Qwen/Qwen2.5-Coder-32B-Instruct"},
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
                    fast_model="",
                    code=None,
                    is_public=True,
                    created_at=_seed_time,
                    updated_at=_seed_time,
                )
                session.add(record)
            else:
                # 已存在的内置 Provider 确保标记为公共
                record.is_public = True
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
                "fast_model": p.fast_model,
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
                    "fast_model": item.get("fast_model") or "",
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


class LLMManager:
    """大模型管理器（主模型 + 降级链）"""

    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self.api_key = settings.OPENAI_API_KEY
        self.api_base = settings.OPENAI_API_BASE
        self.model = settings.OPENAI_MODEL
        self.embedding_model = settings.OPENAI_EMBEDDING_MODEL
        self.fallback_models = _parse_fallback_models(settings.LLM_FALLBACK_MODELS)
        self._client = None
        self._client_cache: Dict[tuple, Any] = {}
        self._initialized = False

    def _available_models(self) -> List[str]:
        """当前 Provider 可用的文本模型列表"""
        cfg = get_user_llm_config()
        provider = cfg.get("provider") if cfg else self.provider
        info = _provider_registry.get(provider)
        if info and info.get("models"):
            return [m["value"] for m in info["models"] if m.get("value")]
        if cfg and cfg.get("model"):
            return [cfg["model"]]
        return [self.model] if self.model else []

    def _available_models_with_desc(self) -> List[tuple]:
        """返回 (model_value, description) 列表，description 包含能力提示"""
        cfg = get_user_llm_config()
        provider = cfg.get("provider") if cfg else self.provider
        info = _provider_registry.get(provider)
        result = []
        if info and info.get("models"):
            for m in info["models"]:
                val = m.get("value", "")
                label = m.get("label", val)
                if not val:
                    continue
                # 根据模型名推断能力描述
                desc = label
                name_lower = val.lower()
                if "flash" in name_lower:
                    desc += "（轻量快速，适合简单任务）"
                elif "v" in name_lower and ("plus" in name_lower or "flash" in name_lower):
                    desc += "（视觉模型，图片识别）"
                elif "5.2" in val or "max" in name_lower or "plus" in name_lower:
                    desc += "（最强，复杂推理）"
                else:
                    desc += "（通用）"
                result.append((val, desc))
        if not result:
            m = self._first_model()
            result.append((m, "通用"))
        return result

    def _first_model(self) -> str:
        """取第一个可用模型（兜底）"""
        models = self._available_models()
        return models[0] if models else self.model or "gpt-3.5-turbo"

    def _eff_vision_model(self, provider: str = "") -> str:
        """根据 provider 选择视觉模型（空字符串=不支持）"""
        cfg = get_user_llm_config()
        p = provider or (cfg.get("provider") if cfg else self.provider)
        return _PROVIDER_VISION_MODELS.get(p, "")

    _model_cache: Dict[str, str] = {}

    _SIMPLE_CONTEXTS = {"参数推断", "对话"}

    def _find_flash_model(self) -> str:
        """从可用模型列表中找一个轻量模型（名称含 flash）"""
        for m in self._available_models():
            if "flash" in m.lower():
                return m
        return ""

    async def pick_model_async(self, message: str, history: List[Dict] = None, context: str = "") -> str:
        """根据任务上下文自动推断选择最合适且最经济的模型。

        Args:
            message: 用户消息
            context: 任务场景描述（如"参数推断"、"代码生成"、"调试修复"、"对话"）
        """
        if not message and not context:
            return self._first_model()

        # 简单场景（参数推断/对话）直接用轻量模型，不问 LLM
        if context in self._SIMPLE_CONTEXTS:
            flash = self._find_flash_model()
            if flash:
                return flash

        cache_key = (context or "") + "|" + (message[:200] if message else "")
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]

        models = self._available_models()
        if len(models) <= 1:
            return models[0] if models else self._first_model()

        # 构建模型列表（含能力描述）
        model_descs = self._available_models_with_desc()
        model_list = "\n".join(f"- {val}：{desc}" for val, desc in model_descs)
        vision = self._eff_vision_model()
        embedding = self._eff_embedding_model()
        if vision and vision not in models:
            model_list += f"\n- {vision}：图片识别/OCR专用"
        if embedding and embedding not in models:
            model_list += f"\n- {embedding}：向量化专用"

        ctx_desc = ""
        if context:
            _ctx_map = {
                "参数推断": "简单任务：根据用户指令拼装参数，不需要复杂推理",
                "技能脚本调用": "技能脚本中的 LLM 调用，根据脚本逻辑判断",
                "技能修改": "复杂任务：修改技能规范和脚本，需要强推理",
                "算子生成": "复杂任务：生成代码，需要强推理",
                "算子修改": "复杂任务：修改代码，需要强推理",
                "算子调试": "复杂任务：调试修复代码，需要强推理",
                "流程生成": "复杂任务：生成流程代码，需要强推理",
                "调试修复": "复杂任务：调试修复代码，需要强推理",
                "对话": "简单任务：日常对话，不需要复杂推理",
            }
            ctx_desc = f"\n任务场景：{context}（{_ctx_map.get(context, context)}）"
        try:
            prompt = (
                f"以下是当前可用的模型列表：\n{model_list}\n"
                f"{ctx_desc}"
                f"\n用户消息：{message[:500] if message else '(无)'}\n\n"
                f"请选择最合适且最经济的模型。原则：能用轻量模型完成的不用重量模型，"
                f"图片任务必须选视觉模型，向量化必须选嵌入模型。"
                f"只返回模型名称，不要其他内容。"
            )
            resp = await self.chat(prompt, model=models[0], temperature=0.0, max_tokens=50)
            chosen = resp.strip().strip('"').strip("'")
            all_models = set(models)
            if vision:
                all_models.add(vision)
            if embedding:
                all_models.add(embedding)
            if chosen in all_models:
                self._model_cache[cache_key] = chosen
                if len(self._model_cache) > 100:
                    self._model_cache.pop(next(iter(self._model_cache)))
                return chosen
            return self._fallback_model(message)
        except Exception as e:
            logger.warning(f"模型推断失败，回退: {e}")
            return self._fallback_model(message)

    def _fallback_model(self, message: str) -> str:
        """兜底模型选择：检查是否涉及图片/向量，否则用第一个可用模型"""
        if message:
            msg_lower = message.lower()
            _vision_kw = {"图片", "识别", "ocr", "OCR", "身份证", "营业执照", "证件", "截图", "image", "photo"}
            _embedding_kw = {"向量化", "向量", "embedding", "语义搜索", "相似度", "vector"}
            for kw in _vision_kw:
                if kw in msg_lower or kw in message:
                    v = self._eff_vision_model()
                    if v:
                        return v
            for kw in _embedding_kw:
                if kw in msg_lower or kw in message:
                    e = self._eff_embedding_model()
                    if e:
                        return e
        return self._first_model()

    def pick_model(self, message: str, history: List[Dict] = None) -> str:
        """同步模型选择（兜底，用关键词）。异步场景用 pick_model_async。"""
        return self._fallback_model(message or "")

    def _resolve_model(self, model: Optional[str]) -> str:
        """解析模型：指定则用指定，断路器熔断则降级。"""
        target = model or self._first_model()
        if _circuit.is_available(target):
            return target
        models = self._available_models()
        for m in models:
            if m != target and _circuit.is_available(m):
                logger.warning(f"断路器降级: {target} 不可用，切换到 {m}")
                return m
        return target

    def _degradation_chain(self, target: str) -> List[str]:
        """构建降级链：目标模型 → 其他可用模型，去重。"""
        chain = [target]
        for m in self._available_models():
            if m != target and m not in chain:
                chain.append(m)
        return chain

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
        """返回有序模型配置列表（主模型 + 有 key 的降级模型）；用户配置优先"""
        cfg = get_user_llm_config()
        if cfg:
            configs = [{
                "provider": cfg.get("provider", ""),
                "api_key": cfg.get("api_key", ""),
                "api_base": cfg.get("api_base", ""),
                "model": cfg.get("model", ""),
            }]
            for fb in (cfg.get("fallback_models") or []):
                if fb.get("api_key"):
                    configs.append(fb)
            return configs
        configs = [{
            "provider": self.provider,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "model": self.model,
        }]
        for fb in (self.fallback_models or []):
            if fb.get("api_key"):
                configs.append(fb)
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

    async def initialize(self):
        """初始化LLM客户端"""
        if self._initialized and self._client:
            return
        try:
            # 优先使用当前请求用户的配置（contextvar），避免全局无 key 时创建空 client 失败
            user_cfg = get_user_llm_config()
            primary = {
                "provider": (user_cfg or {}).get("provider") or self.provider,
                "api_key": (user_cfg or {}).get("api_key") or self.api_key,
                "api_base": (user_cfg or {}).get("api_base") or self.api_base,
                "model": (user_cfg or {}).get("model") or self.model,
            }
            self._client = self._client_for(primary)
            self._initialized = True
            fb_desc = f", fallback={[f['provider']+'/'+f['model'] for f in self.fallback_models]}" if self.fallback_models else ""
            logger.info(f"LLM客户端初始化完成: provider={primary['provider']}, model={primary['model']}{fb_desc}")
        except Exception as e:
            logger.error(f"LLM客户端初始化失败: {e}")
            raise

    async def reinitialize(self, provider: str, api_key: str, api_base: str = None, model: str = None, embedding_model: str = None, fallback_models: List[Dict[str, str]] = None):
        """使用新配置重新初始化LLM客户端"""
        self.provider = provider
        self.api_key = api_key
        self.api_base = api_base
        self.model = model or self.model
        self.embedding_model = embedding_model or self.embedding_model
        if fallback_models is not None:
            self.fallback_models = fallback_models
        # 清空客户端缓存，强制按新配置重建
        self._client_cache = {}
        self._client = None
        self._initialized = False
        await self.initialize()

    # ---------- 非流式调用（全链路降级） ----------
    async def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        context: str = "",
    ) -> str:
        """与大模型对话。model=None 时自动推断。"""
        if not self._initialized:
            await self.initialize()

        if model is None:
            model = await self.pick_model_async(prompt, context=context)

        last_err = None
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
                last_err = e
                logger.warning(f"LLM chat失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
        raise last_err or RuntimeError("无可用LLM模型")

    async def chat_with_messages(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        context: str = "",
    ) -> str:
        """多轮对话，支持 system/user/assistant 消息列表。model=None 时自动推断。"""
        if not self._initialized:
            await self.initialize()

        if model is None:
            _last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    _last_user = m.get("content", "")[:500]
                    break
            model = await self.pick_model_async(_last_user, context=context)

        last_err = None
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
                last_err = e
                logger.warning(f"LLM chat_with_messages失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
        raise last_err or RuntimeError("无可用LLM模型")

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

        last_err = None
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
                last_err = e
                logger.warning(f"LLM chat_with_tools失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
        raise last_err or RuntimeError("无可用LLM模型")

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

        last_err = None
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
                last_err = e
                logger.warning(f"LLM chat_stream创建失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
            try:
                async for chunk in _stream_with_timeout(stream):
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            except Exception as e:
                last_err = e
                logger.warning(f"模型 {actual_model} 流式超时/中断: {e}，尝试下一个模型")
                continue
        raise last_err or RuntimeError("无可用LLM模型")

    async def chat_stream_with_messages(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        context: str = "",
    ) -> AsyncGenerator[str, None]:
        """多轮流式对话。model=None 时自动推断。"""
        if not self._initialized:
            await self.initialize()

        if model is None:
            _last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    _last_user = m.get("content", "")[:500]
                    break
            model = await self.pick_model_async(_last_user, context=context)

        last_err = None
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
                last_err = e
                logger.warning(f"LLM chat_stream_with_messages创建失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
            try:
                async for chunk in _stream_with_timeout(stream):
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            except Exception as e:
                last_err = e
                logger.warning(f"模型 {actual_model} 流式超时/中断: {e}，尝试下一个模型")
                continue
        raise last_err or RuntimeError("无可用LLM模型")

    async def chat_stream_with_thinking(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        context: str = "",
    ) -> AsyncGenerator[Dict[str, str], None]:
        """流式对话（含推理过程）。model=None 时自动推断。"""
        if not self._initialized:
            await self.initialize()

        if model is None:
            _last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    _last_user = m.get("content", "")[:500]
                    break
            model = await self.pick_model_async(_last_user, context=context)

        target_model = self._resolve_model(model)
        chain = self._degradation_chain(target_model)
        tried_models: List[str] = []

        for attempt_model in chain:
            if attempt_model in tried_models:
                continue
            if not _circuit.is_available(attempt_model):
                continue
            tried_models.append(attempt_model)

            cfg = self._model_configs()[0]
            try:
                logger.info(f"LLM chat_stream_with_thinking: model={attempt_model}")
                create_kwargs = dict(
                    model=attempt_model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                )
                stream = await self._acreate(cfg, **create_kwargs)
            except Exception as e:
                _circuit.record_failure(attempt_model)
                logger.warning(f"模型 {attempt_model} 连接失败: {e}，尝试降级")
                continue

            try:
                yield {"type": "model", "content": attempt_model}
                async for chunk in _stream_with_timeout(stream):
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        yield {"type": "thinking", "content": delta.reasoning_content}
                    if delta.content:
                        yield {"type": "content", "content": delta.content}

                _circuit.record_success(attempt_model)
                return
            except Exception as e:
                _circuit.record_failure(attempt_model)
                logger.warning(f"模型 {attempt_model} 流式中断: {e}，尝试降级")
                continue

        raise RuntimeError(f"所有模型均不可用: {tried_models}")

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

        last_err = None
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
                last_err = e
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
                last_err = e
                logger.warning(f"模型 {actual_model} 流式超时/中断: {e}，尝试下一个模型")
                continue
        raise last_err or RuntimeError("无可用LLM模型")

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

        target_model = self._resolve_model(model)
        chain = self._degradation_chain(target_model)
        tried_models: List[str] = []

        for attempt_model in chain:
            if attempt_model in tried_models:
                continue
            if not _circuit.is_available(attempt_model):
                continue
            tried_models.append(attempt_model)

            cfg = self._model_configs()[0]
            try:
                logger.info(f"LLM stream+tools: model={attempt_model}, tools={[t['function']['name'] for t in tools]}")
                create_kwargs = dict(
                    model=attempt_model,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    stream=True,
                )
                stream = await self._acreate(cfg, **create_kwargs)
            except Exception as e:
                _circuit.record_failure(attempt_model)
                logger.warning(f"模型 {attempt_model} 连接失败: {e}，尝试降级")
                continue

            try:
                yield {"type": "model", "content": attempt_model}

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

                _circuit.record_success(attempt_model)

                tc_list = [accumulated_tc[i] for i in sorted(accumulated_tc.keys())]
                if tc_list:
                    yield {"type": "tool_calls", "tool_calls": tc_list}

                yield {"type": "finish", "finish_reason": finish_reason or "stop"}
                return

            except Exception as e:
                _circuit.record_failure(attempt_model)
                logger.warning(f"模型 {attempt_model} 流式中断: {e}，尝试降级")
                continue

        raise RuntimeError(f"所有模型均不可用: {tried_models}")

    # ---------- 嵌入 ----------
    def _eff_embedding_model(self, provider: str = "") -> str:
        """根据 provider 选择 embedding 模型（用户配置优先 → provider 默认 → 全局兜底）"""
        cfg = get_user_llm_config()
        if cfg and cfg.get("embedding_model"):
            return cfg["embedding_model"]
        if provider and provider in _PROVIDER_EMBEDDING_MODELS:
            emb = _PROVIDER_EMBEDDING_MODELS[provider]
            if emb:
                return emb
        return self.embedding_model or settings.OPENAI_EMBEDDING_MODEL

    async def embed(self, text: str) -> list:
        """生成文本嵌入向量（主模型，失败则降级）"""
        if not self._initialized:
            await self.initialize()

        last_err = None
        for cfg in self._model_configs():
            try:
                client = self._client_for(cfg)
                provider = cfg.get("provider", "")
                emb_model = self._eff_embedding_model(provider)
                if not emb_model:
                    raise RuntimeError(f"Provider {provider} 不支持嵌入模型，无法处理向量化任务")
                response = await client.embeddings.create(
                    model=emb_model,
                    input=text,
                )
                return response.data[0].embedding
            except Exception as e:
                last_err = e
                logger.warning(f"LLM embed失败 [{cfg['provider']}/{cfg['model']}]: {e}，尝试下一个模型")
                continue
        raise last_err or RuntimeError("无可用LLM模型")

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
