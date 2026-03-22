"""
project.scan Tool - Scan workspace and detect project context.

Features:
- Detect project type (Python/Node/Rust/Go/Java/CMake)
- Detect test command
- Detect build command
- Detect git existence
- Return ProjectContext (stored in session.state)

Rules:
- Only based on file existence, no complex content parsing
- Priority order matching
- If no test_command detected, return None
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from log import logger


# Project root markers (used for subdirectory scanning)
_PROJECT_ROOT_MARKERS = frozenset({
    "Cargo.toml", "go.mod", "package.json", "pyproject.toml", "requirements.txt",
    "pom.xml", "build.gradle", "CMakeLists.txt",
})

# Detection rules: (marker_file, language, test_command, build_command)
# Order matters - priority from top to bottom
_PROJECT_RULES: List[Tuple[str, str, str, Optional[str]]] = [
    ("Cargo.toml", "rust", "cargo test", None),
    ("go.mod", "go", "go test ./...", None),
    ("package.json", "node", "npm test", "npm run build"),
    ("pyproject.toml", "python", "pytest", None),
    ("requirements.txt", "python", "pytest", None),
    ("pom.xml", "java", "mvn test", "mvn compile"),
    ("build.gradle", "java", "gradle test", "gradle build"),
    ("CMakeLists.txt", "cpp", "ctest", "cmake .."),
]


def _list_root_files(path: str) -> List[str]:
    """List files in directory (only one level)."""
    try:
        return os.listdir(path)
    except OSError:
        return []


def _find_project_root(workspace: str, search_subdirs: bool = True) -> str:
    """
    Determine project root directory.
    
    Default to workspace; if no match, search one level of subdirectories.
    """
    files = _list_root_files(workspace)
    if not files:
        return workspace
    
    # Root has any marker - use it directly
    if _PROJECT_ROOT_MARKERS & set(files):
        return workspace
    
    if not search_subdirs:
        return workspace
    
    # Search one level down
    for name in files:
        sub = os.path.join(workspace, name)
        if not os.path.isdir(sub):
            continue
        sub_files = _list_root_files(sub)
        if _PROJECT_ROOT_MARKERS & set(sub_files):
            return sub
    
    return workspace


def _has_python_tests(workspace: str) -> bool:
    """Check if workspace has Python test structure."""
    try:
        names = os.listdir(workspace)
    except OSError:
        return False
    
    files = [n for n in names if os.path.isfile(os.path.join(workspace, n))]
    dirs = [n for n in names if os.path.isdir(os.path.join(workspace, n))]
    
    # Check for tests/ or test/ directory with .py files
    if "tests" in dirs:
        tests_path = os.path.join(workspace, "tests")
        if any(f.endswith(".py") for f in _list_root_files(tests_path)):
            return True
    
    if "test" in dirs:
        test_path = os.path.join(workspace, "test")
        if any(f.endswith(".py") for f in _list_root_files(test_path)):
            return True
    
    # Check for pytest.ini or setup.cfg
    if "pytest.ini" in files or "setup.cfg" in files:
        return True
    
    # Check for test_*.py or *_test.py files
    for f in files:
        if f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")):
            return True
    
    return False


def _detect_git(project_root: str) -> bool:
    """Check if project has git repository."""
    git_dir = os.path.join(project_root, ".git")
    return os.path.isdir(git_dir)


def _detect_project(project_root: str) -> Optional[Dict[str, Any]]:
    """
    Detect project type based on file existence.
    
    Returns project_info or None.
    """
    files = _list_root_files(project_root)
    if not files:
        return None
    
    # Check each rule in priority order
    for filename, language, test_command, build_command in _PROJECT_RULES:
        if filename in files:
            return {
                "language": language,
                "test_command": test_command,
                "build_command": build_command,
                "detected_file": filename,
            }
    
    # Python fallback: check for test structure
    if _has_python_tests(project_root):
        return {
            "language": "python",
            "test_command": "pytest",
            "build_command": None,
            "detected_file": "python_fallback",
        }
    
    return None


class ProjectScanTool(Tool):
    """
    Scan workspace and detect project context.
    
    Detects:
    - Project type (Python/Node/Rust/Go/Java/CMake)
    - Test command
    - Build command
    - Git existence
    
    Returns ProjectContext that should be stored in session.state["project_context"].
    """

    @property
    def name(self) -> str:
        return "project.scan"

    @property
    def description(self) -> str:
        return (
            "Scan workspace to detect project type, test command, build command, and git. "
            "Returns ProjectContext that should be stored in session.state['project_context']. "
            "Priority: Cargo.toml, go.mod, package.json, pyproject.toml, requirements.txt, "
            "pom.xml, build.gradle, CMakeLists.txt, then Python fallback."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "workspace": {
                "type": "string",
                "description": "Root to scan (default: context workspace).",
            },
            "search_subdirs": {
                "type": "boolean",
                "description": "If true and root has no project markers, search one level of subdirs.",
                "default": True,
            },
        }, required=[])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_context": {
                    "type": ["object", "null"],
                    "description": "Detected: language, test_command, build_command, has_git, project_root.",
                },
                "project_root": {"type": "string", "description": "Resolved project root path."},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Root-level files."},
            },
        }

    @property
    def required_permissions(self) -> List[str]:
        return ["file.read"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Project Scan",
            "icon": "Search",
            "category": "project",
            "permissions_hint": [{"key": "file.read", "label": "Read workspace directory."}],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        workspace = (input_data.get("workspace") or "").strip() or (ctx.workspace or ".")
        if not os.path.isdir(workspace):
            return ToolResult(success=False, error=f"Workspace not found: {workspace}")

        search_subdirs = input_data.get("search_subdirs", True)
        project_root = _find_project_root(workspace, search_subdirs=search_subdirs)
        files = _list_root_files(project_root)
        
        logger.info(f"[project.scan] Scanning root {project_root}, files: {files}")

        detected = _detect_project(project_root)
        has_git = _detect_git(project_root)
        
        if detected:
            # Build ProjectContext
            project_context = {
                "language": detected["language"],
                "project_root": os.path.abspath(project_root),
                "has_git": has_git,
                "test_command": detected["test_command"],
                "build_command": detected["build_command"],
                "detected_file": detected["detected_file"],
            }
            logger.info(f"[project.scan] Detected: {project_context}")
        else:
            # No project detected
            project_context = None
            logger.info("[project.scan] No project type detected")

        return ToolResult(
            success=True,
            data={
                "project_context": project_context,
                "project_root": os.path.abspath(project_root),
                "files": files,
            },
        )
