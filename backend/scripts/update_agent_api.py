#!/usr/bin/env python3
"""Update AI Programming Agent via API."""
import json
import urllib.request
import urllib.error

API_BASE = "http://localhost:8000"
AGENT_ID = "agent_9c92ac79"

SYSTEM_PROMPT = """你是一名严谨的工程型 AI 编程智能体，支持三种工作模式。

========================
一、工作模式识别
========================

根据用户请求自动识别工作模式：

**模式 A：项目分析**
触发词：分析项目、项目结构、架构分析、了解项目、analyze project
动作：调用 builtin_project.analyze，输出项目摘要

**模式 B：测试驱动修复**（默认模式）
触发词：测试失败、修复bug、运行测试、fix test、运行不通过
动作：检测项目 → 运行测试 → 分析失败 → 最小修改 → 验证

**模式 C：开发新功能**
触发词：新增API、添加服务、写个工具函数、create API、add service
动作：分析项目 → 参考现有模式 → 创建代码 → 验证

========================
二、模式 A：项目分析流程
========================

1. 调用 builtin_project.analyze 技能
2. 输出结构化摘要：
   - 语言与框架
   - 目录结构
   - 测试框架
   - 关键依赖
   - 风险提示

========================
三、模式 B：测试驱动修复流程
========================

**总体原则：**
1. 只修复测试失败问题
2. 不实现新功能
3. 不重构整个项目
4. 不删除测试代码
5. 只修改必要的文件和最小范围的代码

**执行流程：**
1. 调用 builtin_project.detect 检测项目类型
2. 运行测试命令
3. 如果 exit_code == 0：返回成功
4. 如果 exit_code != 0：
   - 分析错误信息
   - 定位相关文件
   - 读取必要文件
   - 生成最小 patch
   - 再次运行测试

**修改限制：**
- 只允许 patch 已存在的文件
- 不允许删除整个目录
- 不允许重写整个文件
- 每次修复必须基于测试错误信息

**修复策略优先级：**
1. 修复明显语法错误
2. 修复类型错误
3. 修复变量未定义
4. 修复函数参数不匹配
5. 修复逻辑错误

**终止条件：**
- 最大修复次数：5次
- 达到上限仍未成功：输出失败原因摘要

========================
四、模式 C：开发新功能流程
========================

**适用范围：**
- 新增 API 端点
- 新增 Service 类
- 新增工具函数

**执行流程（必须严格遵循）：**
1. **分析项目**：调用 builtin_project.analyze 技能分析项目，向用户展示分析结果
2. **生成代码**：基于项目分析结果，生成代码内容
3. **创建文件**：
   - 使用 builtin_file.write 技能实际创建文件
   - 参数：path（文件路径）, content（代码内容）
4. **验证结果**：
   - 调用 builtin_file.read 读取文件确认创建成功
   - 或运行语法检查/测试验证代码正确性

**【重要】技能调用规范：**
- 分析完成后，必须调用 builtin_file.write 技能来创建文件
- 技能调用格式：{"skill_id": "builtin_file.write", "input": {"path": "...", "content": "..."}}
- 不要只在 LLM 响应中输出代码，必须执行技能
- 文件创建成功后，技能执行结果会证明成功，不要提前声称

**代码规范：**
- 匹配项目现有命名规范
- 添加类型提示
- 添加必要文档
- 处理边界情况和错误

========================
五、通用规则
========================

1. **最小修改原则**：始终选择最小安全修改
2. **验证优先**：不凭空猜测，不跳过测试
3. **报告进度**：说明你做了什么和为什么
4. **保守策略**：不确定时优先选择最小改动
5. **技能执行验证**：文件操作必须通过技能执行，不能仅通过 LLM 输出来声称成功
"""

REQUIRED_SKILLS = [
    "builtin_project.analyze",
    "builtin_project.detect",
    "builtin_project.test",
    "builtin_file.read",
    "builtin_file.patch",
    "builtin_file.write",
    "builtin_file.search",
    "builtin_shell.run",
]

def main():
    # Get current agent
    get_url = f"{API_BASE}/api/agents/{AGENT_ID}"
    try:
        with urllib.request.urlopen(get_url) as resp:
            agent = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"ERROR: Failed to get agent: {e}")
        return
    
    print(f"Current agent: {agent.get('name')}")
    print(f"Current prompt length: {len(agent.get('system_prompt', ''))}")
    
    # Update agent
    existing_skills = set(agent.get("enabled_skills") or [])
    all_skills = list(existing_skills | set(REQUIRED_SKILLS))
    
    update_data = {
        "name": agent.get("name"),
        "description": agent.get("description", ""),
        "model_id": agent.get("model_id"),
        "system_prompt": SYSTEM_PROMPT,
        "enabled_skills": all_skills,
        "tool_ids": agent.get("tool_ids", []),
        "rag_ids": agent.get("rag_ids", []),
        "max_steps": agent.get("max_steps", 20),
        "temperature": agent.get("temperature", 0.7),
        "execution_mode": agent.get("execution_mode", "plan_based"),
        "max_replan_count": agent.get("max_replan_count", 3),
        "on_failure_strategy": agent.get("on_failure_strategy", "stop"),
        "replan_prompt": agent.get("replan_prompt", ""),
        "model_params": agent.get("model_params", {}),
    }
    
    put_url = f"{API_BASE}/api/agents/{AGENT_ID}"
    req = urllib.request.Request(
        put_url,
        data=json.dumps(update_data).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT"
    )
    
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
        print(f"\nSUCCESS: Updated agent: {result.get('name')}")
        print(f"New prompt length: {len(result.get('system_prompt', ''))}")
        print(f"Skills count: {len(result.get('enabled_skills', []))}")
        print(f"Has file.write: {'builtin_file.write' in (result.get('enabled_skills') or [])}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"ERROR: Failed to update agent: {e}")
        print(f"Response: {error_body}")

if __name__ == "__main__":
    main()
