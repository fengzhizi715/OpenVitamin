"""
User Context Middleware
用于在每个请求中统一注入 user_id 到 request.state
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi import Request as FastAPIRequest
from core.utils.user_context import get_user_id, DEFAULT_USER_ID


class UserContextMiddleware(BaseHTTPMiddleware):
    """
    用户上下文中间件
    
    在每个请求的 request.state 中注入 user_id，
    后续可以通过 request.state.user_id 或 get_user_id(request) 获取
    """

    async def dispatch(self, request: Request, call_next):
        # 注入 user_id 到 request.state
        request.state.user_id = get_user_id(request)
        
        response = await call_next(request)
        return response


def get_current_user(request: FastAPIRequest) -> str:
    """
    获取当前用户 ID（FastAPI 依赖注入）
    
    从 request.state.user_id 获取，与 UserContextMiddleware 注入的值一致
    如果没有则回退到 DEFAULT_USER_ID
    """
    return getattr(request.state, "user_id", None) or DEFAULT_USER_ID
