"""LLM管理器（支持多模型降级 + 瞬态重试）"""

import json
from typing import Optional, AsyncGenerator, List, Dict, Any
from app.core.config import settings
from loguru import logger

# 瞬态重试异常类型（仅对这些错误重试同一模型，其他直接降级）
_TRANSIENT_ERRORS = None

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


# 不同provider的API base URL配置
PROVIDER_BASE_URLS = {
    "openai": None,  # 使用默认值
    "azure": None,  # 需要用户设置
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "custom": None,  # 用户自定义
}

# 各 provider 的快速模型（用于调试对话等不需要深度推理的场景）
FAST_MODELS = {
    "glm": "glm-4-flash",
    "qwen": "qwen-turbo",
    "siliconflow": "Qwen/Qwen2.5-7B-Instruct",
    "openai": "gpt-4o-mini",
    "custom": None,
}


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
                    "provider": item.get("provider") or "custom",
                    "api_key": item.get("api_key") or "",
                    "api_base": item.get("api_base"),
                    "model": item.get("model"),
                })
        return out
    except Exception as e:
        logger.warning(f"解析 LLM_FALLBACK_MODELS 失败: {e}")
        return []


# 触发深度模型的关键词（需要代码生成/修改/深度分析）
_DEEP_MODEL_KEYWORDS = {
    "修改", "修复", "修改脚本", "改一下", "帮我改", "fix", "修复代码",
    "优化", "重构", "改进", "重写", "改写", "optimize", "refactor", "improve",
    "生成", "创建", "写一个", "生成代码", "generate", "create", "modify", "rewrite",
    "报错", "错误", "失败", "异常", "error", "exception", "traceback", "fail", "failed",
    "不对", "不正确", "有问题", "不工作", "bug", "wrong", "incorrect",
}


def should_use_deep_model(message: str, is_retry: bool = False) -> bool:
    """根据用户消息和上下文判断是否应该使用深度模型。

    - 执行失败后重试 → 深度模型（需要分析错误+改代码）
    - 消息含修改/修复/优化/生成/报错等关键词 → 深度模型
    - 其他（运行/执行/解释/分析） → 快速模型
    """
    if is_retry:
        return True
    msg_lower = message.lower()
    for kw in _DEEP_MODEL_KEYWORDS:
        if kw in msg_lower or kw in message:
            return True
    return False


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

    @property
    def fast_model(self) -> str:
        """返回快速模型名（非推理模型，用于调试对话等场景）。
        优先使用配置的 LLM_FAST_MODEL，否则按 provider 自动选择。"""
        configured = getattr(settings, 'LLM_FAST_MODEL', '') or ''
        return configured.strip() or FAST_MODELS.get(self.provider) or self.model

    def pick_model(self, message: str, is_retry: bool = False) -> str:
        """根据消息内容动态选择模型：深度任务用主模型，轻量任务用快速模型。"""
        if should_use_deep_model(message, is_retry):
            return self.model
        return self.fast_model

    # ---------- 客户端管理 ----------
    def _client_for(self, cfg: Dict[str, str]):
        """按配置构建/复用 AsyncOpenAI 客户端"""
        key = (cfg.get("provider"), cfg.get("api_base"), cfg.get("api_key"), cfg.get("model"))
        cached = self._client_cache.get(key)
        if cached is not None:
            return cached
        from openai import AsyncOpenAI
        api_key = cfg.get("api_key") or ""
        base_url = cfg.get("api_base") or PROVIDER_BASE_URLS.get(cfg.get("provider"))
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
        """返回有序模型配置列表（主模型 + 有 key 的降级模型）"""
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
            # 主客户端写入缓存，便于复用
            primary = {
                "provider": self.provider,
                "api_key": self.api_key,
                "api_base": self.api_base,
                "model": self.model,
            }
            self._client = self._client_for(primary)
            self._initialized = True
            fb_desc = f", fallback={[f['provider']+'/'+f['model'] for f in self.fallback_models]}" if self.fallback_models else ""
            logger.info(f"LLM客户端初始化完成: provider={self.provider}, model={self.model}{fb_desc}")
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
        max_tokens: int = 2000,
    ) -> str:
        """与大模型对话"""
        if not self._initialized:
            await self.initialize()

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
        max_tokens: int = 2000,
    ) -> str:
        """多轮对话，支持 system/user/assistant 消息列表"""
        if not self._initialized:
            await self.initialize()

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
        max_tokens: int = 2000,
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
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            return
        raise last_err or RuntimeError("无可用LLM模型")

    async def chat_stream_with_messages(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """多轮流式对话"""
        if not self._initialized:
            await self.initialize()

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
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            return
        raise last_err or RuntimeError("无可用LLM模型")

    async def chat_stream_with_thinking(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, str], None]:
        if not self._initialized:
            await self.initialize()

        last_err = None
        for cfg in self._model_configs():
            actual_model = model or cfg["model"]
            try:
                logger.info(f"LLM chat_stream_with_thinking: provider={cfg['provider']}, model={actual_model}")
                create_kwargs = dict(
                    model=actual_model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                )
                if max_tokens:
                    create_kwargs["max_tokens"] = max_tokens
                stream = await self._acreate(cfg, **create_kwargs)
            except Exception as e:
                last_err = e
                logger.warning(f"LLM chat_stream_with_thinking创建失败 [{cfg['provider']}/{actual_model}]: {e}，尝试下一个模型")
                continue
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    yield {"type": "thinking", "content": delta.reasoning_content}
                if delta.content:
                    yield {"type": "content", "content": delta.content}
            return
        raise last_err or RuntimeError("无可用LLM模型")

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
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'type': 'content', 'content': delta.content}, ensure_ascii=False)}\n\n"
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        yield f"data: {json.dumps({'type': 'tool_call', 'id': tc.id, 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}}, ensure_ascii=False)}\n\n"
            return
        raise last_err or RuntimeError("无可用LLM模型")

    # ---------- 嵌入 ----------
    async def embed(self, text: str) -> list:
        """生成文本嵌入向量（主模型，失败则降级）"""
        if not self._initialized:
            await self.initialize()

        last_err = None
        for cfg in self._model_configs():
            try:
                client = self._client_for(cfg)
                response = await client.embeddings.create(
                    model=self.embedding_model or settings.OPENAI_EMBEDDING_MODEL,
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
        max_tokens: int = 2000,
    ) -> str:
        """生成文本响应（chat方法的别名）"""
        return await self.chat(prompt, model=model, temperature=temperature, max_tokens=max_tokens)


# 全局LLM管理器实例
llm_manager = LLMManager()
