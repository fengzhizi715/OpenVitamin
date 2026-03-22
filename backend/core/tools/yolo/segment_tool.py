"""
vision.segment_objects: FastSAM 实例分割 Tool

通过 FastSAM backend 做实例分割，返回 objects（含 bbox + 可选 mask）及可选标注图。
标注图：多实例、多块彩色 mask + 轮廓，每个实例不同颜色。
"""

import base64
import io
from typing import Any, Dict, List

import numpy as np
from PIL import Image, ImageFilter

from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from log import logger

from .router import get_yolo_router
from .segment_manifest import SEGMENT_INPUT_SCHEMA, SEGMENT_OUTPUT_SCHEMA

# 复用 detect_objects 的输入解析与无 mask 时的 bbox 标注
from .tool import _parse_image_input, _draw_annotated_image


# 每实例一色，高对比度、易区分
_SEGMENT_PALETTE = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255),
    (0, 255, 255), (255, 128, 0), (128, 255, 0), (0, 128, 255), (255, 0, 128),
    (128, 0, 255), (128, 128, 255), (255, 128, 128), (128, 255, 128), (128, 128, 255),
]


def _draw_segment_annotated_image(pil_image: Image.Image, detections: List[Any]) -> str:
    """
    在原图上绘制多实例彩色 mask + 轮廓，返回 base64 data URL。
    每个实例不同颜色，mask 半透明叠加，轮廓为深色描边。
    detections 中每项需有 .bbox, .label, .confidence，可选 .mask（base64 PNG）。
    若没有任何 mask，则回退为 bbox 标注图。
    """
    if not any(getattr(d, "mask", None) for d in detections):
        return _draw_annotated_image(pil_image, detections)

    img = pil_image.copy()
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    base = np.array(img, dtype=np.uint8)

    # 先叠所有彩色 mask，再统一画轮廓，避免轮廓被后续 mask 盖住
    overlays = []
    outline_masks = []  # (outline_binary, color)
    outline_color = (40, 40, 40)

    for i, d in enumerate(detections):
        mask_b64 = getattr(d, "mask", None)
        if not mask_b64:
            continue
        try:
            raw = base64.b64decode(mask_b64)
            mask_pil = Image.open(io.BytesIO(raw)).convert("L")
        except Exception:
            continue
        mask_np = np.array(mask_pil, dtype=np.uint8)
        if mask_np.size == 0:
            continue
        # 二值化
        thresh = (mask_np > 127).astype(np.uint8)
        if thresh.shape[0] != h or thresh.shape[1] != w:
            mask_pil = mask_pil.resize((w, h), Image.Resampling.NEAREST)
            thresh = (np.array(mask_pil, dtype=np.uint8) > 127).astype(np.uint8)

        color = _SEGMENT_PALETTE[i % len(_SEGMENT_PALETTE)]
        alpha = 0.45
        overlay = np.zeros((h, w, 4), dtype=np.uint8)
        overlay[thresh > 0] = (*color, int(255 * alpha))
        overlays.append(overlay)

        # 轮廓：dilate - mask
        dilated = mask_pil.filter(ImageFilter.MaxFilter(3))
        dilated_np = (np.array(dilated, dtype=np.uint8) > 127).astype(np.uint8)
        if dilated_np.shape[0] != h or dilated_np.shape[1] != w:
            dilated_pil = Image.fromarray((dilated_np * 255).astype(np.uint8)).resize((w, h), Image.Resampling.NEAREST)
            dilated_np = (np.array(dilated_pil) > 127).astype(np.uint8)
        outline = (dilated_np > 0) & (thresh == 0)
        outline_masks.append((outline, outline_color))

    # 合成：先画所有半透明 mask，再画轮廓
    out = base.copy()
    for overlay in overlays:
        mask_alpha = overlay[:, :, 3] > 0
        a = overlay[:, :, 3] / 255.0
        for c in range(3):
            out[:, :, c] = np.where(mask_alpha, (out[:, :, c] * (1 - a) + overlay[:, :, c] * a).astype(np.uint8), out[:, :, c])
    for outline, color in outline_masks:
        for c in range(3):
            out[:, :, c] = np.where(outline, color[c], out[:, :, c])

    result_pil = Image.fromarray(out)
    buf = io.BytesIO()
    result_pil.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


class SegmentObjectsTool(Tool):
    """FastSAM 实例分割 Tool"""

    def __init__(self):
        self._router = get_yolo_router()

    @property
    def name(self) -> str:
        return "vision.segment_objects"

    @property
    def description(self) -> str:
        return (
            "Segment objects in an image using FastSAM (instance segmentation). "
            "Input: image as base64 data URL or file path relative to workspace. "
            "Output: objects (label, confidence, bbox, mask as base64 PNG), image_size, and optionally annotated_image. "
            "Set output_annotated_image=true to get a drawn image with colored masks and outlines per instance."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return SEGMENT_INPUT_SCHEMA

    @property
    def output_schema(self) -> Dict[str, Any]:
        return SEGMENT_OUTPUT_SCHEMA

    @property
    def required_permissions(self) -> List[str]:
        return ["file.read"]

    @property
    def capabilities(self) -> List[str]:
        return ["vision.instance_segmentation"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Instance Segmentation",
            "icon": "Scan",
            "category": "vision",
            "permissions_hint": [{"key": "file.read", "label": "Read image files from workspace."}],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            image_raw = input_data.get("image")
            confidence_threshold = float(input_data.get("confidence_threshold", 0.4))
            output_annotated = bool(input_data.get("output_annotated_image", True))

            pil_image, image_size = _parse_image_input(image_raw, ctx.workspace or ".")

            backend = self._router.get("fastsam")
            detections = await backend.detect(
                image=pil_image,
                confidence_threshold=confidence_threshold,
            )

            result = {
                "objects": [
                    {
                        "label": d.label,
                        "confidence": round(d.confidence, 4),
                        "bbox": list(d.bbox),
                        **({"mask": d.mask} if getattr(d, "mask", None) else {}),
                    }
                    for d in detections
                ],
                "image_size": list(image_size),
            }
            if output_annotated:
                result["annotated_image"] = _draw_segment_annotated_image(pil_image, detections)
            logger.info(
                f"[vision.segment_objects] backend={backend.name} segmented {len(detections)} objects"
            )
            return ToolResult(success=True, data=result)
        except ValueError as e:
            return ToolResult(success=False, data=None, error=str(e))
        except FileNotFoundError as e:
            return ToolResult(success=False, data=None, error=str(e))
        except Exception as e:
            logger.exception(f"[vision.segment_objects] Failed: {e}")
            return ToolResult(success=False, data=None, error=str(e))
