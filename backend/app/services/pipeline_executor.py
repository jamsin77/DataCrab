"""Pipeline执行引擎 - 支持多技能组合执行"""

import asyncio
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import pandas as pd
from loguru import logger

from app.services.skill_executor import (
    SkillExecutor,
    ExecutionContext,
    ExecutionResult,
    BUILTIN_SKILL_EXECUTORS,
)


@dataclass
class PipelineStep:
    """Pipeline步骤"""
    step_id: str
    skill_name: str
    skill_id: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    input_mapping: Dict[str, str] = field(default_factory=dict)  # 输入映射
    output_name: str = "main"  # 输出名称


@dataclass
class Pipeline:
    """Pipeline定义"""
    name: str
    description: str = ""
    steps: List[PipelineStep] = field(default_factory=list)
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineExecutionResult:
    """Pipeline执行结果"""
    success: bool
    final_output: Optional[pd.DataFrame] = None
    step_results: Dict[str, ExecutionResult] = field(default_factory=dict)
    execution_time: float = 0.0
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)


class ContextManager:
    """上下文管理器 - 管理Pipeline执行过程中的数据流"""

    def __init__(self):
        self.data_frames: Dict[str, pd.DataFrame] = {}
        self.variables: Dict[str, Any] = {}

    def initialize(self, input_data: pd.DataFrame, input_name: str = "main"):
        """初始化输入数据"""
        self.data_frames[input_name] = input_data
        logger.debug(f"初始化数据: {input_name}, shape={input_data.shape}")

    def get_data(self, name: str) -> Optional[pd.DataFrame]:
        """获取数据"""
        return self.data_frames.get(name)

    def set_data(self, name: str, df: pd.DataFrame):
        """设置数据"""
        self.data_frames[name] = df
        logger.debug(f"设置数据: {name}, shape={df.shape}")

    def resolve_input_mapping(
        self,
        step: PipelineStep
    ) -> Dict[str, pd.DataFrame]:
        """解析步骤输入映射"""
        inputs = {}

        # 如果没有指定映射，使用默认的main数据
        if not step.input_mapping:
            default_data = self.get_data("main")
            if default_data is not None:
                inputs["main"] = default_data
            return inputs

        # 解析映射
        for input_name, source in step.input_mapping.items():
            if source.startswith("$input."):
                # 来自Pipeline输入
                var_name = source[7:]  # 去掉"$input."
                data = self.get_data(var_name)
            elif source.startswith("$step."):
                # 来自其他步骤输出
                parts = source[6:].split(".")
                step_id = parts[0]
                output_name = parts[1] if len(parts) > 1 else "main"
                data = self.get_data(f"{step_id}.{output_name}")
            else:
                # 直接引用变量名
                data = self.get_data(source)

            if data is not None:
                inputs[input_name] = data

        return inputs

    def save_step_output(self, step: PipelineStep, df: pd.DataFrame):
        """保存步骤输出"""
        output_key = f"{step.step_id}.{step.output_name}"
        self.set_data(output_key, df)
        # 同时保存为main，供后续步骤使用
        self.set_data("main", df)


class ProgressTracker:
    """进度跟踪器"""

    def __init__(self, total_steps: int = 0):
        self.total_steps = total_steps
        self.completed_steps = 0
        self.current_step = None
        self.start_time = None
        self.step_times: Dict[str, float] = {}

    def start(self):
        """开始跟踪"""
        self.start_time = time.time()

    def log_step_start(self, step_id: str, step_name: str):
        """记录步骤开始"""
        self.current_step = step_id
        self.step_times[step_id] = time.time()
        logger.info(f"[{self.completed_steps + 1}/{self.total_steps}] 开始执行: {step_name}")

    def log_step_complete(self, step_id: str, success: bool):
        """记录步骤完成"""
        if step_id in self.step_times:
            elapsed = time.time() - self.step_times[step_id]
        else:
            elapsed = 0

        if success:
            self.completed_steps += 1
            logger.info(f"[{self.completed_steps}/{self.total_steps}] 步骤完成, 耗时 {elapsed:.3f}s")
        else:
            logger.error(f"[{self.completed_steps + 1}/{self.total_steps}] 步骤失败")

    def get_progress(self) -> Dict[str, Any]:
        """获取进度"""
        if self.start_time:
            total_elapsed = time.time() - self.start_time
        else:
            total_elapsed = 0

        return {
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
            "progress_percent": (self.completed_steps / self.total_steps * 100) if self.total_steps > 0 else 0,
            "elapsed_time": total_elapsed,
        }


class ErrorHandler:
    """错误处理器"""

    def __init__(self, retry_count: int = 3, retry_delay: float = 1.0):
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.errors: List[str] = []

    async def handle_error(self, error: Exception, step: PipelineStep) -> bool:
        """处理错误"""
        error_msg = f"步骤 {step.step_id} ({step.skill_name}) 执行失败: {error}"
        self.errors.append(error_msg)
        logger.error(error_msg)

        # TODO: 实现重试逻辑
        return False

    def get_errors(self) -> List[str]:
        """获取所有错误"""
        return self.errors


class PipelineExecutor:
    """Pipeline执行引擎"""

    def __init__(self, skill_library=None):
        self.skill_library = skill_library
        self.skill_executor = SkillExecutor()
        self.context_manager = ContextManager()
        self.progress_tracker = ProgressTracker()
        self.error_handler = ErrorHandler()

    async def execute(
        self,
        pipeline: Pipeline,
        input_data: pd.DataFrame,
        context: ExecutionContext = None
    ) -> PipelineExecutionResult:
        """执行Pipeline"""
        start_time = time.time()
        logs = []

        logger.info(f"开始执行Pipeline: {pipeline.name}, 共 {len(pipeline.steps)} 个步骤")

        # 初始化
        self.context_manager.initialize(input_data)
        self.progress_tracker = ProgressTracker(total_steps=len(pipeline.steps))
        self.progress_tracker.start()

        step_results = {}

        try:
            for step in pipeline.steps:
                # 记录步骤开始
                self.progress_tracker.log_step_start(step.step_id, step.skill_name)

                # 执行步骤
                step_result = await self._execute_step(step, context)
                step_results[step.step_id] = step_result

                if step_result.success:
                    # 保存输出
                    self.context_manager.save_step_output(step, step_result.output)
                    self.progress_tracker.log_step_complete(step.step_id, True)
                    logs.append(f"步骤 {step.skill_name} 完成")
                else:
                    # 处理错误
                    should_continue = await self.error_handler.handle_error(
                        Exception(step_result.error),
                        step
                    )
                    self.progress_tracker.log_step_complete(step.step_id, False)

                    if not should_continue:
                        return PipelineExecutionResult(
                            success=False,
                            error=step_result.error,
                            step_results=step_results,
                            execution_time=time.time() - start_time,
                            logs=logs + self.error_handler.get_errors()
                        )

            # 获取最终输出
            final_output = self.context_manager.get_data("main")

            execution_time = time.time() - start_time
            logger.info(f"Pipeline执行完成, 总耗时 {execution_time:.3f}s")

            return PipelineExecutionResult(
                success=True,
                final_output=final_output,
                step_results=step_results,
                execution_time=execution_time,
                logs=logs
            )

        except Exception as e:
            logger.error(f"Pipeline执行异常: {e}")
            return PipelineExecutionResult(
                success=False,
                error=str(e),
                step_results=step_results,
                execution_time=time.time() - start_time,
                logs=logs + [f"执行异常: {e}"]
            )

    async def _execute_step(
        self,
        step: PipelineStep,
        context: ExecutionContext = None
    ) -> ExecutionResult:
        """执行单个步骤"""
        try:
            # 获取技能执行配置
            executor_config = BUILTIN_SKILL_EXECUTORS.get(step.skill_name)

            if not executor_config:
                # 尝试从技能库获取
                if self.skill_library:
                    skill = self.skill_library.get_skill(step.skill_id or step.skill_name)
                    if skill:
                        executor_config = skill.get("executor_config")

            if not executor_config:
                raise ValueError(f"未找到技能 {step.skill_name} 的执行配置")

            # 解析输入
            inputs = self.context_manager.resolve_input_mapping(step)

            if not inputs or len(inputs) == 0:
                # 使用当前main数据
                main_data = self.context_manager.get_data("main")
                if main_data is not None:
                    inputs = {"main": main_data}

            # 执行技能
            result = await self.skill_executor.execute(
                executor_config=executor_config,
                inputs=inputs,
                parameters=step.parameters
            )

            return result

        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                logs=[f"步骤执行失败: {e}"]
            )


class StreamingPipelineExecutor(PipelineExecutor):
    """支持流式响应的Pipeline执行器"""

    async def execute_streaming(
        self,
        pipeline: Pipeline,
        input_data: pd.DataFrame,
        context: ExecutionContext = None
    ):
        """流式执行Pipeline，逐步返回结果"""
        start_time = time.time()

        # 初始化
        self.context_manager.initialize(input_data)
        self.progress_tracker = ProgressTracker(total_steps=len(pipeline.steps))
        self.progress_tracker.start()

        # 返回初始状态
        yield {
            "type": "start",
            "pipeline_name": pipeline.name,
            "total_steps": len(pipeline.steps),
            "input_shape": input_data.shape
        }

        step_results = {}

        try:
            for i, step in enumerate(pipeline.steps):
                # 返回步骤开始状态
                yield {
                    "type": "step_start",
                    "step_id": step.step_id,
                    "step_name": step.skill_name,
                    "step_index": i,
                    "progress": self.progress_tracker.get_progress()
                }

                # 执行步骤
                self.progress_tracker.log_step_start(step.step_id, step.skill_name)
                step_result = await self._execute_step(step, context)
                step_results[step.step_id] = step_result

                if step_result.success:
                    self.context_manager.save_step_output(step, step_result.output)
                    self.progress_tracker.log_step_complete(step.step_id, True)

                    # 返回步骤完成状态和中间结果
                    yield {
                        "type": "step_complete",
                        "step_id": step.step_id,
                        "step_name": step.skill_name,
                        "success": True,
                        "output_shape": step_result.output.shape if step_result.output is not None else None,
                        "execution_time": step_result.metrics.get("execution_time", 0),
                        "logs": step_result.logs,
                        "preview": self._get_preview(step_result.output) if step_result.output is not None else None
                    }
                else:
                    self.progress_tracker.log_step_complete(step.step_id, False)

                    yield {
                        "type": "step_complete",
                        "step_id": step.step_id,
                        "step_name": step.skill_name,
                        "success": False,
                        "error": step_result.error,
                        "logs": step_result.logs
                    }

                    # 中断执行
                    break

            # 返回最终结果
            final_output = self.context_manager.get_data("main")
            execution_time = time.time() - start_time

            yield {
                "type": "complete",
                "success": final_output is not None,
                "final_output_shape": final_output.shape if final_output is not None else None,
                "execution_time": execution_time,
                "preview": self._get_preview(final_output) if final_output is not None else None,
                "total_steps": len(pipeline.steps),
                "completed_steps": self.progress_tracker.completed_steps
            }

        except Exception as e:
            yield {
                "type": "error",
                "error": str(e),
                "execution_time": time.time() - start_time
            }

    def _get_preview(self, df: pd.DataFrame, max_rows: int = 10) -> Dict[str, Any]:
        """获取数据预览"""
        if df is None:
            return None

        preview_df = df.head(max_rows)
        return {
            "columns": list(df.columns),
            "shape": df.shape,
            "data": preview_df.to_dict(orient="records"),
            "dtypes": {col: str(df[col].dtype) for col in df.columns}
        }


def create_pipeline_from_steps(
    step_configs: List[Dict[str, Any]],
    name: str = "unnamed",
    description: str = ""
) -> Pipeline:
    """从步骤配置创建Pipeline"""
    steps = []
    for i, config in enumerate(step_configs):
        step = PipelineStep(
            step_id=config.get("step_id", f"step_{i+1}"),
            skill_name=config.get("skill_name"),
            skill_id=config.get("skill_id"),
            parameters=config.get("parameters", {}),
            input_mapping=config.get("input_mapping", {}),
            output_name=config.get("output_name", "main")
        )
        steps.append(step)

    return Pipeline(
        name=name,
        description=description,
        steps=steps
    )