"""One-off patch: add get_trace_by_id to RAGTraceStore."""
path = "core/rag/trace_store.py"
with open(path) as f:
    content = f.read()

marker = """                ],
            }
    
    def cleanup_old_traces(self, days: int = 7) -> int:"""

addition = """                ],
            }
    
    def get_trace_by_id(self, trace_id: str) -> Optional[Dict[str, Any]]:
        '''通过 trace_id 获取 Trace（前端兜底：message_id 未同步时可用 meta.rag.trace_id 查询）'''
        with self._connect() as conn:
            trace = conn.execute("SELECT * FROM rag_traces WHERE id = ?", (trace_id,)).fetchone()
            if not trace:
                return None
            chunks = conn.execute(
                "SELECT doc_id, doc_name, chunk_id, score, content, content_tokens, rank "
                "FROM rag_trace_chunks WHERE trace_id = ? ORDER BY rank ASC",
                (trace_id,),
            ).fetchall()
            return {
                "id": trace["id"],
                "session_id": trace["session_id"],
                "message_id": trace["message_id"],
                "rag_id": trace["rag_id"],
                "rag_type": trace["rag_type"],
                "query": trace["query"],
                "embedding_model": trace["embedding_model"],
                "vector_store": trace["vector_store"],
                "top_k": trace["top_k"],
                "retrieved_count": trace["retrieved_count"],
                "injected_token_count": trace["injected_token_count"],
                "finalized": bool(trace["finalized"]),
                "created_at": trace["created_at"],
                "chunks": [
                    {
                        "doc_id": c["doc_id"],
                        "doc_name": c["doc_name"],
                        "chunk_id": c["chunk_id"],
                        "score": c["score"],
                        "content": c["content"],
                        "content_tokens": c["content_tokens"],
                        "rank": c["rank"],
                    }
                    for c in chunks
                ],
            }

    def cleanup_old_traces(self, days: int = 7) -> int:"""

if marker not in content:
    raise SystemExit("Marker not found")
content = content.replace(marker, addition, 1)
with open(path, "w") as f:
    f.write(content)
print("Patched: get_trace_by_id added")
