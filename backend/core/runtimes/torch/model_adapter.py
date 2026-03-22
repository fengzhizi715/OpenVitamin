"""
ModelAdapter 抽象层

每个 VLM 架构（InternVL、Qwen-VL 等）实现一个 Adapter，负责：
- 加载 tokenizer / model / processor
- 将 VLMRequest 转换为模型输入
- 调用 model.generate()
- 将输出转回 VLMResponse
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

try:
    from PIL import Image
except ImportError:
    Image = None


class ModelAdapter(ABC):
    """
    VLM 模型适配器抽象基类

    Runtime 不感知具体模型结构，仅依赖 Adapter 完成加载与推理。
    """

    @abstractmethod
    def load(self, model_dir: Path, options: Dict[str, Any]) -> None:
        """
        加载 tokenizer、model、processor

        Args:
            model_dir: 模型目录（含 model.json manifest）
            options: 从 manifest 解析的配置（torch_dtype, device, 等）
        """
        pass

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, Any]],
        images: Optional[List[Union[str, bytes, "Image.Image"]]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        stop: Optional[List[str]] = None,
        **kwargs
    ) -> str:
        """
        执行生成

        Args:
            messages: [{"role":"system"|"user"|"assistant", "content": str | content_array}]
            images: 图像列表，按 user 消息中图像出现顺序对应
            max_tokens, temperature, top_p, stop: 生成参数

        Returns:
            生成的文本
        """
        pass

    @abstractmethod
    def unload(self) -> None:
        """释放模型资源"""
        pass

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """是否已加载"""
        pass

    def health(self) -> Dict[str, Any]:
        """健康检查"""
        return {"status": "ok" if self.is_loaded else "not_loaded"}
