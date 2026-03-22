"""
RAG Context Retrieval for Agent Runtime
Retrieves relevant context from knowledge bases for agent execution
"""
import json
import hashlib
from typing import List, Dict, Any, Optional
from log import logger
from core.knowledge.knowledge_base_store import KnowledgeBaseStore, KnowledgeBaseConfig
from config.settings import settings

# Global KB store instance
_kb_store: Optional[KnowledgeBaseStore] = None

def get_kb_store() -> KnowledgeBaseStore:
    """Get or create the knowledge base store singleton"""
    global _kb_store
    if _kb_store is None:
        try:
            from pathlib import Path
            if settings.db_path:
                db_path = Path(settings.db_path)
            else:
                # Use default path consistent with other stores
                root = Path(__file__).resolve().parents[2]
                db_path = root / "data" / "platform.db"
            _kb_store = KnowledgeBaseStore(
                KnowledgeBaseConfig(
                    db_path=db_path,
                    embedding_dim=settings.memory_embedding_dim
                )
            )
            logger.info("[RAGRetrieval] KnowledgeBaseStore initialized")
        except Exception as e:
            logger.warning(f"[RAGRetrieval] Failed to initialize KnowledgeBaseStore: {e}")
            _kb_store = None
    return _kb_store


class RAGRetrieval:
    """
    RAG Context Retrieval Helper
    
    Provides methods to retrieve relevant context from knowledge bases
    for agent execution.
    """
    
    def __init__(self):
        self.kb_store = get_kb_store()
    
    async def retrieve_context(
        self,
        query: str,
        knowledge_base_ids: List[str],
        top_k: int = 5,
        max_distance: Optional[float] = None
    ) -> str:
        """
        Retrieve relevant context from knowledge bases
        
        Args:
            query: The query to search for
            knowledge_base_ids: List of knowledge base IDs to search in
            top_k: Number of results to return
            max_distance: Maximum distance threshold for filtering
            
        Returns:
            Formatted context string for the agent
        """
        if not knowledge_base_ids:
            return ""
            
        if not self.kb_store:
            logger.warning("[RAGRetrieval] KB store not available")
            return ""
        
        try:
            # Check if vector search is available
            if not getattr(self.kb_store, '_vec_available', False):
                logger.debug("[RAGRetrieval] sqlite-vec not available, skipping RAG")
                return ""
            
            # Get embedding for the query
            query_embedding = self._get_query_embedding(query)
            if not query_embedding:
                logger.warning("[RAGRetrieval] Failed to generate query embedding")
                return ""
            
            # Search in knowledge bases
            results = self.kb_store.search_chunks_multi_kb(
                knowledge_base_ids=knowledge_base_ids,
                query_embedding=query_embedding,
                limit=top_k,
                max_distance=max_distance
            )
            
            if not results:
                logger.debug(f"[RAGRetrieval] No results found for query")
                return ""
            
            # Format results as context
            context_parts = [f"Retrieved Context (from {len(results)} sources):"]
            for i, result in enumerate(results, 1):
                source = result.get('doc_source', 'Unknown')
                content = result.get('content', '')
                distance = result.get('distance', 0)
                
                context_parts.append(f"\n--- Source {i} ({source}, relevance: {1-distance:.2f}) ---")
                context_parts.append(content[:1000])  # Limit content length
            
            context = '\n'.join(context_parts)
            logger.info(f"[RAGRetrieval] Retrieved {len(results)} chunks for query")
            
            return context
            
        except Exception as e:
            logger.error(f"[RAGRetrieval] Error retrieving context: {e}")
            return ""
    
    def _get_query_embedding(self, query: str) -> Optional[List[float]]:
        """
        Generate embedding for query
        
        Note: This is a placeholder. In production, this should call
        an embedding model API.
        """
        try:
            logger.debug("[RAGRetrieval] Using placeholder embedding (not semantic)")
            
            # Return a simple hash-based vector for testing
            # This is NOT semantic, just a placeholder
            hash_obj = hashlib.md5(query.encode())
            hash_bytes = hash_obj.digest()
            
            # Create a 512-dimensional vector from hash
            vector = []
            for i in range(512):
                byte_val = hash_bytes[i % len(hash_bytes)] if hash_bytes else 0
                vector.append(byte_val / 255.0)
            
            return vector
            
        except Exception as e:
            logger.error(f"[RAGRetrieval] Error generating embedding: {e}")
            return None
    
    async def get_knowledge_base_info(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific knowledge base"""
        if not self.kb_store:
            return None
            
        try:
            return self.kb_store.get_knowledge_base(kb_id)
        except Exception as e:
            logger.error(f"[RAGRetrieval] Error getting KB info: {e}")
            return None


# Global retrieval instance
_rag_retrieval: Optional[RAGRetrieval] = None

def get_rag_retrieval() -> RAGRetrieval:
    """Get or create the RAG retrieval singleton"""
    global _rag_retrieval
    if _rag_retrieval is None:
        _rag_retrieval = RAGRetrieval()
    return _rag_retrieval
