"""
Project Intelligence Model - Static Engineering Cognitive Engine.

This module defines the data structures for representing a project's
structural and semantic model. It is completely independent of Agent,
test, build, or patch functionality.

The ProjectModel is a JSON-serializable representation of a codebase
that can be used for:
- Architecture understanding
- Risk assessment
- Development planning
- Code navigation
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class Language(Enum):
    """Supported programming languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    CPP = "cpp"
    UNKNOWN = "unknown"


class ModuleType(Enum):
    """Module classification types."""
    SERVICE = "service"
    MODEL = "model"
    CONTROLLER = "controller"
    ROUTE = "route"
    UTILITY = "utility"
    CONFIG = "config"
    TEST = "test"
    UNKNOWN = "unknown"


class EntryPointType(Enum):
    """Entry point classification."""
    HTTP_SERVER = "http_server"
    CLI = "cli"
    SCRIPT = "script"
    LIBRARY = "library"
    UNKNOWN = "unknown"


# ============================================================
# Layer 1: Meta
# ============================================================

@dataclass
class ProjectMeta:
    """
    Project metadata - top-level information.
    
    Example:
        {
            "language": "python",
            "languages_detected": ["python", "javascript"],
            "repo_root": "/workspace",
            "file_count": 132,
            "size_kb": 824,
            "monorepo": false
        }
    """
    language: str = "unknown"
    languages_detected: List[str] = field(default_factory=list)
    repo_root: str = "."
    file_count: int = 0
    size_kb: int = 0
    monorepo: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "language": self.language,
            "languages_detected": self.languages_detected,
            "repo_root": self.repo_root,
            "file_count": self.file_count,
            "size_kb": self.size_kb,
            "monorepo": self.monorepo,
        }


# ============================================================
# Layer 2: Structure
# ============================================================

@dataclass
class DirectoryNode:
    """
    A node in the directory tree (file or directory).
    """
    path: str
    type: str  # "file" or "directory"
    children: List["DirectoryNode"] = field(default_factory=list)
    file_type: Optional[str] = None  # Extension for files
    size_bytes: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "type": self.type,
            "children": [c.to_dict() for c in self.children] if self.children else [],
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
        }


@dataclass
class LayeredGuess:
    """
    Architecture layer inference based on directory structure.
    
    This is a heuristic-based guess, not definitive.
    """
    presentation: List[str] = field(default_factory=list)  # routes/, controllers/, views/
    service: List[str] = field(default_factory=list)       # services/, business/
    data: List[str] = field(default_factory=list)          # models/, repository/, db/
    utils: List[str] = field(default_factory=list)         # utils/, helpers/
    config: List[str] = field(default_factory=list)        # config/, settings/
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "presentation": self.presentation,
            "service": self.service,
            "data": self.data,
            "utils": self.utils,
            "config": self.config,
        }


@dataclass
class ProjectStructure:
    """
    Directory structure and architecture inference.
    """
    tree: List[DirectoryNode] = field(default_factory=list)
    layered_guess: LayeredGuess = field(default_factory=LayeredGuess)
    directory_count: int = 0
    max_depth: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tree": [n.to_dict() for n in self.tree],
            "layered_guess": self.layered_guess.to_dict(),
            "directory_count": self.directory_count,
            "max_depth": self.max_depth,
        }


# ============================================================
# Layer 3: Modules
# ============================================================

@dataclass
class ModuleInfo:
    """
    Module abstraction - a single code file or logical unit.
    
    Example:
        {
            "name": "user_service",
            "path": "app/services/user_service.py",
            "type": "service",
            "exports": ["create_user", "get_user"],
            "imports": ["app.models.user"],
            "depends_on": ["user_model"],
            "lines": 230
        }
    """
    name: str
    path: str
    type: str = "unknown"  # ModuleType value
    exports: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    lines: int = 0
    has_tests: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "type": self.type,
            "exports": self.exports,
            "imports": self.imports,
            "depends_on": self.depends_on,
            "lines": self.lines,
            "has_tests": self.has_tests,
        }


# ============================================================
# Layer 4: Entry Points
# ============================================================

@dataclass
class EntryPoint:
    """
    Project entry point.
    
    Example:
        {
            "file": "main.py",
            "type": "http_server",
            "framework": "fastapi"
        }
    """
    file: str
    type: str  # EntryPointType value
    framework: Optional[str] = None
    port: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "type": self.type,
            "framework": self.framework,
            "port": self.port,
        }


# ============================================================
# Layer 5: Tests
# ============================================================

@dataclass
class TestInfo:
    """
    Test structure and configuration.
    
    Example:
        {
            "framework": "pytest",
            "test_dirs": ["tests/"],
            "test_files": ["tests/test_user.py"],
            "coverage_target_guess": ["services/", "models/"]
        }
    """
    framework: Optional[str] = None
    test_dirs: List[str] = field(default_factory=list)
    test_files: List[str] = field(default_factory=list)
    coverage_target_guess: List[str] = field(default_factory=list)
    has_fixtures: bool = False
    has_mocks: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "framework": self.framework,
            "test_dirs": self.test_dirs,
            "test_files": self.test_files,
            "coverage_target_guess": self.coverage_target_guess,
            "has_fixtures": self.has_fixtures,
            "has_mocks": self.has_mocks,
        }


# ============================================================
# Layer 6: Dependencies
# ============================================================

@dataclass
class DependencyInfo:
    """
    Dependency management and internal graph.
    
    Example:
        {
            "package_manager": "pip",
            "requirements_file": "requirements.txt",
            "external_libs": ["fastapi", "sqlalchemy"],
            "internal_graph": {"user_service": ["user_model"]}
        }
    """
    package_manager: Optional[str] = None
    requirements_files: List[str] = field(default_factory=list)
    external_libs: List[str] = field(default_factory=list)
    internal_graph: Dict[str, List[str]] = field(default_factory=dict)
    dev_dependencies: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "package_manager": self.package_manager,
            "requirements_files": self.requirements_files,
            "external_libs": self.external_libs,
            "internal_graph": self.internal_graph,
            "dev_dependencies": self.dev_dependencies,
        }


# ============================================================
# Layer 7: Framework
# ============================================================

@dataclass
class FrameworkInfo:
    """
    Detected frameworks and libraries.
    
    Example:
        {
            "web_framework": "fastapi",
            "orm": "sqlalchemy",
            "task_queue": null,
            "frontend": null,
            "kmp_targets": ["jvm", "ios", "android"]
        }
    """
    web_framework: Optional[str] = None
    orm: Optional[str] = None
    task_queue: Optional[str] = None
    frontend: Optional[str] = None
    testing: Optional[str] = None
    database: Optional[str] = None
    # Kotlin Multiplatform
    is_kmp: bool = False
    kmp_targets: List[str] = field(default_factory=list)
    kmp_source_sets: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "web_framework": self.web_framework,
            "orm": self.orm,
            "task_queue": self.task_queue,
            "frontend": self.frontend,
            "testing": self.testing,
            "database": self.database,
            "is_kmp": self.is_kmp,
            "kmp_targets": self.kmp_targets,
            "kmp_source_sets": self.kmp_source_sets,
        }


# ============================================================
# Layer 8: Build System
# ============================================================

@dataclass
class BuildInfo:
    """
    Build system and CI/CD detection.
    
    Example:
        {
            "type": "python",
            "has_makefile": false,
            "has_dockerfile": true,
            "ci_detected": true
        }
    """
    type: str = "unknown"
    has_makefile: bool = False
    has_dockerfile: bool = False
    dockerfile_path: Optional[str] = None
    ci_detected: bool = False
    ci_files: List[str] = field(default_factory=list)
    build_commands: List[str] = field(default_factory=list)
    cmake: Optional[Dict[str, Any]] = None  # CMake project info
    maven: Optional[Dict[str, Any]] = None  # Maven project info (Java)
    gradle: Optional[Dict[str, Any]] = None  # Gradle project info (Java/Kotlin)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "has_makefile": self.has_makefile,
            "has_dockerfile": self.has_dockerfile,
            "dockerfile_path": self.dockerfile_path,
            "ci_detected": self.ci_detected,
            "ci_files": self.ci_files,
            "build_commands": self.build_commands,
            "cmake": self.cmake,
            "maven": self.maven,
            "gradle": self.gradle,
        }


# ============================================================
# Layer 9: Risk Profile
# ============================================================

@dataclass
class RiskProfile:
    """
    Engineering risk assessment.
    
    This is critical for industrial-grade development decisions.
    
    Example:
        {
            "large_files": ["legacy.py"],
            "high_coupling_modules": ["core.py"],
            "circular_dependencies_detected": false,
            "unsafe_patterns": ["eval("]
        }
    """
    large_files: List[str] = field(default_factory=list)  # Files > 500 lines
    high_coupling_modules: List[str] = field(default_factory=list)  # > 10 imports
    circular_dependencies_detected: bool = False
    circular_dependencies: List[List[str]] = field(default_factory=list)
    unsafe_patterns: List[str] = field(default_factory=list)  # eval, exec, etc.
    missing_tests: List[str] = field(default_factory=list)
    deprecated_patterns: List[str] = field(default_factory=list)
    risk_score: int = 0  # 0-100, higher = more risky
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "large_files": self.large_files,
            "high_coupling_modules": self.high_coupling_modules,
            "circular_dependencies_detected": self.circular_dependencies_detected,
            "circular_dependencies": self.circular_dependencies,
            "unsafe_patterns": self.unsafe_patterns,
            "missing_tests": self.missing_tests,
            "deprecated_patterns": self.deprecated_patterns,
            "risk_score": self.risk_score,
        }


# ============================================================
# Top-Level Project Model
# ============================================================

@dataclass
class ProjectModel:
    """
    Complete project intelligence model.
    
    This is the main output of the analyze() function.
    It can be serialized to JSON for storage or transfer.
    
    Usage:
        from core.project_intelligence import analyze
        model = analyze("/path/to/workspace")
        print(model.to_json())
    """
    meta: ProjectMeta = field(default_factory=ProjectMeta)
    structure: ProjectStructure = field(default_factory=ProjectStructure)
    modules: List[ModuleInfo] = field(default_factory=list)
    entry_points: List[EntryPoint] = field(default_factory=list)
    tests: TestInfo = field(default_factory=TestInfo)
    dependencies: DependencyInfo = field(default_factory=DependencyInfo)
    framework: FrameworkInfo = field(default_factory=FrameworkInfo)
    build: BuildInfo = field(default_factory=BuildInfo)
    risk: RiskProfile = field(default_factory=RiskProfile)
    
    # Analysis metadata
    analysis_time_ms: int = 0
    analyzer_version: str = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "meta": self.meta.to_dict(),
            "structure": self.structure.to_dict(),
            "modules": [m.to_dict() for m in self.modules],
            "entry_points": [e.to_dict() for e in self.entry_points],
            "tests": self.tests.to_dict(),
            "dependencies": self.dependencies.to_dict(),
            "framework": self.framework.to_dict(),
            "build": self.build.to_dict(),
            "risk": self.risk.to_dict(),
            "analysis_time_ms": self.analysis_time_ms,
            "analyzer_version": self.analyzer_version,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    def get_module_by_path(self, path: str) -> Optional[ModuleInfo]:
        """Find module by file path."""
        for module in self.modules:
            if module.path == path:
                return module
        return None
    
    def get_modules_by_type(self, module_type: str) -> List[ModuleInfo]:
        """Filter modules by type."""
        return [m for m in self.modules if m.type == module_type]
    
    def get_dependency_order(self) -> List[str]:
        """
        Get topological order of modules (dependency-first).
        Useful for understanding which modules to process first.
        """
        # Simple topological sort
        visited = set()
        order = []
        
        def visit(module_name: str):
            if module_name in visited:
                return
            visited.add(module_name)
            
            module = next((m for m in self.modules if m.name == module_name), None)
            if module:
                for dep in module.depends_on:
                    visit(dep)
            order.append(module_name)
        
        for module in self.modules:
            visit(module.name)
        
        return order
