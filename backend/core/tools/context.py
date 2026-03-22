from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class ToolContext(BaseModel):
    agent_id: Optional[str] = Field(None, description="The ID of the agent calling the tool")
    trace_id: Optional[str] = Field(None, description="The trace ID for observability")
    workspace: str = Field(".", description="The base directory for file operations")
    permissions: Dict[str, Any] = Field(default_factory=dict, description="Permission flags for the tool")
