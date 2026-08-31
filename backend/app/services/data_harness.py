"""数据 Harness — 非侵入式流程层组件

将原本散落在业务代码中的流程逻辑（收敛检测、经验采集）抽成独立组件，
业务代码只需调用一行，不再内联实现。

设计原则：
- 数据层 Harness（get_table_data / inspector_tools）保持侵入式——必须看到数据内容
- 流程层 Harness（收敛检测 / 经验采集）非侵入式——业务代码不感知 harness 细节
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple
from loguru import logger


class ConvergenceGuard:
    """Handoff 收敛检测器 — 非侵入式

    从 multi_agent.py 抽出。AgentRuntime 不再自己管签名追踪，
    只需在每次 handoff 时调用 record()，再检查 is_diverged()。

    判定规则：连续 threshold 次在同一张表上来回 handoff → 未收敛
    """

    def __init__(self, threshold: int = 4):
        self._threshold = threshold
        self._signatures: List[Tuple[str, str, str]] = []

    def record(self, to_agent: str, datasource_id: str = "", table_name: str = "") -> None:
        """记录一次 handoff 签名"""
        self._signatures.append((to_agent, str(datasource_id), str(table_name)))

    def is_diverged(self) -> bool:
        """是否已发散（连续 N 次同表来回）"""
        if len(self._signatures) < self._threshold:
            return False
        recent = self._signatures[-self._threshold:]
        tables = set((s[1], s[2]) for s in recent)
        return len(tables) == 1 and recent[0][0] != recent[-1][0]


def collect_experience(
    base: Path,
    source: str,
    exec_result: Dict[str, Any],
    parameters: Dict[str, Any] = None,
    script_name: str = "",
) -> None:
    """非侵入式经验采集 — 根据执行结果自动记录正反例

    替代 skill.py / operator.py 中重复的 15+ 行内联采集逻辑：
    - 执行失败 → 记录反例（错误类型 + 参数 + stdout）
    - 执行成功 且 有历史失败 → 记录正例（修错后成功的模式）

    Args:
        base: 经验库目录（技能文件夹或算子经验目录）
        source: 来源标记（run-stream / debug-chat / debug 等）
        exec_result: 执行结果 dict，需含 success / error / stdout / result
        parameters: 执行参数
        script_name: 脚本名
    """
    from app.services import experience

    params = parameters or {}
    success = exec_result.get("success", False)
    # 进程成功不代表脚本成功：检查脚本返回值中的 success 字段
    _inner = exec_result.get("result")
    if isinstance(_inner, dict) and _inner.get("success") is False:
        success = False
    # 兜底：检查 result_summary 字符串中是否含 success: False（防止 dict 被 stringify 后漏判）
    if success:
        _summary = str(exec_result.get("result", ""))
        if "'success': False" in _summary or '"success": false' in _summary.lower():
            success = False

    if not success:
        try:
            experience.append_negative(
                base,
                source=source,
                error_type="execution_error",
                error_message=exec_result.get("error", "未知错误"),
                parameters=params,
                stdout=exec_result.get("stdout", ""),
                script_name=script_name,
            )
        except Exception as e:
            logger.warning(f"采集反例失败: {e}")
    else:
        try:
            experience.append_positive(
                base,
                source=source,
                parameters=params,
                result_summary=str(exec_result.get("result", ""))[:200],
                script_name=script_name,
            )
        except Exception as e:
            logger.warning(f"采集正例失败: {e}")
