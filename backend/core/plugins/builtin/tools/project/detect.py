"""
Project Detect Tool (V2.2).

1. 项目根目录：默认 workspace；若根目录无匹配，可向下查找一层子目录中的项目根。
2. 按文件存在性检测，顺序即优先级（不可打乱）：
   Cargo.toml → Rust, go.mod → Go, package.json → Node,
   pyproject.toml / requirements.txt → Python, pom.xml / build.gradle → Java, CMakeLists.txt → C++,
   最后 Python 回退（tests/test 目录下需有 .py 或根目录有 pytest/test_*.py 等特征）。
3. 若均未匹配则返回 None，由调用方（如 plan 步骤）决定后续行为。
"""
import os
from typing import Any, Dict, List, Optional, Tuple

from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from log import logger


# 用于查找项目根的标识文件（与检测规则一致，用于子目录扫描）
_PROJECT_ROOT_MARKERS = frozenset({
    "Cargo.toml", "go.mod", "package.json", "pyproject.toml", "requirements.txt",
    "pom.xml", "build.gradle", "CMakeLists.txt",
})

# 检测顺序即优先级，不可打乱。(单个文件, language, test_command, build_command)
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
    """列出目录下的文件名（仅一层）。"""
    try:
        return os.listdir(path)
    except OSError:
        return []


def _find_project_root(workspace: str, search_subdirs: bool = True) -> str:
    """
    确定项目根目录。默认先用 workspace；若无匹配则在其直接子目录中查找包含项目标识的目录。
    """
    files = _list_root_files(workspace)
    if not files:
        return workspace
    # 根目录已有任一标识则直接使用
    if _PROJECT_ROOT_MARKERS & set(files):
        return workspace
    if not search_subdirs:
        return workspace
    # 向下找一层：仅考虑直接子目录
    for name in files:
        sub = os.path.join(workspace, name)
        if not os.path.isdir(sub):
            continue
        sub_files = _list_root_files(sub)
        if _PROJECT_ROOT_MARKERS & set(sub_files):
            return sub
    return workspace


def _has_python_in_dir(path: str, max_files: int = 50) -> bool:
    """目录内是否存在 .py 文件（限制数量避免过深）。"""
    count = 0
    try:
        for name in os.listdir(path):
            if count >= max_files:
                return True
            full = os.path.join(path, name)
            if os.path.isfile(full) and name.endswith(".py"):
                return True
            if os.path.isdir(full):
                if _has_python_in_dir(full, max_files - count):
                    return True
            count += 1
    except OSError:
        pass
    return False


def _detect_python_tests(workspace: str) -> bool:
    """通过 tests/test 目录（且含 .py）或根目录 pytest/test_*.py 特征判断是否为可测 Python 项目。"""
    try:
        names = os.listdir(workspace)
    except OSError:
        return False
    files = [n for n in names if os.path.isfile(os.path.join(workspace, n))]
    dirs = [n for n in names if os.path.isdir(os.path.join(workspace, n))]
    if "tests" in dirs and _has_python_in_dir(os.path.join(workspace, "tests")):
        return True
    if "test" in dirs and _has_python_in_dir(os.path.join(workspace, "test")):
        return True
    if "pytest.ini" in files or "setup.cfg" in files:
        return True
    for f in files:
        if f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")):
            return True
    return False


def _auto_detect_project(project_root: str) -> Optional[Dict[str, Any]]:
    """
    在给定项目根下按优先级做文件存在性检测。
    返回 project_info 或 None。
    """
    files = _list_root_files(project_root)
    if not files:
        return None

    for filename, language, test_command, build_command in _PROJECT_RULES:
        if filename in files:
            return {
                "language": language,
                "test_command": test_command,
                "build_command": build_command,
                "detected_file": filename,
            }

    if _detect_python_tests(project_root):
        return {
            "language": "python",
            "test_command": "pytest",
            "build_command": None,
            "detected_file": "python_fallback",
        }

    return None


class ProjectDetectTool(Tool):
    """从项目根（默认 workspace，可向下查找一层）按优先级检测项目类型并推断 test/build 命令。"""

    @property
    def name(self) -> str:
        return "project.detect"

    @property
    def description(self) -> str:
        return (
            "Detect project type from workspace root (or one level of subdirs). "
            "Priority: Cargo.toml, go.mod, package.json, pyproject.toml, requirements.txt, "
            "pom.xml, build.gradle, CMakeLists.txt, then Python fallback. Returns project_info or None."
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
                "description": "If true and root has no project markers, search one level of subdirs for project root.",
                "default": True,
            },
        }, required=[])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_info": {
                    "type": ["object", "null"],
                    "description": "Detected: language, test_command, build_command, detected_file; null if none.",
                },
                "project_root": {"type": "string", "description": "Resolved project root path used for detection."},
                "files": {"type": "array", "items": {"type": "string"}, "description": "List of root-level names."},
            },
        }

    @property
    def required_permissions(self) -> List[str]:
        return ["file.read"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Detect Project",
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
        logger.info(f"[project.detect] Scanning root {project_root}, files: {files}")

        detected = _auto_detect_project(project_root)
        if detected:
            logger.info(f"[project.detect] Detected {detected}")
        else:
            logger.info("[project.detect] No project type detected")

        return ToolResult(
            success=True,
            data={
                "project_info": detected,
                "project_root": project_root,
                "files": files,
            },
        )
