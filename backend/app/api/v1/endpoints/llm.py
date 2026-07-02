"""大模型公开API端点"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.api.deps import get_current_user
from app.models.user import User
from app.services.llm import llm_manager

router = APIRouter()


class LLMEmbedRequest(BaseModel):
    text: str = Field(..., description="要嵌入的文本")


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
