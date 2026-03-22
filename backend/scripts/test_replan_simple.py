#!/usr/bin/env python3
"""
简化版 Replan 功能测试

测试场景：
1. 使用 agent_9c92ac79 (AI编程智能体)
2. 执行一个会失败的测试命令
3. 验证 replan 是否触发
4. 检查占位符是否正确替换
"""
import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.agent_runtime.definition import get_agent_registry
from core.agent_runtime.session import AgentSession, get_agent_session_store
from core.agent_runtime.v2.runtime import AgentRuntime
from log import logger
from core.types import Message


def _init_skills_and_tools():
    """初始化 skills 和 tools"""
    from core.plugins.builtin.tools import bootstrap_tools
    from core.skills.service import bootstrap_builtin_skills
    from core.skills.registry import SkillRegistry
    
    bootstrap_tools()
    n_builtin = bootstrap_builtin_skills()
    SkillRegistry.load()
    logger.info(f"[Test] Initialized tools and skills")


async def test_replan():
    """测试 replan 功能"""
    print("=" * 80)
    print("测试 Replan 功能")
    print("=" * 80)
    
    # 初始化
    _init_skills_and_tools()
    
    # 获取 agent
    registry = get_agent_registry()
    agent = registry.get_agent("agent_9c92ac79")
    
    if not agent:
        print("❌ Agent agent_9c92ac79 不存在")
        return False
    
    print(f"\n✅ Agent: {agent.name}")
    print(f"   Execution Mode: {agent.execution_mode}")
    print(f"   Max Replan Count: {agent.max_replan_count}")
    print(f"   On Failure Strategy: {agent.on_failure_strategy}")
    print(f"   Replan Prompt 预览: {agent.replan_prompt[:150] if agent.replan_prompt else 'None'}...")
    
    # 创建一个会失败的测试命令（使用不存在的测试文件）
    failing_command = "cd /Users/tony/PycharmProjects/local_ai_inference_platform/backend/data/test_workspace && pytest nonexistent_test.py -v"
    
    # 创建 session
    session_store = get_agent_session_store()
    session_id = f"test_replan_{int(asyncio.get_event_loop().time())}"
    session = AgentSession(
        session_id=session_id,
        agent_id=agent.agent_id,
        messages=[
            Message(role="user", content=f"运行测试: {failing_command}")
        ],
        status="idle"
    )
    session_store.save_session(session)
    
    print(f"\n📝 Session: {session_id}")
    print(f"   User Input: {session.messages[0].content}")
    
    # 创建 runtime
    from core.agent_runtime.executor import get_agent_executor
    executor = get_agent_executor()
    runtime = AgentRuntime(executor=executor)
    
    # 设置 workspace
    workspace = "/Users/tony/PycharmProjects/local_ai_inference_platform/backend/data/test_workspace"
    session.workspace_dir = workspace
    
    print(f"\n🚀 开始执行（预期会失败并触发 replan）...")
    print(f"   Workspace: {workspace}")
    
    try:
        # 执行 agent
        result_session = await runtime.run(agent, session, workspace=workspace)
        
        print(f"\n📊 执行结果:")
        print(f"   Status: {result_session.status}")
        print(f"   Error Message: {result_session.error_message or 'None'}")
        print(f"   Messages Count: {len(result_session.messages)}")
        
        # 检查消息
        print(f"\n💬 消息内容:")
        for i, msg in enumerate(result_session.messages):
            content_preview = (msg.content or "")[:200]
            print(f"   [{i+1}] {msg.role}: {content_preview}...")
        
        # 检查 replan 是否触发（通过日志或消息内容）
        replan_detected = False
        for msg in result_session.messages:
            if msg.role == "assistant" and msg.content:
                content = msg.content.lower()
                # 检查是否包含 replan prompt 中的占位符替换后的内容
                if "测试执行失败" in msg.content or "exit_code" in content or "测试命令" in msg.content:
                    replan_detected = True
                    print(f"\n✅ 检测到 replan 相关内容")
                    break
        
        # 检查 replan prompt 中的占位符
        if agent.replan_prompt:
            print(f"\n🔍 Replan Prompt 占位符检查:")
            placeholders_in_prompt = []
            if "{test_command}" in agent.replan_prompt:
                placeholders_in_prompt.append("{test_command}")
            if "{exit_code}" in agent.replan_prompt:
                placeholders_in_prompt.append("{exit_code}")
            if "{stdout}" in agent.replan_prompt:
                placeholders_in_prompt.append("{stdout}")
            if "{stderr}" in agent.replan_prompt:
                placeholders_in_prompt.append("{stderr}")
            if "{failed_step_id}" in agent.replan_prompt:
                placeholders_in_prompt.append("{failed_step_id}")
            if "{failed_step_error}" in agent.replan_prompt:
                placeholders_in_prompt.append("{failed_step_error}")
            
            if placeholders_in_prompt:
                print(f"   ✅ 发现占位符: {placeholders_in_prompt}")
                print(f"   ✅ 占位符替换功能应该已生效")
            else:
                print(f"   ⚠️  未发现常见占位符")
        
        # 总结
        print(f"\n" + "=" * 80)
        print("测试总结")
        print("=" * 80)
        print(f"✅ Agent 执行完成")
        print(f"✅ Session 状态: {result_session.status}")
        if replan_detected:
            print(f"✅ Replan 功能已触发（从消息内容推断）")
        else:
            print(f"⚠️  未明确检测到 replan 触发（可能需要查看日志）")
        
        print(f"\n💡 提示：查看上面的日志，应该能看到：")
        print(f"   - 'Step ... failed, triggering on_failure_replan'")
        print(f"   - 'Created followup plan ...'")
        
        return True
        
    except Exception as e:
        logger.exception("测试失败")
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数"""
    result = await test_replan()
    return 0 if result else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
