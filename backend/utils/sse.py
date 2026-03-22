"""
SSE（Server-Sent Events）工具函数
"""
import json
from typing import Dict, Any


def format_sse_event(data: Dict[str, Any]) -> str:
    """
    格式化 SSE 事件
    
    Args:
        data: 事件数据字典
    
    Returns:
        格式化的 SSE 事件字符串
    """
    return f"data: {json.dumps(data)}\n\n"


def format_sse_done() -> str:
    """
    格式化 SSE 结束信号
    
    Returns:
        [DONE] 信号
    """
    return "data: [DONE]\n\n"


def parse_sse_line(line: str) -> Dict[str, Any] | None:
    """
    解析 SSE 行
    
    Args:
        line: SSE 行（格式：data: {...}）
    
    Returns:
        解析后的数据字典，或 None 如果是完成信号
    
    Raises:
        json.JSONDecodeError: 如果 JSON 解析失败
    """
    if not line.startswith("data: "):
        return None
    
    data_str = line[6:]
    
    if data_str == "[DONE]":
        return None
    
    return json.loads(data_str)
