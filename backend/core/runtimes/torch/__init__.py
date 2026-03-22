"""
Torch Runtime Modules

基于 PyTorch 的运行时模块：
- TorchVLMRuntime: VLM（视觉语言模型）运行时
- TorchASRRuntime: ASR（自动语音识别）运行时
"""

from .torch_vlm_runtime import TorchVLMRuntime
from .model_adapter import ModelAdapter

# 延迟导入 ASR Runtime（避免在未安装 faster-whisper 时导入失败）
try:
    from .torch_asr_runtime import TorchASRRuntime
    __all__ = ["TorchVLMRuntime", "TorchASRRuntime", "ModelAdapter"]
except ImportError:
    __all__ = ["TorchVLMRuntime", "ModelAdapter"]
