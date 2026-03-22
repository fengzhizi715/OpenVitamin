"""
Project Intelligence - Static Engineering Cognitive Engine.

This module transforms a project from a "file collection" to a 
"structured engineering model" through static analysis.

Key Features:
- Completely independent of Agent, test, build, patch, plan
- Deterministic (no AI, pure static analysis)
- Fast (regex-based, no AST)
- JSON-serializable output

Usage:
    from core.project_intelligence import analyze
    
    model = analyze("/path/to/workspace")
    
    # Access structured information
    print(f"Language: {model.meta.language}")
    print(f"Entry points: {[e.file for e in model.entry_points]}")
    print(f"Risk score: {model.risk.risk_score}")
    
    # Get JSON output
    json_str = model.to_json()

Architecture Layers:
    1. Meta - Project metadata (language, file count, size)
    2. Structure - Directory tree and architecture inference
    3. Modules - List of modules with imports/exports
    4. Entry Points - Detected entry points
    5. Tests - Test structure and framework
    6. Dependencies - External libs and internal graph
    7. Framework - Detected frameworks (web, ORM, etc.)
    8. Build - Build system and CI/CD info
    9. Risk - Engineering risk profile
"""

from .model import (
    ProjectModel,
    ProjectMeta,
    ProjectStructure,
    DirectoryNode,
    LayeredGuess,
    ModuleInfo,
    EntryPoint,
    EntryPointType,
    TestInfo,
    DependencyInfo,
    FrameworkInfo,
    BuildInfo,
    RiskProfile,
    Language,
    ModuleType,
)

from .analyzer import analyze
from .formatter import ProjectFormatter, format_project_analysis

__version__ = "1.0.0"

__all__ = [
    # Main API
    'analyze',
    'format_project_analysis',
    
    # Formatters
    'ProjectFormatter',
    
    # Models
    'ProjectModel',
    'ProjectMeta',
    'ProjectStructure',
    'DirectoryNode',
    'LayeredGuess',
    'ModuleInfo',
    'EntryPoint',
    'EntryPointType',
    'TestInfo',
    'DependencyInfo',
    'FrameworkInfo',
    'BuildInfo',
    'RiskProfile',
    
    # Enums
    'Language',
    'ModuleType',
]
