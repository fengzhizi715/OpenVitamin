"""
ProjectContext dataclass for AI programming agent.

Stores detected project information in session.state["project_context"].
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ProjectContext:
    """
    Detected project context for AI programming agent.
    
    Stored in session.state["project_context"] after project.scan.
    """
    language: str  # python, node, rust, go, java, cpp, etc.
    project_root: str  # Absolute path to project root
    has_git: bool = False
    test_command: Optional[str] = None
    build_command: Optional[str] = None
    detected_file: Optional[str] = None  # The marker file that was detected
    extra: Dict[str, Any] = field(default_factory=dict)  # Additional context
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for session.state storage."""
        return {
            "language": self.language,
            "project_root": self.project_root,
            "has_git": self.has_git,
            "test_command": self.test_command,
            "build_command": self.build_command,
            "detected_file": self.detected_file,
            "extra": self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectContext":
        """Deserialize from dictionary."""
        return cls(
            language=data.get("language", "unknown"),
            project_root=data.get("project_root", "."),
            has_git=data.get("has_git", False),
            test_command=data.get("test_command"),
            build_command=data.get("build_command"),
            detected_file=data.get("detected_file"),
            extra=data.get("extra", {}),
        )
