#!/usr/bin/env python3
"""Print agent definition JSON for a given agent_id (e.g. agent_9c92ac79)."""
import json
import sys
import os

# Allow importing from backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent_runtime.definition import get_agent_registry

def main():
    agent_id = sys.argv[1] if len(sys.argv) > 1 else "agent_9c92ac79"
    registry = get_agent_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        print(f"Agent not found: {agent_id}", file=sys.stderr)
        sys.exit(1)
    # Output as readable JSON (agent is AgentDefinition, model_dump for dict)
    d = agent.model_dump()
    print(json.dumps(d, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
