"""
LM Studio 模型代理实现
"""
import httpx
from core.agents.openai_compatible_agent import OpenAICompatibleAgent


class LMStudioAgent(OpenAICompatibleAgent):
    """
    LM Studio 适配器
    默认地址: http://localhost:1234/v1
    """

    def __init__(self, base_url: str = "http://127.0.0.1:1234/v1", api_key: str = "lm-studio"):
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            backend_name="lmstudio"
        )

    def model_info(self) -> dict:
        info = super().model_info()
        info.update({
            "description": "LM Studio Local Inference",
            "device": "local"
        })
        return info

    async def _pre_process_payload(self, payload: dict) -> dict:
        """
        LM Studio 自动修正模型名
        如果用户发送的是 'lmstudio'，尝试从后端获取实际加载的模型名
        """
        if payload.get("model") != "lmstudio":
            return payload

        try:
            # 简化连接测试
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/models")
                if resp.status_code == 200:
                    data = resp.json()
                    # 获取第一个加载的模型 ID
                    if "data" in data and len(data["data"]) > 0:
                        real_model = data["data"][0]["id"]
                        payload["model"] = real_model
        except Exception as e:
            print(f"DEBUG: LM Studio auto-detect failed: {str(e)}")
            # 忽略获取失败，继续尝试使用原始 model 名
            pass
        
        return payload
