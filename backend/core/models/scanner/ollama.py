import httpx
from typing import List
from log import logger
from core.models.descriptor import ModelDescriptor
from core.models.registry import get_model_registry
from config.settings import settings

class OllamaScanner:
    """
    Ollama 模型扫描器
    通过 Ollama 的本地 API 发现已下载的模型并注册到系统
    """
    def __init__(self, base_url: str = settings.ollama_base_url):
        self.base_url = base_url
        self.registry = get_model_registry()

    async def scan(self) -> List[ModelDescriptor]:
        """执行扫描并返回发现的模型列表"""
        logger.info(f"[OllamaScanner] Scanning models from {self.base_url}")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code != 200:
                    logger.error(f"[OllamaScanner] Failed to fetch models: {response.status_code}")
                    return []
                
                data = response.json()
                models_data = data.get("models", [])
                
                descriptors = []
                for m in models_data:
                    full_name = m.get("name")
                    # 系统内部 ID 格式: ollama:model_name
                    model_id = f"ollama:{full_name}"
                    
                    # 获取文件大小
                    size_bytes = m.get("size", 0)
                    if size_bytes > 1024**3:
                        size_str = f"{size_bytes / 1024**3:.1f} GB"
                    else:
                        size_str = f"{size_bytes / 1024**2:.1f} MB"
                    
                    descriptor = ModelDescriptor(
                        id=model_id,
                        name=full_name,
                        provider="ollama",
                        provider_model_id=full_name,
                        runtime="ollama",
                        base_url=self.base_url,
                        capabilities=["chat"],
                        family=m.get("details", {}).get("family"),
                        quantization=m.get("details", {}).get("quantization_level"),
                        size=size_str,
                        format=m.get("details", {}).get("format", "gguf").upper(),
                        source="Ollama",
                        version=m.get("details", {}).get("parameter_size"),
                        description=f"Ollama local model: {full_name}",
                        tags=["local", "ollama"]
                    )
                    
                    self.registry.upsert_model(descriptor)
                    descriptors.append(descriptor)
                
                # 如果 Ollama 服务可用但没有模型，注册一个占位符模型以表示后端可用
                if not descriptors:
                    logger.info(f"[OllamaScanner] Ollama service is available but no models found. Registering placeholder.")
                    placeholder_id = "ollama:auto"
                    placeholder = ModelDescriptor(
                        id=placeholder_id,
                        name="Ollama (Auto-Detect)",
                        provider="ollama",
                        provider_model_id="auto",
                        runtime="ollama",
                        base_url=self.base_url,
                        capabilities=["chat"],
                        description="Ollama backend is available. Use 'ollama pull <model>' to download models.",
                        tags=["local", "ollama", "placeholder"]
                    )
                    self.registry.upsert_model(placeholder)
                    descriptors.append(placeholder)
                
                logger.info(f"[OllamaScanner] Successfully registered {len(descriptors)} models")
                return descriptors
                
        except httpx.TimeoutException:
            logger.warning(f"[OllamaScanner] Connection timeout to {self.base_url}. Ollama service may not be running.")
            return []
        except httpx.ConnectError:
            logger.warning(f"[OllamaScanner] Cannot connect to {self.base_url}. Ollama service may not be running.")
            return []
        except Exception as e:
            logger.error(f"[OllamaScanner] Error during scan: {str(e)}")
            return []
