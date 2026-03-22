"""
V2.8 Inference Gateway Layer - Model Router

Resolves model_alias to (provider, model_id) with fallback support.
"""
from typing import Optional
from dataclasses import dataclass
from log import logger

from core.inference.registry.model_registry import (
    InferenceModelRegistry,
    ModelAlias,
    get_inference_model_registry,
)


@dataclass
class RoutingResult:
    """
    Result of model alias resolution.
    
    Attributes:
        alias: The resolved ModelAlias (None if direct passthrough)
        provider: Provider name (e.g., 'openai', 'ollama')
        model_id: Concrete model ID to use
        resolved_via: How the resolution was done ('alias', 'direct', 'fallback')
    """
    alias: Optional[ModelAlias]
    provider: str
    model_id: str
    resolved_via: str  # "alias", "direct", "fallback"


class ModelRouter:
    """
    Resolves model_alias to (provider, model_id).
    
    Resolution order:
    1. Exact alias match (if enabled)
    2. Fallback chain (if alias has fallback)
    3. Direct passthrough (treat alias as model_id)
    
    Usage:
        router = ModelRouter()
        result = router.resolve("reasoning-model")
        print(f"Provider: {result.provider}, Model: {result.model_id}")
    """
    
    def __init__(self, registry: Optional[InferenceModelRegistry] = None):
        self.registry = registry or get_inference_model_registry()
    
    def resolve(self, model_alias: str, max_depth: int = 10) -> RoutingResult:
        """
        Resolve an alias to provider + model_id.
        
        Args:
            model_alias: The alias to resolve
            
        Returns:
            RoutingResult with resolution details
        """
        visited = set()
        current = model_alias
        for _ in range(max_depth):
            if current in visited:
                logger.warning(f"[ModelRouter] Circular fallback detected for '{model_alias}'")
                break
            visited.add(current)

            alias = self.registry.resolve(current)
            if alias:
                if alias.enabled:
                    return RoutingResult(
                        alias=alias,
                        provider=alias.provider,
                        model_id=alias.model_id,
                        resolved_via="alias",
                    )
                if alias.fallback:
                    logger.info(
                        f"[ModelRouter] Alias '{current}' disabled, trying fallback '{alias.fallback}'"
                    )
                    current = alias.fallback
                    continue
            break
        
        # 3. Direct passthrough - treat alias as model_id
        # This allows backward compatibility with existing model_ids
        logger.debug(
            f"[ModelRouter] No alias found for '{model_alias}', "
            f"using as direct model_id"
        )
        return RoutingResult(
            alias=None,
            provider="auto",  # Let existing system determine provider
            model_id=current,
            resolved_via="direct"
        )
    
    def resolve_with_fallback_chain(
        self,
        model_alias: str,
        max_depth: int = 5
    ) -> RoutingResult:
        """
        Resolve with explicit fallback chain tracking.
        
        Args:
            model_alias: The alias to resolve
            max_depth: Maximum fallback depth to prevent infinite loops
            
        Returns:
            RoutingResult with resolution details
        """
        visited = set()
        current_alias = model_alias
        
        for _ in range(max_depth):
            if current_alias in visited:
                logger.warning(
                    f"[ModelRouter] Circular fallback detected for '{model_alias}'"
                )
                break
            
            visited.add(current_alias)
            result = self.resolve(current_alias)
            
            if result.resolved_via != "fallback":
                return result
            
            # Continue with fallback
            alias = self.registry.resolve(current_alias)
            if alias and alias.fallback:
                current_alias = alias.fallback
            else:
                break
        
        # Final resolution
        return self.resolve(current_alias)
    
    def list_available_models(self) -> list:
        """
        List all available model aliases.
        
        Returns:
            List of alias names that can be resolved
        """
        return self.registry.list_aliases()
    
    def is_alias_registered(self, alias_name: str) -> bool:
        """Check if an alias is registered"""
        return self.registry.resolve(alias_name) is not None
