import sys
import types
import asyncio

import pytest

# Optional dependency stub for lightweight unit tests
onnx_stub = types.ModuleType("onnxruntime")
onnx_stub.InferenceSession = object
sys.modules.setdefault("onnxruntime", onnx_stub)

transformers_stub = types.ModuleType("transformers")


class _DummyAutoTokenizer:
    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        return cls()


transformers_stub.AutoTokenizer = _DummyAutoTokenizer
sys.modules.setdefault("transformers", transformers_stub)

from core.agent_runtime.definition import AgentDefinition
from core.agent_runtime.session import AgentSession
from core.agent_runtime.v2.executor_v2 import PlanBasedExecutor
from core.agent_runtime.v2.models import (
    AgentState,
    ExecutionTrace,
    ExecutorType,
    Plan,
    Step,
    StepLog,
    StepStatus,
    StepType,
    create_replan_step,
)
from core.agent_runtime.v2.planner import Planner
from core.types import Message

try:
    from core.agent_runtime.v2.runtime import AgentRuntime
except Exception:
    AgentRuntime = None


def _make_agent(**overrides) -> AgentDefinition:
    data = {
        "agent_id": "agent_test",
        "name": "test",
        "description": "",
        "model_id": "m1",
        "system_prompt": "",
        "enabled_skills": [],
        "tool_ids": [],
        "rag_ids": [],
        "max_steps": 10,
        "temperature": 0.1,
        "model_params": {},
        "execution_mode": "plan_based",
        "max_replan_count": 3,
        "on_failure_strategy": "stop",
        "replan_prompt": "",
    }
    data.update(overrides)
    return AgentDefinition(**data)


def _make_session() -> AgentSession:
    return AgentSession(
        session_id="asess_test",
        agent_id="agent_test",
        user_id="u1",
        messages=[Message(role="user", content="hello")],
    )


def test_keyword_match_boundary_does_not_confuse_tree_with_test():
    assert Planner._keyword_matches("please show tree .", "test") is False
    assert Planner._keyword_matches("please run test now", "test") is True


def test_intent_rules_boundary_matches_tree_rule():
    available_skills = ["builtin_shell.run", "builtin_project.tree"]
    model_params = {
        "intent_rules": [
            {"keywords": ["test"], "skills": ["builtin_shell.run"]},
            {"keywords": ["tree", "目录树"], "skills": ["builtin_project.tree"]},
        ]
    }
    matched = Planner._match_configured_intent_rules(
        user_input="帮我看下 tree .",
        user_lower="帮我看下 tree .",
        available_skills=available_skills,
        model_params=model_params,
    )
    assert matched == "builtin_project.tree"


def test_extract_shell_command_and_path_stable():
    cmd = Planner._extract_shell_command("运行测试: cd backend && pytest -q")
    assert cmd == "cd backend && pytest -q"

    path = Planner._extract_path_from_text("请展示目录树 path: ./backend/tests")
    assert path == "./backend/tests"

def test_build_skill_inputs_workspace_prefers_user_explicit_path():
    planner = Planner()

    class _Skill:
        id = "builtin_project.analyze"
        input_schema = {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "detail_level": {"type": "string"},
                "include_tree": {"type": "boolean"},
            },
        }

    inputs = planner._build_skill_inputs_simple(
        _Skill(),
        "帮我分析这个项目： /Users/tony/IdeaProjects/Monica",
        {
            "workspace": "/Users/tony/PycharmProjects/local_ai_inference_platform/backend/data/agent_workspaces/asess_xxx",
            "session_id": "asess_xxx",
            "model_params": {},
        },
    )
    assert inputs["workspace"] == "/Users/tony/IdeaProjects/Monica"
    assert inputs["detail_level"] == "detailed"


def test_execute_replan_respects_limit():
    executor = PlanBasedExecutor()
    step = create_replan_step("retry")
    state = AgentState(agent_id="agent_test", runtime_state={"replan_count": 2})
    agent = _make_agent(max_replan_count=2)
    session = _make_session()
    trace = ExecutionTrace(plan_id="plan_test")

    out = asyncio.run(
        executor._execute_replan(
            step=step,
            state=state,
            context={"agent": agent, "session": session, "planner": object()},
            trace=trace,
        )
    )

    assert out.status == StepStatus.FAILED
    assert "Maximum replan count" in (out.error or "")


def test_replan_recovery_marks_failed_step_as_completed():
    executor = PlanBasedExecutor()
    state = AgentState(agent_id="agent_test")
    session = _make_session()
    agent = _make_agent(
        enabled_skills=["builtin_shell.run"],
        on_failure_strategy="replan",
        replan_prompt="失败后重试：{failed_step_error}",
    )

    original_step = Step(
        step_id="step_skill",
        type=StepType.ATOMIC,
        executor=ExecutorType.SKILL,
        inputs={"skill_id": "builtin_shell.run", "inputs": {"command": "pytest"}},
    )
    plan = Plan(plan_id="plan_test", goal="run", steps=[original_step], failure_strategy="replan")

    async def fake_execute_step(step, state, context, trace, parent_step_id=None, depth=0):
        if step.type == StepType.REPLAN:
            step.status = StepStatus.COMPLETED
            step.outputs = {"followup_plan_id": "plan_followup"}
            step.error = None
            return step
        step.status = StepStatus.FAILED
        step.error = "tool failed"
        step.outputs = {"error": "tool failed"}
        return step

    executor._execute_step = fake_execute_step  # type: ignore[method-assign]

    out_plan, _, out_trace = asyncio.run(
        executor.execute_plan(
            plan=plan,
            state=state,
            session=session,
            agent=agent,
            workspace=".",
            permissions={"shell.run": True},
        )
    )

    assert out_plan.steps[0].status == StepStatus.COMPLETED
    assert out_plan.steps[0].outputs.get("recovered_by_replan") is True
    assert out_trace.final_status == "completed"


def test_plan_result_completed_clears_error_message():
    if AgentRuntime is None:
        pytest.skip("AgentRuntime optional dependencies are not available in this environment")
    runtime = AgentRuntime(executor=None)
    session = _make_session()
    session.status = "error"
    session.error_message = "old error"

    plan = Plan(
        plan_id="plan_ok",
        goal="g",
        steps=[
            Step(
                step_id="s1",
                executor=ExecutorType.LLM,
                status=StepStatus.COMPLETED,
                outputs={"response": "done"},
            )
        ],
    )
    state = AgentState(agent_id="agent_test", persistent_state={"k": "v"})
    trace = ExecutionTrace(plan_id="plan_ok", final_status="completed")

    out = runtime._plan_result_to_session(session, plan, state, trace)
    assert out.status == "finished"
    assert out.error_message is None


def test_plan_result_failed_uses_trace_error_when_no_step_error():
    if AgentRuntime is None:
        pytest.skip("AgentRuntime optional dependencies are not available in this environment")
    runtime = AgentRuntime(executor=None)
    session = _make_session()
    plan = Plan(
        plan_id="plan_fail",
        goal="g",
        steps=[
            Step(
                step_id="s1",
                executor=ExecutorType.LLM,
                status=StepStatus.PENDING,
                outputs={},
            )
        ],
    )
    state = AgentState(agent_id="agent_test")
    trace = ExecutionTrace(
        plan_id="plan_fail",
        final_status="failed",
        step_logs=[
            StepLog(
                step_id="s1",
                event_type="error",
                output_data={"error": "planner failed by timeout"},
            )
        ],
    )

    out = runtime._plan_result_to_session(session, plan, state, trace)
    assert out.status == "error"
    assert out.error_message == "planner failed by timeout"


def test_summarize_project_analyze_prefers_summary_text():
    if AgentRuntime is None:
        pytest.skip("AgentRuntime optional dependencies are not available in this environment")
    summary = AgentRuntime._summarize_skill_step(
        {
            "skill_id": "builtin_project.analyze",
            "result": {
                "output": {
                    "summary": "Project Intelligence 摘要：\\n- language: kotlin",
                    "meta": {"language": "kotlin"},
                }
            },
        }
    )
    assert summary == "Project Intelligence 摘要：\\n- language: kotlin"


def test_summarize_shell_run_returns_human_readable_text():
    if AgentRuntime is None:
        pytest.skip("AgentRuntime optional dependencies are not available in this environment")
    summary = AgentRuntime._summarize_skill_step(
        {
            "skill_id": "builtin_shell.run",
            "result": {
                "output": {
                    "command": "pytest -q",
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "assert 1 == 2",
                    "timed_out": False,
                    "duration_seconds": 0.12,
                }
            },
        }
    )
    assert isinstance(summary, str)
    assert "命令执行结果" in summary
    assert "exit_code: 1" in summary


def test_replan_direct_skill_plan_is_explicitly_configured():
    planner = Planner()
    agent = _make_agent(
        enabled_skills=["builtin_shell.run", "builtin_project.analyze"],
        model_params={
            "replan_direct_skill": {
                "enabled": True,
                "when": ["skill_failed"],
                "strategy": "retry_failed_skill",
                "allowed_skills": ["builtin_shell.run"],
            }
        },
    )
    failed_step = Step(
        step_id="s_fail",
        executor=ExecutorType.SKILL,
        status=StepStatus.FAILED,
        inputs={
            "skill_id": "builtin_shell.run",
            "inputs": {"command": "pytest -q"},
        },
        error="test failed",
    )
    plan = asyncio.run(
        planner.create_followup_plan(
            agent=agent,
            execution_context={
                "last_failed_step": failed_step,
                "last_error": "test failed",
                "replan_instruction": "retry",
            },
            parent_plan_id="plan_parent",
        )
    )
    assert plan.context.get("plan_source") == "replan_direct_skill"
    assert len(plan.steps) == 1
    assert plan.steps[0].inputs.get("skill_id") == "builtin_shell.run"


def test_replan_direct_skill_disabled_falls_back_to_regular_planner():
    planner = Planner()
    agent = _make_agent(
        enabled_skills=["builtin_shell.run"],
        model_params={},
    )

    async def _fake_create_plan(*args, **kwargs):
        return Plan(plan_id="plan_fallback", goal="fallback", steps=[])

    planner.create_plan = _fake_create_plan  # type: ignore[method-assign]
    plan = asyncio.run(
        planner.create_followup_plan(
            agent=agent,
            execution_context={"replan_instruction": "retry"},
            parent_plan_id="plan_parent",
        )
    )
    assert plan.plan_id == "plan_fallback"


def test_replan_direct_skill_retry_shell_nonzero_falls_back():
    planner = Planner()
    agent = _make_agent(
        enabled_skills=["builtin_shell.run"],
        model_params={
            "replan_direct_skill": {
                "enabled": True,
                "when": ["skill_failed"],
                "strategy": "retry_failed_skill",
                "allowed_skills": ["builtin_shell.run"],
                "fallback": "planner_replan",
            }
        },
    )
    failed_step = Step(
        step_id="s_fail_shell",
        executor=ExecutorType.SKILL,
        status=StepStatus.FAILED,
        inputs={"skill_id": "builtin_shell.run", "inputs": {"command": "pytest -q"}},
        outputs={"result": {"output": {"exit_code": 1, "stderr": "FAILED"}}},
        error="Tool failed (exit_code=1)",
    )

    async def _fake_create_plan(*args, **kwargs):
        return Plan(plan_id="plan_after_fallback", goal="fallback", steps=[])

    planner.create_plan = _fake_create_plan  # type: ignore[method-assign]
    plan = asyncio.run(
        planner.create_followup_plan(
            agent=agent,
            execution_context={
                "last_failed_step": failed_step,
                "last_error": failed_step.error,
                "replan_instruction": "retry",
            },
            parent_plan_id="p1",
        )
    )
    assert plan.plan_id == "plan_after_fallback"


def test_extract_replan_target_file_from_shell_command_context():
    planner = Planner()
    failed_step = Step(
        step_id="s_shell_fail",
        executor=ExecutorType.SKILL,
        status=StepStatus.FAILED,
        inputs={
            "skill_id": "builtin_shell.run",
            "inputs": {
                "command": "cd /tmp/work && pytest test_app.py -v",
            },
        },
        outputs={"result": {"output": {"exit_code": 1, "stdout": "FAILED test_app.py::test_add"}}},
        error="Tool failed (exit_code=1)",
    )
    file_path = planner._extract_replan_target_file({"last_failed_step": failed_step, "last_error": failed_step.error})
    assert isinstance(file_path, str)
    assert file_path.endswith("/tmp/work/test_app.py")


def test_replan_fix_plan_marks_patch_extraction_on_patch_step():
    planner = Planner()
    agent = _make_agent(
        enabled_skills=[
            "builtin_file.read",
            "builtin_file.patch",
            "builtin_shell.run",
        ],
    )
    failed_step = Step(
        step_id="s_shell_fail2",
        executor=ExecutorType.SKILL,
        status=StepStatus.FAILED,
        inputs={
            "skill_id": "builtin_shell.run",
            "inputs": {
                "command": "cd /tmp/work && pytest test_app.py -v",
            },
        },
        outputs={"result": {"output": {"exit_code": 1, "stderr": "File \"/tmp/work/test_app.py\", line 9"}}},
        error="Tool failed (exit_code=1)",
    )
    plan = planner._build_replan_fix_plan(  # pylint: disable=protected-access
        agent=agent,
        execution_context={"last_failed_step": failed_step, "last_error": failed_step.error},
        parent_plan_id="pfix",
    )
    assert plan is not None
    # read, llm, patch, shell
    assert len(plan.steps) == 4
    patch_step = plan.steps[2]
    assert patch_step.inputs.get("_extract_patch") is True


def test_replan_fix_plan_prefers_source_file_over_test_file_when_exists(tmp_path):
    planner = Planner()
    src_file = tmp_path / "app.py"
    test_file = tmp_path / "test_app.py"
    src_file.write_text("def add(a,b): return a-b\n", encoding="utf-8")
    test_file.write_text("from app import add\n", encoding="utf-8")

    agent = _make_agent(
        enabled_skills=[
            "builtin_file.read",
            "builtin_file.patch",
            "builtin_shell.run",
        ],
    )
    failed_step = Step(
        step_id="s_shell_fail3",
        executor=ExecutorType.SKILL,
        status=StepStatus.FAILED,
        inputs={
            "skill_id": "builtin_shell.run",
            "inputs": {
                "command": f"cd {tmp_path} && pytest test_app.py -v",
            },
        },
        outputs={"result": {"output": {"exit_code": 1, "stderr": "FAILED test_app.py::test_add"}}},
        error="Tool failed (exit_code=1)",
    )
    plan = planner._build_replan_fix_plan(
        agent=agent,
        execution_context={"last_failed_step": failed_step, "last_error": failed_step.error},
        parent_plan_id="pfix2",
    )
    assert plan is not None
    read_step = plan.steps[0]
    assert read_step.inputs["inputs"]["path"] == str(src_file.resolve())
    patch_step = plan.steps[2]
    assert patch_step.inputs["inputs"]["path"] == str(src_file.resolve())


def test_extract_unified_diff_from_think_wrapped_output():
    text = (
        "<think>analysis...</think>\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-return a-b\n"
        "+return a+b\n"
    )
    patch = PlanBasedExecutor._extract_unified_diff(text)
    assert patch is not None
    assert patch.startswith("--- a/app.py")


def test_inject_skill_output_failure_includes_exit_code_and_stderr():
    executor = PlanBasedExecutor()

    # 模拟 shell.run 失败时 SkillExecutor 的输出结构（失败时也应保留 output_data）
    last_skill_step_outputs = {
        "skill_id": "builtin_shell.run",
        "result": {
            "type": "tool",
            "output": {
                "command": "pytest test_app.py -v",
                "exit_code": 1,
                "stdout": "",
                "stderr": "FAILED test_app.py::test_add - AssertionError",
            },
            "error": "Tool failed (exit_code=1): FAILED test_app.py::test_add - AssertionError",
        },
    }

    llm_inputs = {
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "用户输入：运行测试\n\n技能已执行，请根据技能执行结果生成最终回复。"},
        ],
        "_inject_skill_output": True,
    }

    injected = executor._inject_skill_output(llm_inputs, last_skill_step_outputs)
    user_content = injected["messages"][-1]["content"]

    assert "执行失败" in user_content
    assert "退出码: 1" in user_content
    assert "FAILED test_app.py::test_add" in user_content
    assert "无输出" not in user_content
