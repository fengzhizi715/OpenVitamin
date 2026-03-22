from typing import Any, Optional
from pydantic import BaseModel

class ToolResult(BaseModel):
    success: bool
    data: Any
    error: Optional[str] = None
