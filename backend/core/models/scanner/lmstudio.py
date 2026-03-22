import httpx
from typing import List
from log import logger
from core.models.descriptor import ModelDescriptor
from core.models.registry import get_model_registry

class LMStudioScanner:
    """
    LM Studio 模型扫描器
    """
    def __init__(self, base_url: str = "http://localhost:1234"):
        self.base_url = base_url
        self.registry = get_model_registry()

    async def scan(self) -> List[ModelDescriptor]:
        """执行扫描并返回发现的模型列表"""
        logger.info(f"[LMStudioScanner] Scanning models from {self.base_url}")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/v1/models")
                if response.status_code != 200:
                    logger.error(f"[LMStudioScanner] Failed to fetch models: {response.status_code}")
                    return []
                
                data = response.json()
                models_data = data.get("data", [])
                
                descriptors = []
                for m in models_data:
                    full_name = m.get("id")
                    # 系统内部 ID 格式: lmstudio:model_id
                    model_id = f"lmstudio:{full_name}"
                    
                    descriptor = ModelDescriptor(
                        id=model_id,
                        name=full_name,
                        provider="lmstudio",
                        provider_model_id=full_name,
                        runtime="lmstudio",
                        base_url=self.base_url,
                        capabilities=["chat"],
                        description=f"LM Studio model: {full_name}",
                        tags=["local", "lmstudio"]
                    )
                    
                    self.registry.upsert_model(descriptor)
                    descriptors.append(descriptor)
                
                logger.info(f"[LMStudioScanner] Successfully registered {len(descriptors)} models")
                return descriptors
                
        except Exception as e:
            # 这里的报错很可能是因为 LM Studio 没启动或者端口不对，属于正常情况
            logger.debug(f"[LMStudioScanner] LM Studio not reachable: {str(e)}")
            return []
