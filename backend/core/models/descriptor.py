from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ModelCapability(BaseModel):
    """模型能力描述"""
    name: str
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ModelDescriptor(BaseModel):
    """
    模型描述符 - 系统的模型一等公民标识
    """
    id: str = Field(..., description="系统内部唯一标识符, 如 'ollama:llama3'")
    name: str = Field(..., description="模型名称, 如 'Llama 3'")
    model_type: str = Field(default="llm", description="模型类型: llm, embedding, vlm, perception, image_generation")
    provider: str = Field(..., description="后端提供商, 如 'ollama', 'lmstudio'")
    provider_model_id: str = Field(..., description="提供商内部的模型ID")
    
    # 运行时信息
    runtime: str = Field(..., description="对应的运行时类型, 如 'ollama', 'openai'")
    base_url: Optional[str] = None
    
    # 能力信息
    capabilities: List[str] = Field(default_factory=list, description="模型能力列表, 如 ['chat', 'vision', 'tool_calling']")
    context_length: int = Field(default=4096, description="上下文长度")
    
    # 硬件/元数据
    device: Optional[str] = Field(None, description="运行设备, 如 'mps', 'cuda', 'cpu'")
    quantization: Optional[str] = Field(None, description="量化级别, 如 'Q4_K_M'")
    size: Optional[str] = Field(None, description="模型大小, 如 '4.9 GB'")
    format: Optional[str] = Field(None, description="模型格式, 如 'GGUF', 'SafeTensors'")
    source: Optional[str] = Field(None, description="模型来源, 如 'Local Disk', 'HuggingFace'")
    family: Optional[str] = None
    version: Optional[str] = None
    
    # UI/展示
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="运行时特定的额外参数")
    
    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
