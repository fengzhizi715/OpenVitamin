"""
Dependency Graph - Lightweight Import Scanning.

This module provides regex-based import extraction for multiple languages.
No AST parsing - keeps complexity low while providing useful dependency information.

Supported languages:
- Python: import / from ... import
- JavaScript/TypeScript: require / import
- Go: import blocks
- Rust: use statements
- Java: import statements
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ============================================================
# Language-specific import patterns
# ============================================================

# Python: import X, from X import Y
PYTHON_IMPORT_PATTERNS = [
    re.compile(r'^\s*import\s+([a-zA-Z_][a-zA-Z0-9_.]*)', re.MULTILINE),
    re.compile(r'^\s*from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+import', re.MULTILINE),
]

# JavaScript/TypeScript: require('X'), import X from 'Y'
JS_IMPORT_PATTERNS = [
    re.compile(r'''require\s*\(\s*['"]([^'"]+)['"]\s*\)'''),
    re.compile(r'''import\s+[^'"]*\s+from\s+['"]([^'"]+)['"]'''),
    re.compile(r'''import\s+['"]([^'"]+)['"]'''),
]

# Go: import "X", import ( "X" "Y" )
GO_IMPORT_PATTERNS = [
    re.compile(r'''import\s+["']([^"']+)["']'''),
    re.compile(r'import\s*\(([^)]+)\)', re.DOTALL),  # Multi-line imports
]

# Rust: use X::Y
RUST_IMPORT_PATTERNS = [
    re.compile(r'^\s*use\s+([a-zA-Z_][a-zA-Z0-9_:]*)', re.MULTILINE),
]

# Java: import X.Y.Z
JAVA_IMPORT_PATTERNS = [
    re.compile(r'^\s*import\s+([a-zA-Z_][a-zA-Z0-9_.]*)', re.MULTILINE),
]

# Kotlin: import X, import X.Y
# Kotlin also supports: import X as Y, import X.*
KOTLIN_IMPORT_PATTERNS = [
    re.compile(r'^\s*import\s+([a-zA-Z_][a-zA-Z0-9_.]*)', re.MULTILINE),
]

# C/C++: #include <file> and #include "file"
CPP_INCLUDE_PATTERNS = [
    re.compile(r'^\s*#include\s*["<]([a-zA-Z0-9_./\\-]+)[">]', re.MULTILINE),
    re.compile(r'^\s*#include\s*<([a-zA-Z0-9_./\\-]+)>', re.MULTILINE),
]


# ============================================================
# Language detection by extension
# ============================================================

LANGUAGE_EXTENSIONS = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.kt': 'kotlin',
    '.kts': 'kotlin',  # Kotlin script
    '.cpp': 'cpp',
    '.cc': 'cpp',
    '.cxx': 'cpp',
    '.c': 'c',
    '.h': 'c_header',
    '.hpp': 'cpp_header',
}


def get_language_from_extension(ext: str) -> str:
    """Get language from file extension."""
    return LANGUAGE_EXTENSIONS.get(ext.lower(), 'unknown')


# ============================================================
# Import extraction functions
# ============================================================

def extract_python_imports(content: str) -> List[str]:
    """
    Extract Python imports using regex.
    
    Handles:
    - import X
    - import X.Y
    - from X import Y
    - from X.Y import Z
    """
    imports = set()
    
    for pattern in PYTHON_IMPORT_PATTERNS:
        matches = pattern.findall(content)
        for match in matches:
            # Normalize: take first part for "from X.Y" -> "X"
            module = match.split('.')[0] if '.' in match else match
            imports.add(module)
    
    return list(imports)


def extract_js_imports(content: str) -> List[str]:
    """
    Extract JavaScript/TypeScript imports.
    
    Handles:
    - require('X')
    - import X from 'Y'
    - import 'X'
    """
    imports = set()
    
    for pattern in JS_IMPORT_PATTERNS:
        matches = pattern.findall(content)
        for match in matches:
            # Skip relative imports (./ or ../) for external lib detection
            if not match.startswith('.') and not match.startswith('/'):
                # Normalize: take package name (first part before /)
                pkg = match.split('/')[0] if '/' in match else match
                imports.add(pkg)
    
    return list(imports)


def extract_go_imports(content: str) -> List[str]:
    """
    Extract Go imports.
    
    Handles:
    - import "X"
    - import ( "X" "Y" )
    """
    imports = set()
    
    # Single imports
    for pattern in GO_IMPORT_PATTERNS[:1]:
        matches = pattern.findall(content)
        imports.update(matches)
    
    # Multi-line imports
    multi_match = GO_IMPORT_PATTERNS[1].search(content)
    if multi_match:
        block = multi_match.group(1)
        # Extract quoted strings from block
        quoted = re.findall(r'["\']([^"\']+)["\']', block)
        imports.update(quoted)
    
    # Normalize: extract package name from full path
    normalized = set()
    for imp in imports:
        # github.com/user/pkg -> pkg
        parts = imp.split('/')
        if parts:
            normalized.add(parts[-1])
    
    return list(normalized)


def extract_rust_imports(content: str) -> List[str]:
    """
    Extract Rust use statements.
    
    Handles:
    - use std::collections::HashMap
    - use crate::module
    """
    imports = set()
    
    for pattern in RUST_IMPORT_PATTERNS:
        matches = pattern.findall(content)
        for match in matches:
            # Normalize: take first part (std, crate, or module name)
            parts = match.split('::')
            if parts:
                imports.add(parts[0])
    
    return list(imports)


def extract_java_imports(content: str) -> List[str]:
    """
    Extract Java imports.
    
    Handles:
    - import java.util.List
    - import com.example.*
    """
    imports = set()
    
    for pattern in JAVA_IMPORT_PATTERNS:
        matches = pattern.findall(content)
        for match in matches:
            # Normalize: take package name (first 2 parts)
            parts = match.split('.')
            if len(parts) >= 2:
                imports.add('.'.join(parts[:2]))
            else:
                imports.add(parts[0])
    
    return list(imports)


def extract_kotlin_imports(content: str) -> List[str]:
    """
    Extract Kotlin imports.
    
    Handles:
    - import kotlin.collections.*
    - import com.example.package.Class
    - import com.example.package as alias
    """
    imports = set()
    
    for pattern in KOTLIN_IMPORT_PATTERNS:
        matches = pattern.findall(content)
        for match in matches:
            # Remove 'as alias' part if present
            match = match.split()[0] if ' ' in match else match
            # Remove trailing .* 
            match = match.rstrip('.*')
            # Normalize: take package name (first 2 parts)
            parts = match.split('.')
            if len(parts) >= 2:
                imports.add('.'.join(parts[:2]))
            elif parts[0]:
                imports.add(parts[0])
    
    return list(imports)


def extract_cpp_imports(content: str) -> List[str]:
    """
    Extract C/C++ includes.
    
    Handles:
    - #include <iostream>
    - #include "myheader.h"
    - #include <path/to/header.hpp>
    
    Returns normalized module names (e.g., 'iostream', 'myheader', 'path.to.header')
    """
    imports = set()
    
    for pattern in CPP_INCLUDE_PATTERNS:
        matches = pattern.findall(content)
        for match in matches:
            # Remove file extension
            match = re.sub(r'\.(h|hpp|hxx|hh)$', '', match)
            # Convert path separators to dots for normalization
            # e.g., 'path/to/header' -> 'path.to.header'
            normalized = match.replace('/', '.').replace('\\', '.')
            # Get the base name (last component) or full path
            parts = normalized.split('.')
            if len(parts) > 1:
                # Keep first 2 parts for libraries like 'boost.system'
                imports.add('.'.join(parts[:2]))
            else:
                imports.add(parts[0])
    
    return list(imports)


# ============================================================
# CMakeLists.txt Parsing
# ============================================================

def parse_cmake_file(content: str) -> Dict[str, Any]:
    """
    Parse CMakeLists.txt to extract:
    - Project name
    - Target executables
    - Target libraries
    - Dependencies (find_package, target_link_libraries)
    - Include directories
    - Source files
    """
    result = {
        'project_name': None,
        'cmake_minimum_version': None,
        'executables': [],
        'libraries': [],
        'dependencies': [],  # from find_package
        'link_libraries': [],  # from target_link_libraries
        'include_dirs': [],
        'source_files': [],
    }
    
    lines = content.split('\n')
    
    # Project name
    match = re.search(r'^\s*project\s*\(\s*([a-zA-Z0-9_]+)', content, re.MULTILINE)
    if match:
        result['project_name'] = match.group(1)
    
    # CMake minimum version
    match = re.search(r'^\s*cmake_minimum_required\s*\(\s*VERSION\s+([0-9.]+)', content, re.MULTILINE)
    if match:
        result['cmake_minimum_version'] = match.group(1)
    
    # Find packages (dependencies)
    find_package_pattern = re.compile(r'^\s*find_package\s*\(\s*([a-zA-Z0-9_]+)', re.MULTILINE)
    for match in find_package_pattern.finditer(content):
        pkg = match.group(1)
        if pkg not in result['dependencies']:
            result['dependencies'].append(pkg)
    
    # Add_subdirectory
    add_subdir_pattern = re.compile(r'^\s*add_subdirectory\s*\(\s*([a-zA-Z0-9_/.-]+)', re.MULTILINE)
    for match in add_subdir_pattern.finditer(content):
        result['dependencies'].append(match.group(1))
    
    # Executables
    add_executable_pattern = re.compile(r'^\s*add_executable\s*\(\s*([a-zA-Z0-9_]+)', re.MULTILINE)
    for match in add_executable_pattern.finditer(content):
        result['executables'].append(match.group(1))
    
    # Libraries (static/shared)
    add_library_pattern = re.compile(r'^\s*add_library\s*\(\s*([a-zA-Z0-9_]+)', re.MULTILINE)
    for match in add_library_pattern.finditer(content):
        lib = match.group(1)
        if lib not in ['${', 'SHARED', 'STATIC', 'OBJECT', 'MODULE']:  # Skip keywords
            result['libraries'].append(lib)
    
    # Target link libraries
    link_lib_pattern = re.compile(r'^\s*target_link_libraries\s*\(\s*([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_${}]+)', re.MULTILINE)
    for match in link_lib_pattern.finditer(content):
        lib = match.group(2).strip()
        if lib not in result['link_libraries']:
            result['link_libraries'].append(lib)
    
    # Include directories
    include_dir_pattern = re.compile(r'^\s*include_directories\s*\(\s*([^")]+)', re.MULTILINE)
    for match in include_dir_pattern.finditer(content):
        dirs = match.group(1).replace('\\n', ' ').split()
        for d in dirs:
            d = d.strip().strip('"').strip()
            if d and d not in ['PUBLIC', 'PRIVATE', 'INTERFACE']:
                if d not in result['include_dirs']:
                    result['include_dirs'].append(d)
    
    # target_include_directories
    target_include_pattern = re.compile(r'^\s*target_include_directories\s*\([^)]+INTERFACE\s+([^)]+)\)', re.MULTILINE)
    for match in target_include_pattern.finditer(content):
        dirs = match.group(1).replace('\\n', ' ').split()
        for d in dirs:
            d = d.strip().strip('"').strip()
            if d and d not in ['PUBLIC', 'PRIVATE', 'INTERFACE']:
                if d not in result['include_dirs']:
                    result['include_dirs'].append(d)
    
    return result


# ============================================================
# Generic extraction dispatcher
# ============================================================

def extract_imports(content: str, language: str) -> List[str]:
    """
    Extract imports based on language.
    
    Args:
        content: File content
        language: Language identifier (python, javascript, etc.)
    
    Returns:
        List of imported module/package names
    """
    extractors = {
        'python': extract_python_imports,
        'javascript': extract_js_imports,
        'typescript': extract_js_imports,
        'go': extract_go_imports,
        'rust': extract_rust_imports,
        'java': extract_java_imports,
        'kotlin': extract_kotlin_imports,
        'cpp': extract_cpp_imports,
        'c': extract_cpp_imports,
        'c_header': extract_cpp_imports,
        'cpp_header': extract_cpp_imports,
    }
    
    extractor = extractors.get(language)
    if not extractor:
        return []
    
    try:
        return extractor(content)
    except Exception:
        return []


def extract_imports_from_file(file_path: Path) -> Tuple[str, List[str]]:
    """
    Extract imports from a file.
    
    Args:
        file_path: Path to the file
    
    Returns:
        Tuple of (language, imports_list)
    """
    ext = file_path.suffix.lower()
    language = get_language_from_extension(ext)
    
    try:
        content = file_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return language, []
    
    imports = extract_imports(content, language)
    return language, imports


# ============================================================
# Dependency graph building
# ============================================================

def build_internal_dependency_graph(
    modules: Dict[str, List[str]],  # module_name -> imports
    project_modules: Set[str],  # known project module names
) -> Dict[str, List[str]]:
    """
    Build internal dependency graph.
    
    Filters imports to only include internal project modules.
    
    Args:
        modules: Dict mapping module name to its imports
        project_modules: Set of known project module names
    
    Returns:
        Dict mapping module name to its internal dependencies
    """
    graph = {}
    
    for module_name, imports in modules.items():
        internal_deps = []
        for imp in imports:
            # Check if import matches a project module
            if imp in project_modules:
                internal_deps.append(imp)
            else:
                # Check partial match (e.g., "app.models" matches "models")
                for pm in project_modules:
                    if imp.endswith(pm) or pm.endswith(imp) or f".{pm}" in imp:
                        internal_deps.append(pm)
                        break
        
        graph[module_name] = list(set(internal_deps))
    
    return graph


def detect_circular_dependencies(graph: Dict[str, List[str]]) -> List[List[str]]:
    """
    Detect circular dependencies using DFS.
    
    Args:
        graph: Dependency graph (module -> dependencies)
    
    Returns:
        List of circular dependency chains found
    """
    cycles = []
    visited = set()
    rec_stack = set()
    path = []
    
    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
                return True
        
        path.pop()
        rec_stack.remove(node)
        return False
    
    for node in graph:
        if node not in visited:
            dfs(node)
    
    return cycles


def calculate_coupling(graph: Dict[str, List[str]]) -> Dict[str, int]:
    """
    Calculate coupling score for each module.
    
    Higher score = more coupled (higher risk).
    
    Args:
        graph: Dependency graph
    
    Returns:
        Dict mapping module name to coupling score
    """
    coupling = {}
    
    for module, deps in graph.items():
        # Outgoing coupling (fan-out)
        fan_out = len(deps)
        
        # Incoming coupling (fan-in)
        fan_in = sum(1 for m, d in graph.items() if module in d)
        
        coupling[module] = fan_out + fan_in
    
    return coupling


# ============================================================
# Export detection (lightweight)
# ============================================================

def extract_python_exports(content: str) -> List[str]:
    """
    Extract Python exports (top-level functions and classes).
    
    Uses regex for simplicity - no AST parsing.
    """
    exports = []
    
    # Functions: def name(
    func_pattern = re.compile(r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', re.MULTILINE)
    exports.extend(func_pattern.findall(content))
    
    # Classes: class Name:
    class_pattern = re.compile(r'^class\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    exports.extend(class_pattern.findall(content))
    
    return exports


def extract_js_exports(content: str) -> List[str]:
    """
    Extract JavaScript/TypeScript exports.
    """
    exports = []
    
    # export function name, export const name, etc.
    patterns = [
        re.compile(r'export\s+(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)'),
        re.compile(r'export\s+const\s+([a-zA-Z_][a-zA-Z0-9_]*)'),
        re.compile(r'export\s+class\s+([a-zA-Z_][a-zA-Z0-9_]*)'),
        re.compile(r'export\s+\{([^}]+)\}'),
    ]
    
    for pattern in patterns:
        matches = pattern.findall(content)
        for match in matches:
            if '{' in str(match):
                # Handle export { a, b, c }
                names = [n.strip() for n in match.split(',')]
                exports.extend(names)
            else:
                exports.append(match)
    
    return exports


def extract_kotlin_exports(content: str) -> List[str]:
    """
    Extract Kotlin exports (public classes, functions, objects).
    
    Uses regex for simplicity - no AST parsing.
    """
    exports = []
    
    # Classes: class Name (including data class, sealed class, etc.)
    class_pattern = re.compile(r'(?:^|\n)(?:(?:public|internal|private|protected)\s+)?(?:data\s+|sealed\s+|open\s+|abstract\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    exports.extend(class_pattern.findall(content))
    
    # Functions: fun name( (including top-level functions)
    func_pattern = re.compile(r'(?:^|\n)(?:(?:public|internal|private|protected)\s+)?(?:suspend\s+)?fun\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[<(]', re.MULTILINE)
    exports.extend(func_pattern.findall(content))
    
    # Objects: object Name (including companion objects)
    object_pattern = re.compile(r'(?:^|\n)(?:(?:public|internal|private|protected)\s+)?object\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    exports.extend(object_pattern.findall(content))
    
    # Interfaces: interface Name
    interface_pattern = re.compile(r'(?:^|\n)(?:(?:public|internal|private|protected)\s+)?interface\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    exports.extend(interface_pattern.findall(content))
    
    return list(set(exports))  # Deduplicate


def extract_java_exports(content: str) -> List[str]:
    """
    Extract Java exports (classes, interfaces, enums, methods, fields).
    
    Handles:
    - public class ClassName
    - public interface InterfaceName
    - public enum EnumName
    - public static void methodName()
    - public field declarations
    - Spring annotations (@RestController, @Service, etc.)
    """
    exports = []
    
    # Classes: public class ClassName [extends X] [implements Y]
    class_pattern = re.compile(
        r'(?:^|\n)\s*(?:public\s+)?(?:abstract\s+)?(?:final\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        re.MULTILINE
    )
    exports.extend(class_pattern.findall(content))
    
    # Interfaces: public interface InterfaceName
    interface_pattern = re.compile(
        r'(?:^|\n)\s*(?:public\s+)?interface\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        re.MULTILINE
    )
    exports.extend(interface_pattern.findall(content))
    
    # Enums: public enum EnumName
    enum_pattern = re.compile(
        r'(?:^|\n)\s*(?:public\s+)?enum\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        re.MULTILINE
    )
    exports.extend(enum_pattern.findall(content))
    
    # Records (Java 14+): public record RecordName()
    record_pattern = re.compile(
        r'(?:^|\n)\s*(?:public\s+)?record\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
        re.MULTILINE
    )
    exports.extend(record_pattern.findall(content))
    
    # Methods: public returnType methodName( params )
    method_pattern = re.compile(
        r'(?:^|\n)\s*(?:public\s+)?(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?(?:[\w<>\[\],\s]+\s+)([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*[\{;]',
        re.MULTILINE
    )
    method_matches = method_pattern.findall(content)
    # Filter out keywords and common non-method names
    keywords = {'if', 'else', 'for', 'while', 'switch', 'catch', 'try', 'return', 'new', 'throw'}
    exports.extend([m for m in method_matches if m not in keywords])
    
    # Fields: public Type fieldName;
    field_pattern = re.compile(
        r'(?:^|\n)\s*(?:public\s+)?(?:static\s+)?(?:final\s+)?(?:[\w<>\[\],\s]+\s+)([a-zA-Z_][a-zA-Z0-9_]*)\s*;',
        re.MULTILINE
    )
    exports.extend(field_pattern.findall(content))
    
    return list(set(exports))  # Deduplicate


def extract_cpp_exports(content: str) -> List[str]:
    """
    Extract C/C++ exports (classes, functions, structs).
    
    Uses regex for simplicity - no AST parsing.
    """
    exports = []
    
    # Classes: class Name { ... }
    class_pattern = re.compile(r'(?:^|\n)\s*(?:template\s*<[^>]*>\s*)?class\s+(?:__declspec\([^)]*\)\s+)?(?:\w+\s+)?([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    exports.extend(class_pattern.findall(content))
    
    # Structs: struct Name { ... }
    struct_pattern = re.compile(r'(?:^|\n)\s*struct\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    exports.extend(struct_pattern.findall(content))
    
    # Functions: ReturnType functionName( ... )
    # Note: This is simplified, may capture some non-exports
    func_pattern = re.compile(r'(?:^|\n)\s*(?:inline\s+)?(?:static\s+)?(?:virtual\s+)?(?:const\s+)?(?:\w+\*?)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*(?:const)?\s*\{', re.MULTILINE)
    exports.extend(func_pattern.findall(content))
    
    # Namespaces (often used as module boundaries)
    ns_pattern = re.compile(r'(?:^|\n)\s*namespace\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    exports.extend(ns_pattern.findall(content))
    
    # Typedef
    typedef_pattern = re.compile(r'(?:^|\n)\s*typedef\s+(?:struct|class)?\s*[a-zA-Z_][a-zA-Z0-9_]*\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    exports.extend(typedef_pattern.findall(content))
    
    return list(set(exports))  # Deduplicate


def extract_exports(content: str, language: str) -> List[str]:
    """
    Extract exports based on language.
    """
    extractors = {
        'python': extract_python_exports,
        'javascript': extract_js_exports,
        'typescript': extract_js_exports,
        'kotlin': extract_kotlin_exports,
        'java': extract_java_exports,  # Use proper Java extractor
        'cpp': extract_cpp_exports,
        'c': extract_cpp_exports,
        'c_header': extract_cpp_exports,
        'cpp_header': extract_cpp_exports,
    }
    
    extractor = extractors.get(language)
    if not extractor:
        return []
    
    try:
        return extractor(content)
    except Exception:
        return []
