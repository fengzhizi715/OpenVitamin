"""
V2.8 Inference Gateway Layer - Model Alias Registry

Manages model alias → provider/model_id mappings.
"""
from typing import Dict, Optional, List
from dataclasses import dataclass
from log import logger


@dataclass
class ModelAlias:
    """
    Model alias configuration.
    
    Maps a logical alias to a concrete provider + model_id.
    
    Attributes:
        alias: Logical name (e.g., "reasoning-model", "fast-model")
        provider: Provider name (e.g., "openai", "ollama", "local")
        model_id: Concrete model ID (e.g., "deepseek-r1", "qwen2")
        fallback: Optional fallback alias name if this one fails
        priority: Higher = preferred when multiple match
        enabled: Whether this alias is active
        description: Human-readable description
    """
    alias: str
    provider: str
    model_id: str
    fallback: Optional[str] = None
    priority: int = 0
    enabled: bool = True
    description: str = ""


class InferenceModelRegistry:
    """
    Manages model alias → provider/model_id mappings.
    
    Supports:
    - Alias registration and lookup
    - Fallback chains
    - Priority-based selection
    
    Usage:
        registry = InferenceModelRegistry()
        registry.register(ModelAlias(
            alias="reasoning-model",
            provider="openai",
            model_id="deepseek-r1"
        ))
        alias = registry.resolve("reasoning-model")
    """
    
    def __init__(self):
        self._aliases: Dict[str, ModelAlias] = {}
        self._load_defaults()
    
    def _load_defaults(self) -> None:
        """
        Load default aliases from existing ModelRegistry.
        
        Creates sensible defaults based on available models.
        """
        try:
            from core.models.registry import get_model_registry
            
            model_registry = get_model_registry()
            models = model_registry.list_models()
            
            if not models:
                logger.debug("[InferenceModelRegistry] No models found in registry")
                return
            
            # Create default aliases based on model capabilities
            for model in models:
                # Skip if already have an alias for this model
                if model.id in self._aliases:
                    continue
                
                # Auto-register model_id as alias (passthrough mode)
                self._aliases[model.id] = ModelAlias(
                    alias=model.id,
                    provider=model.provider,
                    model_id=model.id,
                    description=f"Auto-registered: {model.name}"
                )
            
            logger.debug(f"[InferenceModelRegistry] Loaded {len(self._aliases)} model aliases")
            
        except Exception as e:
            logger.warning(f"[InferenceModelRegistry] Failed to load defaults: {e}")
    
    def register(self, alias: ModelAlias) -> None:
        """
        Register a model alias.
        
        Args:
            alias: ModelAlias configuration
        """
        self._aliases[alias.alias] = alias
        logger.info(f"[InferenceModelRegistry] Registered alias '{alias.alias}' -> {alias.provider}/{alias.model_id}")
    
    def register_batch(self, aliases: List[ModelAlias]) -> None:
        """Register multiple aliases at once"""
        for alias in aliases:
            self.register(alias)
    
    def resolve(self, alias_name: str) -> Optional[ModelAlias]:
        """
        Resolve an alias name to its configuration.
        
        Args:
            alias_name: The alias to resolve
            
        Returns:
            ModelAlias if found, None otherwise
        """
        return self._aliases.get(alias_name)
    
    def unregister(self, alias_name: str) -> bool:
        """
        Remove an alias.
        
        Args:
            alias_name: The alias to remove
            
        Returns:
            True if removed, False if not found
        """
        if alias_name in self._aliases:
            del self._aliases[alias_name]
            return True
        return False
    
    def list_aliases(self) -> List[str]:
        """List all registered alias names"""
        return list(self._aliases.keys())
    
    def get_all(self) -> Dict[str, ModelAlias]:
        """Get all registered aliases"""
        return dict(self._aliases)
    
    def set_enabled(self, alias_name: str, enabled: bool) -> bool:
        """
        Enable or disable an alias.
        
        Args:
            alias_name: The alias to modify
            enabled: New enabled state
            
        Returns:
            True if modified, False if not found
        """
        alias = self._aliases.get(alias_name)
        if alias:
            alias.enabled = enabled
            return True
        return False
    
    def refresh(self) -> int:
        """
        Refresh aliases from the underlying ModelRegistry.
        
        Call this when models are added/removed dynamically.
        
        Returns:
            Number of new aliases added
        """
        added = 0
        try:
            from core.models.registry import get_model_registry
            
            model_registry = get_model_registry()
            models = model_registry.list_models()
            
            for model in models:
                if model.id not in self._aliases:
                    self._aliases[model.id] = ModelAlias(
                        alias=model.id,
                        provider=model.provider,
                        model_id=model.id,
                        description=f"Auto-registered: {model.name}"
                    )
                    added += 1
            
            if added > 0:
                logger.info(f"[InferenceModelRegistry] Refreshed, added {added} new aliases")
            
        except Exception as e:
            logger.warning(f"[InferenceModelRegistry] Refresh failed: {e}")
        
        return added
    
    def sync_from_registry(self) -> Dict[str, str]:
        """
        Full sync with ModelRegistry - remove stale aliases.
        
        Returns:
            Dict with 'added' and 'removed' counts
        """
        result = {"added": 0, "removed": 0}
        
        try:
            from core.models.registry import get_model_registry
            
            model_registry = get_model_registry()
            models = model_registry.list_models()
            valid_ids = {m.id for m in models}
            
            # Remove stale aliases (only auto-registered ones)
            stale = [
                alias_name for alias_name, alias in self._aliases.items()
                if alias_name not in valid_ids and alias.description.startswith("Auto-registered:")
            ]
            for alias_name in stale:
                del self._aliases[alias_name]
                result["removed"] += 1
            
            # Add new models
            for model in models:
                if model.id not in self._aliases:
                    self._aliases[model.id] = ModelAlias(
                        alias=model.id,
                        provider=model.provider,
                        model_id=model.id,
                        description=f"Auto-registered: {model.name}"
                    )
                    result["added"] += 1
            
            if result["added"] > 0 or result["removed"] > 0:
                logger.info(
                    f"[InferenceModelRegistry] Synced: +{result['added']}, -{result['removed']}"
                )
            
        except Exception as e:
            logger.warning(f"[InferenceModelRegistry] Sync failed: {e}")
        
        return result


# Singleton
_registry = None


def get_inference_model_registry() -> InferenceModelRegistry:
    """Get the global InferenceModelRegistry singleton"""
    global _registry
    if _registry is None:
        _registry = InferenceModelRegistry()
    return _registry
