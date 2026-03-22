"""
vision.detect_objects: YOLO 目标检测 Tool

对外唯一入口，通过 Router 选择 backend，Agent/Skill 无感。
流程：YOLO 检测 → 可选绘制标注图 → 返回 objects + 标注图（供 VLM 自然语言解释）
"""

import base64
import io
import re
from pathlib import Path
from typing import Any, Dict, List, TYPE_CHECKING

from core.tools.base import Tool

if TYPE_CHECKING:
    from PIL import Image
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError
from log import logger

from .router import get_yolo_router
from .manifest import INPUT_SCHEMA, OUTPUT_SCHEMA


def _parse_image_input(image: str, workspace: str) -> tuple:
    """
    解析 image 参数，返回 (PIL.Image, (width, height))。
    支持：base64 data URL、workspace 内文件路径
    """
    if not image or not isinstance(image, str):
        raise ValueError("image 必填")

    image = image.strip()

    # base64 data URL
    m = re.match(r"^data:image/[a-zA-Z0-9+.-]+;base64,(.+)$", image, re.DOTALL)
    if m:
        try:
            data = base64.b64decode(m.group(1))
        except Exception as e:
            raise ValueError(f"base64 解码失败: {e}") from e
        try:
            from PIL import Image
            pil = Image.open(io.BytesIO(data)).convert("RGB")
            return pil, pil.size
        except ImportError:
            raise ImportError("PIL 未安装，无法解析 base64 图像")
        except Exception as e:
            raise ValueError(f"图像解析失败: {e}") from e

    # 文件路径
    allowed_roots = ["/"]
    try:
        from config.settings import settings
        raw = getattr(settings, "file_read_allowed_roots", None) or ""
        roots = [r.strip() for r in str(raw).split(",") if r.strip()]
        if roots:
            allowed_roots = roots
    except Exception:
        pass

    try:
        resolved = resolve_in_workspace(
            workspace=workspace or ".",
            path=image,
            allowed_absolute_roots=allowed_roots,
        )
        if not resolved.is_file():
            raise ValueError(f"文件不存在: {resolved}")
        from PIL import Image
        pil = Image.open(resolved).convert("RGB")
        return pil, pil.size
    except WorkspacePathError as e:
        raise ValueError(str(e)) from e


def _draw_annotated_image(
    pil_image: "Image.Image",
    detections: List[Any],
) -> str:
    """
    在原图上绘制 bbox 和标签，返回 base64 data URL。
    bbox 为归一化坐标 [x1, y1, x2, y2] (0~1)。
    """
    from PIL import ImageDraw, ImageFont

    img = pil_image.copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # 尝试使用默认字体，避免中文乱码
    font_size = max(16, int(min(w, h) / 50))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255),
        (0, 255, 255), (128, 0, 0), (0, 128, 0), (0, 0, 128), (128, 128, 0),
    ]

    # 框线粗细随分辨率略微放大，避免小图难以辨认
    line_width = max(3, int(min(w, h) / 200))
    for i, d in enumerate(detections):
        x1, y1, x2, y2 = d.bbox
        x1_px = int(x1 * w)
        y1_px = int(y1 * h)
        x2_px = int(x2 * w)
        y2_px = int(y2 * h)
        color = colors[i % len(colors)]
        label = f"{d.label} {d.confidence:.2f}"
        draw.rectangle([x1_px, y1_px, x2_px, y2_px], outline=color, width=line_width)
        label_y = max(0, y1_px - (font_size + 6))
        draw.text((x1_px, label_y), label, fill=color, font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


class YOLODetectObjectsTool(Tool):
    """YOLO 目标检测 Tool，内部通过 Router 选择 backend"""

    def __init__(self):
        self._router = get_yolo_router()

    @property
    def name(self) -> str:
        return "vision.detect_objects"

    @property
    def description(self) -> str:
        return (
            "Detect objects in an image using YOLO. "
            "Input: image as base64 data URL or file path relative to workspace. "
            "Output: objects (label, confidence, bbox), image_size, and optionally annotated_image (base64). "
            "Set output_annotated_image=true to get a drawn image for the user. "
            "Agent should then feed the objects to VLM for natural language explanation."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return INPUT_SCHEMA

    @property
    def output_schema(self) -> Dict[str, Any]:
        return OUTPUT_SCHEMA

    @property
    def required_permissions(self) -> List[str]:
        return ["file.read"]

    @property
    def capabilities(self) -> List[str]:
        return ["vision.object_detection"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Object Detection",
            "icon": "ScanSearch",
            "category": "vision",
            "permissions_hint": [{"key": "file.read", "label": "Read image files from workspace."}],
        }

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            image_raw = input_data.get("image")
            confidence_threshold = float(input_data.get("confidence_threshold", 0.25))
            output_annotated = bool(input_data.get("output_annotated_image", True))
            backend_name = input_data.get("backend")

            pil_image, image_size = _parse_image_input(image_raw, ctx.workspace or ".")

            backend = self._router.get(backend_name) if backend_name else self._router.default()
            detections = await backend.detect(
                image=pil_image,
                confidence_threshold=confidence_threshold,
            )

            result = {
                "objects": [
                    {"label": d.label, "confidence": round(d.confidence, 4), "bbox": list(d.bbox)}
                    for d in detections
                ],
                "image_size": list(image_size),
            }
            if output_annotated:
                result["annotated_image"] = _draw_annotated_image(pil_image, detections)
            logger.info(f"[vision.detect_objects] backend={backend.name} detected {len(detections)} objects")
            return ToolResult(success=True, data=result)
        except ValueError as e:
            return ToolResult(success=False, data=None, error=str(e))
        except FileNotFoundError as e:
            return ToolResult(success=False, data=None, error=str(e))
        except NotImplementedError as e:
            return ToolResult(success=False, data=None, error=str(e))
        except Exception as e:
            logger.exception(f"[vision.detect_objects] Failed: {e}")
            return ToolResult(success=False, data=None, error=str(e))
