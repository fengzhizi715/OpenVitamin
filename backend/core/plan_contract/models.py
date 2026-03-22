"""
Plan Contract data models using Pydantic.

These models define the structure and contract for task plans without
any execution logic. They are:
- JSON serializable
- Type-safe via Pydantic validation
- Ready for DAG-style step dependencies
- Independent from Agent implementation
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Dict, Optional, Any


class PlanMetadata(BaseModel):
    """
    Optional metadata for a Plan.
    
    Attributes:
        version: Contract version (default: "0.1")
        created_by: Creator identifier (e.g., agent_id, planner_name)
        tags: Classification tags for categorization
        custom: Arbitrary key-value pairs for extensibility
    """
    version: str = Field(default="0.1", description="Contract version")
    created_by: Optional[str] = Field(default=None, description="Creator identifier")
    tags: List[str] = Field(default_factory=list, description="Classification tags")
    custom: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata")
    
    model_config = ConfigDict(extra="allow")  # Metadata is extensible by design


class PlanStep(BaseModel):
    """
    A single step in a task plan.
    
    Attributes:
        id: Unique identifier for this step within the plan
        name: Human-readable name/description
        skill: Skill identifier to execute (e.g., "file.read", "llm.generate")
        input: Input parameters for the skill
        depends_on: List of step IDs that must complete before this step
        output_schema: Expected output structure (optional, for validation)
        
    Example:
        PlanStep(
            id="read_file",
            name="Read source file",
            skill="file.read",
            input={"path": "app.py"},
            depends_on=[]
        )
        
        PlanStep(
            id="apply_patch",
            name="Apply fix patch",
            skill="file.apply_patch",
            input={
                "path": "app.py",
                "patch": "__from_previous_step:generate_patch"
            },
            depends_on=["read_file", "generate_patch"]
        )
    """
    id: str = Field(..., description="Unique step identifier")
    name: str = Field(..., description="Human-readable step name")
    skill: str = Field(..., description="Skill identifier to execute")
    input: Dict[str, Any] = Field(default_factory=dict, description="Input parameters")
    depends_on: List[str] = Field(
        default_factory=list,
        description="IDs of steps this step depends on"
    )
    output_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Expected output structure for validation"
    )
    
    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate step ID format."""
        if not v or not v.strip():
            raise ValueError("Step ID cannot be empty")
        if " " in v:
            raise ValueError("Step ID cannot contain spaces")
        return v.strip()
    
    @field_validator("skill")
    @classmethod
    def validate_skill(cls, v: str) -> str:
        """Validate skill identifier is not empty."""
        if not v or not v.strip():
            raise ValueError("Skill identifier cannot be empty")
        return v.strip()
    
    model_config = ConfigDict(extra="forbid")  # Strict field validation


class Plan(BaseModel):
    """
    A structured task plan with clear goals and step definitions.
    
    Attributes:
        id: Unique plan identifier
        goal: Clear statement of what this plan achieves
        steps: Ordered list of steps to execute
        metadata: Optional metadata for versioning and categorization
        
    Example:
        Plan(
            id="plan_fix_test_001",
            goal="Fix failing unit test by applying code patch",
            steps=[
                PlanStep(id="step1", name="Read file", skill="file.read", 
                        input={"path": "app.py"}),
                PlanStep(id="step2", name="Generate patch", skill="llm.generate",
                        input={"task": "fix bug"}, depends_on=["step1"]),
                PlanStep(id="step3", name="Apply patch", skill="file.apply_patch",
                        input={"patch": "__from_previous_step"}, depends_on=["step2"]),
                PlanStep(id="step4", name="Run tests", skill="shell.run",
                        input={"command": "pytest"}, depends_on=["step3"]),
            ],
            metadata=PlanMetadata(version="0.1", created_by="agent_001")
        )
    """
    id: str = Field(..., description="Unique plan identifier")
    goal: str = Field(..., description="Clear goal statement")
    steps: List[PlanStep] = Field(..., description="List of steps to execute")
    metadata: Optional[PlanMetadata] = Field(default=None, description="Plan metadata")
    
    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate plan ID format."""
        if not v or not v.strip():
            raise ValueError("Plan ID cannot be empty")
        return v.strip()
    
    @field_validator("goal")
    @classmethod
    def validate_goal(cls, v: str) -> str:
        """Validate goal is not empty."""
        if not v or not v.strip():
            raise ValueError("Plan goal cannot be empty")
        return v.strip()
    
    @field_validator("steps")
    @classmethod
    def validate_steps_not_empty(cls, v: List[PlanStep]) -> List[PlanStep]:
        """Validate steps list is not empty."""
        if not v or len(v) == 0:
            raise ValueError("Plan must have at least one step")
        return v
    
    def get_step_ids(self) -> List[str]:
        """Get all step IDs in this plan."""
        return [step.id for step in self.steps]
    
    def get_step_by_id(self, step_id: str) -> Optional[PlanStep]:
        """Get a specific step by ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return self.model_dump(mode="json")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        """Create Plan from dictionary (Pydantic validation only).
        
        Note: This method only performs Pydantic model validation.
        For full contract validation (dependency checks, cycle detection),
        explicitly call validate_plan(plan) after creation.
        
        Example:
            plan = Plan.from_dict(data)
            validate_plan(plan)  # Required for dependency validation
        """
        return cls.model_validate(data)
    
    model_config = ConfigDict(
        extra="forbid",  # Strict contract enforcement
        json_schema_extra={
            "example": {
                "id": "plan_001",
                "goal": "Fix failing unit test",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Read file",
                        "skill": "file.read",
                        "input": {"path": "app.py"},
                        "depends_on": []
                    },
                    {
                        "id": "step2",
                        "name": "Generate patch",
                        "skill": "llm.generate",
                        "input": {"task": "fix bug"},
                        "depends_on": ["step1"]
                    }
                ],
                "metadata": {
                    "version": "0.1",
                    "created_by": "agent_001"
                }
            }
        }
    )
