"""
Graph Runtime Adapter

将 Workflow DAG 转换为 execution_kernel 的 GraphDefinition。
"""

from typing import Dict, Any, Optional, List
import json

from core.workflows.models import WorkflowVersion, WorkflowDAG, WorkflowNode, WorkflowEdge
from execution_kernel.models.graph_definition import (
    GraphDefinition,
    NodeDefinition,
    EdgeDefinition,
    NodeType,
    EdgeTrigger
)
from log import logger


class GraphRuntimeAdapter:
    """
    Graph 运行时适配器
    
    负责 Workflow DAG 与 execution_kernel GraphDefinition 之间的转换。
    """
    
    # 节点类型映射（llm 单独映射以便 WorkflowRuntime 的 _llm_handler 被正确分发）
    NODE_TYPE_MAP = {
        "llm": NodeType.LLM,
        "tool": NodeType.TOOL,
        # data 节点：复用 TOOL 调度，在 WorkflowRuntime 里按 workflow_node_type 做 passthrough
        "input": NodeType.TOOL,
        "output": NodeType.TOOL,
        # 兼容前端旧节点类型命名
        "start": NodeType.TOOL,   # 语义等同 input
        "end": NodeType.TOOL,     # 语义等同 output
        # kernel 暂无独立 AGENT 类型，复用 TOOL 调度并在 config.workflow_node_type 区分
        "agent": NodeType.TOOL,
        "condition": NodeType.CONDITION,
        "script": NodeType.SCRIPT,
        "replan": NodeType.REPLAN,
        "loop": NodeType.LOOP,
    }

    EDGE_TRIGGER_MAP = {
        "success": EdgeTrigger.SUCCESS,
        "failure": EdgeTrigger.FAILURE,
        "always": EdgeTrigger.ALWAYS,
        "true": EdgeTrigger.CONDITION_TRUE,
        "false": EdgeTrigger.CONDITION_FALSE,
        "condition_true": EdgeTrigger.CONDITION_TRUE,
        "condition_false": EdgeTrigger.CONDITION_FALSE,
        "continue": EdgeTrigger.LOOP_CONTINUE,
        "exit": EdgeTrigger.LOOP_EXIT,
        "loop_continue": EdgeTrigger.LOOP_CONTINUE,
        "loop_exit": EdgeTrigger.LOOP_EXIT,
    }

    @classmethod
    def _normalize_workflow_node_type(cls, node_type: str) -> str:
        t = str(node_type or "").strip().lower()
        if t == "start":
            return "input"
        if t == "end":
            return "output"
        return t

    @classmethod
    def _resolve_workflow_node_type(cls, node: WorkflowNode) -> str:
        """
        解析 workflow 节点语义类型，兼容历史数据：
        - 老数据可能把 start/end 存成 type=tool
        - 或者 type=tool 但 config.workflow_node_type 标记了 input/output/start/end
        """
        cfg = node.config or {}
        cfg_type = str(cfg.get("workflow_node_type") or "").strip().lower()
        normalized_cfg_type = cls._normalize_workflow_node_type(cfg_type)
        if normalized_cfg_type in {"input", "output", "agent", "condition", "loop", "replan", "script", "llm"}:
            return normalized_cfg_type

        normalized_type = cls._normalize_workflow_node_type(node.type)
        if normalized_type == "tool":
            node_id = str(node.id or "").strip().lower()
            if node_id == "start":
                return "input"
            if node_id in {"end", "output"}:
                return "output"
        return normalized_type
    
    @classmethod
    def adapt(cls, workflow_version: WorkflowVersion) -> GraphDefinition:
        """
        将 WorkflowVersion 转换为 GraphDefinition
        
        Args:
            workflow_version: 工作流版本
        
        Returns:
            execution_kernel 的 GraphDefinition
        """
        dag = workflow_version.dag
        
        # 转换节点
        nodes = [cls._adapt_node(node) for node in dag.nodes]
        
        # 转换边
        edges = [cls._adapt_edge(edge) for edge in dag.edges]
        
        # 创建 GraphDefinition
        graph_def = GraphDefinition(
            id=workflow_version.version_id,
            version=workflow_version.version_number,
            nodes=nodes,
            edges=edges,
            metadata={
                "workflow_id": workflow_version.workflow_id,
                "version_id": workflow_version.version_id,
                "entry_node": dag.entry_node,
                **dag.global_config
            }
        )
        
        logger.debug(
            f"[GraphRuntimeAdapter] Adapted workflow {workflow_version.workflow_id} "
            f"v{workflow_version.version_number} to GraphDefinition: "
            f"{len(nodes)} nodes, {len(edges)} edges"
        )
        
        return graph_def
    
    @classmethod
    def _adapt_node(cls, node: WorkflowNode) -> NodeDefinition:
        """转换节点"""
        normalized_type = cls._resolve_workflow_node_type(node)
        # 映射节点类型
        node_type = cls.NODE_TYPE_MAP.get(normalized_type, NodeType.TOOL)
        
        # 构建节点配置
        config = dict(node.config)
        config["name"] = node.name or node.id
        config["description"] = node.description
        config.setdefault("workflow_node_type", normalized_type)
        
        kwargs: Dict[str, Any] = {
            "id": node.id,
            "type": node_type,
            "config": config,
            # 从 config 中提取其他配置
            "input_schema": config.get("input_schema", {}),
            "output_schema": config.get("output_schema", {}),
            "timeout_seconds": config.get("timeout_seconds", 300.0),
            "cacheable": config.get("cacheable", False),
        }
        retry_policy = config.get("retry_policy")
        if retry_policy is not None:
            kwargs["retry_policy"] = retry_policy
        return NodeDefinition(**kwargs)
    
    @classmethod
    def _adapt_edge(cls, edge: WorkflowEdge) -> EdgeDefinition:
        """转换边"""
        # 触发条件优先级：
        # source_handle > label > condition(历史兼容) > success(默认)
        trigger = EdgeTrigger.SUCCESS

        source_handle = str(edge.source_handle or "").strip().lower()
        label = str(edge.label or "").strip().lower()

        if source_handle in cls.EDGE_TRIGGER_MAP:
            trigger = cls.EDGE_TRIGGER_MAP[source_handle]
        elif label in cls.EDGE_TRIGGER_MAP:
            trigger = cls.EDGE_TRIGGER_MAP[label]
        elif edge.condition:
            # 兼容旧数据：只有 condition 字段时按 true 分支
            trigger = EdgeTrigger.CONDITION_TRUE
        
        return EdgeDefinition(
            from_node=edge.from_node,
            to_node=edge.to_node,
            on=trigger,
            condition=edge.condition
        )
    
    @classmethod
    def create_graph_instance(
        cls,
        workflow_version: WorkflowVersion,
        input_data: Optional[Dict[str, Any]] = None,
        global_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        创建 GraphInstance 初始化数据
        
        Args:
            workflow_version: 工作流版本
            input_data: 输入数据
            global_context: 全局上下文
        
        Returns:
            GraphInstance 创建参数
        """
        dag = workflow_version.dag
        
        # 确定入口节点
        entry_node = dag.entry_node
        if not entry_node and dag.nodes:
            entry_node = dag.nodes[0].id
        
        # 构建初始上下文
        context = dict(global_context or {})
        context["workflow_id"] = workflow_version.workflow_id
        context["version_id"] = workflow_version.version_id
        context["version_number"] = workflow_version.version_number
        context["input_data"] = input_data or {}
        
        return {
            "graph_definition_id": workflow_version.version_id,
            "graph_definition_version": workflow_version.version_number,
            "global_context": context,
            "entry_node": entry_node
        }

    @classmethod
    def _parse_node_error_details(cls, error_message: Optional[str]) -> Optional[Dict[str, Any]]:
        if not error_message or not isinstance(error_message, str):
            return None
        marker = "AGENT_NODE_OUTPUT_SCHEMA_ERROR:"
        if marker not in error_message:
            return None
        payload = error_message.split(marker, 1)[1].strip()
        if not payload:
            return None
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {
                "error_code": "AGENT_OUTPUT_SCHEMA_VALIDATION_ERROR",
                "message": payload,
            }
        return None
    
    @classmethod
    async def extract_execution_result_from_kernel(
        cls,
        instance_id: str,
        kernel_db: Any
    ) -> Dict[str, Any]:
        """
        从 execution_kernel 数据库查询执行结果
        
        Args:
            instance_id: GraphInstance ID
            kernel_db: execution_kernel 的 Database 实例
        
        Returns:
            执行结果
        """
        from execution_kernel.persistence.repositories import (
            GraphInstanceRepository,
            NodeRuntimeRepository
        )
        
        async with kernel_db.async_session() as session:
            # 查询实例状态
            instance_repo = GraphInstanceRepository(session)
            instance_db = await instance_repo.get(instance_id)
            
            if not instance_db:
                return {
                    "state": "failed",
                    "output_data": {},
                    "node_outputs": {},
                    "error": "Instance not found in kernel"
                }
            
            # 查询所有节点运行时
            node_repo = NodeRuntimeRepository(session)
            node_runtimes = await node_repo.get_all_by_instance(instance_id)

            def _map_state(v: str) -> str:
                vv = (v or "").lower()
                if vv in {"pending", "running", "success", "failed", "skipped", "cancelled", "timeout"}:
                    return vv
                if vv == "retrying":
                    return "running"
                return "pending"
            
            # 收集节点输出
            node_outputs = {}
            node_states: List[Dict[str, Any]] = []
            agent_summaries: List[Dict[str, Any]] = []
            for node_runtime in node_runtimes:
                if node_runtime.output_data:
                    node_outputs[node_runtime.node_id] = node_runtime.output_data
                state_val = (
                    node_runtime.state.value if hasattr(node_runtime.state, "value") else str(node_runtime.state)
                )
                node_states.append(
                    {
                        "node_id": node_runtime.node_id,
                        "state": _map_state(state_val),
                        "input_data": node_runtime.input_data or {},
                        "output_data": node_runtime.output_data or {},
                        "error_message": node_runtime.error_message,
                        "error_details": cls._parse_node_error_details(node_runtime.error_message),
                        "started_at": node_runtime.started_at.isoformat() if node_runtime.started_at else None,
                        "finished_at": node_runtime.finished_at.isoformat() if node_runtime.finished_at else None,
                        "retry_count": int(node_runtime.retry_count or 0),
                    }
                )
                out = node_runtime.output_data or {}
                if isinstance(out, dict) and out.get("type") == "agent_result":
                    agent_summaries.append(
                        {
                            "node_id": node_runtime.node_id,
                            "agent_id": out.get("agent_id"),
                            "agent_session_id": out.get("agent_session_id"),
                            "status": out.get("status", "success"),
                            "response_preview": out.get("response_preview"),
                            "started_at": node_runtime.started_at.isoformat() if node_runtime.started_at else None,
                            "finished_at": node_runtime.finished_at.isoformat() if node_runtime.finished_at else None,
                            "duration_ms": int((node_runtime.finished_at - node_runtime.started_at).total_seconds() * 1000)
                            if node_runtime.started_at and node_runtime.finished_at
                            else None,
                        }
                    )
            
            # 确定最终输出（使用最后一个成功完成节点的输出）
            output_data = {}
            if node_outputs:
                # 找到最后一个完成的节点
                last_node = None
                for node in node_runtimes:
                    if node.state.value == "success":
                        if last_node is None or (node.finished_at and last_node.finished_at and node.finished_at > last_node.finished_at):
                            last_node = node
                
                if last_node and last_node.output_data:
                    output_data = last_node.output_data
            
            return {
                "state": instance_db.state.value,
                "output_data": output_data,
                "node_outputs": node_outputs,
                "node_states": node_states,
                "agent_summaries": agent_summaries,
                "global_context": instance_db.global_context if hasattr(instance_db, 'global_context') else {},
                "tokens_consumed": 0  # 可以从节点输出中统计
            }
    
    @classmethod
    def validate_compatibility(
        cls,
        workflow_version: WorkflowVersion
    ) -> List[str]:
        """
        验证 WorkflowVersion 与 execution_kernel 的兼容性
        
        Returns:
            错误列表，空列表表示兼容
        """
        errors = []
        dag = workflow_version.dag
        
        # 检查节点类型
        supported_types = set(cls.NODE_TYPE_MAP.keys())
        for node in dag.nodes:
            normalized_type = cls._resolve_workflow_node_type(node)
            if normalized_type not in supported_types:
                errors.append(
                    f"Unsupported node type '{node.type}' for node {node.id}. "
                    f"Supported: {supported_types}"
                )
        
        # 检查必需的配置
        for node in dag.nodes:
            normalized_type = cls._resolve_workflow_node_type(node)
            if normalized_type == "llm":
                config = node.config or {}
                model_id = str(config.get("model_id") or "").strip()
                legacy_model = str(config.get("model") or "").strip()
                if not model_id and not legacy_model:
                    errors.append(f"LLM node {node.id} missing 'model_id' or 'model' config")
            
            elif normalized_type == "tool":
                config = node.config or {}
                if "tool_name" not in config and "tool_id" not in config:
                    errors.append(f"Tool node {node.id} missing 'tool_name' or 'tool_id' config")
            elif normalized_type == "agent":
                config = node.config or {}
                if not str(config.get("agent_id") or "").strip():
                    errors.append(f"Agent node {node.id} missing 'agent_id' config")
            elif normalized_type == "input":
                config = node.config or {}
                if "input_key" in config:
                    input_key = config.get("input_key")
                    if not isinstance(input_key, str):
                        errors.append(f"Input node {node.id} config.input_key must be string")
                    elif not input_key.strip():
                        errors.append(f"Input node {node.id} config.input_key cannot be empty")
            elif normalized_type == "output":
                config = node.config or {}
                output_key = config.get("output_key")
                expression = config.get("expression")
                if expression is not None and not isinstance(expression, str):
                    errors.append(f"Output node {node.id} config.expression must be string when provided")
                if expression is not None and not str(output_key or "").strip():
                    errors.append(
                        f"Output node {node.id} requires non-empty config.output_key when config.expression is set"
                    )
                if output_key is not None and not isinstance(output_key, str):
                    errors.append(f"Output node {node.id} config.output_key must be string")

        # Condition 节点分支触发语义校验：
        # 必须具备 true/false 两条出边，且 trigger 必须可识别。
        condition_node_ids = {
            node.id
            for node in dag.nodes
            if cls._resolve_workflow_node_type(node) == "condition"
        }
        if condition_node_ids:
            outgoing_by_node: Dict[str, List[WorkflowEdge]] = {nid: [] for nid in condition_node_ids}
            for edge in dag.edges:
                if edge.from_node in outgoing_by_node:
                    outgoing_by_node[edge.from_node].append(edge)
            for node_id, outgoing in outgoing_by_node.items():
                has_true = False
                has_false = False
                bad_edges: List[str] = []
                for edge in outgoing:
                    trigger_hint = str(edge.source_handle or edge.label or "").strip().lower()
                    if trigger_hint in {"true", "condition_true"}:
                        has_true = True
                    elif trigger_hint in {"false", "condition_false"}:
                        has_false = True
                    else:
                        bad_edges.append(
                            f"{edge.from_node}->{edge.to_node}(source_handle={edge.source_handle},label={edge.label})"
                        )
                if not has_true or not has_false:
                    miss = []
                    if not has_true:
                        miss.append("true")
                    if not has_false:
                        miss.append("false")
                    errors.append(
                        f"Condition node {node_id} missing branch trigger(s): {', '.join(miss)} "
                        f"(edge source_handle/label should be true/false). bad_edges={bad_edges}"
                    )

        # Loop 节点分支触发语义校验：必须具备 continue/exit 两条出边。
        loop_node_ids = {
            node.id
            for node in dag.nodes
            if cls._resolve_workflow_node_type(node) == "loop"
        }
        if loop_node_ids:
            outgoing_by_node: Dict[str, List[WorkflowEdge]] = {nid: [] for nid in loop_node_ids}
            for edge in dag.edges:
                if edge.from_node in outgoing_by_node:
                    outgoing_by_node[edge.from_node].append(edge)
            for node_id, outgoing in outgoing_by_node.items():
                has_continue = False
                has_exit = False
                bad_edges: List[str] = []
                for edge in outgoing:
                    trigger_hint = str(edge.source_handle or edge.label or "").strip().lower()
                    if trigger_hint in {"continue", "loop_continue"}:
                        has_continue = True
                    elif trigger_hint in {"exit", "loop_exit"}:
                        has_exit = True
                    else:
                        bad_edges.append(
                            f"{edge.from_node}->{edge.to_node}(source_handle={edge.source_handle},label={edge.label})"
                        )
                if not has_continue or not has_exit:
                    miss = []
                    if not has_continue:
                        miss.append("continue")
                    if not has_exit:
                        miss.append("exit")
                    errors.append(
                        f"Loop node {node_id} missing branch trigger(s): {', '.join(miss)} "
                        f"(edge source_handle/label should be continue/exit). bad_edges={bad_edges}"
                    )
        
        return errors
