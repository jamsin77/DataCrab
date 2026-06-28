"""智能体相关 schemas"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class AgentRunRequest(BaseModel):
    agent_name: str
    message: str
    datasource_id: Optional[str] = None
    table_name: Optional[str] = None
    session_id: Optional[str] = None


class AgentInfo(BaseModel):
    name: str
    display_name: str
    description: str


class InspectRequest(BaseModel):
    datasource_id: str
    table_name: str
    check_dimensions: Optional[List[str]] = None


class AgentEventResponse(BaseModel):
    id: str
    trace_id: str
    agent_name: str
    event_type: str
    timestamp: str
    payload: Dict[str, Any]
