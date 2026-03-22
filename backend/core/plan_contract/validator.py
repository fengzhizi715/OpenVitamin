"""
Plan Contract validation logic.

This module provides validation functions for Plan contracts:
- Validate step ID uniqueness
- Validate dependency references exist
- Validate steps are non-empty
- Validate DAG structure (no cycles)

Does NOT implement execution or scheduling logic.
"""

from typing import List, Set, Dict, Optional, Any
from .models import Plan, PlanStep


class PlanValidationError(Exception):
    """Exception raised when plan validation fails."""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for error reporting."""
        return {
            "error": "PlanValidationError",
            "message": self.message,
            "details": self.details
        }


def validate_plan(plan: Plan) -> None:
    """
    Validate a Plan contract.
    
    Checks:
    1. Plan has non-empty steps
    2. All step IDs are unique
    3. All depends_on references point to existing step IDs
    4. No circular dependencies (DAG validation)
    5. Required fields are present
    
    Args:
        plan: The Plan to validate
        
    Raises:
        PlanValidationError: If validation fails
        
    Example:
        try:
            validate_plan(plan)
            print("Plan is valid")
        except PlanValidationError as e:
            print(f"Validation failed: {e.message}")
    """
    # Check 1: Steps must not be empty
    if not plan.steps or len(plan.steps) == 0:
        raise PlanValidationError(
            "Plan must have at least one step",
            {"plan_id": plan.id}
        )
    
    # Check 2: All step IDs must be unique
    step_ids = [step.id for step in plan.steps]
    duplicate_ids = _find_duplicates(step_ids)
    if duplicate_ids:
        raise PlanValidationError(
            f"Duplicate step IDs found: {duplicate_ids}",
            {"duplicate_ids": duplicate_ids, "all_ids": step_ids}
        )
    
    # Check 3: All depends_on references must exist
    step_id_set = set(step_ids)
    for step in plan.steps:
        if step.depends_on:
            missing_deps = [dep for dep in step.depends_on if dep not in step_id_set]
            if missing_deps:
                raise PlanValidationError(
                    f"Step '{step.id}' depends on non-existent steps: {missing_deps}",
                    {
                        "step_id": step.id,
                        "missing_dependencies": missing_deps,
                        "available_ids": list(step_id_set)
                    }
                )
    
    # Check 4: No circular dependencies (DAG validation)
    _validate_no_cycles(plan)
    
    # Check 5: Validate individual steps
    for i, step in enumerate(plan.steps):
        _validate_step(step, i)


def _validate_step(step: PlanStep, index: int) -> None:
    """
    Validate an individual step.
    
    Args:
        step: The step to validate
        index: Position in the plan (for error reporting)
        
    Raises:
        PlanValidationError: If step validation fails
    """
    # Check required fields
    if not step.id or not step.id.strip():
        raise PlanValidationError(
            f"Step at index {index} has empty ID",
            {"step_index": index, "step_name": step.name}
        )
    
    if not step.skill or not step.skill.strip():
        raise PlanValidationError(
            f"Step '{step.id}' has empty skill identifier",
            {"step_index": index, "step_name": step.name}
        )
    
    # Check: Step cannot depend on itself
    if step.depends_on and step.id in step.depends_on:
        raise PlanValidationError(
            f"Step '{step.id}' cannot depend on itself",
            {
                "step_id": step.id,
                "depends_on": step.depends_on
            }
        )


def _validate_no_cycles(plan: Plan) -> None:
    """
    Validate that the plan has no circular dependencies (is a DAG).
    
    Uses depth-first search to detect cycles in the dependency graph.
    
    Args:
        plan: The plan to validate
        
    Raises:
        PlanValidationError: If circular dependency detected
    """
    # Build adjacency list
    graph: Dict[str, List[str]] = {}
    for step in plan.steps:
        graph[step.id] = step.depends_on or []
    
    # DFS-based cycle detection
    # States: 0=unvisited, 1=visiting, 2=visited
    state: Dict[str, int] = {step_id: 0 for step_id in graph.keys()}
    path: List[str] = []
    
    def dfs(node: str) -> bool:
        """Returns True if cycle detected."""
        if state[node] == 1:  # Currently visiting -> cycle!
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            raise PlanValidationError(
                f"Circular dependency detected: {' -> '.join(cycle)}",
                {
                    "cycle": cycle,
                    "full_path": path.copy()
                }
            )
        
        if state[node] == 2:  # Already visited
            return False
        
        # Mark as visiting
        state[node] = 1
        path.append(node)
        
        # Visit all dependencies
        for dep in graph.get(node, []):
            if dep in graph:  # Only check deps that exist in graph
                if dfs(dep):
                    return True
        
        # Mark as visited
        path.pop()
        state[node] = 2
        return False
    
    # Check all nodes
    for step_id in graph.keys():
        if state[step_id] == 0:  # Unvisited
            if dfs(step_id):
                pass  # Cycle already reported by DFS
    
    # No cycles found
    return None


def _find_duplicates(items: List[str]) -> List[str]:
    """
    Find duplicate strings in a list.
    
    Args:
        items: List of strings to check
        
    Returns:
        List of duplicate values (empty if none)
    """
    seen: Set[str] = set()
    duplicates: Set[str] = set()
    
    for item in items:
        if item in seen:
            duplicates.add(item)
        else:
            seen.add(item)
    
    return list(duplicates)


def validate_plan_structure(plan: Plan) -> Dict[str, Any]:
    """
    Analyze plan structure and return statistics.
    
    This is a helper function for debugging and monitoring.
    
    Important: This function does NOT perform validation. 
    Call validate_plan(plan) first to ensure the plan is valid.
    
    Args:
        plan: The plan to analyze
        
    Returns:
        Dictionary with structural information:
        - total_steps: Total number of steps
        - root_steps: Steps with no dependencies
        - leaf_steps: Steps with no dependents
        - max_depth: Maximum dependency chain length
        - has_cycles: Whether cycles exist (only accurate after validate_plan)
        
    Example:
        validate_plan(plan)  # First validate
        stats = validate_plan_structure(plan)  # Then analyze
    """
    step_ids = set(step.id for step in plan.steps)
    
    # Find root steps (no dependencies)
    root_steps = [
        step.id for step in plan.steps 
        if not step.depends_on or len(step.depends_on) == 0
    ]
    
    # Find leaf steps (no other step depends on them)
    all_deps: Set[str] = set()
    for step in plan.steps:
        all_deps.update(step.depends_on or [])
    
    leaf_steps = [
        step.id for step in plan.steps 
        if step.id not in all_deps
    ]
    
    # Calculate max depth (longest dependency chain)
    def get_depth(step_id: str, memo: Dict[str, int] = None) -> int:
        if memo is None:
            memo = {}
        
        if step_id in memo:
            return memo[step_id]
        
        step = plan.get_step_by_id(step_id)
        if not step or not step.depends_on:
            memo[step_id] = 1
            return 1
        
        max_dep_depth = max(
            get_depth(dep, memo) for dep in step.depends_on 
            if dep in step_ids
        )
        memo[step_id] = max_dep_depth + 1
        return memo[step_id]
    
    max_depth = max((get_depth(step_id) for step_id in step_ids), default=0)
    
    return {
        "total_steps": len(plan.steps),
        "root_steps": root_steps,
        "leaf_steps": leaf_steps,
        "max_depth": max_depth,
        "has_cycles": False  # If validation passed, no cycles
    }
