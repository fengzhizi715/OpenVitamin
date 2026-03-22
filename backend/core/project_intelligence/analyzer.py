"""
Project Intelligence Analyzer - Main API.

This module provides the main `analyze()` function that transforms
a project from a "file collection" to a "structured engineering model".

The analyzer is:
- Independent of Agent, test, build, patch, plan
- Deterministic (no AI, pure static analysis)
- Fast (regex-based, no AST)
- JSON-serializable output

Usage:
    from core.project_intelligence import analyze
    
    model = analyze("/path/to/workspace")
    print(model.to_json())
"""
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .model import (
    ProjectModel,
    ProjectMeta,
    ProjectStructure,
    DirectoryNode,
    LayeredGuess,
    ModuleInfo,
    RiskProfile,
)
from .dependency_graph import (
    extract_imports_from_file,
    extract_exports,
    build_internal_dependency_graph,
    detect_circular_dependencies,
    calculate_coupling,
    get_language_from_extension,
)
from .indexer import (
    detect_entry_points,
    detect_tests,
    detect_frameworks,
    detect_build_system,
    detect_package_manager,
)


# ============================================================
# Configuration
# ============================================================

# Directories to skip during scanning
SKIP_DIRS = {
    '__pycache__', '.git', '.hg', '.svn',
    'node_modules', '.venv', 'venv', 'env',
    '.idea', '.vscode', '.tox', '.pytest_cache',
    'dist', 'build', 'egg-info', '.eggs',
    'target', 'bin', 'obj', '.gradle', '.mvn',
    '.kotlin', '.gradle-kotlin',  # Kotlin/Gradle cache
    'cmake-build-debug', 'cmake-build-release', 'cmake-build',  # CMake build artifacts
    '.kotlin', 'kotlinc',  # Kotlin compiler output
}

# Files to skip
SKIP_FILES = {
    '.DS_Store', '.gitignore', '.gitattributes',
    '*.pyc', '*.pyo', '*.so', '*.dll',
    '*.egg', '*.whl',
}

# Large file threshold (lines)
LARGE_FILE_THRESHOLD = 500

# High coupling threshold (imports)
HIGH_COUPLING_THRESHOLD = 10

# Unsafe code patterns
UNSAFE_PATTERNS = {
    'eval(': 'eval() can execute arbitrary code',
    'exec(': 'exec() can execute arbitrary code',
    '__import__(': 'dynamic import',
    'compile(': 'runtime compilation',
    'subprocess.shell=True': 'shell injection risk',
    'os.system(': 'shell command execution',
    'pickle.loads(': 'pickle deserialization risk',
    'yaml.load(': 'yaml unsafe load (use yaml.safe_load)',
}


# ============================================================
# Step 1: Static File Scanner
# ============================================================

def scan_files(root: Path) -> tuple[List[Path], Dict[str, int], int]:
    """
    Recursively scan directory structure.
    
    Returns:
        Tuple of (all_files, file_count_by_ext, total_size_bytes)
    """
    all_files = []
    file_count_by_ext: Dict[str, int] = {}
    total_size = 0
    
    for path in root.rglob('*'):
        # Skip certain directories
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        
        if path.is_file():
            # Skip certain files
            if path.name in SKIP_FILES:
                continue
            
            all_files.append(path)
            
            # Track extension
            ext = path.suffix.lower()
            file_count_by_ext[ext] = file_count_by_ext.get(ext, 0) + 1
            
            # Track size
            try:
                total_size += path.stat().st_size
            except OSError:
                pass
    
    return all_files, file_count_by_ext, total_size


def build_directory_tree(root: Path, max_depth: int = 10) -> List[DirectoryNode]:
    """
    Build a hierarchical directory tree.
    """
    def _build_node(path: Path, current_depth: int) -> Optional[DirectoryNode]:
        if current_depth > max_depth:
            return None
        
        rel_path = str(path.relative_to(root))
        
        if path.is_dir():
            # Skip certain directories
            if path.name in SKIP_DIRS:
                return None
            
            node = DirectoryNode(
                path=rel_path,
                type="directory",
            )
            
            try:
                for child in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                    child_node = _build_node(child, current_depth + 1)
                    if child_node:
                        node.children.append(child_node)
            except PermissionError:
                pass
            
            return node
        
        else:
            # File node
            if path.name in SKIP_FILES:
                return None
            
            node = DirectoryNode(
                path=rel_path,
                type="file",
                file_type=path.suffix.lower() or None,
            )
            
            try:
                node.size_bytes = path.stat().st_size
            except OSError:
                pass
            
            return node
    
    tree = []
    try:
        for child in sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            node = _build_node(child, 1)
            if node:
                tree.append(node)
    except PermissionError:
        pass
    
    return tree


# ============================================================
# Step 2: Structure Inference
# ============================================================

def infer_architecture_layers(root: Path) -> LayeredGuess:
    """
    Infer architecture layers from directory structure.
    
    This is a heuristic-based guess, not definitive.
    """
    guess = LayeredGuess()
    
    # Get all directories
    dirs = set()
    for d in root.rglob('*'):
        if d.is_dir() and d.name not in SKIP_DIRS:
            rel = str(d.relative_to(root))
            dirs.add(rel)
            # Also add first-level directories
            parts = rel.split('/')
            if len(parts) > 0:
                dirs.add(parts[0] + '/')
    
    # Presentation layer patterns
    presentation_patterns = ['routes', 'controllers', 'views', 'api', 'endpoints', 'handlers', 'views']
    for d in dirs:
        d_name = d.rstrip('/').split('/')[-1].lower()
        if d_name in presentation_patterns:
            guess.presentation.append(d)
    
    # Service layer patterns
    service_patterns = ['services', 'service', 'business', 'usecases', 'use_cases', 'interactors']
    for d in dirs:
        d_name = d.rstrip('/').split('/')[-1].lower()
        if d_name in service_patterns:
            guess.service.append(d)
    
    # Data layer patterns
    data_patterns = ['models', 'model', 'repository', 'repositories', 'db', 'database', 'entities', 'dao']
    for d in dirs:
        d_name = d.rstrip('/').split('/')[-1].lower()
        if d_name in data_patterns:
            guess.data.append(d)
    
    # Utils layer patterns
    utils_patterns = ['utils', 'util', 'helpers', 'helper', 'common', 'lib', 'libs']
    for d in dirs:
        d_name = d.rstrip('/').split('/')[-1].lower()
        if d_name in utils_patterns:
            guess.utils.append(d)
    
    # Config layer patterns
    config_patterns = ['config', 'settings', 'configuration', 'conf']
    for d in dirs:
        d_name = d.rstrip('/').split('/')[-1].lower()
        if d_name in config_patterns:
            guess.config.append(d)
    
    return guess


def infer_module_type(file_path: Path, root: Path) -> str:
    """
    Infer module type from file path and name.
    
    Enhanced to support Spring Framework annotations for Java projects.
    """
    parts = [p.lower() for p in file_path.parts[:-1]]
    name = file_path.stem.lower()
    ext = file_path.suffix.lower()
    
    # Read file content for annotation detection (Java files only)
    content = ""
    if ext == '.java':
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            pass
    
    # Check directory patterns first
    if 'test' in parts or 'tests' in parts or name.startswith('test_') or name.endswith('_test'):
        return 'test'
    
    if 'service' in parts or 'services' in parts:
        return 'service'
    
    if 'model' in parts or 'models' in parts or 'entity' in parts or 'entities' in parts:
        return 'model'
    
    if 'controller' in parts or 'controllers' in parts or 'api' in parts:
        return 'controller'
    
    if 'route' in parts or 'routes' in parts or 'api' in parts:
        return 'route'
    
    if 'repository' in parts or 'repositories' in parts or 'dao' in parts:
        return 'repository'
    
    if 'util' in parts or 'utils' in parts or 'helper' in parts:
        return 'utility'
    
    if 'config' in parts or 'settings' in parts:
        return 'config'
    
    # Check file name patterns
    if name.startswith('test_'):
        return 'test'
    
    if 'service' in name:
        return 'service'
    
    if 'model' in name:
        return 'model'
    
    if 'controller' in name:
        return 'controller'
    
    if 'route' in name or 'router' in name:
        return 'route'
    
    # Enhanced: Check Spring annotations for Java files
    if ext == '.java' and content:
        import re
        
        # REST Controller
        if re.search(r'@RestController', content):
            return 'controller'
        
        # MVC Controller
        if re.search(r'@Controller', content):
            return 'controller'
        
        # Service layer
        if re.search(r'@Service', content):
            return 'service'
        
        # Repository/Data Access
        if re.search(r'@Repository', content):
            return 'repository'
        
        # Component (generic)
        if re.search(r'@Component', content):
            return 'component'
        
        # Configuration class
        if re.search(r'@Configuration', content):
            return 'config'
        
        # Entity/Model
        if re.search(r'@Entity|@Table|@Embeddable', content):
            return 'model'
        
        # DTO/Record
        if re.search(r'@Data|@Value|@Builder|record\s+\w+\(', content):
            return 'model'
        
        # Application main class
        if re.search(r'@SpringBootApplication', content):
            return 'main'
    
    return 'unknown'


# ============================================================
# Kotlin Multiplatform Detection
# ============================================================

# KMP source set patterns
KMP_SOURCE_SETS = {
    'commonMain', 'commonTest',  # Common code
    'jvmMain', 'jvmTest',  # JVM target
    'jsMain', 'jsTest',  # JavaScript target
    'androidMain', 'androidTest',  # Android target
    'iosMain', 'iosTest',  # iOS (legacy)
    'iosX64Main', 'iosX64Test',  # iOS x86_64
    'iosArm64Main', 'iosArm64Test',  # iOS ARM64
    'macosX64Main', 'macosX64Test',  # macOS
    'macosArm64Main', 'macosArm64Test',  # macOS ARM
    'linuxX64Main', 'linuxX64Test',  # Linux
    'mingwX64Main', 'mingwX64Test',  # Windows
    'wasmMain', 'wasmTest',  # WebAssembly
}

def detect_kmp_targets(root: Path, all_files: List[Path]) -> Dict[str, Any]:
    """
    Detect Kotlin Multiplatform project targets.
    
    Returns dict with:
    - is_kmp: bool
    - targets: List[str]
    - source_sets: Dict[str, List[str]]
    """
    result = {
        'is_kmp': False,
        'targets': [],
        'source_sets': {},
    }
    
    # Check for build.gradle.kts with kotlin { ... } multiplatform block
    gradle_files = list(root.glob('**/build.gradle.kts')) + list(root.glob('**/build.gradle'))
    
    for gradle_file in gradle_files:
        try:
            content = gradle_file.read_text(encoding='utf-8', errors='replace')
            
            # Check for multiplatform plugin
            if 'kotlin("multiplatform")' in content or 'kotlin("multiplatform")' in content or 'kotlin("multiplatform")' in content:
                result['is_kmp'] = True
            
            # Check for explicit targets
            target_patterns = [
                (r'jvm\(\)', 'jvm'),
                (r'js\(.*\)', 'js'),
                (r'android\(\)', 'android'),
                (r'ios\(\)', 'ios'),
                (r'iosX64\(\)', 'ios'),
                (r'iosArm64\(\)', 'ios'),
                (r'macosX64\(\)', 'macos'),
                (r'macosArm64\(\)', 'macos'),
                (r'linuxX64\(\)', 'linux'),
                (r'mingwX64\(\)', 'windows'),
                (r'wasm\(\)', 'wasm'),
            ]
            
            import re
            for pattern, target in target_patterns:
                if re.search(pattern, content):
                    if target not in result['targets']:
                        result['targets'].append(target)
                        
        except Exception:
            continue
    
    # Detect source sets from directory structure
    for file_path in all_files:
        if file_path.suffix == '.kt':
            parts = file_path.parts
            for part in parts:
                if part in KMP_SOURCE_SETS:
                    result['is_kmp'] = True
                    if part not in result['source_sets']:
                        result['source_sets'][part] = []
                    result['source_sets'][part].append(str(file_path))
                    break
    
    # Infer targets from source sets
    for source_set in result['source_sets']:
        for target_hint, target_name in [
            ('jvm', 'jvm'), ('js', 'js'), ('android', 'android'),
            ('ios', 'ios'), ('macos', 'macos'), ('linux', 'linux'),
            ('mingw', 'windows'), ('wasm', 'wasm'),
        ]:
            if target_hint in source_set and target_name not in result['targets']:
                result['targets'].append(target_name)
    
    return result


# ============================================================
# Step 3: Risk Profile Detection
# ============================================================

def detect_risk_profile(
    root: Path,
    modules: List[ModuleInfo],
    dependency_graph: Dict[str, List[str]],
    test_files: List[str],
) -> RiskProfile:
    """
    Detect engineering risks.
    
    Checks for:
    - Large files (>500 lines)
    - High coupling modules (>10 imports)
    - Circular dependencies
    - Unsafe code patterns
    - Missing tests
    """
    profile = RiskProfile()
    
    # Large files
    for module in modules:
        if module.lines > LARGE_FILE_THRESHOLD:
            profile.large_files.append(module.path)
    
    # High coupling
    coupling = calculate_coupling(dependency_graph)
    for module_name, score in coupling.items():
        if score >= HIGH_COUPLING_THRESHOLD:
            # Find module path
            for m in modules:
                if m.name == module_name:
                    profile.high_coupling_modules.append(m.path)
                    break
    
    # Circular dependencies
    cycles = detect_circular_dependencies(dependency_graph)
    if cycles:
        profile.circular_dependencies_detected = True
        profile.circular_dependencies = cycles
    
    # Unsafe patterns - scan source files
    for module in modules:
        try:
            file_path = root / module.path
            content = file_path.read_text(encoding='utf-8', errors='replace')
            
            for pattern, description in UNSAFE_PATTERNS.items():
                if pattern.lower() in content.lower():
                    profile.unsafe_patterns.append(f"{module.path}: {description}")
        except Exception:
            pass
    
    # Missing tests - modules without corresponding tests
    tested_names = set()
    for test_file in test_files:
        # Extract base name from test file
        name = Path(test_file).stem.lower()
        if name.startswith('test_'):
            name = name[5:]  # Remove test_ prefix
        elif name.endswith('_test'):
            name = name[:-5]  # Remove _test suffix
        tested_names.add(name)
    
    for module in modules:
        if module.type != 'test':
            base_name = Path(module.path).stem.lower()
            # Check if any tested name matches
            has_test = any(
                tested in base_name or base_name in tested
                for tested in tested_names
            )
            if not has_test:
                profile.missing_tests.append(module.path)
    
    # Calculate overall risk score (0-100) using normalized percentages
    # Each category contributes max 25 points, total 100 points
    total_modules = len([m for m in modules if m.type != 'test'])
    
    # 1. Safety issues (eval/exec) - max 25 points
    safety_ratio = len(profile.unsafe_patterns) / max(total_modules, 1)
    safety_score = min(25.0, safety_ratio * 100 * 0.5)  # 50% unsafe code → 25 points
    
    # 2. Architecture issues (circular deps) - max 25 points
    arch_ratio = len(profile.circular_dependencies) / max(total_modules, 1)
    arch_score = min(25.0, arch_ratio * 100 * 0.3)  # 30% circular deps → 25 points
    
    # 3. Coupling issues - max 25 points
    coupling_ratio = len(profile.high_coupling_modules) / max(total_modules, 1)
    coupling_score = min(25.0, coupling_ratio * 100 * 0.4)  # 40% high coupling → 25 points
    
    # 4. Maintainability issues (large files + missing tests) - max 25 points
    maint_count = len(profile.large_files) + len(profile.missing_tests)
    maint_ratio = maint_count / max(total_modules * 2, 1)
    maint_score = min(25.0, maint_ratio * 100 * 0.3)  # 30% maintainability issues → 25 points
    
    # Sum up and round to integer
    profile.risk_score = int(round(safety_score + arch_score + coupling_score + maint_score))
    
    return profile


# ============================================================
# Main API: analyze()
# ============================================================

def _should_skip_module(path: str, name: str) -> bool:
    """
    Check if a module should be skipped from analysis.
    
    Skip patterns:
    - Build artifacts (CMakeCompilerId, etc.)
    - Generated files
    - Third-party libraries in source tree
    """
    skip_patterns = [
        'CMakeCXXCompilerId',  # CMake generated
        'CMakeCCompilerId',    # CMake generated
        'cmake_install.cmake',
        'CTestTestfile.cmake',
    ]
    
    # Skip known generated/build artifact modules
    for pattern in skip_patterns:
        if pattern in name or pattern in path:
            return True
    
    # Skip if path contains build directories
    build_dir_patterns = ['cmake-build-', 'cmake_build/', 'build/', 'out/', 'bin/']
    for pattern in build_dir_patterns:
        if pattern in path:
            return True
    
    return False


def analyze(workspace_path: str) -> ProjectModel:
    """
    Analyze a project and return a structured ProjectModel.
    
    This is the main entry point for Project Intelligence.
    
    Args:
        workspace_path: Path to the project root directory
    
    Returns:
        ProjectModel containing:
        - meta: Project metadata (language, file count, size)
        - structure: Directory tree and architecture layers
        - modules: List of module info with imports/exports
        - entry_points: Detected entry points
        - tests: Test structure and framework
        - dependencies: External dependencies and internal graph
        - framework: Detected frameworks (web, ORM, etc.)
        - build: Build system info
        - risk: Engineering risk profile
    
    Example:
        >>> model = analyze("/path/to/project")
        >>> print(model.to_json())
        >>> print(model.risk.risk_score)
    """
    start_time = time.time()
    
    root = Path(workspace_path).resolve()
    model = ProjectModel()
    
    # ========================================================
    # Step 1: Static File Scan
    # ========================================================
    
    all_files, file_count_by_ext, total_size = scan_files(root)
    
    # Detect primary language
    lang_scores = {
        'python': file_count_by_ext.get('.py', 0),
        'javascript': file_count_by_ext.get('.js', 0) + file_count_by_ext.get('.jsx', 0),
        'typescript': file_count_by_ext.get('.ts', 0) + file_count_by_ext.get('.tsx', 0),
        'go': file_count_by_ext.get('.go', 0),
        'rust': file_count_by_ext.get('.rs', 0),
        'java': file_count_by_ext.get('.java', 0),
        'kotlin': file_count_by_ext.get('.kt', 0) + file_count_by_ext.get('.kts', 0),
        'cpp': file_count_by_ext.get('.cpp', 0) + file_count_by_ext.get('.cc', 0) + file_count_by_ext.get('.cxx', 0),
        'c': file_count_by_ext.get('.c', 0) + file_count_by_ext.get('.h', 0) + file_count_by_ext.get('.hpp', 0),
    }
    
    primary_language = max(lang_scores.items(), key=lambda x: x[1])[0] if lang_scores else 'unknown'
    if lang_scores[primary_language] == 0:
        primary_language = 'unknown'
    
    detected_languages = [lang for lang, count in lang_scores.items() if count > 0]
    
    # Build Meta
    model.meta = ProjectMeta(
        language=primary_language,
        languages_detected=detected_languages,
        repo_root=str(root),
        file_count=len(all_files),
        size_kb=total_size // 1024,
        monorepo=False,  # TODO: detect monorepo
    )
    
    # ========================================================
    # Step 2: Structure Analysis
    # ========================================================
    
    tree = build_directory_tree(root)
    
    # Count directories and max depth
    dir_count = 0
    max_depth = 0
    
    def count_dirs(nodes: List[DirectoryNode], depth: int):
        nonlocal dir_count, max_depth
        for node in nodes:
            if node.type == "directory":
                dir_count += 1
                max_depth = max(max_depth, depth)
                count_dirs(node.children, depth + 1)
    
    count_dirs(tree, 1)
    
    layered_guess = infer_architecture_layers(root)
    
    model.structure = ProjectStructure(
        tree=tree,
        layered_guess=layered_guess,
        directory_count=dir_count,
        max_depth=max_depth,
    )
    
    # ========================================================
    # Step 3: Module Analysis
    # ========================================================
    
    modules: List[ModuleInfo] = []
    module_imports: Dict[str, List[str]] = {}  # module_name -> imports
    project_module_names: Set[str] = set()
    
    # Collect all module names first
    for file_path in all_files:
        ext = file_path.suffix.lower()
        if ext in ('.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.kt', '.kts', '.cpp', '.cc', '.cxx', '.c', '.h', '.hpp'):
            module_name = file_path.stem
            project_module_names.add(module_name)
    
    # Analyze each source file
    seen_paths = set()  # Track unique paths to avoid duplicates
    
    for file_path in all_files:
        ext = file_path.suffix.lower()
        if ext not in ('.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.kt', '.kts', '.cpp', '.cc', '.cxx', '.c', '.h', '.hpp'):
            continue
        
        rel_path = str(file_path.relative_to(root))
        
        # Skip if already processed (shouldn't happen, but safety check)
        if rel_path in seen_paths:
            continue
        
        # Skip build artifacts and generated files
        if _should_skip_module(rel_path, file_path.stem):
            continue
        
        seen_paths.add(rel_path)
        
        language, imports = extract_imports_from_file(file_path)
        exports = []
        
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
            exports = extract_exports(content, language)
            line_count = len(content.splitlines())
        except Exception:
            line_count = 0
        
        module_name = file_path.stem
        
        module = ModuleInfo(
            name=module_name,
            path=rel_path,
            type=infer_module_type(file_path, root),
            exports=exports,
            imports=imports,
            lines=line_count,
        )
        
        modules.append(module)
        module_imports[module_name] = imports
    
    model.modules = modules
    
    # Build internal dependency graph
    internal_graph = build_internal_dependency_graph(module_imports, project_module_names)
    model.dependencies.internal_graph = internal_graph
    
    # ========================================================
    # Step 4: Indexing (Entry Points, Tests, Frameworks, Build)
    # ========================================================
    
    # Group files by extension
    files_by_ext: Dict[str, List[Path]] = {}
    for f in all_files:
        ext = f.suffix.lower()
        if ext not in files_by_ext:
            files_by_ext[ext] = []
        files_by_ext[ext].append(f)
    
    # Entry points
    model.entry_points = detect_entry_points(root, primary_language, files_by_ext)
    
    # Tests
    model.tests = detect_tests(root, primary_language, all_files)
    
    # Package manager
    pkg_manager, req_files = detect_package_manager(root, primary_language)
    model.dependencies.package_manager = pkg_manager
    model.dependencies.requirements_files = req_files
    
    # Frameworks
    model.framework = detect_frameworks(root, primary_language, all_files, req_files)
    
    # Kotlin Multiplatform detection
    if primary_language == 'kotlin' or 'kotlin' in model.meta.languages_detected:
        kmp_info = detect_kmp_targets(root, all_files)
        if kmp_info['is_kmp']:
            model.framework.is_kmp = True
            model.framework.kmp_targets = kmp_info['targets']
            model.framework.kmp_source_sets = list(kmp_info['source_sets'].keys())
    
    # Build system
    model.build = detect_build_system(root, primary_language)
    
    # Collect external libs from imports
    external_libs = set()
    for module in modules:
        for imp in module.imports:
            if imp not in project_module_names:
                external_libs.add(imp)
    model.dependencies.external_libs = list(external_libs)[:50]  # Limit to 50
    
    # ========================================================
    # Step 5: Risk Profile
    # ========================================================
    
    test_files = model.tests.test_files
    model.risk = detect_risk_profile(root, modules, internal_graph, test_files)
    
    # ========================================================
    # Finalize
    # ========================================================
    
    model.analysis_time_ms = int((time.time() - start_time) * 1000)
    
    return model


# ============================================================
# Convenience exports
# ============================================================

__all__ = [
    'analyze',
    'ProjectModel',
    'ProjectMeta',
    'ProjectStructure',
    'ModuleInfo',
    'EntryPoint',
    'TestInfo',
    'DependencyInfo',
    'FrameworkInfo',
    'BuildInfo',
    'RiskProfile',
]
