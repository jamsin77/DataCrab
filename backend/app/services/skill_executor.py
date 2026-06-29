"""技能执行器系统 - 支持多种执行器类型"""

from __future__ import annotations

import asyncio
import importlib
from typing import Dict, Any, Callable, Optional, List
from dataclasses import dataclass, field
from loguru import logger
from app.services.operators import get_operator, BaseOperator


@dataclass
class ExecutionContext:
    """执行上下文"""
    session_id: str = ""
    user_id: str = ""
    variables: Dict[str, Any] = field(default_factory=dict)
    data_frames: Dict[str, pd.DataFrame] = field(default_factory=dict)

    def get_data(self, name: str = "main") -> Optional[pd.DataFrame]:
        """获取数据"""
        return self.data_frames.get(name)

    def set_data(self, df: pd.DataFrame, name: str = "main"):
        """设置数据"""
        self.data_frames[name] = df

    def get_variable(self, name: str) -> Any:
        """获取变量"""
        return self.variables.get(name)

    def set_variable(self, name: str, value: Any):
        """设置变量"""
        self.variables[name] = value


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    output: Optional[pd.DataFrame] = None
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


class SkillExecutor:
    """技能执行器 - 支持多种执行器类型"""

    def __init__(self, context: ExecutionContext = None):
        self.context = context or ExecutionContext()

    def get_executor(self, executor_config: Dict[str, Any]) -> Callable:
        """根据配置获取执行器"""
        executor_type = executor_config.get("type")

        if executor_type == "python_function":
            return self._get_python_executor(executor_config)
        elif executor_type == "lambda":
            return self._get_lambda_executor(executor_config)
        elif executor_type == "operator_reference":
            return self._get_operator_executor(executor_config)
        elif executor_type == "skill_composition":
            return self._get_composition_executor(executor_config)
        else:
            raise ValueError(f"不支持的执行器类型: {executor_type}")

    def _get_python_executor(self, config: Dict[str, Any]) -> Callable:
        """获取Python函数执行器"""
        module_path = config.get("module")
        function_name = config.get("function")

        if not module_path or not function_name:
            raise ValueError("Python函数执行器需要指定module和function")

        try:
            module = importlib.import_module(module_path)
            func = getattr(module, function_name)
            logger.debug(f"加载Python函数: {module_path}.{function_name}")
            return func
        except Exception as e:
            raise ValueError(f"无法加载Python函数 {module_path}.{function_name}: {e}")

    def _get_lambda_executor(self, config: Dict[str, Any]) -> Callable:
        """获取Lambda执行器"""
        code = config.get("code")
        if not code:
            raise ValueError("Lambda执行器需要指定code")

        try:
            import pandas as pd
            # 安全执行：只允许pandas操作
            allowed_globals = {"pd": pd, "df": None}
            func = eval(code, {"__builtins__": {}}, allowed_globals)
            return func
        except Exception as e:
            raise ValueError(f"Lambda代码解析失败: {e}")

    def _get_operator_executor(self, config: Dict[str, Any]) -> Callable:
        """获取算子引用执行器"""
        operator_name = config.get("operator_name")
        operator_id = config.get("operator_id")

        # 优先使用名称查找
        if operator_name:
            operator = get_operator(operator_name)
            return operator.execute
        elif operator_id:
            # TODO: 从数据库加载算子
            raise ValueError("暂不支持通过ID查找算子")
        else:
            raise ValueError("算子引用执行器需要指定operator_name或operator_id")

    def _get_composition_executor(self, config: Dict[str, Any]) -> Callable:
        """获取组合执行器"""
        skills = config.get("skills", [])
        if not skills:
            raise ValueError("组合执行器需要指定skills列表")

        async def composition_func(inputs: Dict[str, pd.DataFrame],
                                   parameters: Dict[str, Any] = None,
                                   context: ExecutionContext = None) -> Dict[str, pd.DataFrame]:
            """组合执行函数"""
            result = inputs
            for i, skill_config in enumerate(skills):
                skill_id = skill_config.get("skill_id")
                skill_params = skill_config.get("parameters", {})

                # 合并传入参数
                merged_params = {**parameters, **skill_params} if parameters else skill_params

                logger.info(f"执行组合技能步骤 {i+1}/{len(skills)}: {skill_id}")

                # 递归执行每个子技能
                # TODO: 这里需要从技能库获取技能配置
                # 暂时跳过，由PipelineExecutor处理
                pass

            return result

        return composition_func

    async def execute(
        self,
        executor_config: Dict[str, Any],
        inputs: Dict[str, pd.DataFrame],
        parameters: Dict[str, Any] = None
    ) -> ExecutionResult:
        """执行技能"""
        import time
        import pandas as pd
        start_time = time.time()

        try:
            executor = self.get_executor(executor_config)
            params = parameters or {}

            # 执行 - 支持同步和异步函数
            if asyncio.iscoroutinefunction(executor):
                output = await executor(inputs=inputs, parameters=params, context=self.context)
            elif callable(executor):
                # 同步函数调用
                output = executor(inputs=inputs, parameters=params, context=self.context)
            else:
                raise ValueError(f"执行器不可调用: {type(executor)}")

            # 处理输出
            if isinstance(output, dict):
                result_df = output.get("main", output.get("result"))
            elif isinstance(output, pd.DataFrame):
                result_df = output
            else:
                result_df = pd.DataFrame({"result": [output]})

            execution_time = time.time() - start_time

            return ExecutionResult(
                success=True,
                output=result_df,
                logs=[f"执行完成，耗时 {execution_time:.3f}s"],
                metrics={"execution_time": execution_time}
            )

        except Exception as e:
            logger.error(f"技能执行失败: {e}")
            return ExecutionResult(
                success=False,
                error=str(e),
                logs=[f"执行失败: {e}"]
            )


# 内置技能执行函数

def select_columns(
    inputs: Dict[str, pd.DataFrame],
    parameters: Dict[str, Any],
    context: ExecutionContext = None
) -> Dict[str, pd.DataFrame]:
    """选择列"""
    df = inputs.get("main")
    columns = parameters.get("columns", [])

    if not columns:
        raise ValueError("请指定要选择的列")

    return {"main": df[columns]}


def filter_data(
    inputs: Dict[str, pd.DataFrame],
    parameters: Dict[str, Any],
    context: ExecutionContext = None
) -> Dict[str, pd.DataFrame]:
    """过滤数据"""
    df = inputs.get("main")
    condition = parameters.get("condition", "")

    if not condition:
        raise ValueError("请指定过滤条件")

    return {"main": df.query(condition)}


def groupby_aggregate(
    inputs: Dict[str, pd.DataFrame],
    parameters: Dict[str, Any],
    context: ExecutionContext = None
) -> Dict[str, pd.DataFrame]:
    """分组聚合"""
    df = inputs.get("main")
    group_column = parameters.get("group_column")
    agg_column = parameters.get("agg_column")
    agg_func = parameters.get("agg_func", "sum")

    if not group_column or not agg_column:
        raise ValueError("请指定分组列和聚合列")

    result = df.groupby(group_column)[agg_column].agg(agg_func).reset_index()
    result.columns = [group_column, agg_column]

    return {"main": result}


def sort_data(
    inputs: Dict[str, pd.DataFrame],
    parameters: Dict[str, Any],
    context: ExecutionContext = None
) -> Dict[str, pd.DataFrame]:
    """排序数据"""
    df = inputs.get("main")
    column = parameters.get("column")
    ascending = parameters.get("ascending", True)

    if not column:
        raise ValueError("请指定排序列")

    return {"main": df.sort_values(column, ascending=ascending)}


def drop_na_rows(
    inputs: Dict[str, pd.DataFrame],
    parameters: Dict[str, Any],
    context: ExecutionContext = None
) -> Dict[str, pd.DataFrame]:
    """删除空值行"""
    df = inputs.get("main")
    columns = parameters.get("columns")

    return {"main": df.dropna(subset=columns)}


def fill_na_values(
    inputs: Dict[str, pd.DataFrame],
    parameters: Dict[str, Any],
    context: ExecutionContext = None
) -> Dict[str, pd.DataFrame]:
    """填充空值"""
    df = inputs.get("main")
    value = parameters.get("value")
    method = parameters.get("method")

    if method == "ffill":
        return {"main": df.ffill()}
    elif method == "bfill":
        return {"main": df.bfill()}
    elif method == "mean":
        return {"main": df.fillna(df.mean())}
    elif method == "median":
        return {"main": df.fillna(df.median())}
    else:
        return {"main": df.fillna(value)}


# 技能注册表：技能名 -> 执行配置
BUILTIN_SKILL_EXECUTORS: Dict[str, Dict[str, Any]] = {
    "select": {
        "type": "python_function",
        "module": "app.services.skill_executor",
        "function": "select_columns"
    },
    "filter": {
        "type": "python_function",
        "module": "app.services.skill_executor",
        "function": "filter_data"
    },
    "groupby": {
        "type": "python_function",
        "module": "app.services.skill_executor",
        "function": "groupby_aggregate"
    },
    "sort": {
        "type": "python_function",
        "module": "app.services.skill_executor",
        "function": "sort_data"
    },
    "dropna": {
        "type": "python_function",
        "module": "app.services.skill_executor",
        "function": "drop_na_rows"
    },
    "fillna": {
        "type": "python_function",
        "module": "app.services.skill_executor",
        "function": "fill_na_values"
    },
}


def get_skill_executor_config(skill_name: str) -> Optional[Dict[str, Any]]:
    """获取技能执行配置"""
    return BUILTIN_SKILL_EXECUTORS.get(skill_name)