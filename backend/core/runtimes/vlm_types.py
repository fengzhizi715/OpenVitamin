"""
VLM 统一请求/响应类型

与 llama.cpp create_chat_completion 行为对齐，供 VLMRuntime.generate() 使用。
"""

from typing import List, Optional, Union, Literal, Dict, Any
from pydantic import BaseModel, Field

try:
    from PIL import Image
except ImportError:
    Image = None


# --- 与 core.types 对齐的消息结构 ---
class ImageInput(BaseModel):
    """图像输入：支持本地路径、bytes、PIL.Image"""
    path: Optional[str] = None
    bytes_data: Optional[bytes] = None
    pil_image: Optional[Any] = None  # PIL.Image.Image

    class Config:
        arbitrary_types_allowed = True


class VLMGenerationConfig(BaseModel):
    """生成配置，与 llama.cpp 参数命名对齐"""
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=1.0, ge=0, le=1)
    stop: Optional[List[str]] = Field(default=None)
    frequency_penalty: float = Field(default=0.0, ge=-2, le=2)
    presence_penalty: float = Field(default=0.0, ge=-2, le=2)


class VLMRequest(BaseModel):
    """
    VLM 统一请求

    - messages: 多轮对话，与 OpenAI/llama.cpp 格式一致
    - images: 可选，当 content 中未内联 image_url 时，按顺序对应 user 消息中的图像位置
    - generation_config: 生成参数
    """
    messages: List[Dict[str, Any]] = Field(..., description="消息列表，role: system|user|assistant, content: str 或 content array")
    images: Optional[List[Any]] = Field(default=None, description="图像列表：路径 / bytes / PIL.Image")
    generation_config: Optional[VLMGenerationConfig] = Field(default_factory=VLMGenerationConfig)

    class Config:
        arbitrary_types_allowed = True


class VLMResponse(BaseModel):
    """
    VLM 统一响应，与 llama.cpp create_chat_completion 结构一致
    """
    id: str = Field(default="")
    object: str = Field(default="chat.completion")
    created: int = Field(default=0)
    model: str = Field(default="")
    choices: List[Dict[str, Any]] = Field(default_factory=list)  # [{"message": {"role":"assistant","content":"..."}, "finish_reason":"stop"}]
    usage: Optional[Dict[str, int]] = Field(default=None)  # {"prompt_tokens": N, "completion_tokens": M, "total_tokens": N+M}
