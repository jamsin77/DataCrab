"""大模型公开API端点"""

import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.llm import llm_manager

router = APIRouter()


class LLMChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    model: Optional[str] = Field(None, description="模型名称，不传则用系统默认")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(2000, ge=1, le=32000, description="最大token数")


class LLMChatResponse(BaseModel):
    content: str
    model: str
    usage: Optional[Dict[str, int]] = None


class LLMChatMessagesRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(..., description="消息列表")
    model: Optional[str] = Field(None, description="模型名称")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(2000, ge=1, le=32000, description="最大token数")


class LLMStreamRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    model: Optional[str] = Field(None, description="模型名称")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度参数")


class LLMStreamMessagesRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(..., description="消息列表")
    model: Optional[str] = Field(None, description="模型名称")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度参数")


class LLMMessagesStreamRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(..., description="消息列表")
    model: Optional[str] = Field(None, description="模型名称")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度参数")


class LLMEmbedRequest(BaseModel):
    text: str = Field(..., description="要嵌入的文本")


@router.post("/chat", response_model=LLMChatResponse)
async def llm_chat(
    request: LLMChatRequest,
    current_user: User = Depends(get_current_user),
):
    """大模型对话（非流式）"""
    await llm_manager.initialize()
    try:
        result = await llm_manager.chat(
            prompt=request.message,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return LLMChatResponse(
            content=result,
            model=request.model or llm_manager.model,
        )
    except Exception as e:
        logger.error(f"LLM chat失败: {e}")
        raise HTTPException(status_code=500, detail=f"大模型调用失败: {str(e)}")


@router.post("/chat-messages", response_model=LLMChatResponse)
async def llm_chat_messages(
    request: LLMChatMessagesRequest,
    current_user: User = Depends(get_current_user),
):
    """大模型多轮对话（非流式）"""
    await llm_manager.initialize()
    try:
        result = await llm_manager.chat_with_messages(
            messages=request.messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return LLMChatResponse(
            content=result,
            model=request.model or llm_manager.model,
        )
    except Exception as e:
        logger.error(f"LLM chat_messages失败: {e}")
        raise HTTPException(status_code=500, detail=f"大模型调用失败: {str(e)}")


@router.post("/chat-stream")
async def llm_chat_stream(
    request: LLMStreamRequest,
    current_user: User = Depends(get_current_user),
):
    """大模型对话（SSE流式）"""
    from fastapi.responses import StreamingResponse

    await llm_manager.initialize()

    async def generate():
        try:
            async for chunk in llm_manager.chat_stream(
                prompt=request.message,
                model=request.model,
                temperature=request.temperature,
            ):
                yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"LLM chat_stream失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/chat-stream-messages")
async def llm_chat_stream_messages(
    request: LLMStreamMessagesRequest,
    current_user: User = Depends(get_current_user),
):
    """大模型多轮对话（SSE流式）"""
    from fastapi.responses import StreamingResponse

    await llm_manager.initialize()

    async def generate():
        try:
            async for chunk in llm_manager.chat_stream_with_messages(
                messages=request.messages,
                model=request.model,
                temperature=request.temperature,
            ):
                yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"LLM chat_stream_messages失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/chat-stream-thinking")
async def llm_chat_stream_thinking(
    request: LLMMessagesStreamRequest,
    current_user: User = Depends(get_current_user),
):
    """大模型多轮对话（SSE流式，含推理过程）"""
    from fastapi.responses import StreamingResponse

    await llm_manager.initialize()

    async def generate():
        try:
            async for chunk in llm_manager.chat_stream_with_thinking(
                messages=request.messages,
                model=request.model,
                temperature=request.temperature,
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"LLM chat_stream_thinking失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/embeddings")
async def llm_embeddings(
    request: LLMEmbedRequest,
    current_user: User = Depends(get_current_user),
):
    """生成文本嵌入向量"""
    await llm_manager.initialize()
    try:
        result = await llm_manager.embed(request.text)
        return {"embedding": result, "dimensions": len(result)}
    except Exception as e:
        logger.error(f"LLM embeddings失败: {e}")
        raise HTTPException(status_code=500, detail=f"嵌入生成失败: {str(e)}")
