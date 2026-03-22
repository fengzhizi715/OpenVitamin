from typing import Dict, Any

def create_input_schema(properties: Dict[str, Any], required: list = None) -> Dict[str, Any]:
    """Helper to create a standard JSON Schema for tool inputs."""
    return {
        "type": "object",
        "properties": properties,
        "required": required or []
    }
