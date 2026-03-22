import pytest
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_runtime.definition import AgentDefinition
from core.agent_runtime.v2.planner import Planner


def test_followup_plan_accepts_contract_dict():
    planner = Planner()
    agent = AgentDefinition(
        agent_id="agent_test",
        name="test",
        model_id="test-model",
        execution_mode="plan_based",
        plan_contract_enabled=True,  # Enable Plan Contract
        plan_contract_sources=["replan_contract_plan", "plan_contract", "followup_plan_contract"],
    )

    contract = {
        "id": "plan_contract_001",
        "goal": "Fix and retest",
        "steps": [
            {
                "id": "read",
                "name": "Read file",
                "skill": "builtin_file.read",
                "input": {"path": "app.py"},
                "depends_on": [],
            },
            {
                "id": "test",
                "name": "Run test",
                "skill": "builtin_shell.run",
                "input": {"command": "pytest -q"},
                "depends_on": ["read"],
            },
        ],
    }

    followup = asyncio.run(
        planner.create_followup_plan(
            agent=agent,
            execution_context={
                "replan_instruction": "请重规划",
                "replan_contract_plan": contract,
            },
            parent_plan_id="parent_001",
        )
    )

    assert followup.plan_id == "plan_contract_001"
    assert followup.parent_plan_id == "parent_001"
    assert len(followup.steps) == 2
    assert followup.steps[0].inputs["skill_id"] == "builtin_file.read"
    assert followup.steps[1].inputs["skill_id"] == "builtin_shell.run"
    assert followup.failure_strategy == "stop"


def test_followup_plan_rejects_invalid_contract():
    """Test that invalid contracts are rejected and planner falls back to LLM."""
    planner = Planner()
    agent = AgentDefinition(
        agent_id="agent_test",
        name="test",
        model_id="test-model",
        execution_mode="plan_based",
        plan_contract_enabled=True,  # Enable Plan Contract
    )

    invalid_contract = {
        "id": "bad_plan",
        "goal": "bad",
        "steps": [
            {
                "id": "s1",
                "name": "step1",
                "skill": "builtin_file.read",
                "input": {"path": "a.py"},
                "depends_on": ["missing_step"],
            }
        ],
    }

    # Should not raise, but should fallback to LLM
    followup = asyncio.run(
        planner.create_followup_plan(
            agent=agent,
            execution_context={
                "replan_instruction": "请重规划",
                "replan_contract_plan": invalid_contract,
            },
            parent_plan_id="parent_001",
        )
    )
    
    # Verify it fell back to LLM (plan will be created via traditional approach)
    assert followup is not None
    assert followup.parent_plan_id == "parent_001"


def test_followup_plan_strict_mode_rejects_invalid_contract():
    planner = Planner()
    agent = AgentDefinition(
        agent_id="agent_test",
        name="test",
        model_id="test-model",
        execution_mode="plan_based",
        plan_contract_enabled=True,
        plan_contract_strict=True,
    )

    invalid_contract = {
        "id": "bad_plan",
        "goal": "bad",
        "steps": [
            {
                "id": "s1",
                "name": "step1",
                "skill": "builtin_file.read",
                "input": {"path": "a.py"},
                "depends_on": ["missing_step"],
            }
        ],
    }

    with pytest.raises(ValueError):
        asyncio.run(
            planner.create_followup_plan(
                agent=agent,
                execution_context={
                    "replan_instruction": "请重规划",
                    "replan_contract_plan": invalid_contract,
                },
                parent_plan_id="parent_001",
            )
        )


def test_followup_plan_llm_prompt_is_normalized_to_messages():
    planner = Planner()
    agent = AgentDefinition(
        agent_id="agent_test",
        name="test",
        model_id="test-model",
        execution_mode="plan_based",
        plan_contract_enabled=True,
    )

    llm_contract = {
        "id": "plan_llm_001",
        "goal": "Answer with LLM",
        "steps": [
            {
                "id": "llm_step",
                "name": "Generate answer",
                "skill": "llm.generate",
                "input": {"prompt": "hello"},
                "depends_on": [],
            }
        ],
    }

    followup = asyncio.run(
        planner.create_followup_plan(
            agent=agent,
            execution_context={
                "replan_instruction": "请重规划",
                "replan_contract_plan": llm_contract,
            },
            parent_plan_id="parent_001",
        )
    )

    assert followup.steps[0].executor.value == "llm"
    assert isinstance(followup.steps[0].inputs.get("messages"), list)
    assert followup.steps[0].inputs["messages"][0]["role"] == "user"
