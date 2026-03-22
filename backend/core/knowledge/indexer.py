"""
知识库索引器
负责完整的索引流程：Parse → Chunk → Embed → Store
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from pathlib import Path
import uuid
import asyncio
from log import logger
from core.knowledge.document_parser import DocumentParser, ParsedDocument
from core.knowledge.chunker import Chunker
from core.knowledge.knowledge_base_store import KnowledgeBaseStore
from core.knowledge.status import DocumentStatus, KnowledgeBaseStatus
from core.runtimes.factory import get_runtime_factory
from core.models.registry import get_model_registry
from core.inference import get_inference_client


class KnowledgeBaseIndexer:
    """
    知识库索引器
    
    负责：
    1. 文档解析
    2. 文档切分
    3. 向量化
    4. 存储到 sqlite-vec
    """
    
    def __init__(
        self,
        kb_store: KnowledgeBaseStore,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        self.kb_store = kb_store
        self.chunker = Chunker(chunk_size=chunk_size, overlap=chunk_overlap)
        self.runtime_factory = get_runtime_factory()
        self.model_registry = get_model_registry()
    
    def _get_embedding_dim(self, embedding_model_id: str) -> int:
        """从 embedding model 获取维度"""
        embedding_model = self.model_registry.get_model(embedding_model_id)
        if not embedding_model:
            raise ValueError(f"Embedding model '{embedding_model_id}' not found")
        
        # 从 metadata 中获取 embedding_dim
        embedding_dim = embedding_model.metadata.get("embedding_dim", 512)
        return embedding_dim
    
    def index_document(
        self,
        kb_id: str,
        doc_id: str,
        file_path: Path,
        doc_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        索引文档（完整流程）
        
        Args:
            kb_id: 知识库 ID
            doc_id: 文档 ID
            file_path: 文件路径
            doc_type: 文档类型
            
        Returns:
            索引结果
        """
        try:
            asyncio.get_running_loop()
            raise RuntimeError("index_document() cannot run inside an event loop; use index_document_async()")
        except RuntimeError as e:
            if "no running event loop" not in str(e).lower():
                raise
        return asyncio.run(self.index_document_async(kb_id=kb_id, doc_id=doc_id, file_path=file_path, doc_type=doc_type))

    async def index_document_async(
        self,
        kb_id: str,
        doc_id: str,
        file_path: Path,
        doc_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """异步索引文档（Embed 通过 Inference Gateway）"""
        result = {
            "doc_id": doc_id,
            "status": DocumentStatus.UPLOADED,
            "chunks_created": 0,
            "error": None,
        }
        
        try:
            # 1. Parse
            logger.info(f"[Indexer] Parsing document: {file_path}")
            result["status"] = DocumentStatus.PARSING
            
            parsed_doc = DocumentParser.parse(file_path, doc_type)
            result["status"] = DocumentStatus.PARSED
            
            # 2. Chunk
            logger.info(f"[Indexer] Chunking document: {doc_id}")
            result["status"] = DocumentStatus.CHUNKING
            
            chunks = self.chunker.chunk_document(
                doc_id=doc_id,
                pages=[{"page": p.page, "text": p.text} for p in parsed_doc.pages]
            )
            result["status"] = DocumentStatus.CHUNKED
            result["chunks_created"] = len(chunks)
            
            # 3. Get embedding model
            kb_info = self.kb_store.get_knowledge_base(kb_id)
            if not kb_info:
                raise ValueError(f"Knowledge base '{kb_id}' not found")
            
            embedding_model_id = kb_info["embedding_model_id"]
            embedding_model = self.model_registry.get_model(embedding_model_id)
            if not embedding_model:
                raise ValueError(f"Embedding model '{embedding_model_id}' not found")

            # Ensure KnowledgeBaseStore vec0 dimension matches embedding model BEFORE insert
            expected_dim = self._get_embedding_dim(embedding_model_id)
            self.kb_store._ensure_vec_table_dimension(kb_id, expected_dim)
            
            # 4. Embed & Store
            logger.info(f"[Indexer] Embedding and storing {len(chunks)} chunks")
            result["status"] = DocumentStatus.EMBEDDING

            # 批量生成 embeddings
            chunk_texts = [chunk.text for chunk in chunks]
            if not chunk_texts:
                raise ValueError("No chunks to embed")

            client = get_inference_client()
            embed_resp = await client.embed(
                model=embedding_model.id,
                input_text=chunk_texts,
                metadata={
                    "caller": "KnowledgeBaseIndexer.embed_chunks",
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                },
            )
            embeddings = embed_resp.embeddings
            
            if not embeddings:
                raise ValueError("Failed to generate embeddings")
            
            if len(embeddings) != len(chunks):
                raise ValueError(f"Embedding count mismatch: expected {len(chunks)}, got {len(embeddings)}")
            
            # 验证 embedding 维度
            if embeddings:
                actual_dim = len(embeddings[0])
                expected_dim = self._get_embedding_dim(embedding_model_id)
                if actual_dim != expected_dim:
                    logger.warning(
                        f"[Indexer] Embedding dimension mismatch: model metadata says {expected_dim}, "
                        f"but runtime returned {actual_dim}. Updating config to {actual_dim}."
                    )
                    # 更新 KnowledgeBaseStore 的 embedding_dim 以匹配实际维度
                    self.kb_store._ensure_vec_table_dimension(kb_id, actual_dim)
            
            # 存储到 sqlite-vec
            for chunk, embedding in zip(chunks, embeddings):
                try:
                    self.kb_store.insert_chunk(
                        knowledge_base_id=kb_id,
                        document_id=doc_id,
                        chunk_id=chunk.chunk_id,
                        content=chunk.text,
                        embedding=embedding,
                    )
                except Exception as e:
                    logger.error(f"[Indexer] Failed to insert chunk {chunk.chunk_id}: {e}", exc_info=True)
                    raise
            
            result["status"] = DocumentStatus.INDEXED
            logger.info(f"[Indexer] Successfully indexed document {doc_id}: {len(chunks)} chunks")
            
        except Exception as e:
            logger.error(f"[Indexer] Failed to index document {doc_id}: {e}", exc_info=True)
            result["error"] = str(e)
            if result["status"] in [DocumentStatus.UPLOADED, DocumentStatus.PARSING]:
                result["status"] = DocumentStatus.FAILED_PARSE
            else:
                result["status"] = DocumentStatus.FAILED_EMBED
        
        return result
