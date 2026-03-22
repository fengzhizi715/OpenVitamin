"""
Plan Contract Protocol - Structured task plan definitions and validation.

This module provides a protocol layer for defining structured task plans
with clear boundaries, data flow contracts, and step dependencies.

Architecture:
- Independent from Agent V2 implementation
- Pure contract/protocol layer (no execution logic)
- JSON serializable
- Ready for future Plan Engine integration
- Supports DAG-style step dependencies

Usage:
    from core.plan_contract.models import Plan, PlanStep
    from core.plan_contract.validator import validate_plan
    
    plan = Plan(
        id="plan_001",
        goal="Fix failing test",
        steps=[
            PlanStep(id="step1", name="Read file", skill="file.read", input={"path": "app.py"}),
            PlanStep(id="step2", name="Generate patch", skill="llm.generate", 
                    input={"task": "fix bug"}, depends_on=["step1"]),
            PlanStep(id="step3", name="Apply patch", skill="file.apply_patch",
                    input={"patch": "__from_previous_step"}, depends_on=["step2"]),
        ]
    )
    
    validate_plan(plan)  # Raises ValueError if invalid
"""

from .models import Plan, PlanStep, PlanMetadata
from .validator import validate_plan, PlanValidationError

__all__ = [
    "Plan",
    "PlanStep", 
    "PlanMetadata",
    "validate_plan",
    "PlanValidationError",
]
