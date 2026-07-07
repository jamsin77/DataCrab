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
        handoff_count = 0
        current_agent = self.registry.get(agent_name)
        current_message = message
        # 收敛检测：委托给非侵入式 ConvergenceGuard（G）
        guard = ConvergenceGuard(threshold=4)

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
