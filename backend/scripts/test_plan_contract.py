"""
Unit tests for Plan Contract module.

These tests verify:
- Model structure and validation
- Plan validation logic
- Dependency checking
- Cycle detection
- JSON serialization

Run with: pytest backend/scripts/test_plan_contract.py -v
"""

import pytest
import sys
from pathlib import Path
from pydantic import ValidationError

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.plan_contract.models import Plan, PlanStep, PlanMetadata
from core.plan_contract.validator import validate_plan, PlanValidationError


class TestPlanStepModel:
    """Test PlanStep model."""
    
    def test_create_minimal_step(self):
        """Test creating a step with minimal required fields."""
        step = PlanStep(
            id="step1",
            name="Read file",
            skill="file.read"
        )
        
        assert step.id == "step1"
        assert step.name == "Read file"
        assert step.skill == "file.read"
        assert step.input == {}
        assert step.depends_on == []
        assert step.output_schema is None
    
    def test_create_step_with_dependencies(self):
        """Test creating a step with dependencies."""
        step = PlanStep(
            id="step2",
            name="Apply patch",
            skill="file.apply_patch",
            input={"path": "app.py", "patch": "__from_previous_step"},
            depends_on=["step1"]
        )
        
        assert step.depends_on == ["step1"]
        assert step.input["path"] == "app.py"
    
    def test_reject_empty_id(self):
        """Test that empty ID is rejected."""
        with pytest.raises(ValidationError):
            PlanStep(id="", name="Test", skill="test")
    
    def test_reject_empty_skill(self):
        """Test that empty skill is rejected."""
        with pytest.raises(ValidationError):
            PlanStep(id="step1", name="Test", skill="")
    
    def test_reject_id_with_spaces(self):
        """Test that ID with spaces is rejected."""
        with pytest.raises(ValidationError):
            PlanStep(id="step 1", name="Test", skill="test")


class TestPlanModel:
    """Test Plan model."""
    
    def test_create_minimal_plan(self):
        """Test creating a plan with minimal required fields."""
        plan = Plan(
            id="plan_001",
            goal="Fix failing test",
            steps=[
                PlanStep(id="step1", name="Read file", skill="file.read")
            ]
        )
        
        assert plan.id == "plan_001"
        assert plan.goal == "Fix failing test"
        assert len(plan.steps) == 1
    
    def test_create_plan_with_metadata(self):
        """Test creating a plan with metadata."""
        plan = Plan(
            id="plan_001",
            goal="Fix failing test",
            steps=[
                PlanStep(id="step1", name="Read file", skill="file.read")
            ],
            metadata=PlanMetadata(
                version="0.1",
                created_by="agent_001",
                tags=["fix", "test"]
            )
        )
        
        assert plan.metadata.version == "0.1"
        assert plan.metadata.created_by == "agent_001"
        assert plan.metadata.tags == ["fix", "test"]
    
    def test_reject_empty_steps(self):
        """Test that empty steps list is rejected."""
        with pytest.raises(ValidationError):
            Plan(id="plan_001", goal="Test", steps=[])
    
    def test_reject_empty_goal(self):
        """Test that empty goal is rejected."""
        with pytest.raises(ValidationError):
            Plan(id="plan_001", goal="", steps=[PlanStep(id="s1", name="Test", skill="test")])


class TestPlanValidation:
    """Test plan validation logic."""
    
    def test_validate_valid_plan(self):
        """Test validating a correct plan."""
        plan = Plan(
            id="plan_001",
            goal="Fix failing test",
            steps=[
                PlanStep(id="step1", name="Read file", skill="file.read"),
                PlanStep(id="step2", name="Generate patch", skill="llm.generate", 
                        depends_on=["step1"]),
                PlanStep(id="step3", name="Apply patch", skill="file.apply_patch",
                        depends_on=["step2"]),
            ]
        )
        
        # Should not raise
        validate_plan(plan)
    
    def test_reject_duplicate_step_ids(self):
        """Test that duplicate step IDs are rejected."""
        plan = Plan(
            id="plan_001",
            goal="Test",
            steps=[
                PlanStep(id="step1", name="Step 1", skill="test"),
                PlanStep(id="step1", name="Duplicate", skill="test"),  # Duplicate!
            ]
        )
        
        with pytest.raises(PlanValidationError) as exc_info:
            validate_plan(plan)
        
        assert "Duplicate step IDs" in exc_info.value.message
        assert "step1" in exc_info.value.details["duplicate_ids"]
    
    def test_reject_missing_dependency(self):
        """Test that missing dependency references are rejected."""
        plan = Plan(
            id="plan_001",
            goal="Test",
            steps=[
                PlanStep(id="step1", name="Step 1", skill="test"),
                PlanStep(id="step2", name="Step 2", skill="test", 
                        depends_on=["nonexistent"]),  # Missing!
            ]
        )
        
        with pytest.raises(PlanValidationError) as exc_info:
            validate_plan(plan)
        
        assert "non-existent steps" in exc_info.value.message
        assert "nonexistent" in exc_info.value.details["missing_dependencies"]
    
    def test_reject_self_dependency(self):
        """Test that self-dependency is rejected."""
        plan = Plan(
            id="plan_001",
            goal="Test",
            steps=[
                PlanStep(id="step1", name="Step 1", skill="test", 
                        depends_on=["step1"]),  # Self-reference!
            ]
        )
        
        with pytest.raises(PlanValidationError) as exc_info:
            validate_plan(plan)
        
        # Self-dependency is detected as a cycle
        assert "Circular dependency" in exc_info.value.message or "cannot depend on itself" in exc_info.value.message
    
    def test_reject_circular_dependency(self):
        """Test that circular dependencies are rejected."""
        plan = Plan(
            id="plan_001",
            goal="Test",
            steps=[
                PlanStep(id="step1", name="Step 1", skill="test", 
                        depends_on=["step3"]),
                PlanStep(id="step2", name="Step 2", skill="test",
                        depends_on=["step1"]),
                PlanStep(id="step3", name="Step 3", skill="test",
                        depends_on=["step2"]),  # Creates cycle: 1->3->2->1
            ]
        )
        
        with pytest.raises(PlanValidationError) as exc_info:
            validate_plan(plan)
        
        assert "Circular dependency" in exc_info.value.message
    
    def test_accept_complex_dag(self):
        """Test accepting a complex DAG structure."""
        plan = Plan(
            id="plan_001",
            goal="Complex workflow",
            steps=[
                PlanStep(id="root1", name="Root 1", skill="test"),
                PlanStep(id="root2", name="Root 2", skill="test"),
                PlanStep(id="mid1", name="Middle 1", skill="test",
                        depends_on=["root1", "root2"]),
                PlanStep(id="mid2", name="Middle 2", skill="test",
                        depends_on=["root1"]),
                PlanStep(id="leaf", name="Leaf", skill="test",
                        depends_on=["mid1", "mid2"]),
            ]
        )
        
        # Should not raise - valid DAG
        validate_plan(plan)


class TestSerialization:
    """Test JSON serialization."""
    
    def test_to_dict(self):
        """Test converting plan to dictionary."""
        plan = Plan(
            id="plan_001",
            goal="Test",
            steps=[
                PlanStep(id="step1", name="Step 1", skill="test",
                        input={"key": "value"})
            ],
            metadata=PlanMetadata(version="0.1")
        )
        
        data = plan.to_dict()
        
        assert isinstance(data, dict)
        assert data["id"] == "plan_001"
        assert data["goal"] == "Test"
        assert len(data["steps"]) == 1
        assert data["metadata"]["version"] == "0.1"
    
    def test_from_dict(self):
        """Test creating plan from dictionary."""
        data = {
            "id": "plan_001",
            "goal": "Test goal",
            "steps": [
                {
                    "id": "step1",
                    "name": "Test step",
                    "skill": "file.read",
                    "input": {"path": "test.py"},
                    "depends_on": []
                }
            ],
            "metadata": {
                "version": "0.1",
                "created_by": "test_agent"
            }
        }
        
        plan = Plan.from_dict(data)
        
        assert plan.id == "plan_001"
        assert plan.goal == "Test goal"
        assert len(plan.steps) == 1
        assert plan.steps[0].skill == "file.read"
    
    def test_round_trip_serialization(self):
        """Test round-trip serialization (dict -> Plan -> dict)."""
        original_data = {
            "id": "plan_001",
            "goal": "Round trip test",
            "steps": [
                PlanStep(
                    id="step1",
                    name="Step 1",
                    skill="test",
                    depends_on=[]
                ).model_dump()
            ]
        }
        
        # Dict -> Plan
        plan = Plan.from_dict(original_data)
        
        # Plan -> Dict
        result_data = plan.to_dict()
        
        # Verify key fields match
        assert result_data["id"] == original_data["id"]
        assert result_data["goal"] == original_data["goal"]
        assert len(result_data["steps"]) == len(original_data["steps"])


class TestStructureAnalysis:
    """Test plan structure analysis."""
    
    def test_analyze_linear_chain(self):
        """Test analyzing a linear dependency chain."""
        from core.plan_contract.validator import validate_plan_structure
        
        plan = Plan(
            id="plan_001",
            goal="Linear chain",
            steps=[
                PlanStep(id="step1", name="1", skill="test"),
                PlanStep(id="step2", name="2", skill="test", depends_on=["step1"]),
                PlanStep(id="step3", name="3", skill="test", depends_on=["step2"]),
            ]
        )
        
        stats = validate_plan_structure(plan)
        
        assert stats["total_steps"] == 3
        assert stats["root_steps"] == ["step1"]
        assert stats["leaf_steps"] == ["step3"]
        assert stats["max_depth"] == 3
    
    def test_analyze_parallel_roots(self):
        """Test analyzing parallel root steps."""
        from core.plan_contract.validator import validate_plan_structure
        
        plan = Plan(
            id="plan_001",
            goal="Parallel roots",
            steps=[
                PlanStep(id="root1", name="R1", skill="test"),
                PlanStep(id="root2", name="R2", skill="test"),
                PlanStep(id="leaf", name="L", skill="test", 
                        depends_on=["root1", "root2"]),
            ]
        )
        
        stats = validate_plan_structure(plan)
        
        assert stats["total_steps"] == 3
        assert set(stats["root_steps"]) == {"root1", "root2"}
        assert stats["leaf_steps"] == ["leaf"]
        assert stats["max_depth"] == 2
