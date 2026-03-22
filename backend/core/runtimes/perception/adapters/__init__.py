"""Perception 适配器"""

from .yolo_object_detection_adapter import YoloObjectDetectionAdapter
from .fastsam_adapter import FastSAMAdapter

# 预留接口，不实现
# from .segmentation_adapter import SegmentationAdapter
# from .pose_adapter import PoseAdapter

__all__ = ["YoloObjectDetectionAdapter", "FastSAMAdapter"]
