"""自然语言处理服务"""

import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class IntentResult:
    """意图识别结果"""
    intent_type: str
    confidence: float
    description: str


@dataclass
class Entity:
    """实体"""
    entity_type: str
    value: str
    start: int = 0
    end: int = 0


@dataclass
class ProcessingResult:
    """NL处理结果"""
    intent: IntentResult
    entities: List[Entity]
    skills: List[Dict[str, Any]]


class IntentRecognizer:
    """意图识别器"""

    INTENT_TYPES = [
        "data_cleaning",
        "data_transformation",
        "data_aggregation",
        "data_analysis",
        "data_fusion",
        "data_export",
        "create_operator",
        "create_skill",
        "create_pipeline",
    ]

    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager

    async def recognize(self, text: str, context: dict = None) -> IntentResult:
        """识别用户意图"""
        # 简化版本:基于关键词匹配
        text_lower = text.lower()
        
        if any(kw in text_lower for kw in ["清洗", "去重", "填充", "空值"]):
            intent_type = "data_cleaning"
        elif any(kw in text_lower for kw in ["选择", "转换", "重命名"]):
            intent_type = "data_transformation"
        elif any(kw in text_lower for kw in ["统计", "分组", "聚合", "求和", "平均"]):
            intent_type = "data_aggregation"
        elif any(kw in text_lower for kw in ["分析", "分布", "相关"]):
            intent_type = "data_analysis"
        elif any(kw in text_lower for kw in ["连接", "合并", "融合"]):
            intent_type = "data_fusion"
        elif any(kw in text_lower for kw in ["导出", "保存"]):
            intent_type = "data_export"
        else:
            intent_type = "data_analysis"
        
        return IntentResult(
            intent_type=intent_type,
            confidence=0.8,
            description=text,
        )


class EntityExtractor:
    """实体提取器"""

    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager

    async def extract(self, text: str, context: dict = None) -> List[Entity]:
        """提取关键实体"""
        # 简化版本:返回空列表
        return []


class SkillMatcher:
    """技能匹配器"""

    def __init__(self, skill_library=None):
        self.skill_library = skill_library

    async def match(
        self,
        text: str,
        intent: IntentResult,
        entities: List[Entity],
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """匹配相关技能"""
        if not self.skill_library:
            return []

        try:
            # 使用原始文本搜索相似技能
            results = await self.skill_library.search_similar(
                query=text,
                top_k=top_k
            )
            return results
        except Exception as e:
            logger.error(f"技能匹配失败: {e}")
            return []


class NLService:
    """自然语言处理服务"""

    def __init__(self, llm_manager=None, skill_library=None):
        self.llm_manager = llm_manager
        self.skill_library = skill_library
        self.intent_recognizer = IntentRecognizer(llm_manager)
        self.entity_extractor = EntityExtractor(llm_manager)
        self.skill_matcher = SkillMatcher(skill_library)

    async def process(self, text: str, context: dict = None) -> ProcessingResult:
        """处理自然语言输入"""
        # 1. 识别意图
        intent = await self.intent_recognizer.recognize(text, context)
        logger.info(f"识别意图: {intent.intent_type} (置信度: {intent.confidence})")

        # 2. 提取实体
        entities = await self.entity_extractor.extract(text, context)
        logger.info(f"提取实体: {len(entities)}个")

        # 3. 匹配技能
        skills = await self.skill_matcher.match(text, intent, entities)
        logger.info(f"匹配技能: {len(skills)}个")

        return ProcessingResult(
            intent=intent,
            entities=entities,
            skills=skills,
        )
