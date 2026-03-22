from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from .context import ToolContext
from .result import ToolResult

class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the tool, used by the LLM to call it."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """A description of what the tool does."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        """JSON Schema for the tool's input."""
        pass

    @property
    def output_schema(self) -> Dict[str, Any]:
        """JSON Schema for the tool's output (optional)."""
        return {}

    @property
    def required_permissions(self) -> List[str]:
        """
        Permission keys required to run this tool (optional).

        Convention: use dotted keys, e.g. "file.read", "file.list", "python.run".
        """
        return []

    @property
    def ui_hint(self) -> Dict[str, Any]:
        """
        Optional UI metadata for rendering tools in the Web UI.

        Keys (all optional):
        - display_name: human-friendly name
        - icon: an icon identifier string (frontend maps to an icon component)
        - category: grouping/category string (e.g. "web", "python", "file", "sql")
        - permissions_hint: list of permission hint objects/strings

        This is intentionally explicit and deterministic (no hidden inference).
        """
        # Default: derive a minimal hint from the tool name.
        category: Optional[str] = None
        if "." in self.name:
            category = self.name.split(".", 1)[0]

        permissions_hint = [{"key": p} for p in (self.required_permissions or [])]

        return {
            "display_name": self.name,
            "icon": None,
            "category": category,
            "permissions_hint": permissions_hint,
        }

    @abstractmethod
    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute the tool."""
        pass
