"""
Plan to GraphDefinition Compiler
将 Agent Runtime 的 Plan 编译为 Execution Kernel 的 GraphDefinition
"""

from typing import Dict, Any, List, Optional
import logging

from execution_kernel.models.graph_definition import (
    GraphDefinition,
    NodeDefinition,
    EdgeDefinition,
    SubgraphDefinition,
    NodeType,
    EdgeTrigger,
    RetryPolicy,
)
from core.agent_runtime.v2.models import Plan, Step, ExecutorType, StepType


logger = logging.getLogger(__name__)


class PlanCompiler:
    """
    Plan 编译器
    
    将 Agent Runtime 的 Plan 转换为 Execution Kernel 的 GraphDefinition
    
    映射关系：
    - Plan.plan_id → GraphDefinition.id
    - Plan.steps[i] → NodeDefinition
    - Step.executor → NodeType (llm→script, skill→tool, internal→tool)
    - Step depends_on → EdgeDefinition (隐式或显式)
    """
    
    # ExecutorType 到 NodeType 的映射
    EXECUTOR_TO_NODE_TYPE = {
        ExecutorType.LLM: NodeType.SCRIPT,      # LLM 步骤使用 script 类型
        ExecutorType.SKILL: NodeType.TOOL,      # Skill 步骤使用 tool 类型
        ExecutorType.TOOLCHAIN: NodeType.TOOL,  # Toolchain 作为 tool
        ExecutorType.INTERNAL: NodeType.TOOL,   # Internal 作为 tool
    }
    
    # Phase C: StepType 到 NodeType 的映射（用于控制流）
    STEP_TYPE_TO_NODE_TYPE = {
        StepType.CONDITION: NodeType.CONDITION,  # 条件步骤
        StepType.LOOP: NodeType.LOOP,            # 循环步骤
        StepType.REPLAN: NodeType.REPLAN,        # RePlan 步骤
    }
    
    def compile(self, plan: Plan, parent_graph_id: str = None) -> GraphDefinition:
        """
        编译 Plan 为 GraphDefinition
        
        Args:
            plan: Agent Runtime 的 Plan
            parent_graph_id: 父图 ID（用于子图）
            
        Returns:
            Execution Kernel 的 GraphDefinition
        """
        # 1. 编译节点
        nodes = self._compile_nodes(plan.steps)
        
        # 2. 推导边（从隐式顺序 + 显式依赖）
        edges = self._compile_edges(plan.steps)
        
        # 3. 编译子图（Phase A: Composite 步骤）
        subgraphs = self._compile_subgraphs(plan.steps, plan.plan_id)
        
        # 4. 创建 GraphDefinition
        graph = GraphDefinition(
            id=plan.plan_id,
            version="1.0.0",
            nodes=nodes,
            edges=edges,
            subgraphs=subgraphs,
            parent_graph_id=parent_graph_id,
        )
        
        # 5. 验证
        errors = graph.validate()
        if errors:
            logger.warning(f"Plan compilation warnings: {errors}")
        
        logger.info(f"Compiled plan {plan.plan_id} to graph with {len(nodes)} nodes, {len(edges)} edges, {len(subgraphs)} subgraphs")
        
        return graph
    
    def _compile_subgraphs(self, steps: List[Step], parent_plan_id: str) -> List[SubgraphDefinition]:
        """
        编译 COMPOSITE 步骤为子图定义（Phase A）
        
        对于每个 COMPOSITE 步骤，递归编译其 sub_plan 为子图。
        """
        subgraphs = []
        
        for step in steps:
            if step.type == StepType.COMPOSITE and step.sub_plan:
                # 递归编译子计划
                subgraph = self.compile(step.sub_plan, parent_graph_id=parent_plan_id)
                
                subgraph_def = SubgraphDefinition(
                    id=f"{parent_plan_id}_{step.step_id}_subgraph",
                    graph=subgraph,
                    parent_node_id=step.step_id,
                )
                subgraphs.append(subgraph_def)
                
                # 递归收集子图的子图（多层嵌套）
                subgraphs.extend(subgraph.subgraphs)
        
        return subgraphs
    
    def _compile_nodes(self, steps: List[Step]) -> List[NodeDefinition]:
        """编译步骤为节点定义"""
        nodes = []
        
        for step in steps:
            # Phase C: 优先根据 StepType 确定 NodeType（控制流节点）
            if step.type in self.STEP_TYPE_TO_NODE_TYPE:
                node_type = self.STEP_TYPE_TO_NODE_TYPE[step.type]
            else:
                # 默认根据 ExecutorType 映射
                node_type = self.EXECUTOR_TO_NODE_TYPE.get(step.executor, NodeType.TOOL)
            
            # 构建 retry policy
            retry_policy = RetryPolicy(
                max_retries=self._get_max_retries(step),
                backoff_seconds=1.0,
                backoff_multiplier=2.0,
            )
            
            # 构建节点配置（包含执行所需的所有信息）
            # default_input 供 Kernel 创建 NodeRuntime 时作为 input_data，保证首轮执行有正确输入
            config = {
                "executor": step.executor.value if step.executor else "internal",
                "inputs": step.inputs,
                "default_input": dict(step.inputs) if step.inputs else {},
                "type": step.type.value,
                "replan_instruction": step.replan_instruction,
                "on_failure_replan": step.on_failure_replan,
            }
            
            # Phase C: 条件/循环节点添加专用配置
            if step.type == StepType.CONDITION:
                config["condition_expression"] = step.inputs.get("condition") if step.inputs else None
            elif step.type == StepType.LOOP:
                config["loop_condition"] = step.inputs.get("loop_condition") if step.inputs else None
                config["max_iterations"] = step.inputs.get("max_iterations", 100) if step.inputs else 100
            
            node = NodeDefinition(
                id=step.step_id,
                type=node_type,
                input_schema={},  # 由 Node Executor 动态处理
                output_schema={},  # 由 Node Executor 动态处理
                retry_policy=retry_policy,
                timeout_seconds=900.0 if node_type == NodeType.SCRIPT else 300.0,
                cacheable=False,  # Agent 步骤通常不缓存
                config=config,
            )
            
            nodes.append(node)
        
        return nodes
    
    def _compile_edges(self, steps: List[Step]) -> List[EdgeDefinition]:
        """
        编译边（依赖关系）
        
        规则：
        1. 显式依赖：Step.inputs 中包含 ${nodes.step_id.output.xxx} 引用
        2. 隐式顺序：如果步骤 i 引用了步骤 j 的输出（__from_previous_step），创建边
        """
        edges = []
        edge_set = set()  # 去重
        incoming_count: Dict[str, int] = {}
        
        # 构建步骤 ID 到索引的映射
        step_ids = [s.step_id for s in steps]
        
        for i, step in enumerate(steps):
            # 1. 检查显式依赖（通过 __from_previous_step 或模板引用）
            deps = self._extract_dependencies(step, step_ids[:i])
            
            for dep_id in deps:
                edge_key = (dep_id, step.step_id)
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append(EdgeDefinition(
                        from_node=dep_id,
                        to_node=step.step_id,
                        on=EdgeTrigger.SUCCESS,
                    ))
                    incoming_count[step.step_id] = incoming_count.get(step.step_id, 0) + 1
            
            # 2. 隐式顺序：LLM 步骤依赖前一个 Skill 步骤
            if step.executor == ExecutorType.LLM and i > 0:
                prev_step = steps[i - 1]
                if prev_step.executor == ExecutorType.SKILL:
                    edge_key = (prev_step.step_id, step.step_id)
                    if edge_key not in edge_set:
                        edge_set.add(edge_key)
                        edges.append(EdgeDefinition(
                            from_node=prev_step.step_id,
                            to_node=step.step_id,
                            on=EdgeTrigger.SUCCESS,
                        ))
                        incoming_count[step.step_id] = incoming_count.get(step.step_id, 0) + 1
            
            # 3. 确定性顺序兜底：若当前步骤没有任何入边，则串到前一步
            # 这样可保持与原 Plan 顺序语义一致，避免无依赖节点被并发调度导致行为漂移。
            if i > 0 and incoming_count.get(step.step_id, 0) == 0:
                prev_step = steps[i - 1]
                edge_key = (prev_step.step_id, step.step_id)
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append(EdgeDefinition(
                        from_node=prev_step.step_id,
                        to_node=step.step_id,
                        on=EdgeTrigger.SUCCESS,
                    ))
                    incoming_count[step.step_id] = 1
        
        return edges
    
    def _extract_dependencies(self, step: Step, previous_step_ids: List[str]) -> List[str]:
        """
        从步骤输入中提取依赖
        
        检查：
        1. __from_previous_step 标记
        2. ${nodes.step_id.output.xxx} 模板引用
        """
        deps = []
        inputs_str = str(step.inputs)
        
        # 检查 __from_previous_step
        if "__from_previous_step" in inputs_str:
            # 依赖最近的步骤
            if previous_step_ids:
                deps.append(previous_step_ids[-1])
        
        # 检查模板引用 ${nodes.step_id.output.xxx}
        import re
        pattern = r'\$\{nodes\.([^.]+)\.output'
        matches = re.findall(pattern, inputs_str)
        for step_id in matches:
            if step_id in previous_step_ids and step_id not in deps:
                deps.append(step_id)
        
        return deps
    
    def _get_max_retries(self, step: Step) -> int:
        """获取步骤的最大重试次数"""
        # 有 on_failure_replan 配置的步骤允许重试
        if step.on_failure_replan:
            return 1
        return 0


def compile_plan(plan: Plan) -> GraphDefinition:
    """便捷函数：编译 Plan"""
    compiler = PlanCompiler()
    return compiler.compile(plan)
