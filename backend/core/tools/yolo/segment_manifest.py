"""vision.segment_objects Tool 的 Schema"""

SEGMENT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "image": {
            "type": "string",
            "description": "Image input: base64 data URL (data:image/xxx;base64,...) or file path relative to workspace",
        },
        "confidence_threshold": {
            "type": "number",
            "default": 0.4,
            "description": "Segmentation confidence threshold (0-1)",
        },
        "output_annotated_image": {
            "type": "boolean",
            "default": True,
            "description": "When true, draw bboxes and labels on image and return as base64 data URL (annotated_image)",
        },
    },
    "required": ["image"],
}

SEGMENT_OUTPUT_SCHEMA = {
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
                    "mask": {
                        "type": "string",
                        "description": "Base64-encoded PNG of binary mask (optional)",
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
