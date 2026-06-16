"""智能代码生成服务"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from uuid import uuid4

from app.services.nl_service import NLService, IntentResult, Entity
from app.services.operators import OPERATOR_REGISTRY


@dataclass
class CodeStep:
    """流程步骤"""
    id: str = field(default_factory=lambda: str(uuid4()))
    skill_id: str = ""
    skill_name: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)


@dataclass
class ComposedCode:
    """组合流程"""
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    nl_description: str = ""
    intent: Optional[IntentResult] = None
    steps: List[CodeStep] = field(default_factory=list)
    validation_result: Optional[Dict] = None


class NLCodeGenerator:
    """自然语言代码生成器"""

    def __init__(self, nl_service: NLService):
        self.nl_service = nl_service

    async def generate(self, nl_description: str, context: dict = None) -> ComposedCode:
        """从自然语言描述生成处理流程"""
        # 1. NL处理
        result = await self.nl_service.process(nl_description, context)

        # 2. 根据意图匹配算子
        steps = self._match_operators(result.intent, result.entities)

        # 3. 推理参数
        self._infer_parameters(steps, result.entities, context)

        # 4. 验证流程
        validation = self._validate_code(steps)

        return ComposedCode(
            name=f"流程-{result.intent.intent_type}",
            nl_description=nl_description,
            intent=result.intent,
            steps=steps,
            validation_result=validation,
        )

    def _match_operators(self, intent: IntentResult, entities: List[Entity]) -> List[CodeStep]:
        """根据意图匹配算子"""
        steps = []
        intent_map = {
            "data_cleaning": ["dropna", "fillna", "duplicate"],
            "data_transformation": ["select", "rename"],
            "data_aggregation": ["groupby", "aggregate"],
            "data_analysis": ["statistics", "correlation"],
            "data_fusion": ["join"],
            "data_export": [],
        }

        operator_names = intent_map.get(intent.intent_type, [])
        for i, op_name in enumerate(operator_names):
            if op_name in OPERATOR_REGISTRY:
                step = CodeStep(
                    skill_name=op_name,
                    parameters={},
                    depends_on=[steps[i-1].id] if i > 0 else [],
                )
                steps.append(step)

        return steps

    def _infer_parameters(
        self, steps: List[CodeStep], entities: List[Entity], context: dict = None
    ) -> None:
        """推理参数"""
        for step in steps:
            # TODO: 基于实体和上下文推理参数
            pass

    def _validate_code(self, steps: List[CodeStep]) -> Dict[str, Any]:
        """验证流程"""
        errors = []
        for step in steps:
            if not step.skill_name:
                errors.append(f"步骤 {step.id} 缺少技能名称")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }


class DynamicCodeExecutor:
    """动态流程执行器"""

    async def execute(self, code: ComposedCode, context: dict = None) -> Dict[str, Any]:
        """执行组合流程"""
        import pandas as pd

        results = {}
        env = {"main": pd.DataFrame()}  # 初始执行环境

        for step in code.steps:
            operator = OPERATOR_REGISTRY.get(step.skill_name)
            if not operator:
                raise ValueError(f"未知的算子: {step.skill_name}")

            # 执行算子
            output = operator.execute(inputs=env, params=step.parameters)
            results[step.id] = output
            env.update(output)

        return {
            "status": "success",
            "results": {k: v.get("main").to_dict() if hasattr(v.get("main"), "to_dict") else v for k, v in results.items()},
        }
