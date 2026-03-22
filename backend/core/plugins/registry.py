import importlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Type
from log import logger
from .base import Plugin
from .manifest import PluginManifest

class PluginRegistry:
    """
    Plugin 注册中心
    负责插件的发现、加载与生命周期管理
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PluginRegistry, cls).__new__(cls)
            cls._instance._plugins = {}
        return cls._instance

    def __init__(self):
        # 单例模式：只在首次创建时初始化
        if not hasattr(self, '_initialized'):
            # 如果 _plugins 不存在，说明是首次创建，已经在 __new__ 中初始化了
            # 这里只需要标记已初始化，避免重复初始化
            self._initialized = True

    def register(self, plugin: Plugin):
        """手动注册插件实例"""
        self._plugins[plugin.name] = plugin
        logger.info(f"[PluginRegistry] Registered plugin: {plugin.name} (v{plugin.version})")

    def get(self, name: str) -> Optional[Plugin]:
        """获取插件实例"""
        return self._plugins.get(name)

    def list(self) -> List[Plugin]:
        """列出所有已注册插件"""
        return list(self._plugins.values())

    async def load_builtin_plugins(self, logger=None, memory=None, model_registry=None):
        """加载内置插件"""
        builtin_path = Path(__file__).parent / "builtin"
        if not builtin_path.exists():
            return

        for item in builtin_path.iterdir():
            if item.is_dir():
                manifest_file = item / "plugin.json"
                if manifest_file.exists():
                    await self._load_from_manifest(manifest_file, logger, memory, model_registry)

    async def _load_from_manifest(self, manifest_path: Path, logger=None, memory=None, model_registry=None):
        """
        从 manifest 文件加载插件
        :raises ImportError: 如果模块导入失败（致命错误）
        :raises AttributeError: 如果类不存在（致命错误）
        :raises ValueError: 如果 manifest 数据无效（致命错误）
        """
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            manifest = PluginManifest(**data)
            
            # 动态加载入口类
            try:
                module_path, class_name = manifest.entry.split(":")
                module = importlib.import_module(module_path)
            except (ImportError, ValueError) as e:
                # 模块导入失败是致命错误，应该抛出
                logger.error(f"[PluginRegistry] Failed to import module '{module_path}' from {manifest_path}: {e}")
                raise
            
            try:
                plugin_class: Type[Plugin] = getattr(module, class_name)
            except AttributeError as e:
                # 类不存在是致命错误，应该抛出
                logger.error(f"[PluginRegistry] Class '{class_name}' not found in module '{module_path}' from {manifest_path}: {e}")
                raise
            
            # 实例化插件并注入元数据
            plugin_inst = plugin_class()
            plugin_inst.name = manifest.name
            plugin_inst.version = manifest.version
            plugin_inst.description = manifest.description
            plugin_inst.type = manifest.type
            plugin_inst.stage = manifest.stage
            plugin_inst.input_schema = manifest.input_schema
            plugin_inst.output_schema = manifest.output_schema
            plugin_inst.supported_modes = manifest.supported_modes
            plugin_inst.permissions = manifest.permissions or []
            
            # 初始化插件
            from .context import PluginContext
            context = PluginContext(
                logger=logger,
                memory=memory,
                registry=model_registry
            )
            try:
                initialized = await plugin_inst.initialize(context)
                if not initialized:
                    logger.warning(f"[PluginRegistry] Plugin '{manifest.name}' initialization returned False")
                    return  # 初始化失败，跳过注册但不抛出异常（可恢复错误）
                
                # 检查就绪状态
                if not await plugin_inst.ready():
                    logger.warning(f"[PluginRegistry] Plugin '{manifest.name}' is not ready after initialization")
                    return  # 未就绪，跳过注册但不抛出异常（可恢复错误）
            except Exception as e:
                # 初始化过程中的异常，记录但继续（可恢复错误）
                logger.warning(f"[PluginRegistry] Plugin '{manifest.name}' initialization raised exception: {e}")
                return
            
            self.register(plugin_inst)
            
        except (ImportError, AttributeError, ValueError) as e:
            # 致命错误：重新抛出
            logger.error(f"[PluginRegistry] Fatal error loading plugin from {manifest_path}: {e}")
            raise
        except Exception as e:
            # 其他错误：记录但不抛出（可恢复错误）
            logger.error(f"[PluginRegistry] Failed to load plugin from {manifest_path}: {e}")

def get_plugin_registry() -> PluginRegistry:
    """获取全局单例"""
    return PluginRegistry()
