"""
Permission derivation utilities.

Auto-derive permissions from skill/tool declarations instead of hardcoding mappings.
"""
from typing import Dict, List, Optional, Set

from log import logger


def derive_permissions_from_tool(tool_name: str) -> List[str]:
    """
    Derive required permissions from a tool by looking up its declaration.
    
    Args:
        tool_name: The tool name (e.g., "file.read", "shell.run")
    
    Returns:
        List of required permission keys
    """
    from core.tools.registry import ToolRegistry
    
    tool = ToolRegistry.get(tool_name)
    if not tool:
        # Tool not found - return empty, let execution fail later
        logger.debug(f"[Permissions] Tool not found: {tool_name}")
        return []
    
    permissions = getattr(tool, "required_permissions", None)
    if permissions is None:
        return []
    
    return list(permissions) if isinstance(permissions, (list, tuple)) else []


def derive_permissions_from_skill(skill_id: str) -> List[str]:
    """
    Derive required permissions from a skill by looking up its underlying tools.
    
    Handles different skill types:
    - tool: Single tool, derive from tool's required_permissions
    - workflow/composite: Multiple steps, aggregate all tool permissions
    - prompt: No direct tool, return empty
    
    Args:
        skill_id: The skill ID (e.g., "builtin_file.read", "custom_workflow")
    
    Returns:
        List of required permission keys (deduplicated)
    """
    from core.skills.registry import SkillRegistry
    from core.tools.registry import ToolRegistry
    
    # Cache key for performance
    cache_key = f"skill_perms:{skill_id}"
    
    skill = SkillRegistry.get(skill_id)
    if not skill:
        # Try to derive from builtin_ prefix pattern
        if skill_id.startswith("builtin_"):
            tool_name = skill_id[8:]  # Remove "builtin_" prefix
            return derive_permissions_from_tool(tool_name)
        
        logger.debug(f"[Permissions] Skill not found: {skill_id}")
        return []
    
    skill_type = skill.type
    definition = skill.definition or {}
    
    permissions: Set[str] = set()
    
    if skill_type == "tool":
        # Single tool skill - derive from tool
        tool_name = definition.get("tool_name")
        if tool_name:
            permissions.update(derive_permissions_from_tool(tool_name))
    
    elif skill_type in ("workflow", "composite"):
        # Multi-step workflow - aggregate from all tools
        steps = definition.get("steps", [])
        for step in steps:
            tool_name = step.get("tool") or step.get("tool_name")
            if tool_name:
                permissions.update(derive_permissions_from_tool(tool_name))
    
    # prompt type skills don't have direct tool permissions
    # They may have indirect permissions via rendered prompts, but those are handled at execution time
    
    return list(permissions)


def build_permissions_for_skills(skill_ids: List[str]) -> Dict[str, bool]:
    """
    Build permissions dict for a list of skill IDs.
    
    This replaces hardcoded _build_permissions methods in runtime.py and loop.py.
    
    Args:
        skill_ids: List of skill IDs enabled for an agent
    
    Returns:
        Dict mapping permission keys to True (granted)
    """
    permissions: Dict[str, bool] = {}
    
    for skill_id in skill_ids:
        skill_perms = derive_permissions_from_skill(skill_id)
        for perm in skill_perms:
            permissions[perm] = True
    
    if permissions:
        logger.debug(f"[Permissions] Derived permissions for skills {skill_ids}: {list(permissions.keys())}")
    
    return permissions


# Permission cache for performance
_permission_cache: Dict[str, List[str]] = {}


def get_cached_skill_permissions(skill_id: str) -> List[str]:
    """
    Get skill permissions with caching for performance.
    
    Cache is invalidated on server restart (acceptable for now).
    """
    if skill_id in _permission_cache:
        return _permission_cache[skill_id]
    
    permissions = derive_permissions_from_skill(skill_id)
    _permission_cache[skill_id] = permissions
    return permissions


def clear_permission_cache():
    """Clear the permission cache (useful for testing or hot reload)."""
    global _permission_cache
    _permission_cache = {}
