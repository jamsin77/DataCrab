"""LLM管理器（支持多模型降级 + 瞬态重试 + ModelRouter 断路器）

设计借鉴 DeepAnalyze 的 ModelRouter：
- 默认用深度模型（主模型），失败自动降级到快速模型
- 断路器：连续 3 次失败的模型熔断 60 秒，之后 half-open 试探恢复
- 系统内部任务（参数推断等）直接用快速模型，不走断路器
- 不做关键词路由——由调用方声明任务类型，ModelRouter 负责降级
"""

import json
import time
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
        """快速模型名（系统内部任务 + 降级兜底）。"""
        configured = getattr(settings, 'LLM_FAST_MODEL', '') or ''
        return configured.strip() or FAST_MODELS.get(self.provider) or self.model

    def _resolve_model(self, model: Optional[str]) -> str:
        """解析模型：指定则用指定，断路器熔断则降级到快速模型。"""
        target = model or self.model
        if _circuit.is_available(target):
            return target
        logger.warning(f"断路器降级: {target} 不可用，切换到 {self.fast_model}")
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
        """流式对话（含推理过程）。
        
        模型选择策略（借鉴 DeepAnalyze ModelRouter）：
        - 默认用深度模型，断路器熔断时自动降级到快速模型
        - 连接失败时记录断路器，重试降级模型
        """
        if not self._initialized:
            await self.initialize()

        target_model = self._resolve_model(model)
        tried_models: List[str] = []

        for attempt_model in [target_model, self.fast_model]:
            if attempt_model in tried_models:
                continue
            if not _circuit.is_available(attempt_model):
                continue
            tried_models.append(attempt_model)

            cfg = self._model_configs()[0]  # 用主 provider 配置
            try:
                logger.info(f"LLM chat_stream_with_thinking: model={attempt_model}")
                create_kwargs = dict(
                    model=attempt_model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                )
                if max_tokens:
                    create_kwargs["max_tokens"] = max_tokens
                stream = await self._acreate(cfg, **create_kwargs)
            except Exception as e:
                _circuit.record_failure(attempt_model)
                logger.warning(f"模型 {attempt_model} 连接失败: {e}，尝试降级")
                continue

            try:
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
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
