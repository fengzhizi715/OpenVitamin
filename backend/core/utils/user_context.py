"""
User Context Utilities
用于多用户架构的用户 ID 获取和管理
"""
from typing import Optional
from fastapi import Request

# 默认用户 ID（当 Header 不存在时使用）
DEFAULT_USER_ID = "default"

# HTTP Header 名称（支持多种格式以兼容不同客户端）
USER_ID_HEADERS = [
    "x-user-id",
    "X-User-Id",
    "X-UserID",
    "x-userid",
]

# request.state 属性名
USER_ID_ATTR = "user_id"


class UserAccessDeniedError(Exception):
    """用户无权限访问资源"""
    def __init__(self, resource_type: str, resource_id: str = None, user_id: str = None):
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.user_id = user_id
        message = f"Access denied to {resource_type}"
        if resource_id:
            message += f" {resource_id}"
        if user_id:
            message += f" for user {user_id}"
        super().__init__(message)


class ResourceNotFoundError(Exception):
    """资源不存在"""
    def __init__(self, resource_type: str, resource_id: str):
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(f"{resource_type} {resource_id} not found")


def get_user_id(request: Request, default: str = DEFAULT_USER_ID) -> str:
    """
    从 HTTP 请求中获取用户 ID
    
    优先级：
    1. request.state.user_id（中间件已注入）
    2. HTTP Header（X-User-Id / X-UserID）
    3. default（fallback）
    
    Args:
        request: FastAPI Request 对象
        default: 默认用户 ID
        
    Returns:
        用户 ID 字符串
    """
    # 1. 优先从 request.state 获取（中间件注入）
    if hasattr(request.state, USER_ID_ATTR):
        state_user_id = getattr(request.state, USER_ID_ATTR, None)
        if state_user_id:
            return state_user_id
    
    # 2. 从 HTTP Header 获取（兼容多种 Header 名称）
    for header_name in USER_ID_HEADERS:
        user_id = request.headers.get(header_name)
        if user_id:
            return user_id
    
    return default


def get_user_id_from_optional(user_id: Optional[str], default: str = DEFAULT_USER_ID) -> str:
    """
    从可选参数中获取用户 ID
    
    Args:
        user_id: 可选的用户 ID
        default: 默认用户 ID
        
    Returns:
        用户 ID 字符串
    """
    if user_id:
        return user_id
    return default
