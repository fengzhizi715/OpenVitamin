"""
vision.detect_objects Tool 的 Schema 与 Manifest
"""

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "image": {
            "type": "string",
            "description": "Image input: base64 data URL (data:image/xxx;base64,...) or file path relative to workspace",
        },
        "confidence_threshold": {
            "type": "number",
            "default": 0.25,
            "description": "Detection confidence threshold (0-1)",
        },
        "output_annotated_image": {
            "type": "boolean",
            "default": True,
            "description": "When true, draw bboxes and labels on image and return as base64 data URL (annotated_image)",
        },
        "backend": {
            "type": "string",
            "enum": ["yolov8", "yolov11", "yolov26", "onnx"],
            "description": "YOLO backend (advanced). Default: yolov8",
        },
    },
    "required": ["image"],
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "confidence": {"type": "number"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Normalized bbox [x1, y1, x2, y2]",
                    },
                },
            },
        },
        "image_size": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "annotated_image": {
            "type": "string",
            "description": "Base64 data URL of annotated image (when output_annotated_image=true)",
        },
    },
}
