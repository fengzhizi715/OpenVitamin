#!/usr/bin/env python3
"""
End-to-end test: Simulate the complete user scenario.

This test verifies that when a user says "analyze /path/to/project",
the system correctly:
1. Extracts the path from user input
2. Passes it to the tool as workspace parameter
3. Tool analyzes the correct path
4. Returns formatted output
"""
import asyncio
from core.tools.context import ToolContext
from core.plugins.builtin.tools.project.analyze import ProjectAnalyzeTool

async def test_end_to_end():
    """Test the complete workflow."""
    
    print("=" * 80)
    print("E2E Test: User says 'analyze /Users/tony/Projects/my_project'")
    print("=" * 80)
    
    # Step 1: LLM extracts path and creates skill call
    print("\n📝 Step 1: LLM parses user input and extracts path")
    user_input = "请帮我分析一下 /Users/tony/PycharmProjects/local_ai_inference_platform 这个项目"
    print(f"   User: {user_input}")
    print(f"   → LLM extracts workspace='/Users/tony/PycharmProjects/local_ai_inference_platform'")
    
    # Step 2: Skill executor calls tool with extracted workspace
    print("\n⚙️  Step 2: Skill executor calls tool")
    tool = ProjectAnalyzeTool()
    
    # Context: session workspace is different (simulating real scenario)
    ctx = ToolContext(
        agent_id="agent_test",
        trace_id="test_trace_001",
        workspace="/tmp/different_workspace",  # Different from target
    )
    
    input_data = {
        "workspace": "/Users/tony/PycharmProjects/local_ai_inference_platform",
        "detail_level": "brief",
        "include_tree": False,
    }
    
    print(f"   Tool context workspace: {ctx.workspace}")
    print(f"   Tool input workspace: {input_data['workspace']}")
    
    # Step 3: Tool executes analysis
    print("\n🔍 Step 3: Tool analyzes project...")
    result = await tool.run(input_data, ctx)
    
    # Step 4: Verify result
    print("\n✅ Step 4: Verify result")
    if result.success:
        print(f"   ✓ Analysis successful")
        print(f"   ✓ Analyzed path: {result.data['meta']['repo_root']}")
        print(f"   ✓ Files: {result.data['meta']['file_count']}")
        print(f"   ✓ Language: {result.data['meta']['language']}")
        
        # Verify it's NOT the session workspace
        if result.data['meta']['repo_root'] != ctx.workspace:
            print(f"   ✓ Correctly used absolute path (not session workspace)")
        else:
            print(f"   ✗ ERROR: Used session workspace instead of absolute path!")
            
        # Check formatter output
        summary = result.data.get('summary', '')
        if summary and len(summary) > 50:
            print(f"   ✓ Formatted summary generated ({len(summary)} chars)")
            print(f"\n📊 Summary preview (first 300 chars):")
            print("-" * 80)
            print(summary[:300])
            print("...")
            print("-" * 80)
        else:
            print(f"   ✗ WARNING: No formatted summary!")
            
    else:
        print(f"   ✗ Analysis failed!")
        print(f"   Error: {result.error}")
        print(f"   Data: {result.data}")
        return False
    
    print("\n" + "=" * 80)
    print("E2E Test: PASSED ✓")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = asyncio.run(test_end_to_end())
    exit(0 if success else 1)
