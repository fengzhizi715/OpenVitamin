import json
from pathlib import Path
from typing import List, Optional
from log import logger
from core.models.descriptor import ModelDescriptor
from core.models.registry import get_model_registry


def _format_size(size_bytes: int) -> str:
    if size_bytes > 1024**3:
        return f"{size_bytes / 1024**3:.1f} GB"
    return f"{size_bytes / 1024**2:.1f} MB"


def _estimate_path_size(path: Path) -> str:
    try:
        if path.is_file():
            return _format_size(path.stat().st_size)
        if path.is_dir():
            total = 0
            for child in path.rglob("*"):
                if child.is_file():
                    total += child.stat().st_size
            return _format_size(total) if total > 0 else "Unknown"
    except Exception:
        return "Unknown"
    return "Unknown"

class LocalScanner:
    """
    本地模型扫描器 (扫描 ~/.local-ai/models)
    加载包含 model.json 的目录
    """
    def __init__(self, models_dir: Optional[str] = None):
        if models_dir:
            self.models_dir = Path(models_dir).expanduser()
        else:
            from core.system.settings_store import get_system_settings_store
            from config.settings import settings
            
            store = get_system_settings_store()
            # 优先从数据库读取用户修改后的路径，否则使用配置文件默认路径
            configured_dir = store.get_setting("dataDirectory") or settings.local_model_directory
            self.models_dir = Path(configured_dir).expanduser()
            
        self.registry = get_model_registry()

    async def scan(self) -> List[ModelDescriptor]:
        if not self.models_dir.exists():
            logger.debug(f"[LocalScanner] Directory not found: {self.models_dir}")
            return []

        logger.info(f"[LocalScanner] Scanning models from {self.models_dir}")
        descriptors = []
        
        # 1. 扫描分层目录 (llm/、embedding/、vlm/、asr/、perception/、image_generation/)
        layered_dirs = ["llm", "embedding", "vlm", "asr", "perception", "image_generation"]
        for sub_name in layered_dirs:
            sub_dir = self.models_dir / sub_name
            if sub_dir.exists() and sub_dir.is_dir():
                for item in sub_dir.iterdir():
                    if item.is_dir():
                        desc = self._load_model_from_dir(item, model_type_hint=sub_name)
                        if desc:
                            descriptors.append(desc)
                            
        # 2. 扫描根目录下的所有子目录 (向下兼容旧版平铺结构)
        # 排除已经处理过的分层目录
        for item in self.models_dir.iterdir():
            if not item.is_dir() or item.name in layered_dirs:
                continue
            
            # 如果该目录下有 model.json，说明是一个模型目录
            if (item / "model.json").exists():
                # 检查是否已经在前面的分层扫描中处理过 (避免重复注册)
                if not any(d.provider_model_id == item.name for d in descriptors):
                    desc = self._load_model_from_dir(item)
                    if desc:
                        descriptors.append(desc)
        
        return descriptors

    def _load_model_from_dir(self, item: Path, model_type_hint: Optional[str] = None) -> Optional[ModelDescriptor]:
        """从目录加载模型描述符"""
        manifest_path = item / "model.json"
        if not manifest_path.exists():
            return None
            
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            
            # 1. 基础校验
            model_id = manifest.get("model_id")
            if not model_id:
                logger.warning(f"[LocalScanner] Missing model_id in {manifest_path}")
                return None
            
            model_type = manifest.get("model_type") or model_type_hint or "llm"
            
            # 2. 字段映射
            rel_path = manifest.get("path")
            abs_path = item / rel_path if rel_path else None
            
            # 获取文件大小
            size_str = "Unknown"
            if abs_path and abs_path.exists():
                size_str = _estimate_path_size(abs_path)
            
            # 3. Embedding 特有校验与处理
            metadata = manifest.get("metadata", {})
            # 兼容旧版的 default_params
            if not metadata and "default_params" in manifest:
                metadata = manifest["default_params"]
                
            if model_type == "embedding":
                # 校验 Embedding 特有字段
                if "embedding" not in manifest.get("capabilities", []):
                    manifest.setdefault("capabilities", []).append("embedding")
                
                # 检查 metadata 里的 embedding_dim
                if "embedding_dim" not in metadata:
                    logger.warning(f"[LocalScanner] Embedding model {model_id} missing embedding_dim in metadata")
            
            # 记录绝对路径到 metadata
            metadata["path"] = str(abs_path) if abs_path else ""
            default_format = "gguf"
            if model_type == "perception":
                default_format = "pytorch"
            elif model_type == "image_generation":
                default_format = "safetensors"
            metadata["format"] = manifest.get("format", default_format)

            # tokenizer id 兼容：很多 embedding 模型会写成 "bge-small-zh-v1.5"（缺少组织名）
            # 为了避免 transformers 尝试访问不存在的 repo，这里对 bge-* 做一次确定性映射
            if model_type == "embedding":
                tok = (metadata.get("tokenizer") or "").strip()
                if tok and ("/" not in tok) and tok.startswith("bge-"):
                    metadata["tokenizer"] = f"BAAI/{tok}"
            
            # 获取量化信息
            quant = manifest.get("quantization") or manifest.get("quant") or manifest.get("quants")
            
            _runtime_default = {
                "llm": "llama.cpp", "vlm": "llama.cpp", "embedding": "onnx",
                "asr": "torch", "perception": "torch", "image_generation": "torch",
            }
            _caps_default = {
                "llm": ["chat"], "vlm": ["chat", "vision"], "embedding": ["embedding"],
                "asr": ["asr"], "perception": ["object_detection"], "image_generation": ["text_to_image"],
            }
            caps = manifest.get("capabilities")
            if caps is None and model_type == "perception" and metadata.get("task") == "instance_segmentation":
                caps = ["instance_segmentation"]
            if caps is None:
                caps = _caps_default.get(model_type, ["chat"])
            descriptor = ModelDescriptor(
                id=f"local:{model_id}",
                name=manifest.get("name", model_id),
                model_type=model_type,
                provider="local",
                provider_model_id=model_id,
                runtime=manifest.get("runtime", _runtime_default.get(model_type, "llama.cpp")),
                capabilities=caps,
                quantization=quant,
                size=size_str,
                format=metadata["format"].upper(),
                source=manifest.get("source", "Local Disk"),
                description=manifest.get("description", f"Local {model_type} model: {model_id}"),
                tags=manifest.get("tags", ["local", model_type]),
                metadata=metadata
            )
            
            self.registry.upsert_model(descriptor)
            logger.info(f"[LocalScanner] Registered local {model_type} model: {model_id}")
            return descriptor
            
        except Exception as e:
            logger.error(f"[LocalScanner] Failed to load model from {item}: {e}")
            return None
