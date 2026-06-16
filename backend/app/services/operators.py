"""算子基类和内置算子"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import pandas as pd


class BaseOperator(ABC):
    """算子基类"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def category(self) -> str:
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def execute(
        self,
        inputs: Dict[str, pd.DataFrame],
        params: Dict[str, Any],
    ) -> Dict[str, pd.DataFrame]:
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """验证参数"""
        for param_name, param_def in self.parameters.items():
            if param_def.get("required", False) and param_name not in params:
                raise ValueError(f"缺少必需参数: {param_name}")
        return True


# ===== 数据转换算子 =====

class SelectOperator(BaseOperator):
    """列选择算子"""
    name = "select"
    description = "选择指定列"
    category = "transform"
    parameters = {"columns": {"type": "list", "required": True, "description": "要选择的列名列表"}}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        columns = params.get("columns", [])
        return {"main": df[columns]}


class FilterOperator(BaseOperator):
    """数据过滤算子"""
    name = "filter"
    description = "按条件过滤数据"
    category = "transform"
    parameters = {"condition": {"type": "str", "required": True, "description": "过滤条件表达式"}}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        condition = params.get("condition", "")
        return {"main": df.query(condition)}


class RenameOperator(BaseOperator):
    """列重命名算子"""
    name = "rename"
    description = "重命名列"
    category = "transform"
    parameters = {"mapping": {"type": "dict", "required": True, "description": "旧名到新名的映射"}}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        mapping = params.get("mapping", {})
        return {"main": df.rename(columns=mapping)}


# ===== 数据聚合算子 =====

class GroupByOperator(BaseOperator):
    """分组聚合算子"""
    name = "groupby"
    description = "按列分组并聚合"
    category = "aggregate"
    parameters = {
        "by": {"type": "list", "required": True, "description": "分组列"},
        "agg": {"type": "dict", "required": True, "description": "聚合函数映射"},
    }

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        by = params.get("by", [])
        agg = params.get("agg", {})
        return {"main": df.groupby(by).agg(agg).reset_index()}


class AggregateOperator(BaseOperator):
    """聚合计算算子"""
    name = "aggregate"
    description = "计算聚合统计值"
    category = "aggregate"
    parameters = {"functions": {"type": "dict", "required": True, "description": "列到聚合函数的映射"}}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        functions = params.get("functions", {})
        result = {}
        for col, func in functions.items():
            result[col] = getattr(df[col], func)()
        return {"main": pd.DataFrame([result])}


# ===== 数据连接算子 =====

class JoinOperator(BaseOperator):
    """表连接算子"""
    name = "join"
    description = "连接两个表"
    category = "join"
    parameters = {
        "on": {"type": "list", "required": True, "description": "连接键"},
        "how": {"type": "str", "required": False, "description": "连接方式", "default": "inner"},
    }

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        left = inputs.get("left")
        right = inputs.get("right")
        on = params.get("on", [])
        how = params.get("how", "inner")
        return {"main": pd.merge(left, right, on=on, how=how)}


# ===== 数据清洗算子 =====

class DropNAOperator(BaseOperator):
    """删除空值算子"""
    name = "dropna"
    description = "删除包含空值的行"
    category = "clean"
    parameters = {"subset": {"type": "list", "required": False, "description": "检查的列"}}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        subset = params.get("subset", None)
        return {"main": df.dropna(subset=subset)}


class FillNAOperator(BaseOperator):
    """填充空值算子"""
    name = "fillna"
    description = "填充空值"
    category = "clean"
    parameters = {"value": {"type": "any", "required": True, "description": "填充值或列到值的映射"}}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        value = params.get("value", {})
        return {"main": df.fillna(value)}


class DuplicateOperator(BaseOperator):
    """去重算子"""
    name = "duplicate"
    description = "删除重复行"
    category = "clean"
    parameters = {"subset": {"type": "list", "required": False, "description": "检查重复的列"}}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        subset = params.get("subset", None)
        return {"main": df.drop_duplicates(subset=subset)}


# ===== 数据分析算子 =====

class StatisticsOperator(BaseOperator):
    """统计分析算子"""
    name = "statistics"
    description = "计算统计信息"
    category = "analysis"
    parameters = {}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        return {"main": df.describe()}


class CorrelationOperator(BaseOperator):
    """相关性分析算子"""
    name = "correlation"
    description = "计算列间相关性"
    category = "analysis"
    parameters = {}

    def execute(self, inputs: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df = inputs.get("main")
        return {"main": df.corr()}


# 算子注册表
OPERATOR_REGISTRY: Dict[str, BaseOperator] = {
    "select": SelectOperator(),
    "filter": FilterOperator(),
    "rename": RenameOperator(),
    "groupby": GroupByOperator(),
    "aggregate": AggregateOperator(),
    "join": JoinOperator(),
    "dropna": DropNAOperator(),
    "fillna": FillNAOperator(),
    "duplicate": DuplicateOperator(),
    "statistics": StatisticsOperator(),
    "correlation": CorrelationOperator(),
}


def get_operator(name: str) -> BaseOperator:
    """获取算子实例"""
    operator = OPERATOR_REGISTRY.get(name)
    if not operator:
        raise ValueError(f"未知的算子: {name}")
    return operator
