from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from .context import PluginContext

class Plugin(ABC):
    """
    Plugin 抽象基类
    所有插件必须继承此类并实现 execute 方法
    
    生命周期：load → initialize → ready → execute → teardown
    """
    name: str
    description: str
    version: str
    type: str  # "system" | "model" | "capability"
    stage: str  # "pre" | "post" | "tool" | "router"

    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    supported_modes: List[str]  # e.g., ["chat", "agent", "task"]
    permissions: Optional[List[str]] = None  # 所需权限列表

    def __init__(self):
        """初始化插件状态"""
        self._initialized = False
        self._ready = False

    async def initialize(self, context: PluginContext) -> bool:
        """
        初始化插件
        :param context: 运行上下文
        :return: 是否初始化成功
        """
        self._initialized = True
        return True

    async def ready(self) -> bool:
        """
        检查插件是否就绪
        :return: 是否就绪
        """
        if not self._initialized:
            return False
        self._ready = True
        return True

    @abstractmethod
    async def execute(
        self,
        input: Dict[str, Any],
        context: PluginContext
    ) -> Dict[str, Any]:
        """
        执行插件逻辑
        :param input: 符合 input_schema 的输入数据
        :param context: 运行上下文
        :return: 符合 output_schema 的输出结果
        """
        ...

    async def teardown(self):
        """
        清理资源
        在插件卸载时调用
        """
        self._ready = False
        self._initialized = False
