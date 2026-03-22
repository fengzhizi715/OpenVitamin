"""
project.analyze Tool - Full Project Intelligence Analysis.

This tool exposes the Project Intelligence engine to AI programming agents.
It transforms a project from a "file collection" to a "structured engineering model".

Returns a comprehensive ProjectModel with 9 layers:
1. Meta - language, file count, size
2. Structure - directory tree, architecture layers
3. Modules - imports/exports, line count, type
4. Entry Points - HTTP server, CLI detection
5. Tests - framework, test dirs, coverage targets
6. Dependencies - package manager, external libs, internal graph
7. Framework - web framework, ORM, task queue
8. Build - Dockerfile, CI/CD
9. Risk Profile - large files, coupling, unsafe patterns

Usage:
    skill_id: builtin_project.analyze
    inputs: { "workspace": "/path/to/project" }
"""
from typing import Any, Dict, List
from pathlib import Path

from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from log import logger


class ProjectAnalyzeTool(Tool):
    """
    Full Project Intelligence analysis tool.
    
    Returns a structured ProjectModel that can be used by AI agents to:
    - Understand project architecture
    - Identify entry points and test structure
    - Assess engineering risks
    - Navigate dependencies
    """

    @property
    def name(self) -> str:
        return "project.analyze"

    @property
    def description(self) -> str:
        return (
            "Analyze a project and return a structured engineering model. "
            "Provides: meta info, directory structure, modules with imports/exports, "
            "entry points, test structure, dependencies, detected frameworks, "
            "build system info, and risk profile. "
            "Use this to understand a codebase before making changes."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "workspace": {
                "type": "string",
                "description": "The path to analyze. Supports: (1) Absolute paths like '/Users/name/Projects/my_project', (2) Relative paths like '../other_project' or './subdir', (3) Home paths like '~/my_project'. If omitted, analyzes the current session workspace.",
            },
            "include_tree": {
                "type": "boolean",
                "description": "Include full directory tree in output (default: false for brevity).",
                "default": False,
            },
            "detail_level": {
                "type": "string",
                "description": "Summary detail level: brief | detailed (default: brief).",
                "default": "brief",
            },
            "top_n_modules": {
                "type": "integer",
                "description": "Top modules to keep by line count (default: 20).",
                "default": 20,
            },
            "top_n_libs": {
                "type": "integer",
                "description": "Top external libraries to keep (default: 20).",
                "default": 20,
            },
            "top_n_risks": {
                "type": "integer",
                "description": "Top risk items to include in detailed summary (default: 10).",
                "default": 10,
            },
        }, required=[])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "meta": {
                    "type": "object",
                    "description": "Project metadata: language, file_count, size_kb",
                },
                "structure": {
                    "type": "object",
                    "description": "Directory structure and architecture layer inference",
                },
                "modules_count": {
                    "type": "integer",
                    "description": "Number of source modules found",
                },
                "entry_points": {
                    "type": "array",
                    "description": "Detected entry points (main.py, http server, etc.)",
                },
                "tests": {
                    "type": "object",
                    "description": "Test framework and structure",
                },
                "framework": {
                    "type": "object",
                    "description": "Detected frameworks (web, ORM, etc.)",
                },
                "build": {
                    "type": "object",
                    "description": "Build system and CI/CD info",
                },
                "risk": {
                    "type": "object",
                    "description": "Risk profile with score and issues",
                },
                "analysis_time_ms": {
                    "type": "integer",
                    "description": "Time taken for analysis",
                },
                "summary": {
                    "type": "string",
                    "description": "Human-readable summary for chat display.",
                },
            },
        }

    @property
    def required_permissions(self) -> List[str]:
        return ["file.read"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Project Analyze",
            "icon": "Brain",
            "category": "project",
            "permissions_hint": [
                {"key": "file.read", "label": "Read project files for analysis"}
            ],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """
        Execute Project Intelligence analysis.
        
        Supports analyzing projects at any path, not just within session workspace.
        """
        # Determine workspace - support absolute paths for external projects
        workspace_raw = input_data.get("workspace")
        
        # If workspace not provided in input, use context workspace (session workspace)
        if not workspace_raw:
            workspace_raw = ctx.workspace or "."
        
        # Expand user (~) and handle absolute vs relative paths
        workspace_expanded = str(Path(workspace_raw).expanduser())
        
        # If it's already an absolute path, use it directly
        if Path(workspace_expanded).is_absolute():
            workspace = workspace_expanded
        else:
            # For relative paths, resolve relative to context workspace
            # This maintains backward compatibility with existing behavior
            workspace = str((Path(ctx.workspace or ".").expanduser() / workspace_expanded).resolve())
        
        # Validate workspace exists
        if not Path(workspace).exists():
            logger.error(f"[project.analyze] Workspace does not exist: {workspace}")
            return ToolResult(
                success=False,
                data={"error": f"Workspace does not exist: {workspace}"},
                error=f"Workspace does not exist: {workspace}",
            )
        
        if not Path(workspace).is_dir():
            logger.error(f"[project.analyze] Workspace is not a directory: {workspace}")
            return ToolResult(
                success=False,
                data={"error": f"Workspace is not a directory: {workspace}"},
                error=f"Workspace is not a directory: {workspace}",
            )
        
        include_tree = input_data.get("include_tree", False)
        detail_level = str(input_data.get("detail_level") or "brief").strip().lower()
        if detail_level not in {"brief", "detailed"}:
            detail_level = "brief"
        try:
            top_n_modules = max(1, min(100, int(input_data.get("top_n_modules", 20))))
        except Exception:
            top_n_modules = 20
        try:
            top_n_libs = max(1, min(100, int(input_data.get("top_n_libs", 20))))
        except Exception:
            top_n_libs = 20
        try:
            top_n_risks = max(1, min(50, int(input_data.get("top_n_risks", 10))))
        except Exception:
            top_n_risks = 10
        
        # Import and run analysis
        try:
            from core.project_intelligence import analyze
            
            logger.info(f"[project.analyze] Analyzing workspace: {workspace}")
            
            model = analyze(workspace)
            
            # Build output - omit full tree by default for brevity
            output = model.to_dict()
            modules_all = output.get("modules") if isinstance(output.get("modules"), list) else []
            external_libs_all = (
                output.get("dependencies", {}).get("external_libs")
                if isinstance(output.get("dependencies"), dict)
                else []
            )
            if not isinstance(external_libs_all, list):
                external_libs_all = []
            
            if not include_tree:
                # Replace full tree with summary
                output["structure"]["tree_summary"] = {
                    "directory_count": output["structure"]["directory_count"],
                    "max_depth": output["structure"]["max_depth"],
                }
                output["structure"]["tree"] = []  # Clear for brevity
            
            # Also omit full module list for brevity, keep count
            output["modules_count"] = len(modules_all)
            module_type_stats: Dict[str, int] = {}
            for m in modules_all:
                if not isinstance(m, dict):
                    continue
                mtype = str(m.get("type") or "unknown")
                module_type_stats[mtype] = module_type_stats.get(mtype, 0) + 1
            output["module_type_stats"] = module_type_stats
            output["external_libs_total"] = len(external_libs_all)
            
            # Keep only top N modules by line count for context
            if output.get("modules"):
                sorted_modules = sorted(
                    output["modules"],
                    key=lambda m: m.get("lines", 0),
                    reverse=True
                )[:top_n_modules]
                output["modules"] = sorted_modules
            
            # Keep only top N external libs
            if output.get("dependencies", {}).get("external_libs"):
                output["dependencies"]["external_libs"] = output["dependencies"]["external_libs"][:top_n_libs]

            output["summary"] = self._build_summary(
                output=output,
                detail_level=detail_level,
                top_n_risks=top_n_risks,
            )
            
            logger.info(
                f"[project.analyze] Complete: {output['meta']['language']}, "
                f"{output['meta']['file_count']} files, risk score {output['risk']['risk_score']}"
            )
            
            return ToolResult(
                success=True,
                data=output,
            )
            
        except Exception as e:
            logger.error(f"[project.analyze] Error: {e}")
            return ToolResult(
                success=False,
                error=f"Project analysis failed: {str(e)}",
            )

    @staticmethod
    def _build_summary(output: Dict[str, Any], detail_level: str, top_n_risks: int) -> str:
        """
        Build a human-readable summary using the ProjectFormatter.
        
        This method now delegates to the formatter for better presentation.
        """
        try:
            # Reconstruct minimal ProjectModel from output dict
            from core.project_intelligence import ProjectModel, ProjectMeta, ProjectStructure
            from core.project_intelligence.model import (
                LayeredGuess, TestInfo, DependencyInfo, FrameworkInfo, 
                BuildInfo, RiskProfile, ModuleInfo, EntryPoint
            )
            
            # Reconstruct model (minimal version for formatting)
            model = ProjectModel()
            
            # Meta
            meta_dict = output.get("meta", {})
            if isinstance(meta_dict, dict):
                model.meta = ProjectMeta(
                    language=meta_dict.get("language", "unknown"),
                    languages_detected=meta_dict.get("languages_detected", []),
                    repo_root=meta_dict.get("repo_root", "."),
                    file_count=meta_dict.get("file_count", 0),
                    size_kb=meta_dict.get("size_kb", 0),
                    monorepo=meta_dict.get("monorepo", False),
                )
            
            # Structure
            struct_dict = output.get("structure", {})
            if isinstance(struct_dict, dict):
                layer_dict = struct_dict.get("layered_guess", {})
                if isinstance(layer_dict, dict):
                    model.structure.layered_guess = LayeredGuess(
                        presentation=layer_dict.get("presentation", []),
                        service=layer_dict.get("service", []),
                        data=layer_dict.get("data", []),
                        utils=layer_dict.get("utils", []),
                        config=layer_dict.get("config", []),
                    )
                model.structure.directory_count = struct_dict.get("directory_count", 0)
                model.structure.max_depth = struct_dict.get("max_depth", 0)
            
            # Modules
            modules_list = output.get("modules", [])
            if isinstance(modules_list, list):
                model.modules = [
                    ModuleInfo(
                        name=m.get("name", ""),
                        path=m.get("path", ""),
                        type=m.get("type", "unknown"),
                        exports=m.get("exports", []),
                        imports=m.get("imports", []),
                        lines=m.get("lines", 0),
                        has_tests=m.get("has_tests", False),
                    )
                    for m in modules_list[:20]  # Limit for performance
                ]
            
            # Entry points
            ep_list = output.get("entry_points", [])
            if isinstance(ep_list, list):
                from core.project_intelligence.model import EntryPointType
                model.entry_points = [
                    EntryPoint(
                        file=ep.get("file", ""),
                        type=ep.get("type", "unknown"),
                        framework=ep.get("framework"),
                        port=ep.get("port"),
                    )
                    for ep in ep_list[:10]
                ]
            
            # Tests
            tests_dict = output.get("tests", {})
            if isinstance(tests_dict, dict):
                model.tests = TestInfo(
                    framework=tests_dict.get("framework"),
                    test_dirs=tests_dict.get("test_dirs", []),
                    test_files=tests_dict.get("test_files", []),
                    coverage_target_guess=tests_dict.get("coverage_target_guess", []),
                    has_fixtures=tests_dict.get("has_fixtures", False),
                    has_mocks=tests_dict.get("has_mocks", False),
                )
            
            # Dependencies
            deps_dict = output.get("dependencies", {})
            if isinstance(deps_dict, dict):
                model.dependencies = DependencyInfo(
                    package_manager=deps_dict.get("package_manager"),
                    requirements_files=deps_dict.get("requirements_files", []),
                    external_libs=deps_dict.get("external_libs", []),
                    internal_graph=deps_dict.get("internal_graph", {}),
                    dev_dependencies=deps_dict.get("dev_dependencies", []),
                )
            
            # Framework
            fw_dict = output.get("framework", {})
            if isinstance(fw_dict, dict):
                model.framework = FrameworkInfo(
                    web_framework=fw_dict.get("web_framework"),
                    orm=fw_dict.get("orm"),
                    task_queue=fw_dict.get("task_queue"),
                    frontend=fw_dict.get("frontend"),
                    testing=fw_dict.get("testing"),
                    database=fw_dict.get("database"),
                    is_kmp=fw_dict.get("is_kmp", False),
                    kmp_targets=fw_dict.get("kmp_targets", []),
                    kmp_source_sets=fw_dict.get("kmp_source_sets", []),
                )
            
            # Build
            build_dict = output.get("build", {})
            if isinstance(build_dict, dict):
                model.build = BuildInfo(
                    type=build_dict.get("type", "unknown"),
                    has_makefile=build_dict.get("has_makefile", False),
                    has_dockerfile=build_dict.get("has_dockerfile", False),
                    dockerfile_path=build_dict.get("dockerfile_path"),
                    ci_detected=build_dict.get("ci_detected", False),
                    ci_files=build_dict.get("ci_files", []),
                    build_commands=build_dict.get("build_commands", []),
                    cmake=build_dict.get("cmake"),
                )
            
            # Risk
            risk_dict = output.get("risk", {})
            if isinstance(risk_dict, dict):
                model.risk = RiskProfile(
                    large_files=risk_dict.get("large_files", []),
                    high_coupling_modules=risk_dict.get("high_coupling_modules", []),
                    circular_dependencies_detected=risk_dict.get("circular_dependencies_detected", False),
                    circular_dependencies=risk_dict.get("circular_dependencies", []),
                    unsafe_patterns=risk_dict.get("unsafe_patterns", []),
                    missing_tests=risk_dict.get("missing_tests", []),
                    deprecated_patterns=risk_dict.get("deprecated_patterns", []),
                    risk_score=risk_dict.get("risk_score", 0),
                )
            
            # Use formatter to generate beautiful output
            from core.project_intelligence.formatter import format_project_analysis
            
            # Choose output style based on detail level
            if detail_level == "detailed":
                return format_project_analysis(
                    model=model,
                    include_sections=["summary", "architecture", "risks"],
                    style="markdown"
                )
            else:
                # Brief mode: just executive summary
                from core.project_intelligence.formatter import ProjectFormatter
                formatter = ProjectFormatter(model)
                return formatter.executive_summary(style="markdown")
        
        except Exception as e:
            logger.warning(f"[project.analyze] Formatter failed, falling back to legacy summary: {e}")
            # Fallback to legacy summary if formatter fails
            return ProjectAnalyzeTool._build_summary_legacy(output, detail_level, top_n_risks)
    
    @staticmethod
    def _build_summary_legacy(output: Dict[str, Any], detail_level: str, top_n_risks: int) -> str:
        """
        Legacy summary builder (kept as fallback).
        """
        meta = output.get("meta", {}) if isinstance(output.get("meta"), dict) else {}
        structure = output.get("structure", {}) if isinstance(output.get("structure"), dict) else {}
        tests = output.get("tests", {}) if isinstance(output.get("tests"), dict) else {}
        deps = output.get("dependencies", {}) if isinstance(output.get("dependencies"), dict) else {}
        framework = output.get("framework", {}) if isinstance(output.get("framework"), dict) else {}
        build = output.get("build", {}) if isinstance(output.get("build"), dict) else {}
        risk = output.get("risk", {}) if isinstance(output.get("risk"), dict) else {}
    
        lines = [
            "Project Intelligence 摘要：",
            f"- repo_root: {meta.get('repo_root') or 'N/A'}",
            f"- language: {meta.get('language') or 'unknown'}",
            f"- files: {meta.get('file_count') if meta.get('file_count') is not None else 'N/A'}",
            f"- size_kb: {meta.get('size_kb') if meta.get('size_kb') is not None else 'N/A'}",
            f"- modules_count: {output.get('modules_count', 'N/A')}",
            f"- test_framework: {tests.get('framework') or 'unknown'}",
            f"- package_manager: {deps.get('package_manager') or 'unknown'}",
            f"- risk_score: {risk.get('risk_score', 'N/A')}",
        ]
        if detail_level != "detailed":
            return "\n".join(lines)
    
        # detailed extension
        test_dirs = tests.get("test_dirs") if isinstance(tests.get("test_dirs"), list) else []
        test_files = tests.get("test_files") if isinstance(tests.get("test_files"), list) else []
        ext_libs = deps.get("external_libs") if isinstance(deps.get("external_libs"), list) else []
        ci_files = build.get("ci_files") if isinstance(build.get("ci_files"), list) else []
        issues = risk.get("issues") if isinstance(risk.get("issues"), list) else []
        layer = structure.get("layered_guess", {}) if isinstance(structure.get("layered_guess"), dict) else {}
        modules = output.get("modules") if isinstance(output.get("modules"), list) else []
        module_stats = output.get("module_type_stats", {}) if isinstance(output.get("module_type_stats"), dict) else {}
        entry_points = output.get("entry_points") if isinstance(output.get("entry_points"), list) else []
        missing_tests = risk.get("missing_tests") if isinstance(risk.get("missing_tests"), list) else []
        large_files = risk.get("large_files") if isinstance(risk.get("large_files"), list) else []
        coupling = risk.get("high_coupling_modules") if isinstance(risk.get("high_coupling_modules"), list) else []
        unsafe_patterns = risk.get("unsafe_patterns") if isinstance(risk.get("unsafe_patterns"), list) else []
        circular = risk.get("circular_dependencies") if isinstance(risk.get("circular_dependencies"), list) else []
    
        lines.extend([
            "",
            "项目概览",
            f"主要语言：{meta.get('language') or 'unknown'}",
            f"检测到的语言：{', '.join(meta.get('languages_detected') or []) or 'unknown'}",
            f"文件总数：{meta.get('file_count') if meta.get('file_count') is not None else 'N/A'}",
            f"项目大小：{meta.get('size_kb') if meta.get('size_kb') is not None else 'N/A'} KB",
            f"目录数：{structure.get('directory_count', 'N/A')}",
            f"最大深度：{structure.get('max_depth', 'N/A')}",
            f"分析耗时：{output.get('analysis_time_ms', 'N/A')}ms",
            "",
            "架构结构",
            f"Presentation 层：{len(layer.get('presentation') or [])} 个目录",
            f"Service 层：{len(layer.get('service') or [])} 个目录",
            f"Data 层：{len(layer.get('data') or [])} 个目录",
            f"Utils 层：{len(layer.get('utils') or [])} 个目录",
            f"Config 层：{len(layer.get('config') or [])} 个目录",
            "",
            f"模块统计（{output.get('modules_count', len(modules))} 个模块）",
            "按类型分布：",
        ])
        if module_stats:
            for k, v in sorted(module_stats.items(), key=lambda kv: -int(kv[1])):
                lines.append(f"{k}: {v}")
        else:
            lines.append("unknown: N/A")
    
        lines.append(f"Top {len(modules)} 模块（按行数）：")
        for m in modules:
            name = m.get("name") or m.get("path") or "unknown"
            lines_count = m.get("lines", 0)
            mtype = m.get("type", "unknown")
            # 简化路径显示，只显示文件名和最后一级目录
            path_parts = name.split('/')
            display_name = '/'.join(path_parts[-2:]) if len(path_parts) > 1 else name
            lines.append(f"{display_name} — {lines_count} 行（{mtype}）")
    
        lines.extend([
            "",
            "入口点",
            f"检测到 {len(entry_points)} 个入口点：",
        ])
        if entry_points:
            for ep in entry_points:
                if isinstance(ep, dict):
                    ep_file = ep.get('file', 'unknown')
                    ep_type = ep.get('type', 'unknown')
                    # 简化路径显示
                    display_file = '/'.join(ep_file.split('/')[-2:]) if '/' in ep_file else ep_file
                    lines.append(f"{display_file} ({ep_type})")
        else:
            lines.append("未检测到明显入口点（可能是库文件或需要手动指定启动方式）")
    
        lines.extend([
            "",
            "测试分析",
            f"测试框架：{tests.get('framework') or 'unknown'}",
            f"测试目录：{len(test_dirs)} 个",
            f"测试文件：{len(test_files)} 个",
        ])
        if test_files:
            for tf in test_files[:20]:
                display_file = '/'.join(str(tf).split('/')[-2:]) if '/' in str(tf) else str(tf)
                lines.append(display_file)
        else:
            lines.append("未检测到测试文件（建议添加单元测试）")
    
        lines.extend([
            "",
            "依赖分析",
            f"包管理器：{deps.get('package_manager') or '未检测到'}",
            f"外部库：{output.get('external_libs_total', len(ext_libs))} 个",
        ])
        if ext_libs:
            # 过滤掉一些常见的标准库导入，让输出更有意义
            meaningful_libs = [lib for lib in ext_libs[:15] if lib.lower() not in ['io', 'os', 'sys', 'path', 'time', 'datetime', 'collections', 'typing', 'functools', 'itertools']]
            if meaningful_libs:
                lines.append(f"主要库：{', '.join(meaningful_libs[:10])}")
            else:
                lines.append(f"主要库：{', '.join(ext_libs[:10])}")
        else:
            lines.append("主要库：none")
            
        lines.append(f"内部依赖图：{len(deps.get('internal_graph') or {})} 个模块")
    
        lines.extend([
            "",
            "框架检测",
            f"web_framework: {framework.get('web_framework') or 'none'}",
            f"orm: {framework.get('orm') or 'none'}",
            f"frontend: {framework.get('frontend') or 'none'}",
            f"testing: {framework.get('testing') or 'none'}",
        ])
            
        # Kotlin Multiplatform 特殊处理
        if framework.get('is_kmp'):
            lines.extend([
                "",
                "Kotlin Multiplatform 项目",
                f"目标平台：{', '.join(framework.get('kmp_targets', [])) or 'none'}",
                f"Source Sets: {', '.join(framework.get('kmp_source_sets', [])) or 'none'}",
            ])
    
        lines.extend([
            "",
            "构建系统",
            f"类型：{build.get('type') or 'unknown'}",
        ])
            
        # CMake 特殊处理
        if build.get('cmake'):
            cmake_info = build['cmake']
            if cmake_info.get('project_name'):
                lines.append(f"CMake 项目名：{cmake_info['project_name']}")
            if cmake_info.get('executables'):
                lines.append(f"可执行文件：{', '.join(cmake_info['executables'])}")
            if cmake_info.get('libraries'):
                lines.append(f"库：{', '.join(cmake_info['libraries'])}")
            
        lines.extend([
            f"Makefile：{'有' if build.get('has_makefile') else '无'}",
            f"Dockerfile：{'有' if build.get('has_dockerfile') else '无'}",
            f"CI/CD：{'已检测' if build.get('ci_detected') else '未检测'}",
        ])
        if ci_files:
            display_ci = ['/'.join(f.split('/')[-2:]) for f in ci_files[:5]]
            lines.append(f"CI 文件：{', '.join(display_ci)}")
    
        lines.extend([
            "",
            f"风险评分：{risk.get('risk_score', 'N/A')}/100",
        ])
            
        if large_files:
            lines.append(f"大文件（>500 行）：{len(large_files)} 个")
            for f in large_files[:top_n_risks]:
                display_file = '/'.join(str(f).split('/')[-3:]) if '/' in str(f) else str(f)
                lines.append(f"  - {display_file}")
        else:
            lines.append("大文件（>500 行）：0 个")
            
        lines.append(f"高耦合模块：{len(coupling)}")
        lines.append(f"循环依赖：{'检测到' if risk.get('circular_dependencies_detected') else '未检测到'}")
        if circular:
            for chain in circular[:top_n_risks]:
                if isinstance(chain, list):
                    display_chain = ' -> '.join(str(x).split('/')[-1] for x in chain)
                    lines.append(f"  {display_chain}")
        lines.append(f"不安全模式：{len(unsafe_patterns)}")
            
        if missing_tests:
            lines.append(f"缺失测试：{len(missing_tests)} 个文件")
            for f in missing_tests[:min(top_n_risks, 10)]:
                display_file = '/'.join(str(f).split('/')[-3:]) if '/' in str(f) else str(f)
                lines.append(f"  - {display_file}")
        else:
            lines.append("缺失测试：0 个文件")
    
        if issues:
            lines.append("\n风险条目（Top）：")
            for issue in issues[:top_n_risks]:
                lines.append(f"- {issue}")
            
        return "\n".join(lines)
