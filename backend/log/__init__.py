"""
backend/log - 平台统一日志

提供：
- logger: 标准 Logger 实例（控制台 + 文件轮转）
- log_structured(component, event, level="info", **kwargs): 结构化 JSON 日志
- setup_logger(...): 可选，重新配置或创建具名 logger
"""
from .logger import logger, log_structured, setup_logger

__all__ = ["logger", "log_structured", "setup_logger"]
