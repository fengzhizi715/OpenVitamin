from typing import Dict, Any, Optional
import jsonschema
from jsonschema import ValidationError
from log import logger
from .registry import PluginRegistry, get_plugin_registry
from .context import PluginContext
from .permissions import PluginPermissions

class PluginExecutor:
    """
    Plugin 执行器
    负责插件的调用、Schema 校验与安全性检查
    """
    def __init__(self, registry: Optional[PluginRegistry] = None):
        self.registry = registry or get_plugin_registry()

    def _check_permissions(self, plugin, context: PluginContext) -> bool:
        """
        检查插件权限
        :param plugin: 插件实例
        :param context: 运行上下文
        :return: 是否有权限
        
        注意：当前是简化实现，默认允许所有权限。
        未来可以根据 context.user_id 或系统配置进行实际权限验证。
        """
        if not plugin.permissions:
            return True  # 无权限要求，允许执行
        
        # TODO: 实现基于用户/会话的实际权限检查
        # 当前简化实现：默认允许所有权限
        # 实际应该：
        # 1. 从 context.user_id 获取用户权限
        # 2. 或从系统配置中获取允许的权限列表
        # 3. 检查 plugin.permissions 是否都在允许列表中
        
        logger.debug(f"[PluginExecutor] Plugin '{plugin.name}' requires permissions: {plugin.permissions} (currently all allowed)")
        return True

    def _validate_schema(self, data: Dict[str, Any], schema: Dict[str, Any], schema_name: str) -> None:
        """
        验证数据是否符合 JSON Schema
        :param data: 要验证的数据
        :param schema: JSON Schema 定义
        :param schema_name: Schema 名称（用于错误信息）
        :raises ValueError: 如果验证失败
        """
        if not schema:
            return  # 无 Schema 定义，跳过验证
        
        try:
            jsonschema.validate(instance=data, schema=schema)
        except ValidationError as e:
            error_msg = f"Schema validation failed for {schema_name}: {e.message}"
            if e.path:
                error_msg += f" (path: {'/'.join(str(p) for p in e.path)})"
            logger.error(f"[PluginExecutor] {error_msg}")
            raise ValueError(error_msg) from e

    async def execute(
        self,
        name: str,
        input_data: Dict[str, Any],
        context: PluginContext
    ) -> Dict[str, Any]:
        """
        执行指定名称的插件
        :param name: 插件名称
        :param input_data: 输入数据
        :param context: 运行上下文
        :return: 插件执行结果
        :raises ValueError: 如果插件不存在、权限不足或 Schema 验证失败
        """
        plugin = self.registry.get(name)
        if not plugin:
            raise ValueError(f"Plugin '{name}' not found")

        # 检查插件是否就绪
        if not await plugin.ready():
            raise RuntimeError(f"Plugin '{name}' is not ready")

        # 权限检查
        if not self._check_permissions(plugin, context):
            raise PermissionError(f"Plugin '{name}' requires permissions that are not granted")

        # 输入 Schema 校验
        try:
            self._validate_schema(input_data, plugin.input_schema, f"input schema of '{name}'")
        except ValueError as e:
            # Schema 验证失败是致命错误，应该抛出
            raise

        try:
            logger.debug(f"[PluginExecutor] Executing plugin: {name}")
            result = await plugin.execute(input_data, context)
            
            # 输出 Schema 校验
            self._validate_schema(result, plugin.output_schema, f"output schema of '{name}'")
            
            return result
        except ValueError as e:
            # Schema 验证错误，直接抛出
            raise
        except PermissionError as e:
            # 权限错误，直接抛出
            raise
        except Exception as e:
            # 其他错误，记录并抛出
            logger.error(f"[PluginExecutor] Failed to execute plugin '{name}': {e}", exc_info=True)
            raise

def get_plugin_executor() -> PluginExecutor:
    """获取全局执行器实例"""
    return PluginExecutor()
