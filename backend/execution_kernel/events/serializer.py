"""
V2.6: Observability & Replay Layer - Event Serializer
事件序列化/反序列化工具
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class EventSerializer:
    """
    事件序列化器
    
    处理：
    - datetime 序列化为 ISO 格式
    - 异常对象序列化
    - 二进制数据安全处理
    """
    
    @staticmethod
    def serialize(payload: Dict[str, Any]) -> str:
        """
        序列化事件负载为 JSON 字符串
        
        Args:
            payload: 事件负载字典
            
        Returns:
            JSON 字符串
        """
        def default_converter(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, Exception):
                return {
                    "type": type(obj).__name__,
                    "message": str(obj),
                }
            if isinstance(obj, bytes):
                return f"<bytes:{len(obj)}>"
            if isinstance(obj, set):
                return list(obj)
            return str(obj)
        
        try:
            return json.dumps(payload, default=default_converter, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Event serialization failed: {e}")
            # 降级：返回简化版本
            return json.dumps({
                "_serialization_error": str(e),
                "_original_keys": list(payload.keys()),
            })
    
    @staticmethod
    def deserialize(json_str: str) -> Dict[str, Any]:
        """
        反序列化 JSON 字符串为事件负载
        
        Args:
            json_str: JSON 字符串
            
        Returns:
            事件负载字典
        """
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Event deserialization failed: {e}")
            return {"_deserialization_error": str(e)}
    
    @staticmethod
    def safe_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        清理 payload，确保可序列化
        
        移除或转换不可序列化的值
        """
        result = {}
        for key, value in payload.items():
            # 处理特殊类型
            if isinstance(value, Exception):
                result[key] = {
                    "type": type(value).__name__,
                    "message": str(value),
                }
            elif isinstance(value, bytes):
                result[key] = f"<bytes:{len(value)}>"
            elif callable(value):
                # 函数/lambda 转为字符串表示
                result[key] = f"<{type(value).__name__}>"
            elif isinstance(value, (datetime, set)):
                # 这些类型可以用 default=str 处理
                result[key] = value
            else:
                # 尝试直接序列化
                try:
                    json.dumps({key: value})
                    result[key] = value
                except (TypeError, ValueError):
                    # 不可序列化，转换为字符串
                    result[key] = f"<{type(value).__name__}>"
        return result
