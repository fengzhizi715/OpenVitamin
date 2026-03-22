#!/usr/bin/env python3
"""
Test Plan Contract with agent_9c92ac79.

This script tests if the agent can accept and process Plan Contract payloads.
"""
import sys
import os
import asyncio

# Allow importing from backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent_runtime.definition import get_agent_registry
from core.agent_runtime.v2.planner import Planner


async def test_plan_contract():
    """Test Plan Contract integration with agent_9c92ac79."""
    registry = get_agent_registry()
    agent = registry.get_agent("agent_9c92ac79")
    
    if not agent:
        print("❌ Agent agent_9c92ac79 not found")
        return False
    
    print(f"\n{'='*70}")
    print(f"Testing Plan Contract with Agent: {agent.name}")
    print(f"{'='*70}\n")
    
    # Check configuration
    print(f"✅ Configuration:")
    print(f"   execution_mode: {agent.execution_mode}")
    print(f"   plan_contract_enabled: {agent.plan_contract_enabled}")
    print(f"   plan_contract_sources: {agent.plan_contract_sources}")
    print()
    
    if not agent.plan_contract_enabled:
        print("❌ Plan Contract is NOT enabled!")
        return False
    
    # Create a test Plan Contract
    test_contract = {
        "id": "test_plan_001",
        "goal": "Test Plan Contract integration",
        "steps": [
            {
                "id": "step1",
                "name": "Read a file",
                "skill": "builtin_file.read",
                "input": {"path": "README.md"},
                "depends_on": []
            },
            {
                "id": "step2",
                "name": "Analyze project",
                "skill": "builtin_project.analyze",
                "input": {"detail_level": "brief"},
                "depends_on": ["step1"]
            }
        ]
    }
    
    print(f"📋 Test Plan Contract:")
    print(f"   ID: {test_contract['id']}")
    print(f"   Goal: {test_contract['goal']}")
    print(f"   Steps: {len(test_contract['steps'])}")
    print()
    
    # Test parsing
    planner = Planner()
    
    try:
        print(f"🔍 Testing Plan Contract parsing...")
        runtime_plan = await planner.create_followup_plan(
            agent=agent,
            execution_context={
                "replan_instruction": "Execute this plan",
                "replan_contract_plan": test_contract
            },
            parent_plan_id="parent_test"
        )
        
        print(f"\n✅ SUCCESS! Plan Contract parsed and converted to runtime plan:")
        print(f"   Runtime Plan ID: {runtime_plan.plan_id}")
        print(f"   Parent Plan ID: {runtime_plan.parent_plan_id}")
        print(f"   Goal: {runtime_plan.goal}")
        print(f"   Steps count: {len(runtime_plan.steps)}")
        print(f"   Failure strategy: {runtime_plan.failure_strategy}")
        
        print(f"\n📝 Step details:")
        for i, step in enumerate(runtime_plan.steps, 1):
            skill_id = step.inputs.get('skill_id', 'N/A')
            print(f"   Step {i}: {step.step_id} -> {skill_id}")
        
        print(f"\n{'='*70}")
        print(f"✅ Plan Contract integration test PASSED!")
        print(f"{'='*70}\n")
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED! Error: {type(e).__name__}: {e}")
        print(f"\n{'='*70}")
        print(f"❌ Plan Contract integration test FAILED!")
        print(f"{'='*70}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_plan_contract())
    sys.exit(0 if success else 1)
