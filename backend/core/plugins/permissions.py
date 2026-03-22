from typing import List, Set

class PluginPermissions:
    """
    Plugin 权限管理 (v2 规划)
    定义插件可访问的资源边界
    """
    def __init__(self, allowed_scopes: Set[str]):
        self.allowed_scopes = allowed_scopes

    def has_permission(self, scope: str) -> bool:
        return scope in self.allowed_scopes or "*" in self.allowed_scopes
