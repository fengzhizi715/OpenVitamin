from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from typing import List, Dict, Any

# ONNX Runtime is optional
try:
    import onnxruntime as ort
    HAS_ONNXRUNTIME = True
except ImportError:
    HAS_ONNXRUNTIME = False
    ort = None

# Transformers is optional
try:
    from transformers import AutoTokenizer
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    AutoTokenizer = None

from .base import EmbeddingRuntime


class OnnxEmbeddingRuntime(EmbeddingRuntime):
    """
    Embedding Runtime v1
    - ONNX Runtime
    - HuggingFace tokenizer
    - Mean Pooling
    - Optional L2 normalization
    """
    
    def __init__(
        self,
        model_path: str,
        tokenizer_name: str,
        embedding_dim: int,
        max_tokens: int = 512,
        pooling: str = "mean",
        normalize: bool = True,
        providers: List[str] | None = None,
    ):
        self._closed = False
        self.model_path = model_path
        self.embedding_dim = embedding_dim
        self.max_tokens = max_tokens
        self.pooling = pooling
        self.normalize = normalize

        if not HAS_TRANSFORMERS:
            raise RuntimeError(
                "transformers is not installed. "
                "Install it with: pip install transformers"
            )

        self.providers = providers or ["CPUExecutionProvider"]

        # Load tokenizer
        # Default: local-only (local-first). To allow downloading from HF, set:
        #   AI_PLATFORM_ALLOW_TOKENIZER_DOWNLOAD=1
        allow_download = os.getenv("AI_PLATFORM_ALLOW_TOKENIZER_DOWNLOAD", "").strip().lower() in {"1", "true", "yes"}
        local_files_only = not allow_download

        candidates: List[str] = []

        # 1) explicit local path
        try:
            if tokenizer_name and Path(tokenizer_name).expanduser().exists():
                candidates.append(str(Path(tokenizer_name).expanduser()))
        except Exception:
            pass

        # 2) model directory (common packaging approach)
        model_dir = Path(model_path).expanduser().resolve().parent
        if any((model_dir / f).exists() for f in ["tokenizer.json", "vocab.txt", "tokenizer_config.json", "special_tokens_map.json"]):
            candidates.append(str(model_dir))

        # 3) known HF namespace heuristic (no-op when local_files_only=True and not cached)
        if tokenizer_name and ("/" not in tokenizer_name) and tokenizer_name.startswith("bge-"):
            candidates.append(f"BAAI/{tokenizer_name}")

        # 4) original value (could be HF repo id, or already cached)
        if tokenizer_name:
            candidates.append(tokenizer_name)

        last_err: Exception | None = None
        self.tokenizer = None
        for cand in dict.fromkeys(candidates):  # preserve order, unique
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    cand,
                    use_fast=True,
                    trust_remote_code=True,
                    local_files_only=local_files_only,
                )
                break
            except Exception as e:
                last_err = e

        if self.tokenizer is None:
            raise ValueError(
                "Failed to load tokenizer for embedding model. "
                "This platform defaults to local-only tokenizer loading. "
                f"Tried: {candidates}. "
                "Fix options: (1) put tokenizer files next to the ONNX model and set metadata.tokenizer to that folder; "
                "(2) set AI_PLATFORM_ALLOW_TOKENIZER_DOWNLOAD=1 to allow downloading from HuggingFace (if network is available). "
                f"Last error: {last_err}"
            )

        # Load ONNX session
        if not HAS_ONNXRUNTIME:
            raise RuntimeError(
                "onnxruntime is not installed. "
                "Install it with: pip install onnxruntime"
            )
        self.session = ort.InferenceSession(
            model_path,
            providers=self.providers,
        )

        # Cache input/output names
        self.input_names = [i.name for i in self.session.get_inputs()]
        self.output_names = [o.name for o in self.session.get_outputs()]

    # =========================
    # Public API
    # =========================

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a batch of texts
        """
        if self._closed or self.session is None:
            raise RuntimeError("Embedding runtime is closed. Create a new runtime instance to embed texts.")
        if not texts:
            return []

        inputs = self._tokenize(texts)
        outputs = self._forward(inputs)
        embeddings = self._pool(outputs, inputs["attention_mask"])

        if self.normalize:
            embeddings = self._l2_normalize(embeddings)

        return embeddings.tolist()

    def close(self) -> None:
        """
        Best-effort release of heavy resources.

        Notes:
        - onnxruntime.InferenceSession does not provide a documented `close()` in all versions;
          releasing Python references + gc is the most reliable cross-version approach.
        - This is mainly useful when the process stays alive (e.g. dev server) and we want to drop memory.
        """
        if self._closed:
            return
        self._closed = True
        try:
            # Drop references first
            self.session = None  # type: ignore[assignment]
            self.tokenizer = None  # type: ignore[assignment]
            self.input_names = []  # type: ignore[assignment]
            self.output_names = []  # type: ignore[assignment]
        finally:
            import gc
            gc.collect()

    # =========================
    # Internal
    # =========================

    def _tokenize(self, texts: List[str]) -> Dict[str, np.ndarray]:
        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_tokens,
            return_tensors="np",
        )

        input_ids = encoded["input_ids"].astype(np.int64)
        attention_mask = encoded["attention_mask"].astype(np.int64)

        out: Dict[str, np.ndarray] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }

        # Some ONNX exports (e.g. BERT-style) require token_type_ids.
        # If the tokenizer doesn't provide it, default to zeros.
        if "token_type_ids" in self.input_names:
            token_type_ids = encoded.get("token_type_ids")
            if token_type_ids is None:
                token_type_ids = np.zeros_like(input_ids)
            out["token_type_ids"] = token_type_ids.astype(np.int64)

        return out

    def _forward(self, inputs: Dict[str, np.ndarray]) -> np.ndarray:
        ort_inputs = {
            name: inputs[name]
            for name in self.input_names
            if name in inputs
        }

        outputs = self.session.run(self.output_names, ort_inputs)

        # 通常 embedding 模型的第一个输出是 last_hidden_state
        return outputs[0]

    def _pool(
        self,
        last_hidden_state: np.ndarray,
        attention_mask: np.ndarray,
    ) -> np.ndarray:
        """
        Mean Pooling
        """
        if self.pooling != "mean":
            raise ValueError(f"Unsupported pooling method: {self.pooling}")

        mask = attention_mask[..., None]
        masked_embeddings = last_hidden_state * mask

        sum_embeddings = masked_embeddings.sum(axis=1)
        token_count = mask.sum(axis=1).clip(min=1)

        return sum_embeddings / token_count

    def _l2_normalize(self, embeddings: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / np.clip(norm, 1e-12, None)

    # =========================
    # Runtime metadata
    # =========================

    def health(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "embedding_dim": self.embedding_dim,
            "pooling": self.pooling,
            "normalize": self.normalize,
            "providers": self.providers,
        }
