"""
Configure AI Programming Agent for development tasks.

Supports:
- Add new API endpoint
- Add new service
- Add utility function

This script configures:
1. Optimized system_prompt
2. intent_rules for task detection
3. skill_param_extractors for parameter handling
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(project_root))

from core.agent_runtime.definition import get_agent_registry, AgentDefinition
from log import logger


# ============================================================================
# System Prompt for Development Tasks
# ============================================================================

DEV_AGENT_SYSTEM_PROMPT = """You are an expert software developer working on this codebase.

## Core Principles

1. **Analyze Before Acting**: Always understand the project structure first
2. **Follow Existing Patterns**: Match coding style, naming conventions, and architecture
3. **Write Production-Ready Code**: Include error handling, type hints, and documentation
4. **Test Your Changes**: Verify your work runs correctly

## Development Workflow

### Step 1: Project Analysis
Before making any changes, use `builtin_project.analyze` to:
- Understand project structure and layers
- Identify existing patterns and conventions
- Find similar files to use as references

### Step 2: Code Writing
When creating new code:

1. **For New API Endpoints**:
   - Find existing API files in the project
   - Match the existing routing pattern (FastAPI/Flask/etc.)
   - Include: route definition, request validation, error handling, response schema
   - Register the route in the main router file if needed

2. **For New Services**:
   - Identify the service layer location
   - Follow existing service class patterns
   - Include: constructor with dependencies, public methods, error handling
   - Add to dependency injection if the project uses it

3. **For Utility Functions**:
   - Locate the utils directory or similar
   - Create focused, single-responsibility functions
   - Include type hints and docstrings
   - Consider edge cases and error conditions

### Step 3: File Operations
Use the appropriate file tools:
- `file.write` for new files
- `file.append` for adding to existing files
- `file.apply_patch` for modifying existing code (preferred for changes)

### Step 4: Verification
After making changes:
1. Run `project.test` to verify nothing is broken
2. Check syntax with `python.run` if applicable
3. Report success or fix issues

## Code Style Guidelines

- Use consistent naming: snake_case for Python, camelCase for JS/TS
- Add docstrings to public functions/classes
- Include type annotations where possible
- Handle errors gracefully with appropriate HTTP status codes
- Keep functions focused and under 50 lines when possible

## Important Rules

- Never delete existing code unless explicitly asked
- Always create backups before modifications (file.apply_patch does this automatically)
- If uncertain about project conventions, check similar files first
- Report what you did and where the changes were made
"""


# ============================================================================
# Intent Rules for Development Tasks
# ============================================================================

DEV_INTENT_RULES = [
    # ================================================================
    # Mode A: Project Analysis Rules
    # ================================================================
    {
        "keywords": [
            "分析项目", "项目结构", "架构分析", "了解项目", "项目信息",
            "analyze project", "project structure", "understand project",
        ],
        "skills": ["builtin_project.analyze"],
        "description": "Project analysis mode",
        "task_type": "analyze_project",
    },
    
    # ================================================================
    # Mode B: Test-driven Fixing Rules
    # ================================================================
    {
        "keywords": [
            "测试失败", "修复bug", "运行测试", "测试不通过", "测试报错",
            "fix test", "test failed", "run test", "fix bug",
        ],
        "skills": ["builtin_project.detect"],
        "description": "Test-driven fixing mode",
        "task_type": "fix_test",
    },
    
    # ================================================================
    # Mode C: API Creation Rules
    # ================================================================
    {
        "keywords": [
            # Chinese
            "新增api", "添加api", "创建api", "写个api", "加个接口",
            "新增接口", "添加接口", "创建接口", "写个接口",
            "增加一个api", "加一个api", "新建api",
            # English
            "add api", "create api", "new api", "add endpoint",
            "create endpoint", "new endpoint", "add a api",
            "create a new api", "implement api", "implement endpoint",
        ],
        "skills": ["builtin_project.analyze"],
        "description": "Create new API endpoint - triggers project analysis first",
        "task_type": "create_api",
    },
    {
        "regex": r"(新增|添加|创建|写个?|加个?)\s*(REST|rest|Rest)?\s*API",
        "skills": ["builtin_project.analyze"],
        "description": "Create new REST API (regex pattern)",
    },
    
    # ================================================================
    # Mode C: Service Creation Rules
    # ================================================================
    {
        "keywords": [
            # Chinese
            "新增service", "添加service", "创建service", "写个service",
            "新增服务", "添加服务", "创建服务", "写个服务",
            "加个service", "增加service", "新建service",
            # English
            "add service", "create service", "new service",
            "add a service", "create a new service", "implement service",
        ],
        "skills": ["builtin_project.analyze"],
        "description": "Create new service - triggers project analysis first",
        "task_type": "create_service",
    },
    {
        "regex": r"(新增|添加|创建|写个?|加个?)\s*(业务)?服务\s*(类|class)?",
        "skills": ["builtin_project.analyze"],
        "description": "Create new service class (regex pattern)",
    },
    
    # ================================================================
    # Mode C: Utility Function Rules
    # ================================================================
    {
        "keywords": [
            # Chinese
            "新增工具函数", "添加工具函数", "创建工具函数", "写个工具函数",
            "新增util", "添加util", "创建util", "写个util",
            "加个工具函数", "增加工具函数", "新建工具函数",
            "新增工具方法", "添加工具方法",
            # English
            "add utility function", "create utility function", "new utility function",
            "add util", "create util", "new util",
            "add a helper function", "create a helper function",
        ],
        "skills": ["builtin_project.analyze"],
        "description": "Create new utility function - triggers project analysis first",
        "task_type": "create_utility",
    },
    {
        "regex": r"(新增|添加|创建|写个?|加个?)\s*(工具|辅助|util)\s*(函数|方法|function)",
        "skills": ["builtin_project.analyze"],
        "description": "Create utility function (regex pattern)",
    },
    
    # ================================================================
    # General Development Rules
    # ================================================================
    {
        "keywords": [
            "开发任务", "写代码", "coding", "implement", "implementation",
            "帮我写", "帮我创建", "帮我添加",
        ],
        "skills": ["builtin_project.analyze"],
        "description": "General development task - analyze first",
    },
]


# ============================================================================
# Skill Parameter Extractors
# ============================================================================

DEV_SKILL_PARAM_EXTRACTORS = {
    # For file.write - extract content from user description
    "file.write": {
        "content": {
            "enabled": True,
            "source": "user_input",  # Content comes from LLM generation
        },
        "path": {
            "enabled": True,
            "source": "extract",  # Extract path from user input
        },
    },
    
    # For file.apply_patch - patch content from LLM
    "file.apply_patch": {
        "patch": {
            "enabled": True,
            "source": "user_input",  # Patch content from LLM
        },
    },
    
    # For project.analyze - configure detail level
    "builtin_project.analyze": {
        "workspace": {
            "enabled": True,
            "default": ".",  # Current workspace
        },
        "detail_level": {
            "enabled": True,
            "default": "detailed",  # Detailed analysis for dev tasks
        },
    },
}


# ============================================================================
# Configuration Function
# ============================================================================

def configure_dev_agent(agent_id: str = None) -> bool:
    """
    Configure an agent for development tasks.
    
    Args:
        agent_id: Optional agent ID. If not provided, finds first AI programming agent.
    
    Returns:
        True if successful, False otherwise
    """
    registry = get_agent_registry()

    # Find agent
    if agent_id:
        agent = registry.get_agent(agent_id)
        if not agent:
            logger.error(f"Agent {agent_id} not found")
            return False
    else:
        # Find AI programming agent
        agents = registry.list_agents()
        ai_agent = None
        for a in agents:
            if a and any(kw in a.name.lower() for kw in ["ai", "programming", "coder", "dev", "开发"]):
                ai_agent = a
                break

        if not ai_agent:
            logger.error("No AI programming agent found. Please create one first or specify --agent-id")
            return False

        agent = ai_agent
        logger.info(f"Found agent: {agent.name} ({agent.agent_id})")

    # Build model_params
    if agent.model_params is None:
        agent.model_params = {}

    # 1. Set system_prompt (stored in agent.system_prompt, not model_params)
    # We'll return the prompt for the user to apply
    
    # 2. Merge intent_rules (avoid duplicates)
    existing_rules = agent.model_params.get("intent_rules", [])
    existing_keywords = set()
    for rule in existing_rules:
        existing_keywords.update(rule.get("keywords", []))

    added_rules = 0
    for rule in DEV_INTENT_RULES:
        # Check for duplicates
        if "keywords" in rule:
            has_duplicate = any(k in existing_keywords for k in rule.get("keywords", []))
            if not has_duplicate:
                existing_rules.append(rule)
                added_rules += 1
        elif "regex" in rule:
            # Regex rules don't have keywords to check, add if pattern is unique
            existing_patterns = [r.get("regex") for r in existing_rules if r.get("regex")]
            if rule["regex"] not in existing_patterns:
                existing_rules.append(rule)
                added_rules += 1

    agent.model_params["intent_rules"] = existing_rules

    # 3. Merge skill_param_extractors
    existing_extractors = agent.model_params.get("skill_param_extractors", {})
    for skill_id, extractors in DEV_SKILL_PARAM_EXTRACTORS.items():
        if skill_id not in existing_extractors:
            existing_extractors[skill_id] = extractors
        else:
            # Merge individual extractors
            for param_name, config in extractors.items():
                if param_name not in existing_extractors[skill_id]:
                    existing_extractors[skill_id][param_name] = config

    agent.model_params["skill_param_extractors"] = existing_extractors

    # 4. Ensure plan_based mode for best results
    if not agent.execution_mode or agent.execution_mode == "legacy":
        agent.execution_mode = "plan_based"
        logger.info("Switched to plan_based execution mode")

    # Save
    if registry.update_agent(agent):
        logger.info(f"✅ Configured agent: {agent.name}")
        logger.info(f"   Added {added_rules} new intent rules")
        logger.info(f"   Total intent rules: {len(existing_rules)}")
        return True
    else:
        logger.error("Failed to update agent")
        return False


def get_system_prompt() -> str:
    """Return the optimized system prompt."""
    return DEV_AGENT_SYSTEM_PROMPT


def print_configuration():
    """Print the full configuration for reference."""
    print("=" * 70)
    print("AI Programming Agent Configuration")
    print("=" * 70)
    
    print("\n📋 SYSTEM PROMPT:")
    print("-" * 70)
    print(DEV_AGENT_SYSTEM_PROMPT)
    
    print("\n📌 INTENT RULES:")
    print("-" * 70)
    for i, rule in enumerate(DEV_INTENT_RULES, 1):
        if "keywords" in rule:
            print(f"{i}. Keywords: {rule['keywords'][:5]}...")
            print(f"   Skills: {rule['skills']}")
            print(f"   Description: {rule.get('description', 'N/A')}")
        else:
            print(f"{i}. Regex: {rule.get('regex', 'N/A')}")
            print(f"   Skills: {rule['skills']}")
        print()
    
    print("\n🔧 SKILL PARAM EXTRACTORS:")
    print("-" * 70)
    for skill_id, extractors in DEV_SKILL_PARAM_EXTRACTORS.items():
        print(f"{skill_id}:")
        for param, config in extractors.items():
            print(f"  - {param}: {config}")
        print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Configure AI Programming Agent for development tasks")
    parser.add_argument("--agent-id", type=str, help="Agent ID to configure (default: auto-detect)")
    parser.add_argument("--show-config", action="store_true", help="Show configuration without applying")
    args = parser.parse_args()

    if args.show_config:
        print_configuration()
    else:
        success = configure_dev_agent(args.agent_id)
        if success:
            print("\n" + "=" * 70)
            print("✅ Agent configured successfully!")
            print("=" * 70)
            print("\n📝 Next Steps:")
            print("1. Copy the SYSTEM PROMPT above")
            print("2. Go to Agent settings in the UI")
            print("3. Paste into the System Prompt field")
            print("4. Save the agent")
            print("\nOr run with --show-config to see the full configuration")
        sys.exit(0 if success else 1)
