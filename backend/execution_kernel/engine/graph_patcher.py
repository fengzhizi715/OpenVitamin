"""
Graph Patcher (Phase B)
动态图扩展引擎，支持 RePlan 场景下的增量图修改
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import copy

from execution_kernel.models.graph_definition import (
    GraphDefinition, 
    NodeDefinition, 
    EdgeDefinition,
    NodeType,
    EdgeTrigger,
    RetryPolicy,
)
from execution_kernel.models.graph_patch import (
    GraphPatch,
    GraphPatchResult,
    PatchOperation,
    AddNodeOperation,
    AddEdgeOperation,
    DisableNodeOperation,
    SetMetadataOperation,
    PatchOperationType,
    ExecutionPointer,
    PatchMigrationPlan,
    PatchMigrationStrategy,
)


class GraphPatcher:
    """
    图补丁引擎
    
    负责：
    1. 应用 GraphPatch 到 GraphDefinition
    2. 版本控制（CAS/乐观锁）
    3. 执行指针安全迁移
    4. 事务化操作
    """
    
    def __init__(self):
        self._version_separator = "."
    
    def apply_patch(
        self,
        graph: GraphDefinition,
        patch: GraphPatch,
        pointer: Optional[ExecutionPointer] = None,
    ) -> Tuple[GraphDefinition, GraphPatchResult, Optional[ExecutionPointer]]:
        """
        应用补丁到图定义
        
        Args:
            graph: 当前图定义
            patch: 要应用的补丁
            pointer: 当前执行指针（可选）
        
        Returns:
            (新图定义, 应用结果, 新执行指针)
        """
        # 1. 版本检查（CAS）
        if graph.version != patch.base_version:
            return graph, GraphPatchResult(
                success=False,
                patch_id=patch.patch_id,
                applied_version=graph.version,
                previous_version=graph.version,
                errors=[f"Version mismatch: expected {patch.base_version}, got {graph.version}"],
            ), pointer
        
        # 2. 创建可变副本
        new_graph = self._create_mutable_copy(graph)
        errors: List[str] = []
        applied_count = 0
        
        # 3. 应用操作
        for op in patch.operations:
            try:
                success = self._apply_operation(new_graph, op)
                if success:
                    applied_count += 1
                else:
                    errors.append(f"Operation {op.type} failed")
            except Exception as e:
                errors.append(f"Operation {op.type} error: {str(e)}")
        
        # 4. 更新版本
        new_graph["version"] = patch.target_version
        
        # 5. 验证新图
        validation_errors = self._validate_graph(new_graph)
        errors.extend(validation_errors)
        
        # 6. 构建结果
        success = len(errors) == 0
        result = GraphPatchResult(
            success=success,
            patch_id=patch.patch_id,
            applied_version=patch.target_version if success else graph.version,
            previous_version=graph.version,
            applied_operations=applied_count,
            failed_operations=len(patch.operations) - applied_count,
            errors=errors,
        )
        
        # 7. 迁移执行指针
        new_pointer = None
        if pointer and success:
            migration_plan = self._create_migration_plan(graph, new_graph, pointer)
            new_pointer = self._migrate_pointer(pointer, migration_plan, patch.target_version)
        
        # 8. 转换为不可变图定义
        final_graph = GraphDefinition(**new_graph) if success else graph
        
        return final_graph, result, new_pointer
    
    def _create_mutable_copy(self, graph: GraphDefinition) -> Dict[str, Any]:
        """创建图的可变副本"""
        return {
            "id": graph.id,
            "version": graph.version,
            "nodes": [dict(node.__dict__) for node in graph.nodes],
            "edges": [dict(edge.__dict__) for edge in graph.edges],
            "subgraphs": list(graph.subgraphs),
            "parent_graph_id": graph.parent_graph_id,
            "metadata": dict(graph.metadata),
            "disabled_nodes": list(graph.disabled_nodes),
        }
    
    def _apply_operation(self, graph: Dict[str, Any], op: PatchOperation) -> bool:
        """应用单个操作"""
        if isinstance(op, AddNodeOperation):
            return self._apply_add_node(graph, op)
        elif isinstance(op, AddEdgeOperation):
            return self._apply_add_edge(graph, op)
        elif isinstance(op, DisableNodeOperation):
            return self._apply_disable_node(graph, op)
        elif isinstance(op, SetMetadataOperation):
            return self._apply_set_metadata(graph, op)
        return False
    
    def _apply_add_node(self, graph: Dict[str, Any], op: AddNodeOperation) -> bool:
        """应用添加节点操作"""
        # 检查节点 ID 是否已存在
        existing_ids = {node["id"] for node in graph["nodes"]}
        if op.node_id in existing_ids:
            raise ValueError(f"Node {op.node_id} already exists")
        
        # 创建新节点
        node = {
            "id": op.node_id,
            "type": NodeType(op.node_type),
            "config": dict(op.config),
            "input_schema": dict(op.input_schema),
            "output_schema": dict(op.output_schema),
            "timeout_seconds": op.timeout_seconds,
            "cacheable": op.config.get("cacheable", False),
        }
        
        if op.retry_policy:
            node["retry_policy"] = RetryPolicy(**op.retry_policy)
        else:
            node["retry_policy"] = RetryPolicy()
        
        graph["nodes"].append(node)
        return True
    
    def _apply_add_edge(self, graph: Dict[str, Any], op: AddEdgeOperation) -> bool:
        """应用添加边操作"""
        # 检查节点是否存在
        node_ids = {node["id"] for node in graph["nodes"]}
        if op.from_node not in node_ids:
            raise ValueError(f"Source node {op.from_node} does not exist")
        if op.to_node not in node_ids:
            raise ValueError(f"Target node {op.to_node} does not exist")
        
        # 检查边是否已存在
        existing_edges = {
            (edge["from_node"], edge["to_node"], edge["on"])
            for edge in graph["edges"]
        }
        if (op.from_node, op.to_node, op.on) in existing_edges:
            raise ValueError(f"Edge from {op.from_node} to {op.to_node} on {op.on} already exists")
        
        # 创建新边
        edge = {
            "from_node": op.from_node,
            "to_node": op.to_node,
            "on": EdgeTrigger(op.on),
            "condition": op.condition,
        }
        graph["edges"].append(edge)
        return True
    
    def _apply_disable_node(self, graph: Dict[str, Any], op: DisableNodeOperation) -> bool:
        """应用禁用节点操作"""
        if op.node_id not in {node["id"] for node in graph["nodes"]}:
            raise ValueError(f"Node {op.node_id} does not exist")
        
        if op.node_id not in graph["disabled_nodes"]:
            graph["disabled_nodes"].append(op.node_id)
        return True
    
    def _apply_set_metadata(self, graph: Dict[str, Any], op: SetMetadataOperation) -> bool:
        """应用设置元数据操作"""
        graph["metadata"][op.key] = op.value
        return True
    
    def _validate_graph(self, graph: Dict[str, Any]) -> List[str]:
        """验证图定义"""
        errors = []
        
        # 检查节点 ID 唯一性
        node_ids = [node["id"] for node in graph["nodes"]]
        if len(node_ids) != len(set(node_ids)):
            errors.append("Duplicate node IDs found")
        
        # 检查边引用的节点是否存在
        node_id_set = set(node_ids)
        for edge in graph["edges"]:
            if edge["from_node"] not in node_id_set:
                errors.append(f"Edge references non-existent from_node: {edge['from_node']}")
            if edge["to_node"] not in node_id_set:
                errors.append(f"Edge references non-existent to_node: {edge['to_node']}")
        
        return errors
    
    def _create_migration_plan(
        self,
        old_graph: GraphDefinition,
        new_graph: Dict[str, Any],
        pointer: ExecutionPointer,
    ) -> PatchMigrationPlan:
        """
        创建执行指针迁移计划
        
        策略：
        1. 保留已完成节点
        2. 重置就绪队列（因为新增节点可能改变依赖关系）
        3. 识别新增依赖
        """
        old_node_ids = {node.id for node in old_graph.nodes}
        new_node_ids = {node["id"] for node in new_graph["nodes"]}
        
        # 新增节点
        added_nodes = new_node_ids - old_node_ids
        
        # 新增依赖：新增节点的入边
        new_dependencies = []
        for edge in new_graph["edges"]:
            if edge["to_node"] in added_nodes:
                new_dependencies.append(edge["to_node"])
        
        return PatchMigrationPlan(
            strategy=PatchMigrationStrategy.PRESERVE_COMPLETED,
            nodes_to_preserve=list(pointer.completed_nodes),
            nodes_to_reset=list(pointer.ready_nodes),
            new_dependencies=list(set(new_dependencies)),
        )
    
    def _migrate_pointer(
        self,
        pointer: ExecutionPointer,
        plan: PatchMigrationPlan,
        new_version: str,
    ) -> ExecutionPointer:
        """迁移执行指针"""
        # 保留已完成节点
        completed = list(plan.nodes_to_preserve)
        
        # 重置就绪队列（新增节点可能改变依赖关系，需要重新计算）
        ready = []
        
        # 保留运行中节点（它们会继续执行）
        running = list(pointer.running_nodes)
        
        # 保留失败节点
        failed = list(pointer.failed_nodes)
        
        return ExecutionPointer(
            instance_id=pointer.instance_id,
            completed_nodes=completed,
            ready_nodes=ready,
            running_nodes=running,
            failed_nodes=failed,
            graph_version=new_version,
            updated_at=datetime.utcnow(),
        )
    
    def generate_next_version(self, current_version: str) -> str:
        """生成下一个版本号"""
        parts = current_version.split(self._version_separator)
        try:
            # 尝试递增最后一部分
            parts[-1] = str(int(parts[-1]) + 1)
        except ValueError:
            # 如果不是数字，追加 .1
            parts.append("1")
        return self._version_separator.join(parts)
