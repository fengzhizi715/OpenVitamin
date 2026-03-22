"""
知识库状态定义
用于避免循环导入
"""


class DocumentStatus:
    """文档状态"""
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    CHUNKING = "CHUNKING"
    CHUNKED = "CHUNKED"
    EMBEDDING = "EMBEDDING"
    INDEXED = "INDEXED"
    FAILED_PARSE = "FAILED_PARSE"
    FAILED_EMBED = "FAILED_EMBED"


class KnowledgeBaseStatus:
    """知识库状态"""
    READY = "READY"           # 就绪，所有文档已索引
    INDEXING = "INDEXING"     # 有文档正在索引
    ERROR = "ERROR"           # 有文档索引失败
    EMPTY = "EMPTY"           # 无文档
