"""
Project Intelligence Formatter - Human-Readable Output Generator.

This module provides formatted, presentation-ready output for Project Intelligence
analysis results. It transforms raw structured data into:
- Executive summaries
- Architecture diagrams (text-based)
- Risk assessment reports
- Development recommendations

Usage:
    from core.project_intelligence.formatter import ProjectFormatter
    
    model = analyze("/path/to/project")
    
    # Get executive summary
    summary = formatter.executive_summary(model)
    
    # Get architecture overview
    arch_view = formatter.architecture_overview(model)
    
    # Get risk report
    risk_report = formatter.risk_assessment_report(model)
"""
from typing import Dict, List, Optional, Any
from .model import ProjectModel, ModuleInfo, RiskProfile


class ProjectFormatter:
    """
    Formats Project Intelligence models into human-readable presentations.
    
    Supports multiple output styles:
    - markdown: For documentation and reports
    - console: For terminal output with ASCII art
    - json_summary: Condensed JSON for API responses
    """
    
    def __init__(self, model: ProjectModel):
        self.model = model
    
    # ============================================================
    # Executive Summary
    # ============================================================
    
    def executive_summary(self, style: str = "markdown") -> str:
        """
        Generate a high-level executive summary.
        
        Focuses on:
        - Project size and complexity
        - Primary language and frameworks
        - Key risks
        - Test coverage
        """
        if style == "markdown":
            return self._executive_summary_markdown()
        elif style == "console":
            return self._executive_summary_console()
        else:
            return self._executive_summary_json()
    
    def _executive_summary_markdown(self) -> str:
        """Markdown-formatted executive summary."""
        meta = self.model.meta
        framework = self.model.framework
        risk = self.model.risk
        
        lines = [
            "# 📊 Project Intelligence Report",
            "",
            "## Overview",
            "",
            f"- **Language**: {meta.language.title()}" + (f" ({', '.join(meta.languages_detected)})" if len(meta.languages_detected) > 1 else ""),
            f"- **Size**: {meta.file_count:,} files / {meta.size_kb:,} KB",
            f"- **Structure**: {self.model.structure.directory_count} directories, max depth {self.model.structure.max_depth}",
            "",
        ]
        
        # Frameworks
        if framework.web_framework or framework.orm:
            lines.extend([
                "## Technology Stack",
                "",
            ])
            if framework.web_framework:
                lines.append(f"- **Web Framework**: {framework.web_framework.title()}")
            if framework.orm:
                lines.append(f"- **ORM**: {framework.orm.title()}")
            if framework.testing:
                lines.append(f"- **Testing**: {framework.testing.title()}")
            if framework.database:
                lines.append(f"- **Database**: {framework.database.title()}")
            lines.append("")
        
        # Entry points
        if self.model.entry_points:
            lines.extend([
                "## Entry Points",
                "",
            ])
            for ep in self.model.entry_points[:3]:  # Top 3
                ep_type = ep.type.replace("_", " ").title()
                fw = f" ({ep.framework})" if ep.framework else ""
                lines.append(f"- `{ep.file}` → {ep_type}{fw}")
            lines.append("")
        
        # Risks
        if risk.risk_score > 0:
            lines.extend([
                "## ⚠️ Risk Assessment",
                "",
                f"**Risk Score**: {risk.risk_score}/100",
                "",
            ])
            
            if risk.large_files:
                lines.append(f"- 📁 Large files (>500 lines): {len(risk.large_files)}")
            if risk.high_coupling_modules:
                lines.append(f"- 🔗 High coupling modules: {len(risk.high_coupling_modules)}")
            if risk.circular_dependencies_detected:
                lines.append(f"- 🔄 Circular dependencies: {len(risk.circular_dependencies)} cycles")
            if risk.unsafe_patterns:
                lines.append(f"- ⚠️ Unsafe patterns: {len(risk.unsafe_patterns)}")
            lines.append("")
        
        # Tests
        test_info = self.model.tests
        if test_info.test_files:
            lines.extend([
                "## ✅ Testing",
                "",
                f"- **Framework**: {test_info.framework or 'Unknown'}",
                f"- **Test files**: {len(test_info.test_files)}",
                f"- **Has fixtures**: {'Yes' if test_info.has_fixtures else 'No'}",
                f"- **Has mocks**: {'Yes' if test_info.has_mocks else 'No'}",
                "",
            ])
        
        # Modules by type
        module_types = self._count_modules_by_type()
        if module_types:
            lines.extend([
                "## 🏗️ Architecture Layers",
                "",
            ])
            for mtype, count in sorted(module_types.items(), key=lambda x: x[1], reverse=True):
                emoji = self._get_module_type_emoji(mtype)
                lines.append(f"{emoji} **{mtype.title()}**: {count} modules")
            lines.append("")
        
        return "\n".join(lines)
    
    def _executive_summary_console(self) -> str:
        """Console-formatted executive summary with ASCII art."""
        meta = self.model.meta
        
        lines = [
            "=" * 70,
            "PROJECT INTELLIGENCE REPORT",
            "=" * 70,
            "",
            f"📦 Language: {meta.language.title()}",
            f"📊 Size: {meta.file_count} files / {meta.size_kb} KB",
            f"🏢 Structure: {self.model.structure.directory_count} dirs (depth {self.model.structure.max_depth})",
            "",
        ]
        
        # Quick stats
        total_lines = sum(m.lines for m in self.model.modules)
        avg_lines = total_lines // len(self.model.modules) if self.model.modules else 0
        
        lines.extend([
            f"📝 Total Lines: {total_lines:,}",
            f"📏 Avg Module: {avg_lines} lines",
            f"⚠️ Risk Score: {self.model.risk.risk_score}/100",
            "",
            "=" * 70,
        ])
        
        return "\n".join(lines)
    
    def _executive_summary_json(self) -> Dict[str, Any]:
        """Condensed JSON summary."""
        return {
            "overview": {
                "language": self.model.meta.language,
                "file_count": self.model.meta.file_count,
                "size_kb": self.model.meta.size_kb,
            },
            "technology_stack": {
                "web_framework": self.model.framework.web_framework,
                "orm": self.model.framework.orm,
                "testing": self.model.framework.testing,
            },
            "risks": {
                "risk_score": self.model.risk.risk_score,
                "large_files_count": len(self.model.risk.large_files),
                "high_coupling_count": len(self.model.risk.high_coupling_modules),
            },
            "tests": {
                "framework": self.model.tests.framework,
                "test_files_count": len(self.model.tests.test_files),
            },
        }
    
    # ============================================================
    # Architecture Overview
    # ============================================================
    
    def architecture_overview(self, include_tree: bool = False) -> str:
        """
        Generate an architecture overview with layer visualization.
        
        Args:
            include_tree: Whether to include full directory tree
        
        Returns:
            Markdown-formatted architecture overview
        """
        layers = self.model.structure.layered_guess
        
        lines = [
            "## 🏛️ Architecture Layers",
            "",
            "Based on directory structure analysis:",
            "",
        ]
        
        # Presentation layer
        if layers.presentation:
            lines.append("### 🎨 Presentation Layer")
            for dir_path in layers.presentation:
                lines.append(f"- `{dir_path}/`")
            lines.append("")
        
        # Service layer
        if layers.service:
            lines.append("### ⚙️ Service Layer")
            for dir_path in layers.service:
                lines.append(f"- `{dir_path}/`")
            lines.append("")
        
        # Data layer
        if layers.data:
            lines.append("### 💾 Data Layer")
            for dir_path in layers.data:
                lines.append(f"- `{dir_path}/`")
            lines.append("")
        
        # Utils layer
        if layers.utils:
            lines.append("### 🔧 Utilities")
            for dir_path in layers.utils:
                lines.append(f"- `{dir_path}/`")
            lines.append("")
        
        # Config layer
        if layers.config:
            lines.append("### ⚙️ Configuration")
            for dir_path in layers.config:
                lines.append(f"- `{dir_path}/`")
            lines.append("")
        
        # Module dependency graph (top 10 most connected)
        if self.model.dependencies.internal_graph:
            lines.extend([
                "## 🔗 Module Dependencies (Top 10)",
                "",
            ])
            
            # Count dependencies per module
            dep_counts = {}
            for module, deps in self.model.dependencies.internal_graph.items():
                dep_counts[module] = len(deps)
            
            top_modules = sorted(dep_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            
            for module, count in top_modules:
                bar = "█" * min(count, 20)  # Visual bar
                lines.append(f"`{module}` {bar} ({count})")
            
            lines.append("")
        
        # Full directory tree (optional)
        if include_tree and self.model.structure.tree:
            lines.extend([
                "## 📁 Directory Structure",
                "",
                "```",
                self._render_directory_tree(self.model.structure.tree, prefix=""),
                "```",
                "",
            ])
        
        return "\n".join(lines)
    
    def _render_directory_tree(self, nodes: List, prefix: str = "", is_last: bool = True) -> str:
        """Render directory tree as ASCII art."""
        lines = []
        
        for i, node in enumerate(nodes):
            is_current_last = (i == len(nodes) - 1)
            connector = "└── " if is_current_last else "├── "
            
            lines.append(f"{prefix}{connector}{node.path}")
            
            if node.type == "directory" and node.children:
                extension = "    " if is_current_last else "│   "
                child_lines = self._render_directory_tree(
                    node.children, 
                    prefix=prefix + extension,
                    is_last=is_current_last
                )
                lines.append(child_lines)
        
        return "\n".join(filter(None, lines))
    
    # ============================================================
    # Risk Assessment Report
    # ============================================================
    
    def risk_assessment_report(self, detailed: bool = False) -> str:
        """
        Generate a detailed risk assessment report.
        
        Args:
            detailed: Include specific file paths and line numbers
        
        Returns:
            Markdown-formatted risk report
        """
        risk = self.model.risk
        total_modules = len([m for m in self.model.modules if m.type != 'test'])
        
        # Risk level classification (adjusted thresholds for normalized scoring)
        if risk.risk_score >= 60:
            level = "🔴 HIGH RISK"
        elif risk.risk_score >= 30:
            level = "🟡 MEDIUM RISK"
        else:
            level = "🟢 LOW RISK"
        
        lines = [
            "## ⚠️ Risk Assessment Report",
            "",
            f"**Overall Risk Level**: {level} (Score: {risk.risk_score}/100)",
            "",
            "### Key Metrics",
            "",
        ]
        
        # Calculate percentages for each category
        if total_modules > 0:
            unsafe_pct = (len(risk.unsafe_patterns) / total_modules) * 100
            arch_pct = (len(risk.circular_dependencies) / total_modules) * 100
            coupling_pct = (len(risk.high_coupling_modules) / total_modules) * 100
            large_pct = (len(risk.large_files) / total_modules) * 100
            untested_pct = (len(risk.missing_tests) / total_modules) * 100
            
            lines.extend([
                f"- 🔒 **Safety issues**: {len(risk.unsafe_patterns)} ({unsafe_pct:.1f}% of modules)",
                f"- 🏗️ **Architecture issues**: {len(risk.circular_dependencies)} circular dependencies ({arch_pct:.1f}%)",
                f"- 🔗 **High coupling**: {len(risk.high_coupling_modules)} modules ({coupling_pct:.1f}%)",
                f"- 📁 **Large files**: {len(risk.large_files)} ({large_pct:.1f}%)",
                f"- 🧪 **Missing tests**: {len(risk.missing_tests)} ({untested_pct:.1f}% without test coverage)",
                "",
            ])
        else:
            lines.extend([
                f"- 📁 Large files: {len(risk.large_files)}",
                f"- 🔗 High coupling modules: {len(risk.high_coupling_modules)}",
                f"- 🔄 Circular dependencies: {len(risk.circular_dependencies)} cycles",
                f"- ⚠️ Unsafe patterns: {len(risk.unsafe_patterns)}",
                f"- 🧪 Missing tests: {len(risk.missing_tests)}",
                "",
            ])
        
        # Large files
        if risk.large_files:
            lines.extend([
                "### 📁 Large Files (>500 lines)",
                "",
                "These files may be difficult to maintain and test:",
                "",
            ])
            for file_path in risk.large_files[:10]:  # Top 10
                lines.append(f"- `{file_path}`")
            if len(risk.large_files) > 10:
                lines.append(f"- ... and {len(risk.large_files) - 10} more")
            lines.append("")
        
        # High coupling modules
        if risk.high_coupling_modules:
            lines.extend([
                "### 🔗 High Coupling Modules",
                "",
                "These modules have many dependencies (tight coupling):",
                "",
            ])
            for file_path in risk.high_coupling_modules[:10]:
                lines.append(f"- `{file_path}`")
            lines.append("")
        
        # Circular dependencies
        if risk.circular_dependencies_detected:
            lines.extend([
                "### 🔄 Circular Dependencies",
                "",
                "**Critical**: These circular imports should be refactored:",
                "",
            ])
            for i, cycle in enumerate(risk.circular_dependencies[:5], 1):
                cycle_str = " → ".join(cycle)
                lines.append(f"{i}. `{cycle_str}`")
            lines.append("")
        
        # Unsafe patterns
        if risk.unsafe_patterns:
            lines.extend([
                "### ⚠️ Unsafe Code Patterns",
                "",
                "Security and maintainability concerns:",
                "",
            ])
            for pattern in risk.unsafe_patterns[:10]:
                lines.append(f"- {pattern}")
            lines.append("")
        
        # Missing tests
        if risk.missing_tests:
            lines.extend([
                "### 🧪 Modules Without Tests",
                "",
                f"{len(risk.missing_tests)} modules lack test coverage:",
                "",
            ])
            for file_path in risk.missing_tests[:10]:
                lines.append(f"- `{file_path}`")
            if len(risk.missing_tests) > 10:
                lines.append(f"- ... and {len(risk.missing_tests) - 10} more")
            lines.append("")
        
        # Recommendations
        lines.extend([
            "## 💡 Recommendations",
            "",
        ])
        recommendations = self._generate_recommendations()
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")
        
        return "\n".join(lines)
    
    # ============================================================
    # Helper Methods
    # ============================================================
    
    def _count_modules_by_type(self) -> Dict[str, int]:
        """Count modules by type."""
        counts = {}
        for module in self.model.modules:
            mtype = module.type
            counts[mtype] = counts.get(mtype, 0) + 1
        return counts
    
    def _get_module_type_emoji(self, module_type: str) -> str:
        """Get emoji for module type."""
        emojis = {
            "service": "⚙️",
            "model": "💾",
            "controller": "🎮",
            "route": "🛣️",
            "utility": "🔧",
            "config": "⚙️",
            "test": "🧪",
        }
        return emojis.get(module_type, "📄")
    
    def _generate_recommendations(self) -> List[str]:
        """
        Generate actionable recommendations with priority and impact.
        
        Priority order:
        1. Safety issues (eval/exec) - CRITICAL
        2. Architecture issues (circular deps) - HIGH
        3. Coupling issues - MEDIUM
        4. Maintainability issues (large files, missing tests) - LOW
        """
        recommendations = []
        risk = self.model.risk
        total_modules = len([m for m in self.model.modules if m.type != 'test'])
        
        # 1. Safety issues - CRITICAL priority
        if risk.unsafe_patterns:
            unique_issues = len(set(p.split(': ')[-1] for p in risk.unsafe_patterns))
            recommendations.append(
                f"🔴 CRITICAL: Remove {len(risk.unsafe_patterns)} unsafe code patterns "
                f"(eval, exec, shell=True) - impacts security and reliability"
            )
        
        # 2. Architecture issues - HIGH priority
        if risk.circular_dependencies_detected:
            top_cycles = min(5, len(risk.circular_dependencies))
            recommendations.append(
                f"🟡 HIGH: Refactor {len(risk.circular_dependencies)} circular dependencies "
                f"(top {top_cycles} cycles shown above) - improves modularity"
            )
        
        # 3. Coupling issues - MEDIUM priority
        if risk.high_coupling_modules:
            recommendations.append(
                f"🟠 MEDIUM: Reduce coupling in {len(risk.high_coupling_modules)} modules "
                f"using dependency injection or interface abstraction"
            )
        
        # 4. Maintainability issues - LOW priority
        if risk.large_files:
            recommendations.append(
                f"🔵 LOW: Split {len(risk.large_files)} large files (>500 lines) into smaller, focused modules"
            )
        
        if risk.missing_tests and total_modules > 0:
            coverage = 100 - (len(risk.missing_tests) / total_modules * 100)
            target_coverage = min(80, coverage + 20)  # Realistic target
            recommendations.append(
                f"🔵 LOW: Increase test coverage from {coverage:.1f}% to {target_coverage:.0f}% "
                f"(add tests for {min(20, len(risk.missing_tests))} critical modules first)"
            )
        
        if not recommendations:
            recommendations.append(
                "✅ Project structure looks healthy! Continue following current best practices."
            )
        
        return recommendations[:5]  # Top 5 recommendations


def format_project_analysis(
    model: ProjectModel,
    include_sections: Optional[List[str]] = None,
    style: str = "markdown"
) -> str:
    """
    Convenience function to format complete project analysis.
    
    Args:
        model: ProjectModel from analyze()
        include_sections: List of sections to include (default: all)
                         Options: ["summary", "architecture", "risks", "modules", "tests"]
        style: Output style ("markdown", "console", "json")
    
    Returns:
        Formatted report string
    """
    formatter = ProjectFormatter(model)
    
    sections = include_sections or ["summary", "architecture", "risks"]
    
    output_parts = []
    
    if "summary" in sections:
        output_parts.append(formatter.executive_summary(style))
    
    if "architecture" in sections:
        output_parts.append(formatter.architecture_overview(include_tree=False))
    
    if "risks" in sections:
        output_parts.append(formatter.risk_assessment_report(detailed=True))
    
    return "\n\n".join(output_parts)
