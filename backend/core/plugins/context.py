from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory.memory_store import MemoryStore
    from core.models.registry import ModelRegistry
    from core.knowledge.knowledge_base_store import KnowledgeBaseStore
    from core.runtimes.factory import RuntimeFactory
    from core.plugins.registry import PluginRegistry
    from logging import Logger

class PluginContext:
    """
    Plugin 运行上下文
    提供对系统核心能力的访问接口，如日志、记忆、模型注册表等
    """
    def __init__(
        self,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        message_id: Optional[str] = None,
        logger: Optional["Logger"] = None,
        memory: Optional["MemoryStore"] = None,
        registry: Optional["ModelRegistry"] = None,
        knowledge_base_store: Optional["KnowledgeBaseStore"] = None,
        runtime_factory: Optional["RuntimeFactory"] = None,
        plugin_registry: Optional["PluginRegistry"] = None,
    ):
        self.session_id = session_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.message_id = message_id

        self.logger = logger
        self.memory = memory
        self.registry = registry
        self.knowledge_base_store = knowledge_base_store
        self.runtime_factory = runtime_factory
        self.plugin_registry = plugin_registry