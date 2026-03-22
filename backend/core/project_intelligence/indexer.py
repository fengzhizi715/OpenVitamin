"""
Indexer - Entry Points, Tests, Framework Detection.

This module provides detection logic for:
- Project entry points (main.py, app.py, index.js, etc.)
- Test frameworks and test files
- Web frameworks, ORMs, and other libraries
- Build systems and CI/CD
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .model import (
    EntryPoint,
    EntryPointType,
    TestInfo,
    FrameworkInfo,
    BuildInfo,
)


# ============================================================
# Entry Point Detection
# ============================================================

# Common entry point files by language
ENTRY_POINT_FILES = {
    'python': ['main.py', 'app.py', 'run.py', 'server.py', 'wsgi.py', 'asgi.py', '__main__.py'],
    'javascript': ['index.js', 'main.js', 'app.js', 'server.js', 'start.js'],
    'typescript': ['index.ts', 'main.ts', 'app.ts', 'server.ts'],
    'go': ['main.go', 'cmd/main.go'],
    'rust': ['src/main.rs', 'main.rs'],
    'java': ['Main.java', 'Application.java', 'App.java'],
    'kotlin': ['Main.kt', 'App.kt', 'Application.kt', 'main.kt'],
}

# Entry point content patterns
ENTRY_POINT_PATTERNS = {
    'python': [
        (r'if\s+__name__\s*==\s*["\']__main__["\']', 'script'),
        (r'app\s*=\s*(?:FastAPI|Flask|Starlette|aiohttp)', 'http_server'),
        (r'uvicorn\.run', 'http_server'),
        (r'@\s*app\.(?:get|post|route)', 'http_server'),
        (r'fire\.\s*Fire', 'cli'),
        (r'argparse\.', 'cli'),
        (r'click\.', 'cli'),
    ],
    'javascript': [
        (r'express\(\)', 'http_server'),
        (r'fastify\(\)', 'http_server'),
        (r'koa\(\)', 'http_server'),
        (r'listen\s*\(', 'http_server'),
        (r'commander', 'cli'),
        (r'yargs', 'cli'),
    ],
    'typescript': [
        (r'express\(\)', 'http_server'),
        (r'fastify\(\)', 'http_server'),
        (r'nest\s*\(', 'http_server'),
        (r'listen\s*\(', 'http_server'),
    ],
    'go': [
        (r'func\s+main\s*\(\)', 'script'),
        (r'http\.ListenAndServe', 'http_server'),
        (r'gin\.Run', 'http_server'),
    ],
    'rust': [
        (r'fn\s+main\s*\(\)', 'script'),
        (r'actix_web::', 'http_server'),
        (r'rocket::', 'http_server'),
    ],
    'java': [
        (r'public\s+static\s+void\s+main', 'script'),
        (r'@SpringBootApplication', 'http_server'),
        (r'SpringApplication\.run', 'http_server'),
    ],
    'kotlin': [
        (r'fun\s+main\s*\(', 'script'),
        (r'Application\s*\(\)', 'http_server'),  # Ktor Application
        (r'embeddedServer', 'http_server'),  # Ktor embedded server
        (r'DefaultHeaders', 'http_server'),  # Ktor feature
        (r'@SpringBootApplication', 'http_server'),  # Spring Boot with Kotlin
    ],
    'cpp': [
        (r'int\s+main\s*\(', 'script'),
        (r'void\s+main\s*\(', 'script'),
        (r'#include\s*<iostream>', 'script'),
    ],
    'c': [
        (r'int\s+main\s*\(', 'script'),
        (r'void\s+main\s*\(', 'script'),
    ],
}


def detect_entry_points(
    root: Path,
    language: str,
    files_by_ext: Dict[str, List[Path]],
) -> List[EntryPoint]:
    """
    Detect project entry points.
    
    Strategy:
    1. Check common entry point file names
    2. Scan file content for entry point patterns
    """
    entry_points = []
    
    # Get candidate files
    candidates = set()
    
    # Check common entry point files
    entry_names = ENTRY_POINT_FILES.get(language, [])
    for name in entry_names:
        for f in root.rglob(name):
            candidates.add(f)
    
    # Also check top-level source files
    ext_map = {
        'python': '.py',
        'javascript': '.js',
        'typescript': '.ts',
        'go': '.go',
        'rust': '.rs',
        'java': '.java',
        'kotlin': '.kt',
        'cpp': '.cpp',
        'c': '.c',
    }
    ext = ext_map.get(language)
    if ext:
        for f in root.glob(f'*{ext}'):
            candidates.add(f)
    
    # Scan candidates for entry point patterns
    patterns = ENTRY_POINT_PATTERNS.get(language, [])
    
    for file_path in candidates:
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        
        rel_path = str(file_path.relative_to(root))
        
        # Check patterns
        for pattern, ep_type in patterns:
            if re.search(pattern, content):
                # Detect framework
                framework = detect_framework_from_content(content, language)
                
                entry_points.append(EntryPoint(
                    file=rel_path,
                    type=ep_type,
                    framework=framework,
                ))
                break  # Only add once per file
    
    return entry_points


def detect_framework_from_content(content: str, language: str) -> Optional[str]:
    """Detect framework from file content."""
    framework_patterns = {
        'python': [
            (r'FastAPI', 'fastapi'),
            (r'Flask', 'flask'),
            (r'Django', 'django'),
            (r'Starlette', 'starlette'),
            (r'aiohttp', 'aiohttp'),
            (r'tornado', 'tornado'),
        ],
        'javascript': [
            (r'express\(\)', 'express'),
            (r'fastify', 'fastify'),
            (r'koa', 'koa'),
            (r'nestjs', 'nestjs'),
        ],
        'typescript': [
            (r'@nestjs', 'nestjs'),
            (r'express\(\)', 'express'),
            (r'fastify', 'fastify'),
        ],
    }
    
    patterns = framework_patterns.get(language, [])
    for pattern, framework in patterns:
        if re.search(pattern, content):
            return framework
    
    return None


# ============================================================
# Test Detection
# ============================================================

TEST_DIRS = {'tests', 'test', '__tests__', 'spec', 'specs', '__tests__'}
TEST_FILE_PATTERNS = {
    'python': [r'test_.*\.py$', r'.*_test\.py$', r'tests?\.py$'],
    'javascript': [r'.*\.test\.js$', r'.*\.spec\.js$'],
    'typescript': [r'.*\.test\.ts$', r'.*\.spec\.ts$'],
    'go': [r'.*_test\.go$'],
    'rust': [r'.*\.rs$'],  # Rust tests are inline with #[test]
    'java': [r'.*Test\.java$', r'.*Tests\.java$'],
    'kotlin': [r'.*Test\.kt$', r'.*Tests\.kt$', r'.*Spec\.kt$'],  # Kotlin test files
    'cpp': [r'.*_test\.cpp$', r'.*_test\.cc$', r'.*Test\.cpp$', r'.*Test\.cc$'],
    'c': [r'.*_test\.c$', r'.*Test\.c$'],
}

TEST_FRAMEWORK_PATTERNS = {
    'python': [
        (r'import\s+pytest', 'pytest'),
        (r'from\s+pytest', 'pytest'),
        (r'import\s+unittest', 'unittest'),
        (r'from\s+unittest', 'unittest'),
        (r'from\s+nose', 'nose'),
    ],
    'javascript': [
        (r'jest', 'jest'),
        (r'mocha', 'mocha'),
        (r'jasmine', 'jasmine'),
        (r'vitest', 'vitest'),
    ],
    'typescript': [
        (r'jest', 'jest'),
        (r'vitest', 'vitest'),
        (r'mocha', 'mocha'),
    ],
    'go': [
        (r'testing', 'go_testing'),
    ],
    'rust': [
        (r'#\[test\]', 'rust_test'),
    ],
    'java': [
        (r'import\s+org\.junit', 'junit'),
        (r'import\s+org\.testng', 'testng'),
    ],
    'kotlin': [
        (r'import\s+org\.junit', 'junit'),
        (r'import\s+kotlin\.test', 'kotlin_test'),
        (r'import\s+io\.kotest', 'kotest'),
        (r'import\s+io\.mockk', 'mockk'),
        (r'@Test', 'junit'),  # JUnit 5 annotation
        (r'class.*Spec\s*:', 'kotest'),  # Kotest spec style
    ],
    'cpp': [
        (r'#include\s*<gtest/gtest\.h>', 'gtest'),
        (r'#include\s*<catch\.hpp>', 'catch2'),
        (r'doctest', 'doctest'),
        (r'#include\s*<boost/test', 'boost_test'),
    ],
    'c': [
        (r'#include\s*<gtest/gtest\.h>', 'gtest'),
        (r'#include\s*<check\.h>', 'check'),
        (r'#include\s*<assert\.h>', 'cunit'),
    ],
}


def detect_tests(
    root: Path,
    language: str,
    all_files: List[Path],
) -> TestInfo:
    """
    Detect test structure and framework.
    """
    info = TestInfo()
    
    # Find test directories
    test_dirs = []
    for d in root.rglob('*'):
        if d.is_dir() and d.name in TEST_DIRS:
            test_dirs.append(str(d.relative_to(root)))
    info.test_dirs = test_dirs
    
    # Find test files
    test_files = []
    patterns = TEST_FILE_PATTERNS.get(language, [])
    for file_path in all_files:
        rel_path = str(file_path.relative_to(root))
        for pattern in patterns:
            if re.search(pattern, file_path.name):
                test_files.append(rel_path)
                break
    info.test_files = test_files
    
    # Detect test framework
    framework_patterns = TEST_FRAMEWORK_PATTERNS.get(language, [])
    for file_path in all_files:
        if 'test' not in str(file_path).lower():
            continue
        
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        
        for pattern, framework in framework_patterns:
            if re.search(pattern, content):
                info.framework = framework
                break
        
        if info.framework:
            break
    
    # Guess coverage targets based on structure
    coverage_targets = []
    for d in ['services/', 'models/', 'controllers/', 'routes/', 'core/']:
        if (root / d).exists():
            coverage_targets.append(d)
    info.coverage_target_guess = coverage_targets
    
    # Check for fixtures and mocks
    for file_path in all_files:
        if 'conftest' in str(file_path) or 'fixture' in str(file_path).lower():
            info.has_fixtures = True
        if 'mock' in str(file_path).lower():
            info.has_mocks = True
    
    return info


# ============================================================
# Framework Detection
# ============================================================

FRAMEWORK_PATTERNS = {
    'web_framework': {
        'python': [
            (r'fastapi', 'fastapi'),
            (r'flask', 'flask'),
            (r'django', 'django'),
            (r'starlette', 'starlette'),
            (r'aiohttp', 'aiohttp'),
            (r'tornado', 'tornado'),
            (r'bottle', 'bottle'),
            (r'falcon', 'falcon'),
        ],
        'javascript': [
            (r'express', 'express'),
            (r'fastify', 'fastify'),
            (r'koa', 'koa'),
            (r'nestjs', 'nestjs'),
            (r'hapi', 'hapi'),
            (r'next', 'next.js'),
            (r'nuxt', 'nuxt.js'),
        ],
        'go': [
            (r'gin-gonic', 'gin'),
            (r'echo', 'echo'),
            (r'fiber', 'fiber'),
            (r'chi', 'chi'),
        ],
        'rust': [
            (r'actix-web', 'actix-web'),
            (r'rocket', 'rocket'),
            (r'warp', 'warp'),
            (r'axum', 'axum'),
        ],
        'java': [
            (r'spring-boot', 'spring-boot'),
            (r'quarkus', 'quarkus'),
            (r'micronaut', 'micronaut'),
        ],
        'kotlin': [
            (r'ktor', 'ktor'),
            (r'spring-boot', 'spring-boot'),
            (r'quarkus', 'quarkus'),
            (r'ktor-server', 'ktor'),
            (r'http4k', 'http4k'),
            (r'javafx', 'javafx'),  # Desktop
            (r'compose', 'compose'),  # Compose Multiplatform
        ],
    },
    'orm': {
        'python': [
            (r'sqlalchemy', 'sqlalchemy'),
            (r'django\.db', 'django-orm'),
            (r'peewee', 'peewee'),
            (r'tortoise', 'tortoise-orm'),
            (r'pony', 'pony'),
        ],
        'javascript': [
            (r'sequelize', 'sequelize'),
            (r'typeorm', 'typeorm'),
            (r'prisma', 'prisma'),
            (r'mongoose', 'mongoose'),
            (r'objection', 'objection'),
        ],
        'go': [
            (r'gorm', 'gorm'),
            (r'ent', 'ent'),
            (r'sqlboiler', 'sqlboiler'),
        ],
        'rust': [
            (r'diesel', 'diesel'),
            (r'sea-orm', 'sea-orm'),
            (r'sqlx', 'sqlx'),
        ],
        'java': [
            (r'hibernate', 'hibernate'),
            (r'jpa', 'jpa'),
            (r'mybatis', 'mybatis'),
        ],
        'kotlin': [
            (r'exposed', 'exposed'),  # JetBrains ORM
            (r'ktorm', 'ktorm'),
            (r'sqldelight', 'sqldelight'),
            (r'realm', 'realm'),
            (r'hibernate', 'hibernate'),
            (r'jpa', 'jpa'),
        ],
    },
    'database': {
        'python': [
            (r'redis', 'redis'),
            (r'pymongo', 'mongodb'),
            (r'psycopg', 'postgresql'),
            (r'mysql', 'mysql'),
            (r'cassandra', 'cassandra'),
        ],
        'javascript': [
            (r'redis', 'redis'),
            (r'mongodb', 'mongodb'),
            (r'mongoose', 'mongodb'),
            (r'pg', 'postgresql'),
            (r'mysql2', 'mysql'),
        ],
    },
    'task_queue': {
        'python': [
            (r'celery', 'celery'),
            (r'rq', 'redis-queue'),
            (r'dramatiq', 'dramatiq'),
            (r'huey', 'huey'),
        ],
        'javascript': [
            (r'bull', 'bull'),
            (r'kue', 'kue'),
            (r'bee-queue', 'bee-queue'),
            (r'agenda', 'agenda'),
        ],
    },
}


def detect_frameworks(
    root: Path,
    language: str,
    all_files: List[Path],
    requirements_files: List[str],
) -> FrameworkInfo:
    """
    Detect frameworks and libraries used in the project.
    
    Strategy:
    1. Check requirements/package files
    2. Scan source imports
    """
    info = FrameworkInfo()
    
    # Collect all imports/dependencies
    all_deps = set()
    
    # From requirements files
    for req_file in requirements_files:
        try:
            content = (root / req_file).read_text(encoding='utf-8', errors='replace')
            # Simple line-by-line extraction
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Extract package name (before version specifier)
                pkg = re.split(r'[=<>!\[]', line)[0].strip().lower()
                if pkg:
                    all_deps.add(pkg)
        except Exception:
            pass
    
    # From package.json
    pkg_json = root / 'package.json'
    if pkg_json.exists():
        try:
            import json
            content = json.loads(pkg_json.read_text(encoding='utf-8'))
            deps = content.get('dependencies', {})
            deps.update(content.get('devDependencies', {}))
            all_deps.update(d.lower() for d in deps.keys())
        except Exception:
            pass
    
    # From Cargo.toml
    cargo_toml = root / 'Cargo.toml'
    if cargo_toml.exists():
        try:
            content = cargo_toml.read_text(encoding='utf-8', errors='replace')
            # Simple regex extraction
            matches = re.findall(r'^\s*([a-zA-Z_-]+)\s*=', content, re.MULTILINE)
            all_deps.update(m.lower() for m in matches)
        except Exception:
            pass
    
    # From go.mod
    go_mod = root / 'go.mod'
    if go_mod.exists():
        try:
            content = go_mod.read_text(encoding='utf-8', errors='replace')
            matches = re.findall(r'require\s+([^\s]+)', content)
            all_deps.update(m.lower().split('/')[-1] for m in matches)
        except Exception:
            pass
    
    # Detect frameworks from dependencies
    for category, patterns_by_lang in FRAMEWORK_PATTERNS.items():
        patterns = patterns_by_lang.get(language, [])
        for dep in all_deps:
            for pattern, framework in patterns:
                if pattern in dep:
                    setattr(info, category, framework)
                    break
            if getattr(info, category):
                break
    
    # Set testing framework if detected
    # (This is also done in detect_tests, but we check here too)
    testing_patterns = FRAMEWORK_PATTERNS.get('testing', {}).get(language, [])
    for dep in all_deps:
        for pattern, framework in testing_patterns:
            if pattern in dep:
                info.testing = framework
                break
    
    return info


# ============================================================
# Build System Detection
# ============================================================

BUILD_FILES = {
    'python': ['setup.py', 'pyproject.toml', 'requirements.txt', 'setup.cfg'],
    'javascript': ['package.json', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml'],
    'typescript': ['package.json', 'tsconfig.json'],
    'go': ['go.mod', 'go.sum'],
    'rust': ['Cargo.toml', 'Cargo.lock'],
    'java': ['pom.xml', 'build.gradle', 'build.gradle.kts', 'settings.gradle'],
    'kotlin': ['build.gradle.kts', 'build.gradle', 'settings.gradle.kts', 'settings.gradle', 'gradle.properties'],
    'cpp': ['CMakeLists.txt', 'Makefile', 'meson.build'],
}

CI_FILES = [
    '.github/workflows',
    '.gitlab-ci.yml',
    '.travis.yml',
    'Jenkinsfile',
    'azure-pipelines.yml',
    '.circleci/config.yml',
    'bitbucket-pipelines.yml',
]


def detect_build_system(
    root: Path,
    language: str,
) -> BuildInfo:
    """
    Detect build system and CI/CD configuration.
    """
    info = BuildInfo()
    info.type = language
    
    # Check for Makefile
    if (root / 'Makefile').exists() or (root / 'makefile').exists():
        info.has_makefile = True
    
    # Check for Dockerfile
    dockerfile = None
    for name in ['Dockerfile', 'dockerfile', 'Dockerfile.dev', 'Dockerfile.prod']:
        if (root / name).exists():
            info.has_dockerfile = True
            info.dockerfile_path = name
            dockerfile = name
            break
    
    # Check for CI/CD
    ci_files = []
    for ci_path in CI_FILES:
        if (root / ci_path).exists():
            info.ci_detected = True
            ci_files.append(ci_path)
    info.ci_files = ci_files
    
    # Detect build commands from build files
    if language == 'python':
        if (root / 'pyproject.toml').exists():
            info.build_commands = ['pip install -e .', 'pip install .']
        else:
            info.build_commands = ['pip install -r requirements.txt']
    
    elif language in ('javascript', 'typescript'):
        pkg_json = root / 'package.json'
        if pkg_json.exists():
            try:
                import json
                content = json.loads(pkg_json.read_text(encoding='utf-8'))
                scripts = content.get('scripts', {})
                if 'build' in scripts:
                    info.build_commands = ['npm run build']
                if 'start' in scripts:
                    pass  # Entry point detection handles this
            except Exception:
                pass
    
    elif language == 'go':
        info.build_commands = ['go build ./...']
    
    elif language == 'rust':
        info.build_commands = ['cargo build']
    
    elif language == 'java':
        # Parse Maven pom.xml
        pom_xml = root / 'pom.xml'
        if pom_xml.exists():
            try:
                content = pom_xml.read_text(encoding='utf-8', errors='replace')
                maven_info = parse_pom_xml(content)
                
                info.maven = {
                    'groupId': maven_info.get('groupId'),
                    'artifactId': maven_info.get('artifactId'),
                    'version': maven_info.get('version'),
                    'packaging': maven_info.get('packaging'),
                    'parent': maven_info.get('parent'),
                    'dependencies_count': len(maven_info.get('dependencies', [])),
                    'properties': maven_info.get('properties', {}),
                }
                
                # Build commands
                info.build_commands = ['mvn compile', 'mvn package']
                
                # Detect Spring Boot from parent or dependencies
                parent = maven_info.get('parent', {})
                if parent and 'spring-boot' in str(parent.get('artifactId', '')):
                    info.build_commands.append('mvn spring-boot:run')
                
                for dep in maven_info.get('dependencies', []):
                    if 'spring-boot-starter' in str(dep.get('artifactId', '')):
                        info.build_commands.append('mvn spring-boot:run')
                        break
            except Exception:
                info.build_commands = ['mvn compile']
        
        # Parse Gradle build files
        elif (root / 'build.gradle').exists() or (root / 'build.gradle.kts').exists():
            gradle_file = root / 'build.gradle'
            gradle_kts = root / 'build.gradle.kts'
            
            try:
                if gradle_file.exists():
                    content = gradle_file.read_text(encoding='utf-8', errors='replace')
                    gradle_info = parse_build_gradle(content)
                elif gradle_kts.exists():
                    content = gradle_kts.read_text(encoding='utf-8', errors='replace')
                    gradle_info = parse_build_gradle_kts(content)
                else:
                    gradle_info = {}
                
                info.gradle = {
                    'plugins': gradle_info.get('plugins', []),
                    'group': gradle_info.get('group'),
                    'version': gradle_info.get('version'),
                    'dependencies_count': len(gradle_info.get('dependencies', [])),
                    'repositories': gradle_info.get('repositories', []),
                }
                
                # Build commands
                info.build_commands = ['gradle build']
                
                # Detect Kotlin/JVM or Android
                plugins = gradle_info.get('plugins', [])
                for plugin in plugins:
                    plugin_id = plugin.get('id', '')
                    if 'kotlin' in plugin_id:
                        if 'android' in plugin_id:
                            info.build_commands.append('./gradlew assembleDebug')
                        else:
                            info.build_commands.append('./gradlew jar')
                    elif 'application' in plugin_id:
                        info.build_commands.append('./gradlew run')
                    elif 'org.springframework.boot' in plugin_id:
                        info.build_commands.append('./gradlew bootRun')
            except Exception:
                info.build_commands = ['gradle build']
    
    elif language in ('cpp', 'c', 'c_header', 'cpp_header'):
        # Check for CMakeLists.txt
        cmake_file = root / 'CMakeLists.txt'
        if cmake_file.exists():
            try:
                from core.project_intelligence.dependency_graph import parse_cmake_file
                content = cmake_file.read_text(encoding='utf-8', errors='replace')
                cmake_info = parse_cmake_file(content)
                
                # Add CMake info to build
                info.cmake = {
                    'project_name': cmake_info.get('project_name'),
                    'cmake_version': cmake_info.get('cmake_minimum_version'),
                    'executables': cmake_info.get('executables', []),
                    'libraries': cmake_info.get('libraries', []),
                    'dependencies': cmake_info.get('dependencies', []),
                    'link_libraries': cmake_info.get('link_libraries', []),
                    'include_dirs': cmake_info.get('include_dirs', []),
                }
                
                # Build commands
                if cmake_info.get('executables'):
                    info.build_commands = ['cmake -B build', 'cmake --build build']
                elif cmake_info.get('libraries'):
                    info.build_commands = ['cmake -B build', 'cmake --build build']
                else:
                    info.build_commands = ['cmake -B build', 'cmake --build build']
            except Exception:
                info.build_commands = ['cmake -B build', 'cmake --build build']
        else:
            info.build_commands = ['make']  # Fallback to Make
    
    return info


# ============================================================
# Package Manager Detection
# ============================================================

PACKAGE_MANAGERS = {
    'python': [
        ('pyproject.toml', 'pip-poetry'),
        ('requirements.txt', 'pip'),
        ('Pipfile', 'pipenv'),
        ('setup.py', 'setuptools'),
    ],
    'javascript': [
        ('pnpm-lock.yaml', 'pnpm'),
        ('yarn.lock', 'yarn'),
        ('package-lock.json', 'npm'),
        ('package.json', 'npm'),
    ],
    'typescript': [
        ('pnpm-lock.yaml', 'pnpm'),
        ('yarn.lock', 'yarn'),
        ('package-lock.json', 'npm'),
    ],
    'go': [
        ('go.mod', 'go-mod'),
    ],
    'rust': [
        ('Cargo.toml', 'cargo'),
    ],
    'java': [
        ('pom.xml', 'maven'),
        ('build.gradle', 'gradle'),
        ('build.gradle.kts', 'gradle'),
    ],
}


def detect_package_manager(root: Path, language: str) -> Tuple[Optional[str], List[str]]:
    """
    Detect package manager and requirements files.
    
    Returns:
        Tuple of (package_manager, requirements_files)
    """
    patterns = PACKAGE_MANAGERS.get(language, [])
    requirements_files = []
    
    for filename, pm in patterns:
        if (root / filename).exists():
            requirements_files.append(filename)
            if not pm.startswith('pip'):  # pip is default, prefer others
                return pm, requirements_files
    
    if requirements_files:
        return patterns[0][1] if patterns else None, requirements_files
    
    return None, []


# ============================================================
# Maven/Gradle Parser (Java Build Systems)
# ============================================================

def parse_pom_xml(content: str) -> Dict[str, Any]:
    """
    Parse Maven pom.xml file.
    
    Extracts:
    - groupId, artifactId, version
    - dependencies (with scope)
    - properties
    - parent project info
    """
    result = {
        'groupId': None,
        'artifactId': None,
        'version': None,
        'packaging': 'jar',
        'dependencies': [],
        'parent': None,
        'properties': {},
    }
    
    # Simple regex-based parsing (no XML parser needed for basic extraction)
    # Group ID
    match = re.search(r'<groupId>([^<]+)</groupId>', content)
    if match:
        result['groupId'] = match.group(1)
    
    # Artifact ID
    match = re.search(r'<artifactId>([^<]+)</artifactId>', content)
    if match:
        result['artifactId'] = match.group(1)
    
    # Version
    match = re.search(r'<version>([^<]+)</version>', content)
    if match:
        result['version'] = match.group(1)
    
    # Packaging
    match = re.search(r'<packaging>([^<]+)</packaging>', content)
    if match:
        result['packaging'] = match.group(1)
    
    # Parent project
    parent_match = re.search(
        r'<parent>.*?<groupId>([^<]+)</groupId>.*?<artifactId>([^<]+)</artifactId>.*?<version>([^<]+)</version>.*?</parent>',
        content,
        re.DOTALL
    )
    if parent_match:
        result['parent'] = {
            'groupId': parent_match.group(1),
            'artifactId': parent_match.group(2),
            'version': parent_match.group(3),
        }
    
    # Dependencies
    dependencies_section = re.search(r'<dependencies>(.*?)</dependencies>', content, re.DOTALL)
    if dependencies_section:
        dep_matches = re.finditer(
            r'<dependency>\s*'
            r'<groupId>([^<]+)</groupId>\s*'
            r'<artifactId>([^<]+)</artifactId>\s*'
            r'(?:<version>([^<]+)</version>)?\s*'
            r'(?:<scope>([^<]+)</scope>)?',
            dependencies_section.group(1),
            re.DOTALL
        )
        for dep in dep_matches:
            result['dependencies'].append({
                'groupId': dep.group(1),
                'artifactId': dep.group(2),
                'version': dep.group(3),
                'scope': dep.group(4) or 'compile',
            })
    
    # Properties
    properties_match = re.search(r'<properties>(.*?)</properties>', content, re.DOTALL)
    if properties_match:
        prop_matches = re.finditer(r'<([^>]+)>([^<]+)</\1>', properties_match.group(1))
        for prop in prop_matches:
            result['properties'][prop.group(1)] = prop.group(2)
    
    return result


def parse_build_gradle(content: str) -> Dict[str, Any]:
    """
    Parse Gradle build.gradle file (Groovy DSL).
    
    Extracts:
    - plugins
    - group, version
    - dependencies
    - repositories
    """
    result = {
        'plugins': [],
        'group': None,
        'version': None,
        'dependencies': [],
        'repositories': [],
    }
    
    # Plugins
    plugin_matches = re.findall(r'id\s+[\'"]([^\'"]+)[\'"](?:\s+version\s+[\'"]([^\'"]+)[\'"])?', content)
    for plugin in plugin_matches:
        result['plugins'].append({
            'id': plugin[0],
            'version': plugin[1] if len(plugin) > 1 and plugin[1] else None,
        })
    
    # Group and version
    group_match = re.search(r"group\s*=\s*['\"]([^'\"]+)['\"]", content)
    if group_match:
        result['group'] = group_match.group(1)
    
    version_match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
    if version_match:
        result['version'] = version_match.group(1)
    
    # Dependencies (multiple formats)
    # compile 'group:artifact:version'
    # implementation 'group:artifact:version'
    # testImplementation 'group:artifact:version'
    dep_patterns = [
        r"(compile|implementation|testImplementation|runtimeOnly|compileOnly)\s+['\"]([^:]+):([^:]+):([^'\"]+)['\"]",
        r"(compile|implementation|testImplementation|runtimeOnly|compileOnly)\s+project\s*\(['\"]([^'\"]+)['\"]\)",
    ]
    
    for pattern in dep_patterns:
        dep_matches = re.finditer(pattern, content)
        for dep in dep_matches:
            if len(dep.groups()) == 4:
                # External dependency
                result['dependencies'].append({
                    'configuration': dep.group(1),
                    'group': dep.group(2),
                    'artifact': dep.group(3),
                    'version': dep.group(4),
                    'type': 'external',
                })
            elif len(dep.groups()) >= 1 and 'project' in content[max(0, dep.start()-20):dep.start()]:
                # Project dependency
                result['dependencies'].append({
                    'configuration': dep.group(1),
                    'path': dep.group(2),
                    'type': 'project',
                })
    
    # Repositories
    repo_matches = re.findall(r"mavenCentral\(\)|jcenter\(\)|google\(\)|maven\s*\{\s*url\s*=\s*['\"]([^'\"]+)['\"]\s*\}", content)
    for repo in repo_matches:
        if repo:
            result['repositories'].append(repo)
        else:
            # Determine from function name
            if 'mavenCentral()' in content:
                result['repositories'].append('mavenCentral')
            if 'jcenter()' in content:
                result['repositories'].append('jcenter')
            if 'google()' in content:
                result['repositories'].append('google')
    
    return result


def parse_build_gradle_kts(content: str) -> Dict[str, Any]:
    """
    Parse Gradle build.gradle.kts file (Kotlin DSL).
    
    Similar to Groovy DSL but with Kotlin syntax.
    """
    result = {
        'plugins': [],
        'group': None,
        'version': None,
        'dependencies': [],
        'repositories': [],
    }
    
    # Plugins
    plugin_matches = re.findall(r'id\s*\(\s*["\']([^"\']+)["\']\s*\)(?:\s*version\s*\(\s*["\']([^"\']+)["\']\s*\))?', content)
    for plugin in plugin_matches:
        result['plugins'].append({
            'id': plugin[0],
            'version': plugin[1] if len(plugin) > 1 and plugin[1] else None,
        })
    
    # Group and version
    group_match = re.search(r'group\s*=\s*["\']([^"\']+)["\']', content)
    if group_match:
        result['group'] = group_match.group(1)
    
    version_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
    if version_match:
        result['version'] = version_match.group(1)
    
    # Dependencies (Kotlin DSL style)
    dep_matches = re.findall(
        r'(implementation|testImplementation|runtimeOnly|compileOnly)\s*\(\s*["\']([^:]+):([^:]+):([^"\']+)["\']\s*\)',
        content
    )
    for dep in dep_matches:
        result['dependencies'].append({
            'configuration': dep[0],
            'group': dep[1],
            'artifact': dep[2],
            'version': dep[3],
            'type': 'external',
        })
    
    return result
