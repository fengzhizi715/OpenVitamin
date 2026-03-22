"""Vision 工具注册"""

from core.tools.registry import ToolRegistry
from core.tools.yolo import YOLODetectObjectsTool
from core.tools.yolo.segment_tool import SegmentObjectsTool


def register():
    ToolRegistry.register(YOLODetectObjectsTool())
    ToolRegistry.register(SegmentObjectsTool())
