"""
V2.6: Observability & Replay Layer - Replay Engine
事件回放引擎
"""

from typing import Optional, List, Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from execution_kernel.events.event_store import EventStore
from execution_kernel.replay.state_rebuilder import StateRebuilder, RebuiltGraphState
from execution_kernel.optimization.scheduler.policy_base import SchedulerPolicy
from execution_kernel.optimization.scheduler.default_policy import DefaultPolicy
from execution_kernel.optimization.snapshot.snapshot import OptimizationSnapshot


logger = logging.getLogger(__name__)


class ReplayEngine:
    """
    回放引擎
    
    职责：
    - 从事件存储加载事件流
    - 重建执行状态（仅用于 Debug，不重新执行节点）
    - 提供状态对比和验证
    
    使用场景：
    - 调试：重建历史执行状态
    - 审计：验证执行过程
    - 测试：验证事件完整性
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.event_store = EventStore(session)
        self.rebuilder = StateRebuilder()
    
    async def rebuild_instance(
        self,
        instance_id: str,
        start_sequence: int = 1,
        end_sequence: Optional[int] = None,
    ) -> RebuiltGraphState:
        """
        重建实例状态
        
        Args:
            instance_id: 图实例 ID
            start_sequence: 起始序列号
            end_sequence: 结束序列号（None 表示到最后）
            
        Returns:
            重建的图状态
        """
        logger.info(f"Rebuilding instance {instance_id} from seq {start_sequence} to {end_sequence}")
        
        # 加载事件流
        events = await self.event_store.get_events(
            instance_id=instance_id,
            start_sequence=start_sequence,
            end_sequence=end_sequence,
        )
        
        if not events:
            raise ValueError(f"No events found for instance {instance_id}")
        
        logger.info(f"Loaded {len(events)} events for replay")
        
        # 重建状态
        state = self.rebuilder.rebuild(events)
        
        logger.info(
            f"Replay completed: {len(state.nodes)} nodes, "
            f"state={state.state}, events={state.event_count}"
        )
        
        return state
    
    async def replay_to_point(
        self,
        instance_id: str,
        target_sequence: int,
    ) -> RebuiltGraphState:
        """
        回放到指定序列号（用于断点调试）
        
        Args:
            instance_id: 图实例 ID
            target_sequence: 目标序列号
            
        Returns:
            重建的图状态（到指定序列号）
        """
        return await self.rebuild_instance(
            instance_id=instance_id,
            start_sequence=1,
            end_sequence=target_sequence,
        )
    
    async def validate_event_stream(
        self,
        instance_id: str,
    ) -> Dict[str, Any]:
        """
        验证事件流的完整性
        
        检查：
        - 序列号连续性
        - 必须有 GraphStarted
        - 必须有终止事件（GraphCompleted/Failed/Cancelled）
        - Node 状态转换合法性
        
        Returns:
            验证报告
        """
        events = await self.event_store.get_events(instance_id)
        
        if not events:
            return {
                "valid": False,
                "error": "No events found",
            }
        
        errors = []
        
        # 1. 检查序列号连续性
        expected_seq = 1
        for event in events:
            if event.sequence != expected_seq:
                errors.append(
                    f"Sequence gap: expected {expected_seq}, got {event.sequence}"
                )
            expected_seq = event.sequence + 1
        
        # 2. 检查必须有 GraphStarted
        has_start = any(
            e.event_type.value == "graph_started" for e in events
        )
        if not has_start:
            errors.append("Missing graph_started event")
        
        # 3. 检查必须有终止事件
        from execution_kernel.events.event_types import TERMINAL_EVENTS
        terminal_types = {e.value for e in TERMINAL_EVENTS}
        has_terminal = any(
            e.event_type.value in terminal_types for e in events
        )
        if not has_terminal:
            errors.append("Missing terminal event (completed/failed/cancelled)")
        
        # 4. 重建状态并检查
        try:
            state = self.rebuilder.rebuild(events)
            node_count = len(state.nodes)
        except Exception as e:
            errors.append(f"Rebuild failed: {e}")
            node_count = 0
        
        return {
            "valid": len(errors) == 0,
            "event_count": len(events),
            "node_count": node_count,
            "errors": errors,
            "first_sequence": events[0].sequence if events else None,
            "last_sequence": events[-1].sequence if events else None,
        }
    
    async def compare_with_runtime(
        self,
        instance_id: str,
        runtime_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        对比重建状态与运行时状态
        
        用于验证事件流是否完整记录了执行过程
        
        Args:
            instance_id: 图实例 ID
            runtime_state: 运行时状态（从数据库读取）
            
        Returns:
            对比报告
        """
        try:
            rebuilt = await self.rebuild_instance(instance_id)
        except Exception as e:
            return {
                "match": False,
                "error": f"Failed to rebuild: {e}",
            }
        
        differences = []
        
        # 对比 Graph 状态
        if rebuilt.state != runtime_state.get("state"):
            differences.append({
                "field": "state",
                "rebuilt": rebuilt.state,
                "runtime": runtime_state.get("state"),
            })
        
        # 对比 Node 状态
        runtime_nodes = runtime_state.get("nodes", {})
        for node_id, node in rebuilt.nodes.items():
            runtime_node = runtime_nodes.get(node_id)
            if runtime_node is None:
                differences.append({
                    "field": f"node.{node_id}",
                    "rebuilt": node.state.value,
                    "runtime": "missing",
                })
            elif node.state.value != runtime_node.get("state"):
                differences.append({
                    "field": f"node.{node_id}.state",
                    "rebuilt": node.state.value,
                    "runtime": runtime_node.get("state"),
                })
        
        return {
            "match": len(differences) == 0,
            "differences": differences,
            "rebuilt_node_count": len(rebuilt.nodes),
            "runtime_node_count": len(runtime_nodes),
        }
    
    async def replay_with_policy(
        self,
        instance_id: str,
        scheduler_policy: SchedulerPolicy,
        optimization_snapshot: Optional[OptimizationSnapshot] = None,
        start_sequence: int = 1,
        end_sequence: Optional[int] = None,
    ) -> RebuiltGraphState:
        """
        V2.7: 使用指定策略回放事件
        
        用于验证在特定策略和快照下，调度顺序是否与原始执行一致。
        
        Args:
            instance_id: 图实例 ID
            scheduler_policy: 调度策略（用于验证调度决策）
            optimization_snapshot: 优化快照（可选）
            start_sequence: 起始序列号
            end_sequence: 结束序列号
            
        Returns:
            重建的图状态
        """
        logger.info(
            f"Replaying instance {instance_id} with policy "
            f"{scheduler_policy.get_name()} v{scheduler_policy.get_version()}"
        )
        
        # 加载事件流
        events = await self.event_store.get_events(
            instance_id=instance_id,
            start_sequence=start_sequence,
            end_sequence=end_sequence,
        )
        
        if not events:
            raise ValueError(f"No events found for instance {instance_id}")
        
        # 重建状态
        state = self.rebuilder.rebuild(events)
        
        # 添加策略信息到状态
        state.context["_replay_policy"] = {
            "policy_name": scheduler_policy.get_name(),
            "policy_version": scheduler_policy.get_version(),
            "snapshot_version": optimization_snapshot.version if optimization_snapshot else None,
        }
        
        logger.info(
            f"Replay with policy completed: {len(state.nodes)} nodes, "
            f"state={state.state}"
        )
        
        return state
    
    async def get_scheduler_decisions(
        self,
        instance_id: str,
    ) -> List[Dict[str, Any]]:
        """
        V2.7: 获取实例的所有调度决策
        
        用于分析调度顺序和策略效果。
        
        Returns:
            调度决策列表
        """
        events = await self.event_store.get_events(instance_id)
        
        decisions = []
        for event in events:
            if event.event_type.value == "scheduler_decision":
                decisions.append({
                    "sequence": event.sequence,
                    "timestamp": event.timestamp,
                    "ready_nodes": event.payload.get("ready_nodes", []),
                    "selected_node": event.payload.get("selected_node"),
                    "strategy": event.payload.get("strategy"),
                    "decision_reason": event.payload.get("decision_reason"),
                    # V2.7: 包含策略和快照版本
                    "policy_version": event.payload.get("policy_version"),
                    "snapshot_version": event.payload.get("snapshot_version"),
                })
        
        return decisions
    
    async def validate_replay_determinism(
        self,
        instance_id: str,
        expected_policy_version: Optional[str] = None,
        expected_snapshot_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        V2.7: 验证 Replay 的确定性
        
        检查事件流中记录的调度决策是否与预期策略一致。
        
        Args:
            instance_id: 图实例 ID
            expected_policy_version: 预期的策略版本
            expected_snapshot_version: 预期的快照版本
            
        Returns:
            验证报告
        """
        events = await self.event_store.get_events(instance_id)
        
        if not events:
            return {
                "valid": False,
                "error": "No events found",
            }
        
        # 从事件中提取策略信息（V2.7: 包含 policy_version 和 snapshot_version）
        policy_info = {}
        for event in events:
            if event.event_type.value == "scheduler_decision":
                strategy = event.payload.get("strategy")
                if strategy:
                    policy_info["policy_name"] = strategy
                    # V2.7: 提取完整策略信息
                    policy_info["policy_version"] = event.payload.get("policy_version")
                    policy_info["snapshot_version"] = event.payload.get("snapshot_version")
                    break
        
        errors = []
        
        # V2.7: 检查策略版本（如果提供了预期值）
        if expected_policy_version is not None:
            actual_policy_version = policy_info.get("policy_version")
            if actual_policy_version is None:
                # 兼容 V2.6 事件（没有 policy_version 字段）
                errors.append(
                    "No policy_version in events (V2.6 event stream), "
                    "cannot verify determinism"
                )
            elif actual_policy_version != expected_policy_version:
                errors.append(
                    f"Policy version mismatch: expected {expected_policy_version}, "
                    f"got {actual_policy_version}"
                )
        
        # V2.7: 检查快照版本（如果提供了预期值）
        if expected_snapshot_version is not None:
            actual_snapshot_version = policy_info.get("snapshot_version")
            if actual_snapshot_version is None:
                # 快照可能未启用
                if expected_snapshot_version is not None:
                    errors.append(
                        f"Snapshot version mismatch: expected {expected_snapshot_version}, "
                        f"but no snapshot was used during execution"
                    )
            elif actual_snapshot_version != expected_snapshot_version:
                errors.append(
                    f"Snapshot version mismatch: expected {expected_snapshot_version}, "
                    f"got {actual_snapshot_version}"
                )
        
        # 重建状态并验证
        try:
            state = self.rebuilder.rebuild(events)
            rebuild_success = True
        except Exception as e:
            errors.append(f"Rebuild failed: {e}")
            rebuild_success = False
            state = None
        
        return {
            "valid": len(errors) == 0 and rebuild_success,
            "policy_info": policy_info,
            "expected_policy_version": expected_policy_version,
            "expected_snapshot_version": expected_snapshot_version,
            "errors": errors,
            "event_count": len(events),
            "rebuilt_node_count": len(state.nodes) if state else 0,
        }
