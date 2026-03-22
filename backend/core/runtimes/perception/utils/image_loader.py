"""
image_loader: 统一图像输入处理

支持：本地文件路径、PIL.Image、numpy.ndarray
输出：torch.Tensor、image_size (width, height)
"""

from pathlib import Path
from typing import Union, Tuple

import numpy as np
import torch

try:
    from PIL import Image
except ImportError:
    Image = None


def load_image(
    image_input: Union[str, Path, "Image.Image", np.ndarray],
) -> Tuple[torch.Tensor, Tuple[int, int]]:
    """
    统一加载图像，输出 torch tensor 与图像尺寸。

    Args:
        image_input: 本地路径、PIL.Image、numpy.ndarray（HWC, RGB, 0~255）

    Returns:
        (tensor, (width, height)): tensor 形状 (1, C, H, W)，float32，值域 0~1
    """
    if isinstance(image_input, (str, Path)):
        arr = _load_from_path(image_input)
    elif Image is not None and isinstance(image_input, Image.Image):
        arr = _pil_to_numpy(image_input)
    elif isinstance(image_input, np.ndarray):
        arr = _validate_numpy(image_input)
    else:
        raise TypeError(
            f"image_input 需为 str/Path/PIL.Image/numpy.ndarray，当前类型: {type(image_input)}"
        )

    tensor, size = _numpy_to_tensor(arr)
    return tensor, size


def _load_from_path(path: Union[str, Path]) -> np.ndarray:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"图像不存在: {path}")
    if Image is None:
        raise ImportError("PIL 未安装，无法从路径加载图像")
    img = Image.open(path).convert("RGB")
    return _pil_to_numpy(img)


def _pil_to_numpy(img: "Image.Image") -> np.ndarray:
    return np.array(img)


def _validate_numpy(arr: np.ndarray) -> np.ndarray:
    if arr.ndim != 3:
        raise ValueError(f"numpy 图像需为 HWC 三维，当前 ndim={arr.ndim}")
    if arr.shape[2] != 3:
        raise ValueError(f"需为 RGB 三通道，当前 channels={arr.shape[2]}")
    arr = arr.astype(np.float32)
    if arr.max() > 1.0:
        arr = arr / 255.0
    return arr


def _numpy_to_tensor(arr: np.ndarray) -> Tuple[torch.Tensor, Tuple[int, int]]:
    # arr: HWC, float32 0~1
    h, w = arr.shape[:2]
    tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)  # (1, C, H, W)
    return tensor.float(), (w, h)
