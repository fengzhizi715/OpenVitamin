"""
Built-in composite Skills (workflow type).
These Skills combine multiple Tools to provide higher-level capabilities.
"""
from datetime import datetime
from core.skills.models import Skill
from core.skills.service import get_skill_store
from core.skills.registry import SkillRegistry
from log import logger


def register_builtin_composite_skills():
    """Register all built-in composite skills."""
    store = get_skill_store()
    skills_to_register = [
        _create_research_skill(),
        _create_document_skill(),
        _create_data_analysis_skill(),
        _create_api_operator_skill(),
        _create_knowledge_base_skill(),
        _create_code_assistant_skill(),
        _create_project_tree_skill(),  # V2.2: project tree skill
        _create_project_detect_skill(),  # V2.2: project type detection (call via skill in plan)
        _create_project_analyze_skill(),  # V2.3: Project Intelligence
    ]
    
    registered = 0
    for skill_def in skills_to_register:
        skill_id = skill_def["id"]
        existing = store.get(skill_id)
        if existing:
            # Update existing skill
            updated_skill = store.update(
                skill_id=skill_id,
                name=skill_def["name"],
                description=skill_def["description"],
                category=skill_def["category"],
                type=skill_def["type"],
                definition=skill_def["definition"],
                input_schema=skill_def["input_schema"],
                enabled=True,
            )
            if updated_skill:
                SkillRegistry.register(updated_skill)
                logger.info(f"[Skills] Updated built-in composite skill: {skill_id}")
        else:
            # Create new skill
            skill = store.create(
                name=skill_def["name"],
                description=skill_def["description"],
                category=skill_def["category"],
                type=skill_def["type"],
                definition=skill_def["definition"],
                input_schema=skill_def["input_schema"],
                enabled=True,
                skill_id=skill_id,
            )
            if skill:
                SkillRegistry.register(skill)
                registered += 1
                logger.info(f"[Skills] Registered built-in composite skill: {skill_id}")
    
    return registered


def _create_research_skill() -> dict:
    """Research & Summarize Skill: web.search + text.split + optional python.run"""
    return {
        "id": "builtin_research.summarize",
        "name": "Research & Summarize",
        "description": "Search the web for information and summarize findings. Can optionally use Python for data analysis.",
        "category": "research",
        # High-level guidance skill: deterministic prompt (LLM summarization happens in AgentLoop, not inside SkillExecutor)
        "type": "prompt",
        "definition": {
            "prompt_template": (
                "You are in Research mode.\n"
                "Goal: research the topic and summarize with sources.\n\n"
                "User query: {{query}}\n\n"
                "Steps:\n"
                "1) Use skill `builtin_web.search` to search the web for the query.\n"
                "2) From the search results, extract 3-7 key facts. Use `builtin_text.split` / `builtin_text.truncate` as needed.\n"
                "3) Write a concise summary, then list sources.\n\n"
                "Output format:\n"
                "- Summary: ...\n"
                "- Key points:\n"
                "  - ...\n"
                "- Sources:\n"
                "  - ...\n"
            )
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research query or topic to search"
                }
            },
            "required": ["query"]
        }
    }


def _create_document_skill() -> dict:
    """Read & Analyze Documents Skill: file.read + file.list + text utilities"""
    return {
        "id": "builtin_document.analyze",
        "name": "Read & Analyze Documents",
        "description": "Read and analyze documents (PDF, MD, TXT). Can batch process multiple files and extract key points.",
        "category": "document",
        "type": "prompt",
        "definition": {
            "prompt_template": (
                "You are in Document Analysis mode.\n"
                "Goal: read local documents in the current workspace and extract structured insights.\n\n"
                "Target file (relative path): {{file_path}}\n\n"
                "Steps:\n"
                "1) Use `builtin_file.read` to read the file content.\n"
                "2) If the file is long, use `builtin_text.truncate` / `builtin_text.split` to chunk it.\n"
                "3) Extract key points and return a structured output.\n\n"
                "Output format (JSON):\n"
                "{\n"
                "  \"file\": \"{{file_path}}\",\n"
                "  \"summary\": \"...\",\n"
                "  \"key_points\": [\"...\"],\n"
                "  \"questions\": [\"...\"],\n"
                "  \"tags\": [\"...\"]\n"
                "}\n"
            )
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the document file to read"
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to list files from (optional, for batch processing)"
                },
                "extract_pattern": {
                    "type": "string",
                    "description": "Optional regex pattern to extract specific information"
                }
            },
            "required": ["file_path"]
        }
    }


def _create_data_analysis_skill() -> dict:
    """Analyze Data with Python Skill: python.run + file.read/write"""
    return {
        "id": "builtin_data.analyze",
        "name": "Analyze Data with Python",
        "description": "Analyze data using Python code. Can read data files, perform analysis, and write results.",
        "category": "analysis",
        "type": "prompt",
        "definition": {
            "prompt_template": (
                "You are in Data Analysis mode.\n"
                "Goal: write Python code to analyze data and report conclusions.\n\n"
                "Data file (relative path, optional): {{data_file}}\n"
                "User request: {{request}}\n\n"
                "Rules:\n"
                "- Prefer reading files via `builtin_file.read` (workspace-relative paths).\n"
                "- Execute analysis via `builtin_python.run`.\n"
                "- If you generate outputs (csv/json/md), write via `builtin_file.write`.\n\n"
                "Deliver:\n"
                "- A short explanation of the approach\n"
                "- Key results\n"
                "- The Python code you ran (or a summary)\n"
            )
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "data_file": {
                    "type": "string",
                    "description": "Path to the data file to analyze (optional, can be read in Python code)"
                },
                "request": {
                    "type": "string",
                    "description": "What analysis to perform / what questions to answer"
                },
                "analysis_code": {
                    "type": "string",
                    "description": "Python code to analyze the data"
                },
                "output_file": {
                    "type": "string",
                    "description": "Optional path to write analysis results"
                }
            },
            # Keep analysis_code optional at the Skill level; the Agent may generate it.
            "required": []
        }
    }


def _create_api_operator_skill() -> dict:
    """Call External API Skill: http.request"""
    return {
        "id": "builtin_api.operator",
        "name": "Call External API",
        "description": "Call external APIs (REST, GraphQL, etc.). Supports authentication, custom headers, and various HTTP methods.",
        "category": "api",
        # A thin wrapper around http.request (still deterministic)
        "type": "tool",
        "definition": {"tool_name": "http.request", "tool_args_mapping": {}},
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET, POST, PUT, DELETE, etc.)",
                    "default": "GET"
                },
                "url": {
                    "type": "string",
                    "description": "API endpoint URL"
                },
                "headers": {
                    "type": "object",
                    "description": "HTTP headers (optional)"
                },
                "body": {
                    "type": "string",
                    "description": "Request body (for POST, PUT, etc.)"
                },
                "params": {
                    "type": "object",
                    "description": "URL query parameters (optional)"
                },
                "auth": {
                    "type": "object",
                    "description": "Authentication config: {type: 'bearer'|'basic', token|username, password}"
                },
                "timeout": {
                    "type": "number",
                    "description": "Request timeout in seconds",
                    "default": 30
                }
            },
            "required": ["url"]
        }
    }


def _create_knowledge_base_skill() -> dict:
    """
    Query Knowledge Base Skill: RAG wrapper
    
    Note: This skill wraps RAG functionality. Since RAG is a Plugin (not a Tool),
    we'll need to create a special Tool wrapper or use a different approach.
    For now, we'll create a workflow that uses file operations to interact with KB.
    Actually, RAG is handled at the Agent level, so this skill should provide
    a simpler interface for agents to query knowledge bases.
    """
    return {
        "id": "builtin_kb.query",
        "name": "Query Knowledge Base",
        "description": "Query knowledge bases using RAG. This skill provides a high-level interface for knowledge retrieval.",
        "category": "rag",
        "type": "prompt",  # Use prompt type for now, as RAG is handled at Agent level
        "definition": {
            "prompt_template": (
                "You are querying the Knowledge Base (RAG).\n"
                "Query: {{query}}\n\n"
                "Notes:\n"
                "- RAG retrieval is handled by the system when the Agent has rag_ids configured.\n"
                "- Ask a clear, specific question, then use retrieved context to answer.\n\n"
                "Output:\n"
                "- Answer (grounded in retrieved context when available)\n"
                "- If context is insufficient, say so and propose next query.\n"
            )
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query to search in knowledge base"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 50
                }
            },
            "required": ["query"]
        }
    }


def _create_code_assistant_skill() -> dict:
    """Read / Write / Refactor Code Skill: file.read + file.write + text.diff"""
    return {
        "id": "builtin_code.assistant",
        "name": "Code Assistant",
        "description": "Read, write, and refactor code. Can analyze code files, make changes, and show diffs.",
        "category": "code",
        "type": "prompt",
        "definition": {
            "prompt_template": (
                "You are in Code Assistant mode.\n"
                "Goal: read / modify / refactor code in the local workspace.\n\n"
                "Target file: {{file_path}}\n\n"
                "Steps:\n"
                "1) Use `builtin_file.read` to inspect the file.\n"
                "2) Propose changes and generate a patch (or new content).\n"
                "3) Use `builtin_text.diff` to show the diff.\n"
                "4) If approved by the user, apply via `builtin_file.write`.\n\n"
                "Rules:\n"
                "- Only edit workspace-relative paths.\n"
                "- Be explicit and deterministic.\n"
            )
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the code file to read"
                },
            },
            "required": ["file_path"]
        }
    }


def _create_project_tree_skill() -> dict:
    """Project Tree Skill: Generate directory tree structure."""
    return {
        "id": "builtin_project.tree",
        "name": "Project Tree",
        "description": "Generate a tree view of project directory structure. Shows file hierarchy up to specified depth.",
        "category": "file",
        "type": "tool",
        "definition": {
            "tool_name": "file.tree",
            "tool_params": {
                "path": "{{path}}",
                "max_depth": "{{max_depth}}"
            }
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Root directory path (relative to workspace or absolute)"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum depth to display (default: 3)",
                    "default": 3
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files (default: false)",
                    "default": False
                }
            },
            "required": ["path"]
        }
    }


def _create_project_analyze_skill() -> dict:
    """Project Analyze Skill: Full Project Intelligence analysis (V2.3)."""
    return {
        "id": "builtin_project.analyze",
        "name": "Analyze Project",
        "description": "Analyze a project and return a structured engineering model. Provides: meta info, directory structure, modules with imports/exports, entry points, test structure, dependencies, detected frameworks, build system info, and risk profile. Use this to understand a codebase before making changes.",
        "category": "project",
        "type": "tool",
        "definition": {
            "tool_name": "project.analyze",
            "tool_args_mapping": {},
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "The path to analyze. Supports: (1) Absolute paths like '/Users/name/Projects/my_project', (2) Relative paths like '../other_project' or './subdir', (3) Home paths like '~/my_project'. If omitted, analyzes the current session workspace.",
                },
                "include_tree": {
                    "type": "boolean",
                    "description": "Include full directory tree in output (default: false for brevity).",
                    "default": False,
                },
            },
            "required": [],
        },
    }


def _create_project_detect_skill() -> dict:
    """Project Detect Skill: detect project type and infer test/build commands (V2.2)."""
    return {
        "id": "builtin_project.detect",
        "name": "Detect Project",
        "description": "Detect project type (Python, Node, Rust, Go, Java, etc.) from workspace and infer test_command and build_command.",
        "category": "project",
        "type": "tool",
        "definition": {
            "tool_name": "project.detect",
            "tool_args_mapping": {},
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace root path to scan (optional; defaults to context workspace).",
                },
            },
            "required": [],
        },
    }
