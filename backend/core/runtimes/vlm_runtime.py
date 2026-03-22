"""
VLMRuntime: Vision-Language Model Runtime Abstraction

独立的多模态推理抽象，专门处理 image + text → text 的端到端推理任务。
不继承 LLMRuntime，保持接口克制，面向未来稳定扩展。
"""

from abc import ABC, abstractmethod
from typing import Union, Optional, Dict, Any
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    # Type stub for when PIL is not available
    class Image:
        pass


class VLMRuntime(ABC):
    """
    Vision-Language Model Runtime 抽象基类
    
    设计原则：
    1. 独立抽象，不继承 LLMRuntime
    2. 专注 image + text → text 推理
    3. 接口极简，避免未来扩展破坏性变更
    4. 支持多种后端实现（llama.cpp、vLLM、API等）
    """
    
    @abstractmethod
    async def initialize(self, model_path: Union[str, Path], **kwargs) -> None:
        """
        初始化模型运行时
        
        Args:
            model_path: 模型文件路径（本地路径或标识符）
            **kwargs: 后端特定配置参数
            
        设计理由：
        - 异步初始化支持大模型加载
        - Union[str, Path] 兼容不同后端的路径表示
        - **kwargs 为后端特定配置保留扩展空间
        - 不返回值，通过异常表示初始化失败
        """
        pass
    
    @abstractmethod
    async def infer(
        self,
        image: Union[Image.Image, bytes],
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        执行单次多模态推理
        
        Args:
            image: 输入图像（PIL Image 对象或原始字节数据）
            prompt: 文本提示词
            temperature: 采样温度（None 表示使用默认值）
            max_tokens: 最大生成 token 数（None 表示使用默认值）
            **kwargs: 后端特定推理参数
            
        Returns:
            str: 模型生成的文本结果
            
        设计理由：
        - image 支持 PIL 和 bytes 两种格式，适应不同输入源
        - prompt 作为必需参数，明确文本输入
        - temperature/max_tokens 为核心推理控制参数
        - **kwargs 为后端特定功能保留（如 top_p、frequency_penalty 等）
        - 返回纯文本，不暴露内部表示（vision tokens/embeddings）
        """
        pass
    
    @abstractmethod
    async def unload(self) -> None:
        """
        卸载模型资源
        
        设计理由：
        - 显式资源管理，避免内存泄漏
        - 异步支持 GPU 资源释放
        - 不接受参数，保持接口简洁
        """
        pass
    
    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """
        检查模型是否已加载
        
        Returns:
            bool: 模型加载状态
            
        设计理由：
        - 只读属性，避免状态不一致
        - 用于健康检查和资源管理
        """
        pass
    
    @property
    @abstractmethod
    def model_info(self) -> Dict[str, Any]:
        """
        获取模型元信息
        
        Returns:
            Dict[str, Any]: 包含模型名称、版本、能力等信息的字典
            
        设计理由：
        - 提供运行时模型信息查询
        - 字典格式灵活，可扩展
        - 不包含敏感配置信息
        """
        pass


# 使用示例（仅为说明，非实际代码）:
"""
class LlamaCppVLMRuntime(VLMRuntime):
    async def initialize(self, model_path: Union[str, Path], **kwargs) -> None:
        # llama.cpp 特定初始化逻辑
        pass
        
    async def infer(
        self,
        image: Union[Image.Image, bytes],
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        # 多模态推理实现
        pass
        
    async def unload(self) -> None:
        # 资源清理
        pass
        
    @property
    def is_loaded(self) -> bool:
        # 状态检查
        pass
        
    @property
    def model_info(self) -> Dict[str, Any]:
        # 返回模型信息
        pass
"""