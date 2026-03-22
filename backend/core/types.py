"""
统一的数据类型定义
所有模型后端都基于这些类型进行交互
"""
from pydantic import BaseModel, Field, model_validator
from typing import List, Literal, Optional, AsyncIterator, Union

# 消息角色（含 tool：用于 tool/skill 输出，表示环境观察而非用户意图）
Role = Literal["system", "user", "assistant", "tool"]


class MessageContentItem(BaseModel):
    """消息内容项（用于多模态消息）"""
    type: Literal["text", "image_url"]
    text: Optional[str] = None
    image_url: Optional[dict] = None
    
    @model_validator(mode='after')
    def validate_content_item(self):
        if self.type == "text" and not self.text:
            raise ValueError("Text content item must have 'text' field")
        if self.type == "image_url" and not self.image_url:
            raise ValueError("Image URL content item must have 'image_url' field")
        return self


class Message(BaseModel):
    """聊天消息"""
    role: Role
    content: Union[str, List[MessageContentItem]]


class RAGConfig(BaseModel):
    """RAG 配置"""
    knowledge_base_id: Optional[str] = Field(default=None, description="知识库 ID（单个）")
    knowledge_base_ids: Optional[List[str]] = Field(default=None, description="知识库 ID 列表（多个）")
    top_k: int = Field(default=5, ge=1, le=50, description="检索的 chunk 数量")
    # 注意：这里的 score_threshold 实际是“distance 阈值”(max_distance)：distance <= threshold 才保留
    # embedding 默认做了 L2 normalize（单位向量），因此常见距离范围大致在 0~2
    score_threshold: Optional[float] = Field(default=1.2, ge=0, le=2, description="距离阈值（distance<=threshold 才返回；默认1.2，范围0-2）")
    max_context_tokens: int = Field(default=2000, ge=100, le=10000, description="RAG 上下文最大 token 数（用于截断）")
    
    @model_validator(mode='after')
    def validate_knowledge_base(self):
        """验证至少提供一个知识库 ID"""
        if not self.knowledge_base_id and not self.knowledge_base_ids:
            raise ValueError("Either knowledge_base_id or knowledge_base_ids must be provided")
        return self


class ChatCompletionRequest(BaseModel):
    """统一的聊天完成请求"""
    model: Optional[str] = Field(default=None, description="模型 ID (精确匹配优先级最高)")
    model_require: Optional[str] = Field(default=None, description="模型要求/能力 (如 'vision', 'fast')")
    
    messages: List[Message] = Field(..., description="消息列表")
    temperature: float = Field(default=0.7, ge=0, le=2, description="温度参数")
    top_p: float = Field(default=1.0, ge=0, le=1, description="Top-P 参数")
    max_tokens: int = Field(default=2048, ge=1, le=8192, description="最大生成 token 数（默认 2048，上限 8192）")
    stream: bool = Field(default=False, description="是否流式响应")
    
    # 高级控制参数
    system_prompt: Optional[str] = Field(default=None, description="覆盖默认的系统提示词")
    max_history_messages: Optional[int] = Field(default=None, description="覆盖默认的历史消息条数")
    
    # RAG 配置（可选）
    rag: Optional[RAGConfig] = Field(default=None, description="RAG 知识库检索配置")


class ChatCompletionResponse(BaseModel):
    """聊天完成响应"""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[dict]
    usage: Optional[dict] = None


# =========================
# RAG Trace Models
# =========================

class RAGTraceChunk(BaseModel):
    """RAG Trace Chunk"""
    doc_id: Optional[str] = None
    doc_name: Optional[str] = None
    chunk_id: Optional[str] = None
    score: float
    content: str
    content_tokens: Optional[int] = None
    rank: int


class RAGTrace(BaseModel):
    """RAG Trace"""
    id: str
    session_id: str
    message_id: str
    rag_id: str
    rag_type: str
    query: str
    embedding_model: str
    vector_store: str
    top_k: int
    retrieved_count: int
    score_threshold: Optional[float] = None
    injected_token_count: Optional[int] = None
    finalized: bool = False
    created_at: str
    chunks: List[RAGTraceChunk] = []


class RAGTraceResponse(BaseModel):
    """RAG Trace 响应（供前端使用）"""
    rag_used: bool
    trace: Optional[RAGTrace] = None
