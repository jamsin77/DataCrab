"""自然语言数据处理服务 - 整合NL理解、技能匹配和执行"""

from __future__ import annotations

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger

from app.services.nl_service import NLService, ProcessingResult
from app.services.skill_library import SkillLibrary, skill_library
from app.services.pipeline_executor import (
    PipelineExecutor,
    Pipeline,
    PipelineStep,
    PipelineExecutionResult,
    create_pipeline_from_steps,
)
from app.services.skill_executor import ExecutionContext, ExecutionResult
from app.services.llm import llm_manager


@dataclass
class DataProcessingRequest:
    """数据处理请求"""
    natural_language: str
    input_data: pd.DataFrame
    context: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""


@dataclass
class DataProcessingResponse:
    """数据处理响应"""
    success: bool
    output_data: Optional[pd.DataFrame] = None
    pipeline_name: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    explanation: str = ""
    execution_time: float = 0.0
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)


@dataclass
class ParameterInferenceResult:
    """参数推理结果"""
    skill_name: str
    parameters: Dict[str, Any]
    confidence: float
    reasoning: str


class ParameterInferrer:
    """参数推理器 - 从自然语言推理技能参数"""

    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager

    async def infer_parameters(
        self,
        skill: Dict[str, Any],
        natural_language: str,
        data_columns: List[str],
        data_preview: Optional[pd.DataFrame] = None
    ) -> ParameterInferenceResult:
        """推理技能参数"""
        skill_name = skill.get("name")
        skill_params = skill.get("parameters", {})
        skill_desc = skill.get("description", "")

        # 构建推理提示
        prompt = self._build_inference_prompt(
            skill_name, skill_params, natural_language, data_columns, data_preview, skill_desc
        )

        try:
            # 使用LLM推理参数
            if self.llm_manager:
                response = await self.llm_manager.generate(prompt, temperature=0.1)
                result = self._parse_llm_response(response, skill_params)
            else:
                # 使用简单规则推理
                result = self._simple_inference(skill_name, natural_language, data_columns)

            return result

        except Exception as e:
            logger.error(f"参数推理失败: {e}")
            return ParameterInferenceResult(
                skill_name=skill_name,
                parameters={},
                confidence=0.0,
                reasoning=f"推理失败: {e}"
            )

    def _build_inference_prompt(
        self,
        skill_name: str,
        skill_params: Dict[str, Any],
        natural_language: str,
        data_columns: List[str],
        data_preview: Optional[pd.DataFrame],
        skill_desc: str = ""
    ) -> str:
        """构建推理提示"""
        params_json = json.dumps(skill_params, ensure_ascii=False, indent=2)
        columns_json = json.dumps(data_columns, ensure_ascii=False)
        param_constraints = self._build_param_constraints(skill_params)
        preview_str = ""
        if data_preview is not None and not data_preview.empty:
            preview_str = f"\n数据预览(前5行):\n{data_preview.to_string()}\n"

        prompt = f"""你是一个数据处理参数推理器。请根据用户的自然语言描述和当前数据信息，严格遵循技能参数定义，推理出执行所需的参数。

技能名称: {skill_name}
技能描述: {skill_desc or '(无)'}

技能参数定义:
{params_json}

{param_constraints}

数据列名: {columns_json}{preview_str}

用户描述: {natural_language}

## 严格要求
1. **参数名必须与参数定义完全一致**，不得自创参数名或使用近义词替换
2. **参数类型必须严格匹配定义**：
   - string/str → 字符串
   - int/integer → 整数
   - bool/boolean → true/false
   - dict/object → JSON 对象（如 {{"key": "value"}}），绝不能输出为数组
   - list/array → JSON 数组
3. **只输出参数定义中存在的参数**，不要添加定义之外的参数
4. **不要输出以下系统自动注入的参数**：datasource_id、datasource_name、datasource、table_name、table_names、tables、table —— 这些由系统自动注入，重复传入会导致冲突
5. **仔细区分语义角色**：数据源名（DataSource）是数据源连接的名称，表名（Table）是数据源中的表；不要将表名当作数据源名，也不要将数据源名当作表名
6. 对于 required 为 true 的参数必须提供值；对于 required 为 false 或有默认值的参数，如果用户未提及可以不输出
7. 对于 dict 类型参数（如 add_columns），格式为 {{"列名": 值}}，不要用 [{{"name":..., "value":...}}] 列表格式

请分析用户意图，推理出各参数的具体值和推理依据。

输出格式要求：
返回严格的 JSON 格式：
```json
{{
    "parameters": {{
        // 只包含参数定义中存在的参数，类型严格匹配
    }},
    "reasoning": "推理依据说明"
}}
```
"""
        return prompt

    def _build_param_constraints(self, skill_params: Any) -> str:
        """从参数定义构建人类可读的参数约束说明"""
        if not skill_params:
            return "（无参数定义）"

        lines = []
        if isinstance(skill_params, dict):
            for name, spec in skill_params.items():
                if isinstance(spec, dict):
                    ptype = spec.get("type", "未知")
                    required = spec.get("required", False)
                    desc = spec.get("description", "")
                    default = spec.get("default", None)
                    req_str = "必填" if required else "可选"
                    line = f"- {name} ({ptype}, {req_str})"
                    if desc:
                        line += f": {desc}"
                    if default is not None:
                        line += f" [默认: {default}]"
                    lines.append(line)
                else:
                    lines.append(f"- {name}: {spec}")
        elif isinstance(skill_params, list):
            for spec in skill_params:
                if isinstance(spec, dict):
                    name = spec.get("name", "未知")
                    ptype = spec.get("type", "未知")
                    required = spec.get("required", False)
                    desc = spec.get("description", "")
                    req_str = "必填" if required else "可选"
                    line = f"- {name} ({ptype}, {req_str})"
                    if desc:
                        line += f": {desc}"
                    lines.append(line)

        return "参数约束清单:\n" + "\n".join(lines) if lines else "（无参数定义）"

    def _parse_llm_response(
        self,
        response: str,
        skill_params: Dict[str, Any]
    ) -> ParameterInferenceResult:
        """解析LLM响应"""
        try:
            # 提取JSON部分
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return ParameterInferenceResult(
                    skill_name="",
                    parameters=data.get("parameters", {}),
                    confidence=data.get("confidence", 0.8),
                    reasoning=data.get("reasoning", "")
                )
        except json.JSONDecodeError:
            pass

        return ParameterInferenceResult(
            skill_name="",
            parameters={},
            confidence=0.5,
            reasoning=response
        )

    def _simple_inference(
        self,
        skill_name: str,
        natural_language: str,
        data_columns: List[str]
    ) -> ParameterInferenceResult:
        """简单规则推理"""
        params = {}
        reasoning = ""

        # 列名匹配
        mentioned_columns = []
        for col in data_columns:
            if col.lower() in natural_language.lower():
                mentioned_columns.append(col)

        if skill_name == "select":
            if mentioned_columns:
                params["columns"] = mentioned_columns
                reasoning = f"从描述中识别到列名: {mentioned_columns}"

        elif skill_name == "filter":
            # 尝试提取条件
            # 简单模式：检测比较关键词
            for keyword, op in [("大于", ">"), ("小于", "<"), ("等于", "=="), ("超过", ">")]:
                if keyword in natural_language:
                    for col in mentioned_columns:
                        # 尝试提取数值
                        numbers = re.findall(r'\d+', natural_language)
                        if numbers:
                            params["condition"] = f"{col} {op} {numbers[0]}"
                            reasoning = f"从描述中提取条件: {col} {keyword} {numbers[0]}"
                            break

        elif skill_name == "groupby":
            if mentioned_columns:
                params["group_column"] = mentioned_columns[0]
                if len(mentioned_columns) > 1:
                    params["agg_column"] = mentioned_columns[1]
                reasoning = f"分组列: {mentioned_columns[0]}"

        elif skill_name == "sort":
            if mentioned_columns:
                params["column"] = mentioned_columns[0]
                if "降序" in natural_language or "从大到小" in natural_language:
                    params["ascending"] = False
                reasoning = f"排序列: {mentioned_columns[0]}"

        return ParameterInferenceResult(
            skill_name=skill_name,
            parameters=params,
            confidence=0.7,
            reasoning=reasoning
        )


class PipelinePlanner:
    """Pipeline规划器 - 根据匹配的技能规划执行流程"""

    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager

    async def plan_pipeline(
        self,
        matched_skills: List[Dict[str, Any]],
        natural_language: str,
        data_columns: List[str]
    ) -> Tuple[Pipeline, str]:
        """规划Pipeline"""
        if not matched_skills:
            return None, "没有匹配到合适的技能"

        # 简单情况：单个技能
        if len(matched_skills) == 1:
            skill = matched_skills[0].get("skill", matched_skills[0])
            step = PipelineStep(
                step_id="step_1",
                skill_name=skill.get("name"),
                parameters={},
            )
            pipeline = Pipeline(
                name=f"single_{skill.get('name')}",
                description=natural_language,
                steps=[step]
            )
            explanation = f"使用技能 '{skill.get('display_name')}' 处理数据"
            return pipeline, explanation

        # 多技能情况：使用LLM规划顺序
        if self.llm_manager:
            return await self._plan_with_llm(matched_skills, natural_language, data_columns)
        else:
            return self._plan_simple(matched_skills, natural_language)

    async def _plan_with_llm(
        self,
        skills: List[Dict[str, Any]],
        natural_language: str,
        data_columns: List[str]
    ) -> Tuple[Pipeline, str]:
        """使用LLM规划Pipeline"""
        skill_names = [s.get("skill", s).get("name") for s in skills]
        skill_info = [
            {
                "name": s.get("skill", s).get("name"),
                "display_name": s.get("skill", s).get("display_name"),
                "description": s.get("skill", s).get("description")
            }
            for s in skills
        ]

        # 构建prompt（避免f-string嵌套问题）
        columns_json = json.dumps(data_columns, ensure_ascii=False)
        skills_json = json.dumps(skill_info, ensure_ascii=False, indent=2)

        prompt = f"""
你是一个数据处理流程规划器。请根据用户的自然语言描述和可用的技能，规划数据处理流程。

用户描述: {natural_language}

数据列: {columns_json}

可用技能:
{skills_json}

请规划：
1. 技能执行顺序
2. 每个技能的参数
3. 简要说明

输出JSON格式：
```json
{
    "steps": [
        {
            "skill_name": "技能名",
            "parameters": dict,
            "reason": "执行原因"
        }
    ],
    "explanation": "流程说明"
}
```
"""
        try:
            response = await self.llm_manager.generate(prompt, temperature=0.2)
            data = self._parse_json_response(response)

            if data:
                steps = []
                for i, step_data in enumerate(data.get("steps", [])):
                    step = PipelineStep(
                        step_id=f"step_{i+1}",
                        skill_name=step_data.get("skill_name"),
                        parameters=step_data.get("parameters", {})
                    )
                    steps.append(step)

                pipeline = Pipeline(
                    name="nl_generated_pipeline",
                    description=natural_language,
                    steps=steps
                )
                return pipeline, data.get("explanation", "")

        except Exception as e:
            logger.error(f"LLM规划失败: {e}")

        return self._plan_simple(skills, natural_language)

    def _plan_simple(
        self,
        skills: List[Dict[str, Any]],
        natural_language: str
    ) -> Tuple[Pipeline, str]:
        """简单规划 - 按匹配顺序执行"""
        steps = []
        explanation_parts = []

        for i, skill_match in enumerate(skills):
            skill = skill_match.get("skill", skill_match)
            step = PipelineStep(
                step_id=f"step_{i+1}",
                skill_name=skill.get("name"),
                parameters={}
            )
            steps.append(step)
            explanation_parts.append(skill.get("display_name", skill.get("name")))

        pipeline = Pipeline(
            name="simple_pipeline",
            description=natural_language,
            steps=steps
        )
        explanation = "执行流程: " + " -> ".join(explanation_parts)

        return pipeline, explanation

    def _parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """解析JSON响应"""
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        return None


class NaturalLanguageDataProcessor:
    """自然语言数据处理主服务"""

    def __init__(
        self,
        llm_manager=None,
        skill_library=None
    ):
        self.llm_manager = llm_manager
        # 使用传入的skill_library或全局实例
        if skill_library is None:
            from app.services.skill_library import skill_library as global_library
            self.skill_library = global_library
        else:
            self.skill_library = skill_library

        self.nl_service = NLService(llm_manager, self.skill_library)
        self.param_inferrer = ParameterInferrer(llm_manager)
        self.pipeline_planner = PipelinePlanner(llm_manager)
        self.pipeline_executor = PipelineExecutor(self.skill_library)

    async def process(
        self,
        request: DataProcessingRequest
    ) -> DataProcessingResponse:
        """处理自然语言数据请求"""
        logger.info(f"收到自然语言请求: {request.natural_language[:50]}...")
        start_time = 0

        try:
            import time
            start_time = time.time()

            # 1. 初始化技能库
            if not self.skill_library._initialized:
                await self.skill_library.initialize()

            # 2. NL处理：意图识别 + 技能匹配
            nl_result = await self.nl_service.process(
                request.natural_language,
                request.context
            )

            if not nl_result.skills:
                return DataProcessingResponse(
                    success=False,
                    error="无法理解您的请求，请尝试更具体的描述",
                    logs=["没有匹配到任何技能"]
                )

            # 3. 获取数据信息
            data_columns = list(request.input_data.columns)

            # 4. 规划Pipeline
            pipeline, explanation = await self.pipeline_planner.plan_pipeline(
                nl_result.skills,
                request.natural_language,
                data_columns
            )

            if not pipeline:
                return DataProcessingResponse(
                    success=False,
                    error="无法生成数据处理流程",
                    logs=["Pipeline规划失败"]
                )

            # 5. 推理每个步骤的参数
            for step in pipeline.steps:
                # 找到对应的技能
                skill = None
                for skill_match in nl_result.skills:
                    s = skill_match.get("skill", skill_match)
                    if s.get("name") == step.skill_name:
                        skill = s
                        break

                if skill:
                    # 推理参数
                    param_result = await self.param_inferrer.infer_parameters(
                        skill,
                        request.natural_language,
                        data_columns,
                        request.input_data.head(5)
                    )
                    step.parameters = param_result.parameters
                    logger.debug(f"步骤 {step.skill_name} 参数: {param_result.parameters}")

            # 6. 执行Pipeline
            execution_context = ExecutionContext(
                session_id=request.session_id,
                data_frames={"main": request.input_data}
            )

            execution_result = await self.pipeline_executor.execute(
                pipeline=pipeline,
                input_data=request.input_data,
                context=execution_context
            )

            # 7. 构建响应
            steps_info = []
            for step in pipeline.steps:
                steps_info.append({
                    "skill_name": step.skill_name,
                    "parameters": step.parameters
                })

            execution_time = time.time() - start_time

            if execution_result.success:
                return DataProcessingResponse(
                    success=True,
                    output_data=execution_result.final_output,
                    pipeline_name=pipeline.name,
                    steps=steps_info,
                    explanation=explanation,
                    execution_time=execution_time,
                    logs=execution_result.logs
                )
            else:
                return DataProcessingResponse(
                    success=False,
                    error=execution_result.error,
                    pipeline_name=pipeline.name,
                    steps=steps_info,
                    explanation=explanation,
                    execution_time=execution_time,
                    logs=execution_result.logs
                )

        except Exception as e:
            import time
            logger.error(f"处理失败: {e}")
            return DataProcessingResponse(
                success=False,
                error=str(e),
                logs=[f"处理异常: {e}"],
                execution_time=time.time() - start_time if start_time else 0
            )

    async def process_streaming(
        self,
        request: DataProcessingRequest
    ):
        """流式处理"""
        logger.info(f"开始流式处理: {request.natural_language[:50]}...")

        # 返回初始状态
        yield {"type": "init", "message": "正在分析您的请求..."}

        # 初始化技能库
        if not self.skill_library._initialized:
            await self.skill_library.initialize()
            yield {"type": "progress", "message": "技能库已初始化"}

        # NL处理
        yield {"type": "progress", "message": "正在理解您的意图..."}
        nl_result = await self.nl_service.process(
            request.natural_language,
            request.context
        )

        if not nl_result.skills:
            yield {"type": "error", "message": "无法理解您的请求"}
            return

        # 显示匹配的技能
        matched_names = [
            s.get("skill", s).get("display_name", s.get("skill", s).get("name"))
            for s in nl_result.skills[:3]
        ]
        yield {
            "type": "matched_skills",
            "skills": matched_names,
            "message": f"匹配到技能: {', '.join(matched_names)}"
        }

        # 规划Pipeline
        yield {"type": "progress", "message": "正在规划处理流程..."}
        data_columns = list(request.input_data.columns)
        pipeline, explanation = await self.pipeline_planner.plan_pipeline(
            nl_result.skills,
            request.natural_language,
            data_columns
        )

        yield {
            "type": "pipeline_plan",
            "steps": [s.skill_name for s in pipeline.steps],
            "explanation": explanation
        }

        # 推理参数
        yield {"type": "progress", "message": "正在推理参数..."}
        for step in pipeline.steps:
            skill = None
            for skill_match in nl_result.skills:
                s = skill_match.get("skill", skill_match)
                if s.get("name") == step.skill_name:
                    skill = s
                    break

            if skill:
                param_result = await self.param_inferrer.infer_parameters(
                    skill,
                    request.natural_language,
                    data_columns
                )
                step.parameters = param_result.parameters
                yield {
                    "type": "parameter_inferred",
                    "skill": step.skill_name,
                    "parameters": param_result.parameters,
                    "reasoning": param_result.reasoning
                }

        # 执行Pipeline
        yield {"type": "progress", "message": "正在执行处理流程..."}

        streaming_executor = self.pipeline_executor
        if hasattr(streaming_executor, 'execute_streaming'):
            for stream_event in await streaming_executor.execute_streaming(
                pipeline=pipeline,
                input_data=request.input_data
            ):
                yield stream_event
        else:
            # 非流式执行
            result = await streaming_executor.execute(
                pipeline=pipeline,
                input_data=request.input_data
            )
            yield {
                "type": "complete",
                "success": result.success,
                "output_shape": result.final_output.shape if result.final_output is not None else None
            }


# 全局处理器实例
nl_processor = NaturalLanguageDataProcessor()