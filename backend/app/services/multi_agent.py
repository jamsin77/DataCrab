"""多智能体协作框架 - BaseAgent + AgentRegistry + AgentRuntime + Handoff"""

import uuid
from abc import ABC, abstractmethod
from typing import Dict, Any, List, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger

from app.services.data_harness import ConvergenceGuard


class HandoffReason(str, Enum):
    INSPECT_RESULT = "inspect_result"
    FIX_REQUIRED = "fix_required"
    FIX_COMPLETED = "fix_completed"
    ESCALATE = "escalate"
    DELEGATE = "delegate"


@dataclass
class AgentMessage:
    from_agent: str
    to_agent: str
    reason: HandoffReason
    payload: Dict[str, Any]
    context: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    parent_trace_id: str = ""


@dataclass
class InspectionResult:
    passed: bool
    issues: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    severity: str = "info"


@dataclass
class AgentEvent:
    id: str
    trace_id: str
    parent_trace_id: str
    agent_name: str
    event_type: str
    timestamp: datetime
    payload: Dict[str, Any]


class EventStore:
    def __init__(self):
        self._events: List[AgentEvent] = []

    def record(self, event: AgentEvent):
        self._events.append(event)

    def record_handoff(self, from_agent: str, to_agent: str, reason: str, trace_id: str):
        self.record(AgentEvent(
            id=str(uuid.uuid4()),
            trace_id=trace_id,
            parent_trace_id="",
            agent_name=from_agent,
            event_type="handoff",
            timestamp=datetime.now(),
            payload={"to_agent": to_agent, "reason": reason},
        ))

    def record_tool_call(self, agent_name: str, tool_name: str, arguments: Dict, result: str, trace_id: str):
        self.record(AgentEvent(
            id=str(uuid.uuid4()),
            trace_id=trace_id,
            parent_trace_id="",
            agent_name=agent_name,
            event_type="tool_call",
            timestamp=datetime.now(),
            payload={"tool_name": tool_name, "arguments": arguments, "result_preview": result[:500]},
        ))

    def get_trace(self, trace_id: str) -> List[AgentEvent]:
        return [e for e in self._events if e.trace_id == trace_id]

    def get_lineage(self, datasource_id: str, table_name: str) -> List[AgentEvent]:
        return [
            e for e in self._events
            if e.event_type == "tool_call"
            and e.payload.get("arguments", {}).get("datasource_id") == datasource_id
            and e.payload.get("arguments", {}).get("table_name") == table_name
        ]


class BaseAgent(ABC):
    name: str
    display_name: str
    description: str
    instructions: str
    tools: List[Dict]
    capabilities: List[str] = []

    @abstractmethod
    async def run(
        self,
        message: AgentMessage,
        context: Dict[str, Any],
    ) -> AsyncGenerator[Dict, None]:
        pass

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        return self.instructions


class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):
        self._agents[agent.name] = agent
        logger.info(f"智能体注册: {agent.name} ({agent.display_name})")

    def get(self, name: str) -> BaseAgent:
        return self._agents.get(name)

    def list_agents(self) -> List[Dict]:
        return [
            {"name": a.name, "display_name": a.display_name, "description": a.description}
            for a in self._agents.values()
        ]

    def find_by_capability(self, capability: str) -> List[BaseAgent]:
        return [a for a in self._agents.values() if capability in getattr(a, 'capabilities', [])]


class AgentRuntime:
    def __init__(self, registry: AgentRegistry, llm_manager):
        self.registry = registry
        self.llm_manager = llm_manager
        self._event_store = EventStore()

    @property
    def event_store(self) -> EventStore:
        return self._event_store

    async def run(
        self,
        agent_name: str,
        message: AgentMessage,
        context: Dict[str, Any],
        max_handoffs: int = 10,
    ) -> AsyncGenerator[Dict, None]:
        # 从 context 获取最大检查轮次，动态调整 handoff 上限和收敛阈值
        # 一轮检查-修复循环需要 2 次 handoff（Processor→Inspector + Inspector→Processor）
        _max_inspections = context.get("debug_max_inspections", 7)
        max_handoffs = max(max_handoffs, _max_inspections * 2 + 2)
        handoff_count = 0
        current_agent = self.registry.get(agent_name)
        current_message = message
        # 收敛检测：阈值 = max_inspections * 2 + 3（允许完整 7 轮循环 + 余量，
        # 确保由 _inspection_round 检查终止而非 ConvergenceGuard 提前截断）
        guard = ConvergenceGuard(threshold=_max_inspections * 2 + 3)

        while current_agent and handoff_count < max_handoffs:
            async for event in current_agent.run(current_message, context):
                if event.get("type") == "handoff":
                    self._event_store.record_handoff(
                        from_agent=current_agent.name,
                        to_agent=event["to"],
                        reason=event["reason"],
                        trace_id=current_message.trace_id,
                    )

                    # 收敛检测：记录签名 + 判断是否发散（G）
                    payload = event.get("payload", {})
                    guard.record(
                        event["to"],
                        payload.get("datasource_id", ""),
                        payload.get("table_name", ""),
                    )

                    if guard.is_diverged():
                        yield {"type": "content", "content": "自动修复未能收敛，同一问题反复出现，请人工介入检查。"}
                        yield {"type": "done", "result": {"agent": "runtime", "content": "收敛失败"}}
                        return

                    target_name = event["to"]
                    current_agent = self.registry.get(target_name)
                    current_message = AgentMessage(
                        from_agent=event.get("from", current_agent.name),
                        to_agent=target_name,
                        reason=HandoffReason(event["reason"]),
                        payload=event.get("payload", {}),
                        context=context,
                        trace_id=current_message.trace_id,
                        parent_trace_id=current_message.trace_id,
                    )
                    handoff_count += 1
                    yield {"type": "agent_switch", "agent": target_name, "reason": event["reason"]}
                    break
                else:
                    yield event
            else:
                break


agent_registry = AgentRegistry()


def ensure_agent_runtime() -> "AgentRuntime":
    """幂等注册 DataProcessor + DataInspector，返回 AgentRuntime。

    消除 7 处重复的 agent 注册样板代码。
    """
    from app.services.llm import llm_manager
    from app.services.data_processor_agent import DataProcessorAgent
    from app.services.data_inspector_agent import DataInspectorAgent

    if not agent_registry.get("data_processor"):
        agent_registry.register(DataProcessorAgent())
    if not agent_registry.get("data_inspector"):
        agent_registry.register(DataInspectorAgent())
    return AgentRuntime(agent_registry, llm_manager)


def build_debug_context(
    db,
    user_id,
    target_type: str,
    history: list,
    script_name: str,
    script_content: str,
    function_name: str,
    lessons: str,
    user_context: dict = None,
    last_success_params=None,
    max_rounds: int = 7,
    max_inspections: int = 7,
    **extras,
) -> Dict[str, Any]:
    """构建调试 context 核心字段 + 类型特定字段（skill/operator/pipeline 共享）。

    extras 中的键直接合并到 context（如 debug_pipeline_id, debug_skill_md 等）。
    """
    context = {
        "debug_mode": True,
        "debug_type": target_type,
        "db": db,
        "user_id": user_id,
        "history": history or [],
        "debug_script_name": script_name,
        "debug_script_content": script_content,
        "debug_function_name": function_name,
        "debug_last_success_params": last_success_params,
        "debug_lessons": lessons,
        "debug_user_context": user_context or {},
        "debug_max_rounds": max_rounds,
        "debug_max_inspections": max_inspections,
    }
    context.update(extras)
    return context


def build_debug_message(user_message: str, context: Dict[str, Any]) -> "AgentMessage":
    """构建 DataProcessor 调试入口消息（所有调试/自修复路径共享）。"""
    return AgentMessage(
        from_agent="user",
        to_agent="data_processor",
        reason=HandoffReason.DELEGATE,
        payload={"user_message": user_message},
        context=context,
    )


async def stream_agent_events_sse(
    runtime: "AgentRuntime",
    message: "AgentMessage",
    context: Dict[str, Any],
    user_id=None,
) -> AsyncGenerator[str, None]:
    """SSE 流式推送 AgentRuntime 事件（3 个 debug-chat 端点共享）。

    处理：agent_switch → inspecting/retry 合成、inspector content 缓冲、
    warning_confirmation/fatal 捕获、SSE ping 保活（20s）。
    """
    import asyncio
    import json

    if user_id:
        from app.services.llm import init_user_llm_context
        await init_user_llm_context(user_id)

    runtime_gen = runtime.run("data_processor", message, context)

    _inspector_active = False
    _inspector_summary = ""
    _inspector_content_sent = False
    try:
        _task = asyncio.ensure_future(runtime_gen.__anext__())
        while True:
            done, _pending = await asyncio.wait({_task}, timeout=20.0)
            if _task not in done:
                yield f"data: {json.dumps({'type': 'ping'}, ensure_ascii=False)}\n\n"
                continue
            try:
                event = _task.result()
            except StopAsyncIteration:
                break
            _task = asyncio.ensure_future(runtime_gen.__anext__())

            t = event.get("type")
            if t == "agent_switch":
                agent = event.get("agent")
                _inspector_active = (agent == "data_inspector")
                if agent == "data_inspector":
                    evt = {"type": "inspecting", "message": "执行成功，DataInspector 正在检查数据质量..."}
                elif agent == "data_processor":
                    _retry_round = context.get("debug_inspection_round", 0) + 1
                    evt = {"type": "retry", "round": _retry_round, "message": f"DataInspector 发现问题，第 {_retry_round} 轮修复..."}
                else:
                    evt = None
                if evt:
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            elif t == "done":
                if _inspector_active and _inspector_summary and not _inspector_content_sent:
                    yield f"data: {json.dumps({'type': 'content', 'content': _inspector_summary}, ensure_ascii=False)}\n\n"
                _inspector_active = False
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            elif _inspector_active and t == "warning_confirmation":
                _inspector_summary = event.get("summary", "")
            elif _inspector_active and t == "content":
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                _inspector_content_sent = True
            elif _inspector_active and t == "fatal":
                _inspector_summary = event.get("summary", "") or "发现致命问题，已停止处理"
            elif _inspector_active and t == "tool_result":
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
    except asyncio.CancelledError:
        yield f"data: {json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error(f"Agent 事件流异常: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
