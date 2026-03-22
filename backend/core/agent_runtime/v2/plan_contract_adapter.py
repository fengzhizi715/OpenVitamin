"""
Plan Contract -> Agent V2 runtime Plan adapter.

This adapter keeps execution model unchanged (sequential execution) while
allowing Planner/RePlan to accept validated Plan Contract payloads.

Features:
- Detailed logging for debugging
- Configurable skill mapping
- Comprehensive error handling
"""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from log import logger
from core.plan_contract.models import Plan as ContractPlan
from core.plan_contract.models import PlanStep as ContractStep
from core.plan_contract.validator import PlanValidationError, validate_plan

from .models import ExecutorType, Plan, Step, StepType

# Configurable skill mapping patterns
SKILL_MAPPING_CONFIG = {
    r"llm\..*": ExecutorType.LLM,
    r"builtin_llm\..*": ExecutorType.LLM,
    r"internal\..*": ExecutorType.INTERNAL,
    r"file\..*": ExecutorType.SKILL,
    r"shell\..*": ExecutorType.SKILL,
    r"builtin_.*": ExecutorType.SKILL,
}


def try_parse_contract_plan(raw: Any) -> Optional[ContractPlan]:
    """
    Parse contract plan from dict/JSON string.

    Returns None when payload does not look like a Plan Contract.
    Raises ValueError when payload looks like contract but is invalid.
    
    Logging:
        - Debug: When attempting to parse
        - Info: When successfully parsed
        - Error: When parsing fails with details
    """
    data: Optional[Dict[str, Any]] = None

    if isinstance(raw, dict):
        logger.debug("[PlanContractAdapter] Attempting to parse contract from dict")
        data = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        # 支持 ```json ... ``` 包裹
        if text.startswith("```"):
            logger.debug("[PlanContractAdapter] Unwrapping fenced JSON")
            text = _unwrap_fenced_json(text)
        if not text.startswith("{"):
            return None
        try:
            data = json.loads(text)
            logger.debug(f"[PlanContractAdapter] Parsed JSON string: {len(data)} keys")
        except Exception as e:
            logger.warning(f"[PlanContractAdapter] Failed to parse JSON: {e}")
            return None
    else:
        return None

    # 基础结构探测：仅在像 Contract 的情况下尝试严格校验
    if not isinstance(data, dict):
        logger.debug("[PlanContractAdapter] Data is not a dict, skipping")
        return None
    if "steps" not in data or "goal" not in data:
        logger.debug(f"[PlanContractAdapter] Missing required fields (steps/goal), has keys: {list(data.keys())}")
        return None

    try:
        logger.info(f"[PlanContractAdapter] Validating contract: id={data.get('id', 'unknown')}")
        plan = ContractPlan.from_dict(data)
        validate_plan(plan)
        logger.info(f"[PlanContractAdapter] Successfully parsed contract: {plan.id} ({len(plan.steps)} steps)")
        return plan
    except PlanValidationError as e:
        logger.error(f"[PlanContractAdapter] Validation failed: {e.message}, details: {e.details}")
        raise ValueError(f"Invalid Plan Contract: {e.message}") from e
    except Exception as e:
        logger.error(f"[PlanContractAdapter] Unexpected error: {type(e).__name__}: {e}")
        raise ValueError(f"Invalid Plan Contract payload: {e}") from e


def adapt_contract_to_runtime_plan(
    contract_plan: ContractPlan,
    context: Optional[Dict[str, Any]] = None,
    parent_plan_id: Optional[str] = None,
) -> Plan:
    """
    Convert Plan Contract to runtime Plan.

    Note: runtime executor is sequential; we topologically sort steps and then
    execute linearly, without introducing DAG executor semantics.
    
    Logging:
        - Info: Conversion start/end
        - Debug: Step-by-step conversion details
        - Warning: Any fallbacks or issues
    """
    logger.info(f"[PlanContractAdapter] Converting contract '{contract_plan.id}' to runtime plan")
    logger.debug(f"  Goal: {contract_plan.goal}")
    logger.debug(f"  Steps count: {len(contract_plan.steps)}")
    logger.debug(f"  Context keys: {list(context.keys()) if context else 'None'}")

    ordered_steps = _topological_sort(contract_plan.steps)
    logger.debug(f"  Topo sorted order: {[s.id for s in ordered_steps]}")
    
    runtime_steps: List[Step] = []

    for item in ordered_steps:
        try:
            executor, inputs = _map_contract_step(item)
            logger.debug(f"    Mapping step '{item.id}' ({item.skill}) -> {executor.value}")
            
            runtime_steps.append(
                Step(
                    step_id=item.id,
                    type=StepType.ATOMIC,
                    executor=executor,
                    inputs=inputs,
                )
            )
        except Exception as e:
            logger.error(f"[PlanContractAdapter] Failed to map step '{item.id}': {e}")
            raise

    result = Plan(
        plan_id=contract_plan.id,
        goal=contract_plan.goal,
        context=context or {},
        steps=runtime_steps,
        parent_plan_id=parent_plan_id,
        failure_strategy="stop",
    )
    
    logger.info(f"[PlanContractAdapter] Successfully converted to runtime plan: {result.plan_id} ({len(result.steps)} steps)")
    return result


def _unwrap_fenced_json(text: str) -> str:
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _map_contract_step(step: ContractStep) -> Tuple[ExecutorType, Dict[str, Any]]:
    """
    Map contract step to runtime executor type and inputs.
    
    Uses configurable pattern matching for flexibility.
    Falls back to SKILL executor if no pattern matches.
    
    For SKILL executor, wraps input as {"skill_id": skill, "inputs": step.input}
    For LLM/INTERNAL, uses step.input directly
    """
    skill = (step.skill or "").strip()
    logger.debug(f"[PlanContractAdapter] Mapping skill: '{skill}'")
    
    # Try pattern-based matching
    for pattern, executor_type in SKILL_MAPPING_CONFIG.items():
        if re.match(pattern, skill):
            logger.debug(f"  Matched pattern '{pattern}' -> {executor_type.value}")
            if executor_type == ExecutorType.SKILL:
                return executor_type, {"skill_id": skill, "inputs": dict(step.input or {})}
            if executor_type == ExecutorType.LLM:
                return executor_type, _normalize_llm_inputs(step.input or {})
            else:
                return executor_type, dict(step.input or {})
    
    # Fallback: detect by common prefixes
    if skill.startswith("llm.") or skill == "builtin_llm.generate":
        logger.debug(f"  Fallback: detected as LLM")
        return ExecutorType.LLM, _normalize_llm_inputs(step.input or {})
    if skill.startswith("internal."):
        logger.debug(f"  Fallback: detected as INTERNAL")
        return ExecutorType.INTERNAL, dict(step.input or {})
    
    # Default to SKILL
    logger.debug(f"  Fallback: defaulting to SKILL")
    return ExecutorType.SKILL, {"skill_id": skill, "inputs": dict(step.input or {})}


def _normalize_llm_inputs(raw_inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate/normalize LLM step inputs.

    Allowed minimal forms:
    - {"messages": [...]}  (preferred)
    - {"prompt": "..."}    (auto-converted to messages)
    """
    inputs = dict(raw_inputs or {})
    messages = inputs.get("messages")
    prompt = inputs.get("prompt")

    if isinstance(messages, list) and len(messages) > 0:
        return inputs

    if isinstance(prompt, str) and prompt.strip():
        normalized = dict(inputs)
        normalized["messages"] = [{"role": "user", "content": prompt.strip()}]
        normalized.pop("prompt", None)
        return normalized

    raise ValueError(
        "Invalid LLM step input: expected non-empty 'messages' or non-empty 'prompt'"
    )


def _topological_sort(steps: List[ContractStep]) -> List[ContractStep]:
    """
    Stable Kahn topo sort.
    Keeps original order among same indegree nodes.
    
    Logging:
        - Debug: Sort progress and result
        - Warning: If fallback to original order occurs
    """
    logger.debug(f"[PlanContractAdapter] Topo sorting {len(steps)} steps")
    
    by_id: Dict[str, ContractStep] = {s.id: s for s in steps}
    indegree: Dict[str, int] = {s.id: 0 for s in steps}
    outgoing: Dict[str, List[str]] = {s.id: [] for s in steps}

    for s in steps:
        for dep in s.depends_on or []:
            if dep in by_id:
                indegree[s.id] += 1
                outgoing[dep].append(s.id)
            else:
                logger.warning(f"[PlanContractAdapter] Dependency '{dep}' not found in steps")

    queue = deque([s.id for s in steps if indegree[s.id] == 0])
    ordered_ids: List[str] = []

    while queue:
        node = queue.popleft()
        ordered_ids.append(node)
        for nxt in outgoing.get(node, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered_ids) != len(steps):
        logger.warning("[PlanContractAdapter] Topo sort incomplete (cycle detected?); fallback to original order")
        return steps

    result = [by_id[sid] for sid in ordered_ids]
    logger.debug(f"[PlanContractAdapter] Topo sort complete: {[s.id for s in result]}")
    return result
