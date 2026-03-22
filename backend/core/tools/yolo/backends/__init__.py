"""YOLO Backends"""

from .base import Detection, YOLOBackend
from .yolov8 import YOLOv8Backend
from .yolov11 import YOLOv11Backend
from .onnx import ONNXBackend
from .yolov26 import YOLOv26Backend
from .fastsam import FastSAMBackend

__all__ = [
    "Detection",
    "YOLOBackend",
    "YOLOv8Backend",
    "YOLOv11Backend",
    "YOLOv26Backend",
    "ONNXBackend",
    "FastSAMBackend",
]
