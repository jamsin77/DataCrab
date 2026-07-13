"""技能执行器数据结构 - 执行上下文与结果"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field


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
