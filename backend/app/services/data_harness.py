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
        # 质量检查：行数波动过大 → 不记 positive（防止假阳性污染经验库）
        # 同一脚本同一份输入，产出行数应稳定；波动 >3x 说明数据质量不可靠
        _should_skip_positive = False
        _result_str = str(exec_result.get("result", ""))[:500]
        _row_count = _extract_row_count(_result_str)
        if _row_count is not None:
            try:
                _prev_positives = experience.read_positive(base)
                if _prev_positives:
                    _prev_counts = [
                        _extract_row_count(p.get("result_summary", ""))
                        for p in _prev_positives[-5:]
                    ]
                    _prev_valid = [c for c in _prev_counts if c is not None]
                    if _prev_valid:
                        _median = sorted(_prev_valid)[len(_prev_valid) // 2]
                        if _median > 0 and _row_count > _median * 3:
                            logger.info(
                                f"[experience] 行数波动过大：本次 {_row_count} vs 历史 {_median}，跳过记 positive"
                            )
                            _should_skip_positive = True
            except Exception as _qe:
                logger.warning(f"经验质量检查失败(非致命): {_qe}")

        if not _should_skip_positive:
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


def _extract_row_count(result_str: str) -> int | None:
    """从 result_summary 字符串中提取 total_rules_written / row_count / migrated_rows 等行数指标。"""
    import re
    if not result_str:
        return None
    # 匹配 total_rules_written: 91 / row_count: 91 / migrated_rows: 91 等
    m = re.search(r'(?:total_rules_written|row_count|migrated_rows|total_rows)["\']?\s*[:=]\s*(\d+)', result_str)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            pass
    return None
