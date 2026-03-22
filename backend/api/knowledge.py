"""
Knowledge Base API 端点
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks, Request
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
import uuid
import shutil
from log import logger
from config.settings import settings
from core.knowledge.knowledge_base_store import KnowledgeBaseStore, KnowledgeBaseConfig
from core.knowledge.file_storage import FileStorage
from core.knowledge.indexer import KnowledgeBaseIndexer
from core.knowledge.status import DocumentStatus
from core.utils.user_context import get_user_id, UserAccessDeniedError, ResourceNotFoundError

router = APIRouter(prefix="/api", tags=["knowledge"])

# 确定统一数据库路径
_db_path = (
    Path(__file__).resolve().parents[1] / "data" / "platform.db"
    if not settings.db_path
    else Path(settings.db_path)
)

# 初始化 KnowledgeBaseStore
_kb_store = KnowledgeBaseStore(
    KnowledgeBaseConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
    )
)


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    description: Optional[str] = None
    embedding_model_id: str
    chunk_size: int = 512
    chunk_overlap: int = 50


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    score_threshold: Optional[float] = None


@router.post("/knowledge-bases")
async def create_knowledge_base(req: CreateKnowledgeBaseRequest, request: Request):
    """创建知识库"""
    try:
        user_id = get_user_id(request)
        
        kb_id = _kb_store.create_knowledge_base(
            name=req.name,
            description=req.description,
            embedding_model_id=req.embedding_model_id,
            user_id=user_id,
        )
        return {
            "id": kb_id,
            "name": req.name,
            "description": req.description,
            "embedding_model_id": req.embedding_model_id,
        }
    except Exception as e:
        logger.error(f"Failed to create knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases")
async def list_knowledge_bases(request: Request):
    """列出用户的所有知识库"""
    try:
        user_id = get_user_id(request)
        kbs = _kb_store.list_knowledge_bases(user_id=user_id)
        return {"object": "list", "data": kbs}
    except Exception as e:
        logger.error(f"Failed to list knowledge bases: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_id}")
async def get_knowledge_base(kb_id: str, request: Request):
    """获取知识库信息"""
    try:
        user_id = get_user_id(request)
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 计算磁盘使用量
        disk_size_info = _kb_store.get_knowledge_base_disk_size(kb_id)
        kb["disk_size"] = disk_size_info
        
        return kb
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class UpdateKnowledgeBaseRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@router.patch("/knowledge-bases/{kb_id}")
async def update_knowledge_base(kb_id: str, req: UpdateKnowledgeBaseRequest, request: Request):
    """更新知识库信息"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 更新知识库
        success = _kb_store.update_knowledge_base(
            kb_id=kb_id,
            name=req.name,
            description=req.description,
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update knowledge base")
        
        # 返回更新后的知识库信息
        updated_kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        return updated_kb
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/knowledge-bases/{kb_id}")
async def delete_knowledge_base(kb_id: str, request: Request):
    """删除知识库（包含物理文件删除）"""
    try:
        user_id = get_user_id(request)
        
        # 获取知识库下的所有文档，用于删除物理文件
        # 先获取 KB 信息（可能抛出权限或不存在异常）
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        docs = _kb_store.list_documents(kb_id, user_id=user_id)
        
        # 删除所有文档的物理文件
        for doc in docs:
            if doc.get("file_path"):
                try:
                    file_path = Path(doc["file_path"])
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"Deleted file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete file {doc.get('file_path')}: {e}")
        
        # 删除知识库目录（如果存在）
        try:
            kb_storage_dir = FileStorage.get_kb_storage_path(kb_id).parent  # parent 是 kb_id 目录
            if kb_storage_dir.exists():
                shutil.rmtree(kb_storage_dir)
                logger.info(f"Deleted knowledge base directory: {kb_storage_dir}")
        except Exception as e:
            logger.warning(f"Failed to delete knowledge base directory: {e}")
        
        # 删除数据库记录（级联删除文档和 chunks）
        _kb_store.delete_knowledge_base(kb_id, user_id=user_id)
        
        logger.info(f"Deleted knowledge base: {kb_id}")
        return {"deleted": True, "id": kb_id}
    except UserAccessDeniedError as e:
        logger.warning(f"Access denied: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/embedding")
async def list_embedding_models():
    """列出所有 embedding 模型"""
    try:
        from core.models.registry import get_model_registry
        registry = get_model_registry()
        all_models = registry.list_models()
        
        # 过滤出 embedding 模型
        embedding_models = [
            {
                "id": m.id,
                "name": m.name,
                "embedding_dim": m.metadata.get("embedding_dim", 512),
            }
            for m in all_models
            if m.model_type == "embedding"
        ]
        
        return {"object": "list", "data": embedding_models}
    except Exception as e:
        logger.error(f"Failed to list embedding models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_id}/stats")
async def get_knowledge_base_stats(kb_id: str, request: Request):
    """获取知识库统计信息"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 获取文档统计
        docs = _kb_store.list_documents(kb_id, user_id=user_id)
        doc_count = len(docs)
        
        # 按状态统计文档
        status_counts = {}
        for doc in docs:
            status = doc.get("status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # 获取 chunk 统计
        chunk_count = _kb_store.get_chunk_count(kb_id)
        
        # 获取磁盘使用量
        disk_size_info = _kb_store.get_knowledge_base_disk_size(kb_id)
        
        return {
            "knowledge_base_id": kb_id,
            "document_count": doc_count,
            "document_status_breakdown": status_counts,
            "chunk_count": chunk_count,
            "vector_count": chunk_count,  # chunk_count = vector_count
            "disk_size": disk_size_info,
            "embedding_model_id": kb["embedding_model_id"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get knowledge base stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_id}/documents")
async def list_documents(kb_id: str, request: Request):
    """列出知识库下的所有文档"""
    try:
        user_id = get_user_id(request)
        docs = _kb_store.list_documents(kb_id, user_id=user_id)
        # 确保状态和 chunks 字段存在
        for doc in docs:
            doc["status"] = doc.get("status", "UPLOADED")
            doc["chunks"] = doc.get("chunks_count", 0)
        return {"object": "list", "data": docs}
    except Exception as e:
        logger.error(f"Failed to list documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}")
async def get_document(kb_id: str, doc_id: str, request: Request):
    """获取文档详细信息"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 获取文档信息
        doc = _kb_store.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # 验证文档属于该知识库
        if doc["knowledge_base_id"] != kb_id:
            raise HTTPException(status_code=400, detail="Document does not belong to this knowledge base")
        
        # 添加额外统计信息
        doc["status"] = doc.get("status", "UPLOADED")
        doc["chunks"] = doc.get("chunks_count", 0)
        
        return doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def index_document_background(
    kb_id: str,
    doc_id: str,
    file_path: Path,
    doc_type: Optional[str],
):
    """后台索引任务（同步函数，由 BackgroundTasks 调用）"""
    try:
        # 获取知识库信息，确保使用正确的 embedding 维度
        kb_info = _kb_store.get_knowledge_base(kb_id)
        if not kb_info:
            raise ValueError(f"Knowledge base '{kb_id}' not found")
        
        # 从 embedding model 获取正确的维度
        from core.models.registry import get_model_registry
        model_registry = get_model_registry()
        embedding_model = model_registry.get_model(kb_info["embedding_model_id"])
        if embedding_model:
            actual_embedding_dim = embedding_model.metadata.get("embedding_dim", 512)
            # 更新 KnowledgeBaseStore 的配置
            if _kb_store.config.embedding_dim != actual_embedding_dim:
                logger.info(
                    f"[Indexer] Updating embedding_dim from {_kb_store.config.embedding_dim} "
                    f"to {actual_embedding_dim} for KB {kb_id}"
                )
                _kb_store.config.embedding_dim = actual_embedding_dim

            # Ensure vec0 table dimension matches (may recreate table)
            _kb_store._ensure_vec_table_dimension(kb_id, actual_embedding_dim)
        
        indexer = KnowledgeBaseIndexer(_kb_store)
        result = indexer.index_document(
            kb_id=kb_id,
            doc_id=doc_id,
            file_path=file_path,
            doc_type=doc_type,
        )
        
        # 更新文档状态
        _kb_store.update_document_status(
            doc_id=doc_id,
            status=result["status"],
            chunks_count=result.get("chunks_created", 0),
            error_message=result.get("error"),
        )
        logger.info(f"Background indexing completed for {doc_id}: {result['status']}")
    except Exception as e:
        logger.error(f"Background indexing failed for {doc_id}: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        _kb_store.update_document_status(
            doc_id=doc_id,
            status=DocumentStatus.FAILED_EMBED,
            error_message=str(e),
        )


@router.post("/knowledge-bases/{kb_id}/documents")
async def upload_document(
    kb_id: str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    request: Request = None,
):
    """上传文档到知识库并启动索引流程"""
    try:
        user_id = get_user_id(request) if request else "default"
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 验证文件类型
        allowed_extensions = {'.pdf', '.txt', '.md', '.docx'}
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")
        
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}. Supported types: PDF, TXT, MD, DOCX")
        
        # 验证文件大小（20MB）
        content = await file.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size exceeds 20MB limit")
        
        # 创建文档记录
        doc_id = _kb_store.create_document(
            knowledge_base_id=kb_id,
            source=file.filename,
            doc_type=file_ext[1:] if file_ext else None,
            status=DocumentStatus.UPLOADED,
            user_id=user_id,
        )
        
        # 保存文件到本地存储
        file_path = FileStorage.save_file(kb_id, doc_id, content, file.filename)
        
        # 更新文档记录中的文件路径
        _kb_store.update_document_status(doc_id, DocumentStatus.UPLOADED)
        
        # 使用 BackgroundTasks 启动索引流程（不阻塞响应）
        background_tasks.add_task(
            index_document_background,
            kb_id=kb_id,
            doc_id=doc_id,
            file_path=file_path,
            doc_type=file_ext[1:] if file_ext else None,
        )
        
        logger.info(f"Document uploaded: {doc_id} to KB {kb_id}, indexing started")
        
        return {
            "id": doc_id,
            "knowledge_base_id": kb_id,
            "source": file.filename,
            "status": DocumentStatus.UPLOADED,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: str, doc_id: str, request: Request):
    """删除文档"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 获取文档信息（用于删除文件）
        doc = _kb_store.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # 验证文档属于该知识库
        if doc["knowledge_base_id"] != kb_id:
            raise HTTPException(status_code=400, detail="Document does not belong to this knowledge base")
        
        # 删除 chunks（通过知识库的向量表）
        _kb_store.delete_document_chunks(kb_id, doc_id)
        
        # 删除文件（如果存在）
        if doc.get("file_path"):
            try:
                from pathlib import Path
                file_path = Path(doc["file_path"])
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Deleted file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete file {doc['file_path']}: {e}")
        
        # 删除文档记录
        success = _kb_store.delete_document(doc_id, user_id=user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Document not found")
        
        logger.info(f"Deleted document: {doc_id} from KB {kb_id}")
        
        return {
            "deleted": True,
            "id": doc_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/reindex")
async def reindex_document(
    kb_id: str,
    doc_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    request: Request = None,
):
    """重新索引文档"""
    try:
        user_id = get_user_id(request) if request else "default"
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 获取文档信息
        doc = _kb_store.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # 验证文档属于该知识库
        if doc["knowledge_base_id"] != kb_id:
            raise HTTPException(status_code=400, detail="Document does not belong to this knowledge base")
        
        # 验证文件存在
        if not doc.get("file_path"):
            raise HTTPException(status_code=400, detail="Document file path not found")
        
        file_path = Path(doc["file_path"])
        if not file_path.exists():
            raise HTTPException(status_code=400, detail=f"Document file not found: {file_path}")
        
        # 1. 删除旧的 chunks
        logger.info(f"Deleting old chunks for document {doc_id}")
        _kb_store.delete_document_chunks(kb_id, doc_id)
        
        # 2. 重置文档状态
        _kb_store.update_document_status(
            doc_id=doc_id,
            status=DocumentStatus.UPLOADED,
            chunks_count=0,
            error_message=None,
        )
        
        # 3. 启动后台索引任务
        background_tasks.add_task(
            index_document_background,
            kb_id=kb_id,
            doc_id=doc_id,
            file_path=file_path,
            doc_type=doc.get("doc_type"),
        )
        
        logger.info(f"Re-indexing started for document {doc_id}")
        
        return {
            "id": doc_id,
            "knowledge_base_id": kb_id,
            "status": DocumentStatus.UPLOADED,
            "message": "Re-indexing started",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to re-index document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_id}/chunks")
async def list_chunks(kb_id: str, limit: int = 50, offset: int = 0, document_id: Optional[str] = None, request: Request = None):
    """列出知识库下的所有 chunks"""
    try:
        user_id = get_user_id(request) if request else "default"
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 获取 chunk 数量
        total = _kb_store.get_chunk_count(kb_id)
        
        # 查询 chunks
        chunks = _kb_store.list_chunks(
            knowledge_base_id=kb_id,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
        
        return {
            "object": "list",
            "data": chunks,
            "total": total,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list chunks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/knowledge-bases/{kb_id}/search")
async def search_knowledge_base(kb_id: str, req: SearchRequest, request: Request = None):
    """检索知识库"""
    try:
        user_id = get_user_id(request) if request else "default"
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # 获取 embedding model
        from core.models.registry import get_model_registry
        registry = get_model_registry()
        embedding_model = registry.get_model(kb["embedding_model_id"])
        if not embedding_model:
            raise HTTPException(status_code=500, detail=f"Embedding model '{kb['embedding_model_id']}' not found")
        
        # 从 embedding model 获取实际维度
        actual_embedding_dim = embedding_model.metadata.get("embedding_dim", settings.memory_embedding_dim)
        
        # 使用正确的维度创建 KnowledgeBaseStore 实例
        # 注意：每个知识库有独立的向量表，这里只需要确保该知识库的表存在
        kb_store = KnowledgeBaseStore(
            KnowledgeBaseConfig(
                db_path=_db_path,
                embedding_dim=actual_embedding_dim,
            )
        )
        # 确保知识库的向量表存在且维度正确
        kb_store._ensure_vec_table_dimension(kb_id, actual_embedding_dim)
        
        # 生成 query embedding（通过 Inference Gateway 解耦调用方）
        from core.inference import get_inference_client
        client = get_inference_client()
        embed_resp = await client.embed(
            model=embedding_model.id,
            input_text=[req.query],
            metadata={
                "caller": "api.knowledge.search",
                "kb_id": kb_id,
                "user_id": user_id,
            },
        )
        query_embeddings = embed_resp.embeddings
        if not query_embeddings:
            raise HTTPException(status_code=500, detail="Failed to generate query embedding")
        
        query_embedding = query_embeddings[0]
        
        # 验证 query embedding 维度
        if len(query_embedding) != actual_embedding_dim:
            raise HTTPException(
                status_code=500,
                detail=f"Query embedding dimension mismatch: expected {actual_embedding_dim}, got {len(query_embedding)}"
            )
        
        # 向量检索
        results = kb_store.search_chunks(
            knowledge_base_id=kb_id,
            query_embedding=query_embedding,
            limit=req.top_k,
            max_distance=req.score_threshold,
        )
        
        return {
            "object": "list",
            "data": [
                {
                    "content": content,
                    "distance": distance,
                    "score": 1.0 - distance,  # 转换为相似度分数
                }
                for content, distance in results
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to search knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
