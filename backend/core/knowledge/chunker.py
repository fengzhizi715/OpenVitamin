"""
文档切分器（Chunker）
实现基于 token 的智能切分
"""
from __future__ import annotations

from typing import List, Dict, Any
from dataclasses import dataclass
import uuid
from log import logger


@dataclass
class Chunk:
    """Chunk 数据结构"""
    chunk_id: str
    doc_id: str
    text: str
    meta: Dict[str, Any]  # page, start, end, etc.
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "meta": self.meta,
        }


class Chunker:
    """
    文档切分器
    
    v1 策略：
    - Chunk Size: 500 tokens（默认）
    - Overlap: 50 tokens（默认）
    - 不跨文档
    - 尽量不跨段落
    """
    
    def __init__(self, chunk_size: int = 500, overlap: int = 50):
        """
        Args:
            chunk_size: Chunk 大小（tokens）
            overlap: 重叠大小（tokens）
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
    
    def chunk_document(self, doc_id: str, pages: List[Dict[str, Any]]) -> List[Chunk]:
        """
        切分文档
        
        Args:
            doc_id: 文档 ID
            pages: 页面列表，每个页面包含 {"page": int, "text": str}
            
        Returns:
            Chunk 列表
        """
        chunks = []
        
        # 合并所有页面文本
        full_text = "\n\n".join(page["text"] for page in pages)
        
        # 简单实现：按字符数估算 tokens（1 token ≈ 4 chars）
        # 后续可以集成 tiktoken 或 transformers tokenizer 进行精确计算
        char_per_token = 4
        chunk_chars = self.chunk_size * char_per_token
        overlap_chars = self.overlap * char_per_token
        
        # 按段落分割（尽量不跨段落）
        paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
        
        current_chunk_text = ""
        current_chunk_start = 0
        
        for para in paragraphs:
            para_chars = len(para)
            
            # 如果当前 chunk + 新段落超过大小
            if len(current_chunk_text) + para_chars > chunk_chars and current_chunk_text:
                # 保存当前 chunk
                chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
                chunks.append(Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    text=current_chunk_text.strip(),
                    meta={
                        "start": current_chunk_start,
                        "end": current_chunk_start + len(current_chunk_text),
                    }
                ))
                
                # 开始新 chunk，保留 overlap
                overlap_text = current_chunk_text[-overlap_chars:] if len(current_chunk_text) > overlap_chars else current_chunk_text
                current_chunk_text = overlap_text + "\n\n" + para
                current_chunk_start = current_chunk_start + len(current_chunk_text) - len(overlap_text) - len(para) - 2
            else:
                # 添加到当前 chunk
                if current_chunk_text:
                    current_chunk_text += "\n\n" + para
                else:
                    current_chunk_text = para
                    # 估算起始位置（简化实现）
                    current_chunk_start = sum(len(p["text"]) for p in pages if p["text"] in full_text[:full_text.find(para)])
        
        # 保存最后一个 chunk
        if current_chunk_text.strip():
            chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
            chunks.append(Chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                text=current_chunk_text.strip(),
                meta={
                    "start": current_chunk_start,
                    "end": current_chunk_start + len(current_chunk_text),
                }
            ))
        
        logger.info(f"[Chunker] Created {len(chunks)} chunks from document {doc_id}")
        return chunks
