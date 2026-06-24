"""LLM管理器"""

import json
from typing import Optional, AsyncGenerator, List, Dict, Any
from app.core.config import settings
from loguru import logger


# 不同provider的API base URL配置
PROVIDER_BASE_URLS = {
    "openai": None,  # 使用默认值
    "azure": None,  # 需要用户设置
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "custom": None,  # 用户自定义
}


class LLMManager:
    """大模型管理器"""

    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self.api_key = settings.OPENAI_API_KEY
        self.api_base = settings.OPENAI_API_BASE
        self.model = settings.OPENAI_MODEL
        self.embedding_model = settings.OPENAI_EMBEDDING_MODEL
        self._client = None
        self._initialized = False

    async def initialize(self):
        """初始化LLM客户端"""
        if self._initialized and self._client:
            return

        try:
            from openai import AsyncOpenAI

            api_key = self.api_key or settings.OPENAI_API_KEY
            base_url = self.api_base or settings.OPENAI_API_BASE
            if not base_url:
                base_url = PROVIDER_BASE_URLS.get(self.provider)

            if self.provider == "azure":
                self._client = AsyncOpenAI(
                    api_key=api_key,
                    azure_endpoint=base_url,
                    api_version="2024-02-15-preview",
                )
            else:
                self._client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=180.0,
                )

            self._initialized = True
            logger.info(f"LLM客户端初始化完成: provider={self.provider}, model={self.model}")

        except Exception as e:
            logger.error(f"LLM客户端初始化失败: {e}")
            raise

    async def reinitialize(self, provider: str, api_key: str, api_base: str = None, model: str = None, embedding_model: str = None):
        """使用新配置重新初始化LLM客户端"""
        from openai import AsyncOpenAI

        base_url = api_base
        if not base_url:
            base_url = PROVIDER_BASE_URLS.get(provider)

        if provider == "azure":
            self._client = AsyncOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version="2024-02-15-preview",
            )
        else:
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=180.0,
            )

        self.provider = provider
        self.api_key = api_key
        self.api_base = api_base
        self.model = model or self.model
        self.embedding_model = embedding_model or self.embedding_model
        self._initialized = True
        logger.info(f"LLM客户端重新初始化: provider={provider}, model={self.model}")

    async def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """与大模型对话"""
        if not self._initialized or not self._client:
            await self.initialize()

        actual_model = model or self.model or settings.OPENAI_MODEL
        logger.info(f"LLM chat调用: provider={self.provider}, model={actual_model}, api_base={self.api_base or settings.OPENAI_API_BASE}")

        response = await self._client.chat.completions.create(
            model=actual_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def chat_with_messages(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """多轮对话，支持 system/user/assistant 消息列表"""
        if not self._initialized or not self._client:
            await self.initialize()

        actual_model = model or self.model or settings.OPENAI_MODEL
        logger.info(f"LLM chat_with_messages: provider={self.provider}, model={actual_model}, messages_count={len(messages)}")

        response = await self._client.chat.completions.create(
            model=actual_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        if not self._initialized or not self._client:
            await self.initialize()

        actual_model = model or self.model or settings.OPENAI_MODEL
        logger.info(f"LLM chat_stream调用: provider={self.provider}, model={actual_model}, api_base={self.api_base or settings.OPENAI_API_BASE}")

        stream = await self._client.chat.completions.create(
            model=actual_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def chat_stream_with_messages(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """多轮流式对话"""
        if not self._initialized or not self._client:
            await self.initialize()

        actual_model = model or self.model or settings.OPENAI_MODEL
        logger.info(f"LLM chat_stream_with_messages: provider={self.provider}, model={actual_model}, messages_count={len(messages)}")

        stream = await self._client.chat.completions.create(
            model=actual_model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def chat_stream_with_thinking(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[Dict[str, str], None]:
        if not self._initialized or not self._client:
            await self.initialize()

        actual_model = model or self.model or settings.OPENAI_MODEL
        logger.info(f"LLM chat_stream_with_thinking: provider={self.provider}, model={actual_model}")

        stream = await self._client.chat.completions.create(
            model=actual_model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                yield {"type": "thinking", "content": delta.reasoning_content}
            if delta.content:
                yield {"type": "content", "content": delta.content}

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict:
        """带工具调用的对话，返回 OpenAI 格式的 response dict"""
        if not self._initialized or not self._client:
            await self.initialize()

        actual_model = model or self.model or settings.OPENAI_MODEL
        logger.info(f"LLM chat_with_tools: model={actual_model}, tools={[t['function']['name'] for t in tools]}")

        response = await self._client.chat.completions.create(
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
        }

    async def chat_stream_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """带工具调用的流式对话"""
        if not self._initialized or not self._client:
            await self.initialize()

        actual_model = model or self.model or settings.OPENAI_MODEL
        logger.info(f"LLM chat_stream_with_tools: model={actual_model}, tools={[t['function']['name'] for t in tools]}")

        stream = await self._client.chat.completions.create(
            model=actual_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield f"data: {json.dumps({'type': 'content', 'content': delta.content}, ensure_ascii=False)}\n\n"
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    yield f"data: {json.dumps({'type': 'tool_call', 'id': tc.id, 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}}, ensure_ascii=False)}\n\n"

    async def embed(self, text: str) -> list:
        """生成文本嵌入向量"""
        if not self._initialized or not self._client:
            await self.initialize()

        response = await self._client.embeddings.create(
            model=self.embedding_model or settings.OPENAI_EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

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
