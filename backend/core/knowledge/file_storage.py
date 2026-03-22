"""
文件存储管理
负责保存原始文档到本地文件系统
"""
from pathlib import Path
from typing import Optional
from log import logger


class FileStorage:
    """
    文件存储管理器
    
    存储结构：
    data/
    └── knowledge_bases/
        └── kb_xxx/
            └── raw/
                ├── doc_xxx.pdf
                ├── doc_yyy.docx
    """
    
    @staticmethod
    def get_kb_storage_path(kb_id: str) -> Path:
        """获取知识库的存储目录"""
        root = Path(__file__).resolve().parents[3]
        storage_dir = root / "backend" / "data" / "knowledge_bases" / kb_id / "raw"
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir
    
    @staticmethod
    def save_file(kb_id: str, doc_id: str, file_content: bytes, filename: str) -> Path:
        """
        保存文件
        
        Args:
            kb_id: 知识库 ID
            doc_id: 文档 ID
            file_content: 文件内容（bytes）
            filename: 原始文件名
            
        Returns:
            保存后的文件路径
        """
        storage_dir = FileStorage.get_kb_storage_path(kb_id)
        
        # 保留原始扩展名
        ext = Path(filename).suffix
        saved_filename = f"{doc_id}{ext}"
        file_path = storage_dir / saved_filename
        
        # 写入文件
        with open(file_path, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"[FileStorage] Saved file: {file_path}")
        return file_path
    
    @staticmethod
    def get_file_path(kb_id: str, doc_id: str, filename: str) -> Optional[Path]:
        """
        获取文件路径
        
        Args:
            kb_id: 知识库 ID
            doc_id: 文档 ID
            filename: 原始文件名
            
        Returns:
            文件路径，如果不存在则返回 None
        """
        storage_dir = FileStorage.get_kb_storage_path(kb_id)
        ext = Path(filename).suffix
        file_path = storage_dir / f"{doc_id}{ext}"
        
        if file_path.exists():
            return file_path
        return None
    
    @staticmethod
    def delete_file(kb_id: str, doc_id: str, filename: str) -> bool:
        """删除文件"""
        file_path = FileStorage.get_file_path(kb_id, doc_id, filename)
        if file_path and file_path.exists():
            file_path.unlink()
            logger.info(f"[FileStorage] Deleted file: {file_path}")
            return True
        return False
