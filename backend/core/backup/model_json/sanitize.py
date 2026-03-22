"""
model.json 备份：model_id 安全化，用于路径与文件名。
规范：`:` → `_`，`/` → `_`，其余仅保留 [a-zA-Z0-9_.-]。
"""
import re


def sanitize_model_id(model_id: str) -> str:
    """
    将 model_id 转为可用于路径/文件名的安全字符串。
    规范：冒号、斜杠替换为下划线，仅保留字母数字及 _ . -
    """
    if not model_id or not isinstance(model_id, str):
        return "_"
    s = model_id.strip()
    s = s.replace(":", "_").replace("/", "_")
    s = re.sub(r"[^a-zA-Z0-9_.-]", "_", s)
    return s or "_"
